from __future__ import annotations

import base64
import json
import logging

from src.config import get_settings
from src.models import HoldedStockPayload
from src.signature import verify_signature
from src.wink_client import adjust_stock

logger = logging.getLogger()
logger.setLevel(logging.INFO)


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

        payload = HoldedStockPayload.model_validate_json(raw_body)
        logger.info(
            "Received stock.update for sku=%s variation=%.2f",
            payload.sku,
            payload.stock_variation,
        )

        if not payload.sku:
            logger.warning("Empty sku in payload, skipping")
            return _response(400, {"error": "Missing sku"})

        if payload.stock_variation == 0:
            logger.info("Stock variation is zero, skipping")
            return _response(200, {"status": "skipped", "reason": "zero_variation"})

        result = adjust_stock(
            sku=payload.sku,
            stock_variation=payload.stock_variation,
            config=config,
        )

        return _response(200, {"status": "ok", "result": result})

    except Exception:
        logger.exception("Unhandled error processing webhook")
        return _response(500, {"error": "Internal server error"})


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
