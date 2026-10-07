"""GameHub — точка входа. Запуск: .venv\\Scripts\\pythonw.exe app.py (без консоли) или python app.py."""
import json
import logging
import os
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import date, datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

import psutil

import cleaner
import config
import deals as deals_mod
import gamemode
import library
import net
import notify
import stats
import tracker
import updater
from db import DB

log = logging.getLogger("gamehub")

ROOT = Path(__file__).parent
LIBRARY_RESCAN_SECONDS = 30 * 60
UPDATE_CHECK_SECONDS = 24 * 3600
PORT_TRIES = 10            # порты cfg.port … cfg.port+9: первый свободный
MAX_INTERVAL = 7 * 86400   # дольше Event.wait не ждёт (OverflowError) — да и смысла нет
PING_IDLE_SECONDS = 120    # без игры пингуем, только пока панель открыта (и чуть после)


def _api_error(text, code=400):
    # ошибка для server.py (там свой класс ApiError; импорт здесь — чтобы не было цикла)
    import server
    return server.ApiError(text, code)


# нижние границы чисел из панели: ноль в интервале = цикл без пауз и долбёжка чужих API
MIN_VALUES = {"poll_seconds": 2, "ping.interval_seconds": 1, "deals.interval_hours": 1}


def check_partial(partial: dict, defaults: dict, path="") -> None:
    """Проверка частичного конфига из панели: только известные ключи и те же типы."""
    for key, value in partial.items():
        name = path + key
        if key not in defaults:
            raise _api_error(f"неизвестная настройка: {name}")
        base = defaults[key]
        if isinstance(base, bool):
            ok = isinstance(value, bool)
        elif isinstance(base, (int, float)):
            ok = isinstance(value, (int, float)) and not isinstance(value, bool) and value >= MIN_VALUES.get(name, 0)
        else:
            ok = isinstance(value, type(base))
        if not ok:
            raise _api_error(f"неверный тип: {name}")
        if isinstance(base, dict) and base:
            check_partial(value, base, name + ".")


def check_lists(cfg: dict) -> None:
    """Проверка содержимого списков конфига (цели пинга, свои игры, kill_list)."""
    for t in cfg["ping"]["targets"]:
        if not (isinstance(t, dict) and isinstance(t.get("name"), str) and t["name"].strip()
                and isinstance(t.get("host"), str) and t["host"].strip()
                and isinstance(t.get("port"), int) and 0 < t["port"] < 65536):
            raise _api_error("цель пинга: нужны name, host и port 1–65535")
    for g in cfg["extra_games"]:
        if not (isinstance(g, dict) and isinstance(g.get("id"), str) and g["id"].startswith("custom:")
                and isinstance(g.get("name"), str) and g["name"].strip()
                and isinstance(g.get("dir"), str) and isinstance(g.get("launch", ""), str)):
            raise _api_error("своя игра: нужны id (custom:...), name, dir")
    for key in ("kill_list",):
        if not all(isinstance(x, str) for x in cfg["gamemode"][key]):
            raise _api_error("kill_list: только строки")
    if not all(isinstance(x, str) for x in cfg["not_games"]):
        raise _api_error("not_games: только строки")


def loop_interval(value) -> float:
    """Пауза фонового цикла из настроек: 1 с … неделя, мусор — минута.
    config.json правят руками: 0, "10", 1e999 не должны ни крутить цикл вхолостую, ни ронять его поток."""
    try:
        v = float(value)
    except OverflowError:   # целое больше float
        return float(MAX_INTERVAL)
    except (TypeError, ValueError):
        return 60.0
    if v != v:          # NaN
        return 60.0
    return min(max(1.0, v), float(MAX_INTERVAL))


def disks() -> list[dict]:
    out = []
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        out.append({"name": part.mountpoint.rstrip("\\"), "free": usage.free, "total": usage.total})
    return out


