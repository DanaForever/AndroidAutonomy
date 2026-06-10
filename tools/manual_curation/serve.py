#!/usr/bin/env python3
"""Local manual Android data-curation server.

The server is intentionally small and localhost-only. It serves the static
coordinate picker, captures screenshots through ADB, records raw trace actions,
and finalizes successful trajectories under ``training/data/manual_curation``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import tempfile
import time
from http import HTTPStatus
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"


def load_json(path: Path) -> dict[str, Any]:
    with path.open() as f:
        return json.load(f)


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as f:
        json.dump(data, f, indent=2)
        f.write("\n")
        tmp = Path(f.name)
    tmp.replace(path)


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as f:
        header = f.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a valid PNG")
    width, height = struct.unpack(">II", header[16:24])
    return int(width), int(height)


def now_id() -> str:
    return time.strftime("%Y%m%d%H%M%S")


def render_template(template: str, params: dict[str, Any]) -> str:
    try:
        return template.format(**params)
    except KeyError:
        return template


def resolve_task_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a task config with concrete per-instance fields rendered."""
    task = dict(config)
    params = dict(task.get("params") or {})
    task["params"] = params
    if task.get("goal_template"):
        task["goal"] = render_template(str(task["goal_template"]), params)
    if task.get("success_criteria_template"):
        task["success_criteria"] = render_template(str(task["success_criteria_template"]), params)
    rendered_checks = []
    for check in task.get("success_checks", []):
        rendered = dict(check)
        for key in ("label", "command", "expected"):
            if isinstance(rendered.get(key), str):
                rendered[key] = render_template(rendered[key], params)
        rendered_checks.append(rendered)
    task["success_checks"] = rendered_checks
    return task


