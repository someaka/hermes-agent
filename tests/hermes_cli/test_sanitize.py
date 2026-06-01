"""Tests for hermes_cli.sanitize — shared error/traceback sanitization.

Covers:
  - Unix filesystem path redaction
  - Windows filesystem path redaction
  - API endpoint preservation (not clobbered by FS-root regex)
  - Short-path preservation (/home/user stays intact)
  - Negative lookahead for /v1/, /v2/, etc.
  - Max-length truncation
  - Exception → sanitized string
  - Edge cases (empty, unicode, nested paths, mixed content)
"""
from __future__ import annotations

import pytest

from hermes_cli.sanitize import (
    _UNIX_PATH,
    _WIN_PATH,
    sanitize_error_msg,
    sanitize_traceback,
)


# ── _UNIX_PATH regex ────────────────────────────────────────────────────────


class TestUnixPathRegex:
    """Regex-level tests for the compiled _UNIX_PATH pattern."""

    # Paths that SHOULD match (be redacted) — requires ≥2 segments after root
    @pytest.mark.parametrize("path", [
        "/home/alice/.ssh/id_rsa",
        "/home/user/project/src/main.py",
        "/Users/bob/Documents/secret.txt",
        "/opt/myapp/config/production.yaml",
        "/var/lib/postgresql/14/main/pg_hba.conf",
        "/tmp/build-abc123/output.tar.gz",
        "/etc/nginx/nginx.conf",
        "/usr/local/bin/python3",
        "/srv/www/htdocs/index.html",
        "/proc/1234/maps",
        "/mnt/backup/daily/2026-06-01.tar",
        "/media/usb0/data.csv",
        "/run/user/1000/wayland-0",
        "/lib/x86_64-linux-gnu/libc.so.6",
        "/nix/store/abc123-python3-3.11/bin/python",
        "/private/var/folders/xx/yy/T/pytest-123",
        # /var/lib/v1/chat — /var is the root, /lib/v1/chat are 3 segments
        # The lookahead checks the segment *immediately* after the root name,
        # so /var/lib/v1/chat passes (segment is /lib, not /v\d/).
        "/var/lib/v1/chat/completions",
    ])
    def test_matches_fs_paths(self, path: str) -> None:
        assert _UNIX_PATH.search(path), f"Should match: {path}"

    # Paths that should NOT match (preserved as-is)
    @pytest.mark.parametrize("path", [
        # Too short — only 1 segment after root (by design: preserves
        # short references like /home/user or /etc/hosts in error messages)
        "/home/user",
        "/opt/app",
        "/var/log",
        "/etc/hosts",
        "/tmp/file",
        "/root/.bashrc",
        "/dev/sda1",
        "/boot/vmlinuz-5.15.0",
        "/bin/bash",
        "/sbin/init",
        # API-style paths — negative lookahead blocks /v1/, /v2/, etc.
        # when the versioned segment is immediately after the root name.
        "/api/v1/chat/completions",   # api is NOT a known FS root
        "/api/v2/models/gpt-4",       # api is NOT a known FS root
        "/home/v1/users/list",        # /home → lookahead blocks /v1/
        # Not a known FS root at all
        "/data/models/weights.bin",
        "/app/src/main.py",
        "/workspace/project/file.py",
        "/custom/path/here",
        # URL-like strings
        "https://example.com/api/v1/chat",
        "http://localhost:8080/health",
        # Embedded in error messages without leading /
        "error in home/user/file.py",
        "var/lib/data is corrupted",
    ])
    def test_does_not_match_non_paths(self, path: str) -> None:
        assert not _UNIX_PATH.search(path), f"Should NOT match: {path}"

    def test_preserves_api_endpoint_in_error(self) -> None:
        """The exact scenario from the review: API endpoints stay intact."""
        msg = "Connection refused: http://localhost:8080/api/v1/chat/completions"
        assert _UNIX_PATH.sub("<path>", msg) == msg

    def test_sanitizes_real_path_in_same_message(self) -> None:
        """Real FS path gets redacted even when API endpoint is present."""
        msg = "Failed to load /home/alice/.config/hermes/config.yaml from /api/v1/settings"
        result = _UNIX_PATH.sub("<path>", msg)
        assert "/home/alice/.config/hermes/config.yaml" not in result
        assert "<path>" in result
        assert "/api/v1/settings" in result  # API path preserved

    def test_negative_lookahead_blocks_home_v1(self) -> None:
        """Paths like /home/v1/users/list are blocked by lookahead."""
        assert not _UNIX_PATH.search("/home/v1/users/list")

    def test_lookbehind_prevents_mid_path_match(self) -> None:
        """Paths embedded inside longer strings don't false-match."""
        # /data/home/user/file — the /home is preceded by /data
        assert not _UNIX_PATH.search("/data/home/user/file.txt")

    def test_matches_deep_path_after_root(self) -> None:
        """Deep paths (≥2 segments after root) are matched."""
        assert _UNIX_PATH.search("/var/log/syslog.1")
        assert _UNIX_PATH.search("/usr/share/doc/python3/README.md")

    def test_short_paths_not_matched(self) -> None:
        """Short paths (1 segment after root) are preserved by design."""
        # This preserves readable error messages like "Permission denied: /etc/hosts"
        assert not _UNIX_PATH.search("/etc/hosts")
        assert not _UNIX_PATH.search("/bin/bash")
        assert not _UNIX_PATH.search("/root/.bashrc")


