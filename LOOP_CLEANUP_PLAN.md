# /loop Cleanup — Implementation Plan

**Task:** PLAN-2: /loop cleanup implementation plan (Planner 2)  
**Date:** 2026-05-30  
**Scope:** `hermes_cli/loop.py`, `cli.py`, `tui_gateway/server.py`, `gateway/run.py`, tests  
**Status:** Ready for implementation  

---

## 1. Executive Summary

The `/loop` command has **three separate implementations** with two incompatible backends:

| Entry Point | Backend | Persistence |
|---|---|---|
| TUI | `LoopManager` + `LoopScheduler` (daemon thread) | `SessionDB.state_meta` |
| CLI | `cronjob` tool | Cron SQLite DB |
| Gateway | `cronjob` tool | Cron SQLite DB |

This plan unifies the architecture, fixes all identified bugs, and adds missing tests. Work is split into **four phases** so each PR is reviewable and bisect-safe.

---

## 2. Consolidated Findings

### 2.1 Critical / High Severity

| ID | Finding | File(s) | Root Cause |
|---|---|---|---|
| C1 | **MAX_TURNS never enforced** — loops run forever despite "5/20 turns" UI | `hermes_cli/loop.py:739-765` | `_tick()` increments `turns_completed` but never checks against `default_max_turns` |
| C2 | **Dual-system architecture** — TUI loops invisible to CLI/gateway and vice versa | `hermes_cli/loop.py`, `cli.py`, `gateway/run.py`, `tui_gateway/server.py` | TUI uses SessionDB; CLI/gateway use cron DB with no sync |
| C3 | **Burst flood on recovery** — all overdue loops fire in one tick after sleep/block | `hermes_cli/loop.py:749-765` | `_tick()` iterates all eligible loops with no rate limit or inter-fire delay |
| C4 | **_make_tui_dispatch missing completion event on failure** — TUI spinner stuck | `tui_gateway/server.py:994-1006` | `except` block sets `running=False` but never emits `message.end` |

### 2.2 Medium Severity

| ID | Finding | File(s) | Root Cause |
|---|---|---|---|
| M1 | **pause(uid) kills scheduler for ALL loops** | `hermes_cli/loop.py:551-574` | `self._stop_scheduler()` called unconditionally after pausing one loop |
| M2 | **LoopManager daemon thread leak on session end** | `tui_gateway/server.py:956-983` | Session cleanup closes worker/unregisters notify but never calls `mgr.shutdown()` |
| M3 | **resume() resets last_fired_at=0 causing immediate refire** | `hermes_cli/loop.py:576-603` | Resume sets `last_fired_at = 0.0` instead of preserving the schedule offset |
| M4 | **_DB_CACHE thread-unsafe** — logical race on SessionDB creation | `hermes_cli/loop.py:131-158` | Check-then-act pattern on module-level dict without lock |
| M5 | **Duplicated CLI/Gateway handlers (~320 lines)** | `cli.py:8248-8430`, `gateway/run.py:11569-11713` | Near-identical cron-based logic copy-pasted with minor drift |
| M6 | **CLI supports "every" syntax, gateway doesn't** | `cli.py:8385-8387`, `gateway/run.py:11684-11692` | Gateway never strips the "every " prefix before parsing |

### 2.3 Low Severity

| ID | Finding | File(s) | Root Cause |
|---|---|---|---|
| L1 | **Silent interval clamping** — no user feedback when <60s raised to 60s | `hermes_cli/loop.py:400,504,537` | `max(parsed, MIN_INTERVAL_SECONDS)` with no warning |
| L2 | **_del_loop_meta sets empty string instead of deleting** | `hermes_cli/loop.py:273-284` | Uses `set_meta(key, "")` rather than `delete_meta` |
| L3 | **_del_all_loop_meta partial failure orphans metadata** | `hermes_cli/loop.py:287-299` | Registry cleared before loop keys; exception mid-loop leaves orphans |
| L4 | **Gateway/CLI clear removes jobs one-by-one without atomicity** | `cli.py:8366-8380`, `gateway/run.py:11669-11682` | O(N) sequential `cronjob remove` calls |
| L5 | **No upper bound on loop interval** | `hermes_cli/loop.py:307-330` | `_parse_interval` accepts "365d" with no cap |
| L6 | **Zero tests for CLI /loop handler** | `tests/hermes_cli/test_loop_command.py` | File exists but only tests `process_command` dispatch, not handler logic |
| L7 | **_state parameter in LoopScheduler stored but never used** | `hermes_cli/loop.py:696-702` | Vestigial from single-loop scheduler design |
| L8 | **on_message callback accepted but never called** | `hermes_cli/loop.py:699,705` | Dead API surface kept for backward compat |
| L9 | **UID collision not checked (6 hex chars)** | `hermes_cli/loop.py:113-115` | `_add_id_to_registry` skips duplicate silently |
| L10 | **_DB_CACHE no invalidation on profile switch** | `hermes_cli/loop.py:131-158` | Cache keyed by `hermes_home` but never cleared |
| L11 | **No prompt content validation (max length)** | `hermes_cli/loop.py:501-503` | Empty check only; no upper bound |

