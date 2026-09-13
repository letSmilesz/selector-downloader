# manga_dl/core/presets.py
"""
Управление пресетами: загрузка из папки, поиск по имени и по домену.
"""
import json
import sys
from pathlib import Path
from typing import List, Dict, Optional
from urllib.parse import urlparse

class PresetManager:
    def __init__(self, presets_dir: Path):
        """
        Сканирует presets_dir и загружает все *.json как пресеты.
        Битые файлы пропускает с записью в stderr.
        """
        self.presets_dir = presets_dir
        self._presets: Dict[str, Dict] = {}  # имя_файла -> содержимое
        self._load_all_presets()

    def _load_all_presets(self):
        if not self.presets_dir.exists():
            return
        for json_file in self.presets_dir.glob("*.json"):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # Проверяем, что это словарь
                if isinstance(data, dict):
                    # Имя файла без расширения
                    name = json_file.stem
                    self._presets[name] = data
                else:
                    print(f"Пропущен {json_file}: не является JSON-объектом", file=sys.stderr)
            except Exception as e:
                print(f"Пропущен {json_file}: {e}", file=sys.stderr)

    def list_presets(self) -> List[str]:
        """Возвращает имена доступных пресетов (ключи словаря)."""
        return list(self._presets.keys())

    def get_preset(self, name: str) -> Optional[Dict]:
        """
        Возвращает пресет по имени.
        Сначала ищет по ключу (имя файла), затем по полю 'name' внутри пресета.
        Если не найден, возвращает None.
        """
        if name in self._presets:
            return self._presets[name]
        # Поиск по полю name
        for preset in self._presets.values():
            if preset.get('name') == name:
                return preset
        return None

    def find_preset_by_domain(self, url: str) -> Optional[Dict]:
        """
        Находит пресет, чей домен совпадает с доменом из URL.
        Сравнивает netloc (без порта) с элементами списка domains пресета.
        Поддерживается поддомен: если netloc заканчивается на "." + domain, считается совпадением.
        Возвращает первый подходящий пресет или None.
        """
        netloc = urlparse(url).netloc.lower().split(':')[0]
        if not netloc:
            return None

        for preset in self._presets.values():
            domains = preset.get('domains', [])
            for domain in domains:
                domain = domain.lower()
                if netloc == domain or netloc.endswith('.' + domain):
                    return preset
        return None