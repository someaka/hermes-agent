# Bare except:Exception Audit Report

> Generated: 2026-05-25
> Scope: `hermes_cli/kanban_db.py` + `tui_gateway/server.py`
> Rule: CORRECT = genuinely needs broad catch (crash logs, atexit cleanup, re-raise)
>       NEEDS-SPECIFIC = should catch ImportError/OSError/ValueError/JSONDecodeError/etc
>       NEEDS-LOGGING = correct to catch broadly but should log instead of silent pass

---

## Summary

| File | CORRECT | NEEDS-SPECIFIC | NEEDS-LOGGING | Total |
|------|---------|----------------|---------------|-------|
| kanban_db.py | 8 | 9 | 5 | 22 |
| server.py | 31 | 23 | 41 | 95 |
| **TOTAL** | **39** | **32** | **46** | **117** |

---

## hermes_cli/kanban_db.py (22 bare excepts)

### CORRECT (8)

#### K1 — Line 1198
```python
# threads from racing through the additive ALTER TABLE pass with
                # stale PRAGMA snapshots during gateway startup.
                conn.executescript(SCHEMA_SQL)
                _migrate_add_optional_columns(conn)
                _INITIALIZED_PATHS.add(resolved)
    except Exception:
        conn.close()
        raise
    return conn
```
**Connection cleanup on schema init failure — closes then re-raises.**

#### K2 — Line 1482
```python
atomic -- at most one concurrent writer can succeed.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
```
**Transaction rollback guard — rolls back then re-raises.**

### NEEDS-SPECIFIC (9)

#### K3 — Line 673
```python
if "skills" in keys and row["skills"]:
            try:
                parsed = json.loads(row["skills"])
                if isinstance(parsed, list):
                    skills_value = [str(s) for s in parsed if s]
            except Exception:
                skills_value = None
        return cls(
            id=row["id"],
            title=row["title"],
            body=row["body"],
```
**JSON parse of skills. Should catch `json.JSONDecodeError`, `TypeError`.**

#### K4 — Line 766
```python
@classmethod
    def from_row(cls, row: sqlite3.Row) -> "Run":
        try:
            meta = json.loads(row["metadata"]) if row["metadata"] else None
        except Exception:
            meta = None
        return cls(
            id=int(row["id"]),
            task_id=row["task_id"],
            profile=row["profile"],
```
**JSON parse of metadata. Should catch `json.JSONDecodeError`, `TypeError`.**

#### K5 — Line 1511
```python
def _claimer_id() -> str:
    """Return a ``host:pid`` string that identifies this claimer."""
    import socket
    try:
        host = socket.gethostname() or "unknown"
    except Exception:
        host = "unknown"
    return f"{host}:{os.getpid()}"


# ---------------------------------------------------------------------------
```
**socket.gethostname(). Should catch `socket.error`.**

#### K6 — Line 2042
```python
).fetchall()
    out = []
    for r in rows:
        try:
            payload = json.loads(r["payload"]) if r["payload"] else None
        except Exception:
            payload = None
        out.append(
            Event(
                id=r["id"],
                task_id=r["task_id"],
```
**JSON parse of event payload. Should catch `json.JSONDecodeError`, `TypeError`.**

### NEEDS-LOGGING (5)

## tui_gateway/server.py (95 bare excepts)

### CORRECT (31)

#### S1 — Line 60
```python
with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"\n=== unhandled exception · {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
            )
            f.write(trace)
    except Exception:
        pass
    # Stderr goes through to the TUI as a gateway.stderr Activity line —
    # the first line here is what the user will see without opening any
    # log files.  Rest of the stack is still in the log for full context.
    first = (
```
**Crash logger fallback — nowhere else to log.**

#### S2 — Line 93
```python
f.write(
                f"\n=== thread exception · {time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"· thread={args.thread.name} ===\n"
            )
            f.write(trace)
    except Exception:
        pass
    first_line = (
        str(args.exc_value).strip().splitlines()[0]
        if str(args.exc_value).strip()
        else args.exc_type.__name__
```
**Thread exception logger fallback.**

#### S3 — Line 113
```python
try:
    from hermes_cli.banner import prefetch_update_check

    prefetch_update_check()
except Exception:
    pass

from tui_gateway.render import make_stream_renderer, render_diff, render_message

_sessions: dict[str, dict] = {}
```
**Import-time prefetch — must not block startup.**

#### S4 — Line 151
```python
# don't block future TUI starts (open() on a stale FIFO blocks forever).
try:
    os.mkfifo(_KANBAN_FIFO_PATH, 0o600)
except FileExistsError:
    pass  # Leftover from prior run — safe to reuse
except Exception:
    pass  # FIFO not available on this platform (e.g. Windows)


def _cleanup_kanban_fifo() -> None:
    try:
```
**mkfifo platform probe — Windows lacks FIFOs.**

#### S5 — Line 159
```python
def _cleanup_kanban_fifo() -> None:
    try:
        if os.path.exists(_KANBAN_FIFO_PATH):
            os.unlink(_KANBAN_FIFO_PATH)
    except Exception:
        pass


atexit.register(_cleanup_kanban_fifo)
```
**atexit FIFO cleanup — must not fail on exit.**

