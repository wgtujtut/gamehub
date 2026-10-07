"""Бесплатные игры: Epic Games Store и GamerPower."""
import json
import re
import time
import urllib.request
from datetime import datetime, timezone

EPIC_URL = "https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions?locale=ru&country=RU&allowCountries=RU"
GP_URL = "https://www.gamerpower.com/api/filter?platform=steam.epic-games-store.gog&type=game"

EPIC_FREE_PAGE = "https://store.epicgames.com/ru/free-games"
EPIC_IMAGE_TYPES = ["OfferImageWide", "DieselStoreFrontWide", "featuredMedia", "Thumbnail", "OfferImageTall"]

# хвосты в названиях GamerPower: " Steam Key Giveaway", " (Steam) Key Giveaway", " (Epic Games) Giveaway"...
_GIVEAWAY_TAIL = re.compile(r"(?:\s*\((?:steam|epic games|gog)\))?(?:\s+steam)?(?:\s+key)?\s+giveaway\s*$", re.I)
_STORE_TAIL = re.compile(r"\s*\((?:steam|epic games|gog)\)\s*$", re.I)


def parse_iso(s: str | None) -> float | None:
    """ISO-дата ("2026-10-01T15:00:00.000Z" или "2026-10-09 23:59:00") -> timestamp. Без зоны — UTC. Мусор -> None."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


# ---------- Epic ----------

def _epic_offers(promos: dict, key: str) -> list[dict]:
    """Все предложения из promotions[key][*].promotionalOffers[*]."""
    offers = []
    for group in promos.get(key) or []:
        offers.extend((group or {}).get("promotionalOffers") or [])
    return offers


def _is_free_offer(offer: dict) -> bool:
    return ((offer or {}).get("discountSetting") or {}).get("discountPercentage") == 0


def _epic_slug(el: dict) -> str | None:
    mappings = (el.get("catalogNs") or {}).get("mappings") or []
    for m in mappings:
        if m.get("pageType") == "productHome" and m.get("pageSlug"):
            return m["pageSlug"]
    for m in mappings:
        if m.get("pageSlug"):
            return m["pageSlug"]
    product = (el.get("productSlug") or "").removesuffix("/home")
    if product:
        return product
    return el.get("urlSlug") or None


def _epic_image(el: dict) -> str | None:
    images = [i for i in el.get("keyImages") or [] if i.get("url")]
    for kind in EPIC_IMAGE_TYPES:
        for i in images:
            if i.get("type") == kind:
                return i["url"]
    return images[0]["url"] if images else None


def _epic_deal(el: dict, offer: dict) -> dict:
    slug = _epic_slug(el)
    price = (el.get("price") or {}).get("totalPrice") or {}
    return {
        "key": f"epic:{el.get('id')}",
        "title": el.get("title") or "",
        "store": "Epic Games",
        "source": "epic",
        "url": f"https://store.epicgames.com/ru/p/{slug}" if slug else EPIC_FREE_PAGE,
        "image": _epic_image(el),
        "start": parse_iso(offer.get("startDate")),
        "end": parse_iso(offer.get("endDate")),
        "worth": (price.get("fmtPrice") or {}).get("originalPrice"),
        "description": el.get("description") or "",
    }


def parse_epic(data: dict, now: float) -> dict:
    """Ответ freeGamesPromotions -> {"now": [...], "upcoming": [...]}."""
    elements = data["data"]["Catalog"]["searchStore"]["elements"] or []
    free_now, upcoming = [], []
    for el in elements:
        promos = el.get("promotions")
        if not promos:
            continue
        # бесплатно сейчас: скидка 0% и now внутри [start, end); цена со скидкой (если есть) тоже 0
        discount_price = ((el.get("price") or {}).get("totalPrice") or {}).get("discountPrice")
        if discount_price in (None, 0):
            for offer in _epic_offers(promos, "promotionalOffers"):
                start = parse_iso(offer.get("startDate"))
                end = parse_iso(offer.get("endDate"))
                if _is_free_offer(offer) and start is not None and end is not None and start <= now < end:
                    free_now.append(_epic_deal(el, offer))
                    break
        # скоро бесплатно: скидка 0% в будущих предложениях
        for offer in _epic_offers(promos, "upcomingPromotionalOffers"):
            if _is_free_offer(offer):
                upcoming.append(_epic_deal(el, offer))
                break
    return {"now": free_now, "upcoming": upcoming}


# ---------- GamerPower ----------

def _gp_store(platforms: str) -> str:
    if "Steam" in platforms:
        return "Steam"
    if "Epic" in platforms:
        return "Epic Games"
    if "GOG" in platforms:
        return "GOG"
    return platforms


def parse_gamerpower(data: list, now: float) -> list[dict]:
    """Ответ GamerPower -> раздачи (только Active и ещё не закончившиеся)."""
    if not isinstance(data, list):
        return []  # без раздач GamerPower отдаёт объект со статусом, а не список
    deals = []
    for g in data:
        if not isinstance(g, dict) or g.get("status") != "Active":
            continue
        end = parse_iso(g.get("end_date"))  # "N/A" -> None
        if end is not None and end < now:
            continue
        worth = g.get("worth")
        deals.append({
            "key": f"gp:{g.get('id')}",
            "title": clean_title(g.get("title") or ""),
            "store": _gp_store(g.get("platforms") or ""),
            "source": "gamerpower",
            "url": g.get("open_giveaway_url") or "",
            "image": g.get("image") or g.get("thumbnail") or None,
            "start": parse_iso(g.get("published_date")),
            "end": end,
            "worth": None if worth in (None, "", "N/A") else worth,
            "description": g.get("description") or "",
        })
    return deals


# ---------- общее ----------

def clean_title(s: str) -> str:
    """Убрать хвосты вида " Giveaway", " Steam Key Giveaway", " (Steam)", " (Epic Games)"."""
    s = (s or "").strip()
    t = _GIVEAWAY_TAIL.sub("", s)
    t = _STORE_TAIL.sub("", t).strip()
    return t or s


def norm_title(s: str) -> str:
    """Для сравнения названий: casefold, только буквы/цифры и одиночные пробелы."""
    s = re.sub(r"[\W_]+", " ", (s or "").casefold())
    return " ".join(s.split())


def merge(epic: dict, gp: list) -> dict:
    """Epic + GamerPower без дублей по названию; now — по end, None в конце."""
    epic_titles = {norm_title(d["title"]) for d in epic["now"] + epic["upcoming"]}
    now = epic["now"] + [d for d in gp if norm_title(d["title"]) not in epic_titles]
    now.sort(key=lambda d: (d.get("end") is None, d.get("end") or 0))
    return {"now": now, "upcoming": list(epic["upcoming"])}


MAX_RESPONSE = 10_000_000   # ответ Epic ~40 КБ; больше 10 МБ — что-то не то


def fetch_json(url: str, timeout: float = 20):
    """GET и разбор JSON. Ошибки пробрасывает."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 GameHub"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(MAX_RESPONSE + 1)
    if len(data) > MAX_RESPONSE:
        raise ValueError("слишком большой ответ")
    return json.loads(data)


def fetch_all(now: float, fetch=fetch_json) -> dict:
    """Скачать и разобрать оба источника; ошибка одного не мешает другому."""
    errors = []
    epic = {"now": [], "upcoming": []}
    gp = []
    try:
        epic = parse_epic(fetch(EPIC_URL), now)
    except Exception as e:
        errors.append(f"epic: {e}")
    try:
        gp = parse_gamerpower(fetch(GP_URL), now)
    except Exception as e:
        errors.append(f"gamerpower: {e}")
    result = merge(epic, gp)
    result["errors"] = errors
    result["fetched_at"] = now
    return result


def pick_new(deals: dict, db) -> list[dict]:
    """Новые раздачи из deals["now"]: пометить в db как увиденные и вернуть. Upcoming не трогаем."""
    seen_at = deals.get("fetched_at") or time.time()
    new = []
    for d in deals.get("now", []):
        if not db.deal_seen(d["key"]):
            db.mark_deal_seen(d["key"], seen_at)
            new.append(d)
    return new
