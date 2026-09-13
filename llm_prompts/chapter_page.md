ТИП СТРАНИЦЫ: CHAPTER_PAGE — глава в постраничном режиме.
Верни JSON ТОЛЬКО со следующими ролями:
image_selector — картинка текущей страницы
page_select — <select> СТРАНИЦ в футере (не глав и не томов)
next_page_button — кнопка «следующая страница» внутри главы
loading_indicator — исчезающий спиннер
Также верни общие роли (см. common.md):
dismiss_texts, dismiss_remove_selectors, banned_paths, marker_groups

СПЕЦИФИЧНЫЕ ПРАВИЛА:
- image_selector ОБЯЗАН содержать <img> или [data-page]. Пользователь дал div? → добавь " img".
- lazy_attr — ТОЛЬКО имя атрибута (строка "data-src") или null. Селектор → null.
- page_select — именно <select>, а НЕ текстовый блок 'страница 5 из 20'.
- На 1-страничной главе page_select / next_page_button легитимно = 0 (пейджер скрыт).

ФОРМАТ:
{ "image_selector": ..., "page_select": ..., "next_page_button": ..., "loading_indicator": ...,
"dismiss_texts": [...], "dismiss_remove_selectors": [...],
"banned_paths": [...], "marker_groups": [[...]] }
<<<ВСТАВЬ HTML ИЛИ ОПИШИ РАЗМЕТКУ: ГЛАВА (PAGE)>>>