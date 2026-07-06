# 📖 User Guide — Illustrator AI MCP

Connect Claude to Adobe Illustrator so it can **design for you, see the result, and iterate** — 100% locally, with nothing leaving your machine.

> **Platform status**
> | Platform | Status |
> |---|---|
> | 🍎 macOS | ✅ Fully supported & tested (AppleScript bridge) |
> | 🪟 Windows | ⚠️ **Experimental** (COM bridge, community testing welcome) |

---

## 1. Requirements

- **Adobe Illustrator** installed (tested with Illustrator 2026 / v30 on macOS)
- **Python 3.11+** — check with `python3 --version` (macOS) or `python --version` (Windows)
- A Claude client: **Claude Desktop** or **Claude Code**

---

## 2. Install

### Option A — with `uv` (recommended)

```bash
# install uv once, if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh        # macOS
# Windows (PowerShell):
# powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

git clone https://github.com/Gokul2/illustrator-mcp-Gokul-Dhatkshina-Moorthy-.git
cd illustrator-mcp-Gokul-Dhatkshina-Moorthy-
uv sync
```

### Option B — plain pip

**macOS:**
```bash
git clone https://github.com/Gokul2/illustrator-mcp-Gokul-Dhatkshina-Moorthy-.git
cd illustrator-mcp-Gokul-Dhatkshina-Moorthy-
python3 -m venv .venv
.venv/bin/pip install -e .
```

**Windows (PowerShell):**
```powershell
git clone https://github.com/Gokul2/illustrator-mcp-Gokul-Dhatkshina-Moorthy-.git
cd illustrator-mcp-Gokul-Dhatkshina-Moorthy-
python -m venv .venv
.venv\Scripts\pip install -e .
```

---

## 3. Connect to Claude Desktop

Edit the config file (create it if missing):

| OS | Config file location |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |

### macOS — with uv
```json
{
  "mcpServers": {
    "illustrator": {
      "command": "uv",
      "args": [
        "--directory",
        "/Users/YOU/path/to/illustrator-mcp-Gokul-Dhatkshina-Moorthy-",
        "run",
        "illustrator-ai-mcp"
      ]
    }
  }
}
```

### macOS — with pip/venv
```json
{
  "mcpServers": {
    "illustrator": {
      "command": "/Users/YOU/path/to/illustrator-mcp-Gokul-Dhatkshina-Moorthy-/.venv/bin/illustrator-ai-mcp"
    }
  }
}
```

### Windows — with pip/venv
```json
{
  "mcpServers": {
    "illustrator": {
      "command": "C:\\Users\\YOU\\path\\to\\illustrator-mcp-Gokul-Dhatkshina-Moorthy-\\.venv\\Scripts\\illustrator-ai-mcp.exe"
    }
  }
}
```

Then **fully quit and restart Claude Desktop**. You should see the 🔨 tools icon with 11 Illustrator tools.

---

## 4. Connect to Claude Code (CLI)

**macOS:**
```bash
claude mcp add illustrator -- /Users/YOU/path/to/repo/.venv/bin/illustrator-ai-mcp
```

**Windows:**
```powershell
claude mcp add illustrator -- C:\Users\YOU\path\to\repo\.venv\Scripts\illustrator-ai-mcp.exe
```

Verify with `/mcp` inside a Claude Code session.

---

## 5. First-run permissions

### macOS (two one-time prompts)
1. **Automation** — the first time Claude runs a script, macOS asks to allow controlling "Adobe Illustrator". Click **Allow**.
   *(Fix later: System Settings → Privacy & Security → Automation)*
2. **Screen Recording** — needed only for `view_canvas` screenshots. Enable your Claude app under:
   *System Settings → Privacy & Security → Screen Recording*, then restart the app.

### Windows
No special permissions. Just make sure **Illustrator is already open** before asking Claude to design (the COM bridge attaches to the running app).

---

## 6. Using it — example prompts

Open Illustrator, then ask Claude:

- *"Create a new document and design a minimalist mountain logo with a sunset. Look at it and refine until it's balanced."*
- *"Draw a 6×6 grid of circles with a rainbow gradient across them."*
- *"Make 3 variations of this concept on separate artboards and show me all of them."*
- *"Export the current document as SVG to my Desktop."*
- *"What layers and artboards does my current document have?"*
- *"Save that gradient technique as a snippet called 'sunset-fade' so we can reuse it."*

### The 11 tools Claude gets

| Tool | What it does |
|---|---|
| `run_script` | Execute ExtendScript in Illustrator (with line-numbered errors so Claude self-corrects) |
| `view_canvas` | Screenshot the Illustrator window — Claude's eyes |
| `get_document_state` | Artboards / layers / selection as JSON |
| `export_artwork` | Export PNG / SVG / PDF / JPG to a path you choose |
| `undo_last` | Undo the last operation |
| `set_memory` | Opt in/out of local history (default: **off**) |
| `list_history` / `get_run` | Browse past runs (local only) |
| `save_snippet` / `search_snippets` | Reusable technique library (local, searchable) |
| `memory_stats` | What's stored, where, and how much |

---

## 7. Privacy — what this tool does and doesn't do

- ✅ **Zero network code.** The server makes no network calls — audit the source, it's short.
- ✅ **History is opt-in** and stored only in `~/.illustrator-mcp/` (macOS) / `%USERPROFILE%\.illustrator-mcp\` (Windows).
- ✅ **Wipe everything**: ask Claude to "clear my design history", or delete the `.illustrator-mcp` folder.
- ⚠️ **Honest note:** screenshots and script results *are* sent to the AI model as part of your conversation — that's how Claude sees your canvas. This is true of any AI design tool.

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| "Adobe Illustrator is not running or not responding" | Open Illustrator first; dismiss any modal dialogs |
| `view_canvas` returns a permission error (macOS) | Enable Screen Recording for your Claude app, restart it |
| Script times out | Illustrator likely has a modal dialog open — close it |
| Tools don't appear in Claude Desktop | Check the config JSON path/syntax, fully quit & restart Claude |
| Windows: "requires pywin32" | `.venv\Scripts\pip install pywin32` |
| Windows: COM errors | Ensure Illustrator is installed and **running**; try running Claude and Illustrator at the same privilege level (both non-admin) |

---

## 9. Windows: current experimental limitations

- `view_canvas` captures the **whole primary screen**, not just the Illustrator window
- The COM bridge is untested against all Illustrator versions — please report issues!
- Everything else (`run_script`, document state, export, memory) uses the same code paths as macOS and should behave identically

Found a bug on Windows? Open an issue — this is exactly the community testing the experimental label is asking for.