#### S6 — Line 207
```python
# FIFO removed or TUI shutting down — recreate if missing
                # so future writers can connect.
                if not os.path.exists(_KANBAN_FIFO_PATH):
                    try:
                        os.mkfifo(_KANBAN_FIFO_PATH, 0o600)
                    except Exception:
                        logger.warning(
                            "kanban_fifo_reader: failed to recreate FIFO",
                            exc_info=True,
                        )
                time.sleep(0.5)
```
**FIFO recreate failure — already logs with warning.**

#### S7 — Line 213
```python
logger.warning(
                            "kanban_fifo_reader: failed to recreate FIFO",
                            exc_info=True,
                        )
                time.sleep(0.5)
            except Exception:
                logger.exception("kanban_fifo_reader_error")
                time.sleep(1.0)

    _t = threading.Thread(target=_reader, daemon=True, name="kanban-fifo-global")
    _t.start()
```
**FIFO reader outer loop — already logs with exception.**

#### S8 — Line 328
```python
session["running"] = True
                        _rid = f"__kanban__{int(time.time() * 1000)}"
                        try:
                            _emit("message.start", sid)
                            _run_prompt_submit(_rid, sid, session, _msg)
                        except Exception:
                            with session["history_lock"]:
                                session["running"] = False
        finally:
            _conn.close()
    except Exception:
```
**Dispatch inner — must reset running state on ANY failure.**

#### S9 — Line 333
```python
except Exception:
                            with session["history_lock"]:
                                session["running"] = False
        finally:
            _conn.close()
    except Exception:
        logger.debug("kanban_notification_dispatch failed", exc_info=True)


def _start_kanban_fifo_reader(sid: str, session: dict) -> threading.Thread:
    """Ensure the global kanban FIFO reader is running.
```
**Dispatch outer — already logs with warning.**

#### S10 — Line 471
```python
def close(self):
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                self.proc.wait(timeout=1)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
```
**Process terminate fails — escalate to kill.**

#### S11 — Line 474
```python
self.proc.terminate()
                self.proc.wait(timeout=1)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


def _load_busy_input_mode() -> str:
    display = _load_cfg().get("display")
```
**Process kill fails — give up.**

#### S12 — Line 492
```python
"""Fire session lifecycle hooks with CLI parity."""
    try:
        from hermes_cli.plugins import invoke_hook as _invoke_hook

        _invoke_hook(event_type, session_id=session_id, platform="tui")
    except Exception:
        pass


def _finalize_session(session: dict | None, end_reason: str = "tui_close") -> None:
    """Best-effort finalize hook + memory commit for a session."""
```
**Session lifecycle hook — best-effort.**

#### S13 — Line 515
```python
else:
        history = list(session.get("history", []))
    if agent is not None and history and hasattr(agent, "commit_memory_session"):
        try:
            agent.commit_memory_session(history)
        except Exception:
            pass

    session_key = session.get("session_key")
    session_id = getattr(agent, "session_id", None) or session_key
    _notify_session_boundary("on_session_finalize", session_id)
```
**Memory commit on finalize — best-effort.**

#### S14 — Line 531
```python
if session_id:
        try:
            db = _get_db()
            if db is not None:
                db.end_session(session_id, end_reason)
        except Exception:
            pass


def _shutdown_sessions() -> None:
    for session in list(_sessions.values()):
```
**end_session DB call — best-effort on shutdown.**

#### S15 — Line 542
```python
_finalize_session(session, end_reason="tui_shutdown")
        try:
            worker = session.get("slash_worker")
            if worker:
                worker.close()
        except Exception:
            pass


atexit.register(_shutdown_sessions)
```
**slash_worker close on shutdown — best-effort.**

#### S16 — Line 635
```python
with Image.open(path) as img:
            width, height = img.size
        meta["width"] = int(width)
        meta["height"] = int(height)
        meta["token_estimate"] = _estimate_image_tokens(int(width), int(height))
    except Exception:
        pass
    return meta


def _ok(rid, result: dict) -> dict:
```
**Image metadata extraction — optional.**

#### S17 — Line 830
```python
finally:
            if _sessions.get(sid) is not current:
                if worker is not None:
                    try:
                        worker.close()
                    except Exception:
                        pass
                if notify_registered:
                    try:
                        from tools.approval import unregister_gateway_notify
```
**Session init cleanup — worker.close in finally.**

#### S18 — Line 837
```python
if notify_registered:
                    try:
                        from tools.approval import unregister_gateway_notify

                        unregister_gateway_notify(key)
                    except Exception:
                        pass
            ready.set()

    threading.Thread(target=_build, daemon=True).start()
```
**Session init cleanup — unregister in finally.**

#### S19 — Line 859
```python
session["running"] = True
        try:
            _emit("message.start", sid)
            _run_prompt_submit(None, sid, session, prompt)
            return True
        except Exception:
            with session["history_lock"]:
                session["running"] = False
            return False
    return _dispatch
```
**Top-level dispatch guard — must reset running state.**

#### S20 — Line 1324
```python
def _restart_slash_worker(session: dict):
    worker = session.get("slash_worker")
    if worker:
        try:
            worker.close()
        except Exception:
            pass
    try:
        session["slash_worker"] = _SlashWorker(
            session["session_key"],
            getattr(session.get("agent"), "model", _resolve_model()),
```
**_restart_slash_worker cleanup — best-effort close.**

