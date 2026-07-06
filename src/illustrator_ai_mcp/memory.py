"""Local, privacy-first memory for the Illustrator MCP server.

Privacy guarantees:
- 100% local: all data lives in SQLite + files under ``~/.illustrator-mcp/``.
  This module imports nothing that can touch the network.
- History logging is OPT-IN. Until the user explicitly enables it, nothing is
  written to disk except the config file that records their choice.
- ``clear_history()`` wipes all logged runs and screenshots in one call.

Layout under the base directory:
    config.json   -- {"history_enabled": bool}
    history.db    -- SQLite database (runs + snippets)
    history/      -- run screenshots (run_<id>.jpg)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

_CONFIG_NAME = "config.json"
_DB_NAME = "history.db"
_HISTORY_DIR = "history"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    code TEXT,
    success INTEGER,
    error TEXT,
    screenshot TEXT
);
CREATE TABLE IF NOT EXISTS snippets (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE,
    description TEXT,
    code TEXT,
    tags TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS snippets_fts USING fts5(
    name, description, code, tags, content='snippets', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS snippets_ai AFTER INSERT ON snippets BEGIN
    INSERT INTO snippets_fts(rowid, name, description, code, tags)
    VALUES (new.id, new.name, new.description, new.code, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS snippets_ad AFTER DELETE ON snippets BEGIN
    INSERT INTO snippets_fts(snippets_fts, rowid, name, description, code, tags)
    VALUES ('delete', old.id, old.name, old.description, old.code, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS snippets_au AFTER UPDATE ON snippets BEGIN
    INSERT INTO snippets_fts(snippets_fts, rowid, name, description, code, tags)
    VALUES ('delete', old.id, old.name, old.description, old.code, old.tags);
    INSERT INTO snippets_fts(rowid, name, description, code, tags)
    VALUES (new.id, new.name, new.description, new.code, new.tags);
END;
"""


