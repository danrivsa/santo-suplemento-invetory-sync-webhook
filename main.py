from __future__ import annotations

import json

from src.handler import lambda_handler

SAMPLE_EVENT = {
    "httpMethod": "POST",
    "path": "/webhook/stock",
    "headers": {
        "Content-Type": "application/json",
        "x-holded-webhook-event": "stock.update",
        "x-holded-webhook-signature": "",
        "x-holded-webhook-id": "evt_test_001",
    },
    "body": json.dumps(
        {
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
    ),
}


def main() -> None:
    response = lambda_handler(SAMPLE_EVENT, None)
    print(json.dumps(response, indent=2))


if __name__ == "__main__":
    main()
