# engine/reader.py
"""
Движок скачивания глав: web-лента и постраничный режим.
Порт рабочих циклов из старого кода под Playwright + перехватчик.
"""
import time
import random
import re
import shutil
import threading
from pathlib import Path
from typing import Optional, Tuple, overload, Literal
from urllib.parse import urlparse, urljoin
from datetime import datetime
from playwright.sync_api import Page, Locator

from core.logger import debug_log, emit_event
from core.namer import generate_chapter_name
from core.retry import get_delay
from output.archiver import finalize_chapter_output
from browser.interceptor import ImageInterceptor

_mode_attempts: set = set()

# Мягкий ретрай при ожидании загрузки картинки.
# Быстрая фаза: 15 секунд. Если не загрузилась — ретрай и долгая фаза 90 секунд.
# Для тестов выставлены маленькие таймауты.
# В боевом режиме: 15 секунд быстрая фаза, 90 секунд долгая фаза.
IMG_WAIT_QUICK_S = 15.0    # тест: 5.0; боевой: 15.0 — без уведомлений, ×2 прогона
IMG_WAIT_LONG_S = 90.0    # тест: 7.0; боевой: 90.0 — после него уведомление в GUI
CHAPTER_WARN_S   = 300.0   # тест: 10.0; боевой: 300.0 — уведомление о долгой главе
IMG_WAIT_SLEEP_S = 0.5     # как часто делается проверка загрузки(сон)

# Долгая глава: таймер из чужого потока ТОЛЬКО поднимает флаг.
# debug_log/emit_event вызываются из main-потока в точках опроса.
_chapter_slow_flag = threading.Event()   # ставится таймером по CHAPTER_WARN_S
_chapter_slow_done = threading.Event()   # предупреждение уже отправлено (защита от дублей)
_chapter_timer: Optional[threading.Timer] = None   # активный таймер долгой главы (единственное место инициализации)

def _warn_chapter_slow(number) -> None:
    span = f"{CHAPTER_WARN_S:.0f} секунд" if CHAPTER_WARN_S < 60 else f"{CHAPTER_WARN_S / 60:.0f} минут"
    debug_log(f"Глава {number} грузится больше {span}")
    emit_event("chapter_slow",
               chapter_number=number,
               message=f"Глава {number} грузится больше {span}, но программа продолжает загрузку")


def _check_chapter_slow(number) -> None:
    """Точка опроса для main-потока: отправить chapter_slow, если таймер сработал."""
    if number is None:
        return
    if _chapter_slow_flag.is_set() and not _chapter_slow_done.is_set():
        _chapter_slow_done.set()
        _warn_chapter_slow(number)

def _chapter_timer_cancel() -> None:
    global _chapter_timer
    if _chapter_timer is not None:
        _chapter_timer.cancel()
        _chapter_timer = None

def start_chapter_timer() -> None:
    """Сбрасывает флаги и запускает таймер долгой главы."""
    global _chapter_timer
    _chapter_slow_flag.clear()
    _chapter_slow_done.clear()
    _chapter_timer_cancel()
    _chapter_timer = threading.Timer(CHAPTER_WARN_S, _chapter_slow_flag.set)
    _chapter_timer.daemon = True
    _chapter_timer.start()


def stop_chapter_timer() -> None:
    """Отменяет таймер долгой главы."""
    _chapter_timer_cancel()

def dismiss_popups(page: Page, preset: dict) -> None:
    """
    Закрывает попапы (18+, cookie, рекламные оверлеи) обычными кликами Playwright.
    Текстовые кнопки: dismiss_texts (матчинг через :has-text).
    Иконочные кнопки (svg-крестики без текста): dismiss_selectors — готовые CSS-селекторы.
    """
    sel = preset.get("selectors", {})
    texts = sel.get("dismiss_texts") or preset.get("dismiss_texts", [])
    extra = sel.get("dismiss_selectors") or preset.get("dismiss_selectors", [])
    if isinstance(texts, str):
        texts = [texts]
    if isinstance(extra, str):
        extra = [extra]
    targets = [f'{tag}:has-text("{t.strip()}")'
               for t in texts if t.strip()
               for tag in ('button', 'a', '[role="button"]')]
    targets += [s.strip() for s in extra if s.strip()]
    if not targets:
        debug_log("dismiss_popups: dismiss_texts/dismiss_selectors пусты в пресете")
        return
    debug_log(f"dismiss_popups: ищу цели {targets}")
    for attempt in range(3):
        clicked_any = False
        for css in targets:
            try:
                loc = page.locator(css)
                for idx in range(min(loc.count(), 10)):
                    el = loc.nth(idx)
                    if el.is_visible():
                        try:
                            el.scroll_into_view_if_needed(timeout=1000)
                        except Exception:
                            pass
                        el.click(timeout=1500)
                        debug_log(f"dismiss_popups: кликнут {css} (совпадение {idx})")
                        clicked_any = True
                        time.sleep(0.5)
                        break
            except Exception:
                pass
        if clicked_any:
            time.sleep(1.0)
        else:
            break

        # Фолбэк: стандартные крестики закрытия (SVG, иконки без текста, туры)
        # Бэк сам закроет типовые модалки, даже если в пресете dismiss_texts = null
        standard_close_selectors = [
            'button[aria-label="Close"]', 'button[aria-label="Закрыть"]',
            'a[aria-label="Close"]', 'a[aria-label="Закрыть"]',
            '[role="button"][aria-label="Close"]',
            '.modal-close', '.popup-close', '.driver-popover-close-btn'
        ]
        for sel in standard_close_selectors:
            try:
                loc = page.locator(sel)
                for idx in range(min(loc.count(), 3)):
                    el = loc.nth(idx)
                    if el.is_visible():
                        try:
                            el.scroll_into_view_if_needed(timeout=1000)
                        except Exception:
                            pass
                        el.click(timeout=1500)
                        debug_log(f"dismiss_popups: кликнут стандартный крестик {sel}")
                        time.sleep(0.3)
            except Exception:
                pass
    # Пресет может задать селекторы рекламных контейнеров без кнопки закрытия,
    # которые достаточно скрыть (оверлеи, перехватывающие клики).
    remove_sels = (preset.get("selectors", {}) or {}).get("dismiss_remove_selectors") or preset.get("dismiss_remove_selectors") or []
    if isinstance(remove_sels, str):
        remove_sels = [remove_sels]
    remove_sels = [s.strip() for s in remove_sels if s.strip()]
    if remove_sels:
        try:
            page.evaluate(
                "(sels) => { for (const s of sels) document.querySelectorAll(s).forEach(el => { el.style.display = 'none'; }); }",
                remove_sels,
            )
            debug_log(f"dismiss_popups: скрыты рекламные контейнеры {remove_sels}")
        except Exception as e:
            debug_log(f"dismiss_popups: не удалось скрыть контейнеры: {e}")

def _selector_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [v for v in value if isinstance(v, str) and v.strip()]


def click_first_visible(page: Page, selectors, role: str, timeout: int = 2500) -> bool:
    """
    Кликает первый видимый элемент среди селекторов.
    Нужен для сайтов с дублями: скрытая справка, mobile/desktop панели, footer/header.
    """
    for css in _selector_list(selectors):
        try:
            loc = page.locator(css)
            count = min(loc.count(), 10)
            debug_log(f"click_first_visible: {role}: {css}, совпадений={count}")
            for idx in range(count):
                el = loc.nth(idx)
                try:
                    if not el.is_visible():
                        continue
                    try:
                        el.scroll_into_view_if_needed(timeout=1000)
                    except Exception:
                        pass
                    try:
                        el.click(timeout=timeout)
                    except Exception:
                        # JS fallback для floating/overlay-кнопок, где обычный click/hover капризничает
                        el.evaluate("(e) => e.click()")
                    debug_log(f"click_first_visible: кликнут {role}: {css} (совпадение {idx})")
                    return True
                except Exception:
                    continue
        except Exception as e:
            debug_log(f"click_first_visible: {role}: селектор не сработал {css}: {e}")
    debug_log(f"click_first_visible: не найден видимый элемент для {role}: {selectors}")
    return False

