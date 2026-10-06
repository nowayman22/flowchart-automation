"""Tests for the two-token expression evaluator used by Count/PNG/OCR steps."""

from __future__ import annotations

import pytest

from flowchart_automation.util.expressions import evaluate


@pytest.mark.parametrize(
    ("expression", "value", "expected"),
    [
        ("> 5", 6, True),
        ("> 5", 5, False),
        ("< 5", 4, True),
        ("< 5", 5, False),
        (">= 5", 5, True),
        (">= 5", 4, False),
        ("<= 5", 5, True),
        ("<= 5", 6, False),
        ("== 5", 5, True),
        ("== 5", 4, False),
        ("!= 5", 4, True),
        ("!= 5", 5, False),
    ],
)
def test_operators(expression: str, value: int, expected: bool) -> None:
    assert evaluate(expression, value) is expected


def test_accepts_float_values() -> None:
    assert evaluate("> 0.5", 0.75) is True
    assert evaluate("< 0.5", 0.25) is True


def test_accepts_float_rhs() -> None:
    assert evaluate(">= 1.5", 2) is True


def test_extra_whitespace_is_tolerated() -> None:
    assert evaluate("  >=   5  ", 6) is True


def test_negative_threshold() -> None:
    assert evaluate("< 0", -1) is True


@pytest.mark.parametrize("expression", ["", "5", ">= 5 extra", ">="])
def test_malformed_expression_raises(expression: str) -> None:
    with pytest.raises(ValueError, match="must be"):
        evaluate(expression, 1)


def test_unknown_operator_raises() -> None:
    with pytest.raises(ValueError, match="Unknown operator"):
        evaluate("=> 5", 1)


def test_non_numeric_rhs_raises() -> None:
    with pytest.raises(ValueError):
        evaluate("> abc", 1)


def test_comparison_is_numeric_not_lexical() -> None:
    """'10' must not compare as less than '9'."""
    assert evaluate("> 9", 10) is True
