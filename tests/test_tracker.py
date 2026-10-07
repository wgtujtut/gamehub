import pytest

from db import DB
from tracker import Tracker, match_game

RUST_EXE = "D:\\Games\\Rust\\RustClient.exe"
DEDI_EXE = "D:\\Games\\RustDedicated\\RustDedicated.exe"

GAMES = [
    {"id": "steam:252490", "name": "Rust", "install_dir": "D:\\Games\\Rust"},
    {"id": "steam:258550", "name": "Rust Dedicated", "install_dir": "D:\\Games\\RustDedicated"},
    {"id": "steam:228980", "name": "Steamworks Redist", "install_dir": "D:\\Games\\Redist", "not_game": True},
    {"id": "custom:empty", "name": "Пусто", "install_dir": ""},
]


def test_match_game_folder_boundary():
    assert match_game(RUST_EXE, GAMES) == "steam:252490"
    assert match_game(DEDI_EXE, GAMES) == "steam:258550"
    assert match_game("D:\\Games\\Rust\\Bin\\sub\\x.exe", GAMES) == "steam:252490"
    assert match_game("D:\\Games\\RustX.exe", GAMES) is None


def test_match_game_case_insensitive():
    assert match_game("d:\\games\\rust\\rustclient.EXE", GAMES) == "steam:252490"
    assert match_game("D:/GAMES/RUST/RustClient.exe", GAMES) == "steam:252490"


def test_match_game_longest_wins():
    games = GAMES + [{"id": "custom:sub", "name": "Sub", "install_dir": "D:\\Games\\Rust\\Sub"}]
    assert match_game("D:\\Games\\Rust\\Sub\\game.exe", games) == "custom:sub"
    assert match_game(RUST_EXE, games) == "steam:252490"


def test_match_game_ignore_exe():
    assert match_game("D:\\Games\\Rust\\UnityCrashHandler64.exe", GAMES) is None
    assert match_game("D:\\Games\\Rust\\EasyAntiCheat\\EasyAntiCheat.exe", GAMES) is None


def test_match_game_not_game_and_empty_dir():
    assert match_game("D:\\Games\\Redist\\setup.exe", GAMES) is None
    assert match_game("C:\\Windows\\notepad.exe", GAMES) is None
    assert match_game("C:\\x.exe", [{"id": "custom:empty", "name": "Пусто", "install_dir": ""}]) is None


class Env:
    """Фейковые процессы, часы и колбэки для Tracker."""

    def __init__(self, db=None, min_session=60, on_start=None, on_stop=None):
        self.db = db or DB(":memory:")
        self.now = 1000.0
        self.procs = []
        self.started = []
        self.stopped = []
        self.stop_result = None
        self.tracker = Tracker(
            self.db, lambda: GAMES,
            list_procs=lambda: list(self.procs),
            clock=lambda: self.now,
            min_session=min_session,
            on_start=on_start or self.started.append,
            on_stop=on_stop or self._on_stop,
        )

    def _on_stop(self, game, session):
        self.stopped.append((game, session))
        return self.stop_result


def test_start_opens_session():
    env = Env()
    env.procs = [(1, "RustClient.exe", RUST_EXE), (2, "notepad.exe", "C:\\Windows\\notepad.exe")]
    env.tracker.tick()
    s = env.db.open_sessions()
    assert len(s) == 1
    assert s[0]["game_id"] == "steam:252490" and s[0]["name"] == "Rust" and s[0]["start"] == 1000.0
    assert [g["id"] for g in env.started] == ["steam:252490"]
    assert env.tracker.running() == [{"game_id": "steam:252490", "name": "Rust", "start": 1000.0, "elapsed": 0.0}]


def test_repeat_tick_heartbeat():
    env = Env()
    env.procs = [(1, "RustClient.exe", RUST_EXE)]
    env.tracker.tick()
    env.now = 1010.0
    env.tracker.tick()
    s = env.db.open_sessions()
    assert len(s) == 1 and s[0]["end"] == 1010.0
    assert len(env.started) == 1  # on_start только один раз
    assert env.tracker.running()[0]["elapsed"] == 10.0


def test_short_session_deleted():
    env = Env(min_session=60)
    env.procs = [(1, "RustClient.exe", RUST_EXE)]
    env.tracker.tick()
    env.now = 1030.0
    env.procs = []
    env.tracker.tick()
    assert env.db.sessions() == []
    assert env.stopped == []
    assert env.tracker.running() == []