---

## 3. Implementation Phases

### Phase 1: Core LoopManager Fixes (hermes_cli/loop.py)
**Goal:** Fix bugs in the shared core module before touching consumers.  
**Estimated:** ~300 lines changed, 8-12 new tests.

#### 1.1 Enforce MAX_TURNS (C1)
- In `LoopScheduler._tick()`, after incrementing `turns_completed`, check `>= self._max_turns`.
- If exceeded: set `state.status = "done"`, save, skip dispatch.
- Add `turns_limit_reached` to `LoopState` status enum or use `"done"` with a reason field.
- Update `status_line()` to show "done (limit reached)" when applicable.

#### 1.2 Fix pause(uid) scheduler scope (M1)
- In `LoopManager.pause(uid=...)`:
  - After saving the paused state, check `self.is_active()`.
  - Only call `self._stop_scheduler()` if no active loops remain.

#### 1.3 Fix resume() immediate refire (M3)
- In `LoopManager.resume()`:
  - Instead of `last_fired_at = 0.0`, set `last_fired_at = time.time()`.
  - This resumes the interval from "now", causing the next fire after `interval_seconds`.
  - Add an optional `fire_now: bool = False` parameter for users who *do* want immediate refire.

#### 1.4 Thread-safe _DB_CACHE (M4)
- Replace module-level `_DB_CACHE: Dict[str, Any] = {}` with:
  ```python
  _DB_CACHE: Dict[str, Any] = {}
  _DB_CACHE_LOCK = threading.Lock()
  ```
- In `_get_session_db()`, wrap the check-then-act in `with _DB_CACHE_LOCK:`.

#### 1.5 Delete metadata properly (L2, L3)
- Change `_del_loop_meta` to call `db.delete_meta(key)` instead of `set_meta(key, "")`.
- In `_del_all_loop_meta`, wrap the entire operation in a try/except and only clear the registry after all loop keys are successfully deleted. On failure, log and leave registry intact so orphans remain discoverable.

#### 1.6 Warn on interval clamping (L1)
- In `_parse_loop_command` and `LoopManager.set/add`, when `parsed < MIN_INTERVAL_SECONDS`, include a notice in the return value / response string: `"Interval adjusted from {parsed}s to {MIN_INTERVAL_SECONDS}s (minimum is 60s)."`

#### 1.7 Cap max interval (L5)
- Add `MAX_INTERVAL_SECONDS = 86400 * 30` (30 days).
- Clamp `interval_seconds` to `min(max(interval, MIN_INTERVAL_SECONDS), MAX_INTERVAL_SECONDS)`.
- Include notice when capped.

#### 1.8 Remove dead code (L7, L8)
- Remove `state` parameter from `LoopScheduler.__init__` and `self._state` attribute.
- Remove `on_message` parameter from `LoopScheduler.__init__` and `self._on_message` attribute.
- Update all call sites (TUI, tests) to stop passing these.

#### 1.9 Add UID collision retry (L9)
- In `_gen_uid()`, add a retry loop (max 3 attempts) checking `_load_loop(session_id, uid)` before returning. If collision detected, generate a new one.
- This is defensive; probability is low but nonzero.

#### 1.10 Tests for Phase 1
- `test_max_turns_enforced` — verify loop auto-pauses after N turns.
- `test_pause_one_does_not_stop_scheduler_for_others` — create 2 loops, pause 1, verify other still ticks.
- `test_resume_preserves_interval` — resume sets `last_fired_at = now`, not 0.
- `test_db_cache_thread_safety` — mock slow import, verify lock prevents double creation.
- `test_delete_meta_actually_deletes` — verify `delete_meta` called, not `set_meta(..., "")`.
- `test_interval_clamping_warning` — verify response contains "adjusted" notice.
- `test_max_interval_cap` — verify "365d" capped to 30d with notice.
- `test_uid_collision_retry` — mock `uuid.uuid4().hex[:6]` to return duplicate once, verify retry succeeds.

---

