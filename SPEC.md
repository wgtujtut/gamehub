# GameHub — спецификация модулей

Локальная игровая панель для Windows 11. Python 3.14, venv `D:\VsCode\gamehub\.venv`.
Зависимости (уже стоят): psutil, pystray, pillow, pytest. Больше ничего не добавлять — только стандартная библиотека.

Работает в фоне (иконка в трее), веб-панель на `http://127.0.0.1:8790`.

## Структура

```
gamehub/
  app.py          — точка входа: потоки, трей, сервер (пишет архитектор)
  server.py       — HTTP API (пишет архитектор)
  config.py       — настройки
  library.py      — установленные игры (Steam, Epic, свои)
  db.py           — SQLite
  stats.py        — подсчёт статистики (чистые функции)
  tracker.py      — слежка за процессами, сессии
  deals.py        — бесплатные игры (Epic, GamerPower)
  notify.py       — уведомления Windows
  gamemode.py     — режим игры (план питания, закрытие программ)
  cleaner.py      — чистка кэшей
  net.py          — пинг-монитор
  web/            — index.html, app.js, style.css
  data/           — gamehub.db, config.json (создаются сами)
  tests/          — pytest, fixtures/ с реальными образцами
```

Все модули — плоские файлы в корне `gamehub/`, импорт вида `import library`. Тесты в `tests/`, в `tests/conftest.py` корень добавляется в `sys.path`.
Стиль: простой понятный код, функции, классы только там, где есть состояние. Комментарии и docstring — по-русски, коротко. Время везде — unix timestamp (float, секунды), в JSON — числа.
Игра идентифицируется строкой `game_id`: `steam:<appid>`, `epic:<AppName>`, `custom:<slug>`.

---

## config.py

```python
DATA_DIR: Path  # = %APPDATA%\GameHub (или GAMEHUB_DATA)
RES_DIR: Path   # папка с web/: sys._MEIPASS в собранном exe, иначе папка исходников
DEFAULTS: dict
def load(path: Path | None = None) -> dict      # DEFAULTS глубоко слитые с data/config.json; файла нет — DEFAULTS (копия)
def save(cfg: dict, path: Path | None = None) -> None  # атомарно: пишем .tmp, потом os.replace; ensure_ascii=False, indent=2
def deep_merge(base: dict, over: dict) -> dict  # новый dict; вложенные dict сливаются, остальное заменяется
```

DEFAULTS:
```python
{
  "port": 8790,
  "poll_seconds": 10,
  "min_session_seconds": 60,
  "stale_days": 60,
  "not_games": ["steam:228980", "steam:1905180", "steam:1325860", "steam:629520", "steam:431960", "steam:380870", "steam:3487310"],
  #   Steamworks Redist, OBS Studio, VTube Studio, Soundpad, Wallpaper Engine, PZ Dedicated Server, Bongo Cat (висит в фоне)
  "extra_games": [],   # [{"id": "custom:tarkov", "name": "...", "dir": "D:\\games\\EscapeFromTarkov", "launch": "C:\\...\\BsgLauncher.exe"}]
  "gamemode": {
    "auto": True,             # включать при старте игры
    "power_plan": True,       # переключать план питания на максимальный
    "kill_on_start": False,   # закрывать программы из kill_list при старте игры
    "kill_list": []
  },
  "deals": {"enabled": True, "interval_hours": 3, "notify": True},
  "ping": {
    "enabled": True,
    "interval_seconds": 5,
    "targets": [
      {"name": "Cloudflare", "host": "1.1.1.1", "port": 443},
      {"name": "Google", "host": "8.8.8.8", "port": 443},
      {"name": "Steam", "host": "api.steampowered.com", "port": 443}
    ]
  },
  "limits": {"daily_minutes": 0},     # 0 — выключено; иначе уведомление, когда за сутки наиграно больше
  "notify_session_end": True
}
```

---

## library.py

