# engine/toc_walker.py
"""
Извлечение оглавления (TOC) и навигация по главам.
"""
import time
import re
from typing import Optional
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import Page

from core.logger import debug_log
from engine.reader import locate, extract_chapter_meta, save_debug_html, dismiss_popups, scroll_to_top, post_nav_checks, _tpl_list, _tpl_match

# Оценка последней главы оглавления для режима «до конца».
# При обратной сортировке первая ссылка ≈ последняя вышедшая глава.
_toc_last_chapter: Optional[float] = None
# Параметры микро-скролла оглавления (фикс пропуска глав в виртуальных списках)
TOC_STEP_DELTA = 300        # пикселей за один шаг
TOC_STEP_SLEEP = 0.15       # пауза после шага, чтобы виртуальный список отрисовал элементы
TOC_STEPS_PER_ROUND = 5     # шагов за один раунд (суммарно ≈ 1500пикс, как раньше)


def get_toc_last_chapter() -> Optional[float]:
    """Номер первой замеченной главы оглавления (оценка последней для прогресс-бара)."""
    return _toc_last_chapter

def ensure_toc(page: Page, preset: dict) -> None:
    """
    Гарантирует, что ссылки на главы присутствуют на странице.
    Никаких знаний о сайтах: только роли селекторов из пресета.
    Состояния: уже в оглавлении → ничего не делаем; главная тайтла → клик по toc_link;
    страница главы → back_to_toc_btn, затем toc_link.
    """
    dismiss_popups(page, preset)
    expand_hidden_chapters(page, preset) 
    sel = preset.get("selectors", {})
    chapter_sel = sel.get("chapter_link")
    if not chapter_sel:
        return
    container_sel = sel.get("toc_container")

    def _toc_ready() -> bool:
        # Ссылки могут лежать в DOM, но быть скрыты (неактивная вкладка grouple):
        # оглавление считаем открытым, только когда ссылки реально видимы.
        if container_sel:
            cont = locate(page, container_sel)
            if cont.count() == 0:
                return False
            inner = cont.first.locator(chapter_sel)
            return inner.count() > 0 and inner.first.is_visible()
        loc = locate(page, chapter_sel)
        return loc.count() > 1 and loc.first.is_visible()

    if _toc_ready():
        return

    toc_link = sel.get("toc_link")
    back_sel = sel.get("back_to_toc_btn")

    # Вкладки «Главы» нет, но есть кнопка возврата — мы на странице главы, идём на тайтл
    if back_sel and not (toc_link and locate(page, toc_link).count() > 0):
        try:
            back_btn = locate(page, back_sel).first
            try:
                back_btn.scroll_into_view_if_needed(timeout=1000)
            except Exception:
                pass
            back_btn.click(timeout=5000)
            debug_log("ensure_toc: клик по back_to_toc_btn (возврат на тайтл)")
            time.sleep(1.5)
        except Exception as e:
            debug_log(f"ensure_toc: не удалось кликнуть back_to_toc_btn: {e}")
        post_nav_checks(page, preset)

    # Открываем вкладку «Главы» и ждём появления списка
    if toc_link:
        try:
            tab = locate(page, toc_link).first
            if tab.count() > 0 and tab.is_visible():
                try:
                    tab.scroll_into_view_if_needed(timeout=1000)
                except Exception:
                    pass
                tab.click(timeout=5000)
                debug_log("ensure_toc: клик по toc_link (вкладка Главы)")
                for _ in range(10):
                    if _toc_ready():
                        break
                    time.sleep(0.5)
        except Exception as e:
            debug_log(f"ensure_toc: не удалось кликнуть toc_link: {e}")

_expanded_sels: set = set()

def expand_hidden_chapters(page: Page, preset: dict) -> None:
    """Разворачивает скрытые группы глав, если пресет задаёт hidden_chapters_btn.
    Один клик на селектор за процесс: кнопка может быть тумблером
    (com-x «Показать с начала») — повторный клик откатит порядок."""
    btn_sel = preset.get("selectors", {}).get("hidden_chapters_btn")
    if not btn_sel:
        return
    if btn_sel in _expanded_sels:
        return
    clicked = 0
    for btn in locate(page, btn_sel).all():
        try:
            btn.click(timeout=2000)
            time.sleep(0.5)
            clicked += 1
        except Exception as e:
            debug_log(f"expand_hidden_chapters: ошибка клика: {e}")
    if clicked:
        _expanded_sels.add(btn_sel)   # ← добавляем ТОЛЬКО после успешного клика
        debug_log(f"expand_hidden_chapters: развёрнуто групп: {clicked}")

