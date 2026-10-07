import json
import os
import shutil
from pathlib import Path

import pytest

import library

FIXTURES = Path(__file__).parent / "fixtures"


# ---------- помощники для фейкового Steam ----------

def vdf_str(value) -> str:
    """Строка для VDF: обратные слэши экранируются."""
    return str(value).replace("\\", "\\\\")


def write_libraryfolders(root: Path, paths: list) -> None:
    d = root / "steamapps"
    d.mkdir(parents=True, exist_ok=True)
    body = "".join(
        f'\t"{i}"\n\t{{\n\t\t"path"\t\t"{vdf_str(p)}"\n\t\t"label"\t\t""\n\t}}\n'
        for i, p in enumerate(paths)
    )
    (d / "libraryfolders.vdf").write_text('"libraryfolders"\n{\n' + body + "}\n", encoding="utf-8")


def write_manifest(lib: Path, appid: str, name: str, installdir: str, size="1000", last="0") -> None:
    d = lib / "steamapps"
    d.mkdir(parents=True, exist_ok=True)
    text = (
        '"AppState"\n{\n'
        f'\t"appid"\t\t"{appid}"\n'
        f'\t"name"\t\t"{name}"\n'
        f'\t"installdir"\t\t"{installdir}"\n'
        f'\t"SizeOnDisk"\t\t"{size}"\n'
        f'\t"LastPlayed"\t\t"{last}"\n'
        "}\n"
    )
    (d / f"appmanifest_{appid}.acf").write_text(text, encoding="utf-8")


def fake_steam(tmp_path: Path) -> tuple[Path, Path]:
    """Корень Steam + вторая библиотека: 730 в корне, реальный манифест Arma и битый файл во второй."""
    root = tmp_path / "steam"
    lib2 = tmp_path / "lib2"
    root.mkdir()
    lib2.mkdir()
    write_libraryfolders(root, [root, lib2])
    write_manifest(root, "730", "Counter-Strike 2", "Counter-Strike Global Offensive", size="74000000000", last="0")
    (lib2 / "steamapps").mkdir()
    shutil.copy(FIXTURES / "appmanifest_1874880.acf", lib2 / "steamapps" / "appmanifest_1874880.acf")
    (lib2 / "steamapps" / "appmanifest_999.acf").write_bytes(b"\xff\xfe\x00 garbage {{{ \"")
    return root, lib2


# ---------- parse_vdf / get_ci ----------

def test_parse_vdf_appmanifest():
    text = (FIXTURES / "appmanifest_1874880.acf").read_text(encoding="utf-8")
    app = library.parse_vdf(text)["AppState"]
    assert app["appid"] == "1874880"
    assert app["name"] == "Arma Reforger"
    assert app["SizeOnDisk"] == "26946681496"
    assert app["LauncherPath"] == "D:\\steam\\steam.exe"     # \\ раскрыт в один слэш
    assert app["InstalledDepots"]["1874881"]["size"] == "26946681496"
    assert app["SharedDepots"] == {"228989": "228980"}


def test_parse_vdf_libraryfolders():
    text = (FIXTURES / "libraryfolders.vdf").read_text(encoding="utf-8")
    folders = library.parse_vdf(text)["libraryfolders"]
    paths = [folders[k]["path"] for k in folders]
    assert paths == ["D:\\steam", "C:\\SteamLibrary", "F:\\SteamLibrary"]
    assert folders["1"]["apps"] == {}
    assert folders["2"]["apps"]["730"] == "73984302411"


def test_parse_vdf_escapes():
    text = r'"a" "x\\y"' + "\n" + r'"b" "say \"hi\""' + "\n" + r'"c" "keep\n"'
    assert library.parse_vdf(text) == {"a": "x\\y", "b": 'say "hi"', "c": "keep\\n"}


def test_parse_vdf_comments():
    text = (
        "// заголовок\n"
        '"root"\n{\n'
        '\t"k"\t"v"   // комментарий\n'
        '\t// "hidden" "x"\n'
        '\t"url"\t"http://site"\n'
        "}\n"
    )
    assert library.parse_vdf(text) == {"root": {"k": "v", "url": "http://site"}}


def test_parse_vdf_unquoted_and_repeat():
    assert library.parse_vdf("root { key value num 5 }") == {"root": {"key": "value", "num": "5"}}
    assert library.parse_vdf('"a" "1" "a" "2"') == {"a": "2"}


def test_get_ci():
    d = {"AppID": "1", "name": "x"}
    assert library.get_ci(d, "appid") == "1"
    assert library.get_ci(d, "NAME") == "x"
    assert library.get_ci(d, "nope") is None
    assert library.get_ci(d, "nope", "def") == "def"


# ---------- Steam ----------

def test_steam_libraries(tmp_path):
    root = tmp_path / "steam"
    lib2 = tmp_path / "lib2"
    root.mkdir()
    lib2.mkdir()
    # корень повторяется, одной папки нет
    write_libraryfolders(root, [root, lib2, tmp_path / "missing", root])
    assert library.steam_libraries(root) == [root, lib2]