class Hub:
    """Всё состояние приложения и операции, которые зовёт API."""

    def __init__(self, cfg: dict, db: DB):
        self.cfg = cfg
        self.db = db
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.steam_root = library.steam_root()
        self.steam_libs = library.steam_libraries(self.steam_root) if self.steam_root else []
        self.games: list[dict] = []
        self.scanned_at = 0.0
        self.size_cache = db.kv_get("size_cache", {}) or {}
        self.gm = gamemode.GameMode()
        self.gm_auto = False          # режим включён автоматически (значит, выключить, когда игры закроются)
        self.ping_mon = net.PingMonitor(cfg["ping"]["targets"])
        self.deals_cache = {"now": [], "upcoming": [], "errors": [], "fetched_at": None}
        self.deals_lock = threading.Lock()
        self.limit_notified = ""      # дата, за которую уже предупреждали о лимите
        self.url = ""
        self.window_show = None       # показать окно (задаёт run_tray)
        self.request_quit = None      # закрыть программу (задаёт run_tray)
        self.update = None            # {"version", "url", "notes", "page"}, если вышла новая версия
        self.update_notified = ""
        self.last_view = 0.0          # когда панель последний раз спрашивала данные (она опрашивает только видимой)
        self.rescan()
        self.tracker = tracker.Tracker(
            db, lambda: self.games,
            min_session=cfg["min_session_seconds"],
            on_start=self._on_game_start, on_stop=self._on_game_stop,
        )

    # ---------- библиотека ----------
    def rescan(self) -> dict:
        games = library.scan_all(self.cfg, self.size_cache)
        with self.lock:
            self.games = games
            self.scanned_at = time.time()
        self.db.kv_set("size_cache", self.size_cache)
        return self.library()

    def game(self, game_id: str) -> dict:
        for g in self.games:
            if g["id"] == game_id:
                return g
        raise _api_error("игра не найдена", 404)

    def library(self) -> dict:
        now = time.time()
        totals = self.db.game_totals()
        stale = cleaner.stale_games(self.games, totals, now, self.cfg["stale_days"])
        stale_ids = {g["id"] for g in stale["games"]}
        out = []
        for g in self.games:
            t = totals.get(g["id"], {})
            out.append({**g, "seconds": t.get("seconds", 0.0), "sessions": t.get("sessions", 0),
                        "last": max(g["last_played"], t.get("last", 0.0)), "stale": g["id"] in stale_ids})
        return {"games": out, "stale": stale, "scanned_at": self.scanned_at}

    def launch(self, game_id: str) -> dict:
        g = self.game(game_id)
        if not g["launch"]:
            raise _api_error("для этой игры не указан запуск")
        os.startfile(g["launch"])
        return {"ok": True}

    def open_folder(self, game_id: str) -> dict:
        g = self.game(game_id)
        if not os.path.isdir(g["install_dir"]):
            raise _api_error("папка не найдена")
        os.startfile(g["install_dir"])
        return {"ok": True}

    def set_not_game(self, game_id: str, value: bool) -> dict:
        self.game(game_id)
        with self.lock:
            ids = [x for x in self.cfg["not_games"] if x != game_id]
            if value:
                ids.append(game_id)
            self.cfg["not_games"] = ids
            config.save(self.cfg)
            for g in self.games:
                g["not_game"] = g["id"] in ids
        return {"ok": True}

    def cover(self, game_id: str, kind: str):
        """(локальный файл, адрес CDN) — что-то одно или ничего."""
        if not game_id.startswith("steam:"):
            return None, None
        appid = game_id.split(":", 1)[1]
        if not appid.isdigit():
            return None, None
        if self.steam_root:
            # нужной картинки нет в кэше Steam — лучше другая локальная, чем догадка про CDN
            for k in [kind] + [x for x in ("portrait", "header", "hero") if x != kind]:
                local = library.find_cover(self.steam_root, appid, k)
                if local:
                    return local, None
        return None, library.cdn_cover(appid, kind)

    # ---------- статистика ----------
    def state(self) -> dict:
        now = time.time()
        self.last_view = now
        sessions = self.db.sessions()
        summary = stats.summary(sessions, now)
        claimed = self.db.claimed_deals()
        return {
            "now": now,
            "playing": self.tracker.running(),
            "summary": summary,
            "gamemode": self._gm_status(),
            "disks": disks(),
            "ping": self.ping_mon.stats(now - 300),
            "deals_now": sum(1 for d in self.deals_cache["now"] if d["key"] not in claimed),
            "limit": {"daily_minutes": self.cfg["limits"]["daily_minutes"], "today_minutes": round(summary["today"] / 60)},
            "version": updater.VERSION,
            "update": self.update,
        }

    def stats(self, days: int) -> dict:
        now = time.time()
        today = date.today()
        first = today - timedelta(days=days - 1)
        t0 = datetime(first.year, first.month, first.day).timestamp()
        sessions = self.db.sessions()
        window = stats.clip(sessions, t0, now)
        by_day = stats.split_by_day_game(window)
        day_list = []
        for i in range(days):
            d = (first + timedelta(days=i)).isoformat()
            games = by_day.get(d, {})
            day_list.append({"date": d, "seconds": sum(games.values()), "games": games})
        names = {s["game_id"]: s["name"] for s in sessions}
        recent = sorted(sessions, key=lambda s: s["start"], reverse=True)[:50]
        return {
            "days": day_list,
            "names": names,
            "per_game": stats.per_game(window),
            "heatmap": stats.heatmap(stats.split_by_day(sessions), today),
            "by_hour": stats.by_hour(window),
            "by_weekday": stats.by_weekday(window),
            "sessions": recent,
            "summary": stats.summary(sessions, now),
        }

    # ---------- режим игры ----------
    def _gm_status(self) -> dict:
        return {**self.gm.status(), "auto": self.cfg["gamemode"]["auto"]}

    def gamemode_action(self, action: str) -> dict:
        killed = []
        with self.lock:
            if action == "on":
                self.gm.enter(self.cfg["gamemode"])
                self.gm_auto = False
            elif action == "off":
                self.gm.exit()
                self.gm_auto = False
            elif action == "kill":
                killed = self.gm.kill_now(self.cfg["gamemode"]["kill_list"])
            else:
                raise _api_error("action: on, off или kill")
        return {"gamemode": self._gm_status(), "killed": killed}

    def _on_game_start(self, game: dict) -> None:
        log.info("игра запущена: %s", game["name"])
        gm_cfg = self.cfg["gamemode"]
        with self.lock:
            if gm_cfg["auto"] and not self.gm.active and (gm_cfg["power_plan"] or gm_cfg["kill_on_start"]):
                res = self.gm.enter(gm_cfg)
                self.gm_auto = True
                log.info("режим игры: %s", res)

    def _on_game_stop(self, game: dict, session: dict):
        log.info("игра закрыта: %s, %.0f с", game["name"], session["seconds"])
        others = [r for r in self.tracker.running() if r["game_id"] != game["id"]]
        with self.lock:
            if self.gm_auto and not others:
                self.gm.exit()
                self.gm_auto = False
        if self.cfg["notify_session_end"]:
            today = stats.summary(self.db.sessions(), time.time())["today"]
            notify.toast(game["name"], f"Сессия: {stats.fmt_duration(session['seconds'])}. "
                                       f"Сегодня всего: {stats.fmt_duration(today)}")
        # упрощение: пинг берётся из буфера монитора (последний час), для длинных сессий — только последний час
        return self.ping_mon.overall(session["start"])

    def _check_limit(self) -> None:
        minutes = self.cfg["limits"]["daily_minutes"]
        today = date.today().isoformat()
        if not minutes or self.limit_notified == today:
            return
        played = stats.summary(self.db.sessions(), time.time())["today"] / 60
        if played >= minutes:
            self.limit_notified = today
            notify.toast("Лимит на сегодня", f"Наиграно {stats.fmt_duration(played * 60)} — пора сделать перерыв")

    # ---------- раздачи ----------
    def deals(self) -> dict:
        if self.deals_cache["fetched_at"] is None and self.cfg["deals"]["enabled"]:
            self.refresh_deals(notify_new=False)
        claimed = self.db.claimed_deals()
        mark = lambda items: [{**d, "claimed": d["key"] in claimed} for d in items]
        c = self.deals_cache
        return {"now": mark(c["now"]), "upcoming": mark(c["upcoming"]), "errors": c["errors"], "fetched_at": c["fetched_at"]}

    def refresh_deals(self, notify_new=True) -> dict:
        with self.deals_lock:
            result = deals_mod.fetch_all(time.time())
            # оба источника упали — оставляем старые данные, показываем ошибки
            if result["errors"] and not result["now"] and not result["upcoming"] and self.deals_cache["now"]:
                self.deals_cache = {**self.deals_cache, "errors": result["errors"]}
            else:
                self.deals_cache = result
            new = deals_mod.pick_new(result, self.db)
        if new and notify_new and self.cfg["deals"]["notify"]:
            titles = ", ".join(d["title"] for d in new[:3])
            more = f" и ещё {len(new) - 3}" if len(new) > 3 else ""
            notify.toast(f"Халява: {len(new)} новых", titles + more)
        return self.deals()

    def claim_deal(self, key: str, claimed: bool) -> dict:
        self.db.set_deal_claimed(key, claimed)
        return {"ok": True}

    # ---------- чистка ----------
    def cleaner(self) -> dict:
        out = []
        for t in cleaner.targets(self.steam_libs):
            out.append({**t, **cleaner.measure(t["paths"], t["min_age"])})
        return {"targets": out, "stale": self.library()["stale"]}

    def clean(self, ids: list) -> dict:
        wanted = {i for i in ids if isinstance(i, str)}
        results = []
        for t in cleaner.targets(self.steam_libs):
            if t["id"] in wanted:
                r = cleaner.clean(t["paths"], t["min_age"])
                results.append({"id": t["id"], "name": t["name"], **r})
                log.info("чистка %s: %s", t["id"], r)
        return {"results": results, "freed": sum(r["freed"] for r in results)}

    # ---------- сеть ----------
    def ping(self, minutes: int) -> dict:
        self.last_view = time.time()
        since = self.last_view - minutes * 60
        return {"series": self.ping_mon.series(since), "stats": self.ping_mon.stats(since),
                "targets": self.cfg["ping"]["targets"]}

    # ---------- настройки ----------
    def get_config(self) -> dict:
        return self.cfg

    def update_config(self, partial: dict) -> dict:
        check_partial(partial, config.DEFAULTS)
        with self.lock:
            new = config.deep_merge(self.cfg, partial)
            check_lists(new)
            if new["port"] != self.cfg["port"]:
                raise _api_error("порт меняется только в data/config.json при выключенной программе")
            old_extra = self.cfg["extra_games"]
            self.cfg.clear()
            self.cfg.update(new)
            config.save(self.cfg)
            self.ping_mon.set_targets(self.cfg["ping"]["targets"])
            for g in self.games:
                g["not_game"] = g["id"] in self.cfg["not_games"]
        if self.cfg["extra_games"] != old_extra:
            threading.Thread(target=self.rescan, daemon=True).start()
        return self.cfg

    def open_url(self, url: str) -> dict:
        if not url.startswith(("https://", "http://")):
            raise _api_error("можно открывать только http/https")
        webbrowser.open(url)
        return {"ok": True}

    def uninstall(self, game_id: str) -> dict:
        g = self.game(game_id)
        if g["source"] != "steam" or not str(g.get("appid") or "").isdigit():
            raise _api_error("удалить через Steam можно только игру из Steam")
        os.startfile(f"steam://uninstall/{g['appid']}")   # Steam сам спросит подтверждение
        return {"ok": True}

    def show_window(self) -> dict:
        if self.window_show:
            self.window_show()
        elif self.url:
            webbrowser.open(self.url)
        return {"ok": True}

    # ---------- обновления ----------
    def update_info(self) -> dict:
        return {"current": updater.VERSION, "update": self.update, "installed": bool(getattr(sys, "frozen", False))}

    def check_update(self) -> None:
        import urllib.error
        try:
            rel = updater.fetch_latest()
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            log.info("релизов на GitHub пока нет")
            return
        self.update = rel if rel and updater.is_newer(rel["version"]) else None
        if self.update and self.update_notified != self.update["version"]:
            self.update_notified = self.update["version"]
            notify.toast("Вышло обновление GameHub", f"Версия {self.update['version']} — обнови в панели")

    def install_update(self) -> dict:
        if not self.update:
            raise _api_error("обновлений нет")
        if not getattr(sys, "frozen", False):
            raise _api_error("обновление ставится только в установленную версию")
        url = self.update["url"]

        def run():
            try:
                updater.download_and_run(url)
            except updater.SignatureError:
                log.error("подпись обновления не совпала — не устанавливаю")
                notify.toast("Обновление не установлено", "Подпись файла не совпала с подписью автора. "
                                                         "Возможно, это подделка — не скачивай его вручную")
                return
            except Exception:
                log.exception("обновление не скачалось")
                notify.toast("Обновление не удалось", "Попробуй позже или скачай вручную с GitHub")
                return
            # установщик заменит файлы — закрываемся сами, аккуратно сохранив сессии
            if self.request_quit:
                self.request_quit()
        threading.Thread(target=run, name="update", daemon=True).start()
        return {"ok": True}

    def ping_needed(self, now: float) -> bool:
        """Пинг нужен во время игры (пишется в сессию) или пока панель открыта; в трее без игры — тишина."""
        return bool(self.tracker.running()) or now - self.last_view < PING_IDLE_SECONDS

    # ---------- фоновые циклы ----------
    def _loop(self, name, interval_fn, fn, first_delay=0.0):
        def run():
            if self.stop_event.wait(first_delay):
                return
            while not self.stop_event.is_set():
                try:
                    fn()
                except Exception:
                    log.exception("ошибка в цикле %s", name)
                try:
                    pause = loop_interval(interval_fn())
                except Exception:
                    pause = 60.0
                if self.stop_event.wait(pause):
                    return
        threading.Thread(target=run, name=name, daemon=True).start()

    def start_background(self) -> None:
        def track():
            self.tracker.tick()
            self._check_limit()

        def ping():
            if self.cfg["ping"]["enabled"] and self.ping_needed(time.time()):
                self.ping_mon.sample()

        def fetch_deals():
            if self.cfg["deals"]["enabled"]:
                self.refresh_deals()

        self._loop("tracker", lambda: self.cfg["poll_seconds"], track)
        self._loop("ping", lambda: self.cfg["ping"]["interval_seconds"], ping)
        self._loop("deals", lambda: self.cfg["deals"]["interval_hours"] * 3600, fetch_deals, first_delay=20)
        self._loop("library", lambda: LIBRARY_RESCAN_SECONDS, self.rescan, first_delay=LIBRARY_RESCAN_SECONDS)
        self._loop("update", lambda: UPDATE_CHECK_SECONDS, self.check_update, first_delay=30)

    def shutdown(self) -> None:
        self.stop_event.set()
        try:
            self.tracker.stop_all()
        except Exception:
            log.exception("ошибка при закрытии сессий")
        with self.lock:
            if self.gm_auto:
                self.gm.exit()