def check_error_banner(page: Page, preset: dict) -> None:
    """
    Порт v3 detect_rate_limit_error: >=2 групп маркеров из пресета
    (rate_limit.marker_groups) в видимом тексте + отсутствие контента
    => RuntimeError. Группы в пресете, не в коде.
    """
    groups = preset.get("rate_limit", {}).get("marker_groups", [])
    if not groups:
        return
    try:
        text = (page.inner_text("body") or "").lower()
    except Exception as e:
        debug_log(f"check_error_banner: не удалось прочитать текст: {e}")
        return
    matched = sum(1 for group in groups if any(kw in text for kw in group))
    if matched < 2:
        return
    # Контекстная проверка: есть ли вообще контент (иначе это баннер, а не страница)
    sel = preset.get("selectors", {})
    has_content = any(
        sel.get(role) and locate(page, sel.get(role)).count() > 0
        for role in ("image_selector", "text_selector")
    )
    if has_content:
        return
    save_debug_html(page, "error_banner")
    raise RuntimeError(
        f"Похоже на баннер ошибки/лимита запросов (совпало групп: {matched}). "
        "Смотри дамп debug_error_banner_*.html, подожди и повтори."
    )

def post_nav_checks(page: Page, preset: dict) -> None:
    """Вызывается после ЛЮБОГО перехода: закрыть попапы, проверить баннер ошибки."""
    dismiss_popups(page, preset)
    check_error_banner(page, preset)

def save_debug_html(page: Page, name: str) -> None:
    """Сохраняет HTML-дамп страницы для отладки."""
    try:
        from core.logger import is_debug_mode
        if is_debug_mode():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', '_', name)
            dump_path = Path(f"debug_{safe_name}_{timestamp}.html")
            dump_path.write_text(page.content(), encoding="utf-8")
            debug_log(f"[DEBUG] HTML-дамп сохранён: {dump_path}")
    except Exception as e:
        debug_log(f"[DEBUG] Не удалось сохранить HTML-дамп: {e}")

def _wait_for_manual_inspection(page: Page, message: str) -> None:
    """В headed-режиме ждёт ENTER от пользователя для проверки селекторов."""
    from core.logger import is_debug_mode
    if is_debug_mode():
        # Проверяем, запущен ли браузер в headed-режиме
        try:
            # Пытаемся определить headed через контекст
            # Это хак, но другого способа нет
            print(f"\n{'='*60}")
            print(f"[MANUAL] {message}")
            print("Проверьте селекторы в окне браузера.")
            print("Нажмите ENTER в консоли, чтобы продолжить...")
            print(f"{'='*60}\n")
            input()
        except Exception:
            pass

def _ext_from_url(url: str) -> str:
    """Расширение из пути URL; всё вне белого списка становится .jpg
    (защищает от query-строк вида 05.jpg?token=...)."""
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"} else ".jpg"

def cleanup_chapter_temps(target_folder: Path, volume, number, ranobe: bool = False) -> int:
    """
    Удаляет осиротевшие .tmp-папки ПРОВАЛЬНОЙ главы.
    ranobe=True: только .tmp_ranobe_{vol}_{num}_* (том в имени защищает
    буферные папки успешных глав до сборки EPUB).
    ranobe=False: только .tmp_ch_{num}_web_*/_page_* (у манги темп живёт
    лишь внутри попытки, чужие успешные главы зацепить невозможно).
    """
    vol = volume or 1   # зеркалит «meta.get("volume") or 1» из collect_chapter_ranobe
    patterns = (
        (f".tmp_ranobe_{vol:g}_{number:g}_*",) if ranobe else
        (f".tmp_ch_{number:g}_web_*", f".tmp_ch_{number:g}_page_*")
    )
    removed = 0
    for pat in patterns:
        for d in target_folder.glob(pat):
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
                debug_log(f"cleanup_chapter_temps: удалена осиротевшая {d.name}")
    return removed

def is_valid_src(src: str, preset: Optional[dict] = None) -> bool:
    """
    Проверяет, что src не является пустым или мусорным (blob:, data:, заглушки).
    Именные баны матчатся ТОЛЬКО целыми токенами имени файла,
    чтобы не зацепить легитимные файлы вида "...gigapixel...".
    Плюс проверкa пути на запрещённые подстроки из пресета (banned_paths).
    """
    if not src:
        return False
    low = src.lower()
    for scheme in ("blob:", "javascript:", "data:", "image:"):
        if scheme in low:
            return False
    path = urlparse(src).path.lower()
    stem = path.rsplit("/", 1)[-1]
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    tokens = {t for t in re.split(r"[^a-z0-9]+", stem) if t}
    if tokens & {"placeholder", "empty", "missing", "pixel",
                 "transparent", "spacer", "blank", "dummy"}:
        return False
    try:
        if preset:
            banned_paths = preset.get("banned_paths", [])
            if isinstance(banned_paths, str):
                banned_paths = [banned_paths]
            if any(b.lower() in path for b in banned_paths):
                return False
    except Exception:
        pass
    return True

def locate(page: Page, selector: str) -> Locator:
    """Универсальный локатор: поддерживает CSS и XPath (если начинается с xpath= или /)."""
    if selector.startswith("xpath=") or selector.startswith("/"):
        return page.locator(selector)
    return page.locator(selector)

def selector_css(preset: dict, role: str, default=None):
    """Селектор из пресета одной CSS-строкой; значение может быть str или списком."""
    val = preset.get("selectors", {}).get(role, default)
    if isinstance(val, (list, tuple)):
        return ", ".join(v for v in val if v)
    return val

def _tpl_to_regex(tpl: str) -> str:
    """Шаблон 'Том {volume} Глава {number}' → регекс с именованными группами."""
    tpl = tpl.strip()
    out = ""
    for part in re.split(r"{(volume|number)}", tpl):
        out += rf"(?P<{part}>\d+(?:\.\d+)?)" if part in ("volume", "number") else re.escape(part)
    return out


def _tpl_list(preset: dict) -> list:
    """meta_text_template: строка или список строк → список шаблонов."""
    tpl = preset.get("meta", {}).get("meta_text_template")
    if isinstance(tpl, str):
        return [tpl] if tpl.strip() else []
    return [t for t in (tpl or []) if isinstance(t, str) and t.strip()]


def _tpl_match(tpl: str, text: str):
    """Шаблон по тексту → (volume|None, number) или None.
    Шаблон без {volume} валиден (volume=None)."""
    try:
        m = re.search(_tpl_to_regex(tpl), text or "")
    except Exception:
        return None
    if not m:
        return None
    vol = m.groupdict().get("volume")
    num = m.groupdict().get("number")
    if num is None:
        return None
    return (float(vol) if vol is not None else None, float(num))


