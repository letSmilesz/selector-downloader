"""
scripts/setup_chrome.py — однократная загрузка пинированного бинаря Chrome for Testing.
В git бинарь НЕ коммитим (~160 МБ): на свежем клоне достаточно запустить этот скрипт.
Идемпотентен: если find_pinned_chrome() уже находит exe — ничего не делает.
Перезагрузка поверх: python scripts/setup_chrome.py --force
"""
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from browser.driver import find_pinned_chrome
from core.logger import get_app_base_dir

CHROME_PIN = "152.0.7977.82"   # пин: один бинарь на авторизацию и боевой режим
URL = (f"https://storage.googleapis.com/chrome-for-testing-public/"
       f"{CHROME_PIN}/win64/chrome-win64.zip")


def main() -> int:
    force = "--force" in sys.argv[1:]
    existing = find_pinned_chrome()
    if existing and not force:
        print(f"Chrome уже установлен: {existing}")
        return 0
    target_dir = get_app_base_dir() / "chrome152"
    print(f"Качаю Chrome for Testing {CHROME_PIN} ...")
    print(URL)
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "chrome-win64.zip"
        with urllib.request.urlopen(URL) as r, open(zip_path, "wb") as f:
            shutil.copyfileobj(r, f)
        print("Распаковываю...")
        unpacked = Path(tmp) / "unpacked"
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(unpacked)
        inner = unpacked / "chrome-win64"
        if not inner.exists():
            print("ERROR: в архиве нет папки chrome-win64", flush=True)
            return 1
        dest = target_dir / "chrome-win64"
        if dest.exists():
            shutil.rmtree(dest)
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(inner), str(dest))
    exe = find_pinned_chrome()
    if exe is None:
        print("ERROR: chrome.exe не найден после распаковки", flush=True)
        return 1
    print(f"Готово: {exe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())