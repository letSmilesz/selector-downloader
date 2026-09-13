"""
scripts/auth_browser.py — разовая подготовка профиля: авторизация + режим чтения.

Куки и настройки сайта сохраняются в chrome_profile/ и используются
всеми последующими headless-запусками.

Запуск:
    python -m scripts.auth_browser "https://mangalib.me"
    python -m scripts.auth_browser "https://rumix.me"
"""
import sys

from browser.driver import BrowserSession


def main(site_url: str):
    print(f"\n{'='*64}")
    print("ПОДГОТОВКА ПРОФИЛЯ (делается один раз на сайт):")
    print("1. В открывшемся браузере зайди на сайт")
    print("2. Если нужно — авторизуйся (логин/пароль, капча)")
    print("3. Открой ЛЮБУЮ главу любого тайтла")
    print("4. В настройках читалки переключи режим чтения на")
    print("   'Веб' / 'Длинная лента' (вертикальная лента)")
    print("5. Убедись, что лента с картинками загрузилась")
    print("6. Вернись сюда и нажми ENTER")
    print(f"{'='*64}\n")

    with BrowserSession(headed=True, channel="chrome") as session:
        session.goto(site_url)
        input("Нажми ENTER после подготовки...")

    print("✅ Профиль подготовлен. Настройки сохранены в chrome_profile/")
    print("Теперь headless-запуски будут видеть сайт в веб-режиме.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.auth_browser <site_url>")
        sys.exit(1)
    main(sys.argv[1])