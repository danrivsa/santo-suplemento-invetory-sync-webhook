from __future__ import annotations

import logging

import httpx

from src.config import Settings
from src.models import HoldedStockAvailability

logger = logging.getLogger(__name__)

HOLDED_BASE_URL = "https://api.holded.com/api/v2"


def get_available_stock(product_id: str, config: Settings) -> float:
    """Fetch a product's stock availability from Holded.

    ``GET /products/{productId}/stock`` answers with ``available`` (total minus
    stock reserved by pending sales orders) as a decimal string, which is the
    value pushed to Wink. Any failure propagates so the webhook answers 500 and
    Holded retries the delivery.
    """
    with httpx.Client(timeout=10) as client:
        response = client.get(
            f"{HOLDED_BASE_URL}/products/{product_id}/stock",
            headers={
                "Authorization": f"Bearer {config.holded_api_key}",
                "Accept": "application/json",
            },
        )

    response.raise_for_status()
    availability = HoldedStockAvailability.model_validate(response.json())
    available = float(availability.available)
    logger.info(
        "Holded availability for product_id=%s: available=%s total=%s reserved=%s in_transit=%s",
        product_id,
        availability.available,
        availability.total,
        availability.reserved,
        availability.in_transit,
    )
    return available
