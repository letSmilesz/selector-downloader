"""
output/archiver.py — финализация вывода главы (CBZ или папка).
Порт ContentDownloader._finalize_chapter_output (downloader.py).
"""
import shutil
import zipfile
from pathlib import Path


def finalize_chapter_output(
    temp_dir: Path,
    target_folder: Path,
    name: str,
    save_as_cbz: bool,
) -> Path:
    """
    Перемещает или архивирует результат скачивания главы.
    Возвращает путь к итоговому файлу/папке.
    """
    pages = sorted(temp_dir.glob("page_*.*"))
    if save_as_cbz:
        cbz_path = target_folder / f"{name}.cbz"
        try:
            with zipfile.ZipFile(cbz_path, 'w', zipfile.ZIP_STORED) as zf:
                for img_path in pages:
                    zf.write(img_path, img_path.name)
        except Exception as e:
            raise RuntimeError(f"Ошибка архивации: {e}")
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
        return cbz_path
    else:
        final_dir = target_folder / name
        if final_dir.exists():
            shutil.rmtree(final_dir)
        final_dir.mkdir(parents=True, exist_ok=True)
        for img_path in pages:
            shutil.move(str(img_path), str(final_dir / img_path.name))
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        return final_dir