"""
main.py — боевой CLI для скачивания манги.

Примеры:
    python main.py "https://mangalib.me/ru/8748--sono-bisque-doll-wa-koi-wo-suru" --mode web
    python main.py "https://rumix.me/geroi_racional_perestraivaet_korolevstvo" --mode web --chapters 1-5
    python main.py "https://mangalib.me/ru/8748--sono-bisque-doll-wa-koi-wo-suru/read/v1/c1" --mode web --count 3
    python main.py "https://a.zazaza.me/ia_byl_predan_tovarichami_v_glubine_podzemelia__no_blagodaria_svoemu_navyku__beskonechnaia_gacha__ia_obrel_soiuznikov_9999_urovnia__chtoby_otomstit_byvshim_soratnikam_i_vsemu_miru" --mode web --chapters 50-51 --headed --debug
"""
import argparse
import sys
from pathlib import Path

from core.logger import setup_logging, set_debug_mode, debug_log, emit_event
from core.presets import PresetManager
from core.config import DEFAULT_CONFIG
from browser.driver import BrowserSession
from browser.interceptor import ImageInterceptor
from engine.toc_walker import find_chapter_in_toc, get_toc_last_chapter
from engine.worker import download_chapters_manga, get_download_errors
from engine.reader import download_chapter, post_nav_checks, read_chapter_meta, cleanup_chapter_temps

# GUI шлёт CTRL_BREAK_EVENT (Windows) — превращаем его в KeyboardInterrupt,
# чтобы сработали штатные обёртки сохранения (ранобэ → EPUB из буфера).
if sys.platform == "win32":
    import signal as _signal
    def _break_to_keyboard(sig, frame):
        raise KeyboardInterrupt
    _signal.signal(_signal.SIGBREAK, _break_to_keyboard)


def parse_range(s: str, as_int: bool = False):
    """Парсит диапазон: '1-5' → (1, 5); '3' → (3, 3) ровно одна;
    '3--1' или '3-' → (3, None) — «до конца» (сентинел -1 как в v3)."""
    a, b = (s.split("-", 1) if "-" in s else (s, s))
    b = b.strip()
    open_end = (b == "" or b == "-1")
    if as_int:
        return int(a), (None if open_end else int(b))
    return float(a), (None if open_end else float(b))