def test_steam_libraries_without_vdf(tmp_path):
    assert library.steam_libraries(tmp_path) == [tmp_path]


def test_scan_steam(tmp_path):
    root, lib2 = fake_steam(tmp_path)
    games = {g["id"]: g for g in library.scan_steam(root)}
    assert set(games) == {"steam:730", "steam:1874880"}   # битый пропущен

    arma = games["steam:1874880"]
    assert arma["name"] == "Arma Reforger"
    assert arma["source"] == "steam"
    assert arma["appid"] == "1874880"
    assert arma["install_dir"] == str(lib2 / "steamapps" / "common" / "Arma Reforger")
    assert arma["size_bytes"] == 26946681496
    assert arma["last_played"] == 1788667086.0
    assert arma["launch"] == "steam://rungameid/1874880"

    cs = games["steam:730"]
    assert cs["install_dir"] == str(root / "steamapps" / "common" / "Counter-Strike Global Offensive")
    assert cs["size_bytes"] == 74000000000
    assert cs["last_played"] == 0.0
    assert isinstance(cs["last_played"], float)


# ---------- Epic ----------

def write_item(d: Path, fname: str, data: dict) -> None:
    (d / fname).write_text(json.dumps(data), encoding="utf-8")


def test_scan_epic(tmp_path):
    write_item(tmp_path, "a.item", {
        "DisplayName": "Fortnite", "InstallLocation": "D:\\Epic\\Fortnite", "AppName": "Fortnite",
        "CatalogNamespace": "fn", "CatalogItemId": "4fe75bbc", "InstallSize": 30000000000,
        "AppCategories": ["public", "games", "applications"], "bIsIncompleteInstall": False,
    })
    write_item(tmp_path, "b.item", {
        "DisplayName": "Half", "InstallLocation": "D:\\Epic\\Half", "AppName": "Half",
        "CatalogNamespace": "ns", "CatalogItemId": "id", "InstallSize": 1,
        "AppCategories": ["games"], "bIsIncompleteInstall": True,
    })
    write_item(tmp_path, "c.item", {
        "DisplayName": "Plugin", "InstallLocation": "D:\\Epic\\Plugin", "AppName": "Plugin",
        "CatalogNamespace": "ns", "CatalogItemId": "id", "InstallSize": 1,
        "AppCategories": ["plugins", "engine"],
    })
    (tmp_path / "broken.item").write_text("{ не json", encoding="utf-8")

    games = library.scan_epic(tmp_path)
    assert len(games) == 1
    g = games[0]
    assert g["id"] == "epic:Fortnite"
    assert g["name"] == "Fortnite"
    assert g["source"] == "epic"
    assert g["appid"] is None
    assert g["install_dir"] == "D:\\Epic\\Fortnite"
    assert g["size_bytes"] == 30000000000
    assert g["last_played"] == 0.0
    assert g["launch"] == "com.epicgames.launcher://apps/fn%3A4fe75bbc%3AFortnite?action=launch&silent=true"


def test_scan_epic_no_categories_is_game(tmp_path):
    write_item(tmp_path, "a.item", {"DisplayName": "Old", "AppName": "Old", "InstallLocation": "D:\\Old"})
    assert [g["id"] for g in library.scan_epic(tmp_path)] == ["epic:Old"]


def test_scan_epic_no_dir(tmp_path):
    assert library.scan_epic(tmp_path / "missing") == []


# ---------- dir_size / custom_games ----------

def test_dir_size(tmp_path):
    (tmp_path / "b" / "c").mkdir(parents=True)
    (tmp_path / "f1").write_bytes(b"x" * 100)
    (tmp_path / "b" / "f2").write_bytes(b"x" * 250)
    (tmp_path / "b" / "c" / "f3").write_bytes(b"x")
    assert library.dir_size(tmp_path) == 351