# ---------- трей ----------
def make_icon_image(size=64):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64
    d.rounded_rectangle((2 * s, 2 * s, 62 * s, 62 * s), radius=14 * s, fill=(14, 16, 12, 255), outline=(198, 255, 61, 255), width=int(3 * s))
    # стилизованный геймпад: крестовина и две кнопки
    d.rectangle((14 * s, 29 * s, 30 * s, 35 * s), fill=(198, 255, 61, 255))
    d.rectangle((19 * s, 24 * s, 25 * s, 40 * s), fill=(198, 255, 61, 255))
    d.ellipse((38 * s, 22 * s, 46 * s, 30 * s), fill=(198, 255, 61, 255))
    d.ellipse((44 * s, 33 * s, 52 * s, 41 * s), fill=(198, 255, 61, 255))
    return img


# ---------- окно ----------
# Окно — отдельный процесс (GameHub.exe --window): движок Edge держит сотни МБ, даже спрятанный.
# Крестик закрывает процесс целиком, в трее остаётся лёгкий процесс с учётом игр, сервером и иконкой.

def window_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--window"]
    return [sys.executable, str(ROOT / "app.py"), "--window"]


def _process_tree(pid: int) -> list[psutil.Process]:
    try:
        proc = psutil.Process(pid)
        return [proc] + proc.children(recursive=True)
    except psutil.Error:
        return []


