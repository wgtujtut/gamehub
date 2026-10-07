import socket

import pytest

import net


# --- calc_stats ---

def test_calc_stats_empty():
    assert net.calc_stats([]) == {"last": None, "avg": None, "min": None, "max": None,
                                  "jitter": None, "loss": 0, "count": 0}


def test_calc_stats_all_none():
    res = net.calc_stats([None, None])
    assert res == {"last": None, "avg": None, "min": None, "max": None,
                   "jitter": None, "loss": 100.0, "count": 2}


def test_calc_stats_mixed():
    res = net.calc_stats([10.0, None, 20.0, 15.0, None])
    assert res["last"] is None
    assert res["avg"] == pytest.approx(15.0)
    assert res["min"] == 10.0
    assert res["max"] == 20.0
    # соседи среди не-None: |20-10| и |15-20| → (10 + 5) / 2
    assert res["jitter"] == pytest.approx(7.5)
    assert res["loss"] == 40.0
    assert res["count"] == 5


def test_calc_stats_one_value():
    res = net.calc_stats([12.5])
    assert res["last"] == 12.5
    assert res["avg"] == 12.5
    assert res["jitter"] is None
    assert res["loss"] == 0


def test_calc_stats_loss_rounding():
    assert net.calc_stats([1.0, None, None])["loss"] == 66.7


# --- PingMonitor ---

class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


TARGETS = [{"name": "A", "host": "a.test", "port": 443},
           {"name": "B", "host": "b.test", "port": 80}]


def make_monitor(maxlen=720):
    clock = Clock()
    answers = {"a.test": 10.0, "b.test": None}
    calls = []

    def ping(host, port):
        calls.append((host, port))
        return answers[host]

    mon = net.PingMonitor(TARGETS, ping=ping, clock=clock, maxlen=maxlen)
    return mon, clock, answers, calls


def test_sample():
    mon, clock, answers, calls = make_monitor()
    res = mon.sample()
    assert res == {"ts": 100.0, "values": {"A": 10.0, "B": None}}
    assert sorted(calls) == [("a.test", 443), ("b.test", 80)]


def test_series_and_stats():
    mon, clock, answers, _ = make_monitor()
    mon.sample()                      # ts 100: A=10, B=None
    clock.t = 200.0
    answers.update({"a.test": 20.0, "b.test": 30.0})
    mon.sample()                      # ts 200: A=20, B=30

    assert mon.series() == [
        {"ts": 100.0, "values": {"A": 10.0, "B": None}},
        {"ts": 200.0, "values": {"A": 20.0, "B": 30.0}},
    ]
    assert mon.series(since=150) == [{"ts": 200.0, "values": {"A": 20.0, "B": 30.0}}]

    st = mon.stats()
    assert st["A"]["avg"] == pytest.approx(15.0)
    assert st["A"]["jitter"] == pytest.approx(10.0)
    assert st["B"]["loss"] == 50.0
    assert st["B"]["count"] == 2
    assert mon.stats(since=150)["B"]["loss"] == 0


def test_overall():
    mon, clock, answers, _ = make_monitor()
    assert mon.overall(0) is None     # данных нет
    mon.sample()
    clock.t = 200.0
    answers["a.test"] = None
    mon.sample()

    assert mon.overall(0) == {"ping_avg": 10.0, "ping_loss": 50.0}
    assert mon.overall(150) == {"ping_avg": None, "ping_loss": 100.0}
    assert mon.overall(1000) is None


def test_maxlen():
    mon, clock, _, _ = make_monitor(maxlen=3)
    for i in range(5):
        clock.t = float(i)
        mon.sample()
    assert [s["ts"] for s in mon.series()] == [2.0, 3.0, 4.0]


def test_set_targets():
    mon, _, answers, _ = make_monitor()
    mon.set_targets([{"name": "C", "host": "a.test", "port": 443}])
    assert mon.sample()["values"] == {"C": 10.0}
    assert set(mon.stats()) == {"C"}


def test_series_returns_copies():
    mon, _, _, _ = make_monitor()
    mon.sample()
    mon.series()[0]["values"]["A"] = 999
    assert mon.series()[0]["values"]["A"] == 10.0


# --- tcp_ping ---

def test_tcp_ping_open_port():
    srv = socket.socket()
    try:
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        port = srv.getsockname()[1]
        ms = net.tcp_ping("127.0.0.1", port, timeout=2.0)
        assert isinstance(ms, float)
        assert ms >= 0
    finally:
        srv.close()


def test_tcp_ping_closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # порт освобождён, никто не слушает
    assert net.tcp_ping("127.0.0.1", port, timeout=0.5) is None