Игра — обычный dict (сразу пригоден для JSON):
```python
{
  "id": "steam:730", "name": "Counter-Strike 2", "source": "steam" | "epic" | "custom",
  "appid": "730" | None,                 # только для steam
  "install_dir": "F:\\SteamLibrary\\steamapps\\common\\Counter-Strike Global Offensive",
  "size_bytes": 74000000000,             # Steam: SizeOnDisk; Epic: InstallSize; custom: dir_size()
  "last_played": 1791055543.0,           # Steam: LastPlayed (0 → 0.0); остальные 0.0
  "launch": "steam://rungameid/730"      # Epic: com.epicgames.launcher://apps/{CatalogNamespace}%3A{CatalogItemId}%3A{AppName}?action=launch&silent=true
                                         # custom: путь к exe/лаунчеру из конфига (или "" если нет)
}
```

```python
def parse_vdf(text: str) -> dict
```
Текстовый формат Valve KeyValues: `"ключ" "значение"` и `"ключ" { ... }`. Строки в двойных кавычках, внутри бывают экранирования `\\` и `\"` (раскрыть). Комментарии `//` до конца строки игнорировать. Без кавычек токены тоже допускать (редко, но бывает). Ключи хранить как в файле. Повтор ключа — последний побеждает. Пример: tests/fixtures/appmanifest_1874880.acf, tests/fixtures/libraryfolders.vdf.

```python
def get_ci(d: dict, key: str, default=None)    # поиск ключа без учёта регистра
def steam_root() -> Path | None
```
Реестр `HKCU\Software\Valve\Steam`, значение `SteamPath` (там прямые слэши, `d:/steam`), через winreg. Нет — пробуем `C:\Program Files (x86)\Steam`. Нет папки — None.

```python
def steam_libraries(root: Path) -> list[Path]
```
Из `root/steamapps/libraryfolders.vdf` все `"path"` (формат: `libraryfolders` → `"0"`,`"1"`… → `path`). Корень Steam всегда в списке. Без дублей (сравнение через os.path.normcase(os.path.abspath)). Только существующие папки.

```python
def scan_steam(root: Path) -> list[dict]
```
Для каждой библиотеки — `steamapps/appmanifest_*.acf` (читать utf-8, errors="replace"). `AppState`: appid, name, installdir, SizeOnDisk, LastPlayed. install_dir = `<lib>/steamapps/common/<installdir>`. Битый файл — пропустить, не падать.

```python
def scan_epic(manifest_dir: Path = Path(r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests")) -> list[dict]
```
Файлы `*.item` (JSON): DisplayName, InstallLocation, AppName, CatalogNamespace, CatalogItemId, InstallSize. Пропускать, если `bIsIncompleteInstall` true или в `AppCategories` нет "games" (если AppCategories отсутствует — считаем игрой). Нет папки — пустой список.

```python
def detect_tarkov() -> dict | None
```
Реестр `HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\EscapeFromTarkov` → InstallLocation, DisplayName. Лаунчер: `C:\Battlestate Games\BsgLauncher\BsgLauncher.exe` если файл есть, иначе "". Возвращает элемент формата extra_games: `{"id": "custom:tarkov", "name": DisplayName or "Escape from Tarkov", "dir": ..., "launch": ...}`. Нет ключа/папки — None.

```python
def dir_size(path: Path) -> int
```
Рекурсивно через os.scandir, ссылки и junction (`entry.is_symlink()`, `os.path.isjunction`) не обходить и не считать. Ошибки доступа — пропускать.

```python
def custom_games(extra: list[dict], size_cache: dict | None = None) -> list[dict]
```
Из элементов extra_games — игры с source="custom". size_bytes = dir_size(dir) (если в size_cache есть значение по id — взять оттуда; size_cache пополняется). Папки нет — пропустить.

```python
def scan_all(cfg: dict, size_cache: dict | None = None) -> list[dict]
```
steam (если корень найден) + epic + custom из `cfg["extra_games"]` + detect_tarkov() (если такого id ещё нет в extra_games). Без дублей по id. Сортировка по name (casefold). Поле `"not_game": bool` = id в `cfg["not_games"]`.

