"""OSRS Grand Exchange price API client.

Pure HTTP functions with no UI dependencies. All network calls are synchronous;
callers are responsible for dispatching them on a worker thread and posting
results back to the UI via root.after().

API: https://prices.runescape.wiki/api/v1/osrs/
"""

from __future__ import annotations

import json
import urllib.request

MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"
LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
HOURLY_URL = "https://prices.runescape.wiki/api/v1/osrs/1h"


def _get(url: str, headers: dict[str, str]) -> dict | list | None:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        if resp.status == 200:
            return json.loads(resp.read().decode())
    return None


def fetch_mapping(headers: dict[str, str]) -> dict | None:
    """Return item mapping as {'by_name': {...}, 'by_id': {...}} or None."""
    data = _get(MAPPING_URL, headers)
    if not isinstance(data, list):
        return None
    return {
        "by_name": {item["name"].lower(): item for item in data},
        "by_id": {item["id"]: item for item in data},
    }


def fetch_item_price(item_id: int, headers: dict[str, str]) -> dict | None:
    """Return raw price dict for a single item id, or None."""
    data = _get(f"{LATEST_URL}?id={item_id}", headers)
    if not isinstance(data, dict) or "data" not in data:
        return None
    return data["data"].get(str(item_id))


def fetch_all_prices(headers: dict[str, str]) -> dict | None:
    """Return the full latest-prices dict keyed by item id string, or None."""
    data = _get(LATEST_URL, headers)
    if not isinstance(data, dict):
        return None
    return data.get("data")


def fetch_hourly_volumes(headers: dict[str, str]) -> dict | None:
    """Return the 1-hour volume dict keyed by item id string, or None."""
    data = _get(HOURLY_URL, headers)
    if not isinstance(data, dict):
        return None
    return data.get("data")


def calculate_price(
    action_type: str,
    high_price: int,
    low_price: int,
    strategy: str,
    custom_price: int = 0,
    margin: int = 1,
) -> int:
    """Apply a buy or sell price strategy and return the final integer price.

    action_type: 'buy' or 'sell'
    high_price: the insta-buy (instant purchase) price
    low_price: the insta-sell (instant sale) price
    """
    if action_type == "buy":
        if strategy == "Insta-Buy":
            return high_price
        if strategy == "+5%":
            return int(high_price * 1.05)
        if strategy == "-5%":
            return int(high_price * 0.95)
        if strategy == "Custom Price":
            return custom_price
        if strategy == "Flip-Buy (use Insta-Sell)":
            return low_price
        if strategy == "Flip-Buy (Insta-Sell + Margin)":
            return low_price + margin
        return high_price

    else:  # sell
        if strategy == "Insta-Sell":
            return low_price
        if strategy == "+5%":
            return int(low_price * 1.05)
        if strategy == "-5%":
            return int(low_price * 0.95)
        if strategy == "Custom Price":
            return custom_price
        if strategy == "Flip-Sell (use Insta-Buy)":
            return high_price
        if strategy == "Flip-Sell (Insta-Buy - Margin)":
            return high_price - margin
        return low_price
