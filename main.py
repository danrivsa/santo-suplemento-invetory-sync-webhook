from __future__ import annotations

import hashlib
import hmac
import json

from src.config import get_settings
from src.handler import lambda_handler


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(key=secret.encode(), msg=body, digestmod=hashlib.sha256).hexdigest()


def _build_event(event_type: str, payload: dict, secret: str, webhook_id: str = "evt_test_001") -> dict:
    body = json.dumps(payload).encode()
    return {
        "httpMethod": "POST",
        "path": "/webhook",
        "headers": {
            "Content-Type": "application/json",
            "x-holded-webhook-event": event_type,
            "x-holded-webhook-signature": f"sha256={_sign(body, secret)}",
            "x-holded-webhook-id": webhook_id,
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

SALE_EVENT_BODY = {
    **STOCK_EVENT_BODY,
    "stockVariation": -1,
    "description": "Venta Wink ID 3795",
    "action": "sales_receipt_stock_update",
    "idOriginChange": "6a33d22b2fa645a14c024bd0",
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

    settings = get_settings()
    print(f"sync allowlist: {sorted(settings.holded_stock_sync_action_set) or 'disabled (syncs every action)'}")

    for webhook_id, event_type, payload in (
        ("evt_manual", "stock.update", STOCK_EVENT_BODY),
        ("evt_sale", "stock.update", SALE_EVENT_BODY),
        ("evt_price", "product.update", PRODUCT_EVENT_BODY),
    ):
        print(f"\n=== {event_type} {payload.get('action') or payload.get('id')} ===")
        response = lambda_handler(_build_event(event_type, payload, settings.holded_webhook_secret, webhook_id), None)
        print(json.dumps(response, indent=2))


if __name__ == "__main__":
    main()