#### S21 — Line 1546
```python
yolo_was_on = False
        if yolo_was_on:
            try:
                enable_session_yolo(new_session_id)
                disable_session_yolo(old_key)
            except Exception:
                pass
        try:
            register_gateway_notify(
                new_session_id,
                lambda data: _emit("approval.request", sid, data),
```
**yolo enable/disable — optional feature toggle.**

#### S22 — Line 1553
```python
try:
            register_gateway_notify(
                new_session_id,
                lambda data: _emit("approval.request", sid, data),
            )
        except Exception:
            pass
    except Exception:
        # Even if the approval module fails to import, still anchor the
        # session_key on the new continuation id so downstream lookups
        # don't keep targeting the ended row.
```
**Approval register — optional module.**

#### S23 — Line 1555
```python
new_session_id,
                lambda data: _emit("approval.request", sid, data),
            )
        except Exception:
            pass
    except Exception:
        # Even if the approval module fails to import, still anchor the
        # session_key on the new continuation id so downstream lookups
        # don't keep targeting the ended row.
        session["session_key"] = new_session_id
```
**Critical fallback — must always set session_key.**

#### S24 — Line 1566
```python
if clear_pending_title:
        session["pending_title"] = None
    if restart_slash_worker:
        try:
            _restart_slash_worker(session)
        except Exception:
            pass


def _get_usage(agent) -> dict:
    g = lambda k, fb=None: getattr(agent, k, 0) or (getattr(agent, fb, 0) if fb else 0)
```
**Slash worker restart — non-critical.**

#### S25 — Line 2631
```python
"started_at": row.get("started_at") or 0,
                    "source": row.get("source") or "",
                },
            )
        return _ok(rid, {"session_id": None})
    except Exception:
        logger.exception("session.most_recent failed")
        return _ok(rid, {"session_id": None})


@method("session.resume")
```
**session.most_recent — already logs with exception.**

#### S26 — Line 3041
```python
_finalize_session(session)
    try:
        from tools.approval import unregister_gateway_notify

        unregister_gateway_notify(session["session_key"])
    except Exception:
        pass
    try:
        agent = session.get("agent")
        if agent and hasattr(agent, "close"):
            agent.close()
```
**session.close unregister — best-effort cleanup.**

#### S27 — Line 3047
```python
pass
    try:
        agent = session.get("agent")
        if agent and hasattr(agent, "close"):
            agent.close()
    except Exception:
        pass
    try:
        worker = session.get("slash_worker")
        if worker:
            worker.close()
```
**session.close agent.close — best-effort cleanup.**

#### S28 — Line 3053
```python
pass
    try:
        worker = session.get("slash_worker")
        if worker:
            worker.close()
    except Exception:
        pass
    return _ok(rid, {"closed": True})


@method("session.branch")
```
**session.close worker.close — best-effort cleanup.**

#### S29 — Line 3126
```python
_clear_pending(params.get("session_id", ""))
    try:
        from tools.approval import resolve_gateway_approval

        resolve_gateway_approval(session["session_key"], "deny", resolve_all=True)
    except Exception:
        pass
    return _ok(rid, {"status": "interrupted"})


# ── Delegation: subagent tree observability + controls ───────────────
```
**Interrupt deny approvals — best-effort.**

#### S30 — Line 3854
```python
f.write(
                        f"\n=== turn-dispatcher exception · "
                        f"{time.strftime('%Y-%m-%d %H:%M:%S')} · sid={sid} ===\n"
                    )
                    f.write(trace)
            except Exception:
                pass
            print(
                f"[gateway-turn] {type(e).__name__}: {e}", file=sys.stderr, flush=True
            )
            _emit("error", sid, {"message": str(e)})
```
**Turn dispatcher crash log write — nowhere else to log.**

#### S31 — Line 6124
```python
payload["warning"] = warning
        return _ok(rid, payload)
    except Exception as e:
        try:
            worker.close()
        except Exception:
            pass
        session["slash_worker"] = None
        return _err(rid, 5030, str(e))
```
**slash.exec worker.close cleanup — must not fail.**

### NEEDS-SPECIFIC (23)

#### S32 — Line 197
```python
_kanban_fifo_queue.put(_data, block=False)
                        except queue.Full:
                            logger.debug(
                                "kanban_fifo_queue full; dropped notification"
                            )
                        except Exception:
                            logger.debug(
                                "kanban_fifo_reader: bad JSON line", exc_info=True
                            )
            except (OSError, IOError):
                # FIFO removed or TUI shutting down — recreate if missing
```
**Bad JSON in FIFO. Already logs but should catch `json.JSONDecodeError`.**

#### S33 — Line 778
```python
current["agent"] = agent

            try:
                worker = _SlashWorker(key, getattr(agent, "model", _resolve_model()))
                current["slash_worker"] = worker
            except Exception:
                pass

            try:
                from tools.approval import (
                    register_gateway_notify,
```
**_SlashWorker init. Should catch `OSError`, `ImportError`.**

#### S34 — Line 792
```python
register_gateway_notify(
                    key, lambda data: _emit("approval.request", sid, data)
                )
                notify_registered = True
                load_permanent_allowlist()
            except Exception:
                pass

            _wire_callbacks(sid)
            _sessions[sid]["_notif_stop"] = _start_notification_poller(sid, _sessions[sid])
            _sessions[sid]["_kanban_fifo_thread"] = _start_kanban_fifo_reader(sid, _sessions[sid])
```
**Approval register. Should catch `ImportError`.**

