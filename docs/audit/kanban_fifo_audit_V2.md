# V2: RESOURCE LIFECYCLE Audit — Kanban FIFO Notification System

> **Task:** t_44c8c0da  
> **Auditor:** worker (Radical Edward)  
> **Date:** 2026-05-25  
> **Scope:** `hermes_cli/kanban_db.py` (writer), `tui_gateway/server.py` (reader/dispatch), stress test suite  
> **Parent tasks:** I1 (t_f21f8a8e), I2 (t_fc4fb47a)

---

## Executive Summary

The kanban FIFO notification bridge was subjected to **programmatic stress testing** across four resource dimensions: file descriptors, threads, queue behavior, and integration load. **13 new stress tests** were written and all pass. Combined with the existing **27 FIFO bridge tests** and **7 kanban notify tests**, the total test coverage is **47 tests, all passing**.

**Key findings:**
- **FD lifecycle is sound** — no leaks detected under sustained load (500 rapid writes)
- **Thread lifecycle is sound** — singleton pattern works, restart on death works
- **Queue behavior is sound** — bounded at 10,000, drops gracefully when full
- **One confirmed bug** — double-close on write-failure path in `kanban_db.py:2098`
- **One design limitation** — reader's blocking `open()` can hang if FIFO is removed while waiting

**Verdict: PASS with one bug to fix.**

---

## Test Suite

New file: `tests/tui_gateway/test_fifo_resource_lifecycle.py` (13 tests)

| Class | Tests | Focus |
|-------|-------|-------|
| `TestFdLifecycle` | 4 | FD leaks, ENXIO handling, double-close bug |
| `TestThreadLifecycle` | 3 | Singleton pattern, FIFO removal survival, restart |
| `TestQueueStress` | 4 | Ordering, drops, memory bounds, throughput |
| `TestIntegrationStress` | 2 | Multi-writer races, FIFO recreation under load |

**Total: 13/13 PASS**

Existing tests also verified:
- `tests/tui_gateway/test_fifo_notification_bridge.py`: 27/27 PASS
- `tests/hermes_cli/test_kanban_core_functionality.py` (notify subset): 7/7 PASS

**Grand total: 47/47 PASS**

---

## V2.1: File Descriptor Lifecycle

### Test Results

| Test | Result | Notes |
|------|--------|-------|
| `test_writer_fd_closed_after_successful_write` | PASS | FD count before/after identical |
| `test_writer_fd_closed_on_enxio` | PASS | No leak when open() fails |
| `test_double_close_bug_documented` | PASS | Bug documented and reproduced |
| `test_sustained_writes_no_fd_leak` | PASS | 500 writes, ±2 fd variance (test noise) |

### Finding: Double-Close Bug (CONFIRMED)

**Location:** `hermes_cli/kanban_db.py`, lines 2093-2099

**Current code:**
```python
_fd = os.open(_fifo_path, os.O_WRONLY | os.O_NONBLOCK)
try:
    _fifo = os.fdopen(_fd, "w", encoding="utf-8")
    _fifo.write(json.dumps({"task_id": task_id, "kind": kind}) + "\n")
    _fifo.close()
except OSError as _e:
    _log.debug("kanban_fifo_write_error: %s", _e)
    os.close(_fd)   # <-- DOUBLE CLOSE if write() failed!
```

**Root cause:** When `os.fdopen()` succeeds, the file object `_fifo` takes ownership of `_fd`. If `_fifo.write()` then raises `OSError`, the except block calls `os.close(_fd)`. However, Python's file object destructor will also close the fd when `_fifo` is garbage-collected. This results in a double-close (second close returns `EBADF`).

**Impact:** LOW in practice — `write()` on a FIFO rarely fails (kernel buffers pipe data). But it is a real correctness issue.

**Fix:** Use `try/finally` or `with` statement:
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

## V2.2: Thread Lifecycle

### Test Results

| Test | Result | Notes |
|------|--------|-------|
| `test_global_reader_is_singleton_per_module` | PASS | Same thread returned on repeated calls |
| `test_reader_thread_survives_fifo_removal` | PASS | Reader recreates FIFO after removal |
| `test_reader_restarts_after_death` | PASS | New thread spawned when global ref reset |

### Finding: Reader Blocking open() Limitation (DOCUMENTED)

**Location:** `tui_gateway/server.py`, line 185

