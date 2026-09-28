from __future__ import annotations

import base64
import json
import logging

from src.config import Settings, get_settings
from src.models import HoldedProductPayload, HoldedStockPayload
from src.signature import verify_signature
from src.wink_client import adjust_price, adjust_stock, get_invenories

logger = logging.getLogger()
logger.setLevel(logging.INFO)

EVENT_STOCK_UPDATE = "stock.update"
EVENT_PRODUCT_UPDATE = "product.update"


def _extract_body(event: dict) -> bytes:
    body = event.get("body", "")
    if event.get("isBase64Encoded"):
        return base64.b64decode(body)
    if isinstance(body, str):
        return body.encode()
    return body


def _extract_header(event: dict, name: str) -> str:
    headers = event.get("headers", {})
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value or ""
    return ""


def _extract_price_targets(payload: HoldedProductPayload) -> list[tuple[str, float]]:
    """Collect the ``(sku, price)`` pairs to push to Wink for a product.update event.

    Variants win over the product itself: Wink tracks one SKU per variant, so the
    product-level SKU is only used when the product has no priced variants.
    Duplicate SKUs and SKUs without a usable price are dropped.
    """
    targets: list[tuple[str, float]] = []
    seen: set[str] = set()

    def add(sku: str | None, price: float | None) -> None:
        clean_sku = (sku or "").strip()
        if not clean_sku or price is None or price < 0 or clean_sku in seen:
            return
        seen.add(clean_sku)
        targets.append((clean_sku, price))

    for variant in payload.variants:
        add(variant.sku, variant.price)

    if not targets:
        add(payload.sku, payload.price)

    return targets


def _handle_stock_update(raw_body: bytes, config: Settings) -> tuple[int, dict]:
    payload = HoldedStockPayload.model_validate_json(raw_body)
    logger.info(
        "Received stock.update for sku=%s variation=%.2f",
        payload.sku,
        payload.stock_variation,
    )

    if not payload.sku:
        logger.warning("Empty sku in payload, skipping")
        return 400, {"error": "Missing sku"}

    if payload.stock_variation == 0:
        logger.info("Stock variation is zero, skipping")
        return 200, {"status": "skipped", "reason": "zero_variation"}

    result = adjust_stock(
        sku=payload.sku,
        stock_variation=payload.stock_variation,
        config=config,
    )

    return 200, {"status": "ok", "result": result}


def _handle_product_update(raw_body: bytes, config: Settings) -> tuple[int, dict]:
    payload = HoldedProductPayload.model_validate_json(raw_body)
    targets = _extract_price_targets(payload)

    if not targets:
        logger.warning("No sku with price in product.update payload for id=%s, skipping", payload.id)
        return 200, {"status": "skipped", "reason": "no_price_targets"}

    logger.info("Received product.update for id=%s with %d sku(s) to price-sync", payload.id, len(targets))

    results: list[dict] = []
    failed = 0
    for sku, price in targets:
        try:
            result = adjust_price(sku=sku, price=price, config=config)
        except Exception:
            logger.exception("Failed to sync price for sku=%s", sku)
            failed += 1
            results.append({"sku": sku, "status": "error"})
        else:
            results.append({"sku": sku, "status": "ok", "result": result})

    if failed:
        # Price is absolute, so a Holded retry re-applies the successful SKUs harmlessly.
        return 500, {
            "status": "error",
            "synced": len(targets) - failed,
            "failed": failed,
            "results": results,
        }

    return 200, {"status": "ok", "synced": len(targets), "results": results}


def lambda_handler(event: dict, context: object) -> dict:  # noqa: ARG001
    try:
        config = get_settings()

        raw_body = _extract_body(event)

        signature = _extract_header(event, "x-holded-webhook-signature")
        if not signature:
            logger.warning("Missing webhook signature header")
            return _response(401, {"error": "Missing signature"})

        if not verify_signature(raw_body, signature, config.holded_webhook_secret):
            logger.warning("Invalid webhook signature")
            return _response(401, {"error": "Invalid signature"})

        event_type = _extract_header(event, "x-holded-webhook-event")

        if event_type == EVENT_STOCK_UPDATE:
            status_code, body = _handle_stock_update(raw_body, config)
        elif event_type == EVENT_PRODUCT_UPDATE:
            status_code, body = _handle_product_update(raw_body, config)
        else:
            logger.info("Ignoring unsupported webhook event: %s", event_type or "<missing>")
            status_code, body = 200, {"status": "ignored", "event": event_type}

        return _response(status_code, body)

    except Exception:
        logger.exception("Unhandled error processing webhook")
        return _response(500, {"error": "Internal server error"})


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