#### S35 — Line 820
```python
lk = current.get("session_key") or sid
                    current["_loop_manager"] = LoopManager(
                        session_id=lk,
                        dispatch=_make_tui_dispatch(current, sid),
                    )
                except Exception:
                    pass
        except Exception as e:
            current["agent_error"] = str(e)
            _emit("error", sid, {"message": f"agent init failed: {e}"})
        finally:
```
**LoopManager init. Should catch `ImportError`.**

#### S36 — Line 923
```python
with _cfg_lock:
            _cfg_cache = copy.deepcopy(data)
            _cfg_mtime = mtime
            _cfg_path = p
        return data
    except Exception:
        pass
    return {}


def _save_cfg(cfg: dict):
```
**_load_cfg fallback. Should catch `FileNotFoundError`, `yaml.YAMLError`.**

#### S37 — Line 940
```python
with _cfg_lock:
        _cfg_cache = copy.deepcopy(cfg)
        _cfg_path = path
        try:
            _cfg_mtime = path.stat().st_mtime
        except Exception:
            _cfg_mtime = None


def _set_session_context(session_key: str) -> list:
    try:
```
**mtime stat. Should catch `OSError`.**

#### S38 — Line 949
```python
def _set_session_context(session_key: str) -> list:
    try:
        from gateway.session_context import set_session_vars

        return set_session_vars(session_key=session_key)
    except Exception:
        return []


def _clear_session_context(tokens: list) -> None:
    if not tokens:
```
**set_session_context. Should catch `ImportError`.**

#### S39 — Line 960
```python
return
    try:
        from gateway.session_context import clear_session_vars

        clear_session_vars(tokens)
    except Exception:
        pass


def _enable_gateway_prompts() -> None:
    """Route approvals through gateway callbacks instead of CLI input()."""
```
**clear_session_context. Should catch `ImportError`.**

#### S40 — Line 1018
```python
"banner_logo": skin.banner_logo,
            "banner_hero": skin.banner_hero,
            "tool_prefix": skin.tool_prefix,
            "help_header": (skin.branding or {}).get("help_header", ""),
        }
    except Exception:
        return {}


def _resolve_model() -> str:
    env = (
```
**_load_skin. Should catch `ImportError`, `AttributeError`.**

#### S41 — Line 1067
```python
)
        detected = detect_static_provider_for_model(explicit_model, current_provider)
        if detected:
            provider, detected_model = detected
            return detected_model, provider
    except Exception:
        pass
    return model, None


def _write_config_key(key_path: str, value):
```
**_resolve_model_with_provider. Should catch `ImportError`, `ValueError`.**

#### S42 — Line 1191
```python
cfg = None
    fallback_notice = None

    try:
        from toolsets import validate_toolset
    except Exception:
        validate_toolset = None

    if explicit and validate_toolset is not None:
        built_in = [name for name in explicit if validate_toolset(name)]
        unresolved = [name for name in explicit if name not in built_in]
```
**validate_toolset import. Should catch `ImportError`.**

#### S43 — Line 1204
```python
try:
                from hermes_cli.plugins import discover_plugins

                discover_plugins()
                plugin_valid = [name for name in unresolved if validate_toolset(name)]
            except Exception:
                plugin_valid = []

            if plugin_valid:
                built_in.extend(plugin_valid)
                unresolved = [name for name in unresolved if name not in plugin_valid]
```
**Plugin discovery. Should catch `ImportError`.**

#### S44 — Line 1244
```python
continue
                if _parse_enabled_flag(server_cfg.get("enabled", True), default=True):
                    mcp_names.add(str(name))
                else:
                    mcp_disabled.add(str(name))
        except Exception:
            mcp_names = set()
            mcp_disabled = set()

        mcp_valid = [name for name in unresolved if name in mcp_names]
        disabled = [name for name in unresolved if name in mcp_disabled]
```
**MCP config read. Should catch `FileNotFoundError`, `json.JSONDecodeError`.**

#### S45 — Line 1297
```python
_get_platform_tools(cfg, "cli", include_default_mcp_servers=True)
        )
        if fallback_notice is not None:
            print(fallback_notice, file=sys.stderr, flush=True)
        return enabled or None
    except Exception:
        if fallback_notice is not None:
            print(
                "[tui] no valid HERMES_TUI_TOOLSETS entries and configured CLI toolsets could not be loaded; enabling all toolsets",
                file=sys.stderr,
                flush=True,
```
**Toolsets fallback. Should catch `ImportError`, `FileNotFoundError`.**

#### S46 — Line 1393
```python
from hermes_cli.config import get_compatible_custom_providers, load_config

        cfg = load_config()
        user_provs = cfg.get("providers")
        custom_provs = get_compatible_custom_providers(cfg)
    except Exception:
        pass

    result = switch_model(
        raw_input=model_input,
        current_provider=current_provider,
```
**Config load. Should catch `ImportError`, `FileNotFoundError`.**

#### S47 — Line 1535
```python
unregister_gateway_notify,
        )

        try:
            unregister_gateway_notify(old_key)
        except Exception:
            pass
        session["session_key"] = new_session_id
        try:
            yolo_was_on = is_session_yolo_enabled(old_key)
        except Exception:
```
**unregister_gateway_notify. Should catch `KeyError`.**

