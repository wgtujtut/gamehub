import pytest

from db import DB


@pytest.fixture
def db():
    return DB(":memory:")


def test_open_heartbeat_close(db):
    sid = db.open_session("steam:730", "CS2", 100.0)
    s = db.open_sessions()
    assert len(s) == 1
    assert s[0]["id"] == sid and s[0]["open"] is True
    assert s[0]["start"] == 100.0 and s[0]["end"] == 100.0

    db.heartbeat(sid, 150.0)
    assert db.open_sessions()[0]["end"] == 150.0

    db.close_session(sid, 200.0, ping_avg=25.5, ping_loss=1.0)
    assert db.open_sessions() == []
    s = db.sessions()[0]
    assert s == {"id": sid, "game_id": "steam:730", "name": "CS2", "start": 100.0, "end": 200.0,
                 "open": False, "ping_avg": 25.5, "ping_loss": 1.0}


def test_close_without_ping(db):
    sid = db.open_session("a", "A", 1.0)
    db.close_session(sid, 2.0)
    s = db.sessions()[0]
    assert s["ping_avg"] is None and s["ping_loss"] is None


def test_close_dangling(db):
    a = db.open_session("a", "A", 100.0)
    db.heartbeat(a, 180.0)
    b = db.open_session("b", "B", 200.0)
    db.close_session(b, 300.0)
    db.open_session("c", "C", 400.0)

    assert db.close_dangling() == 2
    assert db.open_sessions() == []
    s = {x["game_id"]: x for x in db.sessions()}
    assert s["a"]["end"] == 180.0  # end — последний heartbeat
    assert db.close_dangling() == 0


def test_sessions_range(db):
    for gid, start, end in [("a", 100, 200), ("b", 300, 400), ("c", 500, 600)]:
        sid = db.open_session(gid, gid.upper(), start)
        db.close_session(sid, end)

    ids = lambda rows: [r["game_id"] for r in rows]
    assert ids(db.sessions()) == ["a", "b", "c"]
    assert ids(db.sessions(150, 350)) == ["a", "b"]
    assert ids(db.sessions(200, 300)) == ["a", "b"]  # границы включительно
    assert ids(db.sessions(210, 290)) == []
    assert ids(db.sessions(450)) == ["c"]
    assert ids(db.sessions(None, 250)) == ["a"]


def test_sessions_sorted_by_start(db):
    for gid, start in [("late", 500), ("early", 100)]:
        sid = db.open_session(gid, gid, start)
        db.close_session(sid, start + 10)
    assert [r["game_id"] for r in db.sessions()] == ["early", "late"]


def test_delete(db):
    sid = db.open_session("a", "A", 1.0)
    db.delete_session(sid)
    assert db.sessions() == []


def test_game_totals(db):
    for gid, start, end in [("a", 100, 200), ("a", 300, 400), ("b", 500, 560)]:
        sid = db.open_session(gid, gid, start)
        db.close_session(sid, end)
    t = db.game_totals()
    assert t["a"] == {"seconds": 200.0, "last": 400.0, "sessions": 2}
    assert t["b"] == {"seconds": 60.0, "last": 560.0, "sessions": 1}
    assert DB(":memory:").game_totals() == {}


def test_deals(db):
    assert db.deal_seen("epic:1") is False
    db.mark_deal_seen("epic:1", 100.0)
    db.mark_deal_seen("epic:1", 200.0)  # повтор не ломает
    assert db.deal_seen("epic:1") is True
    assert db.claimed_deals() == set()

    db.set_deal_claimed("epic:1", True)
    db.set_deal_claimed("gp:2", True)  # записи не было — создаётся
    assert db.claimed_deals() == {"epic:1", "gp:2"}
    assert db.deal_seen("gp:2") is True

    db.set_deal_claimed("epic:1", False)
    assert db.claimed_deals() == {"gp:2"}


def test_kv(db):
    assert db.kv_get("sizes") is None
    assert db.kv_get("sizes", {}) == {}
    db.kv_set("sizes", {"custom:tarkov": 50_000_000_000, "имя": "Тарков"})
    assert db.kv_get("sizes") == {"custom:tarkov": 50_000_000_000, "имя": "Тарков"}
    db.kv_set("sizes", {"x": 1})
    assert db.kv_get("sizes") == {"x": 1}


def test_wal_synchronous_normal(tmp_path):
    # NORMAL в режиме WAL: без fsync на каждый heartbeat, база при сбое не портится
    from db import DB
    d = DB(tmp_path / "x.db")
    assert d._read("PRAGMA synchronous")[0][0] == 1
