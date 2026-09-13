"""
engine/worker.py
Цикл скачивания нескольких глав подряд.
"""
import time
import random
from typing import List, Optional, Tuple
from pathlib import Path
from urllib.parse import urlparse
from core.logger import debug_log, emit_event
from engine.toc_walker import click_chapter_link
from engine.reader import download_chapter, goto_next_chapter, extract_chapter_meta, save_debug_html, read_chapter_meta, _identity_from_text, start_chapter_timer, stop_chapter_timer, cleanup_chapter_temps

_STOP_FILE = Path(__file__).parent.parent / ".stop_download"

_download_errors: list = []

def get_download_errors() -> list:
    return list(_download_errors)

def clear_download_errors():
    _download_errors.clear()

def _stop_requested() -> bool:
    return _STOP_FILE.exists()

def _same_path(current_url: str, chapter_url: str) -> bool:
    """Сравнивает пути URL без query/fragment."""
    return urlparse(current_url).path.rstrip("/") == urlparse(chapter_url).path.rstrip("/")


def _landed_on_chapter(page, preset: dict, chapter: dict) -> bool:
    """Сравнивает главу, на которой реально оказались, с целевой — по тексту страницы."""
    ident = _identity_from_text(page, preset)
    if ident is None:
        try:
            meta = extract_chapter_meta(page, preset, page.url)
            ident = (meta.get("volume") or 0, meta["number"])
        except Exception as e:
            debug_log(f"_landed_on_chapter: не удалось определить главу: {e}")
            return False
    got_vol, got_num = ident
    want_num = chapter.get("number")
    if want_num is None or abs(got_num - want_num) > 1e-6:
        return False
    wv = chapter.get("volume")
    if wv is not None and abs(got_vol - wv) > 1e-6:
        return False
    return True