#### S48 — Line 1540
```python
except Exception:
            pass
        session["session_key"] = new_session_id
        try:
            yolo_was_on = is_session_yolo_enabled(old_key)
        except Exception:
            yolo_was_on = False
        if yolo_was_on:
            try:
                enable_session_yolo(new_session_id)
                disable_session_yolo(old_key)
```
**yolo check. Should catch `ImportError`, `KeyError`.**

#### S49 — Line 1610
```python
base_url=getattr(agent, "base_url", None),
        )
        usage["cost_status"] = cost.status
        if cost.amount_usd is not None:
            usage["cost_usd"] = float(cost.amount_usd)
    except Exception:
        pass
    return usage


def _probe_credentials(agent) -> str:
```
**_get_usage. Should catch `AttributeError`, `ImportError`.**

#### S50 — Line 1622
```python
try:
        key = getattr(agent, "api_key", "") or ""
        provider = getattr(agent, "provider", "") or ""
        if not key or key == "no-key-required":
            return f"No API key configured for provider '{provider}'. First message will fail."
    except Exception:
        pass
    return ""


def _probe_config_health(cfg: dict) -> str:
```
**_probe_credentials. Should catch `AttributeError`.**

#### S51 — Line 1665
```python
def _current_profile_name() -> str:
    try:
        from hermes_cli.profiles import get_active_profile_name

        return get_active_profile_name() or "default"
    except Exception:
        return "default"


def _session_info(agent) -> dict:
    reasoning_config = getattr(agent, "reasoning_config", None)
```
**_current_profile_name. Should catch `ImportError`.**

#### S52 — Line 1698
```python
try:
        from hermes_cli import __version__, __release_date__

        info["version"] = __version__
        info["release_date"] = __release_date__
    except Exception:
        pass
    try:
        from model_tools import get_toolset_for_tool

        for t in getattr(agent, "tools", []) or []:
```
**_session_info version. Should catch `ImportError`, `AttributeError`.**

#### S53 — Line 1708
```python
for t in getattr(agent, "tools", []) or []:
            name = t["function"]["name"]
            info["tools"].setdefault(get_toolset_for_tool(name) or "other", []).append(
                name
            )
    except Exception:
        pass
    try:
        from hermes_cli.banner import get_available_skills

        info["skills"] = get_available_skills()
```
**_session_info tools. Should catch `ImportError`, `AttributeError`.**

#### S54 — Line 1742
```python
def _tool_ctx(name: str, args: dict) -> str:
    try:
        from agent.display import build_tool_preview

        return build_tool_preview(name, args, max_len=80) or ""
    except Exception:
        return ""


_TUI_VERBOSE_TEXT_MAX_CHARS = 16_000
_TUI_VERBOSE_TEXT_MAX_LINES = 240
```
**_tool_ctx. Should catch `ImportError`, `AttributeError`.**

### NEEDS-LOGGING (41)

#### S55 — Line 1331
```python
try:
        session["slash_worker"] = _SlashWorker(
            session["session_key"],
            getattr(session.get("agent"), "model", _resolve_model()),
        )
    except Exception:
        session["slash_worker"] = None


def _persist_model_switch(result) -> None:
    from hermes_cli.config import save_config
```
**_SlashWorker creation fails silently. Should log at WARNING.**

#### S56 — Line 1714
```python
pass
    try:
        from hermes_cli.banner import get_available_skills

        info["skills"] = get_available_skills()
    except Exception:
        pass
    try:
        from tools.mcp_tool import get_mcp_status

        info["mcp_servers"] = get_mcp_status()
```
**_session_info skills. Fails silently. Should log at DEBUG.**

#### S57 — Line 1720
```python
pass
    try:
        from tools.mcp_tool import get_mcp_status

        info["mcp_servers"] = get_mcp_status()
    except Exception:
        info["mcp_servers"] = []
    try:
        info["system_prompt"] = getattr(agent, "_cached_system_prompt", "") or ""
    except Exception:
        pass
```
**_session_info MCP. Fails silently. Should log at DEBUG.**

#### S58 — Line 1724
```python
info["mcp_servers"] = get_mcp_status()
    except Exception:
        info["mcp_servers"] = []
    try:
        info["system_prompt"] = getattr(agent, "_cached_system_prompt", "") or ""
    except Exception:
        pass
    try:
        from hermes_cli.banner import get_update_result
        from hermes_cli.config import recommended_update_command
```
**_session_info system_prompt. Fails silently. Should log at DEBUG.**

#### S59 — Line 1732
```python
from hermes_cli.banner import get_update_result
        from hermes_cli.config import recommended_update_command

        info["update_behind"] = get_update_result(timeout=0.5)
        info["update_command"] = recommended_update_command()
    except Exception:
        pass
    return info


def _tool_ctx(name: str, args: dict) -> str:
```
**_session_info update. Fails silently. Should log at DEBUG.**

#### S60 — Line 1791
```python
def _redact_tui_verbose_text(text: str) -> str:
    try:
        from agent.redact import redact_sensitive_text

        redacted = redact_sensitive_text(str(text), force=True)
    except Exception:
        return ""
    return _cap_tui_verbose_text(redacted)


def _tool_args_text(args: dict) -> str:
```
**_redact_tui_verbose_text. Fails silently — may leak sensitive data. Should log at WARNING.**