```python
def find_cover(root: Path | None, appid: str, kind: str = "portrait") -> Path | None
```
Локальный кэш обложек Steam: `root/appcache/librarycache/<appid>/`. kind="portrait" → `library_600x900.jpg`; "header" → `header.jpg`; "hero" → `library_hero.jpg`. Сначала прямо в папке appid, потом в подпапках на один уровень глубже (новый формат Steam кладёт header.jpg в подпапку с хэшем). Ещё старый формат: `root/appcache/librarycache/<appid>_library_600x900.jpg`, `<appid>_header.jpg`, `<appid>_library_hero.jpg`. Нет — None.

```python
def cdn_cover(appid: str, kind: str = "portrait") -> str
```
`https://cdn.cloudflare.steamstatic.com/steam/apps/<appid>/library_600x900.jpg` | `header.jpg` | `library_hero.jpg`.

---

## db.py

SQLite, один объект на всё приложение, доступ из нескольких потоков: `sqlite3.connect(path, check_same_thread=False)` + `threading.Lock` на каждую операцию. Включить WAL.

```python
class DB:
    def __init__(self, path: Path | str)   # ":memory:" для тестов; создаёт таблицы
    # сессии
    def open_session(self, game_id: str, name: str, start: float) -> int
    def heartbeat(self, sid: int, now: float) -> None          # end = now (сессия ещё открыта)
    def close_session(self, sid: int, end: float, ping_avg: float | None = None, ping_loss: float | None = None) -> None   # open = 0
    def delete_session(self, sid: int) -> None
    def close_dangling(self) -> int     # все open=1 → open=0 (end уже последний heartbeat); вернуть количество
    def sessions(self, t0: float | None = None, t1: float | None = None) -> list[dict]
        # пересекающиеся с [t0, t1] (end >= t0 и start <= t1); без границ — все; сортировка по start
        # dict: id, game_id, name, start, end, open (bool), ping_avg, ping_loss
    def open_sessions(self) -> list[dict]
    def game_totals(self) -> dict[str, dict]   # game_id → {"seconds": float, "last": float (макс end), "sessions": int}
    # раздачи
    def deal_seen(self, key: str) -> bool
    def mark_deal_seen(self, key: str, now: float) -> None    # INSERT OR IGNORE
    def set_deal_claimed(self, key: str, claimed: bool) -> None   # если записи нет — создать
    def claimed_deals(self) -> set[str]
    # кэш размеров папок (для custom-игр, чтобы не считать 50 ГБ каждый запуск)
    def kv_get(self, key: str, default=None)      # таблица kv(key TEXT PK, value TEXT JSON)
    def kv_set(self, key: str, value) -> None
```
Таблицы:
```sql
sessions(id INTEGER PRIMARY KEY, game_id TEXT, name TEXT, start REAL, end REAL, open INTEGER, ping_avg REAL, ping_loss REAL)
deals(key TEXT PRIMARY KEY, first_seen REAL, claimed INTEGER DEFAULT 0)
kv(key TEXT PRIMARY KEY, value TEXT)
```
Индекс по sessions(start).

---

## stats.py — чистые функции, никакого ввода-вывода

Сессия — dict из db.sessions(). Дни — локальное время (`datetime.fromtimestamp(ts)`), ключ дня — строка `YYYY-MM-DD`. Для тестов во все функции, где нужно «сейчас», передаётся `now: float`.

```python
def split_by_day(sessions) -> dict[str, float]
```
Секунды по дням; сессия через полночь делится между днями.

```python
def split_by_day_game(sessions) -> dict[str, dict[str, float]]   # день → {game_id: сек}
def clip(sessions, t0, t1) -> list[dict]       # копии сессий, обрезанные по [t0, t1], пустые выкинуть
def per_game(sessions) -> list[dict]
```
`[{"game_id", "name", "seconds", "sessions", "last"}]` по убыванию seconds; name — из последней по времени сессии.

```python
def streak(day_totals: dict[str, float], today: date, min_seconds: float = 900) -> int
```
Подряд идущие дни (до сегодня включительно) с игрой ≥ min_seconds. Если сегодня ещё меньше порога — считать начиная со вчера (сегодня серию не обрывает).

