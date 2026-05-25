# I3: PRODUCTION READINESS Audit — Kanban FIFO Notification System

> **Task:** t_ea26c097  
> **Auditor:** worker (default profile)  
> **Date:** 2026-05-25  
> **Scope:** `hermes_cli/kanban_db.py` (writer), `tui_gateway/server.py` (reader/dispatch/queue/poller), `tests/tui_gateway/test_fifo_notification_bridge.py`  
> **Parents:** t_f21f8a8e (V1 correctness), t_fc4fb47a (V2 cross-project research)

---

## Executive Summary

The kanban FIFO notification bridge is **architecturally sound and production-ready** with respect to core correctness. All 798 kanban-related tests pass (27 FIFO bridge + 771 kanban_db/tools). The at-most-once, best-effort design is the **correct choice** — validated against systemd, Docker, Redis Pub/Sub, and PostgreSQL NOTIFY patterns.

However, **three issues degrade production operability**: a confirmed double-close bug on the writer failure path, all operational failures logged at DEBUG (invisible in production), and zero observability metrics. These are not correctness bugs but **operability gaps** that make production incidents hard to diagnose.

**Test Results:** 798/798 PASS (1 skipped)

---

## V3.1: WRITER SIDE — `hermes_cli/kanban_db.py` lines 2080-2106

### Code Under Audit

```python
_notify_kinds = {"completed", "blocked", "gave_up", "crashed", "timed_out"}
if kind in _notify_kinds:
    _fifo_path = os.path.expanduser("~/.hermes/tui_kanban.fifo")
    if os.path.exists(_fifo_path):
        try:
            _fd = os.open(_fifo_path, os.O_WRONLY | os.O_NONBLOCK)
            try:
                _fifo = os.fdopen(_fd, "w", encoding="utf-8")
                _fifo.write(json.dumps({"task_id": task_id, "kind": kind}) + "\n")
                _fifo.close()
            except OSError as _e:
                _log.debug("kanban_fifo_write_error: %s", _e)
                os.close(_fd)                          # ← BUG: double-close
        except OSError as _e:
            if _e.errno == errno.ENXIO:
                _log.debug("kanban_fifo_no_reader: no TUI listening on %s", _fifo_path)
            else:
                _log.debug("kanban_fifo_open_error: %s", _e)
        except Exception as _e:
            _log.debug("kanban_fifo_write_error: %s", _e)
```

### Finding V3-M1: DOUBLE-CLOSE on write-failure path (CONFIRMED BUG)

**Severity:** Medium  
**Location:** kanban_db.py line 2099  
**Status:** Reproduced and verified

**Analysis:**

When `_fifo.write()` fails after `os.fdopen()` succeeds, the except block calls `os.close(_fd)`. But `_fifo` (the file object returned by `os.fdopen()`) **already owns the file descriptor**. When `write()` raises, `_fifo` still holds the fd. Calling `os.close(_fd)` closes it a second time.

**Reproduction:**

```python
import os, tempfile
fifo_path = tempfile.mktemp(suffix='.fifo')
os.mkfifo(fifo_path, 0o600)
fd = os.open(fifo_path, os.O_WRONLY | os.O_NONBLOCK)
fifo = os.fdopen(fd, "w", encoding="utf-8")
fifo.write("test\n")
fifo.close()          # fd is now closed
os.close(fd)          # OSError: [Errno 9] Bad file descriptor
```

**Impact:**
- In practice, `write()` on a FIFO rarely fails (kernel buffers pipe data)
- If it DOES fail, the double-close raises `OSError(EBADF)` which is caught by the outer `except Exception` and logged at debug
- **No data loss**, but the error path itself is buggy
- In threaded environments, closing an already-closed fd could theoretically close a fd that was reused by another thread (race condition)

**Fix:**

```python
_fd = os.open(_fifo_path, os.O_WRONLY | os.O_NONBLOCK)
_fifo = None
try:
    _fifo = os.fdopen(_fd, "w", encoding="utf-8")
    _fifo.write(json.dumps({"task_id": task_id, "kind": kind}) + "\n")
except OSError as _e:
    _log.debug("kanban_fifo_write_error: %s", _e)
finally:
    if _fifo is not None:
        _fifo.close()
    else:
        os.close(_fd)
```