def kill_tree(pid: int) -> None:
    for proc in reversed(_process_tree(pid)):
        try:
            proc.terminate()
        except psutil.Error:
            pass


def focus_process_window(pid: int) -> None:
    """Поднять окно уже открытой панели (из исходников окно у дочернего python, поэтому смотрим всё дерево)."""
    import ctypes
    from ctypes import wintypes
    pids = {p.pid for p in _process_tree(pid)}
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value in pids and user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(each, 0)
    for hwnd in found[:1]:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)   # SW_RESTORE
        user32.SetForegroundWindow(hwnd)


class WindowProc:
    """Процесс окна панели: открыть (или поднять уже открытое) и закрыть при выходе."""

    def __init__(self, url: str, popen=subprocess.Popen):
        self.url = url
        self.proc = None
        self.lock = threading.Lock()
        self._popen = popen

    def open(self) -> None:
        with self.lock:
            if self.proc is not None and self.proc.poll() is None:
                focus_process_window(self.proc.pid)
                return
            # адрес с ключом — через окружение: командную строку видят другие программы
            self.proc = self._popen(window_command(), env={**os.environ, "GAMEHUB_URL": self.url})

    def close(self) -> None:
        with self.lock:
            if self.proc is not None and self.proc.poll() is None:
                kill_tree(self.proc.pid)


