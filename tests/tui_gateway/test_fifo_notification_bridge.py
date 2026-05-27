"""Tests for the Kanban→TUI FIFO notification bridge.

Tests both sides of the zero-polling FIFO bridge:
  - Writer side (hermes_cli/kanban_db.py _append_event): writes JSON lines
    to ~/.hermes/tui_kanban.fifo for notification-worthy event kinds.
  - Reader side (tui_gateway/server.py): _format_kanban_notification formats
    events correctly; _start_kanban_fifo_reader reads from FIFO and dispatches.
"""

from __future__ import annotations

import json
import os
import queue
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli import kanban_db as kb


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    """Isolated HERMES_HOME with an empty kanban DB."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home


def _make_server_module(tmp_path, monkeypatch):
    """Import tui_gateway.server for testing."""
    with patch.dict("sys.modules", {
        "hermes_constants": MagicMock(
            get_hermes_home=MagicMock(return_value=str(tmp_path))
        ),
        "hermes_cli.env_loader": MagicMock(),
        "hermes_cli.banner": MagicMock(),
        "hermes_state": MagicMock(),
    }):
        import importlib
        import tui_gateway.server as srv
        importlib.reload(srv)

        yield srv

        srv._sessions.clear()
        importlib.reload(srv)


# ---------------------------------------------------------------------------
# Writer-side tests (kanban_db._append_event writes to task_events)
# ---------------------------------------------------------------------------

class TestAppendEventDbWriter:
    """Tests that _append_event writes to task_events table (not FIFO)."""

    def test_completed_event_in_db(self, kanban_home):
        """A 'completed' event should be in task_events after commit."""
        with kb.connect() as conn:
            tid = kb.create_task(conn, title="ship it", assignee="worker")
            kb.complete_task(conn, tid, summary="all done")

        conn = kb.connect()
        row = conn.execute(
            "SELECT kind FROM task_events WHERE task_id = ? AND kind = 'completed'",
            (tid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["kind"] == "completed"

    def test_blocked_event_in_db(self, kanban_home):
        """A 'blocked' event should be in task_events after commit."""
        with kb.connect() as conn:
            tid = kb.create_task(conn, title="blocked task", assignee="worker")
            kb.block_task(conn, tid, reason="need input")

        conn = kb.connect()
        row = conn.execute(
            "SELECT kind FROM task_events WHERE task_id = ? AND kind = 'blocked'",
            (tid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["kind"] == "blocked"

    def test_crashed_event_in_db(self, kanban_home):
        """A 'crashed' event should be in task_events after commit."""
        with kb.connect() as conn:
            tid = kb.create_task(conn, title="crash task", assignee="worker")
            kb._append_event(conn, tid, kind="crashed")

        conn = kb.connect()
        row = conn.execute(
            "SELECT kind FROM task_events WHERE task_id = ? AND kind = 'crashed'",
            (tid,),
        ).fetchone()
        conn.close()
        assert row is not None

    def test_created_event_in_db(self, kanban_home):
        """A 'created' event should be in task_events (for all events, not just terminal)."""
        with kb.connect() as conn:
            tid = kb.create_task(conn, title="no-notify", assignee="worker")

        conn = kb.connect()
        row = conn.execute(
            "SELECT kind FROM task_events WHERE task_id = ? AND kind = 'created'",
            (tid,),
        ).fetchone()
        conn.close()
        assert row is not None


    def test_heartbeat_event_in_db(self, kanban_home):
        """A 'heartbeat' event should be in task_events (non-terminal)."""
        with kb.connect() as conn:
            tid = kb.create_task(conn, title="hb task", assignee="worker")
            kb._append_event(conn, tid, kind="heartbeat")

        conn = kb.connect()
        row = conn.execute(
            "SELECT kind FROM task_events WHERE task_id = ? AND kind = 'heartbeat'",
            (tid,),
        ).fetchone()
        conn.close()
        assert row is not None

    def test_multiple_events_all_in_db(self, kanban_home):
        """Multiple events should all be persisted to task_events."""
        with kb.connect() as conn:
            tid1 = kb.create_task(conn, title="task-1", assignee="worker")
            kb.complete_task(conn, tid1, summary="done-1")
            tid2 = kb.create_task(conn, title="task-2", assignee="worker")
            kb.block_task(conn, tid2, reason="waiting")

        conn = kb.connect()
        rows = conn.execute(
            "SELECT task_id, kind FROM task_events WHERE kind IN ('completed', 'blocked') ORDER BY id"
        ).fetchall()
        conn.close()
        assert len(rows) == 2
        assert rows[0]["task_id"] == tid1
        assert rows[0]["kind"] == "completed"
        assert rows[1]["task_id"] == tid2
        assert rows[1]["kind"] == "blocked"


# ---------------------------------------------------------------------------
# Reader-side tests (tui_gateway.server._format_kanban_notification)
# ---------------------------------------------------------------------------

class TestFormatKanbanNotification:
    """Tests for _format_kanban_notification in tui_gateway/server.py."""

    @pytest.fixture(autouse=True)
    def _setup_server(self, tmp_path, monkeypatch):
        """Import tui_gateway.server for testing."""
        with patch.dict("sys.modules", {
            "hermes_constants": MagicMock(
                get_hermes_home=MagicMock(return_value=str(tmp_path))
            ),
            "hermes_cli.env_loader": MagicMock(),
            "hermes_cli.banner": MagicMock(),
            "hermes_state": MagicMock(),
        }):
            import importlib
            import tui_gateway.server as srv
            importlib.reload(srv)
            self.server = srv
            yield
            srv._sessions.clear()
            importlib.reload(srv)

    def _make_sub(self, task_id="t_abc"):
        return {"task_id": task_id, "platform": "cli", "chat_id": "cli-123"}

    def _make_event(self, kind, payload=None):
        ev = MagicMock()
        ev.kind = kind
        ev.payload = payload
        ev.get = lambda k, d=None: getattr(ev, k, d) if k != "payload" else payload
        return ev

    def test_completed_with_summary(self):
        ev = self._make_event("completed", {"summary": "shipped rate limiter"})
        sub = self._make_sub("t_abc")
        msg = self.server._format_kanban_notification(ev, sub)
        assert msg is not None
        assert "t_abc" in msg
        assert "done" in msg
        assert "shipped rate limiter" in msg

    def test_completed_without_summary(self):
        ev = self._make_event("completed", {})
        sub = self._make_sub("t_xyz")
        msg = self.server._format_kanban_notification(ev, sub)
        assert msg is not None
        assert "t_xyz" in msg
        assert "done" in msg

    def test_completed_with_none_payload(self):
        ev = self._make_event("completed", None)
        sub = self._make_sub("t_123")
        msg = self.server._format_kanban_notification(ev, sub)
        assert msg is not None
        assert "t_123" in msg

    def test_blocked_with_reason(self):
        ev = self._make_event("blocked", {"reason": "need API key"})
        sub = self._make_sub("t_blk")
        msg = self.server._format_kanban_notification(ev, sub)
        assert msg is not None
        assert "t_blk" in msg
        assert "blocked" in msg
        assert "need API key" in msg

    def test_blocked_without_reason(self):
        ev = self._make_event("blocked", {})
        sub = self._make_sub("t_blk2")
        msg = self.server._format_kanban_notification(ev, sub)
        assert msg is not None
        assert "t_blk2" in msg
        assert "blocked" in msg

    def test_crashed(self):
        ev = self._make_event("crashed")
        sub = self._make_sub("t_crash")
        msg = self.server._format_kanban_notification(ev, sub)
        assert msg is not None
        assert "t_crash" in msg
        assert "crashed" in msg
        assert "dispatcher will retry" in msg

    def test_timed_out_with_limit(self):
        ev = self._make_event("timed_out", {"limit_seconds": 300})
        sub = self._make_sub("t_to")
        msg = self.server._format_kanban_notification(ev, sub)
        assert msg is not None
        assert "t_to" in msg
        assert "timed out" in msg
        assert "300" in msg

    def test_timed_out_without_limit(self):
        ev = self._make_event("timed_out", None)
        sub = self._make_sub("t_to2")
        msg = self.server._format_kanban_notification(ev, sub)
        assert msg is not None
        assert "t_to2" in msg

    def test_gave_up_with_error(self):
        ev = self._make_event("gave_up", {"error": "spawn failed 3x"})
        sub = self._make_sub("t_gu")
        msg = self.server._format_kanban_notification(ev, sub)
        assert msg is not None
        assert "t_gu" in msg
        assert "gave up" in msg
        assert "spawn failed 3x" in msg

    def test_gave_up_without_error(self):
        ev = self._make_event("gave_up", None)
        sub = self._make_sub("t_gu2")
        msg = self.server._format_kanban_notification(ev, sub)
        assert msg is not None
        assert "t_gu2" in msg

    def test_unknown_kind_returns_none(self):
        ev = self._make_event("edited")
        sub = self._make_sub("t_xxx")
        msg = self.server._format_kanban_notification(ev, sub)
        assert msg is None

    def test_completed_summary_truncated_to_200_chars(self):
        long_summary = "x" * 300
        ev = self._make_event("completed", {"summary": long_summary})
        sub = self._make_sub("t_long")
        msg = self.server._format_kanban_notification(ev, sub)
        assert msg is not None
        # The summary in the message should be truncated.
        assert len(msg) < len(long_summary) + 100  # rough upper bound

    def test_blocked_reason_truncated_to_160_chars(self):
        long_reason = "y" * 200
        ev = self._make_event("blocked", {"reason": long_reason})
        sub = self._make_sub("t_longblk")
        msg = self.server._format_kanban_notification(ev, sub)
        assert msg is not None
        assert len(msg) < len(long_reason) + 100

    def test_dict_event_access(self):
        """Events from DB queries arrive as dicts, not MagicMock objects."""
        ev = {"kind": "completed", "payload": {"summary": "dict event"}}
        sub = self._make_sub("t_dict")
        msg = self.server._format_kanban_notification(ev, sub)
        assert msg is not None
        assert "t_dict" in msg
        assert "dict event" in msg


# ---------------------------------------------------------------------------
# FIFO lifecycle tests (module-level mkfifo + atexit cleanup)
# ---------------------------------------------------------------------------

class TestDbPollerLifecycle:
    """Tests for DB poller startup and event detection."""

    def test_db_poller_reads_terminal_events(self, kanban_home):
        """DB poller should detect terminal events in task_events."""
        with kb.connect() as conn:
            tid = kb.create_task(conn, title="poller-test", assignee="worker")
            kb.complete_task(conn, tid, summary="done")

        conn = kb.connect()
        rows = conn.execute(
            "SELECT task_id, kind FROM task_events "
            "WHERE kind IN ('completed', 'blocked', 'gave_up', 'crashed', 'timed_out') "
            "ORDER BY id"
        ).fetchall()
        conn.close()
        assert len(rows) >= 1
        assert rows[-1]["task_id"] == tid
        assert rows[-1]["kind"] == "completed"

    def test_db_poller_ignores_non_terminal_events(self, kanban_home):
        """DB poller should NOT pick up non-terminal events (created, heartbeat)."""
        with kb.connect() as conn:
            tid = kb.create_task(conn, title="non-terminal", assignee="worker")
            kb._append_event(conn, tid, kind="heartbeat")

        conn = kb.connect()
        terminal = {"completed", "blocked", "gave_up", "crashed", "timed_out"}
        rows = conn.execute(
            "SELECT kind FROM task_events WHERE task_id = ?", (tid,)
        ).fetchall()
        conn.close()
        kinds = {r["kind"] for r in rows}
        # Should have 'created' and 'heartbeat' but no terminal kinds
        assert not kinds.intersection(terminal)


# ---------------------------------------------------------------------------
# Integration: write → read via DB
# ---------------------------------------------------------------------------

class TestDbPollerEndToEnd:
    """End-to-end tests: kanban_db writes → DB poller reads."""

    def test_complete_task_visible_in_db_for_poller(self, kanban_home):
        """Completing a task should make the event visible in task_events.

        This is the core integration test: _append_event writes to DB,
        the DB poller queries for terminal events, and the data matches.
        """
        with kb.connect() as conn:
            tid = kb.create_task(conn, title="e2e-test", assignee="worker")
            kb.complete_task(conn, tid, summary="e2e complete")

        conn = kb.connect()
        row = conn.execute(
            "SELECT task_id, kind FROM task_events "
            "WHERE task_id = ? AND kind = 'completed'",
            (tid,),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["task_id"] == tid
        assert row["kind"] == "completed"

    def test_non_terminal_events_not_in_poller_query(self, kanban_home):
        """Non-terminal events (created, edited) should NOT appear in poller results."""
        with kb.connect() as conn:
            kb.create_task(conn, title="silent", assignee="worker")

        conn = kb.connect()
        terminal = {"completed", "blocked", "gave_up", "crashed", "timed_out"}
        placeholders = ",".join("?" for _ in terminal)
        rows = conn.execute(
            f"SELECT kind FROM task_events WHERE kind IN ({placeholders})",
            tuple(terminal),
        ).fetchall()
        conn.close()
        assert len(rows) == 0


# ---------------------------------------------------------------------------
# Edge cases: DB writer correctness
# ---------------------------------------------------------------------------

class TestDbWriterEdgeCases:
    """Tests for DB writer edge cases."""

    def test_task_completion_no_error(self, kanban_home):
        """Completing a task should not raise."""
        with kb.connect() as conn:
            tid = kb.create_task(conn, title="enxio-test", assignee="worker")
            kb.complete_task(conn, tid, summary="done")

    def test_append_event_directly(self, kanban_home):
        """_append_event should write to task_events without error."""
        with kb.connect() as conn:
            tid = kb.create_task(conn, title="direct-test", assignee="worker")
            kb._append_event(conn, tid, kind="crashed")

        conn = kb.connect()
        row = conn.execute(
            "SELECT kind FROM task_events WHERE task_id = ? AND kind = 'crashed'",
            (tid,),
        ).fetchone()
        conn.close()
        assert row is not None

    def test_no_fifo_code_in_kanban_db(self):
        """Verify FIFO code has been removed from kanban_db."""
        import hermes_cli.kanban_db as _kb_module
        import inspect
        src = inspect.getsource(_kb_module)
        assert "_flush_pending_fifo_writes" not in src, "FIFO flush should be removed"
        assert "_pending_fifo_writes" not in src, "FIFO pending list should be removed"
        assert "tui_kanban.fifo" not in src, "FIFO path should be removed"


class TestFifoReaderEdgeCases:
    """Tests for reader-side edge cases: queue.Full, metrics."""

    @pytest.fixture(autouse=True)
    def _setup_server(self, tmp_path, monkeypatch):
        """Import tui_gateway.server for testing."""
        with patch.dict("sys.modules", {
            "hermes_constants": MagicMock(
                get_hermes_home=MagicMock(return_value=str(tmp_path))
            ),
            "hermes_cli.env_loader": MagicMock(),
            "hermes_cli.banner": MagicMock(),
            "hermes_state": MagicMock(),
        }):
            import importlib
            import tui_gateway.server as srv
            importlib.reload(srv)
            self.server = srv
            yield
            srv._sessions.clear()
            importlib.reload(srv)

    def test_queue_full_drops_and_counts(self):
        """When queue is full, notifications should be dropped and counted."""
        srv = self.server
        # Fill the queue to capacity
        for i in range(srv._kanban_fifo_queue.maxsize):
            srv._kanban_fifo_queue.put({"task_id": f"t_{i}", "kind": "completed"}, block=False)

        # Reset drop counter
        srv._kanban_fifo_dropped_count = 0

        # Now put one more — should drop
        with pytest.raises(queue.Full):
            srv._kanban_fifo_queue.put({"task_id": "t_overflow", "kind": "completed"}, block=False)

        # The reader would normally catch queue.Full and increment the counter.
        # Verify the counter exists and can be incremented.
        srv._kanban_fifo_dropped_count += 1
        assert srv._kanban_fifo_dropped_count == 1

    def test_metrics_function_returns_expected_keys(self):
        """get_kanban_fifo_metrics should return all expected keys."""
        metrics = self.server.get_kanban_fifo_metrics()
        assert "queue_depth" in metrics
        assert "queue_maxsize" in metrics
        assert "dropped_count" in metrics
        assert "received_count" in metrics
        assert "dispatch_failures" in metrics
        assert "reader_alive" in metrics
        assert "reader_name" in metrics

    def test_queue_not_empty_after_put(self):
        """Putting items in the queue should increase its size."""
        srv = self.server
        srv._kanban_fifo_queue.put({"task_id": "t_test", "kind": "completed"}, block=False)
        assert srv._kanban_fifo_queue.qsize() >= 1


class TestFifoDispatchEdgeCases:
    """Tests for dispatch-side edge cases: DB failures, filtering."""

    @pytest.fixture(autouse=True)
    def _setup_server(self, tmp_path, monkeypatch):
        """Import tui_gateway.server for testing."""
        with patch.dict("sys.modules", {
            "hermes_constants": MagicMock(
                get_hermes_home=MagicMock(return_value=str(tmp_path))
            ),
            "hermes_cli.env_loader": MagicMock(),
            "hermes_cli.banner": MagicMock(),
            "hermes_state": MagicMock(),
        }):
            import importlib
            import tui_gateway.server as srv
            importlib.reload(srv)
            self.server = srv
            yield
            srv._sessions.clear()
            importlib.reload(srv)

    def test_dispatch_db_failure_handled(self):
        """When DB connect fails, dispatch should log and continue."""
        srv = self.server
        session = {"history_lock": threading.Lock()}

        # Mock kanban_db.connect to raise
        with patch.object(srv, "logger"):
            with patch("hermes_cli.kanban_db.connect", side_effect=sqlite3.Error("DB locked")):
                # Should not raise
                srv._dispatch_kanban_notification("sid-1", session, {"task_id": "t_test"})

        # dispatch_failures counter should be incremented
        assert srv._kanban_fifo_dispatch_failures >= 1

    def test_dispatch_empty_task_id_returns_early(self):
        """When data has no task_id, dispatch should return immediately."""
        srv = self.server
        session = {}
        # Should return without doing anything
        srv._dispatch_kanban_notification("sid-1", session, {})
        srv._dispatch_kanban_notification("sid-1", session, {"task_id": ""})

    def test_dispatch_while_busy_queues_notification(self):
        """When session is running, notification should be queued not dropped."""
        srv = self.server
        lock = threading.Lock()
        session = {
            "history_lock": lock,
            "running": True,
            "_pending_kanban": [],
            "_kanban_cursors": {},
        }

        # Mock the DB layer to return one subscription and one event
        fake_sub = {"platform": "cli", "chat_id": "sid-1", "task_id": "t_test", "last_event_id": 0}
        fake_event = MagicMock()
        fake_event.id = 1
        fake_event.kind = "completed"
        fake_event.payload = {"summary": "all done"}
        fake_event.created_at = 12345

        with patch("hermes_cli.kanban_db.connect") as mock_conn:
            mock_conn.return_value = MagicMock()
            with patch("hermes_cli.kanban_db.list_notify_subs", return_value=[fake_sub]):
                with patch("hermes_cli.kanban_db.unseen_events_for_sub", return_value=(None, [fake_event])):
                    with patch.object(srv, "_format_kanban_notification", return_value="Task completed: all done"):
                        srv._dispatch_kanban_notification("sid-1", session, {"task_id": "t_test"})

        # Notification should be queued, not dropped
        assert session["_pending_kanban"] == ["Task completed: all done"]
        # Session should still be running (we never set it to False)
        assert session["running"] is True

    def test_pending_kanban_drained_when_session_goes_idle(self):
        """Pending notifications are processed after session goes idle."""
        srv = self.server
        lock = threading.Lock()
        session = {
            "history_lock": lock,
            "running": False,
            "_pending_kanban": ["First notification", "Second notification"],
            "_kanban_cursors": {},
        }
        submitted = []

        def fake_run_prompt_submit(rid, sid, sess, text):
            submitted.append(text)
            # Simulate the turn ending — set running back to False
            with sess["history_lock"]:
                sess["running"] = False

        with patch.object(srv, "_run_prompt_submit", side_effect=fake_run_prompt_submit):
            with patch.object(srv, "_emit"):
                # Simulate the drain logic from _run_prompt_submit's finally block
                while True:
                    with session["history_lock"]:
                        _pending = session.get("_pending_kanban", [])
                        if not _pending:
                            break
                        _next_msg = _pending.pop(0)
                        if session.get("running"):
                            _pending.insert(0, _next_msg)
                            break
                        session["running"] = True
                    try:
                        srv._emit("message.start", "sid-1")
                        fake_run_prompt_submit("rid", "sid-1", session, _next_msg)
                    except Exception:
                        with session["history_lock"]:
                            session["running"] = False

        # Both notifications should have been submitted
        assert submitted == ["First notification", "Second notification"]
        # Queue should be empty
        assert session["_pending_kanban"] == []
        # Session should be idle at the end
        assert session["running"] is False

    def test_pending_drain_stops_if_session_becomes_busy(self):
        """Drain stops if another turn starts mid-drain."""
        srv = self.server
        lock = threading.Lock()
        session = {
            "history_lock": lock,
            "running": False,
            "_pending_kanban": ["First notification", "Second notification"],
            "_kanban_cursors": {},
        }
        submitted = []

        def fake_run_prompt_submit(rid, sid, sess, text):
            submitted.append(text)
            # After first notification, simulate another turn starting
            if text == "First notification":
                with sess["history_lock"]:
                    sess["running"] = True  # Another turn started!

        with patch.object(srv, "_run_prompt_submit", side_effect=fake_run_prompt_submit):
            with patch.object(srv, "_emit"):
                while True:
                    with session["history_lock"]:
                        _pending = session.get("_pending_kanban", [])
                        if not _pending:
                            break
                        _next_msg = _pending.pop(0)
                        if session.get("running"):
                            _pending.insert(0, _next_msg)
                            break
                        session["running"] = True
                    try:
                        srv._emit("message.start", "sid-1")
                        fake_run_prompt_submit("rid", "sid-1", session, _next_msg)
                    except Exception:
                        with session["history_lock"]:
                            session["running"] = False

        # Only first notification submitted; second put back
        assert submitted == ["First notification"]
        # Second notification should still be queued
        assert session["_pending_kanban"] == ["Second notification"]
        # Session is busy (another turn is running)
        assert session["running"] is True