def download_chapters_ranobe(
    page,
    preset: dict,
    interceptor,
    first_chapter: dict,
    target_folder: Path,
    namer_config: dict,
    delay_min: float = 3.0,
    delay_max: float = 8.0,
    count: Optional[int] = None,
    end_chapter: Optional[float] = None,
    end_volume: Optional[float] = None,
    total_chapters: Optional[int] = None,
    clean_failed_temps: bool = True,
) -> List[Path]:
    """
    Скачивает главы ранобэ подряд (без режимов web/page) и собирает буфер.
    После завершения цикла формирует единый EPUB.
    """
    from core.namer import title_slug_from_url
    from engine.reader import collect_chapter_ranobe
    from output.epub import build_ranobe_epub

    buffer = []
    clear_download_errors()
    current = first_chapter
    i = 0
    try:
        while True:
            if count is not None and i >= count:
                break
            if _stop_requested():
                debug_log("download_chapters_ranobe: получен стоп — сохраняю буфер")
                break
            interceptor.clear()
            # Событие для GUI: начало главы
            emit_event("chapter_started",
                        chapter_number=current.get("number"),
                        volume=current.get("volume"),
                        current=i + 1,
                        total=total_chapters)

            if i > 0:
                # Переход к следующей главе через кнопку "дальше"
                new_url = goto_next_chapter(page, preset)
                if not new_url:
                    debug_log("download_chapters_ranobe: нет кнопки 'дальше' — последняя глава")
                    break
                try:
                    current = read_chapter_meta(page, preset, new_url)
                except Exception as e:
                    debug_log(f"download_chapters_ranobe: не удалось распарсить URL {new_url}: {e}")
                    break
                time.sleep(1.0)

            # Проверка конечного тома и главы
            if end_volume is not None and (current.get("volume") or 0) > end_volume + 1e-9:
                debug_log(f"download_chapters_ranobe: том {current.get('volume'):g} > конца {end_volume:g} — стоп")
                break
            if end_chapter is not None and (current.get("number") or 0) > end_chapter + 1e-9:
                debug_log(f"download_chapters_ranobe: глава {current.get('number'):g} > конца {end_chapter:g} — стоп")
                break

            # Для первой главы: если мы не на ней, кликаем ссылку в оглавлении
            if i == 0 and not _same_path(page.url, current["url"]):
                debug_log("download_chapters_ranobe: кликаем первую главу в оглавлении")
                if not click_chapter_link(page, preset, current):
                    debug_log(f"download_chapters_ranobe: не удалось открыть первую главу {current.get('number')}")
                    _download_errors.append(f"Глава {current.get('number'):g}: не удалось открыть ссылку в оглавлении")
                    emit_event("chapter_incomplete",
                                chapter_number=current.get("number"),
                                message=f"Глава {current.get('number'):g}: не удалось открыть ссылку в оглавлении")
                    save_debug_html(page, f"skip_ranobe_ch_{current.get('number')}")
                    break
                time.sleep(1.5)

            # Проверяем, что мы на правильной главе
            if not _landed_on_chapter(page, preset, current):
                debug_log(f"download_chapters_ranobe: попали не на ту главу ({page.url}), пропускаем")
                _download_errors.append(f"Глава {current.get('number'):g}: попали не на ту главу")  # ← ДОБАВИТЬ
                save_debug_html(page, f"skip_ranobe_ch_{current.get('number')}")
            else:
                start_chapter_timer()
                try:
                    # Скачиваем главу в буфер
                    entry = collect_chapter_ranobe(
                        page=page,
                        preset=preset,
                        interceptor=interceptor,
                        url=current["url"],
                        target_folder=target_folder,
                        namer_config=namer_config,
                    )
                finally:
                    stop_chapter_timer()
                if entry:
                    buffer.append(entry)
                    debug_log(f"download_chapters_ranobe: глава {current.get('number')} добавлена в буфер")
                    emit_event("chapter_completed",
                            chapter_number=current.get("number"),
                            volume=current.get("volume"),
                            file_path=None)
                else:
                    debug_log(f"download_chapters_ranobe: глава {current.get('number')} не скачана")
                    _download_errors.append(f"Глава {current.get('number'):g}: не скачана")
                    emit_event("chapter_incomplete",
                                chapter_number=current.get("number"),
                                message=f"Глава {current.get('number'):g}: не скачана")
                    if clean_failed_temps:
                        cleanup_chapter_temps(target_folder, current.get("volume"),
                                            current.get("number"), ranobe=True)
            i += 1
            # Если достигли end_chapter, выходим без перехода
            if end_chapter is not None and (current.get("number") or 0) >= end_chapter - 1e-9:
                debug_log(f"download_chapters_ranobe: достигнута конечная глава {end_chapter:g} — стоп")
                break

            time.sleep(random.uniform(delay_min, delay_max))
    except KeyboardInterrupt:
        debug_log("download_chapters_ranobe: прервано пользователем")
    if not buffer:
        debug_log("download_chapters_ranobe: буфер пуст, EPUB не создан")
        return []

    # Формируем slug из URL первой главы
    slug = title_slug_from_url(first_chapter["url"])
    emit_event("epub_building", status="Сборка книги из скачанного...")
    try:
        epub_path = build_ranobe_epub(buffer, slug, target_folder,
                                      source_name=preset.get("name", ""))
    except Exception as ex:
        debug_log(f"download_chapters_ranobe: сборка EPUB упала: {ex}")
        _download_errors.append(f"Сборка EPUB не удалась: {ex}")
        emit_event("error", message=(
            f"Сборка EPUB не удалась: {ex}. "
            f"Черновики глав остались в папках .tmp_ranobe_* внутри {target_folder}"
        ))
        return []
    return [epub_path]

