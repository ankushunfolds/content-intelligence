from __future__ import annotations


def compact_number(value: int | float | None) -> str:
    """183421 -> '183K'. Used anywhere a raw count would be noise."""
    if value is None:
        return "—"
    value = float(value)
    for threshold, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if abs(value) >= threshold:
            scaled = value / threshold
            return f"{scaled:.1f}".rstrip("0").rstrip(".") + suffix
    return str(int(value))


def multiplier(ratio: float | None) -> str:
    """1.0 -> '1×'; 4.25 -> '4.3×'."""
    if ratio is None:
        return "—"
    return f"{ratio:.1f}".rstrip("0").rstrip(".") + "×"


def percent(fraction: float | None) -> str:
    """0.43 -> '+43%'."""
    if fraction is None:
        return "—"
    return f"{fraction * 100:+.0f}%"
