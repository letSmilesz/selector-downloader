# frontend/preset_window.py
import json
import sys
from pathlib import Path
from typing import Optional, Dict, List, Any
import flet as ft

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.presets import PresetManager

# Тултипы полей редактора пресетов
TOOLTIPS = {
    # Основное
    "domains": "Домены, на которых работает пресет, через запятую. Поддомены учитываются автоматически.",
    "content": "Тип контента: manga — страницы-картинки; ranobe — текст с иллюстрациями.",
    "default_mode": "Режим чтения манги по умолчанию: web (лента) или page (постранично).",
    # Селекторы
    "content_container": "Основной контейнер главы: только текст/картинки главы, БЕЗ навигации, комментариев и рекламы. Примеры: div.text-content, #mangaBox.",
    "image_selector": "<img> страниц манги или иллюстраций. Не должен ловить аватарки, иконки, рекламу, превью. Примеры: div[data-page] img, #mangaBox img.manga-img.",
    "text_selector": "Абзацы <p> текста ранобэ строго внутри content_container.",
    "lazy_attr": (
        "Имя атрибута тега <img>, в котором лежит реальный URL картинки. "
        "Нужно только для сайтов с ленивой загрузкой, где в src плейсхолдер, "
        "а настоящий путь в другом атрибуте.\n"
        "Как проверить: откройте главу, ПКМ по картинке → Просмотреть код. "
        "Если в src полный путь (https://.../page_001.jpg) — оставьте пустым. "
        "Если в src мусор (data:image/..., 1x1.png), но есть другой атрибут "
        "с реальным путём — впишите его имя.\n"
        "Примеры: 'data-src', 'data-original', 'data-lazy-src'. "
        "Пишем только имя атрибута, без кавычек и без префикса.\n"
        "Отличие от image_selector: image_selector находит сами <img> элементы "
        "на странице, а lazy_attr говорит, из какого атрибута каждого <img> "
        "читать URL для скачивания."
    ),
    "next_chapter_btn": "Кнопка/ссылка «Следующая глава». Массив. URL после клика должен вести на другую главу, а не ?page=2.",
    "prev_chapter_btn": "Кнопка/ссылка «Предыдущая глава». Опционально.",
    "back_to_toc_btn": "Ссылка возврата из ридера на страницу тайтла (к оглавлению).",
    "toc_container": "Контейнер списка глав; внутри должны быть <a> ссылки на главы.",
    "chapter_link": "Ссылка на главу в оглавлении. НЕ уникальный — матчит все ссылки глав. Примеры: a[href*='/read/'], a[href*='/vol'].",
    "toc_link": "Вкладка/кнопка «Главы» на странице тайтла, открывает оглавление.",
    "dismiss_texts": (
        "Тексты кнопок закрытия всплывающих окон (18+, cookie, подписка). "
        "Скрипт ищет элементы с этим текстом и кликает по ним. "
        "Каждая строка = один текст. Пример: 'Да, мне есть 18', 'Принять', 'Закрыть'."
    ),
    "navbar_hover_selector": (
        "(Опционально) CSS-селектор области, на которую нужно навести курсор, чтобы "
        "появились скрытые кнопки навигации. Нужен только если сайт прячет кнопки "
        "'Следующая глава' / 'К оглавлению' в невидимую зону до hover-эффекта. "
        "В большинстве пресетов не требуется."
    ),
    "settings_button": "Кнопка настроек ридера (шестерёнка). Должна открывать меню режимов, а не настройки сайта.",
    "web_mode_toggle": "Переключатель режима «веб/вертикальная лента» в настройках ридера.",
    "page_mode_toggle": "Переключатель режима «постранично» в настройках ридера.",
    "page_select": (
        "CSS-селектор выпадающего списка <select> с номерами страниц (1, 2, 3... N). "
        "Нужен для определения общего числа страниц в главе через количество <option>. "
        "Это именно <select>, а НЕ текстовый блок 'страница 5 из 20'. "
        "Пример: 'select.page-select', '.manga-pages select'."
    ),
    "next_page_button": "Кнопка «Следующая страница» внутри главы (page-режим).",
    "loading_indicator": "Спиннер/«Загрузка...», исчезающий после загрузки контента.",
    "hidden_chapters_btn": "Кнопка разворота скрытых групп глав в оглавлении («Скрыто», «Показать ещё»).",
    "banned_paths":  (
        "Подстроки URL, запрещённые к скачиванию. Используется для защиты от заглушек, "
        "которые сайт отдаёт вместо реальных страниц.\n"
        "Как заполнить: откройте главу с заглушками, через DevTools посмотрите src одной "
        "из заглушек, сравните несколько src и найдите общую часть пути. "
        "Пример: src='/static/deleted1.png?t=111&u=0&h=XXX' — общая часть '/static/deleted', "
        "'deleted' или 'deleted1.png'. Любая из этих подстрок подойдёт. "
        "Каждая подстрока — с новой строки."
    ),
    "dismiss_remove_selectors":  (
        "CSS-селекторы контейнеров (реклама, оверлеи, информационные блоки), "
        "которые нужно скрыть целиком через display:none. "
        "Используется, когда у блока нет кнопки закрытия — скрипт прячет его сам. "
        "Каждый селектор с новой строки. Пример: div[class^='csr-uniq']."
    ),
    # Мета
    "volume_regex": "Regex тома из URL ссылки оглавления, номер в группе 1. Пример: /read/v(\\d+(?:\\.\\d+)?)",
    "chapter_num_regex": "Regex главы из URL ссылки оглавления, номер в группе 1. Пример: /read/v[\\d.]+/c([\\d.]+)",
    "meta_text_selector": "Элемент с текстом «Том X Глава Y» на странице главы.",
    "meta_text_template": "Точный шаблон текста meta_text_selector с плейсхолдерами {volume} и {number}.",
    "chapter_name_selector": "Элемент с названием главы (для имени файла). Опционально.",
    # Rate limit
    "marker_groups": (
        "JSON-массив групп маркеров для детекта баннера rate-limit (запрос подождать / "
        "капча / бан по IP). Срабатывает, когда на странице совпали ≥2 разных групп "
        "одновременно И при этом нет полезного контента (картинок/текста).\n"
        "Логика: одиночный поп-ап — ещё не rate-limit; а вот сочетание "
        "'баннер + затемнение + отсутствие контента' — уже он.\n"
        "Формат каждой группы: JSON-объект с полями type ('text' или 'selector') "
        "и value (текст или CSS-селектор). Пример:\n"
        "[\n"
        "  {\"type\": \"text\", \"value\": \"Слишком много запросов\"},\n"
        "  {\"type\": \"selector\", \"value\": \"div.rate-limit-overlay\"},\n"
        "  {\"type\": \"text\", \"value\": \"Подождите\"}\n"
        "]\n"
        "Если не уверены — оставьте пустым, детект будет только по отсутствию контента."
    ),
}