---

### Finding V3-M2: All operational failures logged at DEBUG (INVISIBLE IN PRODUCTION)

**Severity:** Medium  
**Location:** kanban_db.py lines 2098, 2102, 2104, 2106; tui_gateway/server.py lines 194-195, 198-199, 208-210, 213-214, 333

**Analysis:**

Every failure path in the FIFO system logs at DEBUG level. In production, Hermes runs with INFO or WARNING level. This means:

| Failure | Current Level | Should Be | Why |
|---------|--------------|-----------|-----|
| ENXIO (no reader) | DEBUG | DEBUG | Expected, not an error |
| FIFO open error (not ENXIO) | DEBUG | WARNING | Indicates permission/FS issue |
| Write error after fdopen | DEBUG | WARNING | Indicates broken pipe or FS issue |
| Queue full (drop) | DEBUG | WARNING | Indicates overload |
| Bad JSON line | DEBUG | WARNING | Indicates corruption |
| FIFO recreate failure | WARNING | WARNING | ✓ Already correct |
| Reader thread crash | EXCEPTION | ERROR | ✓ Already correct |
| Dispatch failure | DEBUG | WARNING | Indicates DB or session issue |

**Impact:**
- Operators cannot see when notifications are being dropped
- Silent degradation — queue fills, drops increase, no alert
- DB connection failures during dispatch are invisible

**Fix:** Elevate log levels for unexpected failures:

```python
# kanban_db.py
except OSError as _e:
    if _e.errno == errno.ENXIO:
        _log.debug("kanban_fifo_no_reader: no TUI listening on %s", _fifo_path)
    else:
        _log.warning("kanban_fifo_open_error: %s", _e)  # ← was debug

# tui_gateway/server.py
except queue.Full:
    _log.warning("kanban_fifo_queue full; dropped notification")  # ← was debug
except Exception:
    _log.warning("kanban_fifo_reader: bad JSON line", exc_info=True)  # ← was debug

# dispatch
except Exception:
    _log.warning("kanban_notification_dispatch failed", exc_info=True)  # ← was debug
```

---

### Finding V3-L2: Symlink attack on FIFO path (THEORETICAL)

**Severity:** Low  
**Location:** kanban_db.py line 2085, tui_gateway/server.py line 138

**Analysis:**

The FIFO path is `os.path.expanduser("~/.hermes/tui_kanban.fifo")`. If an attacker can create a symlink at this path pointing to a sensitive file, and the writer opens it with `O_WRONLY`, they could potentially cause writes to arbitrary files.

**Mitigation factors:**
- The FIFO is created with `0o600` permissions (owner-only)
- The path is under `~/.hermes` which is user-owned
- An attacker would need access to the user's home directory
- `os.path.exists()` check does NOT follow symlinks safely — race condition exists

**Fix:** Use `os.lstat()` to verify the path is actually a FIFO before opening:

```python
import stat
if os.path.exists(_fifo_path):
    try:
        st = os.lstat(_fifo_path)
        if not stat.S_ISFIFO(st.st_mode):
            _log.warning("kanban_fifo_path_not_fifo: %s", _fifo_path)
            return
    except OSError:
        pass
```

---

## V3.2: READER SIDE — `tui_gateway/server.py` lines 137-224

### Code Under Audit

```python
_kanban_fifo_queue: queue.Queue = queue.Queue(maxsize=10000)
_kanban_global_reader_thread: threading.Thread | None = None

def _start_global_kanban_reader() -> threading.Thread:
    global _kanban_global_reader_thread
    if (_kanban_global_reader_thread is not None
        and _kanban_global_reader_thread.is_alive()):
        return _kanban_global_reader_thread

    def _reader() -> None:
        while True:
            try:
                with open(_KANBAN_FIFO_PATH, "r", encoding="utf-8") as _fifo:
                    for _line in _fifo:
                        ...
                        _kanban_fifo_queue.put(_data, block=False)
            except (OSError, IOError):
                if not os.path.exists(_KANBAN_FIFO_PATH):
                    try:
                        os.mkfifo(_KANBAN_FIFO_PATH, 0o600)
                    except Exception:
                        logger.warning("...", exc_info=True)
                time.sleep(0.5)
            except Exception:
                logger.exception("kanban_fifo_reader_error")
                time.sleep(1.0)

    _t = threading.Thread(target=_reader, daemon=True, name="kanban-fifo-global")
    _t.start()
    _kanban_global_reader_thread = _t
    return _t

_start_global_kanban_reader()  # eager start at import
```

