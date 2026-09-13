import random

def get_delay(delay_type: str = "random",
              delay_fixed: float = 0.5,
              delay_min: float = 0.5,
              delay_max: float = 2.5) -> float:
    """Возвращает задержку в секундах."""
    if delay_type == "random":
        return random.uniform(delay_min, delay_max)
    else:
        return delay_fixed
