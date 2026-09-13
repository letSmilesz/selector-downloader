Ты собираешь пресет загрузчика манги/ранобэ из готовых фрагментов. Анализа HTML НЕТ — только склейка.
ВХОД: JSON-фрагменты по страницам (TITLE/TOC, CHAPTER_WEB или CHAPTER_RANOBE, CHAPTER_PAGE) + имя сайта и домен.
Выход: СТРОГО один JSON-объект формата пресета, без комментариев.

ФОРМАТ ВЫВОДА:
{
  "name": "<имя сайта строчными>",
  "domains": ["<домен без протокола и пути>"],
  "default_mode": "web|page",
  "content": "manga|ranobe",
  "banned_paths": ["<подстроки пути заглушек из фрагментов>"],
  "selectors": { все селекторные роли из фрагментов },
  "meta": {
    "volume_regex": [...], "chapter_num_regex": [...],
    "meta_text_selector": ..., "meta_text_template": ..., "chapter_name_selector": ...
  },
  "rate_limit": { "marker_groups": [["лимит", "превышен"], ["повторите", "позже"]] }
}

ПРАВИЛА СБОРКИ:
1. Не выдумывай селекторы — бери ТОЛЬКО из фрагментов.
2. Роль отсутствует во фрагменте или равна null → не включать в итог.
3. `content` = "ranobe", если во фрагменте главы непустой `text_selector`, иначе "manga".
4. `default_mode` = "page", если во фрагменте главы есть `next_page_button` или `page_select`; иначе "web".
5. `dismiss_texts`, `dismiss_remove_selectors`, `navbar_hover_selector`, `settings_button`, `web_mode_toggle`, `page_mode_toggle`, `page_select`, `next_page_button`, `loading_indicator`, `hidden_chapters_btn`, `back_to_toc_btn`, `prev_chapter_btn`, `next_chapter_btn`, `toc_link`, `toc_container`, `chapter_link`, `content_container`, `image_selector`, `text_selector`, `lazy_attr`, `chapter_name_selector` → клади в `selectors`.
6. `volume_regex`, `chapter_num_regex`, `meta_text_selector`, `meta_text_template`, `chapter_name_selector` → клади в `meta`.
7. `banned_paths` → клади на ВЕРХНИЙ уровень пресета (не в `selectors`).
8. `marker_groups` → клади в `rate_limit.marker_groups` как массив массивов строк.
9. Если одна и та же роль встречается в нескольких фрагментах (например, `dismiss_texts` в TITLE и CHAPTER) — бери значение из фрагмента главы, если оно не пустое; иначе из тайтла.
10. `name` и `domains` бери из входных данных пользователя, не выдумывай.

Вставь фрагменты ниже:
<<<ФРАГМЕНТ TITLE/TOC>>>
<<<ФРАГМЕНТ ГЛАВА (WEB) ИЛИ ГЛАВА (РАНОБЭ)>>>
<<<ФРАГМЕНТ ГЛАВА (PAGE), если есть>>>