# ── _WIN_PATH regex ─────────────────────────────────────────────────────────


class TestWindowsPathRegex:
    """Regex-level tests for the compiled _WIN_PATH pattern."""

    @pytest.mark.parametrize("path", [
        r"C:\Users\Alice\Documents\secret.docx",
        r"D:\Projects\hermes\config.yaml",
        r"E:\Backup\2026\June\dump.sql",
    ])
    def test_matches_windows_paths(self, path: str) -> None:
        assert _WIN_PATH.search(path), f"Should match: {path}"

    @pytest.mark.parametrize("text", [
        "C: drive is full",
        "D:no-slashes",
        "regular text without paths",
        # "Program Files" has a space — the regex requires \w+ segments
        # separated by backslashes, so this won't match. That's fine —
        # paths with spaces are rare in error messages.
    ])
    def test_does_not_match_non_windows_paths(self, text: str) -> None:
        assert not _WIN_PATH.search(text), f"Should NOT match: {text}"

    def test_windows_path_with_spaces_not_matched(self) -> None:
        """Paths with spaces (e.g. Program Files) don't match — acceptable trade-off."""
        # The regex uses [\w.-]+ which doesn't include spaces.
        # This is fine: real Windows error messages almost always use 8.3 paths.
        assert not _WIN_PATH.search(r"C:\Program Files\Python311\python.exe")


# ── sanitize_error_msg ──────────────────────────────────────────────────────


class TestSanitizeErrorMsg:
    """Integration tests for sanitize_error_msg()."""

    def test_strips_unix_path(self) -> None:
        exc = FileNotFoundError("[Errno 2] No such file or directory: '/home/alice/.ssh/id_rsa'")
        result = sanitize_error_msg(exc)
        assert "/home/alice/.ssh/id_rsa" not in result
        assert "<path>" in result

    def test_strips_windows_path(self) -> None:
        exc = FileNotFoundError(r"[Errno 2] No such file or directory: 'C:\Users\Alice\secret.txt'")
        result = sanitize_error_msg(exc)
        assert "C:\\Users\\Alice\\secret.txt" not in result
        assert "<path>" in result

    def test_preserves_api_endpoint(self) -> None:
        exc = ConnectionError("Failed to reach http://localhost:8080/api/v1/chat/completions")
        result = sanitize_error_msg(exc)
        assert "/api/v1/chat/completions" in result

    def test_truncates_long_message(self) -> None:
        exc = RuntimeError("x" * 500)
        result = sanitize_error_msg(exc, max_len=100)
        assert len(result) <= 104  # 100 + "..."
        assert result.endswith("...")

    def test_short_message_unchanged(self) -> None:
        exc = ValueError("bad value")
        result = sanitize_error_msg(exc)
        assert result == "bad value"

    def test_empty_exception(self) -> None:
        exc = RuntimeError("")
        result = sanitize_error_msg(exc)
        assert result == ""

    def test_mixed_paths_and_api(self) -> None:
        exc = RuntimeError(
            "Failed to load /home/user/.hermes/config.yaml — "
            "got 404 from http://api.example.com/v1/models"
        )
        result = sanitize_error_msg(exc)
        assert "/home/user/.hermes/config.yaml" not in result
        assert "<path>" in result
        assert "http://api.example.com/v1/models" in result  # URL preserved

    def test_multiple_paths_sanitized(self) -> None:
        exc = RuntimeError(
            "Cannot copy /home/alice/data.csv to /opt/app/input/data.csv"
        )
        result = sanitize_error_msg(exc)
        assert "/home/alice/data.csv" not in result
        assert "/opt/app/input/data.csv" not in result
        assert result.count("<path>") == 2

    def test_no_false_positive_on_api_paths(self) -> None:
        """API endpoints are never clobbered — the key review concern."""
        exc = RuntimeError("POST /api/v1/chat/completions returned 500")
        result = sanitize_error_msg(exc)
        assert "/api/v1/chat/completions" in result
        assert "<path>" not in result


