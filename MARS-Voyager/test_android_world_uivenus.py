#!/usr/bin/env python3
"""Android World Parallel Evaluation Script - UI-Venus Navigator

Mirrors test_android_world_maiui.py but swaps the agent for a thin
BaseEvalAgent wrapper around the UI-Venus navigator. Talks to an
OpenAI-compatible vLLM endpoint serving the UI-Venus model, reusing
UI-Venus's MOBILE_USER_PROMPT and parse_answer from
UI-Venus/models/navigation/utils.py.
"""

import argparse
import base64
import io
import json
import math
import multiprocessing as mp
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

os.environ['GRPC_VERBOSITY'] = 'ERROR'
os.environ['GRPC_TRACE'] = 'none'

SCRIPT_DIR = Path(__file__).parent.absolute()
PROJECT_ROOT = SCRIPT_DIR
ANDROID_WORLD_PATH = PROJECT_ROOT / "androidworld"
ANDROID_ENV_PATH = PROJECT_ROOT / "android_env"
UIVENUS_ROOT = PROJECT_ROOT.parent / "UI-Venus"

sys.path.insert(0, str(ANDROID_WORLD_PATH))
sys.path.insert(0, str(ANDROID_ENV_PATH))
sys.path.insert(0, str(UIVENUS_ROOT))


def setup_logging(log_file: str):
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    class Tee:
        def __init__(self, *files):
            self.files = files
        def write(self, obj):
            for f in self.files:
                f.write(obj)
                f.flush()
        def flush(self):
            for f in self.files:
                f.flush()

    log_fp = open(log_file, 'w', encoding='utf-8')
    sys.stdout = Tee(sys.stdout, log_fp)
    sys.stderr = Tee(sys.stderr, log_fp)
    return log_file


def split_tasks(tasks: List[str], num_workers: int) -> List[List[str]]:
    chunks = [[] for _ in range(num_workers)]
    for i, task in enumerate(tasks):
        chunks[i % num_workers].append(task)
    return [c for c in chunks if c]


def get_all_tasks() -> List[str]:
    from android_world import registry
    reg = registry.TaskRegistry().get_registry(family='android_world')
    return list(reg.keys())


def _worker_reap_zombies():
    try:
        while True:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
    except (ChildProcessError, OSError):
        pass


def _zombie_reaper_thread(stop_event):
    while not stop_event.is_set():
        _worker_reap_zombies()
        stop_event.wait(5)


# ---------------------------------------------------------------------------
# UI-Venus eval agent wrapper
# ---------------------------------------------------------------------------

def _smart_resize(h: int, w: int, factor: int = 28,
                  min_pixels: int = 3136, max_pixels: int = 12845056) -> Tuple[int, int]:
    """Replicates qwen_vl_utils.smart_resize (returns (h, w) resized)."""
    if h < factor or w < factor:
        raise ValueError(f'image too small: ({h}, {w})')
    def round_by_factor(n: float, f: int) -> int:
        return max(f, round(n / f) * f)
    h_bar = round_by_factor(h, factor)
    w_bar = round_by_factor(w, factor)
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((h * w) / max_pixels)
        h_bar = max(factor, math.floor(h / beta / factor) * factor)
        w_bar = max(factor, math.floor(w / beta / factor) * factor)
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (h * w))
        h_bar = math.ceil(h * beta / factor) * factor
        w_bar = math.ceil(w * beta / factor) * factor
    return h_bar, w_bar


