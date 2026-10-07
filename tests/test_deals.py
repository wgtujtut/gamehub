import json
from datetime import datetime, timezone

import pytest

import deals
from conftest import FIXTURES


def ts(*args) -> float:
    """UTC-дата -> timestamp."""
    return datetime(*args, tzinfo=timezone.utc).timestamp()


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def wrap(elements):
    """Обернуть элементы в структуру ответа Epic."""
    return {"data": {"Catalog": {"searchStore": {"elements": elements}}}}


FREE_PROMO = {
    "promotionalOffers": [{"promotionalOffers": [{
        "startDate": "2026-10-01T15:00:00.000Z", "endDate": "2026-10-08T15:00:00.000Z",
        "discountSetting": {"discountType": "PERCENTAGE", "discountPercentage": 0}}]}],
    "upcomingPromotionalOffers": [],
}


# ---------- parse_iso ----------

def test_parse_iso():
    assert deals.parse_iso("2026-10-01T15:00:00.000Z") == ts(2026, 10, 1, 15)
    assert deals.parse_iso("2026-10-09 23:59:00") == ts(2026, 10, 9, 23, 59)
    assert deals.parse_iso(None) is None
    assert deals.parse_iso("") is None
    assert deals.parse_iso("N/A") is None


# ---------- Epic ----------

def test_parse_epic_now():
    res = deals.parse_epic(load("epic.json"), ts(2026, 10, 5))
    by_title = {d["title"]: d for d in res["now"]}
    assert set(by_title) == {"System Shock 2: 25th Anniversary Remaster", "BURIED STARS"}
    assert len(res["now"]) == 2

    ss = by_title["System Shock 2: 25th Anniversary Remaster"]
    assert ss["key"] == "epic:7ae00c3e89174012b175cc73b4737723"
    assert ss["url"] == "https://store.epicgames.com/ru/p/system-shock-2-25th-anniversary-remaster-cb94d9"
    assert ss["image"] == ("https://cdn1.epicgames.com/spt-assets/690ff600d5134d9ab12c96862ed5257a/"
                           "system-shock-2-25th-anniversary-remaster-1e28j.jpg")
    assert ss["start"] == ts(2026, 10, 1, 15)
    assert ss["end"] == ts(2026, 10, 8, 15)
    assert ss["worth"] == "899,00\xa0₽"  # Epic ставит неразрывный пробел
    assert ss["store"] == "Epic Games"
    assert ss["source"] == "epic"

    bs = by_title["BURIED STARS"]
    assert bs["url"] == "https://store.epicgames.com/ru/p/buried-stars-d7c88c"
    assert bs["image"] is not None
    assert bs["end"] == ts(2026, 10, 8, 15)


def test_parse_epic_upcoming():
    res = deals.parse_epic(load("epic.json"), ts(2026, 10, 5))
    titles = {d["title"] for d in res["upcoming"]}
    assert "Out of Sight" in titles
    assert "TerraScape" in titles
    assert "Ghostrunner 2" not in titles   # скидка 20%, не бесплатно
    assert "Monument Valley" not in titles  # скидка 35%
    oos = next(d for d in res["upcoming"] if d["title"] == "Out of Sight")
    assert oos["start"] == ts(2026, 10, 8, 15)
    assert oos["end"] == ts(2026, 10, 15, 15)
    assert oos["url"] == "https://store.epicgames.com/ru/p/out-of-sight-b96ca8"


def test_parse_epic_after_end():
    data = load("epic.json")
    assert deals.parse_epic(data, ts(2026, 10, 8, 15))["now"] == []
    assert deals.parse_epic(data, ts(2026, 10, 9))["now"] == []


def test_parse_epic_null_promotions_and_minimal():
    # promotions = null — пропустить; элемент без картинок/слагов/цены — не падать
    data = wrap([
        {"title": "Null", "id": "n1", "promotions": None},
        {"title": "Bare", "id": "b1", "promotions": FREE_PROMO},
    ])
    res = deals.parse_epic(data, ts(2026, 10, 5))
    assert [d["title"] for d in res["now"]] == ["Bare"]
    bare = res["now"][0]
    assert bare["url"] == "https://store.epicgames.com/ru/free-games"
    assert bare["image"] is None
    assert bare["worth"] is None
    assert res["upcoming"] == []


