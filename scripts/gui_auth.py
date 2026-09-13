"""
scripts/gui_auth.py — авторизация через чистый Chrome (без Playwright).
Все вкладки и OAuth-попапы работают нативно. Куки пишутся в chrome_profile.
Lock .downloader.lock исключает параллель с боевым запуском.
Завершение: закрыть окно ИЛИ файл chrome_profile/.auth_stop (кнопка GUI).
"""
import os
import subprocess
import sys
import time
from typing import List
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from browser.driver import find_pinned_chrome, normalize_profile_prefs

PROFILE_DIR = Path(__file__).parent.parent / "chrome_profile"
STOP_FILE = PROFILE_DIR / ".auth_stop"
LOCK_FILE = PROFILE_DIR / ".downloader.lock"


def _take_lock() -> None:
    """Тот же lock-протокол, что в BrowserSession: взаимное исключение с боевым запуском."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(LOCK_FILE, "x") as f:
            f.write(str(os.getpid()))
    except FileExistsError:
        raise RuntimeError(
            f"Профиль занят другим процессом (файл {LOCK_FILE}). "
            "Если это не так, удалите файл вручную."
        )


def _release_lock() -> None:
    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
    except Exception:
        pass

def _profile_chrome_pids() -> List[int]:
    """PID всех chrome.exe, чья командная строка содержит наш профиль."""
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{PROFILE_DIR.name}*' }} | "
        "Select-Object -ExpandProperty ProcessId"
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return [int(x) for x in out.stdout.split() if x.strip().isdigit()]


def _kill_profile_chrome(force: bool = False) -> int:
    """Штатно (WM_CLOSE) или принудительно гасит ВСЕ chrome.exe нашего профиля.
    Возвращает число затронутых процессов."""
    pids = _profile_chrome_pids()
    for pid in pids:
        cmd = (["taskkill", "/F", "/T", "/PID", str(pid)] if force
               else ["taskkill", "/PID", str(pid)])
        subprocess.run(cmd, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return len(pids)

def main():
    if STOP_FILE.exists():
        try:
            STOP_FILE.unlink()
        except Exception:
            pass
    
    exe = find_pinned_chrome()
    if exe is None:
        print("ERROR: Пинированный Chrome не найден в chrome152/ или chrome_bin/", flush=True)
        return

    alive = _profile_chrome_pids()
    if alive:
        print(f"ERROR: Chrome с этим профилем уже запущен (PID: {alive}). "
              "Закрой его и повтори.", flush=True)
        return
    normalize_profile_prefs(PROFILE_DIR)
    _take_lock()
    try:
        proc = subprocess.Popen(
            [str(exe), f"--user-data-dir={PROFILE_DIR}",
             "--profile-directory=Default",
             "--hide-restore-bubble",
             "--disable-session-crashed-bubble",
             "about:blank"],
        )
        print("READY: браузер открыт, залогинься и закрой окно", flush=True)
        while proc.poll() is None:
            time.sleep(1)
            if STOP_FILE.exists():
                try:
                    STOP_FILE.unlink()
                except Exception:
                    pass
                print("Получена команда завершения, закрываю браузер", flush=True)
                n = _kill_profile_chrome(force=False)   # WM_CLOSE каждому browser-процессу профиля
                print(f"Закрываю Chrome: процессов = {n}...", flush=True)
                deadline = time.time() + 10
                while time.time() < deadline and _profile_chrome_pids():
                    time.sleep(1)
                for _ in range(2):   # принудительно + добор сирот вторым раундом
                    if not _profile_chrome_pids():
                        break
                    _kill_profile_chrome(force=True)
                    time.sleep(1)
                left = _profile_chrome_pids()
                print(f"Chrome закрыт. Оставшихся процессов: {len(left)}", flush=True)
                break
        # Страховка: добираем остаток процессов профиля (зомби-рендеры и т.п.)
        if _profile_chrome_pids():
            _kill_profile_chrome(force=True)
    except Exception as e:
        print(f"ERROR: {e}", flush=True)
    finally:
        _release_lock()


if __name__ == "__main__":
    main()