def _identity_from_text(page, preset):
    sel = preset.get("meta", {}).get("meta_text_selector")
    tpls = _tpl_list(preset)
    debug_log(f"_identity_from_text: sel={sel}, tpl={tpls}")
    if not sel:
        debug_log("_identity_from_text: нет sel в пресете")
        return None
    try:
        nav = preset.get("selectors", {}).get("navbar_hover_selector")
        if nav:
            try:
                page.hover(nav, timeout=1500)
            except Exception:
                pass
        loc = locate(page, sel)
        if loc.count() == 0:
            debug_log(f"_identity_from_text: селектор {sel} не найден")
            return None
        text = (loc.first.text_content() or "").strip()
        debug_log(f"_identity_from_text: прочитано '{text}'")
        for t in tpls:
            ident = _tpl_match(t, text)
            if ident:
                vol, num = ident
                debug_log(f"_identity_from_text: шаблон '{t}' → ({vol}, {num})")
                return (vol if vol is not None else 0.0, num)
        debug_log("_identity_from_text: ни один шаблон не сматчил")
        # data-num/data-vol — только если пресет разрешил ключом meta.data_num_scale
        scale = preset.get("meta", {}).get("data_num_scale")
        if scale:
            try:
                dv = loc.first.evaluate(
                    "el => { const w = el.closest('[data-num]') || el; "
                    "return [w.getAttribute('data-num'), w.getAttribute('data-vol')]; }"
                )
                if dv and dv[0] is not None:
                    return (float(dv[1] or 0), float(dv[0]) / float(scale))
            except Exception:
                pass
        return None
    except Exception as e:
        debug_log(f"_identity_from_text: исключение {e}")
        return None


def read_chapter_meta(page, preset, url: str) -> dict:
    """Мета текущей главы: текст-шаблон приоритетнее URL-регексов."""
    ident = _identity_from_text(page, preset)
    if ident:
        return {"volume": ident[0], "number": ident[1], "name": "", "url": url}
    meta = extract_chapter_meta(page, preset, url)
    meta["url"] = url
    return meta

def _wait_image_loaded(page: Page, el, timeout_s: Optional[float] = None,
                       sleep_s: float = IMG_WAIT_SLEEP_S,
                       preset: Optional[dict] = None,
                       chapter_number: Optional[float] = None,
                       page_idx: Optional[int] = None) -> Tuple[Optional[str], bool]:
    """
    Ждёт, пока картинка реально загрузится в кэш браузера (complete && naturalWidth > 0).
    Проверяет и валидный src (не заглушку через is_valid_src), и факт загрузки.
    Если в пресете задан lazy_attr, сначала пробует его, потом src.
    Агрессивная нормализация: любой не-http путь → абсолютный через urljoin.

    Args:
        timeout_s: Если число — ждать фиксированное время (для быстрой фазы в веб).
                   Если None — ждать до победного.
        chapter_number, page_idx: для предупреждений image_slow / chapter_slow.

    Возвращает (валидный_src_или_None, загрузилась_или_нет).
    Переиспользуется в веб, паге и ранобэ.
    """
    lazy_attr = preset.get("selectors", {}).get("lazy_attr") if preset else None
    start = time.monotonic()
    warned = False

    while True:
        # Сначала пробуем lazy_attr (если задан), потом src
        src = None
        if lazy_attr:
            src = el.get_attribute(lazy_attr)
        if not src or not src.startswith("http"):
            src = el.get_attribute("src")
        # Агрессивная нормализация: любой не-http путь → абсолютный
        if src and not src.startswith("http"):
            src = urljoin(page.url, src)
        if src and src.startswith("http"):
            if is_valid_src(src, preset):
                try:
                    loaded = el.evaluate("el => el.complete && el.naturalWidth > 0")
                    if loaded:
                        return src, True
                except Exception:
                    pass
            else:
                # src абсолютный, но забанен (заглушка) — ждать бесполезно
                debug_log(f"_wait_image_loaded: заглушка вместо картинки: {src}")
                return src, False

        elapsed = time.monotonic() - start
        # Фиксированный таймаут (для быстрой фазы в веб)
        if timeout_s is not None and elapsed >= timeout_s:
            return src, False

        # Опрос главы: флаг таймера → emit из main-потока (работает даже при зависании)
        _check_chapter_slow(chapter_number)
        # Однократное предупреждение по текущей странице
        if not warned and elapsed >= IMG_WAIT_LONG_S:
            warned = True
            debug_log(f"_wait_image_loaded: картинка грузится дольше {IMG_WAIT_LONG_S:.0f}с, продолжаем ждать")
            emit_event("image_slow",
                       chapter_number=chapter_number,
                       page=page_idx + 1 if page_idx is not None else None,
                       message=f"Картинка грузится дольше {IMG_WAIT_LONG_S:.0f} секунд, но программа продолжает ждать")

        time.sleep(sleep_s)

def scroll_and_load_images(page, preset, img_sel, urls, number, expected_pages):
    """
    Постраничный скролл ленты с дожиданием загрузки каждой картинки.
    Схема «2.5 прохода»:
      Проход 1   — быстрое ожидание (IMG_WAIT_QUICK_S) каждой картинки.
      Проход 1.5 — повторное быстрое ожидание только незагруженных (ДО reload).
      Проход 2   — ОДИН мягкий ретрай (page.reload) на главу для оставшихся:
                   полный цикл наращивания, проверка/поиск src, долгое ожидание
                   до победного. Уведомления — только здесь, через внутреннее
                   предупреждение _wait_image_loaded (однократно).
    Возвращает (final_count, unloaded_indices).
    """
    # Фаза 0: наращиваем DOM (бесконечный скролл)
    final_count = scroll_grow(page, img_sel, expected=expected_pages, on_round=None)
    scroll_to_top(page)

    src_index: dict = {}  # src → индекс страницы в DOM: порядок по страницам, а не по времени загрузки

    def _collect(src, idx) -> bool:
        """Добавляет валидный src в urls и шлёт событие прогресса."""
        if src and src.startswith("http") and src not in urls:
            urls.append(src)
            src_index[src] = idx
            emit_event("page_saved",
                       chapter_number=number,
                       page=idx + 1,
                       total_pages=expected_pages or final_count)
            return True
        return False

    def _quick_pass(indices):
        """Быстрый проход по индексам: ждёт IMG_WAIT_QUICK_S на элемент.
        Возвращает список индексов, которые так и не загрузились."""
        loc = locate(page, img_sel)
        total = loc.count()
        not_loaded = []
        for i in indices:
            if i >= total:
                not_loaded.append(i)
                continue
            el = loc.nth(i)
            try:
                el.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            src, loaded = _wait_image_loaded(page, el, IMG_WAIT_QUICK_S, preset=preset,
                                             chapter_number=number, page_idx=i)
            if loaded and _collect(src, i):
                pass
            else:
                not_loaded.append(i)
        return not_loaded

    # Проход 1: все элементы
    loc = locate(page, img_sel)
    total = loc.count()
    unloaded = _quick_pass(list(range(total)))

    # Страница-заглушка целиком (например, deleted на allhen при прямой ссылке):
    # ВСЕ картинки не загрузились, и первая имеет забаненный статичный src.
    # Ретрай бесполезен — выходим без проходов 1.5 и 2.
    if len(unloaded) == total and total > 0:
        first_src = loc.nth(0).get_attribute("src") or ""
        if first_src and not first_src.startswith("http"):
            first_src = urljoin(page.url, first_src)
        if first_src and not is_valid_src(first_src, preset):
            debug_log(f"scroll_and_load_images: все {total} картинок заглушки (первая: {first_src}) — ретрай бесполезен")
            return final_count, unloaded, src_index
    ran_pass15 = False
    # Проход 1.5: только незагруженные (до reload)
    if unloaded:
        ran_pass15 = True
        debug_log(f"scroll_and_load_images: проход 1.5 — {len(unloaded)} шт. не загрузились, повторяем без reload")
        unloaded = _quick_pass(unloaded)
    else:
        debug_log(f"Все загрузилось с первого прохода")

    # Проход 2: один мягкий ретрай на главу для оставшихся
    if unloaded:
        debug_log(f"scroll_and_load_images: {len(unloaded)} шт. не загрузились за 2 прохода — мягкий ретрай (reload)")
        try:
            page.reload(timeout=20000, wait_until="domcontentloaded")
            post_nav_checks(page, preset)
        except Exception as e:
            debug_log(f"scroll_and_load_images: reload не удался: {e}")

        # Полный цикл наращивания после релоада (для бесконечного скролла),
        # чтобы сопоставить индексы и докачать только недостающие
        final_count = scroll_grow(page, img_sel, expected=expected_pages, on_round=None)
        scroll_to_top(page)

        loc = locate(page, img_sel)
        total = loc.count()
        still = []
        for i in unloaded:
            if i >= total:
                debug_log(f"scroll_and_load_images: индекс {i} исчез после reload (всего {total})")
                still.append(i)
                continue
            el = loc.nth(i)
            try:
                el.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            # Долгое ожидание до победного.
            # Уведомление сработает однократно через IMG_WAIT_LONG_S
            # (внутреннее предупреждение _wait_image_loaded).
            # Заглушка вернёт (src, False) сразу благодаря проверке в _wait_image_loaded.
            src, loaded = _wait_image_loaded(page, el, timeout_s=None, preset=preset,
                                             chapter_number=number, page_idx=i)
            if loaded and _collect(src, i):
                pass
            else:
                still.append(i)
        unloaded = still
    elif ran_pass15:
        debug_log(f"Все загрузилось с прохода 1.5")

    # Восстанавливаем порядок страниц: urls наполнялся по времени загрузки,
    # а архив должен собираться по порядку индексов DOM.
    if src_index:
        urls.sort(key=lambda u: src_index.get(u, -1))
    return final_count, unloaded, src_index
        
