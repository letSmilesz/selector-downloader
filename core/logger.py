# core/logger.py
import threading
import logging
import json
from pathlib import Path
from datetime import datetime

_local = threading.local()
_local.debug_mode = False

def setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(level)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    fh = logging.FileHandler(
        log_dir / f"run_{datetime.now():%Y%m%d_%H%M%S}.log", encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

def set_debug_mode(flag: bool) -> None:
    _local.debug_mode = flag
    logging.getLogger().setLevel(logging.DEBUG if flag else logging.INFO)

def is_debug_mode() -> bool:
    """Возвращает True, если режим отладки включён в текущем потоке."""
    return getattr(_local, 'debug_mode', False)

def debug_log(msg: str) -> None:
    """Пишет в лог только если is_debug_mode() == True."""
    if is_debug_mode():
        logging.debug(msg)

def get_app_base_dir() -> Path:
    """
    Возвращает директорию, где находится исполняемый файл (или скрипт).
    Для .exe — рядом с ним, для скрипта — папка с файлом.
    """
    import sys
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent  # корень проекта (рядом с core/)

def emit_event(event_type: str, **fields) -> None:
    """
    Выводит JSON-строку в stdout с полем type и переданными полями.
    """
    data = {"type": event_type, **fields}
    print(json.dumps(data, ensure_ascii=False), flush=True)