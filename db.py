"""SQLite: сессии игр, раздачи, кэш ключ-значение."""
import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(
    id INTEGER PRIMARY KEY, game_id TEXT, name TEXT, start REAL, "end" REAL,
    open INTEGER, ping_avg REAL, ping_loss REAL);
CREATE INDEX IF NOT EXISTS sessions_start ON sessions(start);
CREATE TABLE IF NOT EXISTS deals(key TEXT PRIMARY KEY, first_seen REAL, claimed INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
"""

SESSION_COLS = 'id, game_id, name, start, "end", open, ping_avg, ping_loss'


def _session(row) -> dict:
    """Строку таблицы sessions → dict."""
    return {"id": row[0], "game_id": row[1], "name": row[2], "start": row[3], "end": row[4],
            "open": bool(row[5]), "ping_avg": row[6], "ping_loss": row[7]}


class DB:
    def __init__(self, path: Path | str):
        """":memory:" — для тестов. Таблицы создаются сами."""
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            # без fsync на каждую запись (heartbeat раз в poll_seconds); с WAL база при сбое не портится
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def _write(self, sql: str, args=()) -> sqlite3.Cursor:
        """Изменение с коммитом под замком."""
        with self._lock, self._conn:
            return self._conn.execute(sql, args)

    def _read(self, sql: str, args=()) -> list:
        """Чтение под замком."""
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    # --- сессии ---

    def open_session(self, game_id: str, name: str, start: float) -> int:
        cur = self._write(
            'INSERT INTO sessions(game_id, name, start, "end", open) VALUES (?, ?, ?, ?, 1)',
            (game_id, name, start, start))
        return cur.lastrowid

    def heartbeat(self, sid: int, now: float) -> None:
        """Сессия ещё идёт: end = now."""
        self._write('UPDATE sessions SET "end" = ? WHERE id = ?', (now, sid))

    def close_session(self, sid: int, end: float, ping_avg: float | None = None,
                      ping_loss: float | None = None) -> None:
        self._write('UPDATE sessions SET "end" = ?, open = 0, ping_avg = ?, ping_loss = ? WHERE id = ?',
                    (end, ping_avg, ping_loss, sid))

    def delete_session(self, sid: int) -> None:
        self._write("DELETE FROM sessions WHERE id = ?", (sid,))

    def close_dangling(self) -> int:
        """Закрыть сессии, оставшиеся открытыми после падения (end — последний heartbeat)."""
        return self._write("UPDATE sessions SET open = 0 WHERE open = 1").rowcount

    def sessions(self, t0: float | None = None, t1: float | None = None) -> list[dict]:
        """Сессии, пересекающиеся с [t0, t1]; без границ — все. По возрастанию start."""
        where, args = [], []
        if t0 is not None:
            where.append('"end" >= ?')
            args.append(t0)
        if t1 is not None:
            where.append("start <= ?")
            args.append(t1)
        sql = f"SELECT {SESSION_COLS} FROM sessions"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY start"
        return [_session(r) for r in self._read(sql, args)]

    def open_sessions(self) -> list[dict]:
        rows = self._read(f"SELECT {SESSION_COLS} FROM sessions WHERE open = 1 ORDER BY start")
        return [_session(r) for r in rows]

    def game_totals(self) -> dict[str, dict]:
        """game_id → {"seconds", "last" (макс end), "sessions"}."""
        rows = self._read('SELECT game_id, SUM("end" - start), MAX("end"), COUNT(*) FROM sessions GROUP BY game_id')
        return {gid: {"seconds": float(sec or 0), "last": float(last or 0), "sessions": n}
                for gid, sec, last, n in rows}

    # --- раздачи ---

    def deal_seen(self, key: str) -> bool:
        return bool(self._read("SELECT 1 FROM deals WHERE key = ?", (key,)))

    def mark_deal_seen(self, key: str, now: float) -> None:
        self._write("INSERT OR IGNORE INTO deals(key, first_seen) VALUES (?, ?)", (key, now))

    def set_deal_claimed(self, key: str, claimed: bool) -> None:
        """Отметка «забрал»; записи нет — создаётся (first_seen = текущее время)."""
        self._write("INSERT INTO deals(key, first_seen, claimed) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET claimed = excluded.claimed",
                    (key, time.time(), int(bool(claimed))))

    def claimed_deals(self) -> set[str]:
        return {r[0] for r in self._read("SELECT key FROM deals WHERE claimed = 1")}

    # --- ключ-значение (значение хранится как JSON) ---

    def kv_get(self, key: str, default=None):
        rows = self._read("SELECT value FROM kv WHERE key = ?", (key,))
        if not rows:
            return default
        return json.loads(rows[0][0])

    def kv_set(self, key: str, value) -> None:
        self._write("INSERT OR REPLACE INTO kv(key, value) VALUES (?, ?)",
                    (key, json.dumps(value, ensure_ascii=False)))
