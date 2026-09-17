import os
from pathlib import Path
from typing import Optional, Tuple, List
import json
import shutil
import socket
import subprocess
import time
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
                 executable_path: Optional[str] = None,
                 initial_url: Optional[str] = None):
        self.headed = headed
        self.channel = channel
        self.profile_dir = profile_dir or (get_app_base_dir() / "chrome_profile")
        self.viewport = viewport
        self.same_site_fix = same_site_fix
        self.extra_args = extra_args or []
        self.executable_path = executable_path
        self.initial_url = initial_url
        self._browser_proc: Optional[subprocess.Popen] = None
        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._lock_path = self.profile_dir / ".downloader.lock"
        self._lock_held = False

    def _free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def _wait_port(self, port: int, timeout_s: float = 20.0) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    return True
            except OSError:
                time.sleep(0.25)
        return False

    def start(self) -> None:
        """Запускает браузер с постоянным профилем: свой spawn чистой cmdline
        (класс gui_auth/Т2) + connect_over_cdp. Стартовая навигация браузера несёт
        куки; launch_persistent_context не используется (Т1: при CDP с рождения
        куки не шлёт ни одна навигация)."""
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
        try:
            exe = Path(self.executable_path) if self.executable_path else find_pinned_chrome()
            if not exe:
                raise RuntimeError(
                    "Пинированный Chrome не найден. "
                    "Запустите 'python scripts/setup_chrome.py' для установки или "
                    "укажите путь через executable_path."
                )
            debug_log(f"BrowserSession: используется пинированный бинарь {exe}")
            port = self._free_port()
            args = [
                f"--user-data-dir={self.profile_dir}",
                "--profile-directory=Default",
                "--hide-restore-bubble",
                "--disable-session-crashed-bubble",
                f"--remote-debugging-port={port}",
            ]
            if not self.headed:
                args += ["--headless=new", "--ignore-certificate-errors"]
            if self.same_site_fix:
                args.append("--disable-features=SameSiteByDefaultCookies,CookiesWithoutSameSiteMustBeSecure")
            args.extend(self.extra_args)
            args.append(self.initial_url or "about:blank")
            self._browser_proc = subprocess.Popen([str(exe)] + args)
            if not self._wait_port(port):
                raise RuntimeError("Chrome не открыл отладочный порт за 20 секунд")
            self._playwright = sync_playwright().start()
            browser = self._playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{port}", timeout=30000)
            if not browser.contexts:
                raise RuntimeError("connect_over_cdp не вернул ни одного контекста")
            self._context = browser.contexts[0]
            self._context.set_default_timeout(30000)
            self._context.set_default_navigation_timeout(30000)
            if self._context.pages:
                self._page = self._context.pages[0]
            else:
                self._page = self._context.new_page()
            try:
                self._page.wait_for_load_state("domcontentloaded", timeout=30000)
            except Exception as e:
                debug_log(f"BrowserSession: ожидание стартовой загрузки: {e}")
            if self.headed:
                try:
                    self._page.set_viewport_size(
                        {"width": self.viewport[0], "height": self.viewport[1]})
                except Exception as e:
                    debug_log(f"BrowserSession: viewport не применён: {e}")
            debug_log(f"BrowserSession started (headed={self.headed}, channel={self.channel})")
            emit_event("browser_started", headed=self.headed, channel=self.channel)
        except Exception as e:
            self.close()
            emit_event("error", message=f"Ошибка запуска браузера: {e}")
            raise

    def close(self) -> None:
        """Отключает Playwright и штатно (WM_CLOSE) гасит Chrome — порядок
        «сначала pw off, затем браузер» проверен вручную: jar сохраняется."""
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception as e:
                debug_log(f"Ошибка при остановке Playwright: {e}")
            self._playwright = None
        self._context = None
        self._page = None
        if self._browser_proc is not None:
            pid = self._browser_proc.pid
            try:
                subprocess.run(["taskkill", "/PID", str(pid)],
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self._browser_proc.wait(timeout=10)
            except Exception:
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    self._browser_proc.wait(timeout=5)
                except Exception as e:
                    debug_log(f"Не удалось завершить Chrome: {e}")
            self._browser_proc = None
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
        cur, tgt = urlparse(self.page.url), urlparse(url)
        same = (cur.scheme, cur.netloc, cur.path) == (tgt.scheme, tgt.netloc, tgt.path)
        if same:
            # Страницу уже открыла стартовая навигация браузера (с куками профиля).
            # Её статус берём из PerformanceNavigationTiming: anti-hotlink сайты
            # (ahen и т.п.) отдают 403/404 на прямой заход без реферера.
            try:
                status = self.page.evaluate(
                    "() => { const e = performance.getEntriesByType('navigation')[0];"
                    " return e && 'responseStatus' in e ? e.responseStatus : 0; }")
            except Exception as e:
                debug_log(f"goto: не удалось прочитать статус стартовой навигации: {e}")
                status = 0
            debug_log(f"goto: уже на этом URL ({url}) — статус стартовой навигации {status}")
            if status not in (403, 404):
                return
        else:
            resp = self.page.goto(url, timeout=timeout_ms, referer=referer, wait_until='domcontentloaded')
            status = resp.status if resp is not None else 0
            debug_log(f"goto: статус {status} для {url}")
        if (status in (403, 404)
                and urlparse(url).scheme in ("http", "https")
                and urlparse(referer).scheme in ("http", "https")):
            debug_log(f"goto: статус {status} — похоже на защиту от прямого захода, ретрай через живой реферер")
            if not self._goto_cross_site(url, referer, timeout_ms):
                if not same:
                    # Возвращаем состояние «как раньше»: страница на исходном URL
                    self.page.goto(url, timeout=timeout_ms, referer=referer, wait_until='domcontentloaded')
                else:
                    debug_log("goto: ретрай через живой реферер не удался, остаёмся на стартовой странице")

    def _goto_cross_site(self, url: str, referer_page: str, timeout_ms: int) -> bool:
        """Заход на сайты с anti-hotlink защитой (404 при прямом goto).
        Садимся на документ-донор реферера и уходим с него доверенным кликом:
        Chromium сам строит пакет cross-site перехода (Referer по политике
        донора + Sec-Fetch-Site: cross-site, Sec-Fetch-Mode: navigate,
        Sec-Fetch-Dest: document, Sec-Fetch-User: ?1). Фолбэк — location.replace."""
        try:
            t0 = time.monotonic()
            self.page.goto(referer_page, timeout=timeout_ms, wait_until="domcontentloaded")
            stay = self.page.url
            debug_log(f"_goto_cross_site: донор загружен за {time.monotonic() - t0:.1f}с: {stay}")
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
            debug_log(f"_goto_cross_site: переход выполнен за {time.monotonic() - t0:.1f}с, url={self.page.url}")
            # Best-effort: цепочки челленжей (DDoS-Guard) устраивают гонку жизненного
            # цикла — Playwright может прозевать уже случившийся domcontentloaded
            # и ложно висеть до таймаута. URL уже на цели: селекторы дальше дождутся DOM сами.
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                debug_log("_goto_cross_site: ожидание domcontentloaded вышло по таймауту "
                          "(цепочка челленжей) — продолжаем, URL уже на цели")
            debug_log(f"_goto_cross_site: заход через живой реферер выполнен за {time.monotonic() - t0:.1f}с, url={self.page.url}")
            return True
        except Exception as e:
            debug_log(f"_goto_cross_site: не удалось за {time.monotonic() - t0:.1f}с: {e}")
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