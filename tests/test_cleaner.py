import _winapi
import os

import cleaner


def make(path, data=b""):
    """Создать файл (и папки над ним)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def fake_env(tmp_path):
    env = {
        "TEMP": str(tmp_path / "Temp"),
        "LOCALAPPDATA": str(tmp_path / "Local"),
        "APPDATA": str(tmp_path / "Roaming"),
    }
    return env


def by_id(items):
    return {t["id"]: t for t in items}


# --- targets ---

def test_targets_only_existing(tmp_path):
    env = fake_env(tmp_path)
    local = tmp_path / "Local"
    (tmp_path / "Temp").mkdir()
    (local / "NVIDIA" / "DXCache").mkdir(parents=True)
    # Firefox: два профиля с cache2, один без
    (local / "Mozilla/Firefox/Profiles/abc.default-release/cache2").mkdir(parents=True)
    (local / "Mozilla/Firefox/Profiles/xyz.dev/cache2").mkdir(parents=True)
    (local / "Mozilla/Firefox/Profiles/empty.profile").mkdir(parents=True)
    # Chrome: Cache в одном профиле, Code Cache в другом
    (local / "Google/Chrome/User Data/Default/Cache").mkdir(parents=True)
    (local / "Google/Chrome/User Data/Profile 1/Code Cache").mkdir(parents=True)
    (local / "EpicGamesLauncher/Saved/webcache_4147").mkdir(parents=True)

    res = by_id(cleaner.targets([], env))

    assert set(res) == {"temp", "nvidia", "firefox", "chrome", "epic"}
    assert res["temp"]["paths"] == [env["TEMP"]]
    assert res["temp"]["default"] is True
    assert res["nvidia"]["paths"] == [str(local / "NVIDIA" / "DXCache")]
    assert res["nvidia"]["default"] is False
    assert res["nvidia"]["note"]
    assert sorted(res["firefox"]["paths"]) == sorted([
        str(local / "Mozilla/Firefox/Profiles/abc.default-release/cache2"),
        str(local / "Mozilla/Firefox/Profiles/xyz.dev/cache2"),
    ])
    assert sorted(res["chrome"]["paths"]) == sorted([
        str(local / "Google/Chrome/User Data/Default/Cache"),
        str(local / "Google/Chrome/User Data/Profile 1/Code Cache"),
    ])
    assert res["epic"]["paths"] == [str(local / "EpicGamesLauncher/Saved/webcache_4147")]
    for t in res.values():
        assert set(t) == {"id", "name", "paths", "note", "default", "min_age"}


def test_targets_steam_shadercache_many_libs(tmp_path):
    env = fake_env(tmp_path)
    lib1 = tmp_path / "Steam"
    lib2 = tmp_path / "SteamLibrary"
    lib3 = tmp_path / "NoShader"
    (lib1 / "steamapps" / "shadercache").mkdir(parents=True)
    (lib2 / "steamapps" / "shadercache").mkdir(parents=True)
    (lib3 / "steamapps").mkdir(parents=True)

    res = by_id(cleaner.targets([lib1, lib2, lib3], env))

    assert res["steam_shader"]["paths"] == [
        str(lib1 / "steamapps" / "shadercache"),
        str(lib2 / "steamapps" / "shadercache"),
    ]
    assert res["steam_shader"]["default"] is False


def test_targets_empty_not_returned(tmp_path):
    # ничего не существует — пустой список
    assert cleaner.targets([tmp_path / "nope"], fake_env(tmp_path)) == []


def test_targets_missing_env_no_relative_paths(tmp_path, monkeypatch):
    # переменных нет — относительные пути от текущей папки не должны всплыть
    monkeypatch.chdir(tmp_path)
    (tmp_path / "D3DSCache").mkdir()
    (tmp_path / "CrashDumps").mkdir()
    assert cleaner.targets([], {}) == []


def test_targets_discord_and_pip(tmp_path):
    env = fake_env(tmp_path)
    (tmp_path / "Roaming/discord/Cache").mkdir(parents=True)
    (tmp_path / "Roaming/discord/GPUCache").mkdir(parents=True)
    (tmp_path / "Local/pip/cache").mkdir(parents=True)

    res = by_id(cleaner.targets([], env))

    assert res["discord"]["paths"] == [
        str(tmp_path / "Roaming/discord/Cache"),
        str(tmp_path / "Roaming/discord/GPUCache"),
    ]
    assert res["pip"]["default"] is False


# --- measure / clean ---

def test_measure(tmp_path):
    root = tmp_path / "cache"
    make(root / "a.bin", b"12345")
    make(root / "sub" / "b.bin", b"123")
    make(root / "sub" / "deep" / "c.bin", b"")

    assert cleaner.measure([str(root)]) == {"bytes": 8, "files": 3}


def test_measure_missing_path(tmp_path):
    assert cleaner.measure([str(tmp_path / "nope")]) == {"bytes": 0, "files": 0}


def test_clean_removes_content_keeps_root(tmp_path):
    root = tmp_path / "cache"
    make(root / "a.bin", b"12345")
    make(root / "sub" / "b.bin", b"123")
    (root / "empty").mkdir()

    res = cleaner.clean([str(root)])

    assert root.is_dir()
    assert list(root.iterdir()) == []
    assert res == {"freed": 8, "deleted": 2, "skipped": 0}


def test_clean_junction_inside_not_followed(tmp_path):
    outside = tmp_path / "outside"
    precious = make(outside / "precious.txt", b"x" * 100)
    root = tmp_path / "cache"
    make(root / "a.bin", b"123")
    link = root / "link"
    _winapi.CreateJunction(str(outside), str(link))

    # measure не считает то, что за junction
    assert cleaner.measure([str(root)]) == {"bytes": 3, "files": 1}

    res = cleaner.clean([str(root)])

    assert precious.exists()
    assert precious.read_bytes() == b"x" * 100
    assert not os.path.lexists(link)
    assert root.is_dir()
    assert list(root.iterdir()) == []
    assert res["freed"] == 3
    assert res["skipped"] == 0


def test_clean_root_junction_skipped(tmp_path):
    outside = tmp_path / "outside"
    precious = make(outside / "precious.txt", b"data")
    link = tmp_path / "link"
    _winapi.CreateJunction(str(outside), str(link))

    assert cleaner.measure([str(link)]) == {"bytes": 0, "files": 0}
    res = cleaner.clean([str(link)])

    assert precious.exists()
    assert os.path.isjunction(link)
    assert res["deleted"] == 0
    assert res["freed"] == 0


def test_clean_busy_file_skipped(tmp_path):
    root = tmp_path / "cache"
    make(root / "free.bin", b"12")
    busy = root / "busy.txt"
    with open(busy, "w") as fh:
        fh.write("busy")
        fh.flush()
        res = cleaner.clean([str(root)])  # не должно бросить исключение
    assert res["skipped"] >= 1
    assert busy.exists()
    assert not (root / "free.bin").exists()
    assert res["deleted"] == 1


# --- stale_games ---

DAY = 86400


def test_stale_games():
    now = 1_000 * DAY
    games = [
        {"id": "steam:1", "name": "Старая", "size_bytes": 100, "last_played": now - 100 * DAY},
        {"id": "steam:2", "name": "Свежая по library", "size_bytes": 500, "last_played": now - 1 * DAY},
        {"id": "steam:3", "name": "Свежая по totals", "size_bytes": 700, "last_played": now - 100 * DAY},
        {"id": "steam:4", "name": "Никогда", "size_bytes": 300, "last_played": 0.0},
        {"id": "steam:5", "name": "Не игра", "size_bytes": 900, "last_played": 0.0, "not_game": True},
        {"id": "custom:x", "name": "Своя", "size_bytes": 50, "last_played": 0.0},
    ]
    totals = {
        "steam:3": {"seconds": 10.0, "last": now - 2 * DAY, "sessions": 1},
        "custom:x": {"seconds": 10.0, "last": now - 61 * DAY, "sessions": 1},
    }

    res = cleaner.stale_games(games, totals, now, 60)

    assert [g["id"] for g in res["games"]] == ["steam:4", "steam:1", "custom:x"]
    assert res["bytes"] == 300 + 100 + 50
    assert res["games"][0] == {"id": "steam:4", "name": "Никогда", "size_bytes": 300, "last": 0.0}
    assert res["games"][2]["last"] == now - 61 * DAY


def test_stale_games_threshold():
    now = 1_000 * DAY
    games = [{"id": "steam:1", "name": "A", "size_bytes": 1, "last_played": now - 60 * DAY}]
    # ровно на пороге — ещё не давно
    assert cleaner.stale_games(games, {}, now, 60)["games"] == []
    assert len(cleaner.stale_games(games, {}, now, 59)["games"]) == 1


def test_min_age_keeps_fresh_files(tmp_path):
    import os
    root = tmp_path / "temp"
    (root / "sub").mkdir(parents=True)
    old = root / "old.tmp"
    old.write_bytes(b"x" * 10)
    fresh = root / "sub" / "fresh.tmp"
    fresh.write_bytes(b"y" * 5)
    now = 1_800_000_000.0
    os.utime(old, (now - 2 * 86400, now - 2 * 86400))
    os.utime(fresh, (now - 60, now - 60))
    assert cleaner.measure([str(root)], 86400, now=now) == {"bytes": 10, "files": 1}
    res = cleaner.clean([str(root)], 86400, now=now)
    assert res["freed"] == 10 and res["deleted"] == 1
    assert not old.exists() and fresh.exists()


def test_temp_target_has_min_age(tmp_path):
    (tmp_path / "t").mkdir()
    (tmp_path / "l" / "CrashDumps").mkdir(parents=True)
    ts = {t["id"]: t for t in cleaner.targets([], env={"TEMP": str(tmp_path / "t"), "LOCALAPPDATA": str(tmp_path / "l")})}
    assert ts["temp"]["min_age"] == 86400
    assert ts["crashdumps"]["min_age"] == 0


def test_pip_cache_dir_env(tmp_path):
    moved = tmp_path / "D" / "cache" / "pip"
    moved.mkdir(parents=True)
    (tmp_path / "l" / "pip" / "cache").mkdir(parents=True)
    ts = {t["id"]: t for t in cleaner.targets([], env={"LOCALAPPDATA": str(tmp_path / "l"), "PIP_CACHE_DIR": str(moved)})}
    assert ts["pip"]["paths"] == [str(moved)]


def test_is_safe_root():
    env = {"USERPROFILE": r"C:\Users\me", "SystemRoot": r"C:\Windows", "LOCALAPPDATA": r"C:\Users\me\AppData\Local"}
    for bad in ["C:\\", "D:\\", r"D:\cache", r"C:\Users", r"C:\Users\me", r"C:\Users\me\AppData", r"C:\Users\me\AppData\Local", r"C:\Windows"]:
        assert not cleaner.is_safe_root(bad, env), bad
    for ok in [r"D:\cache\pip", r"C:\Users\me\AppData\Local\Temp", r"C:\Users\me\AppData\Local\pip\cache"]:
        assert cleaner.is_safe_root(ok, env), ok


def test_targets_skip_dangerous_env(tmp_path):
    # TEMP и PIP_CACHE_DIR указывают на корень диска — такие цели не предлагаются вовсе
    drive = os.path.splitdrive(str(tmp_path))[0] + "\\"
    ts = {t["id"]: t for t in cleaner.targets([], env={"TEMP": drive, "PIP_CACHE_DIR": drive, "LOCALAPPDATA": str(tmp_path)})}
    assert "temp" not in ts and "pip" not in ts


def test_clean_refuses_dangerous_root(monkeypatch, tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "important.txt").write_text("x")
    monkeypatch.setattr(cleaner, "is_safe_root", lambda p, env=None: False)
    res = cleaner.clean([str(victim)])
    assert res["skipped"] == 1 and (victim / "important.txt").exists()