def scroll_grow(page, selector: str, expected=None, max_rounds: int = 500,
                on_round=None) -> int:
    """
    Универсальный скролл ленты: hover последнего элемента + wheel(0, 500),
    пока count не стабилизируется (3 тихих раунда; 6, если задан expected,
    но не достигнут) или не достигнет expected.
    on_round(loc, count) — хук каждого раунда (инкрементальный сбор).
    Возвращает финальное число элементов.
    """
    prev_count = -1
    stable = 0
    final = 0
    for _ in range(max_rounds):
        loc = locate(page, selector)
        count = loc.count()
        final = count
        if on_round:
            on_round(loc, count)
        if expected and count >= expected:
            debug_log(f"scroll_grow: достигнут expected ({expected}), стоп")
            break
        if count > 0:
            try:
                loc.nth(count - 1).hover(timeout=250)
                page.mouse.wheel(0, 500)
            except Exception:
                page.mouse.wheel(0, 500)
        time.sleep(0.2)
        if count == prev_count:
            stable += 1
            if stable >= (6 if expected and count < expected else 3):
                break
        else:
            stable = 0
        prev_count = count
    return final

def scroll_to_top(page: Page) -> None:
    """Поднимает страницу в самый верх: сайт помнит позицию чтения,
    а скрытый навбар выезжает только у верха."""
    try:
        page.keyboard.press("Home")
    except Exception:
        pass
    time.sleep(0.7)

def ensure_mode(page: Page, preset: dict, mode: str) -> None:
    """
    Переключает режим чтения через обычные клики Playwright.
    Паттерн: если селектор есть в пресете — используем. Если нет — пропускаем.
    Никакого JS, никакого force=True, никаких mouse.move.
    """
    if mode in _mode_attempts:
        return
    _mode_attempts.add(mode)

    if mode not in ("web", "page"):
        debug_log(f"ensure_mode: неизвестный режим {mode}, пропускаем")
        return

    sel = preset.get("selectors", {})
    toggle_sel = sel.get("web_mode_toggle") if mode == "web" else sel.get("page_mode_toggle")
    
    # Паттерн: нет тумблера для режима → пропускаем
    if not toggle_sel:
        debug_log(f"ensure_mode: нет тумблера для mode={mode} в пресете")
        return

    # Паттерн: если есть navbar_hover_selector → hover для пробуждения навбара
    # Playwright .hover() сам делает scrollIntoViewIfNeeded и наводит мышь
    navbar_sel = sel.get("navbar_hover_selector")
    if navbar_sel:
        try:
            nav_loc = page.locator(navbar_sel).first
            if nav_loc.count() > 0:
                nav_loc.hover(timeout=3000)
                debug_log(f"ensure_mode: hover на navbar ({navbar_sel})")
                time.sleep(0.7)
        except Exception as e:
            debug_log(f"ensure_mode: hover на navbar не удался: {e}")

    # Паттерн: если есть settings_button → hover + click
    settings_sel = preset.get("selectors", {}).get("settings_button")
    if not click_first_visible(page, settings_sel, "settings_button", timeout=3000):
        save_debug_html(page, "ensure_mode_settings_FAIL")
        raise RuntimeError("Не удалось открыть настройки ридера")
    # Меню настроек: ждём видимость тумблера. Повторный клик по settings не нужен:
    # клик уже выполнен click_first_visible, а открытая модалка перехватывает указатель.
    try:
        page.locator(toggle_sel).first.wait_for(state="visible", timeout=3000)
        debug_log("ensure_mode: меню настроек появилось")
    except Exception:
        debug_log("ensure_mode: меню настроек не появилось за 3с")
        save_debug_html(page, "ensure_mode_menu_NOT_OPENED")
    # Паттерн: ОДИН клик по тумблеру через click_first_visible
    toggle_key = "web_mode_toggle" if mode == "web" else "page_mode_toggle"
    toggle_sel = preset.get("selectors", {}).get(toggle_key)
    if not click_first_visible(page, toggle_sel, toggle_key, timeout=3000):
        save_debug_html(page, f"ensure_mode_{toggle_key}_FAIL")
        raise RuntimeError(f"Не удалось переключить режим: {mode}")
    debug_log(f"ensure_mode: клик по тумблеру mode={mode} OK")
    # Закрытие меню
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    # Reload для сайтов с отложенным применением (grouple)
    try:
        page.reload(timeout=20000, wait_until="domcontentloaded")
        debug_log("ensure_mode: страница перезагружена")
        time.sleep(1.0)
    except Exception as e:
        debug_log(f"ensure_mode: reload не удался: {e}")
    post_nav_checks(page, preset)

def extract_chapter_meta(page: Page, preset: dict, url: str) -> dict:
    meta = preset.get("meta", {})
    volume_regexes = meta.get("volume_regex", [])
    chapter_regexes = meta.get("chapter_num_regex", [])
    name_selector = meta.get("chapter_name_selector")
    
    # ЗАЩИТА: приводим к списку, если в пресете передали строку
    if isinstance(volume_regexes, str):
        volume_regexes = [volume_regexes]
    if isinstance(chapter_regexes, str):
        chapter_regexes = [chapter_regexes]

    volume = None
    number = None
    name = ""

    # Ищем том
    for pat in volume_regexes:
        m = re.search(pat, url)
        if m:
            try:
                val = m.group(1)
                volume = float(val) if '.' in val else int(val)
            except (ValueError, IndexError):
                pass
            break

    # Ищем номер главы
    for pat in chapter_regexes:
        m = re.search(pat, url)
        if m:
            try:
                val = m.group(1)
                number = float(val) if '.' in val else int(val)
            except (ValueError, IndexError):
                pass
            break

    if number is None:
        raise RuntimeError(f"Не удалось извлечь номер главы из URL: {url}")

    # Извлекаем название, если задан селектор
    if name_selector:
        try:
            loc = locate(page, name_selector)
            if loc.count() > 0:
                el = loc.first
                js = """
                (el) => {
                    let text = '';
                    for (let node of el.childNodes) {
                        if (node.nodeType === 3) {
                            text += node.textContent;
                        }
                    }
                    return text.trim();
                }
                """
                name = el.evaluate(js) or ""
                # Санитизация названия (как в старом коде)
                if name:
                    safe = "".join(c if c.isalnum() or c in ' _-.' else '_' for c in name).strip('_ ')
                    while '__' in safe:
                        safe = safe.replace('__', '_')
                    name = safe
        except Exception as e:
            debug_log(f"extract_chapter_meta: ошибка при извлечении названия: {e}")

    return {"volume": volume, "number": number, "name": name}

