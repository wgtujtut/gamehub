"""Слежка за процессами игр и запись сессий."""
import logging
import os
import threading
import time

import psutil

log = logging.getLogger(__name__)

# Служебные exe внутри папок игр: краш-репортеры, анти-читы, лаунчеры, установщики
IGNORE_EXE: set[str] = {
    "unitycrashhandler64.exe", "unitycrashhandler32.exe", "crashreportclient.exe", "crashpad_handler.exe",
    "easyanticheat.exe", "easyanticheat_eos.exe", "easyanticheat_eos_setup.exe", "beservice.exe", "beservice_x64.exe",
    "battleye launcher.exe", "steam.exe", "steamwebhelper.exe", "steamservice.exe", "steamerrorreporter.exe",
    "steamerrorreporter64.exe", "epicgameslauncher.exe", "epicwebhelper.exe", "unrealcefsubprocess.exe",
    "vc_redist.x64.exe", "vc_redist.x86.exe", "dxsetup.exe", "unins000.exe", "cefprocess.exe", "crashsender.exe",
    "bugsplat.exe",
}


def norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def match_game(exe_path: str, games: list[dict]) -> str | None:
    """id игры, в чьей install_dir лежит exe (самое длинное совпадение), иначе None."""
    if os.path.basename(exe_path).lower() in IGNORE_EXE:
        return None
    exe = norm(exe_path)
    best_id, best_len = None, -1
    for g in games:
        if g.get("not_game") or not g.get("install_dir"):
            continue
        prefix = norm(g["install_dir"]).rstrip(os.sep) + os.sep  # граница по разделителю
        if exe.startswith(prefix) and len(prefix) > best_len:
            best_id, best_len = g["id"], len(prefix)
    return best_id


def list_processes() -> list[tuple[int, str, str]]:
    """(pid, name, exe) всех процессов; без exe (нет доступа) — пропускаются."""
    out = []
    for p in psutil.process_iter(["pid", "name", "exe"]):
        try:
            info = p.info
        except psutil.Error:
            continue
        if info.get("exe"):
            out.append((info["pid"], info.get("name") or "", info["exe"]))
    return out


class Tracker:
    def __init__(self, db, get_games, *, list_procs=list_processes, clock=time.time,
                 min_session=60, on_start=None, on_stop=None):
        self.db = db
        self.get_games = get_games
        self.list_procs = list_procs
        self.clock = clock
        self.min_session = min_session
        self.on_start = on_start
        self.on_stop = on_stop
        self._open = {}  # game_id → {"sid", "game", "name", "start"}
        self._lock = threading.Lock()  # running() зовут из другого потока
        db.close_dangling()

    def tick(self) -> None:
        """Один проход: открыть новые сессии, закрыть пропавшие, остальным heartbeat."""
        now = self.clock()
        games = self.get_games()
        by_id = {g["id"]: g for g in games}
        running = set()
        for _pid, _name, exe in self.list_procs():
            gid = match_game(exe, games)
            if gid:
                running.add(gid)

        with self._lock:
            new = [gid for gid in running if gid not in self._open]
            gone = [gid for gid in self._open if gid not in running]
            rest = [gid for gid in self._open if gid in running]

        for gid in new:
            game = by_id[gid]
            name = game.get("name") or gid
            sid = self.db.open_session(gid, name, now)
            with self._lock:
                self._open[gid] = {"sid": sid, "game": game, "name": name, "start": now}
            self._call(self.on_start, game)

        for gid in gone:
            with self._lock:
                entry = self._open.pop(gid)
            self._finish(entry, now)

        for gid in rest:
            self.db.heartbeat(self._open[gid]["sid"], now)

    def running(self) -> list[dict]:
        """Игры, запущенные сейчас."""
        now = self.clock()
        with self._lock:
            entries = list(self._open.items())
        return [{"game_id": gid, "name": e["name"], "start": e["start"], "elapsed": now - e["start"]}
                for gid, e in entries]

    def stop_all(self) -> None:
        """Закрыть все открытые сессии (при выходе из программы)."""
        now = self.clock()
        with self._lock:
            entries = list(self._open.values())
            self._open.clear()
        for entry in entries:
            self._finish(entry, now)

    def _finish(self, entry: dict, now: float) -> None:
        """Закрыть сессию: короткую удалить, иначе on_stop и запись с пингом."""
        seconds = now - entry["start"]
        if seconds < self.min_session:
            self.db.delete_session(entry["sid"])
            return
        game = entry["game"]
        session = {"id": entry["sid"], "game_id": game["id"], "name": entry["name"],
                   "start": entry["start"], "end": now, "seconds": seconds}
        ping = self._call(self.on_stop, game, session)
        if not isinstance(ping, dict):
            ping = {}
        self.db.close_session(entry["sid"], now, ping.get("ping_avg"), ping.get("ping_loss"))

    @staticmethod
    def _call(fn, *args):
        """Вызов колбэка; ошибки только в лог."""
        if fn is None:
            return None
        try:
            return fn(*args)
        except Exception:
            log.exception("ошибка в колбэке трекера")
            return None
