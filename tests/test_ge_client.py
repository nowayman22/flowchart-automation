"""Tests for the OSRS Grand Exchange client.

Network calls are never made: the parsing helpers are exercised by
monkeypatching the private ``_get``.
"""

from __future__ import annotations

import pytest

from flowchart_automation.integrations import ge_client

HEADERS = {"User-Agent": "test"}


# --- calculate_price --------------------------------------------------------


@pytest.mark.parametrize(
    ("strategy", "expected"),
    [
        ("Insta-Buy", 1000),
        ("+5%", 1050),
        ("-5%", 950),
        ("Custom Price", 777),
        ("Flip-Buy (use Insta-Sell)", 900),
        ("Flip-Buy (Insta-Sell + Margin)", 910),
    ],
)
def test_buy_strategies(strategy: str, expected: int) -> None:
    assert ge_client.calculate_price("buy", 1000, 900, strategy, custom_price=777, margin=10) == expected


@pytest.mark.parametrize(
    ("strategy", "expected"),
    [
        ("Insta-Sell", 900),
        ("+5%", 945),
        ("-5%", 855),
        ("Custom Price", 777),
        ("Flip-Sell (use Insta-Buy)", 1000),
        ("Flip-Sell (Insta-Buy - Margin)", 990),
    ],
)
def test_sell_strategies(strategy: str, expected: int) -> None:
    assert ge_client.calculate_price("sell", 1000, 900, strategy, custom_price=777, margin=10) == expected


def test_unknown_buy_strategy_falls_back_to_high() -> None:
    assert ge_client.calculate_price("buy", 1000, 900, "nonsense") == 1000


def test_unknown_sell_strategy_falls_back_to_low() -> None:
    assert ge_client.calculate_price("sell", 1000, 900, "nonsense") == 900


def test_anything_that_is_not_buy_is_treated_as_sell() -> None:
    assert ge_client.calculate_price("SELL", 1000, 900, "Insta-Sell") == 900


def test_percentage_results_are_truncated_to_int() -> None:
    price = ge_client.calculate_price("buy", 999, 900, "+5%")
    assert price == int(999 * 1.05)
    assert isinstance(price, int)


def test_flip_buy_margin_can_push_price_above_high() -> None:
    """Margin is added blindly; document the behaviour rather than assume it clamps."""
    assert ge_client.calculate_price("buy", 1000, 995, "Flip-Buy (Insta-Sell + Margin)", margin=50) == 1045


# --- response parsing -------------------------------------------------------


def test_fetch_mapping_indexes_by_name_and_id(monkeypatch) -> None:
    payload = [{"id": 4151, "name": "Abyssal whip", "limit": 70}]
    monkeypatch.setattr(ge_client, "_get", lambda url, headers: payload)

    mapping = ge_client.fetch_mapping(HEADERS)
    assert mapping["by_name"]["abyssal whip"]["id"] == 4151
    assert mapping["by_id"][4151]["name"] == "Abyssal whip"


def test_fetch_mapping_returns_none_for_unexpected_shape(monkeypatch) -> None:
    monkeypatch.setattr(ge_client, "_get", lambda url, headers: {"not": "a list"})
    assert ge_client.fetch_mapping(HEADERS) is None


def test_fetch_item_price_unwraps_data(monkeypatch) -> None:
    monkeypatch.setattr(ge_client, "_get", lambda url, headers: {"data": {"4151": {"high": 100, "low": 90}}})
    assert ge_client.fetch_item_price(4151, HEADERS) == {"high": 100, "low": 90}


def test_fetch_item_price_missing_id_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(ge_client, "_get", lambda url, headers: {"data": {}})
    assert ge_client.fetch_item_price(4151, HEADERS) is None


def test_fetch_all_prices(monkeypatch) -> None:
    monkeypatch.setattr(ge_client, "_get", lambda url, headers: {"data": {"1": {"high": 5}}})
    assert ge_client.fetch_all_prices(HEADERS) == {"1": {"high": 5}}


def test_fetch_all_prices_returns_none_on_error(monkeypatch) -> None:
    monkeypatch.setattr(ge_client, "_get", lambda url, headers: None)
    assert ge_client.fetch_all_prices(HEADERS) is None


def test_fetch_hourly_volumes(monkeypatch) -> None:
    monkeypatch.setattr(ge_client, "_get", lambda url, headers: {"data": {"1": {"volume": 42}}})
    assert ge_client.fetch_hourly_volumes(HEADERS) == {"1": {"volume": 42}}
