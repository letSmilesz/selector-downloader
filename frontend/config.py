# frontend/config.py
import json
from pathlib import Path
from typing import Dict, Any

CONFIG_PATH = Path(__file__).parent / "gui_config.json"
DEFAULT_CONFIG = {
    "last_url": "",
    "last_output": "downloads",
    "theme": "system",
    "headed": False,
    "debug": False,
    "show_log": True,
    "cbz": True,
    "subfolder": True,
    "preset_override": "",
}

def load_config() -> Dict[str, Any]:
    """Загружает gui_config.json или возвращает значения по умолчанию."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Применяем только известные ключи
                result = DEFAULT_CONFIG.copy()
                for key in result:
                    if key in data:
                        result[key] = data[key]
                return result
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(config: Dict[str, Any]) -> None:
    """Сохраняет конфигурацию в gui_config.json."""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception:
        pass