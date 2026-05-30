# Upstream Issue/PR Scan — Fork Features vs NousResearch/hermes-agent

> Generated 2026-05-30. Scanned open/closed issues and PRs for overlap with fork-specific features.

---

## 1. Loop system (LoopScheduler, daemon ticker, /loop clear)

### Existing issues
- #3752: "Long-running cron jobs block the scheduler tick loop" — **open** — low relevance (upstream cron, not our loop module)
- #22397: "CLI agent loops indefinitely" — **open** — irrelevant (agent behavior, not loop scheduling)

### Existing PRs
- (none found)

### Assessment
- **Duplicate risk**: none
- **Recommendation**: no action — upstream has LoopManager; fork's LoopScheduler is a separate standalone module, no overlap
- **Gaps**: `/loop clear`, live countdown, auto-UID multi-loop are all fork-unique

---

## 2. Kanban improvements

### Assignee inheritance
- (no matching issues found)

### Circuit-breaker guard
- **#29320**: "kanban dispatcher: add circuit-breaker for repeated worker bails with identical block reason" — **open** — **HIGH relevance** — exact feature match

### Auto-subscribe CLI session
- **#19479**: "feat(kanban): kanban_create tool should auto-subscribe originating gateway chat to notifications" — **open** — **HIGH relevance** — exact feature match

### Notify subscribe improvements
- (no matching issues found)