def _scan_for_target(
    scope,
    page: Page,
    preset: dict,
    chapter_sel: str,
    target_volume: Optional[float],
    target_number: float,
) -> tuple:
    """
    Свип видимых ссылок оглавления: парсит пары (том, номер) и ищет цель.

    Возвращает (pairs, found_or_None, count):
      pairs           — список кортежей (vol_or_0, num) для всех распаршенных ссылок
      found_or_None   — dict {"volume", "number", "name", "url"}, если цель найдена
      count           — общее число ссылок в DOM (до фильтрации)
    """
    links = scope.locator(chapter_sel)
    count = links.count()
    pairs = []
    found = None
    for el in links.all():
        href = el.get_attribute("href")
        if not href:
            continue
        vol, num = None, None
        # 1) Текст-шаблон (надёжнее всего, когда задан)
        for t in _tpl_list(preset):
            ident = _tpl_match(t, (el.text_content() or "").strip())
            if ident:
                vol, num = ident
                break
        # 2) URL-регексы (всегда есть в URL)
        if num is None:
            try:
                meta = extract_chapter_meta(page, preset, href)
                vol, num = (meta.get("volume") or 0), meta["number"]
            except Exception:
                num = None
        # 3) data-num/data-vol — ПОСЛЕДНИЙ резерв
        if num is None:
            try:
                dn = el.get_attribute("data-num")
                dv = el.get_attribute("data-vol")
                if dn is None:
                    wrap = el.evaluate(
                        "el => { const w = el.closest('[data-num]'); "
                        "return w ? [w.getAttribute('data-num'), w.getAttribute('data-vol')] : null; }"
                    )
                    if wrap:
                        dn, dv = wrap
                if dn is not None:
                    num = float(dn)
                    vol = float(dv) if dv not in (None, "") else None
            except Exception:
                num = None
        if num is None:
            # Фоллбэк для безциферных глав ("Экстра", "Иллюстрации", "Сингл").
            # Берём номер предыдущей распаршенной главы + дробный инкремент,
            # чтобы сортировка (vol, num) и end_chapter-отсечка работали.
            if pairs:
                prev_vol, prev_num = pairs[-1]
                # Считаем, сколько экстра уже добавлено к этому prev_num
                extras_count = sum(
                    1 for pv, pn in pairs
                    if pv == prev_vol and prev_num < pn < prev_num + 1
                )
                num = prev_num + 0.1 * (extras_count + 1)
                vol = prev_vol
            else:
                # Первая глава в списке без номера — пропускаем (нет опоры)
                continue
        pairs.append((vol or 0, num))
        # Проверка совпадения с целью
        if target_volume is not None and abs((vol or 0) - target_volume) > 1e-9:
            continue
        if abs(num - target_number) < 1e-9:
            found = {"volume": vol, "number": num, "name": "", "url": href}
    return pairs, found, count