#### S61 — Line 1799
```python
def _tool_args_text(args: dict) -> str:
    try:
        raw = json.dumps(args or {}, indent=2, ensure_ascii=False, default=str)
    except Exception:
        raw = str(args or {})
    return _redact_tui_verbose_text(raw)


def _tool_result_text(result: object) -> str:
```
**_tool_args_text JSON. Fails silently. Should log at DEBUG.**

#### S62 — Line 1809
```python
def _tool_result_text(result: object) -> str:
    try:
        from agent.tool_dispatch_helpers import _multimodal_text_summary

        raw = _multimodal_text_summary(result)
    except Exception:
        raw = str(result)
    return _redact_tui_verbose_text(raw)


def _fmt_tool_duration(seconds: float | None) -> str:
```
**_tool_result_text multimodal. Fails silently. Should log at DEBUG.**

#### S63 — Line 1837
```python
def _tool_summary(name: str, result: str, duration_s: float | None) -> str | None:
    try:
        data = json.loads(result)
    except Exception:
        data = None

    dur = _fmt_tool_duration(duration_s)
    suffix = f" in {dur}" if dur else ""
    text = None
```
**_tool_summary JSON. Fails silently. Should log at DEBUG.**

#### S64 — Line 1871
```python
from agent.display import capture_local_edit_snapshot

            snapshot = capture_local_edit_snapshot(name, args)
            if snapshot is not None:
                session.setdefault("edit_snapshots", {})[tool_call_id] = snapshot
        except Exception:
            pass
        session.setdefault("tool_started_at", {})[tool_call_id] = time.time()
    if _tool_progress_enabled(sid):
        payload = {
            "tool_id": tool_call_id,
```
**capture_local_edit_snapshot. Fails silently. Should log at DEBUG.**

#### S65 — Line 1912
```python
if name == "todo":
        try:
            data = json.loads(result)
            if isinstance(data, dict) and isinstance(data.get("todos"), list):
                payload["todos"] = data.get("todos")
        except Exception:
            pass
    try:
        from agent.display import render_edit_diff_with_delta

        rendered: list[str] = []
```
**todo result parse. Fails silently. Should log at DEBUG.**

#### S66 — Line 1926
```python
function_args=args,
            snapshot=snapshot,
            print_fn=rendered.append,
        ):
            payload["inline_diff"] = "\n".join(rendered)
    except Exception:
        pass
    if _tool_progress_enabled(sid) or payload.get("inline_diff"):
        _emit("tool.complete", sid, payload)
```
**render_edit_diff_with_delta. Fails silently. Should log at DEBUG.**

#### S67 — Line 2085
```python
def _available_personalities(cfg: dict | None = None) -> dict:
    try:
        from cli import load_cli_config

        return (load_cli_config().get("agent") or {}).get("personalities", {}) or {}
    except Exception:
        try:
            from hermes_cli.config import load_config as _load_full_cfg

            return (_load_full_cfg().get("agent") or {}).get("personalities", {}) or {}
        except Exception:
```
**_available_personalities first fallback. Should log at DEBUG.**

#### S68 — Line 2090
```python
except Exception:
        try:
            from hermes_cli.config import load_config as _load_full_cfg

            return (_load_full_cfg().get("agent") or {}).get("personalities", {}) or {}
        except Exception:
            cfg = cfg or _load_cfg()
            return (cfg.get("agent") or {}).get("personalities", {}) or {}


def _validate_personality(value: str, cfg: dict | None = None) -> tuple[str, str]:
```
**_available_personalities second fallback. Should log at DEBUG.**

#### S69 — Line 2329
```python
}
    try:
        _sessions[sid]["slash_worker"] = _SlashWorker(
            key, getattr(agent, "model", _resolve_model())
        )
    except Exception:
        # Defer hard-failure to slash.exec; chat still works without slash worker.
        _sessions[sid]["slash_worker"] = None
    try:
        from tools.approval import register_gateway_notify, load_permanent_allowlist
```
**_SlashWorker creation on session start. Fails silently. Should log at WARNING.**

#### S70 — Line 2337
```python
try:
        from tools.approval import register_gateway_notify, load_permanent_allowlist

        register_gateway_notify(key, lambda data: _emit("approval.request", sid, data))
        load_permanent_allowlist()
    except Exception:
        pass
    # Surface the self-improvement background review's "💾 …" summary as a
    # review.summary event so Ink can render it as a persistent system line
    # in the transcript. In the CLI path this message is printed via
    # prompt_toolkit; the TUI has no equivalent print surface, so without
```
**Approval register on start. Fails silently. Should log at DEBUG.**

#### S71 — Line 2348
```python
# this callback the review would write the skill/memory change silently.
    try:
        agent.background_review_callback = lambda message, _sid=sid: _emit(
            "review.summary", _sid, {"text": str(message)}
        )
    except Exception:
        # Bare AIAgents that don't expose the attribute (unlikely, but keep
        # session startup resilient).
        pass
    _wire_callbacks(sid)
    _sessions[sid]["_notif_stop"] = _start_notification_poller(sid, _sessions[sid])
```
**background_review_callback. Already commented but no log. Should log at DEBUG.**

#### S72 — Line 2405
```python
parts.append(
                f"[The user attached an image:\n{desc}]\n{hint}"
                if desc
                else f"[The user attached an image but analysis failed.]\n{hint}"
            )
        except Exception:
            parts.append(f"[The user attached an image but analysis failed.]\n{hint}")

    text = user_text or ""
    prefix = "\n\n".join(parts)
    if prefix:
```
**Image analysis failure. Fails silently. Should log at WARNING.**