# Maps free-form names the model may emit onto keys/patterns in
# android_world's _PATTERN_TO_ACTIVITY (see androidworld/android_world/env/adb_utils.py).
# Keys on the left are lowercased; values on the right are any string whose
# lowercase prefix matches a pattern in _PATTERN_TO_ACTIVITY.
_UIVENUS_APP_ALIASES: Dict[str, str] = {
    'file manager': 'files',
    'file': 'files',
    'files app': 'files',
    'documents': 'files',
    'file explorer': 'files',
    'gallery': 'simple gallery pro',
    'photos': 'simple gallery pro',
    'simple gallery': 'simple gallery pro',
    'calendar': 'simple calendar pro',
    'camera app': 'camera',
    'phone': 'dialer',
    'clock app': 'clock',
    'alarm': 'clock',
    'alarm clock': 'clock',
    'audio recorder app': 'audio recorder',
    'recorder': 'audio recorder',
    'voice recorder': 'audio recorder',
    'sms': 'simple sms messenger',
    'messaging': 'messages',
    'text messages': 'messages',
    'markor notes': 'markor',
    'notes': 'markor',
    'browser': 'chrome',
    'web browser': 'chrome',
    'internet': 'chrome',
    'maps': 'google maps',
    'setting': 'settings',
    'android settings': 'settings',
}