class CurationState:
    def __init__(
        self,
        *,
        adb: str,
        device: str | None,
        task_name: str,
        task_config: Path,
        out_root: Path,
        host: str,
        port: int,
    ) -> None:
        self.adb = adb
        self.device = device
        self.task_name = task_name
        self.task_config_path = task_config
        self.task = resolve_task_config(load_json(task_config))
        self.out_root = out_root
        self.host = host
        self.port = port
        self.task_root = out_root / task_name
        self.draft_dir = self.task_root / ".draft"
        self.draft_screens = self.draft_dir / "screens"
        self.trajectories_dir = self.task_root / "trajectories"
        self.last_device_status: dict[str, Any] = {}
        self.start_draft()

    @property
    def trace_path(self) -> Path:
        return self.draft_dir / "trace.json"

    def adb_cmd(self, *args: str) -> list[str]:
        cmd = [self.adb]
        if self.device:
            cmd.extend(["-s", self.device])
        cmd.extend(args)
        return cmd

    def run_adb(self, *args: str, timeout: int = 15, binary: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(
            self.adb_cmd(*args),
            check=False,
            capture_output=True,
            timeout=timeout,
            text=not binary,
        )

    def preflight(self) -> dict[str, Any]:
        status: dict[str, Any] = {
            "adb": self.adb,
            "device": self.device,
            "ok": False,
            "error": None,
            "devices": "",
            "wm_size": "",
            "wm_density": "",
        }
        try:
            subprocess.run([self.adb, "start-server"], check=False, capture_output=True, text=True, timeout=10)
            devices = subprocess.run(
                [self.adb, "devices", "-l"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            status["devices"] = devices.stdout.strip()
            attached = [
                line.split()[0]
                for line in devices.stdout.splitlines()[1:]
                if line.strip() and "\tdevice" in line
            ]
            if not self.device:
                if len(attached) == 1:
                    self.device = attached[0]
                    status["device"] = self.device
                elif not attached:
                    status["error"] = "No attached ADB device."
                    self.last_device_status = status
                    return status
                else:
                    status["error"] = f"Multiple devices attached: {', '.join(attached)}. Pass --device."
                    self.last_device_status = status
                    return status
            wait = self.run_adb("wait-for-device", timeout=20)
            if wait.returncode != 0:
                status["error"] = wait.stderr.strip() or wait.stdout.strip() or "adb wait-for-device failed"
                self.last_device_status = status
                return status
            size = self.run_adb("shell", "wm", "size")
            density = self.run_adb("shell", "wm", "density")
            status["wm_size"] = size.stdout.strip()
            status["wm_density"] = density.stdout.strip()
            status["ok"] = size.returncode == 0 and density.returncode == 0
            if not status["ok"]:
                status["error"] = (size.stderr or density.stderr or "wm checks failed").strip()
        except (OSError, subprocess.TimeoutExpired) as e:
            status["error"] = str(e)
        self.last_device_status = status
        return status

    def next_trajectory_id(self) -> str:
        self.trajectories_dir.mkdir(parents=True, exist_ok=True)
        max_seen = -1
        for p in self.trajectories_dir.glob("traj_*"):
            m = re.match(r"traj_(\d+)$", p.name)
            if m:
                max_seen = max(max_seen, int(m.group(1)))
        return f"traj_{max_seen + 1:04d}"

    def saved_count(self) -> int:
        if not self.trajectories_dir.exists():
            return 0
        return sum(1 for p in self.trajectories_dir.glob("traj_*/trace.json") if p.is_file())

    def start_draft(self) -> None:
        self.draft_screens.mkdir(parents=True, exist_ok=True)
        if not self.trace_path.exists():
            trace = {
                "schema_version": "manual_trace_v1",
                "task_name": self.task_name,
                "goal": self.task.get("goal", ""),
                "params": self.task.get("params", {}),
                "trajectory_id": ".draft",
                "budget": self.task.get("budget"),
                "optimal_steps": self.task.get("optimal_steps"),
                "success_criteria": self.task.get("success_criteria", ""),
                "success_checks": self.task.get("success_checks", []),
                "verification": {"success_verified": False, "method": ""},
                "device": {"adb_serial": self.device, "screen_width": None, "screen_height": None},
                "created_at": now_id(),
                "steps": [],
            }
            write_json_atomic(self.trace_path, trace)

    def read_trace(self) -> dict[str, Any]:
        self.start_draft()
        return load_json(self.trace_path)

    def write_trace(self, trace: dict[str, Any]) -> None:
        write_json_atomic(self.trace_path, trace)

    def task_payload(self) -> dict[str, Any]:
        trace = self.read_trace()
        return {
            **self.task,
            "task_name": self.task_name,
            "saved_trajectories": self.saved_count(),
            "current_trajectory_id": trace.get("trajectory_id", ".draft"),
            "out_root": str(self.out_root),
        }

    def capture(self) -> dict[str, Any]:
        self.start_draft()
        trace = self.read_trace()
        step_idx = len(trace.get("steps", []))
        image_name = f"step_{step_idx:03d}.png"
        image_path = self.draft_screens / image_name
        proc = self.run_adb("exec-out", "screencap", "-p", timeout=20, binary=True)
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", "replace") if isinstance(proc.stderr, bytes) else proc.stderr
            raise RuntimeError(stderr.strip() or "screencap failed")
        image_path.write_bytes(proc.stdout)
        width, height = png_dimensions(image_path)
        trace.setdefault("device", {})["adb_serial"] = self.device
        trace["device"]["screen_width"] = width
        trace["device"]["screen_height"] = height
        trace["current_screenshot"] = f"screens/{image_name}"
        self.write_trace(trace)
        return {
            "image_url": f"/files/{self.task_name}/.draft/screens/{image_name}?t={int(time.time() * 1000)}",
            "screenshot": f"screens/{image_name}",
            "width": width,
            "height": height,
            "step_index": step_idx,
        }

    def record_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        trace = self.read_trace()
        steps = trace.setdefault("steps", [])
        step_idx = len(steps)
        screenshot = payload.get("screenshot") or trace.get("current_screenshot")
        action = payload.get("action")
        if not isinstance(action, dict):
            raise ValueError("payload.action must be an object")
        if action.get("type") != "terminate" and not screenshot:
            raise ValueError("non-terminal action requires a screenshot")
        step = {
            "step_index": step_idx,
            "screenshot": screenshot,
            "action": action,
            "adb_command": payload.get("adb_command", ""),
            "human_note": payload.get("human_note", ""),
            "verified": bool(payload.get("verified", False)),
            "created_at": now_id(),
        }
        steps.append(step)
        trace.pop("current_screenshot", None)
        self.write_trace(trace)
        return {"ok": True, "step": step, "trace": trace}

    def delete_step(self, payload: dict[str, Any]) -> dict[str, Any]:
        trace = self.read_trace()
        steps = trace.setdefault("steps", [])
        step_index = payload.get("step_index")
        if not isinstance(step_index, int):
            raise ValueError("step_index must be an integer")
        if step_index < 0 or step_index >= len(steps):
            raise ValueError(f"step_index out of range: {step_index}")
        removed = steps.pop(step_index)
        for i, step in enumerate(steps):
            step["step_index"] = i
        self.write_trace(trace)
        return {"ok": True, "removed": removed, "trace": trace}

    def run_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        command = payload.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command is required")
        cmd = shlex.split(command.strip())
        if cmd[:2] == [self.adb, "shell"]:
            args = cmd[2:]
        elif cmd[:3] == [self.adb, "-s", self.device or ""]:
            args = cmd[4:] if len(cmd) >= 4 and cmd[3] == "shell" else cmd[3:]
        elif cmd[0:2] == ["adb", "shell"]:
            args = cmd[2:]
        else:
            raise ValueError("only adb shell commands are allowed")
        proc = self.run_adb("shell", *args, timeout=20)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }

    def validate_for_save(self, trace: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        steps = trace.get("steps", [])
        if not trace.get("task_name") or not trace.get("goal"):
            errors.append("task metadata is missing")
        if not steps:
            errors.append("trajectory has no steps")
            return errors
        terminals = [s for s in steps if s.get("action", {}).get("type") == "terminate"]
        if len(terminals) != 1 or steps[-1].get("action", {}).get("type") != "terminate":
            errors.append("trajectory must end with exactly one terminal action")
        elif steps[-1].get("action", {}).get("status") != "success":
            errors.append("terminal action must be terminate(success)")
        non_terminal = [s for s in steps if s.get("action", {}).get("type") != "terminate"]
        if not non_terminal:
            errors.append("trajectory needs at least one non-terminal action")
        width = trace.get("device", {}).get("screen_width")
        height = trace.get("device", {}).get("screen_height")
        for s in non_terminal:
            if not s.get("screenshot"):
                errors.append(f"step {s.get('step_index')} missing screenshot")
            action = s.get("action", {})
            atype = action.get("type")
            if atype in {"click", "long_press"}:
                if not _coord(action.get("pixel")) or not _coord(action.get("qwen")):
                    errors.append(f"step {s.get('step_index')} has invalid coordinate")
            if atype == "swipe":
                if not _coord_pair(action.get("pixel")) or not _coord_pair(action.get("qwen")):
                    errors.append(f"step {s.get('step_index')} has invalid swipe coordinates")
        for s in terminals:
            if not s.get("screenshot"):
                errors.append(f"terminal step {s.get('step_index')} missing final-state screenshot")
        if width is None or height is None:
            errors.append("device screen dimensions are missing")
        verification = trace.get("verification", {})
        if not verification.get("success_verified"):
            errors.append("verification.success_verified must be true")
        return errors

    def save_trajectory(self, payload: dict[str, Any]) -> dict[str, Any]:
        trace = self.read_trace()
        verification = payload.get("verification")
        if isinstance(verification, dict):
            trace["verification"] = verification
            self.write_trace(trace)
        errors = self.validate_for_save(trace)
        if errors:
            return {"ok": False, "errors": errors, "trace": trace}
        traj_id = self.next_trajectory_id()
        trace["trajectory_id"] = traj_id
        write_json_atomic(self.trace_path, trace)
        dest = self.trajectories_dir / traj_id
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            raise RuntimeError(f"{dest} already exists")
        shutil.move(str(self.draft_dir), str(dest))
        self.start_draft()
        return {"ok": True, "trajectory_id": traj_id, "saved_trajectories": self.saved_count()}

    def new_trajectory(self, discard: bool = False) -> dict[str, Any]:
        if self.draft_dir.exists() and discard:
            shutil.rmtree(self.draft_dir)
        self.start_draft()
        return {"ok": True, "trace": self.read_trace(), "saved_trajectories": self.saved_count()}


def _coord(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
    )


def _coord_pair(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and _coord(value[0]) and _coord(value[1])


class Handler(BaseHTTPRequestHandler):
    state: CurationState

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text: str, status: int = 200, content_type: str = "text/plain") -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/":
                self.serve_file(STATIC_DIR / "index.html", "text/html")
            elif path == "/app.js":
                self.serve_file(STATIC_DIR / "app.js", "application/javascript")
            elif path == "/styles.css":
                self.serve_file(STATIC_DIR / "styles.css", "text/css")
            elif path == "/device_status":
                self.send_json(self.state.preflight())
            elif path == "/task":
                self.send_json(self.state.task_payload())
            elif path == "/trace":
                self.send_json(self.state.read_trace())
            elif path.startswith("/files/"):
                self.serve_data_file(path)
            else:
                self.send_text("not found", HTTPStatus.NOT_FOUND)
        except Exception as e:  # pragma: no cover - surfaced to UI.
            self.send_json({"ok": False, "error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            payload = self.read_json()
            if parsed.path == "/capture":
                self.send_json({"ok": True, **self.state.capture()})
            elif parsed.path == "/record_action":
                self.send_json(self.state.record_action(payload))
            elif parsed.path == "/delete_step":
                self.send_json(self.state.delete_step(payload))
            elif parsed.path == "/run_adb":
                self.send_json(self.state.run_command(payload))
            elif parsed.path == "/save_trajectory":
                self.send_json(self.state.save_trajectory(payload))
            elif parsed.path == "/new_trajectory":
                self.send_json(self.state.new_trajectory(discard=bool(payload.get("discard", False))))
            else:
                self.send_text("not found", HTTPStatus.NOT_FOUND)
        except Exception as e:  # pragma: no cover - surfaced to UI.
            self.send_json({"ok": False, "error": str(e)}, HTTPStatus.BAD_REQUEST)

    def serve_file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_data_file(self, request_path: str) -> None:
        rel = unquote(request_path[len("/files/"):])
        target = (self.state.out_root / rel).resolve()
        if not str(target).startswith(str(self.state.out_root.resolve())):
            self.send_text("forbidden", HTTPStatus.FORBIDDEN)
            return
        if not target.is_file():
            self.send_text("not found", HTTPStatus.NOT_FOUND)
            return
        self.serve_file(target, "image/png")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--adb", default=os.environ.get("ADB", "adb"))
    p.add_argument("--device", default=os.environ.get("ANDROID_SERIAL"))
    p.add_argument("--task", required=True)
    p.add_argument("--task-config", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("training/data/manual_curation/raw"))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_root = args.out if args.out.is_absolute() else ROOT / args.out
    task_config = args.task_config if args.task_config.is_absolute() else ROOT / args.task_config
    Handler.state = CurationState(
        adb=args.adb,
        device=args.device,
        task_name=args.task,
        task_config=task_config,
        out_root=out_root,
        host=args.host,
        port=args.port,
    )
    status = Handler.state.preflight()
    if not status.get("ok"):
        print(f"ADB preflight warning: {status.get('error')}")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Manual curation UI: http://{args.host}:{args.port}")
    print(f"Task: {args.task}")
    print(f"Output: {out_root}")
    server.serve_forever()


if __name__ == "__main__":
    main()