#### S73 — Line 2748
```python
resolved_title = fallback
                    elif not resolved_title:
                        resolved_title = fallback
            elif resolved_title:
                session["pending_title"] = None
        except Exception:
            resolved_title = fallback
        return _ok(
            rid,
            {
                "title": resolved_title,
```
**Title resolution fallback. Fails silently. Should log at DEBUG.**

#### S74 — Line 2815
```python
meta = {}
    db = _get_db()
    if db and key:
        try:
            meta = db.get_session(key) or {}
        except Exception:
            meta = {}

    def _dt(value, fallback: datetime | None = None) -> datetime:
        if value:
            try:
```
**session.info DB read. Fails silently. Should log at DEBUG.**

#### S75 — Line 2822
```python
def _dt(value, fallback: datetime | None = None) -> datetime:
        if value:
            try:
                return datetime.fromtimestamp(float(value))
            except Exception:
                pass
        return fallback or datetime.now()

    created = _dt(meta.get("started_at"))
    updated = created
```
**_dt timestamp parse. Fails silently. Should log at DEBUG.**

#### S76 — Line 2869
```python
if db is not None and session.get("session_key"):
        try:
            history = db.get_messages_as_conversation(
                session["session_key"], include_ancestors=True
            )
        except Exception:
            pass
    return _ok(
        rid,
        {
            "count": len(history),
```
**session.history DB read. Fails silently. Should log at WARNING.**

#### S77 — Line 3313
```python
continue
            try:
                stat = p.stat()
                try:
                    raw = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    raw = {}
                subagents = raw.get("subagents") or []
                entries.append(
                    {
                        "path": str(p),
```
**Subagent JSON read. Corrupt state silently treated as empty. Should log at WARNING.**

#### S78 — Line 3447
```python
from tools.process_registry import process_registry, format_process_notification

    while not stop_event.is_set() and not session.get("_finalized"):
        try:
            evt = process_registry.completion_queue.get(timeout=0.5)
        except Exception:
            # No process event — check kanban queue while we're awake.
            try:
                _kanban_evt = _kanban_fifo_queue.get_nowait()
                _dispatch_kanban_notification(sid, session, _kanban_evt)
            except queue.Empty:
```
**process_registry queue.get. Should catch `queue.Empty`, log others.**

#### S79 — Line 3491
```python
# Drain any remaining events after stop signal (process all pending
    # before exiting so nothing is lost on shutdown).
    while not process_registry.completion_queue.empty():
        try:
            evt = process_registry.completion_queue.get_nowait()
        except Exception:
            break
        _evt_sid = evt.get("session_id", "")
        if evt.get("type") == "completion" and process_registry.is_completion_consumed(_evt_sid):
            continue
        text = format_process_notification(evt)
```
**Drain events queue.get. Should catch `queue.Empty`, log others.**

#### S80 — Line 3751
```python
sid_key = session.get("session_key") or ""
                    if sid_key:
                        try:
                            goals_cfg = _load_cfg().get("goals") or {}
                            goal_max_turns = int(goals_cfg.get("max_turns", 20) or 20)
                        except Exception:
                            goal_max_turns = 20
                        goal_mgr = GoalManager(
                            session_id=sid_key,
                            default_max_turns=goal_max_turns,
                        )
```
**Goals config load. Fails silently. Should log at DEBUG.**

#### S81 — Line 3797
```python
session["pending_title"] = None
                        logger.info(
                            "Dropping pending title for session %s: %s",
                            _session_key, exc,
                        )
                    except Exception:
                        # Transient DB failure — keep pending_title for retry.
                        pass

            if (
                status == "complete"
```
**Pending title DB save. Has comment but no log. Should log at DEBUG.**

#### S82 — Line 3818
```python
session.get("session_key") or sid,
                        text,
                        raw,
                        session.get("history", []),
                    )
                except Exception:
                    pass

            # CLI parity: when voice-mode TTS is on, speak the agent reply
            # (cli.py:_voice_speak_response).  Only the final text — tool
            # calls / reasoning already stream separately and would be
```
**Auto-title generation. Fails silently. Should log at DEBUG.**

#### S83 — Line 3864
```python
_emit("error", sid, {"message": str(e)})
        finally:
            try:
                if approval_token is not None:
                    reset_current_session_key(approval_token)
            except Exception:
                pass
            _clear_session_context(session_tokens)
            with session["history_lock"]:
                session["running"] = False
```
**Approval token reset. Fails silently. Should log at DEBUG.**

#### S84 — Line 4688
```python
cfg_path = _hermes_home / "config.yaml"
        try:
            return _ok(
                rid, {"mtime": cfg_path.stat().st_mtime if cfg_path.exists() else 0}
            )
        except Exception:
            return _ok(rid, {"mtime": 0})
    return _err(rid, 4002, f"unknown config key: {key}")


@method("setup.status")
```
**config.mtime stat. Fails silently. Should log at DEBUG.**

#### S85 — Line 4737
```python
_cfg = _load_config()
                _approvals = _cfg.get("approvals") if isinstance(_cfg, dict) else None
                _confirm_required = True
                if isinstance(_approvals, dict):
                    _confirm_required = bool(_approvals.get("mcp_reload_confirm", True))
            except Exception:
                _confirm_required = True
            if _confirm_required:
                # Return a structured response the Ink client can surface
                # as a warning/confirmation without actually reloading yet.
                # Ink's ops.ts reads ``status`` and prints ``message`` to
```
**MCP reload confirm config. Fails silently. Should log at DEBUG.**