def find_chapter_in_toc(
    page: Page,
    preset: dict,
    target_number: float,
    target_volume: Optional[float] = None,
) -> Optional[dict]:
    """
    Целевой поиск главы в оглавлении: Home (верх списка), затем скролл вниз
    со свипом видимых ссылок каждый раунд, пока не найдётся целевая глава
    (минимум запрошенного диапазона, иначе 1). Без накопления полного списка.
    Поиск строго внутри toc_container. Ранний стоп: видимое окно «перекрыло»
    цель (номера по обе стороны) или список кончился.
    """
    ensure_toc(page, preset)
    expand_hidden_chapters(page, preset)
    sel = preset.get("selectors", {})
    chapter_sel = sel.get("chapter_link")
    if not chapter_sel:
        raise RuntimeError("В пресете не задан chapter_link")
    container_sel = sel.get("toc_container")
    scope = page
    if container_sel and locate(page, container_sel).count() > 0:
        scope = locate(page, container_sel).first

    scroll_to_top(page)
    global _toc_last_chapter
    _toc_last_chapter = None
    prev_edge = None
    stable = 0
    debug_seen_pairs = set()
    for round_idx in range(500):
        pairs, found, count = _scan_for_target(
            scope, page, preset, chapter_sel, target_volume, target_number
        )
        # Обновляем оценку последней главы (только раунд 0)
        if round_idx == 0 and _toc_last_chapter is None and pairs:
            _toc_last_chapter = pairs[0][1]
        if found:
            debug_log(f"find_chapter_in_toc: целевая {target_number:g} найдена в оглавлении")
            return found
        # Адаптивный скролл: шаг пропорционален расстоянию до цели,
        # направление — из порядка сортировки списка (первый/последний видимый).
        # Аккумулятора нет: только скользящие номера видимого окна.
        debug_log(f"find_chapter_in_toc: раунд: ссылок {count}, распаршено {len(pairs)}")
        if pairs:
            debug_seen_pairs.update(pairs)
            nums = [p[1] for p in pairs]
            debug_log(
                "find_chapter_in_toc: окно "
                f"first={pairs[0]}, last={pairs[-1]}, "
                f"num_min={min(nums):g}, num_max={max(nums):g}, "
                f"target_volume={target_volume}, target_number={target_number:g}"
            )
        if pairs:
            first, last = pairs[0], pairs[-1]
            asc = last >= first
            if target_volume is not None:
                # Том указан → кортежи (том, номер): дробные тома/главы работают
                tgt = (target_volume, target_number)
                below = (tgt > last) if asc else (tgt < last)
                above = (tgt < first) if asc else (tgt > first)
            else:
                # Том не указан → только номера глав (без сравнения томов)
                below = (target_number > last[1]) if asc else (target_number < last[1])
                above = (target_number < first[1]) if asc else (target_number > first[1])
            wheel = 1500 if below else (-1500 if above else 800)
            debug_log(
                "find_chapter_in_toc: направление "
                f"asc={asc if pairs else None}, "
                f"below={below if pairs else None}, "
                f"above={above if pairs else None}, "
                f"wheel={wheel}"
            )
        else:
            wheel = 1500
        # Hover один раз, чтобы wheel попал в нужный контейнер
        if count > 0:
            try:
                scope.locator(chapter_sel).nth(count - 1).hover(timeout=1000)
            except Exception:
                pass
        # Серия мелких шагов с проверкой после каждого
        sign = 1 if wheel > 0 else -1
        step = sign * TOC_STEP_DELTA
        found_mid = None
        for _ in range(TOC_STEPS_PER_ROUND):
            page.mouse.wheel(0, step)
            time.sleep(TOC_STEP_SLEEP)
            step_pairs, step_found, _ = _scan_for_target(
                scope, page, preset, chapter_sel, target_volume, target_number
            )
            if step_found:
                found_mid = step_found
                break
            if step_pairs:
                debug_seen_pairs.update(step_pairs)
        if found_mid:
            debug_log(f"find_chapter_in_toc: целевая {target_number:g} найдена в оглавлении")
            return found_mid
        pairs = step_pairs
        edge = (pairs[0], pairs[-1]) if pairs else None
        if edge == prev_edge:
            stable += 1
            if stable >= 4:
                break
        else:
            stable = 0
        prev_edge = edge
    debug_log(f"find_chapter_in_toc: целевая {target_number:g} не найдена")
    if debug_seen_pairs:
        seen_sorted = sorted(debug_seen_pairs)
        seen_nums = [p[1] for p in seen_sorted]
        closest = sorted(
            debug_seen_pairs,
            key=lambda p: abs(p[1] - target_number)
        )[:10]
        debug_log(
            "find_chapter_in_toc: всего увидено "
            f"{len(debug_seen_pairs)} уникальных глав; "
            f"num_min={min(seen_nums):g}, num_max={max(seen_nums):g}, "
            f"closest={closest}"
        )
    save_debug_html(page, "find_chapter_fail")
    return None

def click_chapter_link(page: Page, preset: dict, chapter: dict) -> bool:
    """
    Переход к главе кликом по её ссылке.
    Этапы:
    1. ensure_toc — гарантирует, что мы в оглавлении (кликает toc_link, если он задан в пресете).
    2. Поиск видимой ссылки и штатный клик Playwright.
    3. Понятная ошибка, если ссылка не найдена (без JS и goto).
    """
    url = chapter.get("url")
    if not url:
        debug_log("click_chapter_link: у главы нет URL")
        return False

    # Этап 1: Гарантируем, что список глав раскрыт
    # Если toc_link есть в пресете — ensure_toc кликнет по нему.
    # Если мы на странице главы — ensure_toc попытается вернуться через back_to_toc_btn.
    ensure_toc(page, preset)

    path = urlparse(url).path
    candidates = [f"a[href='{url}']", f"a[href='{path}']", f"a[href*='{path}']"]
    current = page.url

    # Этап 2: Ищем видимую ссылку и кликаем
    for sel in candidates:
        loc = page.locator(sel)
        count = loc.count()
        if count == 0:
            continue
        for i in range(min(count, 10)):
            el = loc.nth(i)
            try:
                el.scroll_into_view_if_needed(timeout=2000)
                if not el.is_visible():
                    continue
                el.click(timeout=2000)
            except Exception as e:
                debug_log(f"click_chapter_link: клик не удался ({sel} #{i}): {e}")
                try:
                    el.evaluate("(e) => e.click()")
                except Exception:
                    continue
                debug_log(f"click_chapter_link: JS-клик сработал ({sel} #{i})")
            if page.url != current:
                debug_log(f"click_chapter_link: переход на {page.url}")
                post_nav_checks(page, preset)
                return True
            time.sleep(1.5)
            if page.url != current:
                debug_log(f"click_chapter_link: переход на {page.url}")
                post_nav_checks(page, preset)
                return True

    # Этап 3: Понятная ошибка
    debug_log(f"click_chapter_link: ссылка для главы {chapter.get('number')} не найдена или не кликабельна после ensure_toc. "
              f"Проверьте наличие и корректность toc_link / chapter_link в пресете.")
    save_debug_html(page, "click_chapter_fail")
    return False