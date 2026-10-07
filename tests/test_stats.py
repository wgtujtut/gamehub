from datetime import date, datetime

import pytest

import stats


def ts(*args) -> float:
    """Локальное время → timestamp (тесты не зависят от часового пояса)."""
    return datetime(*args).timestamp()


def sess(gid, start, end, name=None, open_=False):
    return {"game_id": gid, "name": name or gid.upper(), "start": start, "end": end, "open": open_}


def test_split_by_day_midnight():
    s = [sess("a", ts(2026, 10, 5, 23, 0), ts(2026, 10, 6, 1, 30))]
    d = stats.split_by_day(s)
    assert d == {"2026-10-05": pytest.approx(3600), "2026-10-06": pytest.approx(5400)}


def test_split_by_day_sums():
    s = [sess("a", ts(2026, 10, 5, 10, 0), ts(2026, 10, 5, 11, 0)),
         sess("b", ts(2026, 10, 5, 12, 0), ts(2026, 10, 5, 12, 30))]
    assert stats.split_by_day(s) == {"2026-10-05": pytest.approx(5400)}
    assert stats.split_by_day([]) == {}


def test_split_by_day_game():
    s = [sess("a", ts(2026, 10, 5, 23, 0), ts(2026, 10, 6, 1, 30)),
         sess("b", ts(2026, 10, 6, 10, 0), ts(2026, 10, 6, 10, 20))]
    d = stats.split_by_day_game(s)
    assert d == {"2026-10-05": {"a": pytest.approx(3600)},
                 "2026-10-06": {"a": pytest.approx(5400), "b": pytest.approx(1200)}}


def test_clip():
    s = [sess("a", 100.0, 200.0), sess("b", 400.0, 500.0), sess("c", 250.0, 260.0)]
    out = stats.clip(s, 150.0, 300.0)
    assert [(x["game_id"], x["start"], x["end"]) for x in out] == [("a", 150.0, 200.0), ("c", 250.0, 260.0)]
    assert out[0]["name"] == "A"
    assert s[0]["start"] == 100.0  # оригинал не тронут


def test_per_game():
    s = [sess("a", 500.0, 600.0, name="New"),
         sess("b", 100.0, 400.0),
         sess("a", 100.0, 150.0, name="Old")]
    out = stats.per_game(s)
    assert [g["game_id"] for g in out] == ["b", "a"]
    assert out[1] == {"game_id": "a", "name": "New", "seconds": 150.0, "sessions": 2, "last": 600.0}
    assert out[0]["seconds"] == 300.0 and out[0]["sessions"] == 1
    assert stats.per_game([]) == []


TODAY = date(2026, 10, 7)


def test_streak_basic():
    t = {"2026-10-05": 1000, "2026-10-06": 1000, "2026-10-07": 1000}
    assert stats.streak(t, TODAY) == 3


def test_streak_today_not_played_yet():
    t = {"2026-10-05": 1000, "2026-10-06": 1000}
    assert stats.streak(t, TODAY) == 2
    t["2026-10-07"] = 100  # сегодня меньше порога — серию не обрывает
    assert stats.streak(t, TODAY) == 2


def test_streak_gap_breaks():
    t = {"2026-10-04": 1000, "2026-10-06": 1000, "2026-10-07": 1000}
    assert stats.streak(t, TODAY) == 2
    assert stats.streak({"2026-10-05": 1000}, TODAY) == 0


def test_streak_below_threshold():
    t = {"2026-10-05": 1000, "2026-10-06": 500, "2026-10-07": 1000}
    assert stats.streak(t, TODAY) == 1
    assert stats.streak(t, TODAY, min_seconds=400) == 3


def test_best_streak():
    t = {"2026-10-01": 1000, "2026-10-02": 1000, "2026-10-03": 1000,
         "2026-10-05": 1000, "2026-10-06": 1000,
         "2026-09-20": 1000, "2026-09-21": 100, "2026-09-22": 1000}
    assert stats.best_streak(t) == 3
    assert stats.best_streak(t, min_seconds=50) == 3
    assert stats.best_streak({}) == 0


def test_heatmap():
    t = {"2026-10-07": 500.0, "2026-09-28": 100.0, "2026-09-27": 999.0}
    h = stats.heatmap(t, TODAY, days=10)
    assert len(h) == 10
    assert h[-1] == {"date": "2026-10-07", "seconds": 500.0}
    assert h[0] == {"date": "2026-09-28", "seconds": 100.0}
    assert h[1]["seconds"] == 0
    full = stats.heatmap(t, TODAY)
    assert len(full) == 371
    assert full[-1]["date"] == "2026-10-07"
    assert full[0]["date"] == "2025-10-02"


def test_by_hour():
    h = stats.by_hour([sess("a", ts(2026, 10, 5, 10, 30), ts(2026, 10, 5, 12, 15))])
    assert len(h) == 24
    assert h[10] == pytest.approx(1800)
    assert h[11] == pytest.approx(3600)
    assert h[12] == pytest.approx(900)
    assert sum(h) == pytest.approx(6300)


def test_by_weekday():
    s = [sess("a", ts(2026, 10, 5, 23, 0), ts(2026, 10, 6, 1, 30))]
    w = stats.by_weekday(s)
    mon = date(2026, 10, 5).weekday()
    assert len(w) == 7
    assert w[mon] == pytest.approx(3600)
    assert w[(mon + 1) % 7] == pytest.approx(5400)
    assert sum(w) == pytest.approx(9000)


def test_summary():
    now = ts(2026, 10, 7, 20, 0)
    s = [
        sess("a", ts(2026, 10, 7, 10, 0), ts(2026, 10, 7, 11, 0)),            # сегодня, 3600
        sess("b", ts(2026, 10, 7, 19, 0), now, open_=True),                  # открытая, 3600
        sess("a", ts(2026, 10, 3, 10, 0), ts(2026, 10, 3, 12, 0)),            # неделя, 7200
        sess("c", ts(2026, 9, 20, 10, 0), ts(2026, 9, 20, 10, 30)),           # месяц, 1800
        sess("c", ts(2026, 8, 1, 10, 0), ts(2026, 8, 1, 11, 0)),              # только total, 3600
    ]
    r = stats.summary(s, now)
    assert r["today"] == pytest.approx(7200)
    assert r["week"] == pytest.approx(14400)
    assert r["month"] == pytest.approx(16200)
    assert r["total"] == pytest.approx(19800)
    assert r["avg_day_month"] == pytest.approx(540)
    assert r["streak"] == 1
    assert r["best_streak"] == 1
    assert r["longest"]["game_id"] == "a"
    assert r["longest"]["seconds"] == pytest.approx(7200)
    assert r["longest"]["start"] == ts(2026, 10, 3, 10, 0)
    assert [g["game_id"] for g in r["top_week"]] == ["a", "b"]
    assert r["top_week"][0]["seconds"] == pytest.approx(10800)
    assert r["top_week"][0]["sessions"] == 2


def test_summary_empty():
    r = stats.summary([], ts(2026, 10, 7, 20, 0))
    assert r["today"] == 0 and r["total"] == 0 and r["streak"] == 0
    assert r["longest"] is None and r["top_week"] == []


def test_fmt_duration():
    assert stats.fmt_duration(0) == "0 мин"
    assert stats.fmt_duration(59) == "0 мин"
    assert stats.fmt_duration(2700) == "45 мин"
    assert stats.fmt_duration(7500) == "2 ч 05 мин"
    assert stats.fmt_duration(130 * 3600) == "130 ч 00 мин"