def run_window_process() -> None:
    """Точка входа процесса окна (--window): только pywebview, закрыли — процесс завершился."""
    import webview
    url = os.environ.pop("GAMEHUB_URL", "")    # дочерним процессам движка ключ ни к чему
    if not url:
        return
    window = webview.create_window("GameHub", url, width=1440, height=900, min_size=(1000, 680),
                                   background_color="#0b0c0a")

    def dark_titlebar():
        # тёмная шапка окна Windows 11 (DWMWA_USE_IMMERSIVE_DARK_MODE = 20)
        try:
            import ctypes
            hwnd = int(window.native.Handle.ToInt64())
            on = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))
        except Exception:
            log.debug("тёмная шапка не включилась", exc_info=True)

    window.events.shown += dark_titlebar
    webview.start()


def run_tray(hub: Hub, url: str, hidden: bool, on_exit) -> None:
    """Иконка в трее (блокирует до «Выход»), окно панели — по требованию отдельным процессом."""
    import pystray
    win = WindowProc(url)

    def show(icon=None, item=None):
        win.open()

    def toggle_gm(icon, item):
        hub.gamemode_action("off" if hub.gm.active else "on")

    def kill(icon, item):
        killed = hub.gamemode_action("kill")["killed"]
        notify.toast("Режим игры", "Закрыто: " + ", ".join(killed) if killed else "Нечего закрывать")

    def quit_app(icon=None, item=None):
        tray.stop()      # tray.run() вернётся, дальше закрытие

    menu = pystray.Menu(
        pystray.MenuItem("Открыть GameHub", show, default=True),
        pystray.MenuItem("Режим игры", toggle_gm, checked=lambda item: hub.gm.active),
        pystray.MenuItem("Закрыть тяжёлые программы", kill),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", quit_app),
    )
    tray = pystray.Icon("GameHub", make_icon_image(), "GameHub", menu)
    notify.set_sink(lambda title, body: tray.notify(body, title))
    hub.window_show = show
    hub.request_quit = quit_app
    if not hidden:
        win.open()
    try:
        tray.run()
    finally:
        win.close()
        on_exit()