# Общая шпаргалка (диалог «?»)
CHEATSHEET = [
    "1. Стабильность: без хешей в классах, без nth-child/порядка, без временных id.",
    "2. Приоритет: #id > семантический .class > тег[attr] > CSS-комбинация > XPath (крайний случай).",
    "3. Селекторы-списки (chapter_link, image_selector) НЕ уникальны — матчат все элементы списка.",
    "4. Контейнеры (content_container, toc_container): только контент главы, без навигации/комментов/рекламы.",
    "5. Lazy-load: реальный URL в data-src/data-original → укажи в lazy_attr.",
    "6. Кнопки по тексту: :has-text('Текст') (Playwright).",
    "7. Разная разметка на страницах — массив селекторов, каждый с новой строки.",
    "8. Текст-шаблон главы надёжнее, URL-regex быстрее; в regex номер в группе 1, без якорей ^$.",
    "9. Проверка: 3 главы (ранняя/средняя/поздняя) + спецглавы, оба режима чтения.",
    "10. Значения полей: один селектор — строка; несколько — список (в редакторе: каждая строка = элемент). dismiss_texts — всегда список.",
    "11. marker_groups — всегда список списков строк, даже одна группа. Это НЕ про клики: это детект баннера лимита.",
    "12. Готовый JSON (от LLM или свой): положи в presets/<имя>.json в корне проекта — появится в списке после переоткрытия редактора.",
    "13. Сырьё из DevTools: заполни шаблон по HOWTO_cleanup.md и скорми LLM вместе с llm_cleanup_prompt.md — на выходе готовый JSON пресета.",
]

