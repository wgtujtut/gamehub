"""Подсчёт статистики по сессиям. Чистые функции, без ввода-вывода.

Дни — по локальному времени, ключ дня — "YYYY-MM-DD".
"""
from datetime import date, datetime, timedelta


def _next_day(dt: datetime) -> datetime:
    """Начало следующих суток (локальное время)."""
    return datetime(dt.year, dt.month, dt.day) + timedelta(days=1)


def _next_hour(dt: datetime) -> datetime:
    """Начало следующего часа."""
    return dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def _cut(start: float, end: float, next_border):
    """Режет [start, end] по границам; отдаёт (локальное время начала куска, секунды)."""
    t = start
    while t < end:
        dt = datetime.fromtimestamp(t)
        nxt = min(next_border(dt).timestamp(), end)
        if nxt <= t:  # защита от зацикливания на переводе часов
            nxt = end
        yield dt, nxt - t
        t = nxt


def _day_start(d: date) -> float:
    """Начало дня d (локальное время) как timestamp."""
    return datetime(d.year, d.month, d.day).timestamp()


def split_by_day(sessions) -> dict[str, float]:
    """Секунды по дням; сессия через полночь делится между днями."""
    out = {}
    for s in sessions:
        for dt, sec in _cut(s["start"], s["end"], _next_day):
            key = dt.date().isoformat()
            out[key] = out.get(key, 0.0) + sec
    return out


def split_by_day_game(sessions) -> dict[str, dict[str, float]]:
    """День → {game_id: секунды}."""
    out = {}
    for s in sessions:
        for dt, sec in _cut(s["start"], s["end"], _next_day):
            day = out.setdefault(dt.date().isoformat(), {})
            day[s["game_id"]] = day.get(s["game_id"], 0.0) + sec
    return out


def clip(sessions, t0, t1) -> list[dict]:
    """Копии сессий, обрезанные по [t0, t1]; пустые выкидываются."""
    out = []
    for s in sessions:
        start, end = max(s["start"], t0), min(s["end"], t1)
        if end > start:
            out.append({**s, "start": start, "end": end})
    return out


def per_game(sessions) -> list[dict]:
    """Итоги по играм, по убыванию секунд; name — из последней по времени сессии."""
    games = {}
    for s in sorted(sessions, key=lambda x: x["start"]):
        g = games.setdefault(s["game_id"], {"game_id": s["game_id"], "name": s["name"],
                                            "seconds": 0.0, "sessions": 0, "last": 0.0})
        g["name"] = s["name"]
        g["seconds"] += s["end"] - s["start"]
        g["sessions"] += 1
        g["last"] = max(g["last"], s["end"])
    return sorted(games.values(), key=lambda g: g["seconds"], reverse=True)


def streak(day_totals: dict[str, float], today: date, min_seconds: float = 900) -> int:
    """Серия дней подряд с игрой >= min_seconds. Сегодня ещё мало — считаем со вчера."""
    d = today
    if day_totals.get(d.isoformat(), 0) < min_seconds:
        d -= timedelta(days=1)
    n = 0
    while day_totals.get(d.isoformat(), 0) >= min_seconds:
        n += 1
        d -= timedelta(days=1)
    return n


def best_streak(day_totals, min_seconds=900) -> int:
    """Самая длинная серия за всё время."""
    days = sorted(date.fromisoformat(k) for k, v in day_totals.items() if v >= min_seconds)
    best = cur = 0
    prev = None
    for d in days:
        cur = cur + 1 if prev is not None and d - prev == timedelta(days=1) else 1
        best = max(best, cur)
        prev = d
    return best


def heatmap(day_totals, today: date, days: int = 371) -> list[dict]:
    """Ровно days дней от старого к новому, последний — today."""
    out = []
    for i in range(days - 1, -1, -1):
        key = (today - timedelta(days=i)).isoformat()
        out.append({"date": key, "seconds": day_totals.get(key, 0.0)})
    return out


def by_hour(sessions) -> list[float]:
    """24 элемента: секунды по часу суток."""
    out = [0.0] * 24
    for s in sessions:
        for dt, sec in _cut(s["start"], s["end"], _next_hour):
            out[dt.hour] += sec
    return out


def by_weekday(sessions) -> list[float]:
    """7 элементов: секунды по дню недели, пн=0."""
    out = [0.0] * 7
    for s in sessions:
        for dt, sec in _cut(s["start"], s["end"], _next_day):
            out[dt.weekday()] += sec
    return out


def summary(sessions, now: float) -> dict:
    """Сводка для главной. Открытые сессии считаются по их текущему end."""
    today = datetime.fromtimestamp(now).date()
    totals = split_by_day(sessions)

    def last_days(n):
        return sum(totals.get((today - timedelta(days=i)).isoformat(), 0.0) for i in range(n))

    month = last_days(30)
    longest = None
    if sessions:
        s = max(sessions, key=lambda x: x["end"] - x["start"])
        longest = {"game_id": s["game_id"], "name": s["name"],
                   "seconds": s["end"] - s["start"], "start": s["start"]}
    week_start = _day_start(today - timedelta(days=6))
    return {
        "today": totals.get(today.isoformat(), 0.0),
        "week": last_days(7),
        "month": month,
        "total": sum(s["end"] - s["start"] for s in sessions),
        "streak": streak(totals, today),
        "best_streak": best_streak(totals),
        "longest": longest,
        "top_week": per_game(clip(sessions, week_start, now))[:5],
        "avg_day_month": month / 30,
    }


def fmt_duration(seconds: float) -> str:
    """"0 мин", "45 мин", "2 ч 05 мин". Минуты округляются вниз."""
    minutes = max(0, int(seconds // 60))
    h, m = divmod(minutes, 60)
    if h == 0:
        return f"{m} мин"
    return f"{h} ч {m:02d} мин"