def download_chapters_manga(
    page,
    preset: dict,
    interceptor,
    first_chapter: dict,
    mode: str,
    target_folder: Path,
    namer_config: dict,
    pages: Optional[Tuple[int, int]] = None,
    save_as_cbz: bool = True,
    delay_min: float = 3.0,
    delay_max: float = 8.0,
    count: Optional[int] = None,
    end_chapter: Optional[float] = None,
    end_volume: Optional[float] = None,
    total_chapters: Optional[int] = None,
    clean_failed_temps: bool = True,
) -> List[Path]:
    """
    Обход глав от first_chapter: первая — кликом в оглавлении, остальные —
    кнопкой «дальше». Стопы: исчерпан count, текущий номер > end_chapter,
    нет кнопки «дальше». Списка глав из TOC больше нет.
    """
    results = []
    clear_download_errors()
    current = first_chapter
    i = 0
    while True:
        if count is not None and i >= count:
            break
        if _stop_requested():
            debug_log("download_chapters: получен стоп — завершаю")
            break
        # Чистим перехватчик ДО навигации
        interceptor.clear()
        # Событие для GUI: начало главы
        emit_event("chapter_started",
                   chapter_number=current.get("number"),
                   volume=current.get("volume"),
                   current=i + 1,
                   total=total_chapters)
        if i > 0:
            new_url = goto_next_chapter(page, preset)
            if not new_url:
                debug_log("download_chapters: нет кнопки 'дальше' — последняя глава")
                break
            try:
                current = read_chapter_meta(page, preset, new_url)
            except Exception as e:
                debug_log(f"download_chapters: не удалось определить главу после перехода: {e}")
                break
            time.sleep(1.0)
        if end_volume is not None and (current.get("volume") or 0) > end_volume + 1e-9:
            debug_log(f"download_chapters: том {current.get('volume'):g} > конца {end_volume:g} — стоп")
            break
        if end_chapter is not None and (current.get("number") or 0) > end_chapter + 1e-9:
            debug_log(f"download_chapters: глава {current.get('number'):g} > конца {end_chapter:g} — стоп")
            break
        if i == 0 and not _same_path(page.url, current["url"]):
            debug_log("download_chapters: мы не на главе, кликаем ссылку в оглавлении")
            if not click_chapter_link(page, preset, current):
                debug_log(f"download_chapters: не удалось открыть первую главу {current.get('number')}")
                _download_errors.append(f"Глава {current.get('number'):g}: не удалось открыть ссылку в оглавлении")
                emit_event("chapter_incomplete",
                        chapter_number=current.get("number"),
                        message=f"Глава {current.get('number'):g}: не удалось открыть ссылку в оглавлении")
                save_debug_html(page, f"skip_ch_{current.get('number')}")
                break
            time.sleep(1.5)
        if not _landed_on_chapter(page, preset, current):
            debug_log(f"download_chapters: попали не на ту главу ({page.url}), пропускаем")
            _download_errors.append(f"Глава {current.get('number'):g}: попали не на ту главу")
            emit_event("chapter_incomplete",
                    chapter_number=current.get("number"),
                    message=f"Глава {current.get('number'):g}: попали не на ту главу")
            save_debug_html(page, f"skip_ch_{current.get('number')}")
        else:
            result = download_chapter(
                page=page,
                preset=preset,
                interceptor=interceptor,
                mode=mode,
                url=current["url"],
                target_folder=target_folder,
                namer_config=namer_config,
                pages=pages,
                save_as_cbz=save_as_cbz,
            )
            if result:
                results.append(result)
                emit_event("chapter_completed",
                           chapter_number=current.get("number"),
                           volume=current.get("volume"),
                           file_path=str(result))
            else:
                _download_errors.append(f"Глава {current.get('number'):g}: не скачана")
                emit_event("chapter_incomplete",
                            chapter_number=current.get("number"),
                            message=f"Глава {current.get('number'):g}: не скачана")
                if clean_failed_temps:
                    cleanup_chapter_temps(target_folder, current.get("volume"),
                                          current.get("number"), ranobe=False)
        i += 1
        if end_chapter is not None and (current.get("number") or 0) >= end_chapter - 1e-9:
            debug_log(f"download_chapters: достигнута конечная глава {end_chapter:g} — стоп без перехода")
            break
        time.sleep(random.uniform(delay_min, delay_max))
    debug_log(f"download_chapters: скачано {len(results)} глав")
    if _download_errors: 
        debug_log(f"download_chapters: провалено {len(_download_errors)} глав")

    return results