def main():
    parser = argparse.ArgumentParser(
        description="Скачивание манги / ранобэ с mangalib, rumix и др.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  # Скачать 3 главы начиная с первой (URL тайтла)
  python main.py "https://mangalib.me/ru/8748--sono-bisque-doll-wa-koi-wo-suru" --mode web --count 3

  # Скачать главы 5-10 (URL тайтла)
  python main.py "https://rumix.me/geroi_racional_perestraivaet_korolevstvo" --mode web --chapters 5-10

  # Скачать одну конкретную главу (URL главы)
  python main.py "https://mangalib.me/ru/8748--sono-bisque-doll-wa-koi-wo-suru/read/v1/c1" --mode web --single

  # Подготовить профиль браузера (авторизация + режим)
  python main.py --setup "https://mangalib.me"
        """,
    )
    parser.add_argument("url", help="URL тайтла (оглавление) или конкретной главы")
    parser.add_argument("--mode", choices=["web", "page"], default="web", help="Режим чтения (по умолчанию: web)")
    parser.add_argument("--count", type=int, help="Количество глав для скачивания (с начала)")
    parser.add_argument("--chapters", type=str, help="Главы: '1-5' диапазон, '3' одна ровно, '3--1' с 3 до конца")
    parser.add_argument("--volumes", type=str, help="Тома: '1-3', '2' ровно, '2--1' до конца")
    parser.add_argument("--single", action="store_true", help="Скачать только одну главу (URL должен вести на главу)")
    parser.add_argument("--output", "-o", type=str, default="downloads", help="Папка для сохранения (по умолчанию: downloads)")
    parser.add_argument("--no-cbz", action="store_true", help="Сохранять как папки, не архивировать в CBZ")
    parser.add_argument("--keep-failed-temps", action="store_true",
                        help="Не удалять .tmp-папки провальных глав (оставить для разбора)")
    parser.add_argument("--headed", action="store_true", help="Показать окно браузера")
    parser.add_argument("--channel", default="chrome", help="Канал браузера (по умолчанию: chrome)")
    parser.add_argument("--debug", action="store_true", help="Включить отладочный вывод и файловые логи")
    parser.add_argument("--setup", action="store_true", help="Режим подготовки профиля (авторизация + настройки)")
    parser.add_argument("--preset", type=str, default=None, help="Имя пресета вручную (вместо автоопределения по домену)")

    args = parser.parse_args()

    # --- Логирование ---
    setup_logging(debug=args.debug)
    if args.debug:
        set_debug_mode(True)

    # --- Режим подготовки профиля ---
    if args.setup:
        print(f"\n{'='*64}")
        print("ПОДГОТОВКА ПРОФИЛЯ:")
        print("1. В браузере зайди на сайт, авторизуйся")
        print("2. Открой любую главу, переключи режим на нужный")
        print("3. Вернись сюда и нажми ENTER")
        print(f"{'='*64}\n")
        with BrowserSession(headed=True, channel=args.channel, initial_url=args.url) as session:
            session.goto(args.url)
            input("Нажми ENTER после подготовки...")
        print("✅ Профиль подготовлен.")
        return

    # --- Определяем пресет ---
    presets_dir = Path(__file__).parent / "presets"
    _pm = PresetManager(presets_dir)
    if args.preset:
        preset = _pm.get_preset(args.preset)
        if not preset:
            emit_event("error", message=f"Пресет '{args.preset}' не найден в presets/")
            print(f"❌ Пресет '{args.preset}' не найден")
            sys.exit(1)
    else:
        preset = _pm.find_preset_by_domain(args.url)
    if not preset:
        emit_event("error", message=f"Не найден пресет для URL: {args.url}")
        print(f"❌ Не найден пресет для URL: {args.url}")
        sys.exit(1)
    print(f"📋 Пресет: {preset['name']}")

    # --- Парсим диапазоны ---
    start_ch, end_ch = None, None
    start_vol, end_vol = None, None
    if args.chapters:
        start_ch, end_ch = parse_range(args.chapters)
    if args.volumes:
        start_vol, end_vol = parse_range(args.volumes)

    # --- Папка для сохранения ---
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    stop_file = Path(__file__).parent / ".stop_download"
    try:
        stop_file.unlink(missing_ok=True)
    except Exception:
        pass
    clean_failed_temps = not args.keep_failed_temps

    # --- Запуск браузера ---
    with BrowserSession(headed=args.headed, channel=args.channel,
                        initial_url=args.url) as session:
        interceptor = ImageInterceptor(session.page)
        interceptor.attach()
        
        # Загружаем страницу с явным ожиданием
        try:
            session.goto(args.url)
            debug_log(f"main: после goto URL = {session.page.url}")
        except Exception as e:
            emit_event("error", message=f"Ошибка при загрузке страницы: {e}")
            print(f"❌ Ошибка при загрузке страницы: {e}")
            print(f"   Текущий URL: {session.page.url}")
            sys.exit(1)
        post_nav_checks(session.page, preset)
        # --- Режим одной главы ---
        if args.single:
            print(f"📖 Скачиваю одну главу: {args.url}")
            emit_event("download_started",
                   total_chapters=1,
                   preset_name=preset.get("name", ""),
                   content=preset.get("content", "manga"))
            result = download_chapter(
                page=session.page,
                preset=preset,
                interceptor=interceptor,
                mode=args.mode,
                url=args.url,
                target_folder=output,
                namer_config=DEFAULT_CONFIG,
                save_as_cbz=not args.no_cbz,
            )
            if result:
                print(f"✅ {result} ({result.stat().st_size} байт)")
                emit_event("download_completed", files=[str(result)], errors=[], total_chapters=1)
            else:
                emit_event("error", message="Не удалось скачать главу")
                emit_event("download_completed", files=[], errors=["Не удалось скачать главу"], total_chapters=1)
                print("❌ Не удалось скачать главу")
                if clean_failed_temps:
                    try:
                        _meta = read_chapter_meta(session.page, preset, session.page.url)
                        cleanup_chapter_temps(output, _meta.get("volume"), _meta["number"],
                                            ranobe=(preset.get("content") == "ranobe"))
                    except Exception:
                        pass
                sys.exit(1)
            return

        # --- Режим нескольких глав ---
        # Целевой поиск стартовой главы в оглавлении (минимум диапазона, иначе 1)
        target_vol = start_vol if start_vol is not None else None
        target_ch = start_ch if start_ch is not None else 1.0
        print(f"📚 Ищу стартовую главу {target_ch:g} в оглавлении...")
        try:
            first = find_chapter_in_toc(
                page=session.page,
                preset=preset,
                target_number=target_ch,
                target_volume=target_vol,
            )
        except Exception as e:
            import traceback
            print(f"❌ Ошибка при поиске главы: {e}")
            traceback.print_exc()
            sys.exit(1)
        if not first:
            emit_event("error", message="Не удалось найти стартовую главу в оглавлении.")
            print("❌ Не удалось найти стартовую главу в оглавлении.")
            sys.exit(1)
        print(f"📖 Старт: v{first.get('volume')} c{first.get('number')}")

        # Оценка общего числа глав для прогресс-бара GUI
        total_chapters = None
        if args.count is not None:
            total_chapters = args.count
        else:
            start_num = start_ch if start_ch is not None else (first.get("number") or 1.0)
            if end_ch is not None:
                total_chapters = max(1, int(end_ch - start_num) + 1)
            else:
                last_ch = get_toc_last_chapter()
                if last_ch is not None and last_ch >= start_num:
                    total_chapters = int(last_ch - start_num) + 1
        debug_log(f"main: оценка последней главы = {get_toc_last_chapter()}, total_chapters = {total_chapters}")

        emit_event("download_started",
                total_chapters=total_chapters,
                preset_name=preset.get("name", ""),
                content=preset.get("content", "manga"))
        try:
            if preset.get("content") == "ranobe":
                from engine.worker import download_chapters_ranobe
                results = download_chapters_ranobe(
                    page=session.page, preset=preset, interceptor=interceptor,
                    first_chapter=first, target_folder=output, namer_config=DEFAULT_CONFIG,
                    count=args.count, end_chapter=end_ch,
                    end_volume=end_vol,
                    total_chapters=total_chapters,
                    clean_failed_temps=clean_failed_temps,
                )
            else:
                results = download_chapters_manga(
                    page=session.page, preset=preset, interceptor=interceptor,
                    first_chapter=first, mode=args.mode, target_folder=output,
                    namer_config=DEFAULT_CONFIG, save_as_cbz=not args.no_cbz,
                    count=args.count, end_chapter=end_ch,
                    end_volume=end_vol,
                    total_chapters=total_chapters,
                    clean_failed_temps=clean_failed_temps, 
                )
        except KeyboardInterrupt:
            debug_log("main: прервано пользователем до старта скачивания")
            results = []
        try:
            stop_file.unlink(missing_ok=True)
        except Exception:
            pass
        errors = get_download_errors()
        print(f"\n{'='*64}")
        print(f"✅ Скачано: {len(results)}")
        for p in results:
            print(f"   {p.name} ({p.stat().st_size:,} байт)")
        if errors:
            print(f"\n⚠️ Провалено: {len(errors)}")
            for e in errors:
                print(f"   ❌ {e}")
        print(f"{'='*64}")
        emit_event("download_completed",
            files=[str(p) for p in results],
            errors=errors,
            total_chapters=total_chapters)

if __name__ == "__main__":
    main()