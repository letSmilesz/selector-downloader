"""
output/epub.py
Сборка EPUB из буфера глав ранобэ.
"""
import shutil
from pathlib import Path
from typing import List, Dict

from ebooklib import epub

from core.logger import debug_log, emit_event


def build_ranobe_epub(chapters: List[Dict], title_slug: str, target_folder: Path,
                      source_name: str = "") -> Path:
    """
    Собирает EPUB из буфера глав ранобэ.
    chapters: список словарей, полученных из download_chapter_ranobe.
    title_slug: идентификатор тайтла (из URL).
    target_folder: папка для сохранения.
    Возвращает Path к созданному файлу.
    """
    if not chapters:
        raise ValueError("build_ranobe_epub: список глав пуст")

    book = epub.EpubBook()
    book.set_identifier(f"{source_name}-{title_slug}" if source_name else title_slug)
    book.set_title(title_slug.replace('_', ' ').title())
    book.set_language('ru')
    if source_name:
        book.add_author(source_name)

    # CSS
    style = (
        'body { font-family: serif; line-height: 1.5; padding: 10px; } '
        'img { max-width: 100%; height: auto; } '
        'h1 { text-align: center; font-size: 1.5em; margin-bottom: 1em; page-break-before: always; }'
    )
    nav_css = epub.EpubItem(
        uid="style",
        file_name="style/nav.css",
        media_type="text/css",
        content=style
    )
    book.add_item(nav_css)

    spine: list = ['nav']
    toc_list = []
    all_images_added = set()  # дедупликация по имени
    skipped = 0
    for i, ch in enumerate(chapters):
        try:
            file_name = f'chap_{i+1}.xhtml'
            c = epub.EpubHtml(uid=f'chapter_{i+1}', title=ch['title'], file_name=file_name, lang='ru')
            c.content = f"<h1>{ch['title']}</h1>" + ch['html']
            c.add_item(nav_css)
        except Exception as e:
            skipped += 1
            debug_log(f"build_ranobe_epub: глава {i+1} пропущена (битые данные): {e}")
            continue

        # Добавляем изображения
        for img_data in ch.get('images', []):
            name = img_data['name']
            if name in all_images_added:
                debug_log(f"build_ranobe_epub: имя '{name}' уже занято (глава {i + 1}) — картинка пропущена как дубль")
                continue
            path = Path(img_data['path'])
            if not path.exists():
                debug_log(f"build_ranobe_epub: файл {path} не найден, пропускаем")
                continue
            try:
                content_bytes = path.read_bytes()
                ext = path.suffix.lower()
                if ext == '.png':
                    media_type = 'image/png'
                elif ext == '.webp':
                    media_type = 'image/webp'
                elif ext == '.gif':
                    media_type = 'image/gif'
                else:
                    media_type = 'image/jpeg'

                img_item = epub.EpubImage(
                    uid=f"img_{i}_{name.replace('.', '_').replace('-', '_')}",
                    media_type=media_type,
                    content=content_bytes,
                    file_name=f"images/{name}"
                )
                book.add_item(img_item)
                c.add_item(img_item)
                all_images_added.add(name)
            except Exception as e:
                debug_log(f"build_ranobe_epub: ошибка добавления картинки {name}: {e}")

        book.add_item(c)
        spine.append(c)
        toc_list.append(c)

    if not toc_list:
        raise ValueError("build_ranobe_epub: все главы пропущены, книга пуста")
    book.toc = toc_list
    book.add_item(epub.EpubNcx())
    nav_item = epub.EpubNav(uid='nav')
    book.add_item(nav_item)
    book.spine = spine
    # Определяем выходной путь (перезапись без счётчиков); глав — сколько реально вошло
    output_path = target_folder / f"{title_slug}_{len(toc_list)}ch.epub"
    target_folder.mkdir(parents=True, exist_ok=True)

    try:
        epub.write_epub(str(output_path), book, {})
        debug_log(f"build_ranobe_epub: EPUB сохранён: {output_path}")
        emit_event("epub_completed", file_path=str(output_path))
    except Exception as e:
        debug_log(f"build_ranobe_epub: ошибка записи EPUB: {e}")
        raise

    # Удаляем временные папки всех глав
    for ch in chapters:
        temp_dir = ch.get('temp_dir')
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)

    return output_path