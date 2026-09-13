ТИП СТРАНИЦЫ: CHAPTER_WEB — глава в режиме «лента».
Верни JSON ТОЛЬКО со следующими ролями:
content_container — контейнер главы (только текст/картинки)
image_selector — картинки страниц/иллюстраций (без аватарок/иконок/рекламы/превью)
text_selector — абзацы <p> текста ранобэ строго внутри content_container
lazy_attr — атрибут реального URL до lazy-load; пустая строка, если src
settings_button — шестерёнка настроек ридера (не настройки сайта)
web_mode_toggle / page_mode_toggle — тумблеры режимов чтения
navbar_hover_selector — навбар, hover открывает меню ридера
meta_text_selector — элемент с текстом «Том X Глава Y»
meta_text_template — точный шаблон этого текста с {volume} и {number}
next_chapter_btn / prev_chapter_btn — навигация по главам (массив; URL после клика ведёт на другую главу, а не ?page=2)
back_to_toc_btn — ссылка возврата на страницу тайтла
loading_indicator — исчезающий спиннер
chapter_name_selector — название главы (опционально)
Также верни общие роли (см. common.md):
dismiss_texts, dismiss_remove_selectors, banned_paths, marker_groups

СПЕЦИФИЧНЫЕ ПРАВИЛА:
- image_selector ОБЯЗАН содержать <img> или [data-page]. Пользователь дал div? → добавь " img".
- lazy_attr — ТОЛЬКО имя атрибута (строка "data-src") или null. Селектор → null.
- ИСКЛЮЧЕНИЕ: кнопка «следующая СТРАНИЦА» (title/aria «Следующая страница») МОЖЕТ стоять в next_chapter_btn — в web-режиме и на последней странице она ведёт на следующую главу. Это НЕ противоречие.
- Если роль присутствует в нескольких документах (image_selector в web и page) — селектор обязан работать во всех; иначе бери вариант CHAPTER_WEB.

ФОРМАТ:
{  "content_container": ...,  "image_selector": ...,  "text_selector": ...,  "lazy_attr": ...,
 "settings_button": ...,  "web_mode_toggle": ...,  "page_mode_toggle": ...,  "navbar_hover_selector": ...,
 "meta_text_selector": ...,  "meta_text_template": "Том {volume} Глава {number}",
 "next_chapter_btn": [...],  "prev_chapter_btn": ...,  "back_to_toc_btn": ...,
 "loading_indicator": ...,  "chapter_name_selector": ...,
 "dismiss_texts": [...], "dismiss_remove_selectors": [...],
 "banned_paths": [...], "marker_groups": [[...]] }
<<<ВСТАВЬ HTML ИЛИ ОПИШИ РАЗМЕТКУ: ГЛАВА (WEB)>>>