def _build_ui_venus_eval_agent(env, agent_cfg: Dict[str, Any], llm_cfg: Dict[str, Any]):
    """Construct a BaseEvalAgent that wraps a UI-Venus HTTP navigator."""
    import time as _time
    from PIL import Image
    import numpy as np
    import requests
    from absl import logging

    from android_world.env import json_action
    from eval.agents.base_agent import BaseEvalAgent, AgentStepResult

    # UI-Venus prompt + parser (reuses their mobile prompt and regex parser).
    from models.navigation.utils import (
        parse_answer,
        get_user_prompt,
    )

    class UIVenusEvalAgent(BaseEvalAgent):
        """BaseEvalAgent wrapper that talks to UI-Venus over an OpenAI-compatible endpoint."""

        def __init__(
            self,
            env,
            llm_base_url: str,
            model_name: str,
            name: str = 'UIVenus-Agent',
            wait_after_action_seconds: float = 2.0,
            history_length: int = 5,
            prompt_type: str = 'mobile',
            temperature: float = 0.0,
            top_p: float = 1.0,
            max_tokens: int = 2048,
            max_pixels: int = 12845056,
            min_pixels: int = 3136,
            request_timeout: float = 120.0,
        ):
            super().__init__(env, name, transition_pause=1.0)
            # Normalize base_url: chat/completions lives under /v1.
            base = llm_base_url.rstrip('/')
            if not base.endswith('/v1'):
                base = base + '/v1'
            self.chat_url = f'{base}/chat/completions'
            self.model_name = model_name
            self.temperature = temperature
            self.top_p = top_p
            self.max_tokens = max_tokens
            self.max_pixels = max_pixels
            self.min_pixels = min_pixels
            self.request_timeout = request_timeout
            self.history_length = max(0, int(history_length))
            self.prompt_template = get_user_prompt(prompt_type)
            self.wait_after_action_seconds = wait_after_action_seconds
            self.history: List[Dict[str, str]] = []

        def reset(self, go_home: bool = False) -> None:
            super().reset(go_home)
            self.history = []

        def _build_query(self, goal: str) -> str:
            if not self.history:
                prev = ''
            else:
                recent = self.history[-self.history_length:] if self.history_length > 0 else []
                prev = '\n'.join(
                    f"Step {i}: <think>{s['think']}</think><action>{s['action']}</action>"
                    for i, s in enumerate(recent)
                )
            return self.prompt_template.format(user_task=goal, previous_actions=prev)

        def _call_model(self, img_b64: str, user_text: str) -> Optional[str]:
            payload = {
                'model': self.model_name,
                'temperature': self.temperature,
                'top_p': self.top_p,
                'max_tokens': self.max_tokens,
                'messages': [
                    {'role': 'system', 'content': 'You are a helpful assistant.'},
                    {'role': 'user', 'content': [
                        {'type': 'text', 'text': user_text},
                        {'type': 'image_url',
                         'image_url': {'url': f'data:image/png;base64,{img_b64}'}},
                    ]},
                ],
            }
            try:
                r = requests.post(self.chat_url, json=payload,
                                  timeout=self.request_timeout)
                r.raise_for_status()
                return r.json()['choices'][0]['message']['content']
            except Exception as e:
                print(f'[UI-Venus] LLM call failed ({self.chat_url}): {e}', flush=True)
                return None

        @staticmethod
        def _extract_tag(tag: str, text: str) -> str:
            import re
            m = re.search(rf'<{tag}>(.*?)</{tag}>', text, re.DOTALL)
            return m.group(1).strip() if m else ''

        def step(self, goal: str, task_name: Optional[str] = None) -> AgentStepResult:
            step_data = {
                'goal': goal,
                'before_screenshot': None,
                'after_screenshot': None,
                'model_response': None,
                'action': None,
                'success': False,
            }

            print(f'[UI-Venus] ---------- Step {len(self.history) + 1} ----------', flush=True)

            state = self.get_post_transition_state()
            h, w = state.pixels.shape[0], state.pixels.shape[1]
            before = state.pixels.copy()
            step_data['before_screenshot'] = before

            img = Image.fromarray(before).convert('RGB')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            img_b64 = base64.b64encode(buf.getvalue()).decode('ascii')

            # Coordinates come back in the smart-resized pixel space; compute that.
            resized_h, resized_w = _smart_resize(
                h, w, factor=28,
                min_pixels=self.min_pixels, max_pixels=self.max_pixels,
            )

            user_text = self._build_query(goal)

            try:
                response = self._call_model(img_b64, user_text)
                step_data['model_response'] = response
                if response is None:
                    print('[UI-Venus] No response from LLM endpoint', flush=True)
                    return AgentStepResult(done=False, data=step_data)
                print(f'[UI-Venus] raw response:\n{response}', flush=True)

                think_text = self._extract_tag('think', response)
                action_text = self._extract_tag('action', response)
                if not action_text:
                    logging.warning('UI-Venus: no <action> tag found')
                    return AgentStepResult(done=False, data=step_data)

                try:
                    action_name, params = parse_answer(action_text)
                except Exception as e:
                    logging.warning(f'UI-Venus: parse_answer failed: {e}')
                    self.history.append({'think': think_text, 'action': action_text})
                    return AgentStepResult(done=False, data=step_data)

                self.history.append({'think': think_text, 'action': action_text})

                action = self._to_json_action(
                    action_name, params, w, h, resized_w, resized_h,
                )
                step_data['action'] = action
                print(f'[UI-Venus] parsed action: {action}', flush=True)

                if action.action_type in ('status', 'answer'):
                    step_data['success'] = True
                    return AgentStepResult(done=True, data=step_data)

                self.env.execute_action(action)
                _time.sleep(self.wait_after_action_seconds)

                state_after = self.env.get_state(wait_to_stabilize=False)
                step_data['after_screenshot'] = state_after.pixels.copy()
                step_data['success'] = True

                return AgentStepResult(done=False, data=step_data)

            except Exception as e:
                logging.error(f'UI-Venus step error: {e}', exc_info=True)
                step_data['error'] = str(e)
                return AgentStepResult(done=False, data=step_data)

        def _rescale(self, x: float, y: float, orig_w: int, orig_h: int,
                     r_w: int, r_h: int) -> Tuple[int, int]:
            # Served UI-Venus emits coordinates normalized to 1000x1000
            # (matches Venus_framework/policy/ui_venus_policy.py). The r_w/r_h
            # smart-resized-pixel convention in ui_venus_navi_agent.py only
            # applies when running vLLM in-process with a custom processor.
            sx = int(round(float(x) * orig_w / 1000.0))
            sy = int(round(float(y) * orig_h / 1000.0))
            return max(0, min(sx, orig_w - 1)), max(0, min(sy, orig_h - 1))

        def _to_json_action(self, action_name: str, params: Dict[str, Any],
                             w: int, h: int, r_w: int, r_h: int):
            """Map UI-Venus (action_name, params) to JSONAction.

            UI-Venus emits coordinates in the smart-resized pixel space; we
            rescale back to original-screen pixels before executing.
            """
            x = y = x_ = y_ = None
            text = direction = goal_status = app_name = None
            act = 'wait'

            if action_name == 'Click':
                bx, by = params['box']
                x, y = self._rescale(bx, by, w, h, r_w, r_h)
                act = 'click'

            elif action_name == 'LongPress':
                bx, by = params['box']
                x, y = self._rescale(bx, by, w, h, r_w, r_h)
                act = 'long_press'

            elif action_name == 'Drag':
                sx, sy = params['start']
                ex, ey = params['end']
                x, y = self._rescale(sx, sy, w, h, r_w, r_h)
                x_, y_ = self._rescale(ex, ey, w, h, r_w, r_h)
                act = 'swipe'

            elif action_name == 'Scroll':
                start = params.get('start')
                end = params.get('end')
                d = (params.get('direction') or '').lower()
                if start and end:
                    x, y = self._rescale(start[0], start[1], w, h, r_w, r_h)
                    x_, y_ = self._rescale(end[0], end[1], w, h, r_w, r_h)
                elif d in ('up', 'down', 'left', 'right'):
                    direction = d
                    x_, y_ = -1, -1
                else:
                    x_, y_ = -1, -1
                act = 'swipe'

            elif action_name == 'Type':
                text = params.get('content', '')
                act = 'input_text'

            elif action_name == 'Launch':
                raw = (params.get('app') or params.get('url') or '').strip()
                app_name = _UIVENUS_APP_ALIASES.get(raw.lower(), raw)
                act = 'open_app'

            elif action_name == 'Wait':
                act = 'wait'

            elif action_name == 'Finished':
                goal_status = 'success'
                act = 'status'
                content = params.get('content', '')
                if content and hasattr(self.env, 'interaction_cache'):
                    self.env.interaction_cache = content

            elif action_name == 'CallUser':
                text = params.get('content', '')
                if hasattr(self.env, 'interaction_cache'):
                    self.env.interaction_cache = text
                act = 'answer'

            elif action_name == 'PressBack':
                act = 'navigate_back'
            elif action_name == 'PressHome':
                act = 'navigate_home'
            elif action_name == 'PressEnter':
                act = 'keyboard_enter'
            elif action_name == 'PressRecent':
                # No direct JSONAction for "recent apps"; fall back to wait.
                act = 'wait'
            else:
                act = 'wait'

            return json_action.JSONAction(
                action_type=act,
                direction=direction,
                x=x,
                y=y,
                x_=x_,
                y_=y_,
                text=text,
                goal_status=goal_status,
                app_name=app_name,
            )

    return UIVenusEvalAgent(
        env=env,
        llm_base_url=llm_cfg.get('base_url', 'http://localhost:8001/v1'),
        model_name=llm_cfg.get('model', 'UI-Venus'),
        name=agent_cfg.get('name', 'UIVenus-Agent'),
        wait_after_action_seconds=agent_cfg.get('wait_after_action_seconds', 2.0),
        history_length=agent_cfg.get('history_length', 5),
        prompt_type=agent_cfg.get('prompt_type', 'mobile'),
        temperature=llm_cfg.get('temperature', 0.0),
        top_p=llm_cfg.get('top_p', 1.0),
        max_tokens=llm_cfg.get('max_tokens', 2048),
        max_pixels=llm_cfg.get('max_pixels', 12845056),
        min_pixels=llm_cfg.get('min_pixels', 3136),
        request_timeout=llm_cfg.get('request_timeout', 120.0),
    )


