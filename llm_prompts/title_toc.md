ТИП СТРАНИЦЫ: TITLE (страница тайтла) и/или TOC (список глав).
Верни JSON ТОЛЬКО со следующими ролями:
toc_link — вкладка «Главы» на тайтле
toc_container — контейнер списка глав
chapter_link — ссылки глав в оглавлении (матчит все)
hidden_chapters_btn — разворот скрытых групп глав («Скрыто», «Показать ещё»)
volume_regex — массив regex тома из href ссылок chapter_link, номер в группе 1
chapter_num_regex — массив regex главы из href ссылок chapter_link, номер в группе 1
Также верни общие роли (см. common.md):
dismiss_texts, dismiss_remove_selectors, banned_paths, marker_groups

СПЕЦИФИЧНЫЕ ПРАВИЛА:
- chapter_link ОБЯЗАН быть <a> или содержать [href]. Контейнер → добавь " a".
- chapter_num_regex не захватывает внутренние ID сайтов. Если число в пути ≠ номер главы → [].
- volume_regex / chapter_num_regex: номер в группе 1, дроби \d+(?:.\d+)?, без якорей ^$.

ФОРМАТ:
{ "toc_link": ..., "toc_container": ..., "chapter_link": ..., "hidden_chapters_btn": ...,
"volume_regex": [...], "chapter_num_regex": [...],
"dismiss_texts": [...], "dismiss_remove_selectors": [...],
"banned_paths": [...], "marker_groups": [[...]] }
<<<ВСТАВЬ HTML ИЛИ ОПИШИ РАЗМЕТКУ: TITLE / TOC>>>