LLM_PROMPT = (
    "Ты делаешь конфиг-пресет для загрузчика манги/ранобэ (Playwright-парсер). "
    "Верни СТРОГО один JSON-объект без комментариев:\n"
    '{\n'
    '  "name": "<имя сайта строчными>",\n'
    '  "domains": ["<домен без протокола и пути>"],\n'
    '  "default_mode": "web|page",\n'
    '  "content": "manga|ranobe",\n'
    '  "selectors": {\n'
    '    "content_container": "<контейнер ТОЛЬКО главы, без навигации/комментов>",\n'
    '    "image_selector": "<img страниц манги/иллюстраций>",\n'
    '    "text_selector": "<p абзацы текста ранобэ>",\n'
    '    "lazy_attr": "<атрибут с реальным URL до lazy-load (data-src/data-original); пусто, если src>",\n'
    '    "next_chapter_btn": ["<ссылка/кнопка следующей главы>"],\n'
    '    "back_to_toc_btn": "<ссылка возврата к оглавлению>",\n'
    '    "toc_container": "<контейнер списка глав>",\n'
    '    "chapter_link": "<ссылки глав в оглавлении, матчит все>",\n'
    '    "toc_link": "<вкладка/кнопка открытия оглавления>",\n'
    '    "dismiss_texts": ["<тексты кнопок закрытия попапов>"]\n'
    '  },\n'
    '  "meta": {\n'
    '    "volume_regex": ["<том из URL ссылки, номер в группе 1>"],\n'
    '    "chapter_num_regex": ["<глава из URL ссылки, номер в группе 1>"],\n'
    '    "meta_text_selector": "<элемент с текстом вида Том X Глава Y>",\n'
    '    "meta_text_template": "Том {volume} Глава {number}"\n'
    '  },\n'
    '  "rate_limit": {"marker_groups": [["лимит", "превышен"], ["повторите", "позже"]]}\n'
    '}\n'
    "Правила: без хешей в классах и nth-child; приоритет #id > .class > тег[attr]; "
    "кнопки по тексту через :has-text('...'); несколько селекторов — список строк. "
    "HTML страницы: <<<ВСТАВЬ HTML ИЛИ ОПИШИ РАЗМЕТКУ>>>"
)