```python
def best_streak(day_totals, min_seconds=900) -> int
def heatmap(day_totals, today: date, days: int = 371) -> list[dict]   # [{"date": "YYYY-MM-DD", "seconds": float}] от старого к новому, ровно days штук, включая today
def by_hour(sessions) -> list[float]       # 24 элемента, секунды по часу суток (сессию разрезать по границам часов)
def by_weekday(sessions) -> list[float]    # 7 элементов, пн=0
def summary(sessions, now: float) -> dict
```
summary → `{"today": сек, "week": сек за 7 дней (сегодня и 6 предыдущих), "month": сек за 30 дней, "total": сек,
"streak": int, "best_streak": int, "longest": {"game_id","name","seconds","start"} | None, "top_week": per_game за 7 дней (первые 5),
"avg_day_month": month / 30}`.
Открытые сессии учитываются по их текущему end.

```python
def fmt_duration(seconds: float) -> str     # "0 мин", "45 мин", "2 ч 05 мин", "130 ч 00 мин"
```

---

## tracker.py

```python
IGNORE_EXE: set[str]   # нижний регистр: crash handlers, анти-читы, лаунчеры, установщики:
# "unitycrashhandler64.exe", "unitycrashhandler32.exe", "crashreportclient.exe", "crashpad_handler.exe",
# "easyanticheat.exe", "easyanticheat_eos.exe", "easyanticheat_eos_setup.exe", "beservice.exe", "beservice_x64.exe",
# "battleye launcher.exe", "steam.exe", "steamwebhelper.exe", "steamservice.exe", "steamerrorreporter.exe", "steamerrorreporter64.exe",
# "epicgameslauncher.exe", "epicwebhelper.exe", "unrealcefsubprocess.exe", "vc_redist.x64.exe", "vc_redist.x86.exe",
# "dxsetup.exe", "unins000.exe", "cefprocess.exe", "crashsender.exe", "bugsplat.exe"

def norm(path: str) -> str      # os.path.normcase(os.path.normpath(path))
def match_game(exe_path: str, games: list[dict]) -> str | None
```
Игра, в чьей install_dir лежит exe (самое длинное совпадение; граница по разделителю: `D:\Games\Rust` не совпадает с `D:\Games\RustDedicated\x.exe`). Имя exe в IGNORE_EXE → None. Игры с `not_game: True` не считаются. Пустой install_dir не совпадает ни с чем.

```python
def list_processes() -> list[tuple[int, str, str]]   # (pid, name, exe) через psutil.process_iter(["pid","name","exe"]); exe None/ошибки доступа → пропустить
```

```python
class Tracker:
    def __init__(self, db, get_games, *, list_procs=list_processes, clock=time.time,
                 min_session=60, on_start=None, on_stop=None)
        # get_games() -> list[dict] — актуальный список игр
        # on_start(game: dict) ; on_stop(game: dict, session: dict) где session = {"id","game_id","name","start","end","seconds"}
        # при создании: db.close_dangling()
    def tick(self) -> None
        # 1) какие игры запущены сейчас (множество game_id)
        # 2) новые → db.open_session(..., now) и on_start
        # 3) пропавшие → закрыть: если длительность < min_session → db.delete_session, on_stop НЕ вызывать;
        #    иначе on_stop(game, session) ДО db.close_session, а close_session с ping_avg/ping_loss,
        #    которые on_stop может вернуть как dict {"ping_avg":..,"ping_loss":..} (или None)
        # 4) остальным открытым → db.heartbeat(sid, now)
    def running(self) -> list[dict]   # [{"game_id","name","start","elapsed"}]
    def stop_all(self) -> None        # закрыть все открытые (при выходе из программы), по тем же правилам
```
Ошибки в колбэках ловить и печатать в лог (logging), трекер не должен падать.

---

## deals.py

