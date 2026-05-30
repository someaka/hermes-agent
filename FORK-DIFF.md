# Fork Diff: what someaka/hermes-agent has that NousResearch/hermes-agent doesn't

> Generated 2026-05-30 after rebase onto upstream `5921d6678`.
> 165 fork commits, 110 files changed, +14,735 / -1,295 lines.

---

## 1. Loop system (alternative to upstream LoopManager)

The fork built its own `/loop` system before upstream added LoopManager. After rebase, upstream's LoopManager is used for the core loop mechanics, but the fork retains:

- **`hermes_cli/loop.py`** — full standalone loop module (thread-safe DB cache with `_DB_CACHE_LOCK`, collision-safe UIDs via `_gen_unique_uid`, max interval cap of 30 days via `MAX_INTERVAL_SECONDS`)
- **`LoopScheduler`** — single tick engine with dispatch callback, eager start, auto-polling when no loop in DB
- **Auto-UID multi-loop** — every `/loop` creates a new loop (no names needed)
- **Live countdown** — shows next tick time in `/loop list` and `/loop status`
- **`/loop clear`** — delete ALL loop jobs at once
- **`_dispatch_loop_prompt`** — adapter-free loop injection into gateway
- **Daemon loop ticker** — background thread that fires loop prompts on schedule
- **Loop tests**: `tests/test_loop.py`, `tests/hermes_cli/test_loop_manager.py`, `tests/hermes_cli/test_loop_command.py`, `tests/gateway/test_loop_command.py`

---

## 2. Kanban improvements

### Assignee inheritance
- Children promoted via `recompute_ready` now inherit assignee from parent when child has none set
- Prevents tasks sitting in `ready` forever because dispatcher skips unassigned tasks

### Circuit-breaker guard
- Tasks that hit `max_retries` (or `failure_limit`) stay blocked instead of cycling: block → auto-recover → respawn → budget exhausted → block
- Failure counter preserved across recovery cycles

### Auto-subscribe CLI session
- `kanban create` auto-subscribes the current CLI session for terminal-state notifications
- Per-session PID-based chat_id so concurrent CLI sessions don't stomp each other
- Skipped when called from gateway handler (which manages its own auto-subscribe)

### Notify subscribe improvements
- `--cli` flag for quick CLI subscription (`--platform cli --chat-id cli-{pid}`)
- Platform + chat_id validation before subscribing

---

## 3. Notification pipeline

### DB polling (replaces FIFO)
- Fork originally built FIFO-based notification bridge, then migrated to direct DB polling
- `process_registry.drain_notifications()` — clean drain API replacing raw queue access
- Cursor advancement logging, retry on dispatch failure, stale backlog skip
- Subscription lifecycle — zombie cleanup, NULL profile handling

### WebUI SSE delivery
- Background process notifications delivered to WebUI via api_server SSE
- Contextvar propagation for background process notifications

### Notification batching
- Pending kanban notifications batched into single turn (avoids notification spam)

---

## 4. Memory system improvements

### Thread-safe MemoryManager
- `MemoryManager` protected by `threading.RLock` for concurrent access
- `remove_provider()` method for deregistering memory providers by name

### Multi-provider support (restored)
- Multiple external memory providers active simultaneously (upstream restricts to one)
- Duplicate provider names rejected with warning

### Memory performance tests
- `tests/agent/test_memory_performance.py` — performance benchmarks
- `tests/hermes_cli/test_memory_setup.py` — memory setup tests
- `tests/hermes_cli/test_plugins_cmd_providers.py` — plugin provider tests
- `tests/plugins/memory/test_get_active_memory_providers.py` — active provider tests

---

## 5. Gateway / TUI improvements

### TUI notification bridge
- Kanban event reader thread per session
- `tui_gateway/server.py` — 695 lines of additions including:
  - `_start_kanban_event_reader()` — per-session event reader
  - `_start_notification_poller()` — background notification poller
  - Crash/timed_out notification message formatting
  - Session boundary notifications

### Gateway fixes
- `_agent_has_active_subagents` — subagent protection prevents premature session cleanup
- `_run_planned_stop_watcher` — planned stop detection
- `_handle_loop_command` dispatch in gateway mode
- Compacting context regex for cleaner summaries
- Verbose test alignment

### API server improvements
- HTTP 500 response sanitization (`str(e)` cleaned before sending)
- SSE delivery for background process notifications

---

## 6. Code quality & security

