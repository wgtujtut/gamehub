"""Сборка GameHub: exe (PyInstaller) и установщик (Inno Setup).
Запуск: .venv\\Scripts\\python.exe build.py  →  dist\\GameHub-Setup-<версия>.exe
"""
import os
import shutil
import subprocess
import sys
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


def run(cmd):
    print(">", " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True, cwd=ROOT)


def main() -> None:
    sys.path.insert(0, str(ROOT))
    from app import make_icon_image
    from updater import VERSION

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
    run([iscc, f"/DAppVersion={VERSION}", "/Q", ROOT / "installer.iss"])

    setup = DIST / f"GameHub-Setup-{VERSION}.exe"
    print(f"\nГотово: {setup} ({setup.stat().st_size / 1e6:.1f} МБ)")


if __name__ == "__main__":
    main()
