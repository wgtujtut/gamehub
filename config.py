"""Настройки: значения по умолчанию, слитые с config.json в папке данных."""
import copy
import json
import os
import sys
from pathlib import Path

# данные пользователя: %APPDATA%\GameHub (GAMEHUB_DATA — для тестов и отладки)
DATA_DIR = Path(os.environ.get("GAMEHUB_DATA") or Path(os.environ.get("APPDATA") or Path.home()) / "GameHub")
# файлы программы (web/): в собранном exe PyInstaller распаковывает их в sys._MEIPASS
RES_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

DEFAULTS = {
    "port": 8790,
    "poll_seconds": 10,
    "min_session_seconds": 60,
    "stale_days": 60,
    # Steamworks Redist, OBS Studio, VTube Studio, Soundpad, Wallpaper Engine, PZ Dedicated Server, Bongo Cat (висит в фоне)
    "not_games": ["steam:228980", "steam:1905180", "steam:1325860", "steam:629520", "steam:431960", "steam:380870", "steam:3487310"],
    # [{"id": "custom:tarkov", "name": "...", "dir": "D:\\games\\EscapeFromTarkov", "launch": "C:\\...\\BsgLauncher.exe"}]
    "extra_games": [],
    "gamemode": {
        "auto": True,             # включать при старте игры
        "power_plan": True,       # переключать план питания на максимальный
        "kill_on_start": False,   # закрывать программы из kill_list при старте игры
        "kill_list": [],          # имена процессов, у каждого свои
    },
    "deals": {"enabled": True, "interval_hours": 3, "notify": True},
    "ping": {
        "enabled": True,
        "interval_seconds": 5,
        "targets": [
            {"name": "Cloudflare", "host": "1.1.1.1", "port": 443},
            {"name": "Google", "host": "8.8.8.8", "port": 443},
            {"name": "Steam", "host": "api.steampowered.com", "port": 443},
        ],
    },
    "limits": {"daily_minutes": 0},     # 0 — выключено; иначе уведомление, когда за сутки наиграно больше
    "notify_session_end": True,
}


def _path(path: Path | None) -> Path:
    """Путь к config.json (по умолчанию в папке данных)."""
    return Path(path) if path is not None else DATA_DIR / "config.json"


def deep_merge(base: dict, over: dict) -> dict:
    """Новый dict: вложенные dict сливаются, остальное заменяется из over."""
    result = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load(path: Path | None = None) -> dict:
    """DEFAULTS, слитые с config.json; файла нет — копия DEFAULTS."""
    path = _path(path)
    if not path.exists():
        return copy.deepcopy(DEFAULTS)
    data = json.loads(path.read_text(encoding="utf-8"))
    return deep_merge(DEFAULTS, data)


def save(cfg: dict, path: Path | None = None) -> None:
    """Атомарная запись: сначала .tmp, потом os.replace."""
    path = _path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
