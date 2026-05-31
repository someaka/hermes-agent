"""File-based platform adapter for TUI/CLI notification delivery.

This adapter registers with the gateway's adapter system so that
_kanban_notifier_watcher (and any other gateway-side event source) can
deliver events to connected TUI/CLI sessions via ``adapter.send()``.

Unlike Telegram/Discord adapters that push to external APIs, this adapter
writes events to a JSON-lines file that the TUI server watches and
dispatches to active sessions.  This bridges the gateway↔TUI process
boundary without OS-specific IPC (no Unix sockets, no FIFOs, no named
pipes) — just cross-platform file I/O.

File: ``~/.hermes/notifications/tui_events.jsonl``
Format: one JSON object per line::

    {"ts": 1717000000, "chat_id": "tui", "content": "...", "metadata": {...}}
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, SendResult

logger = logging.getLogger(__name__)

# ── Event file path ──────────────────────────────────────────────────
_HERMES_HOME = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
_EVENT_DIR = _HERMES_HOME / "notifications"
_EVENT_FILE = _EVENT_DIR / "tui_events.jsonl"

# Maximum file size before rotation (512 KB).  The TUI truncates what
# it has consumed, so this only bounds crash-orphaned growth.
_MAX_FILE_BYTES = 512 * 1024


def _ensure_dir() -> None:
    _EVENT_DIR.mkdir(parents=True, exist_ok=True)


def append_event(chat_id: str, content: str, metadata: dict | None = None) -> None:
    """Append a notification event to the shared JSON-lines file.

    Called by :meth:`TUIAdapter.send` in the gateway process.
    The TUI server's watcher thread reads the other end.
    """
    _ensure_dir()
    entry = {
        "ts": int(time.time()),
        "chat_id": chat_id,
        "content": content,
        "metadata": metadata or {},
    }
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
    try:
        with open(_EVENT_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as exc:
        logger.debug("tui_adapter: failed to write event: %s", exc)


class TUIAdapter(BasePlatformAdapter):
    """Platform adapter that delivers messages via a shared file.

    The gateway's kanban notifier calls ``adapter.send(chat_id, msg)``
    which appends the event to ``~/.hermes/notifications/tui_events.jsonl``.
    The TUI server watches this file and dispatches events to active
    sessions — bridging the gateway↔TUI process boundary.
    """

    def __init__(self, config: PlatformConfig, platform: Platform):
        super().__init__(config, platform)

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        """Write the event to the shared notification file."""
        try:
            append_event(chat_id, content, metadata)
            return SendResult(success=True)
        except Exception as exc:
            logger.warning("tui_adapter: write failed: %s", exc)
            return SendResult(success=False, error=str(exc))

    async def connect(self) -> bool:
        """No external connection needed — file I/O only."""
        self._running = True
        return True

    async def disconnect(self) -> None:
        """No external connection to tear down."""
        self._running = False

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        """Return minimal chat info for the TUI platform."""
        return {"chat_id": chat_id, "platform": "tui", "type": "direct"}

    async def start(self) -> None:
        """No external connection needed — file I/O only."""
        self._running = True

    async def stop(self) -> None:
        self._running = False