### Phase 2: TUI Integration Fixes (tui_gateway/server.py)
**Goal:** Fix TUI-specific lifecycle and dispatch issues.  
**Estimated:** ~80 lines changed, 4-6 new tests.

#### 2.1 Shutdown LoopManager on session cleanup (M2)
- In the session cleanup block (`_sessions.get(sid) is not current`), add:
  ```python
  mgr = current.get("_loop_manager")
  if mgr is not None:
      try:
          mgr.shutdown()
      except Exception:
          pass
  ```

#### 2.2 Emit message.end on dispatch failure (C4)
- In `_make_tui_dispatch`, in the `except Exception:` block, after setting `session["running"] = False`, add `_emit("message.end", sid, {"error": "loop dispatch failed"})`.
- Also log the exception at WARNING level (addresses F8 from review A).

#### 2.3 Rate-limit burst fires (C3) — TUI side
- In `_make_tui_dispatch`, after a successful dispatch, record `session["last_loop_fire"] = time.time()`.
- In the LoopScheduler's `_tick()` (or in `_dispatch` itself), reject additional fires within `BURST_COOLDOWN_SECONDS = 2`.
- This prevents N back-to-back prompts when N loops are all overdue.

#### 2.4 Tests for Phase 2
- `test_session_cleanup_shuts_down_loop_manager` — verify `mgr.shutdown()` called on session replace.
- `test_dispatch_failure_emits_message_end` — mock `_run_prompt_submit` to raise, verify `message.end` emitted.
- `test_burst_fire_rate_limited` — create 3 overdue loops, verify only 1 fires per tick with 2s cooldown.

---

### Phase 3: Unify CLI/Gateway Handlers (new module + refactor)
**Goal:** Eliminate duplication, fix "every" syntax gap, add CLI tests.  
**Estimated:** ~200 lines new, ~300 lines removed, 10-15 new tests.

#### 3.1 Extract shared handler logic
- Create `hermes_cli/loop_commands.py` with a pure function:
  ```python
  def handle_loop_command(
      text: str,
      *,
      cron_api: Callable[..., dict],
      output: Callable[[str], None],   # _cprint for CLI, accumulate for gateway
      check_gateway_running: Optional[Callable[[], bool]] = None,
  ) -> None:
      ...
  ```
- This function handles: list, pause, resume, remove, clear, create (including "every" syntax).
- It returns structured data; callers format for their output medium.

#### 3.2 Refactor CLI handler
- Replace `cli.py:_handle_loop_command` (~180 lines) with a thin wrapper:
  ```python
  def _handle_loop_command(self, cmd: str):
      from hermes_cli.loop_commands import handle_loop_command
      def _cron_api(**kwargs):
          return json.loads(cronjob_tool(**kwargs))
      def _output(text: str):
          _cprint(text)
      handle_loop_command(cmd, cron_api=_cron_api, output=_output)
  ```

#### 3.3 Refactor Gateway handler
- Replace `gateway/run.py:_handle_loop_command` (~140 lines) with a thin async wrapper:
  ```python
  async def _handle_loop_command(self, event: MessageEvent) -> str:
      from hermes_cli.loop_commands import handle_loop_command
      lines: list[str] = []
      def _cron_api(**kwargs):
          return json.loads(await asyncio.to_thread(cronjob, **kwargs))
      def _output(text: str):
          lines.append(text)
      handle_loop_command(event.text, cron_api=_cron_api, output=_output)
      return "\n".join(lines)
  ```

#### 3.4 Fix "every" syntax in gateway (M6)
- The shared `handle_loop_command` strips the "every " prefix before parsing the schedule, so both CLI and gateway support it.

#### 3.5 Add CLI handler tests (L6)
- Add `tests/hermes_cli/test_loop_cli_handler.py` with tests for:
  - `every 5m` syntax
  - gateway-running warning
  - list/pause/resume/remove/clear flows
  - short interval warning

#### 3.6 Tests for Phase 3
- `test_shared_handler_list_empty` / `test_shared_handler_list_with_jobs`
- `test_shared_handler_create_every_syntax` — verify "every 30m" parsed correctly
- `test_shared_handler_clear_partial_failure` — mock cron_api to fail on 2nd removal, verify error logged
- `test_cli_gateway_output_equivalent` — same input produces semantically equivalent actions

---

### Phase 4: Cross-Backend Visibility (TUI ↔ Cron sync)
**Goal:** Make loops visible across all interfaces.  
**Estimated:** ~250 lines changed, 6-10 new tests.  
**Note:** This is the most invasive phase. It can be deferred if unification is deemed too risky.