Раздача:
```python
{"key": "epic:<id>" | "gp:<id>", "title": str, "store": "Epic Games" | "Steam" | "GOG" | ...,
 "source": "epic" | "gamerpower", "url": str, "image": str | None,
 "start": float | None, "end": float | None, "worth": str | None, "description": str}
```
```python
EPIC_URL = "https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions?locale=ru&country=RU&allowCountries=RU"
GP_URL = "https://www.gamerpower.com/api/filter?platform=steam.epic-games-store.gog&type=game"

def parse_iso(s: str | None) -> float | None    # "2026-10-01T15:00:00.000Z" → ts; None/"" → None
def parse_epic(data: dict, now: float) -> dict  # {"now": [...], "upcoming": [...]}
```
Элементы `data["data"]["Catalog"]["searchStore"]["elements"]`.
- «Бесплатно сейчас»: в `promotions.promotionalOffers[*].promotionalOffers[*]` есть предложение с `discountSetting.discountPercentage == 0` и start <= now < end. Дополнительно у таких `price.totalPrice.discountPrice == 0`.
- «Скоро бесплатно»: в `promotions.upcomingPromotionalOffers[*].promotionalOffers[*]` предложение с discountPercentage == 0. start/end — из него.
- `promotions` может быть null — пропустить.
- url: `https://store.epicgames.com/ru/p/<slug>`, slug = первый `catalogNs.mappings[*].pageSlug` с pageType "productHome", иначе первый pageSlug, иначе productSlug (без "/home" на конце), иначе urlSlug. Нет никакого — `https://store.epicgames.com/ru/free-games`.
- image: `keyImages` по приоритету type: OfferImageWide, DieselStoreFrontWide, featuredMedia, Thumbnail, OfferImageTall, любой первый.
- worth: `price.totalPrice.fmtPrice.originalPrice` (может отсутствовать → None).
- key: `epic:<id>`.
Образец: tests/fixtures/epic.json (сохранён 2026-10-07; в нём сейчас бесплатны «System Shock 2: 25th Anniversary Remaster» и «BURIED STARS» до 2026-10-08T15:00Z, «Out of Sight» и «TerraScape» — скоро бесплатно с 2026-10-08T15:00Z).

```python
def parse_gamerpower(data: list, now: float) -> list[dict]
```
Образец: tests/fixtures/gamerpower.json. Поля: id, title, worth ("N/A" → None), image (или thumbnail), description, open_giveaway_url, platforms ("PC, Steam" / "PC, Epic Games Store" / "PC, GOG"…), end_date ("YYYY-MM-DD HH:MM:SS" UTC или "N/A" → None), published_date (→ start), status. Только status == "Active". store: если в platforms есть "Steam" → "Steam", "Epic" → "Epic Games", "GOG" → "GOG", иначе platforms как есть. Уже закончившиеся (end < now) выкинуть. title — убрать хвосты вида " Giveaway", " Steam Key Giveaway", " (Steam)", " (Epic Games)" — `clean_title()`.

```python
def clean_title(s: str) -> str
def norm_title(s: str) -> str      # casefold, только буквы/цифры и одиночные пробелы
def merge(epic: dict, gp: list) -> dict
```
`{"now": epic_now + gp (без тех gp, чей norm_title совпадает с norm_title любой epic-раздачи из now/upcoming), "upcoming": epic_upcoming}`. now сортировать по end (None — в конец).

```python
def fetch_json(url: str, timeout: float = 20)   # urllib.request с User-Agent "Mozilla/5.0 GameHub"; ошибки пробрасывает
def fetch_all(now: float, fetch=fetch_json) -> dict
```
→ `{"now": [...], "upcoming": [...], "errors": ["epic: <текст>", ...], "fetched_at": now}`. Ошибка одного источника не роняет другой.

```python
def pick_new(deals: dict, db) -> list[dict]
```
Раздачи из `deals["now"]`, которых нет в db (db.deal_seen), — пометить mark_deal_seen и вернуть. Upcoming не помечать.

---

## notify.py

