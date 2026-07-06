"""Illustrator AI MCP server.

Exposes Adobe Illustrator to AI assistants over the Model Context Protocol.
Everything runs locally on this machine: ExtendScript execution via AppleScript,
window screenshots via macOS screencapture, and an opt-in SQLite memory stored
in ~/.illustrator-mcp. No network code exists anywhere in this package.

The FastMCP instance is exported as `mcp`; the package __init__ imports it and
calls mcp.run().
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP, Image

from .jsx import run_jsx
from .vision import capture_illustrator
from .document import get_document_state as _get_document_state
from .document import export_artwork as _export_artwork
from .document import undo as _undo
from .memory import Memory

mcp = FastMCP("illustrator")

# Module-level singleton. Memory is disabled by default (privacy-first) —
# nothing is logged until the user opts in via set_memory(True).
memory = Memory()


@mcp.tool()
def run_script(code: str) -> str:
    """Execute ExtendScript (JSX) code inside the running Adobe Illustrator.

    This is the primary way to create and edit artwork. The code runs against
    the CURRENT document (or you can create one with app.documents.add()).

    IMPORTANT — returning values: your code is wrapped in a function before it
    runs, so you can use a top-level `return <value>` statement to send data
    back to yourself. Whatever you return is stringified and becomes this
    tool's result. Use this to inspect object properties, verify geometry,
    count items, etc.

    Error handling: if the script throws, you get back "Error: ..." including
    the ExtendScript error message and the line number where it failed — read
    it, fix your code, and retry. Common gotchas: ExtendScript is ES3 (no
    `let`/`const`/arrow functions/template literals), coordinates are in
    points with Y increasing UPWARD from the artboard origin, and colors are
    set via `new RGBColor()` with .red/.green/.blue in 0-255.

    Example:
        var doc = app.documents.add(DocumentColorSpace.RGB, 800, 600);
        var rect = doc.pathItems.rectangle(-100, 100, 300, 200); // top, left, w, h
        var fill = new RGBColor();
        fill.red = 30; fill.green = 90; fill.blue = 200;
        rect.filled = true;
        rect.fillColor = fill;
        rect.stroked = false;
        return app.activeDocument.name;

    After running a script, call view_canvas() to see the visual result, or
    get_document_state() for a structural check.

    Args:
        code: ExtendScript source to execute. May contain a top-level
            `return` statement to pass a value back.

    Returns:
        The stringified return value of the script on success, or an
        "Error: ..." string (with line number when available) on failure.
    """
    try:
        result = run_jsx(code)
        success = bool(result.get("success"))
        error = result.get("error")
        try:
            memory.log_run(code, success, error)
        except Exception:
            # Memory problems must never break script execution.
            pass
        if success:
            return result.get("result") or ""
        return f"Error: {error or 'unknown ExtendScript error'}"
    except Exception as e:  # noqa: BLE001 — tool must never raise
        try:
            memory.log_run(code, False, str(e))
        except Exception:
            pass
        return f"Error: {e}"


@mcp.tool()
def view_canvas():  # returns Image | str; annotation omitted — FastMCP can't schema a union with Image
    """Take a screenshot of the Adobe Illustrator window so you can SEE the design.

    This is your eyes. Call it after run_script() to visually verify what you
    drew: composition, colors, alignment, typography, whether shapes actually
    landed where you intended. The screenshot captures the live Illustrator
    window (dynamically located, whatever screen it is on) and is downscaled
    to a compact JPEG.

    Use view_canvas() for visual judgment; use get_document_state() when you
    only need structure (artboard sizes, layer names, selection) — the JSON is
    much cheaper than an image.

    Returns:
        A JPEG image of the Illustrator window, or a plain-text error message
        (e.g. if Illustrator is not running or Screen Recording permission is
        missing).
    """
    try:
        jpeg_bytes = capture_illustrator()
        return Image(data=jpeg_bytes, format="jpeg")
    except RuntimeError as e:
        return str(e)
    except Exception as e:  # noqa: BLE001
        return f"Error: {e}"


@mcp.tool()
def get_document_state() -> dict:
    """Get structured JSON describing the current Illustrator document.

    Returns artboards (names, bounds), layers (names, visibility, lock state,
    item counts), and the current selection. This is far cheaper than a
    screenshot and better for LAYOUT LOGIC: computing coordinates, checking
    what exists before adding to it, finding the active artboard's dimensions,
    or confirming a script created the objects you expected.

    Prefer this over view_canvas() when you need numbers, not pixels.

    Returns:
        {"success": bool, "data": {...document structure...}, "error": str | None}
    """
    try:
        return _get_document_state()
    except Exception as e:  # noqa: BLE001
        return {"success": False, "data": None, "error": str(e)}


@mcp.tool()
def export_artwork(path: str, format: str = "png") -> dict:
    """Export the current document to an image or vector file on disk.

    Use this when the user wants a deliverable file of the finished design.
    The file is written locally at the exact path given (parent directory
    should exist; use an absolute path like /Users/name/Desktop/logo.png).

    Args:
        path: Absolute destination path for the exported file.
        format: One of "png", "svg", "pdf", "jpg". Defaults to "png".

    Returns:
        {"success": bool, "path": str, "error": str | None}
    """
    try:
        return _export_artwork(path, format)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "path": path, "error": str(e)}


@mcp.tool()
def undo_last() -> dict:
    """Undo the most recent action in Illustrator (same as Cmd+Z).

    Use this to roll back a script that produced the wrong result before
    trying an improved version. Each call undoes one step; call repeatedly to
    step further back. Note that a single run_script() call may have performed
    several document operations, each of which can be its own undo step.

    Returns:
        {"success": bool, "error": str | None}
    """
    try:
        return _undo()
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}


@mcp.tool()
def list_history(limit: int = 20) -> list:
    """List recent script runs from local history (requires memory enabled).

    Each entry summarizes one run_script() execution: id, timestamp, a code
    preview, and whether it succeeded. Use get_run(run_id) to fetch the full
    code of an interesting entry. Handy for "do that again but bigger" style
    requests, or for reviewing what has been tried in past sessions.

    History is OFF by default for privacy. If it is disabled you will get a
    hint back instead of history; enable logging with set_memory(True).

    Args:
        limit: Maximum number of recent runs to return (default 20).

    Returns:
        A list of run summaries, newest first — or a one-item list with a hint
        when memory is disabled.
    """
    try:
        if not memory.enabled:
            return [
                {
                    "hint": (
                        "Local history is disabled (privacy default). "
                        "Call set_memory(True) to start logging runs on this machine."
                    )
                }
            ]
        return memory.list_history(limit)
    except Exception as e:  # noqa: BLE001
        return [{"error": str(e)}]


@mcp.tool()
def get_run(run_id: int) -> dict:
    """Fetch one past run in full: complete code, result/error, and screenshot path.

    Use after list_history() when you want to reuse or adapt the exact script
    from a previous run. The screenshot path (when present) points to a local
    file under ~/.illustrator-mcp.

    Args:
        run_id: The id of the run, as shown by list_history().

    Returns:
        The full run record, or {"error": ...} if the id is unknown or memory
        is disabled.
    """
    try:
        run = memory.get_run(run_id)
        if run is None:
            return {"error": f"No run found with id {run_id} (is memory enabled?)"}
        return run
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp.tool()
def save_snippet(
    name: str, description: str, code: str, tags: list[str] | None = None
) -> dict:
    """Save a reusable ExtendScript technique to the local snippet library.

    When a script works well — a gradient recipe, a text-on-path setup, a
    star-burst generator, a clean export routine — save it here so FUTURE
    SESSIONS can find and reuse it instead of rediscovering the approach from
    scratch. Write the description like documentation for your future self:
    what it draws, what parameters to tweak, any gotchas.

    The library lives locally in ~/.illustrator-mcp and works regardless of
    the history/memory toggle.

    Args:
        name: Short unique name, e.g. "radial-gradient-badge".
        description: What the snippet does and how to adapt it.
        code: The working ExtendScript source.
        tags: Optional list of keywords for searching, e.g. ["gradient", "logo"].

    Returns:
        {"success": bool, ...} confirming the save, or {"error": ...}.
    """
    try:
        return memory.save_snippet(name, description, code, tags)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp.tool()
def search_snippets(query: str = "", limit: int = 10) -> list:
    """Search the local snippet library for proven ExtendScript techniques.

    CALL THIS BEFORE writing a complex script from scratch — a working,
    debugged version of what you need may already be saved from a previous
    session. Matches against snippet names, descriptions, and tags. An empty
    query lists the most recent snippets.

    Args:
        query: Keywords to search for, e.g. "gradient logo". Empty for all.
        limit: Maximum number of snippets to return (default 10).

    Returns:
        A list of matching snippets (name, description, code, tags).
    """
    try:
        return memory.search_snippets(query, limit)
    except Exception as e:  # noqa: BLE001
        return [{"error": str(e)}]


@mcp.tool()
def set_memory(enabled: bool) -> dict:
    """Enable or disable local history logging (privacy feature, default OFF).

    When enabled, each run_script() call is logged to a local SQLite database
    in ~/.illustrator-mcp on THIS machine only — nothing is transmitted
    anywhere. History lets you and future sessions review past runs via
    list_history()/get_run(). When disabled, no new runs are recorded.

    Ask the user before enabling if they haven't expressed a preference — it
    is their data. Existing history can be wiped at any time by deleting
    ~/.illustrator-mcp (or via the memory module's clear_history).

    Args:
        enabled: True to start logging runs locally, False to stop.

    Returns:
        A dict confirming the new state.
    """
    try:
        return memory.set_enabled(enabled)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@mcp.tool()
def memory_stats() -> dict:
    """Report what the local memory store contains and where it lives.

    Returns counts (runs logged, snippets saved), whether history logging is
    currently enabled, on-disk size, and a privacy statement. Useful for
    transparency: the user can see exactly what has been recorded.

    Returns:
        memory.stats() plus a "privacy" key describing local-only storage.
    """
    try:
        stats = memory.stats()
        if not isinstance(stats, dict):
            stats = {"stats": stats}
        stats["privacy"] = (
            "All data is stored locally in ~/.illustrator-mcp — "
            "nothing ever leaves this machine."
        )
        return stats
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