class PresetWindow:
    def __init__(self, page: ft.Page):
        self.page = page
        self.preset_manager = PresetManager(Path(__file__).parent.parent / "presets")
        self.current_preset_name: Optional[str] = None
        self.preset_data: Dict[str, Any] = {}

        self.preset_dropdown = ft.Dropdown(label="Пресет", width=300, on_select=self.on_preset_selected)
        self.help_button = ft.IconButton(icon=ft.Icons.HELP_OUTLINE, tooltip="Шпаргалка", on_click=self.show_help_dialog)
        self.name_field = ft.TextField(label="Имя пресета", width=300)
        
        self.domains_field = ft.TextField(label="Домены (через запятую)", multiline=True, min_lines=1, max_lines=3, tooltip=TOOLTIPS["domains"])
        self.content_dropdown = ft.Dropdown(label="Тип контента", options=[ft.dropdown.Option("manga"), ft.dropdown.Option("ranobe")], width=200, tooltip=TOOLTIPS["content"])
        self.default_mode_dropdown = ft.Dropdown(label="Режим по умолчанию", options=[ft.dropdown.Option("web"), ft.dropdown.Option("page")], width=200, tooltip=TOOLTIPS["default_mode"])        
        self.banned_paths_field = ft.TextField(
            label="Banned Paths",
            multiline=True,
            min_lines=1,
            max_lines=3,
            hint_text="Клик — редактор массива",
            tooltip=TOOLTIPS["banned_paths"],
            on_click=self._open_field_editor,
        )
        self.selectors_fields = {}
        selectors_keys = [
            "content_container", "image_selector", "text_selector", "lazy_attr", "next_chapter_btn", "prev_chapter_btn",
            "back_to_toc_btn", "toc_container", "chapter_link", "toc_link", "dismiss_texts", "dismiss_remove_selectors",
            "navbar_hover_selector", "settings_button", "web_mode_toggle", "page_mode_toggle", "page_select", "next_page_button", "loading_indicator", "hidden_chapters_btn",
        ]
        for key in selectors_keys:
            self.selectors_fields[key] = ft.TextField(
                label=key.replace("_", " ").title(),
                multiline=True, min_lines=1, max_lines=4,
                hint_text="Клик — редактирование в большом окне",
                tooltip=TOOLTIPS.get(key, ""),
                on_click=self._open_field_editor,
            )
            
        self.meta_volume_regex = ft.TextField(
            label="Volume Regex",
            multiline=True,
            min_lines=1,
            max_lines=3,
            hint_text="Клик — редактор массива regex",
            tooltip=TOOLTIPS["volume_regex"],
            on_click=self._open_field_editor,
        )
        self.meta_chapter_regex = ft.TextField(
            label="Chapter Num Regex",
            multiline=True,
            min_lines=1,
            max_lines=3,
            hint_text="Клик — редактор массива regex",
            tooltip=TOOLTIPS["chapter_num_regex"],
            on_click=self._open_field_editor,
        )
        self.meta_text_selector = ft.TextField(label="Meta Text Selector", tooltip=TOOLTIPS["meta_text_selector"])
        self.meta_text_template = ft.TextField(label="Meta Text Template", tooltip=TOOLTIPS["meta_text_template"])
        self.meta_name_selector = ft.TextField(label="Chapter Name Selector", tooltip=TOOLTIPS["chapter_name_selector"])
        self.rate_limit_groups = ft.TextField(
            label="Marker Groups",
            multiline=True,
            min_lines=2,
            max_lines=6,
            hint_text="Клик — редактор групп. Одна строка = одна группа, слова через запятую",
            tooltip=TOOLTIPS["marker_groups"],
            on_click=self._open_rate_editor,
        )
        # ИСПРАВЛЕНО: ElevatedButton -> Button
        self.save_overwrite_btn = ft.Button("Перезаписать", on_click=self.save_preset)
        self.save_new_btn = ft.Button("Сохранить как новый", on_click=self.save_preset_as_new)
        self.delete_btn = ft.Button("Удалить пресет", on_click=self.delete_preset, color=ft.Colors.RED)
        self.use_btn = ft.Button("▶ Использовать для скачивания", on_click=self.make_active)
        self.auto_btn = ft.Button("Авто-выбор по домену", on_click=self.make_auto)
        self.active_label = ft.Text("", size=12, italic=True)
        
        # ИСПРАВЛЕНО: build_ui теперь возвращает контрол, а не добавляет его на страницу
        self.content = self.build_ui()

    def build_ui(self) -> ft.Control:
        top_row = ft.Row(
            controls=[self.preset_dropdown, self.help_button, self.name_field],
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.END,
        )
        action_row = ft.Row(
            controls=[self.save_overwrite_btn, self.save_new_btn, self.delete_btn],
            alignment=ft.MainAxisAlignment.START,
            spacing=10,
        )
        active_row = ft.Row(
            controls=[self.use_btn, self.auto_btn, self.active_label],
            alignment=ft.MainAxisAlignment.START,
            spacing=10,
        )
        basic_col = ft.Column(
            controls=[
                self.domains_field,
                ft.Row([self.content_dropdown, self.default_mode_dropdown], spacing=10),
                self.banned_paths_field,
            ],
            spacing=5,
        )
        sel_left = ft.Column(
            controls=[self.selectors_fields[k] for k in [
                "content_container", "image_selector", "text_selector", "lazy_attr",
                "next_chapter_btn", "prev_chapter_btn", "back_to_toc_btn",
                "toc_container", "chapter_link", "toc_link",
            ]],
            spacing=14, expand=True,
        )
        sel_right = ft.Column(
            controls=[self.selectors_fields[k] for k in [
                "dismiss_texts", "dismiss_remove_selectors", "navbar_hover_selector", "settings_button",
                "web_mode_toggle", "page_mode_toggle", "page_select",
                "next_page_button", "loading_indicator", "hidden_chapters_btn",
            ]],
            spacing=14, expand=True,
        )
        selectors_row = ft.Row(
            controls=[sel_left, sel_right],
            vertical_alignment=ft.CrossAxisAlignment.START,
            spacing=10,
        )
        meta_col = ft.Column(
            controls=[
                self.meta_volume_regex, self.meta_chapter_regex,
                self.meta_text_selector, self.meta_text_template,
                self.meta_name_selector,
            ],
            spacing=5,
        )
        content = ft.Column(
            controls=[
                ft.Text("Редактор пресетов", size=20, weight=ft.FontWeight.BOLD),
                top_row, action_row, active_row, ft.Divider(height=10),                
                ft.Text("Основное", weight=ft.FontWeight.BOLD), basic_col, ft.Divider(height=10),
                ft.Text("Селекторы", weight=ft.FontWeight.BOLD), selectors_row, ft.Divider(height=10),
                ft.Text("Мета", weight=ft.FontWeight.BOLD), meta_col, ft.Divider(height=10),
                ft.Text("Rate Limit", weight=ft.FontWeight.BOLD), self.rate_limit_groups,
            ],
            spacing=5,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        self.refresh_preset_list()
        return content
    
    def refresh_preset_list(self):
        names = self.preset_manager.list_presets()
        self.preset_dropdown.options = [ft.dropdown.Option(n) for n in names]
        if names:
            self.preset_dropdown.value = names[0]
            self.load_preset(names[0])
        else:
            self.preset_dropdown.value = None
            self.clear_fields()
        self.name_field.value = self.preset_dropdown.value or ""
        self.page.update()

    def load_preset(self, name: str):
        data = self.preset_manager.get_preset(name)
        if not data:
            return
        self.current_preset_name = name
        self.preset_data = data.copy()
        self.name_field.value = name
        self.domains_field.value = ", ".join(data.get("domains", []))
        self.content_dropdown.value = data.get("content", "manga")
        self.default_mode_dropdown.value = data.get("default_mode", "web")
        banned = data.get("banned_paths", [])
        if isinstance(banned, str):
            banned = [banned]
        self.banned_paths_field.value = "\n".join(banned)
        selectors = data.get("selectors", {})
        for key, field in self.selectors_fields.items():
            val = selectors.get(key)
            if isinstance(val, list):
                field.value = "\n".join(val)
            elif val is not None:
                field.value = str(val)
            else:
                field.value = ""
        meta = data.get("meta", {})
        self.meta_volume_regex.value = "\n".join(meta.get("volume_regex", []))
        self.meta_chapter_regex.value = "\n".join(meta.get("chapter_num_regex", []))
        self.meta_text_selector.value = meta.get("meta_text_selector", "") or ""
        self.meta_text_template.value = meta.get("meta_text_template", "") or ""
        self.meta_name_selector.value = meta.get("chapter_name_selector", "") or ""
        rate = data.get("rate_limit", {})
        self.rate_limit_groups.value = self._format_rate_groups(rate.get("marker_groups", []))
        self.page.update()

    def clear_fields(self):
        self.current_preset_name = None
        self.preset_data = {}
        self.name_field.value = ""
        self.domains_field.value = ""
        self.content_dropdown.value = "manga"
        self.default_mode_dropdown.value = "web"
        self.banned_paths_field.value = ""
        for field in self.selectors_fields.values():
            field.value = ""
        self.meta_volume_regex.value = ""
        self.meta_chapter_regex.value = ""
        self.meta_text_selector.value = ""
        self.meta_text_template.value = ""
        self.meta_name_selector.value = ""
        self.rate_limit_groups.value = ""
        self.page.update()

    def on_preset_selected(self, e):
        if self.preset_dropdown.value:
            self.load_preset(self.preset_dropdown.value)

    def _format_rate_groups(self, groups) -> str:
        """Для GUI: [['лимит', 'превышен'], ['повторите', 'позже']] -> строки."""
        if not isinstance(groups, list):
            return ""
        lines = []
        for group in groups:
            if not isinstance(group, list):
                continue
            words = [str(w).strip() for w in group if str(w).strip()]
            if words:
                lines.append(", ".join(words))
        return "\n".join(lines)

    def _parse_rate_groups(self, raw: str) -> List[List[str]]:
        """
        Для сохранения:
        - человеческий вид:
              лимит, превышен
              повторите, позже
        - старый JSON-вид тоже понимает, на всякий пожарный.
        """
        raw = (raw or "").strip()
        if not raw:
            return []

        # Backward compatibility: если в поле вдруг остался старый JSON
        if raw.startswith("["):
            try:
                data = json.loads(raw)
                if isinstance(data, list):
                    result = []
                    for group in data:
                        if isinstance(group, list):
                            words = [str(w).strip().strip('"').strip("'") for w in group if str(w).strip()]
                            if words:
                                result.append(words)
                    return result
            except Exception:
                pass

        result = []
        for line in raw.splitlines():
            words = [
                w.strip().strip('"').strip("'")
                for w in line.split(",")
                if w.strip()
            ]
            if words:
                result.append(words)
        return result

    def _open_rate_editor(self, e):
        """Rate limit: диалог, по полю на группу. Слова через запятую, без JSON."""
        groups = self._parse_rate_groups(self.rate_limit_groups.value or "")

        fields: List[ft.TextField] = [
            ft.TextField(value=", ".join(str(w) for w in group))
            for group in groups
        ]
        fields.append(ft.TextField(hint_text="Новая группа: слова через запятую"))

        controls: List[ft.Control] = [
            ft.Text(
                "Каждое поле — одна группа. Слова через запятую, кавычки не нужны. "
                "Пустое поле — группа удаляется.",
                size=12,
                italic=True,
            ),
            *fields,
        ]

        def save(ev):
            new_groups: List[List[str]] = []
            for f in fields:
                words = [
                    w.strip().strip('"').strip("'")
                    for w in (f.value or "").split(",")
                    if w.strip()
                ]
                if words:
                    new_groups.append(words)

            self.rate_limit_groups.value = self._format_rate_groups(new_groups)
            self.rate_limit_groups.update()
            self.page.pop_dialog()

        dlg = ft.AlertDialog(
            title=ft.Text("Rate limit: группы маркеров"),
            modal=True,
            content=ft.Container(
                content=ft.Column(
                    controls=controls,
                    spacing=8,
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=700,
                height=420,
            ),
            actions=[
                ft.Button("Сохранить", on_click=save),
                ft.Button("Отмена", on_click=lambda ev: self.page.pop_dialog()),
            ],
        )
        self.page.show_dialog(dlg)

    def _open_field_editor(self, e):
        """Клик по полю селектора/меты — большой редактор."""
        field = e.control

        array_labels = {
            "Next Chapter Btn",
            "Prev Chapter Btn",
            "Dismiss Texts",
            "Dismiss Remove Selectors",
            "Banned Paths",
            "Volume Regex",
            "Chapter Num Regex",
        }

        if field.label in array_labels:
            self._open_lines_editor(field)
            return

        editor = ft.TextField(value=field.value or "", multiline=True, expand=True)
        hint = ft.Text(field.tooltip or "", size=12, italic=True)

        def save(ev):
            field.value = editor.value
            field.update()
            self.page.pop_dialog()

        dlg = ft.AlertDialog(
            title=ft.Text(f"Редактор: {field.label}"),
            modal=True,
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        hint,
                        ft.Container(content=editor, height=320),
                    ],
                    spacing=8,
                ),
                width=900,
            ),
            actions=[
                ft.Button("Сохранить", on_click=save),
                ft.Button("Отмена", on_click=lambda ev: self.page.pop_dialog()),
            ],
        )
        self.page.show_dialog(dlg)

    def _open_lines_editor(self, field):
        """Редактор массива: каждый элемент массива — отдельное поле."""
        values = [
            line.strip()
            for line in (field.value or "").splitlines()
            if line.strip()
        ]

        fields: List[ft.TextField] = [
            ft.TextField(value=value)
            for value in values
        ]
        fields.append(ft.TextField(hint_text="Новый элемент массива"))

        controls: List[ft.Control] = [
            ft.Text(
                field.tooltip or "Каждое поле — отдельный элемент массива. Пустое поле удаляется.",
                size=12,
                italic=True,
            ),
            *fields,
        ]

        def save(ev):
            lines = [
                f.value.strip()
                for f in fields
                if (f.value or "").strip()
            ]
            field.value = "\n".join(lines)
            field.update()
            self.page.pop_dialog()

        dlg = ft.AlertDialog(
            title=ft.Text(f"Массив: {field.label}"),
            modal=True,
            content=ft.Container(
                content=ft.Column(
                    controls=controls,
                    spacing=8,
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=900,
                height=420,
            ),
            actions=[
                ft.Button("Сохранить", on_click=save),
                ft.Button("Отмена", on_click=lambda ev: self.page.pop_dialog()),
            ],
        )
        self.page.show_dialog(dlg)

    def get_data_from_fields(self) -> dict:
        domains = [d.strip() for d in (self.domains_field.value or "").split(",") if d.strip()]
        selectors = {}
        for key, field in self.selectors_fields.items():
            lines = [ln.strip() for ln in (field.value or "").splitlines() if ln.strip()]
            if len(lines) == 1:
                selectors[key] = lines[0]
            elif len(lines) > 1:
                selectors[key] = lines
            else:
                selectors[key] = None
        meta: Dict[str, Any] = {
            "volume_regex": [ln.strip() for ln in (self.meta_volume_regex.value or "").splitlines() if ln.strip()],
            "chapter_num_regex": [ln.strip() for ln in (self.meta_chapter_regex.value or "").splitlines() if ln.strip()],
        }
        if self.meta_text_selector.value:
            meta["meta_text_selector"] = self.meta_text_selector.value
        if self.meta_text_template.value:
            meta["meta_text_template"] = self.meta_text_template.value
        if self.meta_name_selector.value:
            meta["chapter_name_selector"] = self.meta_name_selector.value
        marker_groups = self._parse_rate_groups(self.rate_limit_groups.value or "")
        banned_lines = [ln.strip() for ln in (self.banned_paths_field.value or "").splitlines() if ln.strip()]
        result = {
            "name": self.name_field.value,
            "domains": domains,
            "content": self.content_dropdown.value or "manga",
            "default_mode": self.default_mode_dropdown.value or "web",
            "selectors": selectors,
            "meta": meta,
            "rate_limit": {"marker_groups": marker_groups},
        }
        if banned_lines:
            result["banned_paths"] = banned_lines
        return result

    def _write_preset(self, data: dict, allow_overwrite: bool) -> None:
        name = data.get("name")
        if not name:
            self._snack("Имя пресета не может быть пустым", error=True)
            return
        file_path = Path(__file__).parent.parent / "presets" / f"{name}.json"
        if file_path.exists() and not allow_overwrite:
            self._snack("Файл уже существует. Используйте 'Перезаписать'.", error=True)
            return
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self.preset_manager._presets[name] = data
            self.current_preset_name = name
            self.refresh_preset_list()
            self.preset_dropdown.value = name
            self.load_preset(name)
            self._snack(f"Пресет '{name}' сохранён")
        except Exception as ex:
            self._snack(f"Ошибка сохранения: {ex}", error=True)

    def save_preset(self, e):
        self._write_preset(self.get_data_from_fields(), allow_overwrite=True)

    def save_preset_as_new(self, e):
        self._write_preset(self.get_data_from_fields(), allow_overwrite=False)

    def delete_preset(self, e):
        name = self.name_field.value
        if not name:
            self._snack("Нет выбранного пресета", error=True)
            return

        def on_confirm(ev, confirm: bool):
            self.page.pop_dialog()
            if not confirm:
                return
            file_path = Path(__file__).parent.parent / "presets" / f"{name}.json"
            if file_path.exists():
                file_path.unlink()
            if name in self.preset_manager._presets:
                del self.preset_manager._presets[name]
            self.refresh_preset_list()
            self._snack(f"Пресет '{name}' удалён")

        dlg = ft.AlertDialog(
            title=ft.Text("Подтверждение удаления"),
            content=ft.Text(f"Удалить пресет '{name}'? Файл будет удалён безвозвратно."),
            actions=[
                ft.TextButton("Да", on_click=lambda ev: on_confirm(ev, True)),
                ft.TextButton("Нет", on_click=lambda ev: on_confirm(ev, False)),
            ],
        )
        self.page.show_dialog(dlg)

    def show_help_dialog(self, e):
        dlg = ft.AlertDialog(
            title=ft.Text("Шпаргалка по селекторам"),
            content=ft.Container(
                content=ft.Column([ft.Text(t, size=12) for t in CHEATSHEET],
                                  spacing=6, scroll=ft.ScrollMode.AUTO),
                width=760, height=420,
            ),
            actions=[
                ft.Button("Скопировать промпт для LLM", on_click=self.copy_llm_prompt),
                ft.Button("Закрыть", on_click=lambda ev: self.page.pop_dialog()),
            ],
        )
        self.page.show_dialog(dlg)

    def copy_llm_prompt(self, e):
        """Меню промптов: универсальный или постраничные (для локальных LLM с малым контекстом)."""
        base = Path(__file__).parent.parent / "llm_prompts"

        def read(name: str) -> str:
            try:
                return (base / name).read_text(encoding="utf-8").strip()
            except Exception:
                return ""

        common = read("common.md")
        items = [
            ("📘 Все страницы (универсальный)", read("full.md") or LLM_PROMPT),
            ("🏠 Тайтл / оглавление", f"{common}\n\n{read('title_toc.md')}"),
            ("📖 Глава: манга, лента (web)", f"{common}\n\n{read('chapter_web.md')}"),
            ("📄 Глава: манга, постранично", f"{common}\n\n{read('chapter_page.md')}"),
            ("📕 Глава: ранобэ", f"{common}\n\n{read('chapter_ranobe.md')}"),
            ("🧩 Собрать пресет из фрагментов", read("merge.md")),
        ]
        guide = ft.Text(
            "Какой промпт когда:\n"
            "• Тайтл/оглавление — страница со списком глав: ссылки прямо на главной "
            "или отдельная вкладка «Главы» — прикладывай тот HTML, что есть.\n"
            "• Глава: манга, лента — глава-«лента» с картинками.\n"
            "• Глава: манга, постранично — только если у сайта есть постраничное чтение.\n"
            "• Глава: ранобэ — глава с текстом; «Сборка» по text_selector сама поймёт, что content=ranobe.\n"
            "• Собрать пресет — когда фрагменты готовы: склейка в финальный JSON без анализа HTML.\n"
            "• Все страницы — для мощных моделей, когда весь HTML влезает в контекст.",
            size=12,
        )

        def make_copy(text: str, label: str):
            def handler(ev):
                self.page.pop_dialog()
                if not text.strip():
                    self._snack(f"Пусто для '{label}' — проверь папку llm_prompts/", error=True)
                    return
                self._copy_text(text, label)
            return handler

        controls: List[ft.Control] = [
            guide,
            *[ft.Button(label, on_click=make_copy(text, label)) for label, text in items],
        ]
        dlg = ft.AlertDialog(
            title=ft.Text("Промпт для LLM"),
            modal=True,
            content=ft.Container(
                content=ft.Column(
                    controls=controls,
                    spacing=8,
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=760,
                height=460,
            ),
            actions=[ft.Button("Отмена", on_click=lambda ev: self.page.pop_dialog())],
        )
        self.page.show_dialog(dlg)

    def _copy_text(self, text: str, label: str):
        async def do_copy():
            try:
                from flet.controls.services.clipboard import Clipboard
                await Clipboard().set(text)
                self._snack(f"Скопировано: {label}")
            except Exception:
                try:
                    import subprocess as sp
                    import os as _os
                    env = dict(_os.environ)
                    env["LLM_PROMPT"] = text
                    sp.run(["powershell", "-NoProfile", "-Command",
                            "Set-Clipboard -Value $env:LLM_PROMPT"],
                           env=env, creationflags=getattr(sp, "CREATE_NO_WINDOW", 0))
                    self._snack(f"Скопировано: {label}")
                except Exception as ex:
                    self._snack(f"Не удалось скопировать: {ex}", error=True)
        self.page.run_task(do_copy)

    def _snack(self, msg: str, error: bool = False):
        self.page.show_dialog(ft.SnackBar(
            content=ft.Text(msg),
            bgcolor=ft.Colors.RED if error else None,
        ))

    def _refresh_active_label(self):
        from frontend.config import load_config
        override = (load_config().get("preset_override") or "").strip()
        self.active_label.value = f"Активен: {override}" if override else "Активен: авто-выбор по домену"
        try:
            self.active_label.update()
        except Exception:
            pass

    def make_active(self, e):
        name = self.name_field.value or (self.preset_dropdown.value or "")
        if not name:
            self._snack("Нет имени пресета", error=True)
            return
        from frontend.config import load_config, save_config
        cfg = load_config()
        cfg["preset_override"] = name
        save_config(cfg)
        self._snack(f"Пресет '{name}' будет использоваться для скачивания")
        self._refresh_active_label()

    def make_auto(self, e):
        from frontend.config import load_config, save_config
        cfg = load_config()
        cfg["preset_override"] = ""
        save_config(cfg)
        self._snack("Включён авто-выбор пресета по домену")
        self._refresh_active_label()