def extract_ranobe_content(page: Page, preset: dict) -> list:
    """
    Извлекает контент главы ранобэ в порядке следования.
    Возвращает список кортежей: [('text', "..."), ('img', src), ...]
    Селектор контейнера берётся из preset['selectors']['content_container'].
    Использует page.evaluate с JS-обходом (порт из ref).
    """
    container_sel = preset.get("selectors", {}).get("content_container")
    if not container_sel:
        debug_log("extract_ranobe_content: content_container не задан в пресете")
        return []

    # JS-код обхода (порт из ref)
    js = """
    (containerSelector) => {
        const container = document.querySelector(containerSelector);
        if (!container) return [];

        function walk(node, result) {
            if (node.nodeType === Node.ELEMENT_NODE) {
                if (node.tagName === 'P') {
                    const clone = node.cloneNode(true);
                    clone.querySelectorAll('*').forEach(el => {
                        if (el.tagName.includes('-')) el.remove();  // виджеты сайта (счётчики комментов и т.п.)
                    });
                    const text = clone.textContent.trim();
                    if (text) result.push(['text', text]);
                } else if (node.tagName === 'IMG') {
                    const src = node.src || node.getAttribute('data-src') || '';
                    result.push(['img', src]);
                }
                // Рекурсивно обходим всех потомков
                for (let child of node.childNodes) {
                    walk(child, result);
                }
            }
        }
        const result = [];
        walk(container, result);
        return result;
    }
    """
    try:
        raw_items = page.evaluate(js, container_sel)
    except Exception as e:
        debug_log(f"extract_ranobe_content: ошибка при выполнении JS: {e}")
        return []

    content = []
    for item in raw_items:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        item_type, value = item[0], item[1]
        if item_type == 'text' and value:
            content.append(('text', value))
        elif item_type == 'img':
            if value and not value.startswith("http"):
                value = urljoin(page.url, value)
            if value and is_valid_src(value, preset):
                content.append(('img', value))
    debug_log(f"extract_ranobe_content: извлечено {len(content)} элементов")
    return content

def collect_chapter_ranobe(
    page: Page,
    preset: dict,
    interceptor: 'ImageInterceptor',
    url: str,
    target_folder: Path,
    namer_config: dict
) -> Optional[dict]:
    """
    Собирает главу ранобэ в буферную запись; файл не собирает (текст + иллюстрации).
    Возвращает словарь-буфер для последующей сборки EPUB:
        {
            "title": "Том X, Глава Y",
            "html": "<p>...</p><img ...>",
            "images": [{"name": "ch1_v1_img001.jpg", "path": "/tmp/..."}],
            "temp_dir": "/tmp/..."
        }
    или None при ошибке.
    """
    meta = read_chapter_meta(page, preset, url)
    number = meta["number"]
    volume = meta.get("volume") or 1
    name = meta.get("name", "")

    container_sel = preset.get("selectors", {}).get("content_container")
    if not container_sel:
        debug_log("download_chapter_ranobe: content_container не задан в пресете")
        return None

    # Ждём появления контейнера
    container_found = False
    try:
        page.wait_for_selector(container_sel, timeout=10000)
        container_found = True
        debug_log("download_chapter_ranobe: контейнер контента загружен")
    except Exception as e:
        debug_log(f"download_chapter_ranobe: контейнер {container_sel} не найден (глава-иллюстрации?)")
        save_debug_html(page, f"ranobe_no_container_{number:g}")
    # Сбор URL картинок с прогрузкой (для глав-иллюстраций — фолбэк на image_selector)
    if container_found:
        img_scope = f"{container_sel} img"
        urls = []
        unloaded = []
        for idx, el in enumerate(locate(page, img_scope).all()):
            try:
                el.scroll_into_view_if_needed()
            except Exception:
                pass
            # Ждём реальную загрузку картинки в кэш браузера
            src, loaded = _wait_image_loaded(page, el, timeout_s=5.0, preset=preset,
                                            chapter_number=number, page_idx=idx)
            if src and src.startswith("http") and src not in urls:
                urls.append(src)
            if not loaded:
                unloaded.append(idx)
        
        # Дожим unloaded с большим таймаутом для гарантии
        if unloaded:
            debug_log(f"download_chapter_ranobe: {len(unloaded)} картинок не загрузились за 5с, дожим")
            loc = locate(page, img_scope)
            for idx in unloaded:
                if idx < loc.count():
                    el = loc.nth(idx)
                    src, loaded = _wait_image_loaded(page, el, timeout_s=15.0, preset=preset,
                                                    chapter_number=number, page_idx=idx)
                    if src and src.startswith("http") and src not in urls:
                        urls.append(src)
    else:
        # Глава без текста (иллюстрации): картинки отдаёт ридер через роль
        # image_selector из пресета; если есть постраничная навигация — фолбэк на page-режим.
        page_btn_sel = preset.get("selectors", {}).get("next_page_button")
        if page_btn_sel and locate(page, page_btn_sel).count() > 0:
            debug_log("download_chapter_ranobe: текста нет, но есть постраничная навигация — собираем как мангу (page-mode)")
            return download_chapter_page(
                page,
                preset,
                interceptor,
                url,
                target_folder,
                namer_config,
                as_buffer=True
            )

        img_scope = selector_css(preset, "image_selector")
        if not img_scope:
            debug_log("download_chapter_ranobe: нет ни текстового контейнера, ни image_selector в пресете")
            return None

        scroll_grow(page, img_scope, max_rounds=200)
        time.sleep(1.0)  # Задержка после скролла

        urls = []
        unloaded = []
        for idx, el in enumerate(locate(page, img_scope).all()):
            src, loaded = _wait_image_loaded(
                page,
                el,
                timeout_s=5.0,
                preset=preset,
                chapter_number=number,
                page_idx=idx
            )

            if src and src.startswith("http") and src not in urls:
                urls.append(src)

            if not loaded:
                unloaded.append(idx)

        # Дожим unloaded с большим таймаутом для гарантии
        if unloaded:
            debug_log(f"download_chapter_ranobe: {len(unloaded)} картинок не загрузились за 5с, дожим")
            loc = locate(page, img_scope)
            for idx in unloaded:
                if idx < loc.count():
                    el = loc.nth(idx)
                    src, loaded = _wait_image_loaded(
                        page,
                        el,
                        timeout_s=15.0,
                        preset=preset,
                        chapter_number=number,
                        page_idx=idx
                    )

                    if src and src.startswith("http") and src not in urls:
                        urls.append(src)
    urls = [u for u in urls if is_valid_src(u, preset)]
    # Дожим ленивых картинок перед перехватом.
    # Это нужно для сайтов, где последние изображения уже есть в DOM,
    # но запрос на загрузку начинается только после реального попадания в видимую область.
    try:
        for el in locate(page, img_scope).all():
            try:
                el.scroll_into_view_if_needed()
                time.sleep(0.15)
            except Exception:
                pass

        if locate(page, img_scope).count() > 0:
            time.sleep(1.5)
    except Exception:
        pass

    debug_log(f"download_chapter_ranobe: собрано {len(urls)} URL картинок")

    # Перехват картинок
    result = interceptor.collect(urls) if urls else {}

    # Один повтор для недозагруженных хвостов.
    # Если часть картинок не пришла, ещё раз показываем изображения браузеру
    # и ждём только недостающие URL.
    missing = [u for u in urls if u not in result]
    if missing:
        debug_log(f"download_chapter_ranobe: с первой попытки не получено {len(missing)} картинок, повторный дожим")

        try:
            for el in locate(page, img_scope).all():
                try:
                    el.scroll_into_view_if_needed()
                    time.sleep(0.25)
                except Exception:
                    pass

            time.sleep(2.0)
        except Exception:
            pass

        extra = interceptor.collect(missing)
        result.update(extra)

        still_missing = [u for u in missing if u not in extra]
        if still_missing:
            debug_log(f"download_chapter_ranobe: после повторного дожима не получены: {still_missing}")

    # Извлекаем контент (текст + img)
    if container_found:
        content = extract_ranobe_content(page, preset)
    else:
        # Глава-иллюстрация: текста нет, строим контент только из собранных картинок
        content = [('img', src) for src in urls]
    if not content:
        debug_log("download_chapter_ranobe: контент пуст")
        return None

    # Создаём временную папку
    temp_dir = target_folder / f".tmp_ranobe_{volume:g}_{number:g}_{random.randint(100,999)}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    html_parts = []
    images_meta = []
    img_counter = 0
    img_pos = 0
    missing_positions = []

    for item_type, value in content:
        if item_type == 'text':
            html_parts.append(f'<p>{value}</p>')
        elif item_type == 'img':
            # Проверяем, есть ли байты для этого URL
            img_pos += 1
            if value in result:
                ext = _ext_from_url(value)
                img_counter += 1
                fname = f"ch{number:g}_v{volume:g}_img{img_counter:03d}{ext}"
                local_path = temp_dir / fname
                local_path.write_bytes(result[value])
                images_meta.append({"name": fname, "path": str(local_path)})
                html_parts.append(
                    f'<img src="images/{fname}" style="max-width:100%;display:block;margin:10px auto;">'
                )
            else:
                missing_positions.append(img_pos)
                debug_log(f"download_chapter_ranobe: байты для {value} не получены, пропускаем")

    if missing_positions:
        emit_event("chapter_incomplete",
                chapter_number=number,
                saved=True,
                message=(f"Глава {number} (том {volume}): {len(images_meta)} из {img_pos} иллюстраций, "
                         f"не получены: {missing_positions}"))

    if not html_parts:
        debug_log("download_chapter_ranobe: не сформировано HTML-содержимое")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None

    title = f"Том {volume}, Глава {number}"
    if name:
        title += f" — {name}"

    return {
        "title": title,
        "html": "\n".join(html_parts),
        "images": images_meta,
        "temp_dir": str(temp_dir)
    }