# ---------------------------------------------------------------------------
# Worker / main
# ---------------------------------------------------------------------------

def worker_process(
    worker_id: int,
    tasks: List[str],
    config: Dict[str, Any],
    console_port: int,
    grpc_port: int,
    adb_server_port: int,
    result_queue: mp.Queue,
    log_dir: str,
    repeat_id: int = 0,
):
    import threading
    stop_event = threading.Event()
    reaper_thread = threading.Thread(target=_zombie_reaper_thread, args=(stop_event,), daemon=True)
    reaper_thread.start()

    print(f'[Worker {worker_id}] Started, handling {len(tasks)} tasks (repeat={repeat_id})')
    print(f'[Worker {worker_id}] Ports: console={console_port}, grpc={grpc_port}, adb_server={adb_server_port}')
    print(f'[Worker {worker_id}] Tasks: {tasks}')

    worker_config = config.copy()
    worker_config['worker_id'] = worker_id
    worker_config['env'] = config.get('env', {}).copy()
    worker_config['env']['console_port'] = console_port
    worker_config['env']['grpc_port'] = grpc_port
    worker_config['env']['adb_server_port'] = adb_server_port
    worker_config['eval'] = config.get('eval', {}).copy()
    worker_config['eval']['tasks'] = tasks

    base_output = os.path.expanduser(worker_config['eval'].get('output_path', '~/android_world/runs'))
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    worker_config['eval']['checkpoint_dir'] = ''
    worker_config['eval']['output_path'] = os.path.join(
        base_output, f'repeat_{repeat_id:02d}', f'{timestamp}_worker_{worker_id}'
    )

    worker_config['agent'] = config.get('agent', {}).copy()
    worker_config['llm'] = config.get('llm', {}).copy()

    results = {
        'worker_id': worker_id,
        'repeat_id': repeat_id,
        'tasks': tasks,
        'success': 0,
        'total': 0,
        'failed_tasks': [],
        'success_tasks': [],
        'error': None,
    }

    runner = None
    try:
        from eval.runner import EvalRunner

        runner = EvalRunner(worker_config)

        print(f'[Worker {worker_id}] Initializing Android environment...')
        runner.setup_env()

        print(f'[Worker {worker_id}] Initializing UI-Venus Agent...')
        runner.agent = _build_ui_venus_eval_agent(
            env=runner.env,
            agent_cfg=worker_config.get('agent', {}),
            llm_cfg=worker_config.get('llm', {}),
        )

        print(f'[Worker {worker_id}] Creating task suite...')
        suite = runner.create_suite()

        print(f'[Worker {worker_id}] Starting evaluation...')
        episodes = runner.run(suite)

        for ep in episodes:
            results['total'] += 1
            task_name = ep.get('task_template', 'unknown')
            is_success = ep.get('is_successful', 0)
            if ep.get('exception_info') is None:
                if is_success > 0.5:
                    results['success'] += 1
                    results['success_tasks'].append(task_name)
                else:
                    results['failed_tasks'].append(task_name)

        results['episodes'] = episodes
        print(f'[Worker {worker_id}] Evaluation completed: {results["success"]}/{results["total"]}')

        if episodes:
            print(f'\n[Worker {worker_id}] Detailed statistics:')
            runner.get_results_summary()

    except Exception as e:
        import traceback
        results['error'] = traceback.format_exc()
        print(f'[Worker {worker_id}] Error: {e}')
        traceback.print_exc()

    finally:
        print(f'[Worker {worker_id}] Closing runner...')
        try:
            if runner is not None:
                runner.close()
        except Exception as e:
            print(f'[Worker {worker_id}] Error during close: {e}')
        print(f'[Worker {worker_id}] Runner closed.')

    stop_event.set()
    print(f'[Worker {worker_id}] Putting results to queue...')
    result_queue.put(results)
    print(f'[Worker {worker_id}] Results sent, exiting...')