def _local_open(req, timeout):
    """Запрос к самому себе мимо системного прокси (иначе 127.0.0.1 может уйти в прокси)."""
    import urllib.request
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout)


def port_busy(port: int) -> bool:
    """Порт кем-то занят? Быстро, без сетевых запросов."""
    import socket
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def is_gamehub(url: str) -> bool:
    """На порту отвечает именно GameHub (а не чужая программа)?"""
    try:
        with _local_open(url + "/api/config", timeout=3) as resp:
            return resp.headers.get("Server", "").startswith("GameHub")
    except Exception as e:
        # чужой сервер может ответить ошибкой — смотрим заголовок и в ней
        headers = getattr(e, "headers", None)
        return bool(headers and headers.get("Server", "").startswith("GameHub"))


def setup_logging(name="gamehub.log") -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(config.DATA_DIR / name, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if sys.stderr is not None:   # под pythonw консоли нет
        root.addHandler(logging.StreamHandler())


def load_config() -> dict:
    """Настройки; битый config.json откладываем в сторону, чтобы программа всё равно запустилась."""
    try:
        return config.load()
    except (ValueError, OSError):
        log.exception("config.json не читается — начинаю с настроек по умолчанию")
        path = config.DATA_DIR / "config.json"
        try:
            os.replace(path, path.with_name("config.broken.json"))
        except OSError:
            pass
        return config.load()


INSTANCE_FILE = "instance.json"   # порт и ключ запущенного GameHub (папка данных доступна только владельцу)


def find_running(ports) -> int | None:
    """Порт уже запущенного GameHub или None.
    Только порт из instance.json: перебор диапазона отдал бы ключ любой программе,
    занявшей порт раньше и назвавшейся GameHub (на 127.0.0.1 порты общие для всех пользователей ПК)."""
    port = read_instance().get("port")
    # HTTP только к занятому порту: в Windows соединение с закрытым портом висит ~2 с
    if isinstance(port, int) and port in ports and port_busy(port) and is_gamehub(f"http://127.0.0.1:{port}"):
        return port
    return None


def write_instance(port: int, token: str) -> None:
    path = config.DATA_DIR / INSTANCE_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"port": port, "token": token}), encoding="utf-8")
    os.replace(tmp, path)