def _warm_via_own_link(page: Page, preset: dict) -> bool:
    """
    Самолечение «холодной» страницы: перезаходим на главу кликом по её же
    ссылке в оглавлении (некоторые сайты отдают заглушки при прямом заходе).
    """
    cur = page.url
    parts = urlparse(cur)
    candidates = [cur, parts.path + (f"?{parts.query}" if parts.query else "")]
    for href in candidates:
        loc = page.locator(f'a[href="{href}"]')
        for idx in range(min(loc.count(), 5)):
            el = loc.nth(idx)
            try:
                if not el.is_visible():
                    continue
                try:
                    el.scroll_into_view_if_needed(timeout=1000)
                except Exception:
                    pass
                el.click(timeout=3000)
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                debug_log(f"_warm_via_own_link: перезашли через ссылку оглавления ({href})")
                post_nav_checks(page, preset)
                return True
            except Exception:
                continue
    debug_log("_warm_via_own_link: своя ссылка главы на странице не найдена")
    return False

def download_chapter_web(
    page: Page,
    preset: dict,
    interceptor: 'ImageInterceptor',
    url: str,
    target_folder: Path,
    namer_config: dict,
    pages: Optional[Tuple[int, int]] = None,
    save_as_cbz: bool = True
) -> Optional[Path]:
    """
    Скачивание главы в web-режиме (лента).
    Порт scroll_and_download_iterative.
    """
    meta = read_chapter_meta(page, preset, url)
    number = meta["number"]
    volume = meta["volume"]
    name = meta["name"]

    dismiss_popups(page, preset)
    scroll_to_top(page)
    ensure_mode(page, preset, "web")
    scroll_to_top(page)

    # Сбор URL картинок из DOM
    img_sel = selector_css(preset, "image_selector")
    debug_log(f"download_chapter_web: image_selector = {img_sel}")

    # Определяем ожидаемое количество страниц (если есть в metadata)
    expected_pages = None
    try:
        page_select_sel = selector_css(preset, "page_select")
        if page_select_sel:
            select = locate(page, page_select_sel).first
            if select.count() > 0:
                opts = [opt.get_attribute("value") for opt in select.locator("option").all()]
                if opts:
                    expected_pages = len(opts)
                    debug_log(f"download_chapter_web: ожидаемое количество страниц из page_select: {expected_pages}")
    except Exception as e:
        debug_log(f"download_chapter_web: не удалось получить ожидаемое количество страниц: {e}")

    urls = []

    # Фаза 1: наращиваем DOM на случай бесконечного скролла + сбор URL с ожиданием.
    # 2.5 прохода внутри: quick → quick по незагруженным → reload + долгая загрузка.
    final_count, unloaded_idx, src_index = scroll_and_load_images(page, preset, img_sel, urls, number, expected_pages)
    debug_log(f"download_chapter_web: после скролла в DOM {final_count} элементов, загружено {len(urls)}, не загрузилось {len(unloaded_idx)}")

    if not urls:
        # Различаем заглушку (забаненный src) и «холодную» страницу (относительный src)
        raw_src = ""
        try:
            first_loc = locate(page, img_sel).first
            if first_loc.count() > 0:
                raw_src = first_loc.get_attribute("src") or ""
        except Exception:
            pass
        first_src = raw_src if raw_src.startswith("http") else (urljoin(page.url, raw_src) if raw_src else "")
        if first_src and not is_valid_src(first_src, preset):
            debug_log(f"download_chapter_web: глава {number} — заглушки ({first_src}), не сохраняем")
            emit_event("chapter_incomplete",
                    chapter_number=number,
                    expected=expected_pages or final_count,
                    downloaded=0,
                    message=f"Глава {number}: сервер отдал заглушки вместо страниц, контент недоступен")
            return None
        # Подозрение на «холодную» страницу: src относительный, но не забанен
        if raw_src and not raw_src.startswith("http") and _warm_via_own_link(page, preset):
            urls.clear()
            final_count, unloaded_idx, src_index = scroll_and_load_images(page, preset, img_sel, urls, number, expected_pages)
            debug_log(f"download_chapter_web: после прогрева собрано {len(urls)} валидных URL")
    if not urls:
        debug_log("download_chapter_web: не найдено URL изображений")
        return None
    # Site-agnostic предохранитель: любая непрогруженная после ретрая страница
    # = глава неполная. Закрывает случай дублей заглушек и тихое частичное сохранение.
    if unloaded_idx:
        debug_log(f"download_chapter_web: {len(unloaded_idx)} стр. не загрузились после ретрая — сохраним без них")
    # Опрос главы после всех фаз скролла (включая warm):
    # флаг мог подняться там, где нет цикла ожидания картинок.
    _check_chapter_slow(number)
    # Ожидание исчезновения индикатора загрузки
    loading_sel = preset.get("selectors", {}).get("loading_indicator")
    interceptor.wait_loading_complete(loading_sel, timeout_ms=3000)

    # Перехват картинок из кэша браузера
    result = interceptor.collect(urls)
    debug_log(f"download_chapter_web: interceptor вернул {len(result)} из {len(urls)} картинок")

    # Фильтр по страницам (если заданы)
    urls_filtered = urls
    if pages:
        start, end = pages
        if start is not None and end is not None:
            urls_filtered = urls[start-1:end]

    if not urls_filtered:
        debug_log("download_chapter_web: после фильтрации страниц нет изображений")
        return None

    # Создаём временную папку
    temp_dir = target_folder / f".tmp_ch_{number:g}_web_{random.randint(100,999)}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    success = 0
    for i, img_url in enumerate(urls_filtered):
        fname = f"page_{i+1:03d}{_ext_from_url(img_url)}"
        data = result.get(img_url)
        if data is None:
            debug_log(f"download_chapter_web: не получены данные для {img_url}")
            continue
        (temp_dir / fname).write_bytes(data)
        success += 1

    if success == 0:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None

    # Строгая проверка: сравниваем с expected_pages (если есть) или с urls_filtered
    expected = expected_pages or final_count
    saved_pages = {src_index.get(u, -1) + 1 for u in urls_filtered if u in result}
    missing_pages = sorted(set(range(1, expected + 1)) - saved_pages)
    if missing_pages:
        debug_log(f"download_chapter_web: ⚠️ пропущены страницы {missing_pages} ({success}/{expected})")
        emit_event("chapter_incomplete",
                chapter_number=number,
                expected=expected,
                downloaded=success,
                saved=True,
                message=(f"Глава {number}: сохранено {success} из {expected} страниц. "
                         f"Пропущены страницы номер: {', '.join(map(str, missing_pages))}"))
        
    emit_event("chapter_finalizing",
            chapter_number=number,
            message="Сборка CBZ..." if save_as_cbz else "Сохранение файлов...")
    chapter_name = generate_chapter_name(volume, number, name, namer_config)
    return finalize_chapter_output(temp_dir, target_folder, chapter_name, save_as_cbz)