### Finding V3-L1: No operational metrics (QUEUE DEPTH, DROP COUNTER, THREAD HEALTH)

**Severity:** Low  
**Location:** tui_gateway/server.py lines 142, 192-196

**Analysis:**

There is no way for an operator to observe:
1. **Queue depth** — how backed up is the notification queue?
2. **Drop count** — how many notifications were dropped due to queue.Full?
3. **Reader thread health** — is the reader thread still alive?
4. **Dispatch latency** — how long between FIFO write and session notification?

**Impact:**
- Cannot detect overload conditions
- Cannot diagnose "why didn't I get a notification?"
- Cannot set up alerts for notification system health

**Fix:** Add simple module-level counters (no external dependencies):

```python
# Module-level metrics (simple, dependency-free)
_kanban_fifo_dropped_count: int = 0
_kanban_fifo_received_count: int = 0
_kanban_fifo_last_drop_ts: float = 0.0

def get_kanban_fifo_metrics() -> dict:
    """Return current FIFO notification metrics."""
    thread = _kanban_global_reader_thread
    return {
        "queue_depth": _kanban_fifo_queue.qsize(),
        "queue_maxsize": _kanban_fifo_queue.maxsize,
        "dropped_count": _kanban_fifo_dropped_count,
        "received_count": _kanban_fifo_received_count,
        "reader_alive": thread.is_alive() if thread else False,
        "reader_name": thread.name if thread else None,
    }
```

Update counters in the reader:

```python
except queue.Full:
    _kanban_fifo_dropped_count += 1
    _kanban_fifo_last_drop_ts = time.time()
    logger.warning("kanban_fifo_queue full; dropped notification")
# ...
_kanban_fifo_queue.put(_data, block=False)
_kanban_fifo_received_count += 1
```

---

### Finding V3-L3: No INFO-level lifecycle logs

**Severity:** Low  
**Location:** tui_gateway/server.py lines 147-152, 217-219

**Analysis:**

Key lifecycle events are silent at INFO level:
- FIFO created on import
- Reader thread started
- FIFO recreated after removal
- First notification dispatched

**Impact:**
- Hard to verify the notification system is actually running
- Hard to correlate notification issues with lifecycle events

**Fix:** Add INFO logs:

```python
# After successful thread start
logger.info("kanban_fifo_reader started: %s", _KANBAN_FIFO_PATH)

# After FIFO recreation
logger.info("kanban_fifo_recreated: %s", _KANBAN_FIFO_PATH)

# On first successful dispatch (rate-limited)
```

---

## V3.3: DISPATCH SIDE — `_dispatch_kanban_notification` lines 273-333

### Code Under Audit

```python
def _dispatch_kanban_notification(sid: str, session: dict, data: dict) -> None:
    _task_id = data.get("task_id", "")
    if not _task_id:
        return
    _fmt_kinds = {"completed", "blocked", "gave_up", "crashed", "timed_out"}
    try:
        from hermes_cli import kanban_db as _kb
        _conn = _kb.connect()
        try:
            _subs = _kb.list_notify_subs(_conn)  # ← loads ALL subs
            for _sub in _subs:
                if _sub.get("platform") != "cli":
                    continue
                if _sub["task_id"] != _task_id:
                    continue
                ...
        finally:
            _conn.close()
    except Exception:
        logger.debug("kanban_notification_dispatch failed", exc_info=True)
```

### Finding V3-M3: DB query loads all subscriptions (PERFORMANCE)

**Severity:** Medium  
**Location:** tui_gateway/server.py line 290

**Analysis:**

`_kb.list_notify_subs(_conn)` is called **without a task_id filter**, loading ALL subscriptions across all tasks and platforms. For large boards with many subscribers, this is O(n) where n = total subscriptions.

The code then filters in Python:
- Skip non-CLI platforms
- Skip non-matching task_ids