**Current code:**
```python
with open(_KANBAN_FIFO_PATH, "r", encoding="utf-8") as _fifo:
```

**Behavior:** `open()` on a FIFO blocks until a writer connects. If the FIFO is `unlink()`ed while the reader is blocked in `open()`, the Linux kernel may keep the reader hung (the inode is still held open by the reader's own pending open). The reader's recovery loop (lines 201-212) only runs if `open()` raises an exception.

**Impact:** LOW — FIFO removal during production is rare (only happens on manual cleanup or atexit). The reader eventually recovers when a new writer connects or the process restarts.

**Mitigation:** The reader already has a 0.5s sleep + recreate loop. For stronger resilience, consider the **self-pipe O_RDWR trick** (open FIFO for both read and write in the reader, keeping a write fd open permanently to prevent EOF). This is what systemd does.

---

## V2.3: Queue Behavior Under Stress

### Test Results

| Test | Result | Notes |
|------|--------|-------|
| `test_queue_maintains_order` | PASS | 1000 items, strict FIFO ordering |
| `test_queue_drops_when_full` | PASS | 50 drops at maxsize=100 |
| `test_queue_memory_bounded` | PASS | 10,000 items, no crash |
| `test_end_to_end_throughput` | PASS | 500 msg, >50 msg/s throughput |

### Metrics

- **Queue capacity:** 10,000 items (configurable via `maxsize`)
- **Throughput:** >50 msg/s end-to-end (writer → FIFO → reader → queue)
- **Drop behavior:** `queue.Full` raised, caught, logged at DEBUG
- **Memory per item:** ~200-300 bytes (small dict with task_id + kind)
- **Max queue memory:** ~3MB at capacity

### Verdict

Queue is well-behaved: bounded, ordered, drops gracefully under overload. Throughput is more than sufficient for the notification use case (expected rate: <1 msg/s in practice).

---

## V2.4: Integration Stress

### Test Results

| Test | Result | Notes |
|------|--------|-------|
| `test_multiple_writers_single_reader` | PASS | 3 writers × 50 msg, ≥75% delivery |
| `test_fifo_recreation_under_load` | PASS | Reader recovers after FIFO removal |

### Observations

**Multi-writer races:** With multiple rapid writers on a single FIFO, expected races occur:
- `EPIPE` (broken pipe): reader closes between writer's `open()` and `write()`
- `ENXIO` (no reader): reader not connected at `open()` time

These are **acceptable** — FIFO is best-effort by design. The I2 cross-project research confirmed that every production system (systemd, Docker, Redis, PostgreSQL) makes the same choice.

**FIFO recreation:** When the FIFO is removed mid-stream:
1. Pre-removal messages: delivered normally
2. During-removal messages: lost (ENXIO on writer)
3. Post-removal messages: delivered after reader recreates FIFO

This matches expected behavior.

---

## Findings Summary

### Critical (0)
None.

### High (0)
None.

### Medium (1)

1. **Double-close bug in kanban_db.py** (lines 2093-2099)
   - `os.close(_fd)` in except block after `os.fdopen()` has taken ownership
   - **Fix:** Use `try/finally` or `with` statement for proper fd lifecycle
   - **Impact:** Low in practice, but incorrect

### Low (1)

2. **Reader blocking open() can hang on FIFO removal**
   - `open(FIFO, "r")` blocks until writer connects
   - If FIFO is unlinked while blocked, recovery depends on kernel behavior
   - **Fix:** Consider self-pipe O_RDWR trick (systemd pattern)
   - **Impact:** Low — rare in production

---

## Recommendations for POLISH Phase

1. **Fix double-close bug** (M1): Replace nested try/except with try/finally
2. **Document reader blocking behavior** (L2): Add comment explaining the open() semantics
3. **Add queue depth metric** (from I1 L2): Module-level counter for observability
4. **Add drop counter** (from I1 L2): Count queue.Full events

---

## Conclusion

The kanban FIFO notification system's **resource lifecycle is sound**. File descriptors are properly managed (one bug aside), threads are well-behaved, the queue is bounded and ordered, and the system degrades gracefully under stress.

The double-close bug is a real issue that should be fixed in the POLISH phase, but it does not affect production behavior (write() on a FIFO almost never fails).

**Gate: PASS — Ready for POLISH phase with one fix required.**