def test_dir_size_skips_symlink(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "big").write_bytes(b"x" * 1000)
    game = tmp_path / "game"
    game.mkdir()
    (game / "f").write_bytes(b"x" * 10)
    try:
        os.symlink(target, game / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("нет прав на создание ссылок")
    assert library.dir_size(game) == 10


def test_dir_size_missing(tmp_path):
    assert library.dir_size(tmp_path / "missing") == 0


def test_custom_games(tmp_path):
    d1 = tmp_path / "g1"
    d2 = tmp_path / "g2"
    d1.mkdir()
    d2.mkdir()
    (d1 / "a").write_bytes(b"x" * 10)
    (d1 / "b").write_bytes(b"x" * 20)
    extra = [
        {"id": "custom:x", "name": "X", "dir": str(d1), "launch": "C:\\x.exe"},
        {"id": "custom:gone", "name": "Gone", "dir": str(tmp_path / "missing")},
        {"id": "custom:y", "name": "Y", "dir": str(d2)},
    ]
    cache = {}
    games = {g["id"]: g for g in library.custom_games(extra, cache)}
    assert set(games) == {"custom:x", "custom:y"}
    x = games["custom:x"]
    assert x["source"] == "custom"
    assert x["appid"] is None
    assert x["install_dir"] == str(d1)
    assert x["size_bytes"] == 30
    assert x["last_played"] == 0.0
    assert x["launch"] == "C:\\x.exe"
    assert games["custom:y"]["launch"] == ""
    assert cache == {"custom:x": 30, "custom:y": 0}

    # значение из кэша берётся без пересчёта
    games = {g["id"]: g for g in library.custom_games(extra, {"custom:x": 999})}
    assert games["custom:x"]["size_bytes"] == 999

    # без кэша тоже работает
    assert len(library.custom_games(extra)) == 2


# ---------- scan_all ----------

def test_scan_all(tmp_path, monkeypatch):
    root, lib2 = fake_steam(tmp_path)
    # дубль 730 во второй библиотеке и не-игра
    write_manifest(lib2, "730", "CS dup", "cs")
    write_manifest(lib2, "228980", "Steamworks Common Redistributables", "Steamworks Shared")
    tarkov_dir = tmp_path / "tarkov"
    tarkov_dir.mkdir()
    epic = {
        "id": "epic:alpha", "name": "alpha game", "source": "epic", "appid": None,
        "install_dir": "D:\\Epic\\alpha", "size_bytes": 1, "last_played": 0.0, "launch": "",
    }
    monkeypatch.setattr(library, "steam_root", lambda: root)
    monkeypatch.setattr(library, "scan_epic", lambda *a, **k: [dict(epic), dict(epic)])
    monkeypatch.setattr(library, "detect_tarkov", lambda: {
        "id": "custom:tarkov", "name": "Escape from Tarkov", "dir": str(tarkov_dir), "launch": "",
    })
    cfg = {
        "not_games": ["steam:228980"],
        "extra_games": [{"id": "custom:tarkov", "name": "Tarkov мой", "dir": str(tarkov_dir), "launch": "L"}],
    }
    games = library.scan_all(cfg, {})
    assert [g["name"] for g in games] == [
        "alpha game", "Arma Reforger", "Counter-Strike 2", "Steamworks Common Redistributables", "Tarkov мой",
    ]
    by_id = {g["id"]: g for g in games}
    assert len(by_id) == len(games)
    assert by_id["steam:228980"]["not_game"] is True
    assert by_id["steam:730"]["not_game"] is False
    assert by_id["custom:tarkov"]["launch"] == "L"


def test_scan_all_adds_tarkov_without_steam(tmp_path, monkeypatch):
    tarkov_dir = tmp_path / "tarkov"
    tarkov_dir.mkdir()
    monkeypatch.setattr(library, "steam_root", lambda: None)
    monkeypatch.setattr(library, "scan_epic", lambda *a, **k: [])
    monkeypatch.setattr(library, "detect_tarkov", lambda: {
        "id": "custom:tarkov", "name": "Escape from Tarkov", "dir": str(tarkov_dir), "launch": "",
    })
    games = library.scan_all({"not_games": [], "extra_games": []})
    assert [(g["id"], g["name"], g["not_game"]) for g in games] == [
        ("custom:tarkov", "Escape from Tarkov", False),
    ]


# ---------- обложки ----------

def test_find_cover(tmp_path):
    cache = tmp_path / "appcache" / "librarycache"
    (cache / "730" / "abc123hash").mkdir(parents=True)
    portrait = cache / "730" / "library_600x900.jpg"
    portrait.write_bytes(b"jpg")
    header = cache / "730" / "abc123hash" / "header.jpg"
    header.write_bytes(b"jpg")
    old = cache / "440_header.jpg"
    old.write_bytes(b"jpg")

    assert library.find_cover(tmp_path, "730") == portrait
    assert library.find_cover(tmp_path, "730", "header") == header
    assert library.find_cover(tmp_path, "440", "header") == old
    assert library.find_cover(tmp_path, "730", "hero") is None
    assert library.find_cover(tmp_path, "999") is None
    assert library.find_cover(None, "730") is None
    assert library.find_cover(tmp_path, "..\\730") is None


def test_cdn_cover():
    base = "https://cdn.cloudflare.steamstatic.com/steam/apps/730/"
    assert library.cdn_cover("730") == base + "library_600x900.jpg"
    assert library.cdn_cover("730", "header") == base + "header.jpg"
    assert library.cdn_cover("730", "hero") == base + "library_hero.jpg"


def test_find_cover_new_names(tmp_path):
    folder = tmp_path / "appcache" / "librarycache" / "2950790"
    folder.mkdir(parents=True)
    (folder / "library_capsule.jpg").write_bytes(b"x")
    (folder / "library_header.jpg").write_bytes(b"x")
    assert library.find_cover(tmp_path, "2950790", "portrait") == folder / "library_capsule.jpg"
    assert library.find_cover(tmp_path, "2950790", "header") == folder / "library_header.jpg"
    assert library.find_cover(tmp_path, "2950790", "hero") is None