def test_parse_epic_slug_fallbacks():
    data = wrap([
        {"title": "A", "id": "a", "promotions": FREE_PROMO, "productSlug": "game-a/home", "urlSlug": "x"},
        {"title": "B", "id": "b", "promotions": FREE_PROMO, "catalogNs": {"mappings": []}, "urlSlug": "game-b"},
        {"title": "C", "id": "c", "promotions": FREE_PROMO,
         "catalogNs": {"mappings": [{"pageSlug": "other", "pageType": "offer"},
                                    {"pageSlug": "home-c", "pageType": "productHome"}]}},
    ])
    urls = {d["title"]: d["url"] for d in deals.parse_epic(data, ts(2026, 10, 5))["now"]}
    assert urls["A"] == "https://store.epicgames.com/ru/p/game-a"
    assert urls["B"] == "https://store.epicgames.com/ru/p/game-b"
    assert urls["C"] == "https://store.epicgames.com/ru/p/home-c"


def test_parse_epic_image_priority():
    data = wrap([{"title": "A", "id": "a", "promotions": FREE_PROMO, "keyImages": [
        {"type": "OfferImageTall", "url": "tall"},
        {"type": "Thumbnail", "url": "thumb"},
        {"type": "DieselStoreFrontWide", "url": "diesel"},
    ]}])
    assert deals.parse_epic(data, ts(2026, 10, 5))["now"][0]["image"] == "diesel"


# ---------- GamerPower ----------

def test_parse_gamerpower_fixture():
    data = load("gamerpower.json")
    res = deals.parse_gamerpower(data, ts(2026, 10, 7, 12))
    by_title = {d["title"]: d for d in res}
    assert set(by_title) == {"Spooky Cats", "BURIED STARS",
                             "System Shock 2: 25th Anniversary Remaster", "Dwarven Realms"}
    assert by_title["Spooky Cats"]["store"] == "Steam"
    assert by_title["Spooky Cats"]["key"] == "gp:3804"
    assert by_title["Spooky Cats"]["end"] == ts(2026, 10, 9, 23, 59)
    assert by_title["Spooky Cats"]["worth"] == "$2.99"
    assert by_title["Spooky Cats"]["source"] == "gamerpower"
    assert by_title["BURIED STARS"]["store"] == "Epic Games"
    assert by_title["Dwarven Realms"]["end"] is None  # end_date "N/A"
    assert by_title["Dwarven Realms"]["start"] == ts(2026, 7, 16, 13, 15, 6)

    # 9 октября: эпиковские раздачи GamerPower уже закончились
    later = deals.parse_gamerpower(data, ts(2026, 10, 9))
    assert {d["title"] for d in later} == {"Spooky Cats", "Dwarven Realms"}


def gp_item(**kw):
    item = {"id": 1, "title": "Game Giveaway", "worth": "$5.00", "image": "img", "thumbnail": "th",
            "description": "d", "open_giveaway_url": "https://example.com/open", "platforms": "PC, Steam",
            "end_date": "2026-10-10 00:00:00", "published_date": "2026-10-01 00:00:00", "status": "Active"}
    item.update(kw)
    return item


def test_parse_gamerpower_synthetic():
    now = ts(2026, 10, 5)
    data = [
        gp_item(id=1, worth="N/A", end_date="N/A", image=None),
        gp_item(id=2, end_date="2026-10-01 00:00:00"),          # уже закончилась
        gp_item(id=3, status="Expired"),                        # не Active
        gp_item(id=4, platforms="PC, Epic Games Store"),
        gp_item(id=5, platforms="PC, GOG"),
        gp_item(id=6, platforms="PC, Itch.io"),
    ]
    res = {d["key"]: d for d in deals.parse_gamerpower(data, now)}
    assert set(res) == {"gp:1", "gp:4", "gp:5", "gp:6"}
    assert res["gp:1"]["worth"] is None
    assert res["gp:1"]["end"] is None
    assert res["gp:1"]["image"] == "th"
    assert res["gp:1"]["store"] == "Steam"
    assert res["gp:1"]["title"] == "Game"
    assert res["gp:1"]["url"] == "https://example.com/open"
    assert res["gp:4"]["store"] == "Epic Games"
    assert res["gp:5"]["store"] == "GOG"
    assert res["gp:6"]["store"] == "PC, Itch.io"


def test_parse_gamerpower_not_list():
    # без раздач GamerPower отдаёт объект
    assert deals.parse_gamerpower({"status": 0, "status_message": "No active giveaways"}, 0) == []


# ---------- названия ----------