# ── sanitize_traceback ──────────────────────────────────────────────────────


class TestSanitizeTraceback:
    """Integration tests for sanitize_traceback()."""

    def test_strips_paths_from_traceback(self) -> None:
        tb = (
            'Traceback (most recent call last):\n'
            '  File "/home/user/project/main.py", line 10, in <module>\n'
            '    raise RuntimeError("oops")\n'
            'RuntimeError: oops\n'
        )
        result = sanitize_traceback(tb)
        assert "/home/user/project/main.py" not in result
        assert "<path>" in result
        assert "RuntimeError: oops" in result

    def test_truncates_long_traceback(self) -> None:
        tb = "x" * 5000
        result = sanitize_traceback(tb, max_len=500)
        assert len(result) <= 520  # 500 + "\n... (truncated)"
        assert "truncated" in result

    def test_short_traceback_unchanged(self) -> None:
        tb = "Error: something went wrong\n"
        result = sanitize_traceback(tb)
        assert result == tb

    def test_windows_paths_in_traceback(self) -> None:
        tb = (
            '  File "D:\\Projects\\hermes\\app.py", line 5\n'
            '    1 / 0\n'
            'ZeroDivisionError: division by zero\n'
        )
        result = sanitize_traceback(tb)
        assert "D:\\Projects\\hermes\\app.py" not in result
        assert "<path>" in result

    def test_preserves_api_refs_in_traceback(self) -> None:
        tb = (
            'requests.exceptions.ConnectionError: '
            'POST http://localhost:8080/api/v1/chat/completions failed\n'
        )
        result = sanitize_traceback(tb)
        assert "/api/v1/chat/completions" in result
        assert "<path>" not in result


# ── Edge cases ──────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and regression tests."""

    def test_unicode_in_message(self) -> None:
        exc = RuntimeError("日本語のエラー: /home/user/ファイル.txt")
        result = sanitize_error_msg(exc)
        assert "日本語のエラー" in result
        assert "/home/user/ファイル.txt" not in result

    def test_nested_paths(self) -> None:
        """Paths inside JSON-like structures are still caught."""
        exc = RuntimeError('{"path": "/home/user/data/file.json", "ok": false}')
        result = sanitize_error_msg(exc)
        assert "/home/user/data/file.json" not in result

    def test_path_at_string_boundary(self) -> None:
        """Path at the very start or end of the message."""
        exc = RuntimeError("/var/log/syslog.1 is corrupted")
        result = sanitize_error_msg(exc)
        assert "/var/log/syslog.1" not in result

    def test_custom_max_len(self) -> None:
        exc = RuntimeError("a" * 100)
        result = sanitize_error_msg(exc, max_len=50)
        assert len(result) <= 54  # 50 + "..."
        assert result.endswith("...")

    def test_real_world_permission_error(self) -> None:
        exc = PermissionError(
            "[Errno 13] Permission denied: '/home/user/.hermes/config.yaml'"
        )
        result = sanitize_error_msg(exc)
        assert "/home/user/.hermes/config.yaml" not in result
        assert "Permission denied" in result

    def test_real_world_connection_error(self) -> None:
        exc = ConnectionError(
            "HTTPSConnectionPool(host='api.openai.com', port=443): "
            "Max retries exceeded with url: /v1/chat/completions"
        )
        result = sanitize_error_msg(exc)
        assert "/v1/chat/completions" in result  # API path preserved
        assert "<path>" not in result

    def test_short_fs_refs_preserved(self) -> None:
        """Short FS references like /etc/hosts stay readable."""
        exc = RuntimeError("Cannot read /etc/hosts")
        result = sanitize_error_msg(exc)
        assert "/etc/hosts" in result  # preserved — only 1 segment
