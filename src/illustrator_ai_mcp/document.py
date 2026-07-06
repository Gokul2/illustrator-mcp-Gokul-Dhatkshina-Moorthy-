"""Document intelligence for the Illustrator AI MCP server.

Local-only module: everything here talks to the running Adobe Illustrator
instance on this machine via ExtendScript (through the sibling ``jsx``
module). No network access, no telemetry — document state never leaves
the local host.

Public API:
    get_document_state() -> dict
    export_artwork(path, format) -> dict
    undo() -> dict
"""

from __future__ import annotations

import os

from .jsx import run_jsx_json

# ---------------------------------------------------------------------------
# Shared JSX fragments
# ---------------------------------------------------------------------------

#: Guard prepended to scripts that must abort cleanly when no document is open.
#: Returns a sentinel JSON string the Python side can recognize.
_NO_DOC_GUARD_JSON = """\
if (app.documents.length === 0) {
    return JSON.stringify({ noDocument: true });
}
"""

_NO_DOC_HINT = "No document open. Create one with run_script: app.documents.add()"

_SUPPORTED_FORMATS = ("png", "svg", "pdf", "jpg")


def _js_string(value: str) -> str:
    """Escape a Python string for safe embedding inside a JSX double-quoted literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _no_document_data() -> dict:
    return {"noDocument": True, "hint": _NO_DOC_HINT}


# ---------------------------------------------------------------------------
# get_document_state
# ---------------------------------------------------------------------------

_DOCUMENT_STATE_JSX = f"""\
{_NO_DOC_GUARD_JSON}
var doc = app.activeDocument;
var state = {{}};

state.name = String(doc.name);
// doc.path throws for never-saved documents; treat that as "".
try {{
    state.path = String(doc.path.fsName) + "/" + String(doc.name);
}} catch (e) {{
    state.path = "";
}}
state.colorSpace = String(doc.documentColorSpace);

// First artboard dimensions. artboardRect is [left, top, right, bottom]
// in points, with top > bottom in Illustrator's coordinate system.
var firstRect = doc.artboards[0].artboardRect;
state.width = firstRect[2] - firstRect[0];
state.height = firstRect[1] - firstRect[3];

// Artboards (capped at 50).
var artboards = [];
var abCount = doc.artboards.length;
if (abCount > 50) {{ abCount = 50; }}
for (var i = 0; i < abCount; i++) {{
    var ab = doc.artboards[i];
    var r = ab.artboardRect;
    artboards.push({{
        name: String(ab.name),
        bounds: [r[0], r[1], r[2], r[3]]
    }});
}}
state.artboards = artboards;

// Top-level layers (capped at 50).
var layers = [];
var layerCount = doc.layers.length;
if (layerCount > 50) {{ layerCount = 50; }}
for (var j = 0; j < layerCount; j++) {{
    var layer = doc.layers[j];
    layers.push({{
        name: String(layer.name),
        visible: layer.visible,
        locked: layer.locked,
        itemCount: layer.pageItems.length
    }});
}}
state.layers = layers;

state.selectionCount = doc.selection.length;
state.totalItems = doc.pageItems.length;

return JSON.stringify(state);
"""


def get_document_state() -> dict:
    """Structured snapshot of the active document.

    Returns {"success": bool, "data": {...} | None, "error": str | None}
    """
    result = run_jsx_json(_DOCUMENT_STATE_JSX)
    if not result.get("success"):
        return {"success": False, "data": None, "error": result.get("error")}

    data = result.get("data")
    if isinstance(data, dict) and data.get("noDocument"):
        return {"success": True, "data": _no_document_data(), "error": None}

    return {"success": True, "data": data, "error": None}


# ---------------------------------------------------------------------------
# export_artwork
# ---------------------------------------------------------------------------


def _export_jsx(posix_path: str, fmt: str) -> str:
    """Build the ExtendScript for exporting the active document."""
    escaped = _js_string(posix_path)

    if fmt == "png":
        body = f"""\
var f = new File("{escaped}");
var opts = new ExportOptionsPNG24();
opts.antiAliasing = true;
opts.transparency = true;
opts.artBoardClipping = true;
app.activeDocument.exportFile(f, ExportType.PNG24, opts);
"""
    elif fmt == "jpg":
        body = f"""\
var f = new File("{escaped}");
var opts = new ExportOptionsJPEG();
opts.qualitySetting = 80;
opts.artBoardClipping = true;
app.activeDocument.exportFile(f, ExportType.JPEG, opts);
"""
    elif fmt == "svg":
        body = f"""\
var f = new File("{escaped}");
var opts = new ExportOptionsSVG();
app.activeDocument.exportFile(f, ExportType.SVG, opts);
"""
    else:  # pdf — uses saveAs, not exportFile
        body = f"""\
var f = new File("{escaped}");
var opts = new PDFSaveOptions();
app.activeDocument.saveAs(f, opts);
"""

    return f"""\
{_NO_DOC_GUARD_JSON}
{body}
return JSON.stringify({{ exported: true }});
"""


def export_artwork(path: str, format: str = "png") -> dict:
    """Export active document to png | svg | pdf | jpg at absolute `path`.

    Returns {"success": bool, "path": str | None, "error": str | None}
    """
    fmt = (format or "").strip().lower()
    if fmt not in _SUPPORTED_FORMATS:
        return {
            "success": False,
            "path": None,
            "error": (
                f"Unsupported format {format!r}. "
                f"Choose one of: {', '.join(_SUPPORTED_FORMATS)}."
            ),
        }

    out_path = os.path.abspath(os.path.expanduser(path))
    if not out_path.lower().endswith(f".{fmt}"):
        out_path = f"{out_path}.{fmt}"

    parent = os.path.dirname(out_path)
    if parent:
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            return {
                "success": False,
                "path": None,
                "error": f"Could not create parent directory {parent!r}: {exc}",
            }

    result = run_jsx_json(_export_jsx(out_path, fmt), timeout=120)
    if not result.get("success"):
        return {"success": False, "path": None, "error": result.get("error")}

    data = result.get("data")
    if isinstance(data, dict) and data.get("noDocument"):
        return {"success": False, "path": None, "error": _NO_DOC_HINT}

    if not os.path.exists(out_path):
        return {
            "success": False,
            "path": None,
            "error": (
                f"Illustrator reported a successful export but no file exists at "
                f"{out_path!r}. Check that Illustrator has permission to write "
                f"there and that the document has visible artwork."
            ),
        }

    return {"success": True, "path": out_path, "error": None}


# ---------------------------------------------------------------------------
# undo
# ---------------------------------------------------------------------------

_UNDO_JSX = f"""\
{_NO_DOC_GUARD_JSON}
app.undo();
return JSON.stringify({{ undone: true }});
"""


def undo() -> dict:
    """Undo the last operation in Illustrator.

    Returns {"success": bool, "error": str | None}
    """
    result = run_jsx_json(_UNDO_JSX)
    if not result.get("success"):
        return {"success": False, "error": result.get("error")}

    data = result.get("data")
    if isinstance(data, dict) and data.get("noDocument"):
        return {"success": False, "error": _NO_DOC_HINT}

    return {"success": True, "error": None}