#### 4.1 Design: TUI uses cron backend for persistence
- Modify `LoopManager` to optionally use the cron system instead of SessionDB.
- Add a `backend: str = "sessiondb" | "cron"` parameter to `LoopManager.__init__`.
- When `backend="cron"`, `add()` creates a cron job, `pause()` pauses it, `resume()` resumes it, `clear()` removes it.
- `status_line()` lists cron jobs filtered by `name.startswith("loop:")`.

#### 4.2 TUI migration
- In `tui_gateway/server.py`, change `LoopManager` initialization to use `backend="cron"`.
- The `LoopScheduler` daemon thread becomes optional — cron handles scheduling.
- Keep `LoopScheduler` for the `"sessiondb"` backend path so tests and backward compat still work.

#### 4.3 SessionDB cleanup
- On TUI startup with `backend="cron"`, read existing SessionDB loops and migrate them to cron jobs (one-time migration).
- After migration, clear SessionDB loop keys.

#### 4.4 Tests for Phase 4
- `test_loop_manager_cron_backend_create_list_pause_resume_clear`
- `test_loop_manager_migrate_from_sessiondb` — verify old SessionDB loops become cron jobs
- `test_cross_visibility` — create loop in TUI, verify visible in CLI/gateway list

---

## 4. Test Plan Summary

| Phase | New Tests | Files |
|---|---|---|
| 1 | 8 | `tests/hermes_cli/test_loop_manager.py`, `tests/test_loop.py` |
| 2 | 4 | `tests/test_tui_loop.py` (new) or extend `tests/gateway/test_loop_command.py` |
| 3 | 12 | `tests/hermes_cli/test_loop_cli_handler.py` (new), `tests/hermes_cli/test_loop_commands.py` (new) |
| 4 | 8 | `tests/hermes_cli/test_loop_manager.py`, `tests/gateway/test_loop_command.py` |
| **Total** | **~32** | |

All existing tests must continue to pass. No breaking changes to public API (`LoopState`, `LoopManager`, `LoopScheduler` signatures remain stable except for removal of dead parameters).

---

## 5. Rollback / Risk Mitigation

- **Phase 1-3 are safe** — they fix bugs and refactor duplication without changing the dual-backend architecture. Each phase is independently reviewable and revertible.
- **Phase 4 is optional** — if the cron migration proves too complex or risky, we can ship Phases 1-3 and defer Phase 4. The system works correctly with dual backends; the only issue is cross-visibility.
- **Feature flag:** Phase 4 can be gated behind a `loop.backend: cron` config key, defaulting to `sessiondb` for backward compatibility.

---

## 6. Files to Touch

| File | Phase | Change |
|---|---|---|
| `hermes_cli/loop.py` | 1 | Bug fixes, dead code removal, thread safety |
| `tui_gateway/server.py` | 2 | Session cleanup, dispatch error handling, burst cooldown |
| `hermes_cli/loop_commands.py` | 3 | **New file** — shared CLI/gateway handler |
| `cli.py` | 3 | Replace `_handle_loop_command` with thin wrapper |
| `gateway/run.py` | 3 | Replace `_handle_loop_command` with thin wrapper |
| `tests/hermes_cli/test_loop_manager.py` | 1 | Add tests for max turns, pause scope, resume interval, cache safety |
| `tests/test_loop.py` | 1 | Add tests for clamping, max cap, UID collision |
| `tests/hermes_cli/test_loop_command.py` | 3 | Extend with CLI handler tests |
| `tests/gateway/test_loop_command.py` | 2, 3 | Extend with TUI dispatch failure, burst limit tests |
| `tests/hermes_cli/test_loop_commands.py` | 3 | **New file** — tests for shared handler |
| `tests/test_tui_loop.py` | 2 | **New file** — TUI-specific loop lifecycle tests |

---

## 7. Acceptance Criteria

- [ ] `MAX_TURNS` is enforced — loops auto-stop after reaching the limit.
- [ ] Pausing one loop does not stop scheduling for other active loops.
- [ ] Resuming a loop respects the original interval (no immediate refire unless requested).
- [ ] `_DB_CACHE` is thread-safe.
- [ ] Metadata deletion actually deletes keys (no empty-string orphans).
- [ ] Interval clamping and capping produce user-visible warnings.
- [ ] TUI session cleanup stops the `LoopManager` scheduler.
- [ ] TUI dispatch failures emit `message.end` and log warnings.
- [ ] CLI and gateway share the same `/loop` handler logic (single source of truth).
- [ ] Gateway supports `"every"` syntax like CLI.
- [ ] All new code has test coverage; existing tests pass.
- [ ] (Phase 4) Loops created in TUI are visible in CLI/gateway `list` and vice versa.
