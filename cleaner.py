"""Чистка кэшей и поиск давно заброшенных игр."""
import glob
import os
import time

SHADER_NOTE = "пересоберётся, первые минуты в игре могут быть подлагивания"


def _p(base, *parts):
    """Шаблон пути от базовой папки; базы нет — None (иначе вышел бы относительный путь)."""
    if not base:
        return None
    return os.path.join(glob.escape(str(base)), *parts)


def _expand(patterns):
    """Раскрыть glob, оставить только существующие папки, без дублей."""
    result = []
    seen = set()
    for pat in patterns:
        if pat is None:
            continue
        for p in sorted(glob.glob(pat)):
            key = os.path.normcase(os.path.abspath(p))
            if os.path.isdir(p) and key not in seen:
                seen.add(key)
                result.append(p)
    return result


def _is_link(path):
    return os.path.islink(path) or os.path.isjunction(path)


def targets(steam_libs, env=None):
    """Список целей для чистки; только существующие пути."""
    env = os.environ if env is None else env
    temp = env.get("TEMP")
    local = env.get("LOCALAPPDATA")
    roaming = env.get("APPDATA")
    raw = [
        ("temp", "Временные файлы", [_p(temp)], "только старше суток — свежие нужны запущенным программам", True),
        ("nvidia", "Кэш шейдеров NVIDIA", [
            _p(local, "NVIDIA", "DXCache"),
            _p(local, "NVIDIA", "GLCache"),
            _p(local, "NVIDIA Corporation", "NV_Cache"),
        ], SHADER_NOTE, False),
        ("d3d", "Кэш шейдеров DirectX", [_p(local, "D3DSCache")], SHADER_NOTE, False),
        ("steam_shader", "Кэш шейдеров Steam",
         [_p(lib, "steamapps", "shadercache") for lib in steam_libs], SHADER_NOTE, False),
        ("steam_web", "Кэш браузера Steam", [_p(local, "Steam", "htmlcache")], "", True),
        ("discord", "Кэш Discord", [
            _p(roaming, "discord", "Cache"),
            _p(roaming, "discord", "Code Cache"),
            _p(roaming, "discord", "GPUCache"),
        ], "", True),
        ("chrome", "Кэш Chrome", [
            _p(local, "Google", "Chrome", "User Data", "*", "Cache"),
            _p(local, "Google", "Chrome", "User Data", "*", "Code Cache"),
        ], "", True),
        ("firefox", "Кэш Firefox",
         [_p(local, "Mozilla", "Firefox", "Profiles", "*", "cache2")], "", True),
        ("crashdumps", "Дампы падений", [_p(local, "CrashDumps")], "", True),
        ("epic", "Кэш Epic Launcher",
         [_p(local, "EpicGamesLauncher", "Saved", "webcache*")], "", True),
        # PIP_CACHE_DIR — если кэш перенесён (у пользователя он на D:\cache\pip)
        ("pip", "Кэш pip", [_p(env.get("PIP_CACHE_DIR")) or _p(local, "pip", "cache")], "", False),
    ]
    result = []
    for tid, name, patterns, note, default in raw:
        paths = _expand(patterns)
        if paths:
            # из temp удаляем только то, что не трогали сутки: свежие файлы могут быть нужны запущенным программам
            min_age = 86400 if tid == "temp" else 0
            result.append({"id": tid, "name": name, "paths": paths, "note": note, "default": default, "min_age": min_age})
    return result


def _measure_dir(path, acc, cutoff):
    try:
        with os.scandir(path) as it:
            entries = list(it)
    except OSError:
        return
    for entry in entries:
        try:
            # ссылки и junction не обходим и не считаем
            if entry.is_symlink() or os.path.isjunction(entry.path):
                continue
            if entry.is_dir(follow_symlinks=False):
                _measure_dir(entry.path, acc, cutoff)
            else:
                st = entry.stat(follow_symlinks=False)
                if st.st_mtime > cutoff:
                    continue
                acc["bytes"] += st.st_size
                acc["files"] += 1
        except OSError:
            continue


def measure(paths, min_age=0, now=None):
    """Размер и число файлов в папках (только файлы старше min_age секунд)."""
    cutoff = (time.time() if now is None else now) - min_age if min_age else float("inf")
    acc = {"bytes": 0, "files": 0}
    for path in paths:
        if _is_link(path):
            continue
        _measure_dir(path, acc, cutoff)
    return acc


def _clean_dir(path, res, cutoff):
    """Удалить содержимое папки. True — всё удалилось."""
    try:
        with os.scandir(path) as it:
            entries = list(it)
    except FileNotFoundError:
        return True
    except OSError:
        res["skipped"] += 1
        return False
    ok = True
    for entry in entries:
        try:
            if os.path.isjunction(entry.path):
                # удаляем саму ссылку, внутрь не заходим
                os.rmdir(entry.path)
                res["deleted"] += 1
            elif entry.is_symlink():
                os.unlink(entry.path)
                res["deleted"] += 1
            elif entry.is_dir(follow_symlinks=False):
                if _clean_dir(entry.path, res, cutoff):
                    os.rmdir(entry.path)
                else:
                    ok = False
            else:
                st = entry.stat(follow_symlinks=False)
                if st.st_mtime > cutoff:
                    ok = False  # свежий файл — оставляем, папку тоже
                    continue
                size = st.st_size
                os.unlink(entry.path)
                res["freed"] += size
                res["deleted"] += 1
        except FileNotFoundError:
            continue  # уже удалили без нас
        except OSError:
            res["skipped"] += 1
            ok = False
    return ok


def clean(paths, min_age=0, now=None):
    """Удалить содержимое каждой папки, сами папки оставить. min_age — не трогать файлы моложе (сек)."""
    cutoff = (time.time() if now is None else now) - min_age if min_age else float("inf")
    res = {"freed": 0, "deleted": 0, "skipped": 0}
    for path in paths:
        if _is_link(path):
            res["skipped"] += 1  # папка-ссылка — не трогаем целиком
            continue
        if not os.path.isdir(path):
            continue
        _clean_dir(path, res, cutoff)
    return res


def stale_games(games, totals, now, days):
    """Игры, в которые давно не играли (или не играли никогда)."""
    out = []
    for g in games:
        if g.get("not_game"):
            continue
        last = max(g.get("last_played") or 0.0, totals.get(g["id"], {}).get("last") or 0.0)
        if last == 0 or now - last > days * 86400:
            out.append({"id": g["id"], "name": g.get("name", ""),
                        "size_bytes": g.get("size_bytes") or 0, "last": float(last)})
    out.sort(key=lambda x: x["size_bytes"], reverse=True)
    return {"games": out, "bytes": sum(x["size_bytes"] for x in out)}
