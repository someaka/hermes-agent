"""Shared /loop command handler — one implementation for CLI, Gateway, TUI.

All surfaces share the same parsing and cron-backed execution logic.
Each surface provides a thin adapter: how to format output and how to
check for a running gateway.
"""

from __future__ import annotations

import json
import shlex
from typing import Any, Callable, List, Optional

from cron.jobs import parse_duration


def _cron_api(cronjob_tool, **kwargs) -> dict:
    """Call the cronjob tool and parse its JSON result."""
    return json.loads(cronjob_tool(**kwargs))


def handle_loop_command(
    text: str,
    *,
    cronjob_tool: Callable[..., str],
    output: Callable[[str], None],
    check_gateway_running: Optional[Callable[[], bool]] = None,
) -> None:
    """Parse and execute a /loop command using the cronjob system.

    Args:
        text: The full command text (e.g. "/loop 5m check deployment")
        cronjob_tool: The cronjob tool function (from tools.cronjob_tools)
        output: Callback for human-readable output (print for CLI, append for gateway)
        check_gateway_running: Optional callback to warn if no gateway is active
    """
    # Strip leading / and "loop" prefix
    text = text.strip()
    if text.startswith("/"):
        text = text.lstrip("/")
    if text.lower().startswith("loop"):
        text = text[len("loop"):].lstrip()

    tokens = shlex.split(text) if text else []

    # ── No args → show usage + list ──────────────────────────────────

    if not tokens:
        output("")
        output("+/loop — Scheduled Prompts")
        output("")
        output("  Usage:")
        output('    /loop <schedule> <prompt>     e.g. /loop 5m "check deployment"')
        output("    /loop list                    Show all loop jobs")
        output("    /loop pause <job_id>          Pause a loop job")
        output("    /loop resume <job_id>         Resume a paused loop job")
        output("    /loop remove <job_id>         Delete a loop job")
        output("    /loop clear                   Delete ALL loop jobs")
        output("")
        output("  Schedules:  5m, 30m, 2h, 1d, every 5m, every 2h, 0 9 * * *")
        output("")

        result = _cron_api(cronjob_tool, action="list", include_disabled=True)
        jobs = result.get("jobs", []) if result.get("success") else []
        loop_jobs = [j for j in jobs if j.get("name", "").startswith("loop:")]
        if loop_jobs:
            output("  Loop Jobs:")
            for job in loop_jobs:
                state_icon = "\u25b6" if job.get("state") == "active" else "\u23f8"
                output(f"    {state_icon} {job['job_id'][:12]:<12} | {job['schedule']:<15}")
                output(f"      {job.get('prompt_preview', '')}")
                if job.get("next_run_at"):
                    output(f"      Next: {job['next_run_at']}")
                output("")
        else:
            output("  No loop jobs. Use '/loop <schedule> <prompt>' to create one.")
        output("")
        return

    subcommand = tokens[0].lower()

    # ── list ─────────────────────────────────────────────────────────

    if subcommand == "list":
        result = _cron_api(cronjob_tool, action="list", include_disabled=True)
        jobs = result.get("jobs", []) if result.get("success") else []
        loop_jobs = [j for j in jobs if j.get("name", "").startswith("loop:")]
        if not loop_jobs:
            output("No loop jobs found.")
            return
        output("Loop Jobs:")
        for job in loop_jobs:
            output(f"  ID: {job['job_id']}")
            output(f"  State: {job.get('state', '?')}")
            output(f"  Schedule: {job['schedule']} ({job.get('repeat', '?')})")
            output(f"  Next run: {job.get('next_run_at', 'N/A')}")
            output(f"  Prompt: {job.get('prompt_preview', '')}")
            if job.get("last_run_at"):
                output(f"  Last run: {job['last_run_at']} ({job.get('last_status', '?')})")
            output("")
        return

    # ── pause ────────────────────────────────────────────────────────

    if subcommand == "pause":
        if len(tokens) < 2:
            output("Usage: /loop pause <job_id>")
            return
        job_id = tokens[1]
        result = _cron_api(cronjob_tool, action="pause", job_id=job_id, reason="paused from /loop")
        if result.get("success"):
            output(f"Paused loop job: {result['job']['name']} ({job_id})")
        else:
            output(f"Failed to pause: {result.get('error')}")
        return

    # ── resume ───────────────────────────────────────────────────────

    if subcommand == "resume":
        if len(tokens) < 2:
            output("Usage: /loop resume <job_id>")
            return
        job_id = tokens[1]
        result = _cron_api(cronjob_tool, action="resume", job_id=job_id)
        if result.get("success"):
            output(f"Resumed loop job: {result['job']['name']} ({job_id})")
            output(f"  Next run: {result['job'].get('next_run_at')}")
        else:
            output(f"Failed to resume: {result.get('error')}")
        return

    # ── remove ───────────────────────────────────────────────────────

    if subcommand == "remove":
        if len(tokens) < 2:
            output("Usage: /loop remove <job_id>")
            return
        job_id = tokens[1]
        result = _cron_api(cronjob_tool, action="remove", job_id=job_id)
        if result.get("success"):
            output(f"Removed loop job: {result.get('removed_job', {}).get('name', job_id)}")
        else:
            output(f"Failed to remove: {result.get('error')}")
        return

    # ── clear (remove ALL loop jobs) ─────────────────────────────────

    if subcommand == "clear":
        result = _cron_api(cronjob_tool, action="list", include_disabled=True)
        jobs = result.get("jobs", []) if result.get("success") else []
        loop_jobs = [j for j in jobs if j.get("name", "").startswith("loop:")]
        if not loop_jobs:
            output("No loop jobs to clear.")
            return
        removed = 0
        for j in loop_jobs:
            r = _cron_api(cronjob_tool, action="remove", job_id=j["job_id"])
            if r.get("success"):
                removed += 1
        output(f"Cleared {removed}/{len(loop_jobs)} loop job(s).")
        return

    # ── create: /loop <schedule> <prompt> ────────────────────────────

    # Handle "every 5m" syntax
    if tokens[0].lower() == "every" and len(tokens) > 1:
        schedule = f"every {tokens[1]}"
        prompt = " ".join(tokens[2:]) if len(tokens) > 2 else ""
    else:
        schedule = tokens[0]
        prompt = " ".join(tokens[1:]) if len(tokens) > 1 else ""

    if not prompt:
        output("Usage: /loop <schedule> <prompt>")
        output('  Example: /loop 5m "check deployment status"')
        output('  Example: /loop every 30m "summarize news"')
        return

    # Warn if interval looks very short
    try:
        minutes = parse_duration(schedule.lstrip("every "))
        if minutes < 1:
            output("Interval is very short (< 1 minute). The scheduler ticks every 60s, so this may not fire as expected.")
    except Exception:
        pass

    # Warn if no gateway is running
    if check_gateway_running is not None:
        try:
            if not check_gateway_running():
                output("No gateway is running. The job will be scheduled but will not execute until a gateway starts.")
        except Exception:
            pass

    name = f"loop: {prompt[:50]}{'...' if len(prompt) > 50 else ''}"
    result = _cron_api(cronjob_tool,
        action="create",
        schedule=schedule,
        prompt=prompt,
        name=name,
        deliver="origin",
    )
    if result.get("success"):
        output(f"Loop job created: {result['job_id']}")
        output(f"  Schedule: {result['schedule']}")
        output(f"  Next run: {result['next_run_at']}")
        output(f"  To stop: /loop remove {result['job_id']}")
    else:
        output(f"Failed to create loop: {result.get('error')}")
