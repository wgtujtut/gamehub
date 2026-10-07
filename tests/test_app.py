import copy

import pytest

import app
import config
import server


def test_check_partial_ok():
    app.check_partial({"gamemode": {"auto": False, "kill_list": ["x"]}, "limits": {"daily_minutes": 120}},
                      config.DEFAULTS)


@pytest.mark.parametrize("partial", [
    {"unknown": 1},
    {"gamemode": {"nope": True}},
    {"gamemode": {"auto": "yes"}},
    {"gamemode": {"auto": 1}},
    {"limits": {"daily_minutes": True}},
    {"limits": {"daily_minutes": -5}},
    {"not_games": "steam:1"},
    {"ping": []},
])
def test_check_partial_rejects(partial):
    with pytest.raises(server.ApiError):
        app.check_partial(partial, config.DEFAULTS)


def test_check_lists_ok():
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg["extra_games"] = [{"id": "custom:minecraft", "name": "Minecraft", "dir": "D:\\Games\\MC", "launch": ""}]
    app.check_lists(cfg)


@pytest.mark.parametrize("change", [
    lambda c: c["ping"]["targets"].append({"name": "x", "host": "1.1.1.1", "port": 70000}),
    lambda c: c["ping"]["targets"].append({"name": "", "host": "1.1.1.1", "port": 443}),
    lambda c: c["ping"]["targets"].append("1.1.1.1"),
    lambda c: c["extra_games"].append({"id": "steam:1", "name": "x", "dir": "D:\\x"}),
    lambda c: c["extra_games"].append({"id": "custom:x", "name": "x"}),
    lambda c: c["gamemode"]["kill_list"].append(5),
    lambda c: c["not_games"].append(None),
])
def test_check_lists_rejects(change):
    cfg = copy.deepcopy(config.DEFAULTS)
    change(cfg)
    with pytest.raises(server.ApiError):
        app.check_lists(cfg)


def test_icon_image():
    img = app.make_icon_image(64)
    assert img.size == (64, 64)


def test_bind_server_skips_busy_port():
    import socket
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen()
    port = busy.getsockname()[1]
    try:
        httpd, got = app.bind_server(type("H", (), {"cfg": {}})(), range(port, port + 5), "tok")
        httpd.server_close()
        assert got != port
    finally:
        busy.close()


def test_load_config_broken_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    (tmp_path / "config.json").write_text("{битый", encoding="utf-8")
    cfg = app.load_config()
    assert cfg == config.DEFAULTS
    assert (tmp_path / "config.broken.json").exists()
    assert not (tmp_path / "config.json").exists()


def test_data_dir_from_env():
    import os
    assert str(config.DATA_DIR) == os.environ["GAMEHUB_DATA"]
    assert config.DEFAULTS["gamemode"]["kill_list"] == []


class FakeHub(app.Hub):
    """Hub без сканирования диска: только то, что нужно методам."""
    def __init__(self, games):
        self.games = games
        self.update = None
        self.window_show = None
        self.request_quit = None
        self.url = "http://127.0.0.1:1"


def test_uninstall_only_steam(monkeypatch):
    opened = []
    monkeypatch.setattr(app.os, "startfile", opened.append, raising=False)
    hub = FakeHub([{"id": "steam:730", "source": "steam", "appid": "730"},
                   {"id": "custom:tarkov", "source": "custom", "appid": None}])
    hub.uninstall("steam:730")
    assert opened == ["steam://uninstall/730"]
    with pytest.raises(server.ApiError):
        hub.uninstall("custom:tarkov")
    with pytest.raises(server.ApiError):
        hub.uninstall("steam:999")


def test_show_window_callback():
    hub = FakeHub([])
    calls = []
    hub.window_show = lambda: calls.append(1)
    hub.show_window()
    assert calls == [1]


def test_check_update(monkeypatch):
    hub = FakeHub([])
    hub.update_notified = ""
    toasts = []
    monkeypatch.setattr(app.notify, "toast", lambda t, b: toasts.append(t))
    monkeypatch.setattr(app.updater, "fetch_latest", lambda: {"version": "99.0.0", "url": "u", "notes": "", "page": "p"})
    hub.check_update()
    hub.check_update()
    assert hub.update["version"] == "99.0.0" and len(toasts) == 1   # уведомление один раз на версию
    monkeypatch.setattr(app.updater, "fetch_latest", lambda: {"version": app.updater.VERSION, "url": "u", "notes": "", "page": "p"})
    hub.check_update()
    assert hub.update is None


def test_install_update_needs_frozen():
    hub = FakeHub([])
    with pytest.raises(server.ApiError):
        hub.install_update()          # обновлений нет
    hub.update = {"version": "99.0.0", "url": "u"}
    with pytest.raises(server.ApiError):
        hub.install_update()          # запуск из исходников


def test_find_running_fast_on_free_ports():
    import socket
    import time
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    t = time.monotonic()
    assert app.find_running(range(port, port + 1)) is None
    assert time.monotonic() - t < 0.5     # свободный порт — без сетевых запросов


def test_port_busy():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    try:
        assert app.port_busy(s.getsockname()[1])
    finally:
        s.close()


@pytest.mark.parametrize("partial", [
    {"poll_seconds": 0},
    {"poll_seconds": 1},
    {"ping": {"interval_seconds": 0}},
    {"deals": {"interval_hours": 0}},
    {"deals": {"interval_hours": 0.5}},
])
def test_check_partial_rejects_zero_intervals(partial):
    with pytest.raises(server.ApiError):
        app.check_partial(partial, config.DEFAULTS)


def test_check_partial_allows_min_intervals():
    app.check_partial({"poll_seconds": 2, "ping": {"interval_seconds": 1}, "deals": {"interval_hours": 1}},
                      config.DEFAULTS)


def test_loop_clamps_zero_interval():
    import threading
    import time
    hub = FakeHub([])
    hub.stop_event = threading.Event()
    calls = []
    hub._loop("t", lambda: 0, lambda: calls.append(1))
    time.sleep(0.3)
    hub.stop_event.set()
    assert len(calls) == 1      # ноль в настройках не крутит цикл без пауз


def test_instance_token_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    assert app.read_token() == ""
    app.write_instance(8790, "abc")
    assert app.read_token() == "abc"
    (tmp_path / app.INSTANCE_FILE).write_text("мусор", encoding="utf-8")
    assert app.read_token() == ""