def test_long_session_closed_with_ping():
    env = Env(min_session=60)
    env.stop_result = {"ping_avg": 25.0, "ping_loss": 1.5}
    env.procs = [(1, "RustClient.exe", RUST_EXE)]
    env.tracker.tick()
    env.now = 1120.0
    env.procs = []
    env.tracker.tick()

    assert len(env.stopped) == 1
    game, session = env.stopped[0]
    assert game["id"] == "steam:252490"
    assert session["game_id"] == "steam:252490" and session["name"] == "Rust"
    assert session["start"] == 1000.0 and session["end"] == 1120.0
    assert session["seconds"] == pytest.approx(120)

    rows = env.db.sessions()
    assert len(rows) == 1
    assert rows[0]["id"] == session["id"]
    assert rows[0]["open"] is False and rows[0]["end"] == 1120.0
    assert rows[0]["ping_avg"] == 25.0 and rows[0]["ping_loss"] == 1.5


def test_on_stop_returns_none():
    env = Env()
    env.procs = [(1, "RustClient.exe", RUST_EXE)]
    env.tracker.tick()
    env.now = 1200.0
    env.procs = []
    env.tracker.tick()
    row = env.db.sessions()[0]
    assert row["open"] is False and row["ping_avg"] is None


def test_two_games_at_once():
    env = Env()
    env.procs = [(1, "RustClient.exe", RUST_EXE), (2, "RustDedicated.exe", DEDI_EXE)]
    env.tracker.tick()
    assert {s["game_id"] for s in env.db.open_sessions()} == {"steam:252490", "steam:258550"}

    env.now = 1100.0
    env.procs = [(2, "RustDedicated.exe", DEDI_EXE)]
    env.tracker.tick()
    assert [s["game_id"] for s in env.db.open_sessions()] == ["steam:258550"]
    assert env.db.open_sessions()[0]["end"] == 1100.0
    assert [g["id"] for g, _ in env.stopped] == ["steam:252490"]


def test_same_game_two_processes_one_session():
    env = Env()
    env.procs = [(1, "RustClient.exe", RUST_EXE), (3, "helper.exe", "D:\\Games\\Rust\\helper.exe")]
    env.tracker.tick()
    assert len(env.db.open_sessions()) == 1


def test_on_start_error_does_not_break_tick():
    def boom(game):
        raise RuntimeError("сломался колбэк")

    env = Env(on_start=boom)
    env.procs = [(1, "RustClient.exe", RUST_EXE)]
    env.tracker.tick()
    assert len(env.db.open_sessions()) == 1
    env.now = 1010.0
    env.tracker.tick()
    assert env.db.open_sessions()[0]["end"] == 1010.0


def test_on_stop_error_still_closes():
    def boom(game, session):
        raise RuntimeError("сломался колбэк")

    env = Env(on_stop=boom)
    env.procs = [(1, "RustClient.exe", RUST_EXE)]
    env.tracker.tick()
    env.now = 1200.0
    env.procs = []
    env.tracker.tick()
    row = env.db.sessions()[0]
    assert row["open"] is False and row["end"] == 1200.0


def test_stop_all():
    env = Env(min_session=60)
    env.procs = [(1, "RustClient.exe", RUST_EXE)]
    env.tracker.tick()
    env.now = 1020.0
    env.procs = [(1, "RustClient.exe", RUST_EXE), (2, "RustDedicated.exe", DEDI_EXE)]
    env.tracker.tick()
    env.now = 1100.0  # Rust 100 с — закрыть, Dedicated 80 с — тоже
    env.tracker.stop_all()
    assert env.db.open_sessions() == []
    assert len(env.db.sessions()) == 2
    assert {g["id"] for g, _ in env.stopped} == {"steam:252490", "steam:258550"}
    assert env.tracker.running() == []


def test_stop_all_short_deleted():
    env = Env(min_session=60)
    env.procs = [(1, "RustClient.exe", RUST_EXE)]
    env.tracker.tick()
    env.now = 1010.0
    env.tracker.stop_all()
    assert env.db.sessions() == []
    assert env.stopped == []


def test_dangling_closed_on_create():
    db = DB(":memory:")
    sid = db.open_session("steam:252490", "Rust", 100.0)
    db.heartbeat(sid, 500.0)
    Env(db=db)
    assert db.open_sessions() == []
    assert db.sessions()[0]["end"] == 500.0
