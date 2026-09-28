from __future__ import annotations

import logging

import httpx

from src.config import Settings
from src.models import WinkAdjustItem, WinkAdjustStockRequest, WinkSyncPriceRequest

logger = logging.getLogger(__name__)

WINK_BASE_URL = "https://api.winktienda.com"


def adjust_stock(sku: str, stock_variation: float, config: Settings) -> dict:
    """Call Wink adjust-stock-by-sku endpoint.

    Maps a Holded ``stockVariation`` to the appropriate Wink operation:
    - Positive variation  → ``add``
    - Negative variation  → ``subtract``

    The quantity is always sent as a positive integer.
    """
    quantity = abs(int(stock_variation))
    if quantity < 1:
        logger.info("Stock variation rounds to zero for sku=%s, skipping", sku)
        return {"skipped": True, "reason": "zero_quantity"}

    operation = "add" if stock_variation > 0 else "subtract"

    body = WinkAdjustStockRequest(
        items=[WinkAdjustItem(sku=sku, operation=operation, quantity=quantity)],
        inventory_ids=config.wink_inventory_id_list,
    )

    with httpx.Client(timeout=10) as client:
        response = client.post(
            f"{WINK_BASE_URL}/product-inventory/adjust-stock-by-sku",
            headers={
                "x-api-key": config.wink_api_key,
                "Content-Type": "application/json",
            },
            content=body.model_dump_json(),
        )

    response.raise_for_status()
    result = response.json()
    logger.info("Wink adjust-stock response: %s", result)
    return result


def adjust_price(sku: str, price: float, config: Settings) -> dict:
    """Call Wink update-price-by-sku endpoint.

    The price is absolute, not a delta, so re-sending the same value is idempotent.
    """
    logger.info("Updating price for sku=%s to price=%s", sku, price)

    body = WinkSyncPriceRequest(
        sku=sku,
        price=price,
        inventory_ids=config.wink_inventory_id_list,
    )

    with httpx.Client(timeout=10) as client:
        response = client.post(
            f"{WINK_BASE_URL}/product-inventory/update-price-by-sku",
            headers={
                "x-api-key": config.wink_api_key,
                "Content-Type": "application/json",
            },
            content=body.model_dump_json(),
        )

    response.raise_for_status()
    result = response.json()
    logger.info("Wink update-price response: %s", result)
    return result


def get_invenories(config: Settings) -> dict:
    with httpx.Client(timeout=10) as client:
        result = client.get(
            f"{WINK_BASE_URL}/inventories",
            headers={"x-api-key": config.wink_api_key, "Content-Type": "application/json"},
        )
        result.raise_for_status()
        print(result.json())