class Memory:
    """Opt-in local history and snippet store backed by SQLite."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path.home() / ".illustrator-mcp"
        self._fts_ok: bool | None = None  # unknown until schema init

    # -- paths -------------------------------------------------------------

    @property
    def _config_path(self) -> Path:
        return self.base_dir / _CONFIG_NAME

    @property
    def _db_path(self) -> Path:
        return self.base_dir / _DB_NAME

    @property
    def _history_dir(self) -> Path:
        return self.base_dir / _HISTORY_DIR

    # -- config ------------------------------------------------------------

    def _read_config(self) -> dict:
        """Read config.json tolerantly; missing or corrupt yields defaults."""
        try:
            data = json.loads(self._config_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
        return {}

    @property
    def enabled(self) -> bool:
        """Whether history logging is enabled (opt-in, default False)."""
        return bool(self._read_config().get("history_enabled", False))

    def set_enabled(self, value: bool) -> dict:
        """Persist the history-logging preference to config.json."""
        config = self._read_config()
        config["history_enabled"] = bool(value)
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            self._config_path.write_text(
                json.dumps(config, indent=2), encoding="utf-8"
            )
        except OSError:
            pass
        return {"enabled": bool(value), "data_dir": str(self.base_dir)}

    # -- db plumbing ---------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open a connection, lazily creating the database and schema."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        if self._fts_ok is not False:
            try:
                conn.executescript(_FTS_SCHEMA)
                self._fts_ok = True
            except sqlite3.OperationalError:
                self._fts_ok = False  # FTS5 unavailable; fall back to LIKE
        return conn

    # -- runs ----------------------------------------------------------------

    def log_run(
        self,
        code: str,
        success: bool,
        error: str | None = None,
        screenshot: bytes | None = None,
    ) -> int | None:
        """Log one ExtendScript run. No-op (returns None) while disabled."""
        if not self.enabled:
            return None
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    "INSERT INTO runs (code, success, error) VALUES (?, ?, ?)",
                    (code, int(bool(success)), error),
                )
                run_id = cur.lastrowid
                if screenshot:
                    rel = f"{_HISTORY_DIR}/run_{run_id}.jpg"
                    try:
                        self._history_dir.mkdir(parents=True, exist_ok=True)
                        (self.base_dir / rel).write_bytes(screenshot)
                        conn.execute(
                            "UPDATE runs SET screenshot = ? WHERE id = ?",
                            (rel, run_id),
                        )
                    except OSError:
                        pass
            return run_id
        except sqlite3.Error:
            return None

    def list_history(self, limit: int = 20) -> list[dict]:
        """Return recent runs, newest first, with truncated code previews."""
        if not self._db_path.exists():
            return []
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT id, created_at, success, error, code, screenshot "
                    "FROM runs ORDER BY id DESC LIMIT ?",
                    (max(0, int(limit)),),
                ).fetchall()
            return [
                {
                    "id": r["id"],
                    "created_at": r["created_at"],
                    "success": bool(r["success"]),
                    "error": r["error"],
                    "code_preview": (r["code"] or "")[:120],
                    "has_screenshot": r["screenshot"] is not None,
                }
                for r in rows
            ]
        except sqlite3.Error:
            return []

    def get_run(self, run_id: int) -> dict | None:
        """Fetch one run in full; screenshot path returned absolute."""
        if not self._db_path.exists():
            return None
        try:
            with self._connect() as conn:
                r = conn.execute(
                    "SELECT id, created_at, success, error, code, screenshot "
                    "FROM runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
            if r is None:
                return None
            return {
                "id": r["id"],
                "created_at": r["created_at"],
                "success": bool(r["success"]),
                "error": r["error"],
                "code": r["code"],
                "screenshot_path": (
                    str(self.base_dir / r["screenshot"]) if r["screenshot"] else None
                ),
            }
        except sqlite3.Error:
            return None

    def clear_history(self) -> dict:
        """Delete all logged runs and their screenshots; snippets are kept."""
        deleted = 0
        if self._db_path.exists():
            try:
                with self._connect() as conn:
                    deleted = conn.execute("DELETE FROM runs").rowcount
            except sqlite3.Error:
                pass
        try:
            if self._history_dir.is_dir():
                for jpg in self._history_dir.glob("*.jpg"):
                    try:
                        jpg.unlink()
                    except OSError:
                        pass
        except OSError:
            pass
        return {"deleted_runs": max(0, deleted)}

    # -- snippets ------------------------------------------------------------

    def save_snippet(
        self,
        name: str,
        description: str,
        code: str,
        tags: list[str] | None = None,
    ) -> dict:
        """Upsert a named snippet. Works even when history logging is off."""
        tags_json = json.dumps(tags or [])
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO snippets (name, description, code, tags) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(name) DO UPDATE SET "
                    "description = excluded.description, "
                    "code = excluded.code, tags = excluded.tags",
                    (name, description, code, tags_json),
                )
                row = conn.execute(
                    "SELECT id FROM snippets WHERE name = ?", (name,)
                ).fetchone()
            return {"id": row["id"] if row else None, "name": name}
        except sqlite3.Error as exc:
            return {"id": None, "name": name, "error": str(exc)}

    def search_snippets(self, query: str, limit: int = 10) -> list[dict]:
        """Search snippets by FTS5 (or LIKE fallback); empty query = recent."""
        if not self._db_path.exists():
            return []
        limit = max(0, int(limit))
        try:
            with self._connect() as conn:
                rows = self._search_rows(conn, (query or "").strip(), limit)
            return [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "description": r["description"],
                    "code": r["code"],
                    "tags": self._parse_tags(r["tags"]),
                }
                for r in rows
            ]
        except sqlite3.Error:
            return []

    def _search_rows(
        self, conn: sqlite3.Connection, query: str, limit: int
    ) -> list[sqlite3.Row]:
        cols = "s.id, s.name, s.description, s.code, s.tags"
        if not query:
            return conn.execute(
                f"SELECT {cols} FROM snippets s ORDER BY s.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        if self._fts_ok:
            # Quote each token so user input can't break MATCH syntax.
            match = " ".join(
                '"{}"'.format(tok.replace('"', '""')) for tok in query.split()
            )
            try:
                return conn.execute(
                    f"SELECT {cols} FROM snippets_fts f "
                    "JOIN snippets s ON s.id = f.rowid "
                    "WHERE snippets_fts MATCH ? ORDER BY rank LIMIT ?",
                    (match, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                pass  # fall through to LIKE
        like = f"%{query}%"
        return conn.execute(
            f"SELECT {cols} FROM snippets s "
            "WHERE s.name LIKE ? OR s.description LIKE ? "
            "OR s.tags LIKE ? OR s.code LIKE ? "
            "ORDER BY s.id DESC LIMIT ?",
            (like, like, like, like, limit),
        ).fetchall()

    @staticmethod
    def _parse_tags(raw: str | None) -> list[str]:
        try:
            tags = json.loads(raw or "[]")
            return tags if isinstance(tags, list) else []
        except ValueError:
            return []

    # -- stats ---------------------------------------------------------------

    def stats(self) -> dict:
        """Summarize what is stored locally and how much disk it uses."""
        runs = snippets = 0
        if self._db_path.exists():
            try:
                with self._connect() as conn:
                    runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
                    snippets = conn.execute(
                        "SELECT COUNT(*) FROM snippets"
                    ).fetchone()[0]
            except sqlite3.Error:
                pass
        disk = 0
        try:
            if self.base_dir.is_dir():
                for path in self.base_dir.rglob("*"):
                    try:
                        if path.is_file():
                            disk += path.stat().st_size
                    except OSError:
                        pass
        except OSError:
            pass
        return {
            "enabled": self.enabled,
            "data_dir": str(self.base_dir),
            "runs": runs,
            "snippets": snippets,
            "disk_bytes": disk,
        }
