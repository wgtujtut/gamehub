"""Установленные игры: Steam, Epic, свои (из конфига)."""
import json
import os
from pathlib import Path

EPIC_MANIFESTS = Path(r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests")
TARKOV_KEY = r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\EscapeFromTarkov"
TARKOV_LAUNCHER = r"C:\Battlestate Games\BsgLauncher\BsgLauncher.exe"

# kind -> имя файла обложки Steam
COVER_FILES = {"portrait": "library_600x900.jpg", "header": "header.jpg", "hero": "library_hero.jpg"}
# в новом кэше Steam часть картинок лежит под другими именами
COVER_ALIASES = {"portrait": ["library_capsule.jpg"], "header": ["library_header.jpg"], "hero": []}


# ---------- VDF (Valve KeyValues) ----------

def _vdf_tokens(text: str):
    """Токены VDF: ("open", "{"), ("close", "}"), ("str", значение)."""
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif text.startswith("//", i):
            # комментарий до конца строки
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif c == "{":
            yield "open", c
            i += 1
        elif c == "}":
            yield "close", c
            i += 1
        elif c == '"':
            i += 1
            buf = []
            while i < n and text[i] != '"':
                # раскрываем только \\ и \"
                if text[i] == "\\" and i + 1 < n and text[i + 1] in '\\"':
                    buf.append(text[i + 1])
                    i += 2
                else:
                    buf.append(text[i])
                    i += 1
            i += 1  # закрывающая кавычка
            yield "str", "".join(buf)
        else:
            # токен без кавычек — до пробела, скобки или кавычки
            j = i
            while j < n and not text[j].isspace() and text[j] not in '{}"':
                j += 1
            yield "str", text[i:j]
            i = j


def parse_vdf(text: str) -> dict:
    """Разбор текстового VDF в dict. Повтор ключа — последний побеждает."""
    root = {}
    stack = [root]
    key = None
    for kind, value in _vdf_tokens(text):
        cur = stack[-1]
        if kind == "str":
            if key is None:
                key = value
            else:
                cur[key] = value
                key = None
        elif kind == "open":
            block = {}
            cur[key if key is not None else ""] = block
            stack.append(block)
            key = None
        else:  # close
            if len(stack) > 1:
                stack.pop()
            key = None
    return root


def get_ci(d: dict, key: str, default=None):
    """Значение по ключу без учёта регистра."""
    if not isinstance(d, dict):
        return default
    if key in d:
        return d[key]
    low = key.casefold()
    for k, v in d.items():
        if k.casefold() == low:
            return v
    return default


def _int(value) -> int:
    """Число из строки; не число — 0."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ---------- Steam ----------

def steam_root() -> Path | None:
    """Папка Steam из реестра (SteamPath), иначе стандартная. Нет папки — None."""
    path = None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            path = winreg.QueryValueEx(key, "SteamPath")[0]
    except (ImportError, OSError):
        pass
    for p in (path, r"C:\Program Files (x86)\Steam"):
        if p and Path(p).is_dir():
            return Path(p)
    return None


def steam_libraries(root: Path) -> list[Path]:
    """Корень Steam + все path из libraryfolders.vdf. Без дублей, только существующие."""
    root = Path(root)
    paths = [root]
    try:
        text = (root / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    folders = get_ci(parse_vdf(text), "libraryfolders")
    if isinstance(folders, dict):
        for item in folders.values():
            p = get_ci(item, "path")
            if isinstance(p, str) and p:
                paths.append(Path(p))
    result, seen = [], set()
    for p in paths:
        norm = os.path.normcase(os.path.abspath(p))
        if norm in seen or not p.is_dir():
            continue
        seen.add(norm)
        result.append(p)
    return result


def _steam_game(lib: Path, data: dict) -> dict | None:
    """Игра из разобранного appmanifest; нет нужных полей — None."""
    app = get_ci(data, "AppState")
    appid = get_ci(app, "appid")
    installdir = get_ci(app, "installdir")
    if not isinstance(appid, str) or not appid or not isinstance(installdir, str) or not installdir:
        return None
    name = get_ci(app, "name")
    if not isinstance(name, str) or not name:
        name = installdir
    return {
        "id": f"steam:{appid}",
        "name": name,
        "source": "steam",
        "appid": appid,
        "install_dir": str(lib / "steamapps" / "common" / installdir),
        "size_bytes": _int(get_ci(app, "SizeOnDisk")),
        "last_played": float(_int(get_ci(app, "LastPlayed"))),
        "launch": f"steam://rungameid/{appid}",
    }


def scan_steam(root: Path) -> list[dict]:
    """Игры из appmanifest_*.acf всех библиотек. Битые файлы пропускаются."""
    games = []
    for lib in steam_libraries(root):
        for f in sorted((lib / "steamapps").glob("appmanifest_*.acf")):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            game = _steam_game(lib, parse_vdf(text))
            if game:
                games.append(game)
    return games


# ---------- Epic ----------

def scan_epic(manifest_dir: Path = EPIC_MANIFESTS) -> list[dict]:
    """Игры из *.item лаунчера Epic. Недокачанные и не-игры пропускаются."""
    games = []
    for f in sorted(Path(manifest_dir).glob("*.item")):
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig", errors="replace"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("bIsIncompleteInstall"):
            continue
        cats = data.get("AppCategories")
        if cats is not None and "games" not in cats:
            continue
        app = data.get("AppName")
        if not app:
            continue
        ns = data.get("CatalogNamespace", "")
        item = data.get("CatalogItemId", "")
        games.append({
            "id": f"epic:{app}",
            "name": data.get("DisplayName") or app,
            "source": "epic",
            "appid": None,
            "install_dir": data.get("InstallLocation", ""),
            "size_bytes": _int(data.get("InstallSize")),
            "last_played": 0.0,
            "launch": f"com.epicgames.launcher://apps/{ns}%3A{item}%3A{app}?action=launch&silent=true",
        })
    return games


# ---------- Свои игры ----------

def detect_tarkov() -> dict | None:
    """Tarkov из реестра в формате extra_games. Нет ключа или папки — None."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, TARKOV_KEY)
    except (ImportError, OSError):
        return None
    values = {}
    with key:
        for name in ("InstallLocation", "DisplayName"):
            try:
                values[name] = winreg.QueryValueEx(key, name)[0]
            except OSError:
                pass
    location = values.get("InstallLocation")
    if not location or not os.path.isdir(location):
        return None
    return {
        "id": "custom:tarkov",
        "name": values.get("DisplayName") or "Escape from Tarkov",
        "dir": location,
        "launch": TARKOV_LAUNCHER if os.path.isfile(TARKOV_LAUNCHER) else "",
    }


def dir_size(path: Path) -> int:
    """Размер папки в байтах. Ссылки и junction не обходятся; ошибки доступа пропускаются."""
    total = 0
    try:
        it = os.scandir(path)
    except OSError:
        return 0
    with it:
        for entry in it:
            try:
                if entry.is_symlink() or os.path.isjunction(entry.path):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    total += dir_size(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
    return total


def custom_games(extra: list[dict], size_cache: dict | None = None) -> list[dict]:
    """Игры из extra_games. Размер — из size_cache или dir_size (кэш пополняется)."""
    games = []
    for item in extra:
        game_id = item.get("id")
        folder = item.get("dir")
        if not game_id or not folder or not os.path.isdir(folder):
            continue
        if size_cache is not None and game_id in size_cache:
            size = size_cache[game_id]
        else:
            size = dir_size(Path(folder))
            if size_cache is not None:
                size_cache[game_id] = size
        games.append({
            "id": game_id,
            "name": item.get("name") or game_id,
            "source": "custom",
            "appid": None,
            "install_dir": str(folder),
            "size_bytes": size,
            "last_played": 0.0,
            "launch": item.get("launch") or "",
        })
    return games


def scan_all(cfg: dict, size_cache: dict | None = None) -> list[dict]:
    """Все игры: Steam + Epic + свои + Tarkov. Без дублей, по имени, с полем not_game."""
    games = []
    root = steam_root()
    if root:
        games += scan_steam(root)
    games += scan_epic()
    extra = list(cfg.get("extra_games", []))
    tarkov = detect_tarkov()
    if tarkov and all(e.get("id") != tarkov["id"] for e in extra):
        extra.append(tarkov)
    games += custom_games(extra, size_cache)

    not_games = set(cfg.get("not_games", []))
    result, seen = [], set()
    for game in games:
        if game["id"] in seen:
            continue
        seen.add(game["id"])
        game["not_game"] = game["id"] in not_games
        result.append(game)
    result.sort(key=lambda g: g["name"].casefold())
    return result


# ---------- Обложки ----------

def find_cover(root: Path | None, appid: str, kind: str = "portrait") -> Path | None:
    """Обложка из локального кэша Steam (librarycache). Нет — None."""
    appid = str(appid)
    # appid приходит из URL — только цифры, чтобы не выйти за пределы папки
    if root is None or not (appid.isascii() and appid.isdigit()):
        return None
    kind = kind if kind in COVER_FILES else "portrait"
    cache = Path(root) / "appcache" / "librarycache"
    folder = cache / appid
    try:
        subs = sorted(x for x in folder.iterdir() if x.is_dir())
    except OSError:
        subs = []
    for fname in [COVER_FILES[kind]] + COVER_ALIASES[kind]:
        # прямо в папке appid, потом в подпапке с хэшем (новый формат), потом <appid>_<файл> (старый)
        for p in [folder / fname] + [sub / fname for sub in subs] + [cache / f"{appid}_{fname}"]:
            if p.is_file():
                return p
    return None


def cdn_cover(appid: str, kind: str = "portrait") -> str:
    """Ссылка на обложку в CDN Steam."""
    fname = COVER_FILES.get(kind, COVER_FILES["portrait"])
    return f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/{fname}"
