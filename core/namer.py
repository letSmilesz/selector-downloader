# manga_dl/core/namer.py
"""
Генерация имён файлов и папок для глав.
Схема соответствует FMD с шаблонами.
"""
import re
from typing import Optional, Dict, Any
from core.config import DEFAULT_CONFIG
from urllib.parse import urlparse

def sanitize_filename(name: str) -> str:
    """
    Заменяет запрещённые символы на '_', схлопывает повторяющиеся '_',
    обрезает '_' и пробелы по краям.
    """
    if not name:
        return ""
    # Заменяем запрещённые символы на '_' (как в старом коде)
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    # Схлопываем повторяющиеся '_'
    while '__' in safe:
        safe = safe.replace('__', '_')
    # Убираем '_' и пробелы по краям
    safe = safe.strip('_ ')
    return safe

def generate_chapter_name(
    volume: Optional[float],
    chapter: float,
    name: str,
    config: Dict[str, Any]
) -> str:
    """
    Генерирует имя папки/файла для главы по заданным шаблонам.
    
    Args:
        volume: номер тома (может быть None)
        chapter: номер главы (дробный допускается)
        name: название главы (может быть пустой строкой)
        config: словарь с ключами:
            - chapter_template_with_volume
            - chapter_template_no_volume
            - volume_padding (int)
    
    Returns:
        отсанитизированное имя
    """
    # Форматируем том, если он есть
    volume_str = ""
    if volume is not None:
        padding = config.get('volume_padding', 3)
        volume_str = f"{int(volume):0{padding}d}" if volume.is_integer() else str(volume)
    
    # chapter как строка (дробные оставляем как есть)
    chapter_str = str(chapter)
    if isinstance(chapter, float) and chapter.is_integer():
        chapter_str = str(int(chapter))
    
    # Название (если пустое, то убираем лишние пробелы)
    name_part = name.strip() if name else ""
    
    # Выбираем шаблон
    if volume is not None:
        template = config.get('chapter_template_with_volume', DEFAULT_CONFIG["chapter_template_with_volume"])
        # Заменяем плейсхолдеры
        result = template.format(volume=volume_str, chapter=chapter_str, name=name_part)
    else:
        template = config.get('chapter_template_no_volume', DEFAULT_CONFIG["chapter_template_no_volume"])
        result = template.format(chapter=chapter_str, name=name_part)
    
    # Если name_part пустой, убираем завершающий пробел (если есть)
    if not name_part:
        result = result.rstrip()
    
    # Санитизация финального имени
    return sanitize_filename(result)

def title_slug_from_url(url: str) -> str:
    """
    Извлекает slug тайтла из URL (например, для ranobelib).
    Пример: https://ranobelib.me/ru/12345--some-title -> "some-title"
    """
    path = urlparse(url).path
    if path.endswith('/'):
        path = path[:-1]
    # Обрезаем хвост главы (/read/vX/cY или /volN/…), чтобы slug работал и из URL главы
    for marker in ("/read/", "/vol"):
        idx = path.find(marker)
        if idx != -1:
            path = path[:idx].rstrip('/')
            break
    parts = path.split('/')
    if not parts:
        return "unknown"
    slug = parts[-1]
    # Если есть --, берём часть после
    if '--' in slug:
        slug = slug.split('--')[-1]
    # Если slug пустой, берём предыдущий сегмент
    if not slug and len(parts) > 1:
        slug = parts[-2]
    if not slug:
        slug = "unknown"
    return slug