@overload
def download_chapter_page(page: Page, preset: dict, interceptor: 'ImageInterceptor',
                          url: str, target_folder: Path, namer_config: dict,
                          pages: Optional[Tuple[int, int]] = None, save_as_cbz: bool = True,
                          *, as_buffer: Literal[True]) -> Optional[dict]: ...
@overload
def download_chapter_page(page: Page, preset: dict, interceptor: 'ImageInterceptor',
                          url: str, target_folder: Path, namer_config: dict,
                          pages: Optional[Tuple[int, int]] = None, save_as_cbz: bool = True,
                          *, as_buffer: Literal[False] = False) -> Optional[Path]: ...

def download_chapter_page(
    page: Page,
    preset: dict,
    interceptor: 'ImageInterceptor',
    url: str,
    target_folder: Path,
    namer_config: dict,
    pages: Optional[Tuple[int, int]] = None,
    save_as_cbz: bool = True,
    *,
    as_buffer: bool = False
):
    """
    Скачивание главы в постраничном режиме.
    Порт _download_manga_chapter + get_total_pages.
    """
    meta = read_chapter_meta(page, preset, url)
    number = meta["number"]
    volume = meta["volume"]
    name = meta["name"]

    scroll_to_top(page)
    ensure_mode(page, preset, "page")

    # Определяем общее число страниц.
    # ВАЖНО: div[data-page] на части сайтов (zazaza, page-режим) — это обёртки
    # блоков комментариев, а не плейсхолдеры страниц, поэтому сначала селекты.
    total_pages = None
    src_method = None
    page_select_sel = preset.get("selectors", {}).get("page_select")
    default_select_sel = "div.pager-control.standard-section select.page-selector, select.page-selector"
    try:
        page.wait_for_selector(page_select_sel or default_select_sel, timeout=8000)
    except Exception:
        pass
    # 1) опции селектора страниц (пресет, затем дефолт семейства grouple/zazaza)
    for sel in (page_select_sel, default_select_sel):
        if not sel or total_pages:
            continue
        try:
            opts = locate(page, sel).first.locator("option").all()
            nums = [int(v) for v in (o.get_attribute("value") for o in opts)
                        if v and v.isdigit()]
            if nums:
                total_pages = len(nums)
                src_method = f"select options ({sel})"
        except Exception:
            pass
    # 2) текстовый счётчик страниц
    if not total_pages:
        try:
            txt = (locate(page, "span.pages-count").first.text_content() or "").strip()
            if txt.isdigit():
                total_pages = int(txt)
                src_method = "span.pages-count"
        except Exception:
            pass
    # 3) последний резерв: ТОЛЬКО плейсхолдеры страниц, не контейнеры комментариев
    if not total_pages:
        try:
            data_pages = page.eval_on_selector_all(
                "div.manga-img-placeholder[data-page]",
                "els => els.map(el => parseInt(el.dataset.page)).filter(v => !isNaN(v))"
            )
            if data_pages:
                debug_log(f"download_chapter_page: div[data-page]: n={len(data_pages)}, min={min(data_pages)}, max={max(data_pages)}")
                total_pages = max(data_pages) - min(data_pages) + 1
                src_method = "div.manga-img-placeholder[data-page]"
        except Exception:
            pass
    if not total_pages or total_pages < 1:
        raise RuntimeError("Не удалось определить total_pages")
    debug_log(f"download_chapter_page: total_pages = {total_pages} (способ: {src_method})")
        
    # Определяем диапазон страниц для скачивания
    start_page = 1
    end_page = total_pages
    if pages:
        start_page, end_page = pages
    # Клиппим
    start_page = max(1, start_page)
    end_page = min(total_pages, end_page)
    if start_page > end_page:
        debug_log("download_chapter_page: start_page > end_page, пропуск")
        return None
    
    # Логируем селекторы
    img_sel = selector_css(preset, "image_selector")
    debug_log(f"download_chapter_page: image_selector = {img_sel}")
    
    # Проверяем, есть ли вообще картинки на странице
    try:
        img_count = locate(page, img_sel).count()
        debug_log(f"download_chapter_page: найдено {img_count} элементов по image_selector")
        if img_count == 0:
            save_debug_html(page, "page_mode_no_images")
            _wait_for_manual_inspection(page, f"Селектор '{img_sel}' не нашёл ни одного элемента!")
    except Exception as e:
        debug_log(f"download_chapter_page: ошибка при проверке image_selector: {e}")
    
    # Временная папка
    temp_dir = target_folder / f".tmp_ch_{number:g}_page_{random.randint(100,999)}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Селекторы
    img_sel = selector_css(preset, "image_selector")
    if not img_sel:
        raise RuntimeError("В пресете отсутствует image_selector")
    next_btn_sel = preset.get("selectors", {}).get("next_page_button")
    page_select_sel = preset.get("selectors", {}).get("page_select")

    downloaded = 0
    fails = 0
    skipped_pages: list = []
    current_page = start_page
    buf_prefix = f"ch{number:g}_v{(volume if volume is not None else 1):g}_" if as_buffer else ""

    # Функция для ожидания реального src
    # Функция для ожидания реальной загрузки картинки (использует единую _wait_image_loaded)
    def wait_for_img_src():
        img_sel = selector_css(preset, "image_selector")
        try:
            loc = locate(page, img_sel).first
            for _ in range(16):   # даём странице отрисовать <img> (~8с)
                if loc.count() > 0:
                    break
                time.sleep(0.5)
            if loc.count() > 0:
                # Скроллим элемент в видимость, чтобы триггернуть загрузку
                try:
                    loc.scroll_into_view_if_needed()
                except Exception:
                    pass
                # Ждём реальную загрузку до победного
                src, loaded = _wait_image_loaded(page, loc, timeout_s=None, preset=preset,
                                                 chapter_number=number, page_idx=current_page - 1)
                if loaded:
                    return src
                debug_log("wait_for_img_src: картинка не загрузилась (заглушка) — src не отдаём")
                return None
        except Exception as e:
            debug_log(f"wait_for_img_src: исключение: {e}")
        return None

    def goto_next_page() -> bool:
        """Следующая страница штатными средствами сайта:
        next_page_button → page_select → JS-клик (последнее средство).
        Без goto: код не знает URL-шаблоны страниц сайта."""
        if next_btn_sel:
            before_url = page.url
            try:
                btn = locate(page, next_btn_sel).first
                if btn.count() > 0 and btn.is_enabled():
                    btn.click(timeout=3000)
                    time.sleep(2)
                    if page.url != before_url:
                        wait_for_img_src()
                        return True
            except Exception as e:
                debug_log(f"download_chapter_page: ошибка при клике по next_page_button: {e}")
        if page_select_sel:
            try:
                select = locate(page, page_select_sel).first
                if select.count() > 0:
                    values = [opt.get_attribute("value")
                              for opt in select.locator("option").all()
                              if opt.get_attribute("value")]
                    current_val = select.input_value()
                    idx = values.index(current_val) if current_val in values else -1
                    if 0 <= idx + 1 < len(values):
                        select.select_option(value=values[idx + 1])
                        wait_for_img_src()
                        return True
            except Exception as e:
                debug_log(f"download_chapter_page: ошибка при работе с page_select: {e}")
        return False
    
    while current_page <= end_page:
        img_src = wait_for_img_src()
        data_dict = interceptor.collect([img_src]) if img_src else {}
        if not img_src or img_src not in data_dict:
            fails += 1
            skipped_pages.append(current_page)
            reason = "нет картинки" if not img_src else "нет байтов"
            debug_log(f"download_chapter_page: страница {current_page} — {reason} ({fails}/3), пропускаем")
            if fails >= 3:
                debug_log("download_chapter_page: 3 страницы подряд пропущены — завершаем главу")
                break
            if current_page == end_page:
                break
            if not goto_next_page():
                debug_log("download_chapter_page: не удалось перейти дальше — завершаем")
                break
            current_page += 1
            continue
        fails = 0

        # Запись
        fname = f"{buf_prefix}page_{current_page:03d}{_ext_from_url(img_src)}"
        (temp_dir / fname).write_bytes(data_dict[img_src])
        downloaded += 1
        debug_log(f"download_chapter_page: страница {current_page} сохранена")
        emit_event("page_saved", chapter_number=number, page=current_page, total_pages=total_pages)

        # Если текущая страница не последняя, переходим на следующую
        if current_page == end_page:
            break

        if not goto_next_page():
            debug_log("download_chapter_page: не удалось перейти на следующую страницу, завершаем")
            break
        current_page += 1

    if skipped_pages and downloaded > 0:
        emit_event("chapter_incomplete",
                chapter_number=number,
                expected=total_pages,
                downloaded=downloaded,
                saved=True,
                message=(f"Глава {number}: сохранено {downloaded} из {total_pages} страниц. "
                         f"Пропущены страницы номер: {', '.join(map(str, skipped_pages))}"))

    if downloaded == 0:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None

    # Генерируем имя
    if as_buffer:
        images_meta = []
        html_parts = []
        for f in sorted(temp_dir.iterdir()):
            images_meta.append({"name": f.name, "path": str(f)})
            html_parts.append(
                f'<img src="images/{f.name}" style="max-width:100%;display:block;margin:10px auto;">'
            )
        return {
            "title": f"Том {volume}, Глава {number:g}",
            "html": "\n".join(html_parts),
            "images": images_meta,
            "temp_dir": str(temp_dir),
        }
    chapter_name = generate_chapter_name(volume, number, name, namer_config)
    return finalize_chapter_output(temp_dir, target_folder, chapter_name, save_as_cbz)


