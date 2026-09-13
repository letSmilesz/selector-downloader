# manga_dl/core/config.py
"""
Глобальные настройки именования.
Загружаются из config.json (если есть) с переопределением дефолтов.
"""
import json
from pathlib import Path
from typing import Dict, Any, Optional

DEFAULT_CONFIG = {
    "chapter_template_with_volume": "{volume} - {chapter} {name}",
    "chapter_template_no_volume": "{chapter} {name}",
    "volume_padding": 3,
    "folder_structure": "flat"
}