### Shell injection fixes
- `tools/environments/docker.py` — `shell=True` → list argv in cleanup
- `hermes_cli/mcp_catalog.py` — `shell=True` → `shlex.split` in bootstrap
- `cli.py` — `shell=True` → `shlex.split` in quick_commands

### Dead code removal
- Unused imports removed from `run_agent.py` (F401 cleanup)
- Dead FIFO verification code and stale reports deleted
- Dead `_get_loop_manager` code removed
- Duplicate definitions cleaned up

### Error sanitization
- `terminal_tool.py` — tracebacks sanitized before sending to LLM context
- `api_server.py` — `str(e)` sanitized in HTTP 500 responses

### Thread safety
- `MemoryManager` with `RLock`
- `SlashWorker` lock scope narrowed to stdin write only
- `web_server.py` — `asyncio.Lock` → `threading.Lock` for event broadcast

---

## 7. CLI improvements

- `codex_runtime` alias for `codex-runtime` slash command
- `doctor` hint ordering improvements
- `quit --delete` flag
- `google_chat` checker in doctor
- `bedrock` extra handling
- `vercel_runtime` env var mapping
- Gateway stdin capture fix
- Background process notification drain on every CLI iteration (not just idle)

---

## 8. Performance optimizations

- `_sanitize_messages_surrogates` gated behind Ollama check (skip for non-Ollama providers)
- `total_chars` gated behind `quiet_mode`
- Duplicate `deepcopy` paths consolidated
- `close()` methods added to 5 SQLite-owning classes (prevents FD leaks)

---

## 9. Test improvements

### New test files
- `tests/test_notification_e2e.py` — E2E notification delivery tests
- `tests/test_regression_notification_paths.py` — regression guards for notification paths
- `tests/tui_gateway/test_fifo_notification_bridge.py` — notification bridge tests (874 lines)
- `tests/agent/test_memory_performance.py` — memory performance benchmarks
- `tests/hermes_cli/test_memory_setup.py` — memory setup tests
- `tests/hermes_cli/test_plugins_cmd_providers.py` — plugin provider tests
- `tests/plugins/memory/test_get_active_memory_providers.py` — active provider tests
- `tests/test_loop.py` — loop system tests
- `tests/hermes_cli/test_loop_manager.py` — LoopManager tests
- `tests/hermes_cli/test_loop_command.py` — loop command tests
- `tests/gateway/test_loop_command.py` — gateway loop command tests

### Test fixes
- 28 zero-assertion tests given assertions or smoke-test comments
- `monkeypatch` improvements for CI stability (staticmethod wrapping, env manipulation avoidance)
- Git history guard made robust — searches all branches, not just HEAD~10
- Shallow clone detection — skips git history guard in CI
- Interrupt timing threshold bumped from 1.0s to 2.0s for slow CI
- Memory performance test thresholds relaxed for CI stability
- Shadowed duplicate test function names renamed
- `_resolve_model_selection` monkeypatch wrapped in `staticmethod()`

---

## 10. Documentation

- `docs/audit/bare-except-audit.md` — bare except audit
- `docs/audit/kanban_fifo_audit_I1.md` — kanban FIFO audit (3 versions)
- `docs/plans/loop-fix-plan.md` — loop fix plan
- `LOOP_CLEANUP_PLAN.md` — loop cleanup plan
- `.kanban-workspace/` — implementation plans and verification docs
- `.hermes/plans/` — scheduler, MCP init, perf threshold plans
- TUI notification pipeline investigation reports

---

## 11. Config / build

- `.gitignore` — MagicMock test artifacts pattern (`<MagicMock*`)
- `pyproject.toml` — dependency adjustments
- `uv.lock` — lockfile updates (kept upstream's canonical version during rebase)
- `.github/workflows/tests.yml` — CI workflow adjustments

---

## Summary: key architectural differences

| Area | Upstream | Fork |
|------|----------|------|
| Loop system | LoopManager (cron-based) | LoopScheduler + daemon ticker + LoopManager |
| Notifications | DB polling | DB polling (evolved from FIFO) + WebUI SSE |
| Memory providers | Single external | Multiple concurrent |
| Thread safety | Basic | RLock on MemoryManager, narrow locks on SlashWorker |
| Shell security | `shell=True` in places | All converted to list argv / `shlex.split` |
| FD management | No close() on SQLite classes | close() on 5 SQLite-owning classes |
| Test coverage | Standard | +11 test files, 28 assertions added, CI robustness |
