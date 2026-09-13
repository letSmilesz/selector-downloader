ТИП СТРАНИЦЫ: CHAPTER_RANOBE — глава ранобэ с текстом (обычно «лента»).
Верни JSON ТОЛЬКО со следующими ролями:
content_container — контейнер главы (только текст, БЕЗ навигации/комментов/рекламы)
text_selector — абзацы <p> текста строго внутри content_container
image_selector — иллюстрации внутри главы (если нет — null)
lazy_attr — атрибут реального URL до lazy-load; пустая строка, если src
next_chapter_btn / prev_chapter_btn — навигация по главам (массив; URL после клика ведёт на другую главу, а не ?page=2)
back_to_toc_btn — ссылка возврата на страницу тайтла
meta_text_selector — элемент с текстом «Том X Глава Y» (или формат сайта)
meta_text_template — точный шаблон этого текста с {volume} и {number}
chapter_name_selector — название главы (опционально)
Также верни общие роли (см. common.md):
dismiss_texts, dismiss_remove_selectors, banned_paths, marker_groups

СПЕЦИФИЧНЫЕ ПРАВИЛА:
- image_selector ОБЯЗАН содержать <img> или [data-page]. Пользователь дал div? → добавь " img".
- lazy_attr — ТОЛЬКО имя атрибута (строка "data-src") или null. Селектор → null.
- meta_text_template ОБЯЗАН содержать хотя бы один плейсхолдер: {volume} и/или {number}.
- content_container: только текст/картинки главы, БЕЗ навигации/комментов/рекламы.

ФОРМАТ:
{  "content_container": ...,  "text_selector": ...,  "image_selector": ...,  "lazy_attr": ...,
 "next_chapter_btn": [...],  "prev_chapter_btn": ...,  "back_to_toc_btn": ...,
 "meta_text_selector": ...,  "meta_text_template": "Том {volume} Глава {number}",
 "chapter_name_selector": ...,
 "dismiss_texts": [...], "dismiss_remove_selectors": [...],
 "banned_paths": [...], "marker_groups": [[...]] }
<<<ВСТАВЬ HTML ИЛИ ОПИШИ РАЗМЕТКУ: ГЛАВА (РАНОБЭ)>>>