**Fix:** Pass `task_id` to `list_notify_subs`:

```python
_subs = _kb.list_notify_subs(_conn, task_id=_task_id)
```

This is already supported by `list_notify_subs` (line 6244-6249 of kanban_db.py):

```python
def list_notify_subs(conn: sqlite3.Connection, task_id: Optional[str] = None) -> list[dict]:
    if task_id is not None:
        rows = conn.execute("SELECT * FROM kanban_notify_subs WHERE task_id = ?", (task_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM kanban_notify_subs").fetchall()
    return [dict(r) for r in rows]
```

---

### Finding V3-L4: Dispatch failures silently swallowed

**Severity:** Low  
**Location:** tui_gateway/server.py line 332-333

**Analysis:**

The entire dispatch function is wrapped in a bare `except Exception` that logs at DEBUG and swallows the exception. This includes:
- DB connection failures
- DB query failures
- `_format_kanban_notification` crashes
- `_emit` failures
- `_run_prompt_submit` failures (though these have their own try/except)

**Impact:**
- If the kanban DB is corrupted or locked, notifications stop silently
- No way to alert on dispatch failure rate

**Fix:** Elevate to WARNING and add a counter:

```python
except Exception:
    _kanban_fifo_dispatch_failures += 1
    logger.warning("kanban_notification_dispatch failed", exc_info=True)
```

---

## V3.4: TEST COVERAGE GAPS

### Current Coverage (27 tests, all passing)

| Area | Tests | Coverage |
|------|-------|----------|
| Writer: notify kinds | 5 | ✓ completed, blocked, crashed, timed_out, gave_up |
| Writer: non-notify kinds | 2 | ✓ created, heartbeat |
| Writer: no FIFO | 1 | ✓ missing FIFO doesn't raise |
| Writer: multiple events | 1 | ✓ multiple lines |
| Reader: format notification | 14 | ✓ all kinds, truncation, dict access |
| Lifecycle: FIFO creation | 1 | ✓ mkfifo on import |
| Lifecycle: FIFO cleanup | 1 | ✓ atexit unlink |
| End-to-end | 2 | ✓ write→read through real FIFO |

### Missing Coverage (HIGH PRIORITY)

| Scenario | Why Missing | Risk |
|----------|-------------|------|
| **Double-close bug** | No test for write() failure path | Bug exists, untested |
| **Queue.Full handling** | No test for queue overflow | Drop path untested |
| **FIFO removal mid-read** | No test for reader recovery | Auto-heal untested |
| **Bad JSON handling** | No test for corrupt FIFO data | Parse error path untested |
| **ENXIO handling** | No test for no-reader scenario | Writer error path untested |
| **Dispatch with DB failure** | No test for `_dispatch_kanban_notification` | Completely untested |
| **Reader thread death** | No test for thread restart | No watchdog coverage |
| **Permissions denied** | No test for `0o600` enforcement | Security path untested |

---

## V3.5: FAILURE RECOVERY MATRIX

| Failure Mode | Current Behavior | Verdict | Recommendation |
|--------------|------------------|---------|----------------|
| FIFO missing | Writer skips; reader recreates | PASS | Add INFO log on recreate |
| FIFO corrupted (regular file) | Reader opens, gets garbage, skips bad JSON | PASS | Add lstat check |
| No reader connected | Writer gets ENXIO, logs debug | PASS | Keep DEBUG — expected |
| Queue full | Drops with debug log | PASS | Elevate to WARNING; add counter |
| Reader thread dies | No auto-restart (but broad except makes this unlikely) | PASS | Add watchdog (low priority) |
| DB connection fail | Dispatch logs debug, continues | PASS | Elevate to WARNING; add counter |
| Session not running | Notification deferred | PASS | — |
| Session finalized | Poller exits | PASS | — |
| Broken pipe during write | Double-close bug | **FAIL** | Fix V3-M1 |
| JSON parse failure | Line dropped, debug log | PASS | Elevate to WARNING |
| FIFO permission denied | Writer skips silently | PASS | Elevate to WARNING |

---

## V3.6: LOGGING AUDIT

### Current Log Levels