def download_chapter(
    page: Page,
    preset: dict,
    interceptor: 'ImageInterceptor',
    mode: str,
    url: str,
    target_folder: Path,
    namer_config: dict,
    pages: Optional[Tuple[int, int]] = None,
    save_as_cbz: bool = True
) -> Optional[Path]:
    """Диспетчер: content=ranobe → ранобэ-ветка; иначе web/page."""
    start_chapter_timer()
    try:
        if preset.get("content") == "ranobe":
            entry = collect_chapter_ranobe(page, preset, interceptor, url, target_folder, namer_config)
            if not entry:
                return None
            from core.namer import title_slug_from_url
            from output.epub import build_ranobe_epub
            return build_ranobe_epub([entry], title_slug_from_url(url), target_folder,
                                    source_name=preset.get("name", ""))
        if mode == "web":
            return download_chapter_web(page, preset, interceptor, url, target_folder,
                                        namer_config, pages, save_as_cbz)
        elif mode == "page":
            try:
                return download_chapter_page(page, preset, interceptor, url, target_folder,
                                            namer_config, pages, save_as_cbz)
            except Exception as e:
                import traceback
                debug_log(f"download_chapter_page: КРАШ: {e}\n{traceback.format_exc()}")
                raise
        else:
            raise ValueError(f"Неизвестный режим: {mode}")
    finally:
        stop_chapter_timer()

def goto_next_chapter(page: Page, preset: dict) -> Optional[str]:
    """
    Переход к следующей главе кликом. Успех = изменился ПУТЬ URL.
    Смена только fragment/query (листание страниц внутри главы) — не переход:
    кликаем повторно (после последней страницы кнопка ведёт на след. главу).
    """
    btn_sels = preset.get("selectors", {}).get("next_chapter_btn")
    if not btn_sels:
        debug_log("goto_next_chapter: в пресете нет next_chapter_btn")
        return None
    if isinstance(btn_sels, str):
        btn_sels = [btn_sels]
    time.sleep(get_delay())
    current_url = page.url
    current_path = urlparse(current_url).path
    before = _identity_from_text(page, preset)
    for sel in btn_sels:
        loc = locate(page, sel)
        if loc.count() == 0:
            debug_log(f"goto_next_chapter: селектор не найден: {sel}")
            continue
        for attempt in range(2):
            try:
                try:
                    loc.first.scroll_into_view_if_needed(timeout=1000)
                except Exception:
                    pass
                loc.first.click(timeout=3000)
            except Exception as e:
                debug_log(f"goto_next_chapter: клик не удался ({sel}): {e}")
                save_debug_html(page, "next_btn_blocked")
                break
            start = time.monotonic()
            same_page_nav = False
            while time.monotonic() - start < 10:
                new_url = page.url
                after = _identity_from_text(page, preset)
                if (before and after and after != before) or \
                   (before is None and urlparse(new_url).path != current_path):
                    debug_log(f"goto_next_chapter: перешли на {new_url} (селектор: {sel}); "
                              f"путь: {current_path} -> {urlparse(new_url).path}; identity: {before} -> {after}")
                    post_nav_checks(page, preset)
                    return new_url
                if urlparse(new_url).path != current_path:
                    same_page_nav = True   # клик листнул страницу внутри главы
                    break
                time.sleep(0.3)
            if not same_page_nav:
                debug_log(f"goto_next_chapter: URL не изменился после клика ({sel})")
                break
            debug_log(f"goto_next_chapter: клик листнул внутри главы ({page.url}), повторный клик")
    # Проход 2: JS-клик — последнее средство (оверлеи, скрытые кнопки),
    # только когда ВСЕ селекторы не кликнулись обычным кликом.
    for sel in btn_sels:
        loc = locate(page, sel)
        if loc.count() == 0:
            continue
        try:
            save_debug_html(page, "next_btn_blocked")
            loc.first.evaluate("(e) => e.click()")
            debug_log(f"goto_next_chapter: JS-клик по ({sel})")
        except Exception as e:
            debug_log(f"goto_next_chapter: JS-клик тоже не смог ({sel}): {e}")
            continue
        start = time.monotonic()
        while time.monotonic() - start < 10:
            new_url = page.url
            after = _identity_from_text(page, preset)
            if urlparse(new_url).path != current_path:
                debug_log(f"goto_next_chapter: перешли на {new_url} (селектор: {sel}); "
                            f"путь: {current_path} -> {urlparse(new_url).path}; identity: {before} -> {after}")
                post_nav_checks(page, preset)
                return new_url
            time.sleep(0.3)
    debug_log("goto_next_chapter: ни один селектор не привёл к переходу")
    return None