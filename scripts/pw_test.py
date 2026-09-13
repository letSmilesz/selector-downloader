"""
scripts/pw_test.py — режим разработчика: тот же пинированный Chrome, но через Playwright (headed).
Смотреть, что видит скрипт: NAV-логи в консоли, F12 на первой вкладке.
GUI не используется; боевой путь не трогает.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from browser.driver import BrowserSession

STOP_FILE = Path(__file__).parent.parent / "chrome_profile" / ".auth_stop"


def main():
    if STOP_FILE.exists():
        try:
            STOP_FILE.unlink()
        except Exception:
            pass
    with BrowserSession(headed=True) as session:   # пин подхватится из chrome152/ автоматически
        session.goto("about:blank")
        print("READY: дебаг через Playwright. NAV-логи ниже; закрыл окно — выход", flush=True)
        last_url = ""
        while True:
            time.sleep(1)
            if STOP_FILE.exists():
                try:
                    STOP_FILE.unlink()
                except Exception:
                    pass
                print("Получена команда завершения, закрываю браузер", flush=True)
                break
            try:
                cur = session.page.url
            except Exception:
                break
            if cur != last_url:
                last_url = cur
                print(f"NAV: {cur}", flush=True)


if __name__ == "__main__":
    main()