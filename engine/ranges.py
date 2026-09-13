"""
engine/ranges.py — парсинг диапазонов глав и страниц.

Формат (документируется в --help):
    "5"    -> только 5
    "5-10" -> с 5 по 10 включительно
    "5-"   -> с 5 до конца
    "-10"  -> с начала до 10
    None/""-> всё

Пользовательской валидации нет: кривой формат -> ValueError (fail-fast).
"""
from typing import Any, Callable, Optional, Tuple


def parse_range(
    spec: Optional[str],
    cast: Callable[[str], Any] = float,
) -> Tuple[Optional[Any], Optional[Any]]:
    """Разбирает строку диапазона в пару (start, end)."""
    if spec is None:
        return None, None
    spec = spec.strip()
    if not spec:
        return None, None
    if "-" not in spec:
        value = cast(spec)
        return value, value
    start_s, end_s = spec.split("-", 1)
    start = cast(start_s) if start_s.strip() else None
    end = cast(end_s) if end_s.strip() else None
    return start, end


def parse_chapters(spec: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    """Диапазон глав (дробные номера допустимы)."""
    return parse_range(spec, float)


def parse_pages(spec: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    """Диапазон страниц (целые)."""
    return parse_range(spec, int)


if __name__ == "__main__":
    assert parse_chapters(None) == (None, None)
    assert parse_chapters("") == (None, None)
    assert parse_chapters("5") == (5.0, 5.0)
    assert parse_chapters("5-10") == (5.0, 10.0)
    assert parse_chapters("5-") == (5.0, None)
    assert parse_chapters("-10") == (None, 10.0)
    assert parse_chapters("5.5") == (5.5, 5.5)
    assert parse_pages("1-20") == (1, 20)
    try:
        parse_pages("abc")
        raise AssertionError("ожидался ValueError")
    except ValueError:
        pass
    print("ranges tests passed")