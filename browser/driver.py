import os
from random import random
from pathlib import Path
from typing import Optional, Tuple, List
from playwright.sync_api import sync_playwright, BrowserContext, Page, Playwright
from core.logger import debug_log, emit_event, get_app_base_dir

# Пул современных User-Agent для ротации (Windows + Chrome)
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

class BrowserSession:
    def __init__(self,
                 headed: bool = False,
                 channel: str = "chrome",
                 profile_dir: Optional[Path] = None,
                 viewport: Tuple[int, int] = (1200, 800),
                 same_site_fix: bool = False,
                 extra_args: Optional[List[str]] = None):
        self.headed = headed
        self.channel = channel
        self.profile_dir = profile_dir or (get_app_base_dir() / "chrome_profile")
        self.viewport = viewport
        self.same_site_fix = same_site_fix
        self.extra_args = extra_args or []
        
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

        args = [
            "--profile-directory=Default",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ]
        if not self.headed:
            args.append("--ignore-certificate-errors")
        if self.same_site_fix:
            args.append("--disable-features=SameSiteByDefaultCookies,CookiesWithoutSameSiteMustBeSecure")
        args.extend(self.extra_args)

        try:
            self._playwright = sync_playwright().start()
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=not self.headed,
                channel=self.channel,
                viewport={"width": self.viewport[0], "height": self.viewport[1]},
                args=args,
                # Ротация User-Agent из пула, чтобы не палиться на Linux-серверах
                user_agent=_UA_POOL[int(random() * len(_UA_POOL))],
            )
            
            # Антидетект: скрываем признаки автоматизации до загрузки страниц
            self._context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [
                        { name: "Chrome PDF Plugin", filename: "internal-pdf-viewer", description: "Portable Document Format" },
                        { name: "Chrome PDF Viewer", filename: "mhjfbmdgcfjbbpaeojofohoefgiehjai", description: "" },
                        { name: "Native Client", filename: "internal-nacl-plugin", description: "" }
                    ]
                });
                Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU', 'ru', 'en-US', 'en'] });
                
                const getParameter = WebGLRenderingContext.prototype.getParameter;
                WebGLRenderingContext.prototype.getParameter = function(parameter) {
                    if (parameter === 37445) return 'Intel Inc.'; 
                    if (parameter === 37446) return 'Intel(R) Iris(Xe) Graphics';
                    return getParameter.apply(this, arguments);
                };
            """)
            
            self._context.set_default_timeout(30000)
            self._context.set_default_navigation_timeout(30000)

            if self._context.pages:
                self._page = self._context.pages[0]
            else:
                self._page = self._context.new_page()
            def _on_new_page(p):
                try:
                    if p is not self._page:
                        p.close()
                        debug_log("driver: закрыта рекламная вкладка")
                except Exception:
                    pass
            self._context.on("page", _on_new_page)
                
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
        self.page.goto(url, timeout=timeout_ms, referer=referer, wait_until='domcontentloaded')

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()