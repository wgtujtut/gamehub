"""Проверка обновлений через GitHub Releases и установка новой версии."""
import json
import logging
import os
import re
import subprocess
import tempfile
import urllib.request

VERSION = "1.0.3"
REPO = "wgtujtut/gamehub"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
# скачиваем установщик только из релизов своего репозитория
ASSET_PREFIX = f"https://github.com/{REPO}/releases/download/"
SETUP_RE = re.compile(r"^GameHub-Setup-[\d.]+\.exe$")
# отпечаток сертификата, которым build.py подписывает установщик. Ключ лежит только у автора
# (хранилище сертификатов Windows), поэтому даже с угнанным GitHub подделку автообновление не поставит
SIGNER_THUMBPRINT = "BCC96AC630CE584CF27431B13871848550356399"
MAX_JSON = 1_000_000          # ответ API релизов
MAX_SETUP = 300_000_000       # установщик (сейчас ~17 МБ)

log = logging.getLogger("gamehub.updater")

# путь к файлу — только через переменную окружения, не в тексте команды
_SIG_PS = ("$s = Get-AuthenticodeSignature -LiteralPath $env:GH_FILE; "
           "[pscustomobject]@{status=[string]$s.Status; thumb=[string]$s.SignerCertificate.Thumbprint} "
           "| ConvertTo-Json -Compress")


class SignatureError(Exception):
    """Подпись установщика не наша — ставить нельзя."""


def _read_signature(path: str) -> str:
    res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _SIG_PS],
                         env={**os.environ, "GH_FILE": path}, capture_output=True, text=True,
                         timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
    return res.stdout


def signature_ok(path: str, read=_read_signature) -> bool:
    """Файл подписан нашим сертификатом и не изменён после подписи.
    Сертификат самодельный, поэтому Windows отвечает UnknownError (корень не доверен) —
    это нормально; испорченный файл дал бы HashMismatch, неподписанный — NotSigned."""
    try:
        data = json.loads(read(path))
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    return (data.get("status") in ("Valid", "UnknownError")
            and str(data.get("thumb") or "").upper() == SIGNER_THUMBPRINT)


def parse_version(s: str) -> tuple[int, ...]:
    """"v1.2.10" → (1, 2, 10); мусор → ()."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (s or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def is_newer(latest: str, current: str = VERSION) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return bool(a) and a > b


def parse_release(data: dict) -> dict | None:
    """Ответ releases/latest → {"version", "url", "notes", "page"}; нет установщика — None."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    version = (data.get("tag_name") or "").lstrip("v")
    if not parse_version(version):
        return None
    for asset in data.get("assets") or []:
        url = asset.get("browser_download_url") or ""
        if SETUP_RE.match(asset.get("name") or "") and url.startswith(ASSET_PREFIX):
            return {"version": version, "url": url, "notes": (data.get("body") or "")[:2000],
                    "page": data.get("html_url") or f"https://github.com/{REPO}/releases"}
    return None


def fetch_latest(timeout: float = 15) -> dict | None:
    req = urllib.request.Request(API_URL, headers={"User-Agent": f"GameHub/{VERSION}",
                                                   "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return parse_release(json.loads(resp.read(MAX_JSON + 1)[:MAX_JSON]))


def download_and_run(url: str) -> None:
    """Скачать установщик во временную папку и запустить тихую установку.
    Установщик сам закроет GameHub, обновит файлы и запустит новую версию."""
    if not url.startswith(ASSET_PREFIX):
        raise ValueError("чужая ссылка на установщик")
    name = url.rsplit("/", 1)[-1]
    if not SETUP_RE.match(name):
        raise ValueError("неожиданное имя файла")
    # своя новая папка: заранее подложенный файл с тем же именем не подменит установщик
    path = os.path.join(tempfile.mkdtemp(prefix="gamehub-update-"), name)
    req = urllib.request.Request(url, headers={"User-Agent": f"GameHub/{VERSION}"})
    size = 0
    with urllib.request.urlopen(req, timeout=120) as resp, open(path, "wb") as f:
        while chunk := resp.read(1 << 16):
            size += len(chunk)
            if size > MAX_SETUP:
                raise ValueError("установщик подозрительно большой")
            f.write(chunk)
    if not signature_ok(path):
        os.remove(path)
        raise SignatureError("подпись установщика не совпала")
    log.info("обновление скачано и подпись проверена: %s", path)
    subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                     creationflags=subprocess.DETACHED_PROCESS)