```python
def set_sink(fn) -> None     # fn(title, body) — например, трей pystray Icon.notify
def toast(title: str, body: str) -> None
```
Если sink задан — через него. Иначе — PowerShell-уведомление: `powershell -NoProfile -NonInteractive -WindowStyle Hidden -Command <скрипт>`, где title/body передаются ТОЛЬКО через переменные окружения (GH_TITLE, GH_BODY), а в скрипте экранируются `[Security.SecurityElement]::Escape` перед вставкой в XML тоста (данные приходят из интернета — никакой подстановки в текст скрипта). AppId: `{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe`. Запуск без окна (`creationflags=subprocess.CREATE_NO_WINDOW`), не ждать завершения дольше 15 с, ошибки глотать (лог).

---

## gamemode.py

```python
ULTIMATE = "e9a42b02-d5df-448d-aa00-03f14749eb61"
HIGH = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"

def parse_schemes(text: str) -> list[dict]
```
Разбор вывода `powercfg /list` (русская или английская Windows), строки вида
`GUID схемы питания: 381b4222-f694-41f0-9685-ff5bb260df2e  (Сбалансированная)` / `Power Scheme GUID: ... (Balanced) *`.
→ `[{"guid", "name", "active": bool}]`. Регулярка по GUID + имя в скобках + `*` в конце.

```python
def run_powercfg(*args) -> str     # subprocess, CREATE_NO_WINDOW, вывод в cp866 (кодировка консоли) — декодировать "cp866", errors="replace"
def list_schemes() -> list[dict]
def active_scheme() -> dict | None
def set_scheme(guid: str) -> bool
def best_scheme(schemes) -> dict | None   # ULTIMATE если есть, иначе HIGH, иначе None
def kill_processes(names: list[str], *, iter_procs=None) -> list[str]
```
Закрыть процессы по имени (без учёта регистра, с ".exe" и без). Возвращает имена закрытых (без дублей). Защита: никогда не трогать системные и свои — `{"explorer", "csrss", "winlogon", "services", "lsass", "svchost", "system", "dwm", "smss", "wininit", "python", "pythonw"}`. `iter_procs` — для тестов (по умолчанию psutil.process_iter(["pid","name"])). terminate(), ошибки доступа глотать.

```python
class GameMode:
    def __init__(self, *, list_fn=list_schemes, set_fn=set_scheme, kill_fn=kill_processes)
    active: bool
    def enter(self, cfg_gm: dict) -> dict
        # если уже active — ничего; запомнить текущую схему; если cfg_gm["power_plan"] — best_scheme и set_fn (если она не текущая);
        # если cfg_gm["kill_on_start"] — kill_fn(cfg_gm["kill_list"]); вернуть {"scheme": имя или None, "killed": [...]}
    def exit(self) -> None     # вернуть запомненную схему, если меняли; active=False
    def kill_now(self, names) -> list[str]   # ручное закрытие
    def status(self) -> dict   # {"active", "scheme": имя активной схемы, "previous": имя запомненной или None}
```
Подсчёт игр (вкл. при первой, выкл. после последней) — снаружи, в app.py.

---

## cleaner.py

Цель (target): `{"id": str, "name": str, "paths": [str], "note": str, "default": bool, "min_age": int}` (min_age — не трогать файлы моложе стольких секунд; у temp — 86400, у остальных 0).

