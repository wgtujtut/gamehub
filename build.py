"""Сборка GameHub: exe (PyInstaller) и установщик (Inno Setup).
Запуск: .venv\\Scripts\\python.exe build.py  →  dist\\GameHub-Setup-<версия>.exe
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
ISCC_CANDIDATES = [
    os.environ.get("ISCC", ""),
    r"D:\Programs\InnoSetup6\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"),
]


# подпись через PowerShell: путь и отпечаток — через переменные окружения
SIGN_PS = (
    r"$c = Get-Item -LiteralPath ('Cert:\CurrentUser\My\' + $env:GH_THUMB) -ErrorAction Stop; "
    "$s = $null; "
    "try { $s = Set-AuthenticodeSignature -LiteralPath $env:GH_FILE -Certificate $c -HashAlgorithm SHA256 "
    "-TimestampServer 'http://timestamp.digicert.com' -ErrorAction Stop } catch { } "
    "if (-not $s -or -not $s.SignerCertificate) { "
    "$s = Set-AuthenticodeSignature -LiteralPath $env:GH_FILE -Certificate $c -HashAlgorithm SHA256 } "
    "[string]$s.Status"
)


def sign(path: Path, thumbprint: str) -> None:
    """Подписать exe сертификатом автора (без метки времени, если сервер времени недоступен)."""
    res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", SIGN_PS],
                         env={**os.environ, "GH_FILE": str(path), "GH_THUMB": thumbprint},
                         capture_output=True, text=True)
    status = res.stdout.strip()
    if status not in ("Valid", "UnknownError"):
        sys.exit(f"Не удалось подписать {path.name}: {status or res.stderr.strip()}\n"
                 f"Нужен сертификат {thumbprint} в хранилище «Личное» текущего пользователя.")
    print(f"подписан: {path.name}")


def run(cmd):
    print(">", " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True, cwd=ROOT)


def main() -> None:
    sys.path.insert(0, str(ROOT))
    from app import make_icon_image
    import updater
    from updater import SIGNER_THUMBPRINT, VERSION

    iscc = next((p for p in ISCC_CANDIDATES if p and Path(p).is_file()), None)
    if not iscc:
        sys.exit("Не найден Inno Setup (ISCC.exe). Поставь его или укажи путь в переменной ISCC")

    shutil.rmtree(DIST / "GameHub", ignore_errors=True)
    BUILD.mkdir(exist_ok=True)
    icon = BUILD / "gamehub.ico"
    make_icon_image(256).save(icon, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
         "--name", "GameHub", "--icon", icon,
         "--add-data", f"{ROOT / 'web'};web",
         "--hidden-import", "pystray._win32",   # pystray выбирает бэкенд динамически
         "--distpath", DIST, "--workpath", BUILD / "pyi", "--specpath", BUILD,
         ROOT / "app.py"])
    sign(DIST / "GameHub" / "GameHub.exe", SIGNER_THUMBPRINT)
    # сразу после подписи антивирус проверяет exe, и Inno Setup падает со странным «Out of memory» — повторяем
    for attempt in range(3):
        time.sleep(5)
        try:
            run([iscc, f"/DAppVersion={VERSION}", "/Q", ROOT / "installer.iss"])
            break
        except subprocess.CalledProcessError:
            if attempt == 2:
                raise
            print("Inno Setup не собрал установщик, пробую ещё раз")

    setup = DIST / f"GameHub-Setup-{VERSION}.exe"
    sign(setup, SIGNER_THUMBPRINT)
    if not updater.signature_ok(str(setup)):     # та же проверка, что сделает автообновление
        sys.exit("Подпись установщика не проходит проверку автообновления")
    print(f"\nГотово: {setup} ({setup.stat().st_size / 1e6:.1f} МБ)")


if __name__ == "__main__":
    main()