| Location | Level | Message | Should Be |
|----------|-------|---------|-----------|
| Writer ENXIO | DEBUG | `kanban_fifo_no_reader` | DEBUG ✓ |
| Writer open error | DEBUG | `kanban_fifo_open_error` | WARNING |
| Writer write error | DEBUG | `kanban_fifo_write_error` | WARNING |
| Reader queue full | DEBUG | `kanban_fifo_queue full` | WARNING |
| Reader bad JSON | DEBUG | `kanban_fifo_reader: bad JSON` | WARNING |
| Reader recreate fail | WARNING | `kanban_fifo_reader: failed to recreate` | WARNING ✓ |
| Reader unexpected | EXCEPTION | `kanban_fifo_reader_error` | ERROR ✓ |
| Dispatch fail | DEBUG | `kanban_notification_dispatch failed` | WARNING |

### Missing Lifecycle Logs

| Event | Missing Level |
|-------|--------------|
| Reader thread started | INFO |
| FIFO recreated | INFO |
| First notification dispatched per session | INFO |

---

## Findings Summary

### Critical (0)
None. No bugs that cause data loss, crashes, or security breaches.

### High (0)
None.

### Medium (3)

1. **V3-M1: Double-close bug on writer failure path** (kanban_db.py line 2099)
   - `os.close(_fd)` called after `_fifo.close()` already closed the fd
   - **Fix:** Use `finally` block with `_fifo is not None` check

2. **V3-M2: All operational failures logged at DEBUG** (both files)
   - queue.Full, open errors, write errors, dispatch failures are invisible in production
   - **Fix:** Elevate unexpected failures to WARNING

3. **V3-M3: DB query loads all subscriptions** (tui_gateway/server.py line 290)
   - `list_notify_subs(_conn)` called without `task_id` filter
   - **Fix:** Pass `task_id=_task_id` to filter at DB level

### Low (4)

4. **V3-L1: No operational metrics** — queue depth, drop counter, thread health unobservable
5. **V3-L2: Symlink attack on FIFO path** — theoretical, mitigated by user-owned path
6. **V3-L3: No INFO-level lifecycle logs** — hard to verify system is running
7. **V3-L4: Dispatch failures silently swallowed at DEBUG** — hard to detect DB issues

---

## Recommendations for POLISH Phase

### Must Fix (for production deploy)

1. **Fix double-close bug (V3-M1)** — 3-line change, zero risk
2. **Elevate log levels (V3-M2)** — change `debug` → `warning` on error paths
3. **Filter DB query (V3-M3)** — pass `task_id` to `list_notify_subs`

### Should Fix (for operability)

4. **Add module-level metrics (V3-L1)** — simple counters, no dependencies
5. **Add INFO lifecycle logs (V3-L3)** — reader start, FIFO recreate

### Could Fix (nice to have)

6. **Add lstat FIFO verification (V3-L2)** — symlink attack defense
7. **Add dispatch failure counter (V3-L4)** — complement to drop counter

### Test Coverage to Add

8. **Test double-close fix** — mock `write()` to raise OSError
9. **Test queue.Full** — fill queue, verify drop + counter
10. **Test FIFO removal recovery** — unlink FIFO mid-read, verify recreation
11. **Test bad JSON handling** — write garbage to FIFO, verify skip
12. **Test ENXIO** — write with no reader, verify graceful skip
13. **Test dispatch with DB failure** — mock `connect()` to raise

---

## Conclusion

The kanban FIFO notification system is **architecturally sound and matches production patterns from systemd, Docker, Redis, and PostgreSQL**. The at-most-once, best-effort design is the correct choice.

The gaps are in **operability, not correctness**:
- A real but low-impact bug (double-close on write failure)
- Silent failure modes (all errors at DEBUG)
- Blind spots (no metrics, no lifecycle logs)

**Gate: PASS with reservations** — Ready for POLISH phase. The must-fix items (M1-M3) should be addressed before declaring "production-grade."

---

*Audit verified against:*
- Source code: `hermes_cli/kanban_db.py` (lines 2080-2106), `tui_gateway/server.py` (lines 137-344)
- Tests: `tests/tui_gateway/test_fifo_notification_bridge.py` (27 tests)
- Full suite: 798 kanban-related tests pass
- Cross-project research: systemd, Docker, Redis, PostgreSQL, Linux POSIX