def test_clean_title():
    assert deals.clean_title("Spooky Cats Steam Key Giveaway") == "Spooky Cats"
    assert deals.clean_title("BURIED STARS (Epic Games) Giveaway") == "BURIED STARS"
    assert deals.clean_title("Dwarven Realms (Steam) Key Giveaway") == "Dwarven Realms"
    assert deals.clean_title("Some Game Giveaway") == "Some Game"
    assert deals.clean_title("Some Game (Steam)") == "Some Game"
    assert deals.clean_title("Some Game (GOG) Giveaway") == "Some Game"
    assert deals.clean_title("Plain Title") == "Plain Title"


def test_norm_title():
    assert deals.norm_title("System Shock 2: 25th  Anniversary Remaster") == "system shock 2 25th anniversary remaster"
    assert deals.norm_title("  BURIED   STARS ") == "buried stars"
    assert deals.norm_title("Ёлка — Тест_Игра!") == "ёлка тест игра"
    assert deals.norm_title("") == ""


# ---------- merge ----------

def test_merge_fixtures():
    epic = deals.parse_epic(load("epic.json"), ts(2026, 10, 5))
    gp = deals.parse_gamerpower(load("gamerpower.json"), ts(2026, 10, 7, 12))
    res = deals.merge(epic, gp)
    titles = [d["title"] for d in res["now"]]
    # дубли из GamerPower (BURIED STARS, System Shock 2) убраны
    assert len(titles) == 4
    assert sorted(titles[:2]) == ["BURIED STARS", "System Shock 2: 25th Anniversary Remaster"]
    assert all(d["source"] == "epic" for d in res["now"][:2])
    assert titles[2:] == ["Spooky Cats", "Dwarven Realms"]  # Dwarven без end — в конце
    assert res["upcoming"] == epic["upcoming"]


def test_merge_dedup_with_upcoming_and_sort():
    epic = {"now": [{"title": "A", "end": 300.0}],
            "upcoming": [{"title": "Soon: Game"}]}
    gp = [{"title": "soon game", "end": 100.0},   # дубль upcoming
          {"title": "B", "end": None},
          {"title": "C", "end": 200.0}]
    res = deals.merge(epic, gp)
    assert [d["title"] for d in res["now"]] == ["C", "A", "B"]
    assert res["upcoming"] == [{"title": "Soon: Game"}]


# ---------- fetch_all ----------

def test_fetch_all_epic_fails():
    gp_data = load("gamerpower.json")

    def fake(url):
        if url == deals.EPIC_URL:
            raise OSError("boom")
        assert url == deals.GP_URL
        return gp_data

    now = ts(2026, 10, 7, 12)
    res = deals.fetch_all(now, fetch=fake)
    assert res["errors"] == ["epic: boom"]
    assert len(res["now"]) == 4
    assert res["upcoming"] == []
    assert res["fetched_at"] == now


def test_fetch_all_gp_fails():
    epic_data = load("epic.json")

    def fake(url):
        if url == deals.GP_URL:
            raise ValueError("bad json")
        return epic_data

    res = deals.fetch_all(ts(2026, 10, 5), fetch=fake)
    assert res["errors"] == ["gamerpower: bad json"]
    assert {d["title"] for d in res["now"]} == {"System Shock 2: 25th Anniversary Remaster", "BURIED STARS"}
    assert len(res["upcoming"]) == 2


# ---------- pick_new ----------

class FakeDB:
    def __init__(self):
        self.seen = set()

    def deal_seen(self, key):
        return key in self.seen

    def mark_deal_seen(self, key, now):
        self.seen.add(key)


def test_pick_new():
    db = FakeDB()
    data = {"now": [{"key": "epic:a"}, {"key": "gp:b"}], "upcoming": [{"key": "epic:c"}], "fetched_at": 100.0}
    assert [d["key"] for d in deals.pick_new(data, db)] == ["epic:a", "gp:b"]
    assert deals.pick_new(data, db) == []
    assert "epic:c" not in db.seen


def test_fetch_json_rejects_huge_response(monkeypatch):
    import io

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(deals, "MAX_RESPONSE", 10)
    monkeypatch.setattr(deals.urllib.request, "urlopen", lambda req, timeout: Resp(b'{"a": "0123456789"}'))
    with pytest.raises(ValueError):
        deals.fetch_json("https://example.com")
    monkeypatch.setattr(deals.urllib.request, "urlopen", lambda req, timeout: Resp(b'{"a": 1}'))
    assert deals.fetch_json("https://example.com") == {"a": 1}