#### S86 — Line 5011
```python
try:
        from hermes_cli.commands import resolve_command

        r = resolve_command(name)
        return r.name if r else name
    except Exception:
        return name


@method("command.dispatch")
def _(rid, params: dict) -> dict:
```
**command.resolve. Fails silently. Should log at DEBUG.**

#### S87 — Line 5059
```python
handler = get_plugin_command_handler(name)
        if handler:
            result = resolve_plugin_command_result(handler(arg))
            return _ok(rid, {"type": "plugin", "output": str(result or "")})
    except Exception:
        pass

    try:
        from agent.skill_commands import (
            scan_skill_commands,
```
**Plugin command handler. Fails silently. Should log at WARNING.**

#### S88 — Line 5083
```python
"type": "skill",
                        "message": msg,
                        "name": cmds[key].get("name", name),
                    },
                )
    except Exception:
        pass

    # ── Commands that queue messages onto _pending_input in the CLI ───
    # In the TUI the slash worker subprocess has no reader for that queue,
    # so we handle them here and return a structured payload.
```
**Skill command handler. Fails silently. Should log at WARNING.**

#### S89 — Line 5144
```python
{
                            "type": "exec",
                            "output": f"⏩ Steer queued — arrives after the next tool call: {arg[:80]}{'...' if len(arg) > 80 else ''}",
                        },
                    )
            except Exception:
                pass
        # Fallback: no active run, treat as next-turn message
        return _ok(rid, {"type": "send", "message": arg})

    if name == "goal":
```
**Steer command queue. Fails silently. Should log at DEBUG.**

#### S90 — Line 5164
```python
return _err(rid, 4001, "no session key")

        try:
            goals_cfg = _load_cfg().get("goals") or {}
            max_turns = int(goals_cfg.get("max_turns", 20) or 20)
        except Exception:
            max_turns = 20
        mgr = GoalManager(session_id=sid_key, default_max_turns=max_turns)

        lower = arg.strip().lower()
        if not arg.strip() or lower == "status":
```
**Goal command config. Fails silently. Should log at DEBUG.**

#### S91 — Line 6079
```python
_cmd_key = f"/{_cmd_base}"
        if _cmd_key in get_skill_commands():
            return _err(
                rid, 4018, f"skill command: use command.dispatch for {_cmd_key}"
            )
    except Exception:
        pass

    plugin_handler = None
    resolve_plugin_command_result = None
    if _cmd_base:
```
**Skill command check. Fails silently. Should log at DEBUG.**

#### S92 — Line 6092
```python
get_plugin_command_handler,
                resolve_plugin_command_result,
            )

            plugin_handler = get_plugin_command_handler(_cmd_base)
        except Exception:
            plugin_handler = None
            resolve_plugin_command_result = None

    if plugin_handler and resolve_plugin_command_result:
        try:
```
**Plugin handler lookup. Fails silently. Should log at DEBUG.**

#### S93 — Line 6541
```python
cfg = read_raw_config()
        browser_cfg = cfg.get("browser", {}) if isinstance(cfg, dict) else {}
        if isinstance(browser_cfg, dict):
            return str(browser_cfg.get("cdp_url", "") or "").strip()
    except Exception:
        pass
    return ""


def _is_default_local_cdp(parsed) -> bool:
```
**Browser CDP URL config. Fails silently. Should log at DEBUG.**

#### S94 — Line 6573
```python
import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except Exception:
        return False


def _probe_urls(parsed) -> list[str]:
    scheme = {"ws": "http", "wss": "https"}.get(parsed.scheme, parsed.scheme)
```
**_probe_cdp_url HTTP. Fails silently. Should log at DEBUG.**

#### S95 — Line 6743
```python
def reap() -> None:
        try:
            from tools.browser_tool import cleanup_all_browsers

            cleanup_all_browsers()
        except Exception:
            pass

    reap()
    os.environ.pop("BROWSER_CDP_URL", None)
    reap()
```
**Browser cleanup. Fails silently. Should log at DEBUG.**

---

## Recommendations by Priority

### P0 — Fix silently swallowed JSON errors (12 instances)
Files: kanban_db.py K1, K2, K6; server.py S6, S32, S47-S50, S52, S53, S71
**Action:** Narrow to `json.JSONDecodeError` / `TypeError`, add logging.

### P1 — Fix silently swallowed import errors (21 instances)
Files: kanban_db.py K11-K15; server.py S18, S23-S28, S30, S31, S33, S35-S38, S46, S48
**Action:** Narrow to `ImportError` (or `ImportError, AttributeError`).

### P2 — Add logging to silent pass blocks (40 instances)
Files: Both files — all `pass` blocks that don't already log.
**Action:** Add `logger.debug/warning(..., exc_info=True)`.

### P3 — Narrow OS-level catches (6 instances)
Files: kanban_db.py K5, K9; server.py S7, S8, S34, S37
**Action:** Use `socket.error`, `OSError`, `ChildProcessError`, `KeyError`.

---

*Report generated by Ed~! Bwahaha! Data streams don't lie, you-person~* ◕‿◕✿