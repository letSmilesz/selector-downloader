import os
from pathlib import Path
from typing import Optional, Tuple, List
import json
import shutil
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, BrowserContext, Page, Playwright
from core.logger import debug_log, emit_event, get_app_base_dir

def find_pinned_chrome() -> Optional[Path]:
    """Ищет пинированный Chrome проекта. Возвращает путь или None."""
    base = get_app_base_dir()
    candidates = [
        base / "chrome152" / "chrome.exe",
        base / "chrome152" / "chrome-win64" / "chrome.exe",
        base / "chrome_bin" / "chrome.exe",
        base / "chrome_bin" / "chrome-win64" / "chrome.exe",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None

def normalize_profile_prefs(profile_dir: Path) -> None:
    """Убивает воскресение вкладок: сносит файлы-списки сессии и сбрасывает
    «краш»-статус профиля. Куки, localStorage и sessionStorage НЕ трогает.
    Вызывать ТОЛЬКО когда Chrome не запущен."""
    default_dir = profile_dir / "Default"
    # 1) Физически удаляем списки вкладок для восстановления
    victims: List[Path] = []
    sess_dir = default_dir / "Sessions"
    if sess_dir.is_dir():
        victims.extend(sess_dir.iterdir())
    for name in ("Current Session", "Current Tabs", "Last Session", "Last Tabs"):
        victims.append(default_dir / name)
    for v in victims:
        try:
            if v.is_file():
                v.unlink()
            elif v.is_dir():
                shutil.rmtree(v, ignore_errors=True)
        except Exception:
            pass
    # 2) Preferences: нет «краша», старт = чистая новая вкладка
    prefs_path = default_dir / "Preferences"
    if not prefs_path.exists():
        return
    try:
        data = json.loads(prefs_path.read_text(encoding="utf-8"))
    except Exception:
        return
    changed = False
    prof = data.setdefault("profile", {})
    if prof.get("exit_type") != "Normal":
        prof["exit_type"] = "Normal"
        changed = True
    sess = data.setdefault("session", {})
    if sess.get("restore_on_startup") != 5:   # 5 = всегда чистая новая вкладка
        sess["restore_on_startup"] = 5
        changed = True
    if changed:
        prefs_path.write_text(json.dumps(data), encoding="utf-8")

class BrowserSession:
    def __init__(self,
                 headed: bool = False,
                 channel: str = "chrome",
                 profile_dir: Optional[Path] = None,
                 viewport: Tuple[int, int] = (1200, 800),
                 same_site_fix: bool = False,
                 extra_args: Optional[List[str]] = None,
                 executable_path: Optional[str] = None):
        self.headed = headed
        self.channel = channel
        self.profile_dir = profile_dir or (get_app_base_dir() / "chrome_profile")
        self.viewport = viewport
        self.same_site_fix = same_site_fix
        self.extra_args = extra_args or []
        self.executable_path = executable_path
        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._lock_path = self.profile_dir / ".downloader.lock"
        self._lock_held = False

    def start(self) -> None:
        """Запускает браузер с постоянным профилем."""
        if self._context is not None:
            return
            
        if self._lock_path.exists():
            raise RuntimeError(
                f"Профиль занят другим процессом (файл {self._lock_path}). "
                "Если это не так, удалите файл вручную."
            )
            
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(self._lock_path, 'x') as f:
                f.write(str(os.getpid()))
        except FileExistsError:
            raise RuntimeError(f"Не удалось создать lock-файл {self._lock_path}")
        self._lock_held = True
        normalize_profile_prefs(self.profile_dir) 
        args = [
            "--profile-directory=Default",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--hide-restore-bubble",
            "--disable-session-crashed-bubble",
        ]
        if not self.headed:
            args.append("--ignore-certificate-errors")
        if self.same_site_fix:
            args.append("--disable-features=SameSiteByDefaultCookies,CookiesWithoutSameSiteMustBeSecure")
        args.extend(self.extra_args)

        try:
            self._playwright = sync_playwright().start()
            
            # Выбираем бинарь: явно заданный > пинированный в проекте
            # Системный Chrome ЗАПРЕЩЁН — только пинированный бинарь
            exe = Path(self.executable_path) if self.executable_path else find_pinned_chrome()
            
            if not exe:
                raise RuntimeError(
                    "Пинированный Chrome не найден. "
                    "Запустите 'python scripts/setup_chrome.py' для установки или "
                    "укажите путь через executable_path."
                )
            
            debug_log(f"BrowserSession: используется пинированный бинарь {exe}")
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=not self.headed,
                executable_path=str(exe),  # channel и executable_path взаимоисключающи
                viewport={"width": self.viewport[0], "height": self.viewport[1]},
                args=args,
            )
            self._context.set_default_timeout(30000)
            self._context.set_default_navigation_timeout(30000)
            if self._context.pages:
                self._page = self._context.pages[0]
            else:
                self._page = self._context.new_page()
            debug_log(f"BrowserSession started (headed={self.headed}, channel={self.channel})")
            emit_event("browser_started", headed=self.headed, channel=self.channel)
        except Exception as e:
            self.close()
            emit_event("error", message=f"Ошибка запуска браузера: {e}")
            raise

    def close(self) -> None:
        """Закрывает браузер и освобождает профиль."""
        if self._context:
            try:
                self._context.close()
            except Exception as e:
                debug_log(f"Ошибка при закрытии контекста: {e}")
            self._context = None
            self._page = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception as e:
                debug_log(f"Ошибка при остановке Playwright: {e}")
            self._playwright = None
        # Удаляем lock-файл
        if self._lock_held:
            try:
                if self._lock_path.exists():
                    self._lock_path.unlink()
            except Exception as e:
                debug_log(f"Не удалось удалить lock-файл: {e}")
            self._lock_held = False
        debug_log("BrowserSession closed")

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Браузер не запущен. Вызовите start() сначала.")
        return self._page

    def goto(self, url: str, timeout_ms: int = 30000, referer: str = "https://www.google.com/") -> None:
        resp = self.page.goto(url, timeout=timeout_ms, referer=referer, wait_until='domcontentloaded')
        status = resp.status if resp is not None else 0
        debug_log(f"goto: статус {status} для {url}")
        if (status in (403, 404)
                and urlparse(url).scheme in ("http", "https")
                and urlparse(referer).scheme in ("http", "https")):
            debug_log(f"goto: статус {status} — похоже на защиту от прямого захода, ретрай через живой реферер")
            if not self._goto_cross_site(url, referer, timeout_ms):
                # Возвращаем состояние «как раньше»: страница на исходном URL
                self.page.goto(url, timeout=timeout_ms, referer=referer, wait_until='domcontentloaded')

    def _goto_cross_site(self, url: str, referer_page: str, timeout_ms: int) -> bool:
        """Заход на сайты с anti-hotlink защитой (404 при прямом goto).
        Садимся на документ-донор реферера и уходим с него доверенным кликом:
        Chromium сам строит пакет cross-site перехода (Referer по политике
        донора + Sec-Fetch-Site: cross-site, Sec-Fetch-Mode: navigate,
        Sec-Fetch-Dest: document, Sec-Fetch-User: ?1). Фолбэк — location.replace."""
        try:
            self.page.goto(referer_page, timeout=timeout_ms, wait_until="domcontentloaded")
            stay = self.page.url
            try:
                self.page.evaluate(
                    "u => { const a = document.createElement('a'); a.href = u; a.id = '__xsite';"
                    " a.textContent = 'goto'; a.style.cssText = 'position:fixed;top:0;left:0;z-index:2147483647';"
                    " document.body.appendChild(a); }",
                    url,
                )
                self.page.click("#__xsite", timeout=5000)
            except Exception as e:
                debug_log(f"_goto_cross_site: клик по внедрённой ссылке не удался ({e}) — location.replace")
                self.page.evaluate("u => { window.location.replace(u); }", url)
            self.page.wait_for_url(lambda u: u != stay, timeout=timeout_ms)
            self.page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            debug_log(f"_goto_cross_site: заход через живой реферер выполнен, url={self.page.url}")
            return True
        except Exception as e:
            debug_log(f"_goto_cross_site: не удалось: {e}")
            return False    

    def add_init_script(self, script: str) -> None:
        """Регистрирует init-скрипт контекста (применяется до загрузки страниц).
        Используется только auth-режимом для маршрутизации попапов в текущую вкладку."""
        if self._context is None:
            raise RuntimeError("Браузер не запущен. Вызовите start() сначала.")
        self._context.add_init_script(script)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()