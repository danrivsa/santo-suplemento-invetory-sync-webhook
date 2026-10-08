from __future__ import annotations

import logging

import httpx

from src.config import Settings
from src.models import WinkAdjustItem, WinkAdjustStockRequest, WinkSyncPriceRequest

logger = logging.getLogger(__name__)

WINK_BASE_URL = "https://api.winktienda.com"


def adjust_stock(sku: str, quantity: float, config: Settings) -> dict:
    """Call Wink adjust-stock-by-sku endpoint with the ``replace`` operation.

    The quantity is the absolute stock Holded reports (its ``available``
    availability), so Wink's existence is *set* to it instead of shifted by a
    delta. Re-sending the same value is idempotent.

    Rounded to the nearest unit and clamped at 0: Wink rejects negative values
    and would then drop the whole request instead of just this SKU.
    """
    stock = max(0, int(round(quantity)))
    if stock != quantity:
        logger.info("Rounded stock for sku=%s from %s to %d", sku, quantity, stock)

    body = WinkAdjustStockRequest(
        items=[WinkAdjustItem(sku=sku, operation="replace", quantity=stock)],
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
