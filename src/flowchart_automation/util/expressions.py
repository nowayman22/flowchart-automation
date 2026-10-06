"""Simple two-token expression evaluator used by Count, PNG-count, and OCR steps.

Supported operators: > < >= <= == !=
Expression format: "<op> <number>"  e.g. ">= 5"
"""

from __future__ import annotations

_OPS = {
    ">": float.__gt__,
    "<": float.__lt__,
    ">=": float.__ge__,
    "<=": float.__le__,
    "==": float.__eq__,
    "!=": float.__ne__,
}


def evaluate(expression_str: str, value: int | float) -> bool:
    """Return whether *value* satisfies *expression_str*.

    Raises ValueError if the expression cannot be parsed.
    """
    parts = expression_str.split()
    if len(parts) != 2:
        raise ValueError(f"Expression must be '<op> <number>' (got {expression_str!r})")
    op_str, rhs_str = parts
    op = _OPS.get(op_str)
    if op is None:
        raise ValueError(f"Unknown operator {op_str!r}; expected one of {list(_OPS)}")
    return op(float(value), float(rhs_str))
