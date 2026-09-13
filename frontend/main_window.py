# frontend/main_window.py
import sys
import subprocess
import threading
import json
import signal
import os
import asyncio
from pathlib import Path
from typing import Optional, List
import flet as ft

# Добавляем корень проекта в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from frontend.config import load_config, save_config

class MainApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "Manga/Ranobe Downloader"
        
        # ИСПРАВЛЕНО: Новые свойства окна в Flet 0.80+
        self.page.window.width = 1000
        self.page.window.height = 720
        self.page.window.min_width = 900
        self.page.window.min_height = 720 

        self.config = load_config()
        
        # ... (остальной код инициализации переменных без изменений) ...
        self.process: Optional[subprocess.Popen] = None
        self.process_thread: Optional[threading.Thread] = None
        self.running = False
        self.auth_process: Optional[subprocess.Popen] = None
        self.total_chapters = 0
        self.current_chapter = 0
        self.total_pages = 0
        self.current_page = 0
        self.files_result: List[str] = []
        self.errors: List[str] = []
        self.incomplete: List[str] = []
        self.last_chapter_info: Optional[str] = None

        # Элементы управления
        self.url_field = ft.TextField(
            label="Ссылка (URL)",
            value=self.config.get("last_url", ""),
            hint_text="https://example.com/title",
            expand=True,
            tooltip="Ссылка на тайтл (оглавление) или конкретную главу",
        )
        self.mode_dropdown = ft.Dropdown(
            label="Режим",
            options=[ft.dropdown.Option("web"), ft.dropdown.Option("page")],
            value="web",
            tooltip="Режим чтения: веб-лента или постраничный. Игнорируется для ранобэ",
        )
        self.start_chapter_field = ft.TextField(label="Начальная глава", width=120, hint_text="1",
            tooltip="Первая глава для скачивания. Не обязательно «с начала»: проверьте номер первой главы на сайте. Если конечная пустая — скачается только эта")
        self.end_chapter_field = ft.TextField(label="Конечная глава", width=120, hint_text="оставьте пустой или -1",
            tooltip="Последняя глава. Оставьте пустой для одной главы. -1 — «до конца»")
        self.start_volume_field = ft.TextField(label="Начальный том", width=120, hint_text="1",
            tooltip="Первый том (опционально)")
        self.end_volume_field = ft.TextField(label="Конечный том", width=120, hint_text="оставьте пустой или -1",
            tooltip="Последний том (опционально)")
        self.count_field = ft.TextField(label="Количество глав", width=150, hint_text="например 10",
            tooltip="Сколько глав скачать, начиная с начальной. Перекрывает диапазон")
        self.output_field = ft.TextField(
            label="Папка вывода",
            value=self.config.get("last_output", "downloads"),
            width=300,
            tooltip="Куда сохранять файлы",
            on_change=self.on_subfolder_change,
        )
        self.output_browse_btn = ft.IconButton(
            icon=ft.Icons.FOLDER_OPEN,
            tooltip="Обзор",
            on_click=self.browse_output_folder,
        )
        self.subfolder_check = ft.Checkbox(label="Создать подпапку", value=self.config.get("subfolder", True),
            tooltip="Класть каждый запуск в отдельную подпапку вывода, чтобы тайтлы не перетирали друг друга")
        self.subfolder_field = ft.TextField(label="Имя подпапки", width=200,
            hint_text="пусто = title1, title2…",
            tooltip="Имя подпапки. Пустое — авто: первое свободное titleN",
            on_change=self.on_subfolder_change)
        self.subfolder_warn = ft.Text("", size=11, color=ft.Colors.YELLOW)
        self.subfolder_warn_slot = ft.Container(content=self.subfolder_warn, height=18)
        self.last_output_used = ""
        self.headed_check = ft.Checkbox(label="Показать окно браузера", value=self.config.get("headed", False),
            tooltip="Запустить браузер с видимым окном (для отладки)")
        self.debug_check = ft.Checkbox(label="Режим отладки", value=self.config.get("debug", False), on_change=self.on_debug_toggle,
            tooltip="Подробный вывод и сохранение HTML-дампов")
        self.cbz_check = ft.Checkbox(label="Сохранить как CBZ", value=self.config.get("cbz", True),
            tooltip="Архивировать главы манги в CBZ. Не влияет на ранобэ")
        self.clean_temps_check = ft.Checkbox(label="Чистить temp провальных глав",
            value=self.config.get("clean_failed_temps", True),
            tooltip="Удалять .tmp-папки провальных глав, чтобы не засорять диск. Снимите, чтобы оставить их для разбора")
        self.show_log_check = ft.Checkbox(label="Показать лог", value=self.config.get("show_log", True), on_change=self.on_log_toggle,
            tooltip="Показать окно лога")
                
        self.delay_min_field = ft.TextField(label="Мин. задержка (сек)", value="3", disabled=True, width=120,
            tooltip="Пока не регулируется из GUI. Фиксировано 3–8 сек. Изменить: engine/worker.py, delay_min")
        self.delay_max_field = ft.TextField(label="Макс. задержка (сек)", value="8", disabled=True, width=120,
            tooltip="Пока не регулируется из GUI. Фиксировано 3–8 сек. Изменить: engine/worker.py, delay_max")
        self.single_check = ft.Checkbox(label="Глава по ссылке", value=False,
            tooltip="URL ведёт прямо на главу: качаем без поиска по оглавлению. Роли TOC не нужны")
        
        # ИСПРАВЛЕНО: ElevatedButton -> Button
        self.start_btn = ft.Button("Старт", on_click=self.start_download, icon=ft.Icons.PLAY_ARROW)
        self.stop_btn = ft.Button("Стоп", on_click=self.stop_download, icon=ft.Icons.STOP, visible=False)
        self.preset_btn = ft.OutlinedButton("⚙ Пресеты", on_click=self.open_preset_window)
        self.auth_btn = ft.Button("🔑 Залогиниться", on_click=self.on_auth_click,
                                  tooltip="Откроет браузер с общим профилем. Залогинься на нужных сайтах и закрой окно — куки сохранятся сразу от всех сайтов.")
        self.auth_stop_btn = ft.Button("⏹ Завершить логин", on_click=self.on_auth_click,
                                       visible=False,
                                       tooltip="Закрыть браузер логина и освободить профиль")
        
        # Прогресс: ранобэ — один «высокий» бар; манга — два поменьше.
        self._is_ranobe = False
        self._stop_dialog = None
        self._image_slow_dialog_open = False
        self._chapter_slow_dialog_open = False
        self.progress_title = ft.Text("Прогресс скачивания", weight=ft.FontWeight.BOLD)
        self.chapter_label = ft.Text("", size=12)
        self.page_label = ft.Text("", size=12)
        self.chapter_bar = ft.ProgressBar(value=0)
        self.page_bar = ft.ProgressBar(value=0)
        self.spinner = ft.ProgressRing(width=22, height=22, stroke_width=3)
        self.progress_header = ft.Row(
            controls=[self.spinner, self.progress_title],
            spacing=10,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.progress_col = ft.Column(
            controls=[self.progress_header, self.chapter_label, self.chapter_bar,
                    self.page_label, self.page_bar],
            spacing=6,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            opacity=0,   # место зарезервировано всегда; «появление» = opacity=1
        )
        self.status_text = ft.Text("Готов к работе", size=14)

        self.log_list = ft.ListView(spacing=2, auto_scroll=True, expand=True)
        self.log_container = ft.Container(
            content=ft.SelectionArea(content=self.log_list),
            border=ft.Border.all(1, ft.Colors.OUTLINE),
            padding=5,
            margin=ft.Margin.only(top=0),
            height=200,
            visible=self.config.get("show_log", True),
        )
        # Ручка: тянет высоту лога мышкой, в пределах окна
        self.log_resize_handle = ft.GestureDetector(
            content=ft.Container(
                height=18,
                bgcolor=ft.Colors.OUTLINE,
                border_radius=9,
                border=ft.Border.all(1, ft.Colors.BLACK),
                content=ft.Row(
                    alignment=ft.MainAxisAlignment.CENTER,
                    controls=[ft.Container(width=50, height=4, bgcolor=ft.Colors.BLACK, border_radius=2)],
                ),
            ),
            on_vertical_drag_update=self._on_log_resize,
            mouse_cursor=ft.MouseCursor.RESIZE_ROW,
            tooltip="Тяни, чтобы изменить высоту лога",
            visible=self.config.get("show_log", True),
        )

        # Таблица результатов (показывается вместо лога, когда лог скрыт)
        self.result_list = ft.ListView(spacing=2, auto_scroll=True, expand=True)
        self.result_container = ft.Container(
            content=ft.SelectionArea(content=self.result_list),
            border=ft.Border.all(1, ft.Colors.OUTLINE),
            padding=5,
            margin=ft.Margin.only(top=0),
            height=200,
            visible=not self.config.get("show_log", True),
        )

        self.file_picker = ft.FilePicker()
        self.build_ui()
        self.apply_theme(self.config.get("theme", "system"))

    def build_ui(self):
        top_row = ft.Row(
            controls=[self.url_field, self.mode_dropdown, self.start_btn, self.stop_btn, self.preset_btn, self.auth_btn, self.auth_stop_btn],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        chapter_row = ft.Row(
            controls=[
                ft.Text("Главы:", weight=ft.FontWeight.BOLD), self.start_chapter_field, ft.Text("—"), self.end_chapter_field,
                ft.VerticalDivider(width=20),
                ft.Text("Тома:", weight=ft.FontWeight.BOLD), self.start_volume_field, ft.Text("—"), self.end_volume_field,
                ft.VerticalDivider(width=20), self.count_field,
            ],
            wrap=True, spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        output_row = ft.Row(
            controls=[self.output_field, self.output_browse_btn, self.subfolder_check, self.subfolder_field],
            spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        flags_row = ft.Row(
            controls=[self.headed_check, self.debug_check, self.cbz_check, self.show_log_check, self.single_check],
            spacing=15, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        delay_row = ft.Row(
            controls=[self.delay_min_field, self.delay_max_field, self.clean_temps_check],
            spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        settings_col = ft.Column(
            controls=[top_row, chapter_row, output_row, self.subfolder_warn_slot, flags_row, delay_row],
            spacing=10,
        )
        main_col = ft.Column(
            controls=[settings_col, self.progress_col, self.status_text, self.log_container, self.result_container, self.log_resize_handle],
            spacing=10,
            expand=True,
        )
        self.page.add(main_col)
        self.page.services = [*self.page.services, self.file_picker]
        self.page.update()

    def apply_theme(self, theme: str):
        if theme == "dark":
            self.page.theme_mode = ft.ThemeMode.DARK
        elif theme == "light":
            self.page.theme_mode = ft.ThemeMode.LIGHT
        else:
            self.page.theme_mode = ft.ThemeMode.SYSTEM
        self.page.update()

    def _next_title_name(self, base: str) -> str:
        """Первое свободное имя подпапки: title1, title2, … (GUI не парсит URL)."""
        try:
            root = Path(base)
            if root.exists():
                nums = [int(d.name[5:]) for d in root.iterdir()
                        if d.is_dir() and d.name.startswith("title") and d.name[5:].isdigit()]
                if nums:
                    return f"title{max(nums) + 1}"
        except Exception:
            pass
        return "title1"

    # ---------- Обзор папки (FilePicker = сервис с async-методами) ----------
    def browse_output_folder(self, e):
        async def pick():
            try:
                path = await self.file_picker.get_directory_path(dialog_title="Выбор папки вывода")
                if path:
                    self.output_field.value = path
                    self.output_field.update()
                    self.on_subfolder_change(None)
            except Exception as ex:
                self.log_message(f"Обзор папки недоступен: {ex}. Введите путь вручную.", is_error=True)
        self.page.run_task(pick)

    def on_debug_toggle(self, e):
        if self.debug_check.value:
            self.show_log_check.value = True
            self.on_log_toggle(None)

    def on_subfolder_change(self, e):
        """Жёлтое предупреждение под полем, если подпапка с введённым именем уже существует."""
        name = (self.subfolder_field.value or "").strip()
        base = (self.output_field.value or "").strip() or "downloads"
        exists = bool(name) and (Path(base) / name).exists()
        self.subfolder_warn.value = (
            "Папка уже существует: при совпадении имён глав они будут перезаписаны"
            if exists else ""
        )
        self.subfolder_warn.update()

    def on_log_toggle(self, e):
        vis = bool(self.show_log_check.value)
        self.log_container.visible = vis
        self.result_container.visible = not vis
        self.log_resize_handle.visible = True
        self.page.update()

    def _on_log_resize(self, e):
        page_h = self.page.height or self.page.window.height or 700
        max_h = max(240, int(page_h) - 380)
        cur = self.log_container.height or 200
        dy = e.primary_delta or 0
        new_h = int(min(max(cur + dy, 120), max_h))
        self.log_container.height = new_h
        self.result_container.height = new_h
        self.log_container.update()
        self.result_container.update()

    def _configure_progress(self, is_ranobe: bool):
        self.progress_col.opacity = 1
        self.progress_col.update()

    def log_message(self, msg: str, is_error=False):
        color = ft.Colors.RED if is_error else None
        self.log_list.controls.append(ft.Text(msg, color=color))
        self.log_list.update()

    def _gui_error(self, where: str, ex: Exception):
        """GUI пишет СВОИ ошибки в лог: что сломалось и почему."""
        import traceback
        self.log_message(f"[GUI] {where}: {ex}", is_error=True)
        self.log_message(traceback.format_exc(), is_error=True)

    def _play_system_sound(self, sound_name: str = "MB_ICONASTERISK") -> None:
        """Системный звук в фоновом потоке — не блокирует event loop GUI."""
        def _play():
            try:
                import winsound
                winsound.MessageBeep(getattr(winsound, sound_name, winsound.MB_ICONASTERISK))
            except Exception:
                pass  # не Windows / нет звуковой схемы — молча пропускаем, как и раньше
        threading.Thread(target=_play, daemon=True).start()

    def _show_slow_dialog(self, flag_attr: str, msg: str, detail: str) -> None:
        """Общий диалог «долгой загрузки» для chapter_slow и image_slow.
        flag_attr — имя флага, защищающего от повторного открытия."""
        if getattr(self, flag_attr):
            return
        setattr(self, flag_attr, True)
        self._play_system_sound("MB_ICONEXCLAMATION")
        body = msg + (f"\n\n{detail}" if detail else "")
        dlg = ft.AlertDialog(
            title=ft.Text("Долгая загрузка"),
            content=ft.Text(
                f"{body}\n\n"
                f"Рекомендуется: перезапустить в оконном режиме (--headed) "
                f"и/или проверить соединение с интернетом."
            ),
            actions=[ft.TextButton("Понятно", on_click=lambda e: self._dismiss_slow_dialog(dlg, flag_attr))],
        )
        self.page.show_dialog(dlg)

    def _dismiss_slow_dialog(self, dlg, flag_attr: str):
        setattr(self, flag_attr, False)
        self.page.pop_dialog()

    def set_status(self, text: str, is_error=False):
        self.status_text.value = text
        self.status_text.color = ft.Colors.RED if is_error else None
        self.status_text.update()

    # ---------- Прогресс ----------
    def update_progress_chapter(self, current: int, total: Optional[int] = None):
        if total is not None:
            v = current / total if total > 0 else 0
            self.chapter_bar.value = v
            self.chapter_label.value = f"Главы: {current}/{total}"
        else:
            self.chapter_bar.value = None  # неопределённый прогресс — анимация
            self.chapter_label.value = f"Глава {current}..."
        if self.page_bar.visible:   # новая глава — счётчик страниц с нуля
            self.page_bar.value = 0
            self.page_label.value = "Страницы: —"
        self.chapter_bar.update()
        self.chapter_label.update()
        self.page_bar.update()
        self.page_label.update()

    def update_progress_page(self, page: int, total: Optional[int] = None):
        if not self.page_bar.visible:   # ранобэ с иллюстрациями — возвращаем бар
            self.page_bar.visible = True
            self.page_label.visible = True
        if total is not None:
            self.page_bar.value = page / total if total > 0 else 0
            self.page_label.value = f"Страницы: {page}/{total}"
        else:
            self.page_bar.value = None
            self.page_label.value = f"Страница {page}..."
        self.page_bar.update()
        self.page_label.update()

    def hide_progress(self):
        self.progress_col.opacity = 0
        self.progress_col.update()

    def set_running_state(self, running: bool):
        self.running = running
        self.start_btn.visible = not running
        self.stop_btn.visible = running
        self.spinner.visible = running
        self.start_btn.update()
        self.stop_btn.update()
        self.spinner.update()

    # ---------- Запуск бэкенда ----------
    def start_download(self, e):
        if self.running:
            return
        if self.auth_process is not None and self.auth_process.poll() is None:
            self.log_message("Сначала закрой окно браузера логина — профиль занят.", is_error=True)
            return
        self.config["last_url"] = self.url_field.value
        self.config["last_output"] = self.output_field.value
        self.config["headed"] = bool(self.headed_check.value)
        self.config["debug"] = bool(self.debug_check.value)
        self.config["cbz"] = bool(self.cbz_check.value)
        self.config["clean_failed_temps"] = bool(self.clean_temps_check.value)
        self.config["show_log"] = bool(self.show_log_check.value)
        self.config["subfolder"] = bool(self.subfolder_check.value)
        save_config(self.config)

        self.log_list.controls.clear()
        self.hide_progress()
        self.files_result = []
        self.errors = []
        self.incomplete = []
        self.result_list.controls.clear()

        cmd = [sys.executable, "main.py", self.url_field.value]
        mode = self.mode_dropdown.value
        if mode:
            cmd.extend(["--mode", mode])
        if self.single_check.value:
            cmd.append("--single")
        start_ch = (self.start_chapter_field.value or "").strip()
        end_ch = (self.end_chapter_field.value or "").strip()
        count_val = (self.count_field.value or "").strip()
        if count_val:
            cmd.extend(["--count", count_val])
        if start_ch:
            if end_ch:
                cmd.extend(["--chapters", f"{start_ch}-{end_ch}"])
            elif count_val:
                cmd.extend(["--chapters", f"{start_ch}-"])   # открыто до конца, реально качает count
            else:
                cmd.extend(["--chapters", f"{start_ch}-{start_ch}"])
        start_vol = (self.start_volume_field.value or "").strip()
        end_vol = (self.end_volume_field.value or "").strip()
        if start_vol:
            cmd.extend(["--volumes", f"{start_vol}-{end_vol}" if end_vol else f"{start_vol}-{start_vol}"])
        out_path = (self.output_field.value or "").strip()
        if self.subfolder_check.value:
            sub = (self.subfolder_field.value or "").strip()
            if not sub:
                sub = self._next_title_name(out_path or "downloads")
            out_path = str(Path(out_path or "downloads") / sub)
        self.last_output_used = out_path
        if out_path:
            cmd.extend(["--output", out_path])
        override = (self.config.get("preset_override") or "").strip()
        if override:
            cmd.extend(["--preset", override])
        if self.headed_check.value:
            cmd.append("--headed")
        if self.debug_check.value:
            cmd.append("--debug")
        if not self.cbz_check.value:
            cmd.append("--no-cbz")
        if not self.clean_temps_check.value:
            cmd.append("--keep-failed-temps")

        self.log_message("Запуск: " + " ".join(cmd))
        self.set_status("Запуск процесса...")
        try:
            creationflags = 0
            if sys.platform == "win32":
                # NO_WINDOW — скрыть консоль; NEW_PROCESS_GROUP — нужен для CTRL_BREAK_EVENT в stop
                creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            # Дочерний процесс обязан писать в UTF-8, иначе cp1251 ломает декодинг
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
            env["PYTHONUNBUFFERED"] = "1"
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=creationflags,
                cwd=str(Path(__file__).parent.parent),
            )
            self.set_running_state(True)
            self.log_message(f"Процесс запущен, pid={self.process.pid}")
            self.process_thread = threading.Thread(target=self.read_output, daemon=True)
            self.process_thread.start()
            self.page.update()
        except Exception as ex:
            self._gui_error("start_download", ex)
            self.set_status(f"Ошибка: {ex}", is_error=True)
            self.set_running_state(False)

    def read_output(self):
        try:
            if self.process is None or self.process.stdout is None:
                return
            for line in iter(self.process.stdout.readline, ""):
                if not line:
                    break
                # каждую строку обрабатываем в event loop — тогда лог и прогресс рендерятся живо
                self.page.run_task(self._process_line_async, line.rstrip())
        except Exception as ex:
            self._gui_error("read_output", ex)
        finally:
            self.page.run_task(self._finish_async)

    async def _process_line_async(self, line: str):
        if line.startswith("{") and line.endswith("}"):
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                data = None
            if data is not None:
                try:
                    self.handle_event(data)
                except Exception as ex:
                    self.log_message(f"Ошибка обработки события: {ex}", is_error=True)
                return
        self.log_message(line)

    async def _finish_async(self):
        self.process_finished()

    def handle_event(self, data: dict):
        event_type = data.get("type")
        if not event_type:
            return
        if event_type == "browser_started":
            self.log_message(f"Браузер запущен (headed={data.get('headed')}, channel={data.get('channel')})")
        elif event_type == "download_started":
            self.result_list.controls.clear()    
            total = data.get("total_chapters")
            is_ranobe = data.get("content") == "ranobe"
            self._is_ranobe = is_ranobe
            self._configure_progress(is_ranobe=is_ranobe)
            if not is_ranobe:
                self.page_bar.value = 0
                self.page_label.value = "Страницы: —"
                self.page_bar.update()
                self.page_label.update()
            if total:
                self.update_progress_chapter(0, int(total))
            self.set_status("Скачивание начато...")
        elif event_type == "chapter_started":
            self._image_slow_dialog_open = False
            self._chapter_slow_dialog_open = False
            current = data.get("current")
            total = data.get("total")
            self.update_progress_chapter(int(current) if current is not None else 0,
                                         int(total) if total is not None else None)
        elif event_type == "page_saved":
            pg = data.get("page")
            total_pages = data.get("total_pages")
            self.update_progress_page(int(pg) if pg is not None else 0,
                                      int(total_pages) if total_pages is not None else None)
        elif event_type == "chapter_completed":
            ch = data.get("chapter_number")
            vol = data.get("volume")
            file_path = data.get("file_path")
            if file_path:
                self.log_message(f"Глава {ch} (том {vol}) сохранена: {file_path}")
                self.files_result.append(str(file_path))
            else:
                self.log_message(f"Глава {ch} (том {vol}) добавлена в буфер")
            self.last_chapter_info = f"том {vol}, глава {ch}"
            self.result_list.controls.append(
                ft.Text(f"✅ Глава {ch} (том {vol})", size=12)
            )
            self.result_list.update()   
        elif event_type == "epub_building":
            self.log_message("Сборка EPUB...")
            self.set_status("Собирается книга из скачанного, подождите немного...")
            self.chapter_bar.value = None  # анимация: сборка может идти долго
            self.chapter_label.value = "Сборка EPUB..."
            self.page_bar.visible = False
            self.page_label.visible = False
            self.chapter_bar.update()
            self.chapter_label.update()
            self.page_bar.update()
            self.page_label.update()
        elif event_type == "epub_completed":
            self.log_message(f"EPUB сохранён: {data.get('file_path')}")
        elif event_type == "chapter_slow":
            msg = data.get("message", "")
            self.log_message(f"⏳ {msg}")
            self.set_status(f"Глава {data.get('chapter_number')} грузится долго...")
            self._show_slow_dialog("_chapter_slow_dialog_open", msg, "")

        elif event_type == "image_slow":
            ch = data.get("chapter_number")
            pg = data.get("page")
            msg = data.get("message", "")
            self.log_message(f"⏳ Глава {ch}, стр. {pg}: {msg}")
            self._show_slow_dialog("_image_slow_dialog_open", msg, f"Глава {ch}, страница {pg}.")

        elif event_type == "chapter_incomplete":
            msg = data.get("message", "")
            self.log_message(f"⚠️ {msg}", is_error=True)
            if data.get("saved"):
                self.incomplete.append(msg)
            self.result_list.controls.append(
                ft.Text(f"❌ {msg}", size=12, color=ft.Colors.RED)
            )
            self.result_list.update()   

        elif event_type == "chapter_finalizing":
            msg = data.get("message", "Сборка...")
            self.page_label.value = msg
            self.page_bar.value = 1.0
            self.page_label.update()
            self.page_bar.update()
        elif event_type == "error":
            msg = data.get("message")
            trace = data.get("traceback")
            self.log_message(f"Ошибка: {msg}", is_error=True)
            if trace:
                self.log_message(str(trace), is_error=True)
            if msg:
                self.errors.append(str(msg))
            self.set_status(f"Ошибка: {msg}", is_error=True)
        elif event_type == "download_completed":
            files = [str(f) for f in data.get("files", [])]
            if files:
                self.files_result = files
            errs = data.get("errors", [])
            if errs:
                self.errors.extend(str(x) for x in errs)
            total = data.get("total_chapters")
            if total:
                self.log_message(f"Завершено. Всего глав: {total}")
            self.show_final_result()

    def _dismiss_image_slow(self, dlg):
        self._image_slow_dialog_open = False
        self.page.pop_dialog()

    def show_final_result(self):
        if self._stop_dialog is not None and self._stop_dialog.open:
            self._stop_dialog.open = False
            self._stop_dialog.update()
            self._stop_dialog = None
            self._image_slow_dialog_open = False
            self._chapter_slow_dialog_open = False
        self._play_system_sound("MB_ICONHAND" if self.errors else "MB_ICONASTERISK")
        last = f" Последняя: {self.last_chapter_info}." if self.last_chapter_info else ""
        where = self.last_output_used or self.output_field.value
        if self.files_result:
            self.set_status(f"Готово.{last} Сохранено в: {where}")
        elif self.errors:
            self.set_status(f"Ошибка: {self.errors[0]}", is_error=True)
        else:
            self.set_status("Завершено, но результат не определён", is_error=True)
        self.hide_progress()
        self.set_running_state(False)
        if not self.files_result and not self.errors:
            return

        lines: list = []
        if self.files_result:
            lines.append(ft.Text(f"✅ Сохранено ({len(self.files_result)}):", weight=ft.FontWeight.BOLD))
            for f in self.files_result:
                lines.append(ft.Text(f"   {Path(f).name}", size=12))
        if self.incomplete:
            if self.files_result:
                lines.append(ft.Divider(height=8))
            lines.append(ft.Text(f"⚠️ Неполные ({len(self.incomplete)}):", weight=ft.FontWeight.BOLD, color=ft.Colors.YELLOW))
            for m in self.incomplete:
                lines.append(ft.Text(f"   {m}", size=12, color=ft.Colors.YELLOW))
        if self.errors:
            if self.files_result or self.incomplete:
                lines.append(ft.Divider(height=8))
            lines.append(ft.Text(f"❌ Провалено ({len(self.errors)}):", weight=ft.FontWeight.BOLD, color=ft.Colors.RED))
            for e in self.errors:
                lines.append(ft.Text(f"   {e}", size=12, color=ft.Colors.RED))

        title = "Завершено с ошибками" if self.errors else ("Завершено с предупреждениями" if self.incomplete else "Успех")
        dlg = ft.AlertDialog(
            title=ft.Text(title),
            content=ft.Container(
                content=ft.Column(controls=lines, spacing=4, scroll=ft.ScrollMode.AUTO),
                width=520,
                height=min(400, 60 + len(lines) * 24),
            ),
            actions=[ft.TextButton("OK", on_click=lambda e: self.page.pop_dialog())],
        )
        self.page.show_dialog(dlg)

    def process_finished(self):
        if self.process is not None:
            try:
                ret = self.process.wait(timeout=10)
            except Exception:
                ret = None
            if ret is not None and ret != 0 and not self.errors:
                self.log_message(f"Процесс завершился с ошибкой (код {ret})", is_error=True)
                self.set_status(f"Ошибка (код {ret})", is_error=True)
        self.set_running_state(False)
        self.hide_progress()
        self.page.update()

    def stop_download(self, e):
        """Стоп без потери данных: флаг-файл + мягкий сигнал. Никакого kill."""
        if self.process is None:
            return
        try:
            (Path(__file__).parent.parent / ".stop_download").write_text("stop", encoding="utf-8")
        except Exception as ex:
            self._gui_error("stop_download", ex)
        try:
            if sys.platform == "win32":
                self.process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.process.send_signal(signal.SIGINT)
        except Exception:
            pass
        self.log_message("Остановка: сохраняю уже скачанное (ранобэ соберётся в EPUB)...")
        self.set_status("Остановка...")
        dlg = ft.AlertDialog(
            title=ft.Text("Остановка"),
            content=ft.Text(
                "Докачивается текущая глава и собирается CBZ/EPUB. "
                "Если прервать процесс сейчас — потеряется всё скачанное. "
                "Окно можно закрыть (ОК) — остановка уже идёт."
            ),
            actions=[
                ft.TextButton("OK", on_click=lambda ev: self.page.pop_dialog()),
                ft.Button("Прервать сейчас", color=ft.Colors.RED, on_click=lambda ev: self._force_kill(dlg)),
            ],
        )
        self._stop_dialog = dlg
        self.page.show_dialog(dlg)

    def _force_kill(self, dlg):
        """«Прервать сейчас»: осознанный kill. Буфер ранобэ теряется."""
        try:
            dlg.open = False
            dlg.update()
        except Exception:
            pass
        self._stop_dialog = None
        proc = self.process
        if proc is not None:
            def _kill_and_clean():
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
                lock = Path(__file__).parent.parent / "chrome_profile" / ".downloader.lock"
                try:
                    if lock.exists():
                        lock.unlink()
                except Exception:
                    pass
            threading.Thread(target=_kill_and_clean, daemon=True).start()
        self.errors.append("Процесс прерван принудительно")
        self.set_status("Процесс прерван принудительно. Текущая глава не сохранена.", is_error=True)

    # ---------- Ручной логин (общий профиль) ----------
    def on_auth_click(self, e):
        """Кнопка-переключатель: открыть браузер логина или завершить логин."""
        if self.auth_process is not None and self.auth_process.poll() is None:
            self.stop_auth(e)
        else:
            self.start_auth(e)

    def start_auth(self, e):
        self.log_message("Открываю браузер для логина. Залогинься на нужных сайтах и закрой окно.")
        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text("Вход в аккаунты"),
            modal=True,
            content=ft.Text(
                "Откроется окно браузера с общим профилем.\n"
                "1. Залогинься на нужных сайтах.\n"
                "2. Нажми «Завершить логин»(кнопка вместо «Залогиниться»).\n"
                "Куки сохранятся в профиль автоматически."
            ),
            actions=[ft.TextButton("Понятно", on_click=lambda ev: self.page.pop_dialog())],
        ))
        try:
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW  # прячем консоль, браузер виден
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
            env["PYTHONUNBUFFERED"] = "1"
            self.auth_process = subprocess.Popen(
                [sys.executable, "scripts/gui_auth.py"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                env=env,
                creationflags=creationflags,
                cwd=str(Path(__file__).parent.parent),
            )
            self.auth_btn.visible = False
            self.auth_stop_btn.visible = True
            self.page.update()
            threading.Thread(target=self._auth_watch, daemon=True).start()
        except Exception as ex:
            self._gui_error("start_auth", ex)

    def stop_auth(self, e):
        """Пишет .auth_stop — gui_auth сам закроется и корректно снимет lock.
        Если за 7 сек не вышел — kill и чистим lock вручную."""
        proc = self.auth_process
        if proc is None or proc.poll() is not None:
            self._reset_auth_btn()
            return
        self.log_message("Завершаю логин...")
        stop_file = Path(__file__).parent.parent / "chrome_profile" / ".auth_stop"
        try:
            stop_file.parent.mkdir(parents=True, exist_ok=True)
            stop_file.write_text("stop", encoding="utf-8")
        except Exception as ex:
            self._gui_error("stop_auth", ex)

        def wait_exit():
            try:
                proc.wait(timeout=7)
            except Exception:
                proc.kill()
                lock = Path(__file__).parent.parent / "chrome_profile" / ".downloader.lock"
                try:
                    if lock.exists():
                        lock.unlink()
                except Exception:
                    pass

        threading.Thread(target=wait_exit, daemon=True).start()

    def _reset_auth_btn(self):
        self.auth_btn.visible = True
        self.auth_stop_btn.visible = False
        self.page.update()

    def _auth_watch(self):
        """Daemon-поток: читает вывод логина без executor, чтобы консоль не блокировалась при выходе."""
        proc = self.auth_process
        if proc is None or proc.stdout is None:
            return
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            line = line.rstrip()
            if line:
                self.page.run_task(self._log_async, f"[auth] {line}")
        self.page.run_task(self._log_async, "Браузер закрыт. Куки сохранены в профиль.")
        self.page.run_task(self._reset_auth_btn_async)

    async def _log_async(self, msg: str):
        self.log_message(msg)

    async def _reset_auth_btn_async(self):
        self._reset_auth_btn()
        
    # ---------- Пресеты: модальный диалог, а не второе окно ----------
    def open_preset_window(self, e):
        try:
            from frontend.preset_window import PresetWindow
            
            # Передаем ТЕКУЩУЮ живую страницу
            preset_window = PresetWindow(self.page)
            
            dlg = ft.AlertDialog(
                title=ft.Text("Редактор пресетов"),
                modal=True,
                content=ft.Container(
                    content=preset_window.content,
                    width=1080,
                    height=700,
                    padding=15,
                    border=ft.Border.all(1, ft.Colors.OUTLINE),
                    border_radius=10,
                ),
                actions=[
                    ft.Button("Закрыть", on_click=lambda e: self.close_preset_dialog(dlg))
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            
            self.page.show_dialog(dlg)
            preset_window.refresh_preset_list()
        except Exception as ex:
            self._gui_error("open_preset_window", ex)

    def close_preset_dialog(self, dlg):
        self.page.pop_dialog()

    def on_close(self):
        self.config["last_url"] = self.url_field.value
        self.config["last_output"] = self.output_field.value
        self.config["headed"] = self.headed_check.value
        self.config["debug"] = self.debug_check.value
        self.config["cbz"] = self.cbz_check.value
        self.config["clean_failed_temps"] = self.clean_temps_check.value
        self.config["show_log"] = self.show_log_check.value
        self.config["subfolder"] = self.subfolder_check.value
        save_config(self.config)

def main(page: ft.Page):
    app = MainApp(page)
    page.on_close = app.on_close

if __name__ == "__main__":
    ft.run(main)