def read_instance() -> dict:
    try:
        data = json.loads((config.DATA_DIR / INSTANCE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def read_token() -> str:
    token = read_instance().get("token")
    return token if isinstance(token, str) else ""


def show_running(port: int) -> None:
    """Попросить запущенный GameHub показать окно (второй запуск ярлыка)."""
    import ctypes
    import urllib.request
    # окно откроет уже запущенный GameHub — разрешаем ему встать поверх (иначе Windows покажет его сзади)
    try:
        ctypes.windll.user32.AllowSetForegroundWindow(-1)   # ASFW_ANY
    except (AttributeError, OSError):
        pass
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/window/show", data=b"{}", method="POST",
                                 headers={"X-GameHub": read_token(), "Content-Type": "application/json"})
    try:
        _local_open(req, timeout=5).close()
    except Exception:
        log.exception("не удалось показать окно запущенного GameHub")


def bind_server(hub, ports, token):
    """Сервер на первом свободном порту из диапазона."""
    import server
    for port in ports:
        try:
            return server.make_server(hub, port, token), port
        except OSError:
            continue
    raise OSError(f"все порты {ports.start}–{ports.stop - 1} заняты")


def main() -> None:
    if "--window" in sys.argv:       # процесс окна: свой лог, чтобы два процесса не делили один файл
        setup_logging("window.log")
        run_window_process()
        return
    setup_logging()
    cfg = load_config()
    base = cfg["port"]
    if not isinstance(base, int) or not 1024 <= base <= 65535 - PORT_TRIES:
        log.warning("порт %r в config.json не подходит — беру %d", base, config.DEFAULTS["port"])
        base = config.DEFAULTS["port"]
    ports = range(base, base + PORT_TRIES)
    running = find_running(ports)
    if running:
        show_running(running)
        return

    db = DB(config.DATA_DIR / "gamehub.db")
    hub = Hub(cfg, db)
    token = secrets.token_urlsafe(32)
    try:
        httpd, port = bind_server(hub, ports, token)
    except OSError as e:
        log.error("%s", e)
        notify.toast("GameHub не запущен", str(e))
        return
    write_instance(port, token)
    url = f"http://127.0.0.1:{port}/?t={token}"   # ключ панель заберёт из адреса и уберёт его оттуда
    hub.url = url
    threading.Thread(target=httpd.serve_forever, name="http", daemon=True).start()
    hub.start_background()
    log.info("GameHub %s запущен: порт %d, игр: %d", updater.VERSION, port, len(hub.games))

    def on_exit():
        hub.shutdown()
        httpd.shutdown()

    if "--no-window" in sys.argv:   # отладка: только сервер, панель в браузере
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            on_exit()
        return
    run_tray(hub, url, "--hidden" in sys.argv, on_exit)


if __name__ == "__main__":
    main()