```python
def targets(steam_libs: list[Path], env: dict | None = None) -> list[dict]
```
env по умолчанию os.environ (TEMP, LOCALAPPDATA, APPDATA). Только существующие пути (glob раскрыть). Список:
- `temp` — Временные файлы: `%TEMP%`. default True
- `nvidia` — Кэш шейдеров NVIDIA: `%LOCALAPPDATA%\NVIDIA\DXCache`, `%LOCALAPPDATA%\NVIDIA\GLCache`, `%LOCALAPPDATA%\NVIDIA Corporation\NV_Cache`. note «пересоберётся, первые минуты в игре могут быть подлагивания». default False
- `d3d` — Кэш шейдеров DirectX: `%LOCALAPPDATA%\D3DSCache`. default False (та же note)
- `steam_shader` — Кэш шейдеров Steam: `<lib>\steamapps\shadercache` для всех библиотек. default False (та же note)
- `steam_web` — Кэш браузера Steam: `%LOCALAPPDATA%\Steam\htmlcache`. default True
- `discord` — Кэш Discord: `%APPDATA%\discord\Cache`, `%APPDATA%\discord\Code Cache`, `%APPDATA%\discord\GPUCache`. default True
- `chrome` — Кэш Chrome: `%LOCALAPPDATA%\Google\Chrome\User Data\*\Cache`, `...\*\Code Cache`. default True
- `firefox` — Кэш Firefox: `%LOCALAPPDATA%\Mozilla\Firefox\Profiles\*\cache2`. default True
- `crashdumps` — Дампы падений: `%LOCALAPPDATA%\CrashDumps`. default True
- `epic` — Кэш Epic Launcher: `%LOCALAPPDATA%\EpicGamesLauncher\Saved\webcache*`. default True
- `pip` — Кэш pip: `%LOCALAPPDATA%\pip\cache`. default False
Цель, у которой не осталось ни одного пути, не возвращать.

```python
def measure(paths: list[str], min_age=0, now=None) -> dict     # {"bytes": int, "files": int}; ссылки/junction не обходить и не считать
def clean(paths: list[str], min_age=0, now=None) -> dict       # {"freed": int, "deleted": int, "skipped": int}
```
clean удаляет СОДЕРЖИМОЕ каждой папки, саму папку оставляет. Ссылки и junction внутри — удалить саму ссылку (os.unlink / os.rmdir для junction), НО не заходить внутрь и не трогать то, на что она указывает. Занятые/запрещённые файлы — skipped, без исключений наружу. Папка из paths сама является ссылкой — пропустить целиком.

```python
def stale_games(games: list[dict], totals: dict, now: float, days: int) -> dict
```
games — из library (с not_game), totals — db.game_totals(). Последний запуск = max(game["last_played"], totals.get(id, {}).get("last", 0)). Давно не играл: last == 0 или now - last > days*86400; not_game пропустить. → `{"games": [{"id","name","size_bytes","last"}] по убыванию size, "bytes": сумма}`.

---

## net.py

```python
def tcp_ping(host: str, port: int = 443, timeout: float = 1.0) -> float | None   # мс до установки TCP-соединения, None при ошибке
def calc_stats(values: list[float | None]) -> dict
```
→ `{"last": последнее значение (может быть None), "avg": среднее по не-None или None, "min", "max", "jitter": среднее |разница| соседних не-None (None если < 2), "loss": доля None в процентах (0..100, округлить до 0.1), "count": len(values)}`. Пустой список → всё None, loss 0, count 0.

```python
class PingMonitor:
    def __init__(self, targets: list[dict], *, ping=tcp_ping, clock=time.time, maxlen=720)
    def sample(self) -> dict       # один замер всех целей параллельно (ThreadPoolExecutor), добавить в буфер (ts, {name: ms|None}), вернуть его
    def set_targets(self, targets) -> None
    def series(self, since: float | None = None) -> list[dict]   # [{"ts": .., "values": {name: ms}}]
    def stats(self, since: float | None = None) -> dict          # {name: calc_stats(...)}
    def overall(self, since: float) -> dict | None               # по первой цели: {"ping_avg", "ping_loss"} для записи в сессию; нет данных — None
    def run(self, stop_event: threading.Event, interval: float)  # цикл: sample, ждать interval (stop_event.wait)
```
Потокобезопасно (Lock на буфер).

---

## HTTP API (server.py) — формат ответов для фронтенда

