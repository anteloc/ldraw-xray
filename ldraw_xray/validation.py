"""Small input checks shared by recipes, layers, styles, and cameras."""
from __future__ import annotations

import math
from collections.abc import Mapping


def fields(value, allowed, *, required=(), name="object") -> dict:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    unknown = value.keys() - set(allowed)
    missing = set(required) - value.keys()
    if unknown:
        raise ValueError(f"Unknown {name} fields: {', '.join(sorted(map(str, unknown)))}")
    if missing:
        raise ValueError(f"{name} needs: {', '.join(sorted(missing))}")
    return dict(value)


def text(value, name, *, limit=None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")
    if limit is not None and len(value) > limit:
        raise ValueError(f"{name} must have at most {limit} characters")
    return value


def number(value, name, *, minimum=None, maximum=None, positive=False, integer=False):
    types = (int,) if integer else (int, float)
    if isinstance(value, bool) or not isinstance(value, types) or not math.isfinite(value):
        kind = "an integer" if integer else "a finite number"
        raise ValueError(f"{name} must be {kind}")
    if positive and value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return value


def vector(value, name, *, size=3, nonzero=False) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise ValueError(f"{name} must contain {size} numbers")
    result = tuple(float(number(item, name)) for item in value)
    if nonzero and math.hypot(*result) < 1e-12:
        raise ValueError(f"{name} must be non-zero")
    return result


def choice(value, choices, name):
    if value not in choices:
        raise ValueError(f"{name} must be one of: {', '.join(choices)}")
    return value


def boolean(value, name) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be true or false")
    return value
