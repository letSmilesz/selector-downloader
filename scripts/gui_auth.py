"""
scripts/gui_auth.py — headed-браузер для логина; куки пишутся в chrome_profile.
Завершение: закрыть окно браузера ИЛИ файл chrome_profile/.auth_stop
(кнопка GUI «Завершить логин»).
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
    with BrowserSession(headed=True, channel="chrome") as session:
        session.goto("about:blank")
        print("READY: браузер открыт, залогинься и закрой окно", flush=True)
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
                _ = session.page.url   # бросит исключение, если окно закрыли
            except Exception:
                break


if __name__ == "__main__":
    main()