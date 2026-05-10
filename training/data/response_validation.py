"""Strict parseability predicate for SFT data curation.

Used to gate which assistant responses qualify for the SFT training set.

The eval-time parser at MARS-Voyager/androidworld/eval/agents/qwen_agent.py
returns ``JSONAction(action_type='wait')`` on every failure mode (missing
``<tool_call>`` tag, malformed JSON, missing required fields, unknown
``system_button``, etc.). Using ``_parse_action`` as a truthy gate would
admit malformed responses as fake "successful waits."

``is_parseable`` here distinguishes a real ``wait`` (model deliberately
emitted ``arguments.action == "wait"``) from the fallback ``wait`` produced
on parse failures, and only accepts responses whose action grammar matches
what the eval pipeline can dispatch.
"""

from __future__ import annotations

import json
from typing import Any

# Action types the eval-time parser dispatches on. Source-form names appear
# alongside their normalized targets ('open' -> 'open_app', 'type' ->
# 'input_text', 'terminate' -> 'status'); the model may emit either form.
_ACCEPTED_ACTIONS = {
    "wait",
    "click",
    "long_press",
    "swipe",
    "open",
    "open_app",
    "type",
    "input_text",
    "system_button",
    "terminate",
    "answer",
}

_VALID_SYSTEM_BUTTONS = {"Back", "Home", "Enter"}


def _extract_tool_call(response: str) -> str | None:
    """Mirror MARS-Voyager qwen_agent._extract_tag_content for 'tool_call'."""
    if "<tool_call>" not in response:
        return None
    later = response.split("<tool_call>", 1)[1].strip("\n")
    if "</tool_call>" in later:
        content = later.split("</tool_call>", 1)[0].strip("\n")
    else:
        # Eval-time parser tolerates missing closing tag by taking the first
        # line; mirror that here so we don't reject responses the eval would
        # have parsed.
        content = later.split("\n", 1)[0]
    return content or None


def _is_coordinate(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 2:
        return False
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)


def is_parseable(response: str) -> bool:
    """Return True iff the response is a well-formed tool call.

    Accepts a deliberate ``wait`` action. Rejects every silent-fallback path
    in the eval-time parser: missing tag, malformed JSON, missing
    ``arguments.action``, unknown action type, or required fields missing /
    wrong-shaped for the chosen action.
    """
    action_str = _extract_tool_call(response)
    if action_str is None:
        return False

    try:
        action_dict = json.loads(action_str)
    except (json.JSONDecodeError, ValueError):
        return False

    if not isinstance(action_dict, dict):
        return False
    arguments = action_dict.get("arguments")
    if not isinstance(arguments, dict):
        return False

    action_type = arguments.get("action")
    if not isinstance(action_type, str) or action_type not in _ACCEPTED_ACTIONS:
        return False

    if action_type in ("click", "long_press"):
        return _is_coordinate(arguments.get("coordinate"))

    if action_type == "swipe":
        return _is_coordinate(arguments.get("coordinate")) and _is_coordinate(
            arguments.get("coordinate2")
        )

    if action_type in ("open", "open_app", "type", "input_text", "answer"):
        text = arguments.get("text")
        return isinstance(text, str) and len(text) > 0

    if action_type == "system_button":
        return arguments.get("button") in _VALID_SYSTEM_BUTTONS

    if action_type == "terminate":
        status = arguments.get("status")
        return isinstance(status, str) and len(status) > 0

    if action_type == "wait":
        return True

    return False


def _selftest() -> None:
    cases: list[tuple[str, bool, str]] = [
        # Accepted: deliberate wait
        (
            'pre <tool_call>{"name": "x", "arguments": {"action": "wait"}}</tool_call> post',
            True,
            "deliberate wait",
        ),
        # Accepted: click with valid coordinate
        (
            'thinking\n<tool_call>{"name": "mobile_use", "arguments": {"action": "click", "coordinate": [123, 456]}}</tool_call>',
            True,
            "click ok",
        ),
        # Accepted: swipe with both coords
        (
            '<tool_call>{"arguments": {"action": "swipe", "coordinate": [1,2], "coordinate2": [3,4]}}</tool_call>',
            True,
            "swipe ok",
        ),
        # Accepted: open / type / answer / system_button / terminate
        ('<tool_call>{"arguments": {"action": "open_app", "text": "Settings"}}</tool_call>', True, "open_app ok"),
        ('<tool_call>{"arguments": {"action": "type", "text": "hello"}}</tool_call>', True, "type ok"),
        ('<tool_call>{"arguments": {"action": "answer", "text": "yes"}}</tool_call>', True, "answer ok"),
        ('<tool_call>{"arguments": {"action": "system_button", "button": "Home"}}</tool_call>', True, "sysbtn ok"),
        ('<tool_call>{"arguments": {"action": "terminate", "status": "success"}}</tool_call>', True, "terminate ok"),
        # Tolerated: missing closing tag, content on one line
        (
            '<tool_call>{"arguments": {"action": "click", "coordinate": [1, 2]}}',
            True,
            "missing close tag",
        ),

        # Rejected: no tag
        ("Thought: I should click. {action: click}", False, "no tag"),
        # Rejected: empty tag
        ("<tool_call></tool_call>", False, "empty tag"),
        # Rejected: malformed JSON
        ("<tool_call>{not json}</tool_call>", False, "bad json"),
        # Rejected: missing arguments.action
        ('<tool_call>{"arguments": {}}</tool_call>', False, "no action"),
        # Rejected: unknown action
        ('<tool_call>{"arguments": {"action": "fly"}}</tool_call>', False, "unknown action"),
        # Rejected: click without coordinate
        ('<tool_call>{"arguments": {"action": "click"}}</tool_call>', False, "click no coord"),
        # Rejected: click with bad coordinate shape
        ('<tool_call>{"arguments": {"action": "click", "coordinate": [1]}}</tool_call>', False, "click 1d coord"),
        ('<tool_call>{"arguments": {"action": "click", "coordinate": ["a","b"]}}</tool_call>', False, "click str coord"),
        # Rejected: swipe missing one coord
        ('<tool_call>{"arguments": {"action": "swipe", "coordinate": [1,2]}}</tool_call>', False, "swipe one coord"),
        # Rejected: open_app missing text
        ('<tool_call>{"arguments": {"action": "open_app"}}</tool_call>', False, "open no text"),
        # Rejected: open_app empty text
        ('<tool_call>{"arguments": {"action": "open_app", "text": ""}}</tool_call>', False, "open empty text"),
        # Rejected: system_button bad button
        ('<tool_call>{"arguments": {"action": "system_button", "button": "Volume"}}</tool_call>', False, "bad button"),
        # Rejected: terminate missing status
        ('<tool_call>{"arguments": {"action": "terminate"}}</tool_call>', False, "terminate no status"),
        # Rejected: arguments not a dict
        ('<tool_call>{"arguments": "click"}</tool_call>', False, "args not dict"),
    ]

    failures = 0
    for response, expected, label in cases:
        got = is_parseable(response)
        if got != expected:
            failures += 1
            print(f"FAIL [{label}] expected={expected} got={got}")
            print(f"  response={response!r}")
    if failures:
        raise SystemExit(f"{failures}/{len(cases)} cases failed")
    print(f"OK {len(cases)} cases")


if __name__ == "__main__":
    _selftest()
