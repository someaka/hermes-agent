"""Unified /loop command parser — one parser, three thin callers.

All surfaces (CLI, Gateway, TUI) share the same parsing and execution
logic.  The only surface-specific part is how the dispatch handler
injects the loop prompt back into the session.
"""

from __future__ import annotations

from typing import Optional

from hermes_cli.unified_loop import UnifiedLoopManager
from hermes_cli.loop import (
    MIN_INTERVAL_SECONDS,
    _parse_interval,
)


def parse_loop_command(text: str) -> dict:
    """Parse a /loop command into a structured action dict.

    Returns dict with keys::

        action: "list" | "pause" | "pause_all" | "resume" | "resume_all"
                | "delete" | "delete_all" | "create" | "error"
        uid:    target UID (for pause/resume/delete)
        interval_seconds: int (for create)
        prompt: str (for create)
        message: str (for error)
    """
    # Strip /loop prefix
    text = text.strip()
    if text.startswith("/"):
        text = text.lstrip("/")
    if text.lower().startswith("loop"):
        text = text[4:].strip()

    # Strip leading "every " prefix (common user input)
    if text.lower().startswith("every "):
        text = text[6:].strip()

    if not text:
        return {"action": "list"}

    tokens = text.split()
    first = tokens[0].lower()

    if first in ("list", "status"):
        return {"action": "list"}

    if first == "pause":
        if len(tokens) > 1:
            return {"action": "pause", "uid": tokens[1].lstrip("#")}
        return {"action": "pause_all"}

    if first == "resume":
        if len(tokens) > 1:
            return {"action": "resume", "uid": tokens[1].lstrip("#")}
        return {"action": "resume_all"}

    if first in ("remove", "delete", "rm", "clear", "stop", "done"):
        if len(tokens) > 1:
            return {"action": "delete", "uid": tokens[1].lstrip("#")}
        return {"action": "delete_all"}

    # /loop <interval> <prompt> — create
    interval = _parse_interval(tokens[0])
    if interval is not None and len(tokens) > 1:
        interval = max(interval, MIN_INTERVAL_SECONDS)
        prompt = " ".join(tokens[1:])
        return {"action": "create", "interval_seconds": interval, "prompt": prompt}
    if interval is not None:
        return {
            "action": "error",
            "message": f"Missing prompt. Usage: /loop {tokens[0]} <prompt>",
        }

    return {"action": "error", "message": f"Unknown subcommand: {first!r}"}


def execute_loop_command(
    parsed: dict,
    *,
    session_id: str,
    hermes_home: str,
    source_json: Optional[str] = None,
    platform: str = "cli",
) -> str:
    """Execute a parsed loop command.  Returns human-readable output.

    All surfaces call this — same logic, same output.
    """
    manager = UnifiedLoopManager(session_id, hermes_home)
    action = parsed["action"]

    if action == "list":
        return manager.status_line()

    if action == "pause":
        manager.pause(parsed["uid"])
        return f"Paused loop #{parsed['uid']}"

    if action == "pause_all":
        for loop in manager.list():
            if loop["status"] == "active":
                manager.pause(loop["uid"])
        return "Paused all loops"

    if action == "resume":
        manager.resume(parsed["uid"], fire_now=True)
        return f"Resumed loop #{parsed['uid']}"

    if action == "resume_all":
        for loop in manager.list():
            if loop["status"] == "paused":
                manager.resume(loop["uid"], fire_now=True)
        return "Resumed all loops"

    if action == "delete":
        manager.delete(parsed["uid"])
        return f"Removed loop #{parsed['uid']}"

    if action == "delete_all":
        count = manager.delete_all()
        return f"Removed {count} loops"

    if action == "create":
        uid = manager.create(
            body=parsed["prompt"],
            interval_seconds=parsed["interval_seconds"],
            source_json=source_json,
            platform=platform,
            fire_now=(platform == "cli"),  # CLI fires immediately, gateway waits
        )
        return (
            f"Created loop #{uid} — "
            f"every {manager._format_interval(parsed['interval_seconds'])} — "
            f"{parsed['prompt']}"
        )

    return parsed.get("message", "Unknown error")
