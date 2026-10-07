"""Режим игры: план питания и закрытие лишних программ."""
import logging
import re
import subprocess
import threading
import time

import psutil

log = logging.getLogger(__name__)

ULTIMATE = "e9a42b02-d5df-448d-aa00-03f14749eb61"
HIGH = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"
SAVER = "a1841308-3541-4fab-bc81-f71556f20b4a"

# без консоли powercfg заменяет кириллицу на "?" — стандартные схемы называем сами
KNOWN_NAMES = {
    ULTIMATE: "Максимальная производительность",
    HIGH: "Высокая производительность",
    BALANCED: "Сбалансированная",
    SAVER: "Экономия энергии",
}

# системные и свои процессы — не трогать никогда
PROTECTED = {"explorer", "csrss", "winlogon", "services", "lsass", "svchost", "system",
             "dwm", "smss", "wininit", "python", "pythonw",
             "gamehub", "msedgewebview2"}   # сам GameHub и движок его окна

# GUID, имя в скобках и необязательная * в конце строки
_SCHEME_RE = re.compile(
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    r"\s+\((.*)\)\s*(\*)?\s*$"
)


def parse_schemes(text):
    """Разбор вывода `powercfg /list` → [{"guid", "name", "active"}]."""
    result = []
    for line in text.splitlines():
        m = _SCHEME_RE.search(line)
        if m:
            guid, name = m.group(1).lower(), m.group(2).strip()
            if "?" in name:
                name = KNOWN_NAMES.get(guid, "Своя схема")
            result.append({"guid": guid, "name": name, "active": m.group(3) is not None})
    return result


def run_powercfg(*args):
    """Запустить powercfg без окна, вернуть вывод (консоль в cp866)."""
    r = subprocess.run(["powercfg", *args], capture_output=True, timeout=15,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    return r.stdout.decode("cp866", errors="replace")


def list_schemes():
    try:
        return parse_schemes(run_powercfg("/list"))
    except (OSError, subprocess.SubprocessError):
        log.exception("powercfg /list не сработал")
        return []


def active_scheme():
    return next((s for s in list_schemes() if s["active"]), None)


def set_scheme(guid):
    """Включить схему; True, если после этого она активна."""
    try:
        run_powercfg("/setactive", guid)
    except (OSError, subprocess.SubprocessError):
        log.exception("powercfg /setactive не сработал")
        return False
    cur = active_scheme()
    return cur is not None and cur["guid"] == guid.lower()


def best_scheme(schemes):
    """Максимальная производительность, иначе высокая, иначе None."""
    for guid in (ULTIMATE, HIGH):
        for s in schemes:
            if s["guid"] == guid:
                return s
    return None


def _base(name):
    """Имя процесса без .exe в нижнем регистре."""
    n = name.lower()
    return n[:-4] if n.endswith(".exe") else n


def kill_processes(names, *, iter_procs=None):
    """Закрыть процессы по именам; вернуть имена закрытых без дублей."""
    wanted = {_base(n) for n in names if n} - PROTECTED
    if not wanted:
        return []
    procs = iter_procs() if iter_procs else psutil.process_iter(["pid", "name"])
    killed = []
    for p in procs:
        name = p.info.get("name") or ""
        base = _base(name)
        if base not in wanted or base in PROTECTED:
            continue
        try:
            p.terminate()
        except (psutil.Error, OSError):
            continue  # нет прав или процесс уже завершился
        if name not in killed:
            killed.append(name)
    return killed


class GameMode:
    def __init__(self, *, list_fn=list_schemes, set_fn=set_scheme, kill_fn=kill_processes):
        self.list_fn = list_fn
        self.set_fn = set_fn
        self.kill_fn = kill_fn
        self.active = False
        self._previous = None   # схема до включения режима
        self._changed = False   # меняли ли схему
        self._lock = threading.Lock()
        self._cache = (0.0, [])   # (время, схемы): status зовёт открытая панель, а powercfg — отдельный процесс

    def _schemes(self, fresh=False):
        """Список схем с кэшем на минуту (свои переключения сбрасывают кэш сразу)."""
        ts, schemes = self._cache
        if fresh or time.monotonic() - ts > 60:
            schemes = self.list_fn()
            self._cache = (time.monotonic(), schemes)
        return schemes

    def enter(self, cfg_gm):
        """Включить режим игры."""
        with self._lock:
            if self.active:
                return {"scheme": None, "killed": []}
            schemes = self._schemes(fresh=True)
            current = next((s for s in schemes if s["active"]), None)
            self._previous = current
            self._changed = False
            scheme = None
            if cfg_gm.get("power_plan"):
                best = best_scheme(schemes)
                if best is not None:
                    if current is not None and current["guid"] == best["guid"]:
                        scheme = best["name"]
                    elif self.set_fn(best["guid"]):
                        self._changed = True
                        scheme = best["name"]
            killed = []
            if cfg_gm.get("kill_on_start"):
                killed = self.kill_fn(cfg_gm.get("kill_list", []))
            self.active = True
            self._cache = (0.0, [])
            return {"scheme": scheme, "killed": killed}

    def exit(self):
        """Выключить режим, вернуть прежнюю схему, если меняли."""
        with self._lock:
            if self._changed and self._previous is not None:
                self.set_fn(self._previous["guid"])
            self._previous = None
            self._changed = False
            self.active = False
            self._cache = (0.0, [])

    def kill_now(self, names):
        return self.kill_fn(names)

    def status(self):
        cur = next((s for s in self._schemes() if s["active"]), None)
        return {"active": self.active,
                "scheme": cur["name"] if cur else None,
                "previous": self._previous["name"] if self._previous else None}
