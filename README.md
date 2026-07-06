# illustrator-ai-mcp

**Let Claude design in Adobe Illustrator — 100% local, private by default.**

An MCP (Model Context Protocol) server that gives AI assistants hands and eyes inside Adobe Illustrator: it writes and runs ExtendScript, sees the canvas via window screenshots, reads document structure, exports artwork, and (optionally) remembers techniques that worked — all without a single byte leaving your machine from this server.

> 📖 **New here? Start with the step-by-step [USER_GUIDE.md](USER_GUIDE.md)** — install, Claude Desktop/Code setup, permissions, and troubleshooting for both platforms.

| Platform | Status |
|---|---|
| 🍎 macOS | ✅ Fully supported & tested (AppleScript bridge) |
| 🪟 Windows | ⚠️ Experimental (COM bridge via pywin32 — testers welcome) |

## Privacy

- **No network code.** This package contains zero HTTP clients, telemetry, or analytics. It talks only to Illustrator (via AppleScript/ExtendScript) and your local filesystem.
- **History is opt-in and OFF by default.** Nothing is logged until you (or the AI, with your permission) call `set_memory(True)`.
- **One-command wipe.** Everything the server ever stores lives in `~/.illustrator-mcp`. Delete that folder and it's gone. There is also a `clear_history` capability in the memory layer.
- **Honest caveat:** screenshots of your Illustrator window and script results *are* sent to the AI model as part of your conversation — that is inherent to how the AI sees the canvas and iterates on the design. If a document is confidential, don't ask an AI to look at it. The *server* itself, however, never transmits anything on its own.

## Features vs. the original

Inspired by [spencerhhubert/illustrator-mcp-server](https://github.com/spencerhhubert/illustrator-mcp-server), rebuilt with the feedback loop an AI actually needs:

| Capability | spencerhhubert/illustrator-mcp-server | illustrator-ai-mcp |
|---|---|---|
| Run ExtendScript in Illustrator | Yes | Yes |
| Script output capture (`return` values) | No — fire and forget | Yes — scripts return data to the AI |
| Error messages with line numbers | No | Yes — AI can fix and retry |
| Window screenshots | Fixed screen region | Dynamic window detection, any display |
| Document state as JSON (artboards/layers/selection) | No | Yes |
| Export artwork (png/svg/pdf/jpg) | No | Yes |
| Undo | No | Yes |
| Local run history | No | Yes — opt-in, off by default |
| Reusable snippet library | No | Yes — searchable across sessions |

## Requirements

- macOS (AppleScript bridge — fully supported) or Windows (COM bridge — experimental)
- Adobe Illustrator (any recent CC version), running
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) recommended (plain pip works too)

## Install

### With uv (recommended)

```bash
git clone <this-repo> illustrator-ai-mcp
cd illustrator-ai-mcp
uv sync
```

### With plain pip

```bash
git clone <this-repo> illustrator-ai-mcp
cd illustrator-ai-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Hook it up

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "illustrator": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/illustrator-ai-mcp",
        "run",
        "illustrator-ai-mcp"
      ]
    }
  }
}
```

Restart Claude Desktop afterwards.

### Claude Code

```bash
claude mcp add illustrator -- uv --directory /absolute/path/to/illustrator-ai-mcp run illustrator-ai-mcp
```

## First run: macOS permissions

The first time the server touches Illustrator, macOS will ask for two permissions. Grant both to the app hosting the server (Claude Desktop, your terminal, etc.):

1. **Automation** — lets the server send ExtendScript to Illustrator.
   *System Settings → Privacy & Security → Automation* → enable **Adobe Illustrator** under your client app.
2. **Screen Recording** — lets `view_canvas` screenshot the Illustrator window.
   *System Settings → Privacy & Security → Screen Recording* → enable your client app, then restart it.

If a screenshot comes back black or the tool reports a permission error, Screen Recording is the usual culprit.

## Tool reference

| Tool | What it does |
|---|---|
| `run_script(code)` | Execute ExtendScript on the current document. `return <value>` sends data back; errors include line numbers for fix-and-retry. |
| `view_canvas()` | JPEG screenshot of the Illustrator window — the AI's eyes. |
| `get_document_state()` | Structured JSON of artboards, layers, and selection — cheaper than a screenshot for layout logic. |
| `export_artwork(path, format)` | Export the document to png / svg / pdf / jpg at a path you choose. |
| `undo_last()` | Undo the most recent action (Cmd+Z). |
| `list_history(limit)` | Recent script runs (only when memory is enabled). |
| `get_run(run_id)` | Full code + screenshot path of one past run. |
| `save_snippet(name, description, code, tags)` | Save a technique that worked to the local library. |
| `search_snippets(query, limit)` | Search the library before writing complex scripts from scratch. |
| `set_memory(enabled)` | Opt in/out of local history logging (default: off). |
| `memory_stats()` | What's stored, where, and a privacy statement. |

## Example prompts

- "Design a minimalist mountain logo — dark blue palette, geometric, on a square artboard."
- "Recreate this layout as 3 variations on separate artboards."
- "Draw a sunburst badge with 24 rays, then export it as an SVG to my Desktop."
- "Look at the canvas and tell me what's misaligned, then fix it."
- "That gradient trick worked great — save it as a snippet for next time."

## Your data

Everything the server stores lives in one folder:

```
~/.illustrator-mcp/
```

That's the opt-in run history (SQLite), optional screenshots, and your snippet library. To wipe it:

- ask the AI to clear the history (uses the memory layer's `clear_history`), or
- nuke it yourself: `rm -rf ~/.illustrator-mcp`

Nothing else is written anywhere, and nothing is ever transmitted by this server.