### Assessment
- **Duplicate risk**: **HIGH** for circuit-breaker (#29320) and auto-subscribe (#19479)
- **Recommendation**: comment on #29320 and #19479 with our implementation details; these are open requests that our fork already solves
- **Gaps**: assignee inheritance, `--cli` flag for quick subscription — no upstream issues exist

---

## 3. Notification pipeline

### DB polling / drain_notifications
- (no matching issues found for `drain_notifications`)

### WebUI SSE delivery
- (no matching issues found)

### Notification batching
- #10478: "CLI: remove noisy 'preparing <tool>…' messages" — **open** — low relevance (different problem)

### Assessment
- **Duplicate risk**: none
- **Recommendation**: no action — notification pipeline is fork-unique infrastructure
- **Gaps**: `drain_notifications()`, SSE delivery for background processes, notification batching — all have zero upstream coverage

---

## 4. Memory system improvements

### Thread-safe MemoryManager (RLock)
- #5129: "bug: background memory review creates second provider instance on same DB" — **open** (with PR #5140) — **MEDIUM relevance** — related concurrency issue but different root cause

### Multi-provider / remove_provider
- #14218: "Credential pool entries persist after custom_provider removal" — **open** — low relevance (credential pools, not memory providers)

### Memory performance tests
- (no matching issues found)

### Assessment
- **Duplicate risk**: low
- **Recommendation**: #5129 is tangentially related — our RLock approach prevents this class of issue; worth a comment noting the thread-safety angle
- **Gaps**: multi-provider concurrent memory, `remove_provider()`, memory performance tests — all fork-unique

---

## 5. Shell injection / security

### Existing issues
- **#10692**: "shell=True in config-driven execution paths bypasses terminal tool safety controls" — **open** — **HIGH relevance**
- **#2743**: "[Bug]: Command injection risk via shell=True in subprocess calls" — **open** — **HIGH relevance**
- **#16560**: "Command injection via shell=True in tui_gateway/server.py" — **open** — **HIGH relevance**

### Existing PRs
- (no merged PRs found fixing these)

### Assessment
- **Duplicate risk**: **HIGH** — 3 open issues describe the exact problem our fork fixed
- **Recommendation**: comment on #2743 (oldest, most general) with our specific fixes: `docker.py` list argv, `mcp_catalog.py` shlex.split, `cli.py` shlex.split. Could also reference #10692 and #16560.
- **Gaps**: our fixes are complete for the 3 files we touched; upstream still has `shell=True` in those paths

---

## 6. Error sanitization

### Existing issues
- #19814: "custom-tools plugin tool results cause KeyError: slice(None, 500, None)" — **open** — low relevance (different bug)
- #13868: "resolve_session_name sanitizes gateway_session_key without length truncation" — **open** — low relevance

### Assessment
- **Duplicate risk**: none
- **Recommendation**: no action — terminal traceback sanitization and HTTP 500 str(e) cleaning are fork-unique

---

## 7. FD management / SQLite close()

### Existing issues
- **#31130**: "kanban-db: WAL file descriptor leak on connect/close cycles" — **PR** — **HIGH relevance** — introduces `_WalSafeConnection` to force FD cleanup
- **#28802**: "[Bug]: kanban specify helpers leak sqlite connections in long-lived processes" — **open** — **HIGH relevance** — exact same class of bug
- **#33580**: "kanban_db.py: connection leak causes 'Too many open files' on macOS" — **open** — **HIGH relevance** — exact same class of bug

### Assessment
- **Duplicate risk**: **HIGH** — 3 issues/PRs describe the exact FD leak problem our fork's `close()` methods address
- **Recommendation**: check if PR #31130 was merged; if so, our `close()` methods may overlap with their `_WalSafeConnection`. Comment on #28802 and #33580 noting our approach (close() on 5 SQLite-owning classes)
- **Gaps**: our approach is simpler (explicit close() calls) vs upstream's `_WalSafeConnection` subclass — different strategy, same goal

---

## 8. TUI notification bridge

### Existing issues
- (no matching issues found)

### Assessment
- **Duplicate risk**: none
- **Recommendation**: no action — TUI kanban event reader and notification poller are fork-unique

---

## 9. Gateway subagent protection

### Existing issues
- **#28547**: "Guardrail: warn before /new chat when subagents or background tasks are still running" — **open** — **MEDIUM relevance** — related but different scope (warning vs blocking)

### Assessment
- **Duplicate risk**: medium
- **Recommendation**: comment on #28547 noting our `_agent_has_active_subagents` implementation that actually blocks cleanup rather than just warning
- **Gaps**: our approach prevents premature session cleanup; upstream issue only asks for a warning

---

## 10. Performance optimizations

### Existing issues
- (no matching issues found for surrogates gating, quiet_mode, deepcopy consolidation)

### Assessment
- **Duplicate risk**: none
- **Recommendation**: no action — these are internal optimizations with no upstream tracking

---

## 11. Test improvements

### Existing issues
- #33211: "Slash command aliases appear as separate entries in autocomplete list" — **open** — low relevance (UI, not tests)
- #15187: "[Bug]: test_gateway_service systemd refresh tests fail in non..." — **open** — low relevance

### Assessment
- **Duplicate risk**: none
- **Recommendation**: no action — test improvements (zero-assertion fixes, monkeypatch, CI robustness) are fork-unique quality work

---

## 12. CLI improvements

### Existing issues
- #33211: "Slash command aliases appear as separate entries in autocomplete list" — **open** — MEDIUM relevance (our `codex_runtime` alias could trigger this)

### Assessment
- **Duplicate risk**: low
- **Recommendation**: be aware of #33211 if submitting our alias work upstream

---

## Summary: actions to take

| Priority | Action | Issue/PR |
|----------|--------|----------|
| **HIGH** | Comment with our circuit-breaker implementation | #29320 |
| **HIGH** | Comment with our auto-subscribe implementation | #19479 |
| **HIGH** | Comment with our shell injection fixes (3 files) | #2743, #10692, #16560 |
| **HIGH** | Comment with our close() FD management approach | #28802, #33580 |
| **MEDIUM** | Check if PR #31130 merged; compare approaches | #31130 |
| **MEDIUM** | Comment on subagent protection (blocking vs warning) | #28547 |
| **MEDIUM** | Note thread-safety angle for memory concurrency | #5129 |
| LOW | No action needed for loop, notifications, error sanitization, perf, tests | — |

### Features with ZERO upstream coverage (fork-unique)
- `drain_notifications()` API
- WebUI SSE delivery for background processes
- Notification batching
- Multi-provider concurrent memory
- `remove_provider()` method
- Memory performance tests
- TUI kanban event reader / notification poller
- `/loop clear`, live countdown, auto-UID multi-loop
- Assignee inheritance in recompute_ready
- `--cli` quick subscription flag
- deepcopy consolidation, surrogates gating, quiet_mode optimization
