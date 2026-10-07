"""Пинг-монитор: TCP-пинг до нескольких целей и статистика."""
import logging
import socket
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)


def tcp_ping(host, port=443, timeout=1.0):
    """Мс до установки TCP-соединения; ошибка — None. DNS в замер не входит."""
    try:
        family, type_, proto, _, addr = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0]
        with socket.socket(family, type_, proto) as s:
            s.settimeout(timeout)
            t0 = time.perf_counter()
            s.connect(addr)
            return (time.perf_counter() - t0) * 1000
    except OSError:
        return None


def calc_stats(values):
    """Статистика по замерам (None — потеря)."""
    ok = [v for v in values if v is not None]
    n = len(values)
    jitter = None
    if len(ok) >= 2:
        # соседи среди успешных замеров, потери пропускаем
        jitter = sum(abs(b - a) for a, b in zip(ok, ok[1:])) / (len(ok) - 1)
    return {
        "last": values[-1] if values else None,
        "avg": sum(ok) / len(ok) if ok else None,
        "min": min(ok) if ok else None,
        "max": max(ok) if ok else None,
        "jitter": jitter,
        "loss": round((n - len(ok)) / n * 100, 1) if n else 0.0,
        "count": n,
    }


class PingMonitor:
    def __init__(self, targets, *, ping=tcp_ping, clock=time.time, maxlen=720):
        self._targets = list(targets)
        self._ping = ping
        self._clock = clock
        self._buf = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def sample(self):
        """Один замер всех целей параллельно; добавить в буфер и вернуть."""
        with self._lock:
            targets = list(self._targets)
        ts = self._clock()
        results = []
        if targets:
            with ThreadPoolExecutor(max_workers=len(targets)) as ex:
                results = list(ex.map(lambda t: self._ping(t["host"], t.get("port", 443)), targets))
        item = {"ts": ts, "values": {t["name"]: r for t, r in zip(targets, results)}}
        with self._lock:
            self._buf.append(item)
        return {"ts": ts, "values": dict(item["values"])}

    def set_targets(self, targets):
        with self._lock:
            self._targets = list(targets)

    def series(self, since=None):
        with self._lock:
            return [{"ts": it["ts"], "values": dict(it["values"])}
                    for it in self._buf if since is None or it["ts"] >= since]

    def _values(self, name, items):
        # только замеры, где эта цель была в списке
        return [it["values"][name] for it in items if name in it["values"]]

    def stats(self, since=None):
        """Статистика по текущим целям."""
        items = self.series(since)
        with self._lock:
            names = [t["name"] for t in self._targets]
        return {name: calc_stats(self._values(name, items)) for name in names}

    def overall(self, since):
        """По первой цели: {"ping_avg", "ping_loss"} для сессии; нет данных — None."""
        with self._lock:
            if not self._targets:
                return None
            name = self._targets[0]["name"]
        values = self._values(name, self.series(since))
        if not values:
            return None
        s = calc_stats(values)
        return {"ping_avg": s["avg"], "ping_loss": s["loss"]}

    def run(self, stop_event, interval):
        """Цикл замеров до stop_event."""
        while not stop_event.is_set():
            try:
                self.sample()
            except Exception:
                log.exception("ошибка замера пинга")
            stop_event.wait(interval)