def run_parallel_eval(
    config: Dict[str, Any],
    num_workers: int,
    start_port: int,
    adb_server_start_port: int = 5037,
    tasks: Optional[List[str]] = None,
    log_dir: str = 'logs',
    repeat_id: int = 0,
):
    if tasks is None:
        eval_tasks = config.get('eval', {}).get('tasks')
        tasks = eval_tasks if eval_tasks else get_all_tasks()

    print(f'Total tasks: {len(tasks)}')
    print(f'Num workers: {num_workers}')
    print(f'Current round: {repeat_id}')

    task_chunks = split_tasks(tasks, num_workers)
    actual_workers = len(task_chunks)

    print(f'Actual workers: {actual_workers}')
    for i, chunk in enumerate(task_chunks):
        print(f'  Worker {i}: {len(chunk)} tasks')

    result_queue = mp.Queue()
    start_time = time.time()

    processes = []
    for i, chunk in enumerate(task_chunks):
        console_port = start_port + i * 2
        grpc_port = 8554 + i
        adb_server_port = adb_server_start_port + i
        p = mp.Process(
            target=worker_process,
            args=(i, chunk, config, console_port, grpc_port, adb_server_port,
                  result_queue, log_dir, repeat_id),
        )
        processes.append(p)

    print(f'\nStarting {actual_workers} worker processes (repeat={repeat_id})...')
    for p in processes:
        p.start()
        time.sleep(5)

    print('Waiting for all processes to complete...\n')

    all_results = []
    finished_count = 0
    total_workers = len(processes)

    while finished_count < total_workers:
        while True:
            try:
                result = result_queue.get_nowait()
                all_results.append(result)
                print(f'[Main] Got result from worker {result["worker_id"]}')
            except Exception:
                break

        for p in processes:
            if p.exitcode is not None and not hasattr(p, '_already_reported'):
                print(f'[Main] Worker {p.pid} finished with exit code {p.exitcode}')
                p._already_reported = True
                finished_count += 1

        if finished_count < total_workers:
            time.sleep(1)
            still_running = sum(1 for p in processes if p.exitcode is None)
            if still_running > 0:
                print(f'[Main] Still waiting for {still_running} workers... (got {len(all_results)} results)')

    while True:
        try:
            result = result_queue.get_nowait()
            all_results.append(result)
            print(f'[Main] Got result from worker {result["worker_id"]}')
        except Exception:
            break

    for p in processes:
        try:
            if p.is_alive():
                p.terminate()
                p.join(timeout=5)
                if p.is_alive():
                    p.kill()
                    p.join(timeout=3)
            p.close()
        except Exception as e:
            print(f'[Main] Error closing process: {e}')

    reap_zombies()

    total_time = time.time() - start_time
    total_success = sum(r['success'] for r in all_results)
    total_tasks = sum(r['total'] for r in all_results)

    print('\n' + '=' * 60)
    print(f'Round {repeat_id} Summary')
    print('=' * 60)
    print(f'Total time: {total_time / 60:.1f} min')
    print(f'Total tasks: {total_tasks}')
    print(f'Successful tasks: {total_success}')
    if total_tasks > 0:
        print(f'Success rate: {total_success / total_tasks * 100:.1f}%')
    print('=' * 60)

    all_episodes = []
    for r in all_results:
        if 'episodes' in r and r['episodes']:
            all_episodes.extend(r['episodes'])

    if all_episodes:
        print('\n' + '=' * 60)
        print('Detailed Statistics')
        print('=' * 60)
        from android_world.suite_utils import process_episodes
        result_df = process_episodes(all_episodes, print_summary=True)
        csv_file = os.path.join(log_dir, 'detailed_results.csv')
        result_df.to_csv(csv_file)
        print(f'\nDetailed results saved to: {csv_file}')

    print('\nWorker Results:')
    for r in sorted(all_results, key=lambda x: x['worker_id']):
        status = 'OK' if r['error'] is None else 'FAIL'
        print(f"  Worker {r['worker_id']}: {r['success']}/{r['total']} [{status}]")
        if r['error']:
            print(f"    Error: {r['error'][:200]}...")

    all_failed = []
    for r in all_results:
        all_failed.extend(r['failed_tasks'])
    if all_failed:
        print(f'\nFailed tasks ({len(all_failed)}):')
        for task in all_failed:
            print(f'  - {task}')

    serializable_results = []
    for r in all_results:
        r_copy = r.copy()
        r_copy.pop('episodes', None)
        serializable_results.append(r_copy)

    summary_file = os.path.join(log_dir, f'parallel_summary_repeat_{repeat_id}.json')
    with open(summary_file, 'w') as f:
        json.dump({
            'total_time_seconds': total_time,
            'total_tasks': total_tasks,
            'total_success': total_success,
            'success_rate': total_success / total_tasks if total_tasks > 0 else 0,
            'num_workers': actual_workers,
            'repeat_id': repeat_id,
            'worker_results': serializable_results,
        }, f, indent=2)
    print(f'\nSummary saved to: {summary_file}')

    reap_zombies()


