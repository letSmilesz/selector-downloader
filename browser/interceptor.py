# browser/interceptor.py
import time
from typing import List, Dict, Optional, Set
from playwright.sync_api import Page, Response

from core.logger import debug_log

class ImageInterceptor:
    def __init__(self, page: Page, min_size: int = 512):
        self.page = page
        self.min_size = min_size
        self._responses_by_url: Dict[str, Response] = {}
        self._responses_by_request_url: Dict[str, Response] = {}
        self._attached = False

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Нормализует пробелы в URL (%20), чтобы собранные и перехваченные совпадали."""
        if not url:
            return url
        from urllib.parse import quote
        return quote(url, safe=":/?#[]@!$&'()*+,;=%")

    def _on_response(self, response: Response) -> None:
        """Обработчик события response. Сохраняет объект Response, но не вызывает body()."""
        if response.request.resource_type != "image":
            return
        if response.status != 200:
            return
        url = self._normalize_url(response.url)
        request_url = self._normalize_url(response.request.url)
        self._responses_by_url[url] = response
        self._responses_by_request_url[request_url] = response

    def attach(self) -> None:
        """Подписывается на событие response."""
        if self._attached:
            return
        self.page.on("response", self._on_response)
        self._attached = True
        debug_log("ImageInterceptor attached")

    def detach(self) -> None:
        """Отписывается от события response."""
        if not self._attached:
            return
        self.page.remove_listener("response", self._on_response)
        self._attached = False
        debug_log("ImageInterceptor detached")

    def clear(self) -> None:
        """Очищает накопленные ответы (между главами)."""
        self._responses_by_url.clear()
        self._responses_by_request_url.clear()
        debug_log("ImageInterceptor cleared")

    def collect(
    self,
    urls: List[str]
) -> Dict[str, bytes]:
        """
        Собирает байты для переданных URL.
        Сначала берёт то, что уже есть в перехваченных ответах.
        Для недостающего пробует достать из кэша браузера через fetch.
        Возвращает словарь {url: bytes} для тех, что удалось загрузить и размер > min_size.
        """
        if not urls:
            return {}
        urls = list(dict.fromkeys(urls))
        found_set: Set[str] = set()
        
        # Сразу собираем из перехваченных, без ожидания сети
        for url in urls:
            nurl = self._normalize_url(url)
            if nurl in self._responses_by_url or nurl in self._responses_by_request_url:
                found_set.add(url)
        
        result: Dict[str, bytes] = {}
        for url in urls:
            if url in found_set:
                nurl = self._normalize_url(url)
                response = self._responses_by_url.get(nurl) or self._responses_by_request_url.get(nurl)
                if response is None:
                    continue
                try:
                    body = response.body()
                    if len(body) < self.min_size:
                        debug_log(f"Тело {url} слишком мало ({len(body)} байт), пропускаем")
                        continue
                    result[url] = body
                except Exception as e:
                    debug_log(f"Ошибка получения тела для {url}: {e}")
        
        # Фолбэк: для тех, что не в интерсепторе, пробуем fetch из кэша браузера
        still_missing = [url for url in urls if url not in result]
        if still_missing:
            debug_log(f"collect: {len(still_missing)} URL не в интерсепторе, пробуем fetch из кэша")
            for url in still_missing:
                try:
                    body = self.page.evaluate("""
                        async (url) => {
                            try {
                                const response = await fetch(url, {cache: "force-cache"});
                                if (!response.ok) return null;
                                const blob = await response.blob();
                                const buffer = await blob.arrayBuffer();
                                return Array.from(new Uint8Array(buffer));
                            } catch (e) {
                                return null;
                            }
                        }
                    """, url)
                    if body:
                        body_bytes = bytes(body)
                        if len(body_bytes) >= self.min_size:
                            result[url] = body_bytes
                            debug_log(f"collect: получено через fetch: {url} ({len(body_bytes)} байт)")
                        else:
                            debug_log(f"collect: fetch вернул слишком мало байт: {url} ({len(body_bytes)} байт)")
                    else:
                        debug_log(f"collect: fetch вернул null для {url}")
                except Exception as e:
                    debug_log(f"collect: fetch не удался для {url}: {e}")
            debug_log(f"collect: в by_url: {list(self._responses_by_url.keys())[:30]}")
            debug_log(f"collect: в by_req: {list(self._responses_by_request_url.keys())[:30]}")

        debug_log(f"collect: возвращено {len(result)} из {len(urls)} картинок")
        return result

    def wait_loading_complete(
        self,
        loading_selector: Optional[str],
        timeout_ms: int = 30000
    ) -> bool:
        """
        Ожидает, что элемент с селектором исчезнет или станет скрытым.
        Если selector None или пустой, сразу возвращает True.
        """
        if not loading_selector:
            return True
        locator = self.page.locator(loading_selector)
        start = time.monotonic()
        while time.monotonic() - start < timeout_ms / 1000.0:
            count = locator.count()
            if count == 0:
                return True
            # Проверяем, скрыт ли элемент (если их несколько, проверяем первый)
            if count > 0 and locator.first.is_hidden():
                return True
            time.sleep(0.2)
        return False