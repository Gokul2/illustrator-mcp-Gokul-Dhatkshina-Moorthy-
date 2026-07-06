"""ExtendScript (JSX) execution bridge for Adobe Illustrator.

Runs user-supplied ExtendScript inside Illustrator — via AppleScript on
macOS, or COM automation (pywin32) on Windows (experimental) — wrapping
it in a harness that captures errors with line numbers so the calling AI
can self-heal from script failures. Local-only; no network.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

_APP_NAME = "Adobe Illustrator"

_HARNESS = """(function () {{
    try {{
        var __r = (function () {{
{user_code}
        }})();
        return "OK:" + (__r === undefined || __r === null ? "" : String(__r));
    }} catch (e) {{
        return "ERR:[line " + (e.line || "?") + "] " + (e.name || "Error") + ": " + e.message;
    }}
}})();
"""

# Compact JSON.stringify polyfill for older ExtendScript engines.
# Prepended only by run_jsx_json; guarded so modern engines keep the native one.
_JSON_POLYFILL = """if (typeof JSON === "undefined") { JSON = {}; }
if (typeof JSON.stringify !== "function") {
    JSON.stringify = function (v) {
        function esc(s) {
            return '"' + String(s).replace(/\\\\/g, "\\\\\\\\").replace(/"/g, '\\\\"')
                .replace(/\\n/g, "\\\\n").replace(/\\r/g, "\\\\r").replace(/\\t/g, "\\\\t") + '"';
        }
        function go(x) {
            if (x === null || x === undefined) return "null";
            var t = typeof x;
            if (t === "number") return isFinite(x) ? String(x) : "null";
            if (t === "boolean") return String(x);
            if (t === "string") return esc(x);
            if (x instanceof Array) {
                var a = [];
                for (var i = 0; i < x.length; i++) a.push(go(x[i]));
                return "[" + a.join(",") + "]";
            }
            if (t === "object") {
                var p = [];
                for (var k in x) {
                    if (x.hasOwnProperty(k) && typeof x[k] !== "function") {
                        p.push(esc(k) + ":" + go(x[k]));
                    }
                }
                return "{" + p.join(",") + "}";
            }
            return "null";
        }
        return go(v);
    };
}
"""

_NOT_RUNNING_HINTS = (
    "isn't running",
    "is not running",
    "-600",
    "-1712",
    "-1708",
    "not authorized",
    "connection is invalid",
    "Can’t get application",
    "Can't get application",
)


def _friendly_oserror(stderr: str) -> str:
    """Map raw osascript stderr to a human-friendly message when recognized."""
    if any(hint in stderr for hint in _NOT_RUNNING_HINTS):
        return (
            "Adobe Illustrator is not running or not responding. "
            "Open it and try again."
        )
    return stderr.strip() or "osascript failed with no error output."


def _parse_harness_output(out: str) -> dict:
    """Parse the OK:/ERR: prefixed harness output into the result dict."""
    if out.startswith("OK:"):
        return {"success": True, "result": out[3:], "error": None}
    if out.startswith("ERR:"):
        return {"success": False, "result": "", "error": out[4:]}
    # Unexpected but non-failing output; surface it as the result.
    return {"success": True, "result": out, "error": None}


def _run_jsx_windows(script: str, timeout: int) -> dict:
    """EXPERIMENTAL: execute the harnessed script via COM automation on Windows."""
    try:
        import pythoncom  # type: ignore[import-not-found]
        import win32com.client  # type: ignore[import-not-found]
    except ImportError:
        return {
            "success": False,
            "result": "",
            "error": "Windows support requires pywin32. Install it with: "
            "pip install pywin32",
        }
    import concurrent.futures

    def _call() -> object:
        pythoncom.CoInitialize()
        try:
            app = win32com.client.Dispatch("Illustrator.Application")
            return app.DoJavaScript(script)
        finally:
            pythoncom.CoUninitialize()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_call)
        try:
            out = str(future.result(timeout=timeout) or "").strip()
        except concurrent.futures.TimeoutError:
            return {
                "success": False,
                "result": "",
                "error": f"Script timed out after {timeout}s. Illustrator may be "
                "busy with a modal dialog or a long-running operation.",
            }
        except Exception as e:  # noqa: BLE001 — COM errors are opaque
            return {
                "success": False,
                "result": "",
                "error": "COM automation failed — is Adobe Illustrator installed "
                f"and running? Details: {e}",
            }
    return _parse_harness_output(out)


def run_jsx(code: str, timeout: int = 60) -> dict:
    """Execute ExtendScript in Adobe Illustrator.

    Returns {"success": bool, "result": str, "error": str | None}.
    result = string value of the script's final return value ("" if none);
    error = structured message including line number when available.
    """
    script = _HARNESS.format(user_code=code)
    if sys.platform == "win32":
        return _run_jsx_windows(script, timeout)
    fd, path = tempfile.mkstemp(suffix=".jsx", prefix="illustrator_ai_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(script)
        applescript = (
            f'tell application "{_APP_NAME}" to do javascript POSIX file "{path}"'
        )
        try:
            proc = subprocess.run(
                ["osascript", "-e", applescript],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "result": "",
                "error": f"Script timed out after {timeout}s. Illustrator may be "
                "busy with a modal dialog or a long-running operation.",
            }
        if proc.returncode != 0:
            return {
                "success": False,
                "result": "",
                "error": _friendly_oserror(proc.stderr),
            }
        return _parse_harness_output(proc.stdout.strip())
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def run_jsx_json(code: str, timeout: int = 60) -> dict:
    """Like run_jsx but expects the script to return a JSON string; parses it.

    Returns {"success": bool, "data": <parsed object> | None, "error": str | None}.
    """
    res = run_jsx(_JSON_POLYFILL + "\n" + code, timeout=timeout)
    if not res["success"]:
        return {"success": False, "data": None, "error": res["error"]}
    try:
        data = json.loads(res["result"]) if res["result"] else None
    except json.JSONDecodeError as e:
        return {
            "success": False,
            "data": None,
            "error": f"Script succeeded but returned invalid JSON: {e}. "
            f"Raw output: {res['result'][:500]}",
        }
    return {"success": True, "data": data, "error": None}