def parse_args():
    parser = argparse.ArgumentParser(description='Android World UI-Venus Parallel Evaluation')
    default_config = str(ANDROID_WORLD_PATH / "eval" / "configs" / "UI-Venus.yaml")
    parser.add_argument('--config', type=str, default=default_config)
    parser.add_argument('--num_workers', type=int, default=1)
    parser.add_argument('--start_port', type=int, default=5556)
    parser.add_argument('--adb_server_start_port', type=int, default=5037)
    parser.add_argument('--tasks', type=str, default=None)
    parser.add_argument('--tasks_file', type=str, default=None)
    parser.add_argument('--log_dir', type=str, default='logs')
    parser.add_argument('--repeat_id', type=int, default=0)
    parser.add_argument('--task_random_seed', type=int, default=None)
    return parser.parse_args()


def reap_zombies():
    try:
        while True:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
    except (ChildProcessError, OSError):
        pass


def cleanup_children(signum=None, frame=None):
    for child in mp.active_children():
        try:
            child.terminate()
            child.join(timeout=5)
            if child.is_alive():
                child.kill()
                child.join(timeout=3)
        except Exception as e:
            print(f'[Cleanup] Error terminating {child.pid}: {e}')
    try:
        while True:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
    except (ChildProcessError, OSError):
        pass
    if signum is not None:
        sys.exit(1)


