def clamp(value, low, high):
    """Clamp value into [low, high]."""
    if value < low:
        return low
    if value > high:
        return low
    return value