Все ответы JSON. Все запросы к /api/* — с заголовком `X-GameHub: <ключ запуска>` (без него 403); POST — тело JSON. Ошибка → `{"error": "текст"}` с кодом 4xx/5xx.

`GET /api/state` — главная, опрашивается каждые 2 с:
```json
{
  "now": 1791100000.0,
  "playing": [{"game_id": "steam:730", "name": "Counter-Strike 2", "start": 1791090000.0, "elapsed": 10000.0}],
  "summary": {"today": 5400, "week": 30000, "month": 90000, "total": 500000, "streak": 4, "best_streak": 12,
              "avg_day_month": 3000, "longest": {"game_id": "...", "name": "...", "seconds": 18000, "start": 1790000000.0},
              "top_week": [{"game_id": "steam:730", "name": "Counter-Strike 2", "seconds": 20000, "sessions": 6, "last": 1791000000.0}]},
  "gamemode": {"active": false, "scheme": "Максимальная производительность", "previous": null, "auto": true},
  "disks": [{"name": "C:", "free": 35500000000, "total": 200000000000}],
  "ping": {"Cloudflare": {"last": 12.3, "avg": 13.1, "min": 10.2, "max": 40.0, "jitter": 1.4, "loss": 0.0, "count": 120}},
  "deals_now": 3,
  "limit": {"daily_minutes": 0, "today_minutes": 90}
}
```
`GET /api/library` → `{"games": [ {...игра из library, "seconds": float, "sessions": int, "last": float, "stale": bool} ], "stale": {"games": [...], "bytes": int}, "scanned_at": float}`
`POST /api/library/rescan` → как GET после пересканирования.
`POST /api/launch {"game_id"}` → `{"ok": true}`. Перед запуском включает режим игры, если включён `gamemode.kill_on_start`/`power_plan` — нет, просто запуск; режим включит трекер.
`POST /api/open_folder {"game_id"}` → `{"ok": true}`
`POST /api/library/not_game {"game_id", "value": bool}` → `{"ok": true}`
`GET /cover/<game_id>?kind=portrait|header|hero` → картинка (локальный кэш Steam) или 302 на CDN; не Steam → 404.
`GET /api/stats?days=30` →
```json
{"days": [{"date": "2026-10-07", "seconds": 5400, "games": {"steam:730": 5400}}],
 "names": {"steam:730": "Counter-Strike 2"},
 "per_game": [{"game_id", "name", "seconds", "sessions", "last"}],
 "heatmap": [{"date": "2025-10-01", "seconds": 0}],
 "by_hour": [24 числа], "by_weekday": [7 чисел],
 "sessions": [{"id", "game_id", "name", "start", "end", "open", "ping_avg", "ping_loss"}],
 "summary": {...как в state}}
```
(days — ровно N последних дней от старого к новому, per_game — за эти N дней, sessions — последние 50 по убыванию start, heatmap — 371 день).
`GET /api/deals` → `{"now": [раздача + "claimed": bool], "upcoming": [...], "errors": [], "fetched_at": float | null}`
`POST /api/deals/refresh` → как GET. `POST /api/deals/claim {"key", "claimed": bool}` → `{"ok": true}`
`GET /api/cleaner` → `{"targets": [{"id","name","paths","note","default","bytes","files"}], "stale": {"games": [...], "bytes": int}}`
`POST /api/cleaner/clean {"ids": [...]}` → `{"results": [{"id","name","freed","deleted","skipped"}], "freed": int}`
`POST /api/gamemode {"action": "on" | "off" | "kill"}` → `{"gamemode": {...как в state}, "killed": [...]}`
`GET /api/ping?minutes=30` → `{"series": [{"ts", "values": {"Cloudflare": 12.3}}], "stats": {...}, "targets": [{"name","host","port"}]}`
`GET /api/config` → конфиг целиком. `POST /api/config {...частичный}` → глубокое слияние, сохранить, вернуть конфиг целиком.
`POST /api/open_url {"url"}` → открыть в браузере по умолчанию (только http/https).
`POST /api/uninstall {"game_id"}` → `steam://uninstall/<appid>` (только Steam-игры).
`POST /api/window/show` → показать окно (второй запуск ярлыка).
`GET /api/update` → `{"current": "1.0.0", "update": {"version","url","notes","page"} | null, "installed": bool}`.
`POST /api/update/install` → скачать установщик последнего релиза, запустить тихую установку, закрыть программу (только установленная версия).
В `/api/state` ещё есть `"version"` и `"update"`.