def main():
    mp.set_start_method('fork', force=True)
    signal.signal(signal.SIGTERM, cleanup_children)
    signal.signal(signal.SIGINT, cleanup_children)

    args = parse_args()

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    os.makedirs(args.log_dir, exist_ok=True)
    log_file = os.path.join(args.log_dir, f'parallel_eval_{timestamp}.log')
    setup_logging(log_file)

    print('\n' + '=' * 60)
    print('Android World UI-Venus Parallel Evaluation')
    print('=' * 60)
    print(f'Config file: {args.config}')
    print(f'Num workers: {args.num_workers}')
    print(f'Start port: {args.start_port}')
    print(f'ADB server start port: {args.adb_server_start_port}')
    print(f'Log dir: {args.log_dir}')
    print(f'Current round: {args.repeat_id}')
    print('=' * 60 + '\n')

    from eval.configs import load_config, get_default_config
    config = load_config(args.config) if os.path.exists(args.config) else get_default_config()

    if args.task_random_seed is not None:
        config.setdefault('eval', {})['task_random_seed'] = args.task_random_seed
        print(f'Task random seed overridden to: {args.task_random_seed}')

    tasks = None
    if args.tasks_file:
        tasks = []
        with open(args.tasks_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    tasks.extend([t.strip() for t in line.split(',') if t.strip()])
    elif args.tasks:
        tasks = [t.strip() for t in args.tasks.split(',')]

    try:
        run_parallel_eval(
            config=config,
            num_workers=args.num_workers,
            start_port=args.start_port,
            adb_server_start_port=args.adb_server_start_port,
            tasks=tasks,
            log_dir=args.log_dir,
            repeat_id=args.repeat_id,
        )
    except KeyboardInterrupt:
        print('\nEvaluation interrupted by user')
    except Exception as e:
        print(f'\nEvaluation error: {e}')
        import traceback
        traceback.print_exc()
    finally:
        cleanup_children()


if __name__ == '__main__':
    main()
