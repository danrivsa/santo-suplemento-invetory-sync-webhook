from __future__ import annotations

import hashlib
import hmac
import json

from src.config import get_settings
from src.handler import lambda_handler


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(key=secret.encode(), msg=body, digestmod=hashlib.sha256).hexdigest()


def _build_event(event_type: str, payload: dict, secret: str) -> dict:
    body = json.dumps(payload).encode()
    return {
        "httpMethod": "POST",
        "path": "/webhook",
        "headers": {
            "Content-Type": "application/json",
            "x-holded-webhook-event": event_type,
            "x-holded-webhook-signature": f"sha256={_sign(body, secret)}",
            "x-holded-webhook-id": "evt_test_001",
        },
        "body": body.decode(),
    }


STOCK_EVENT_BODY = {
    "productId": "prod_001",
    "variantId": "var_001",
    "warehouseId": "wh_001",
    "sku": "ABC-123",
    "stockVariation": 5,
    "calculatedStock": 105,
    "calculatedVariantStock": 50,
    "description": "Manual stock update",
    "date": "2026-01-01T00:00:00Z",
    "created": "2026-01-01T00:00:00Z",
    "action": "manual_stock_update",
    "providerOriginChange": None,
    "providerIdOriginChange": None,
    "idOriginChange": None,
    "docHash": None,
    "hash": None,
}

PRODUCT_EVENT_BODY = {
    "id": "prod_001",
    "name": "Creatina monohidrato",
    "description": "Polvo",
    "kind": "variants",
    "sku": "CREA-GEN",
    "barcode": None,
    "price": "10.00",
    "cost": "5.00",
    "stock": "100",
    "variants": [
        {
            "id": "var_001",
            "sku": "CREA-500",
            "barcode": None,
            "price": "10.00",
            "cost": "5.00",
            "stock": "50",
            "description": "500 g",
        },
        {
            "id": "var_002",
            "sku": "CREA-1000",
            "barcode": None,
            "price": "18.50",
            "cost": "9.00",
            "stock": "30",
            "description": "1 kg",
        },
    ],
}


def main() -> None:

    secret = get_settings().held_webhook_secret
    for event_type, payload in (
        ("stock.update", STOCK_EVENT_BODY),
        ("product.update", PRODUCT_EVENT_BODY),
    ):
        print(f"\n=== {event_type} ===")
        response = lambda_handler(_build_event(event_type, payload, secret), None)
        print(json.dumps(response, indent=2))


if __name__ == "__main__":
    main()
