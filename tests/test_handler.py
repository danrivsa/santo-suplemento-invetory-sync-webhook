from __future__ import annotations

import base64
import hashlib
import hmac
import json

from src.handler import lambda_handler


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(key=secret.encode(), msg=body, digestmod=hashlib.sha256).hexdigest()


SECRET = "whsec_test_secret"
API_KEY = "wink_test_key"
INVENTORY_ID = 12


def _make_event(payload: dict, secret: str = SECRET, event: str = "stock.update") -> dict:
    body = json.dumps(payload).encode()
    sig = _sign(body, secret)
    headers = {
        "x-holded-webhook-signature": f"sha256={sig}",
        "x-holded-webhook-event": event,
    }
    return {
        "body": body.decode(),
        "isBase64Encoded": False,
        "headers": headers,
    }


VALID_PAYLOAD = {
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

AVAILABLE = 42.0


def _patch_settings(monkeypatch):
    monkeypatch.setenv("HOLDED_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("HOLDED_API_KEY", "holded_test_key")
    monkeypatch.setenv("WINK_API_KEY", API_KEY)
    monkeypatch.setenv("WINK_INVENTORY_IDS", str(INVENTORY_ID))


def _patch_availability(mocker, available: float = AVAILABLE):
    return mocker.patch("src.handler.get_available_stock", return_value=available)


def test_missing_signature_returns_401(monkeypatch):
    _patch_settings(monkeypatch)
    event = {
        "body": json.dumps(VALID_PAYLOAD),
        "isBase64Encoded": False,
        "headers": {},
    }
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 401
    assert "Missing signature" in resp["body"]


def test_invalid_signature_returns_401(monkeypatch):
    _patch_settings(monkeypatch)
    event = {
        "body": json.dumps(VALID_PAYLOAD),
        "isBase64Encoded": False,
        "headers": {"x-holded-webhook-signature": "sha256=invalid"},
    }
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 401
    assert "Invalid signature" in resp["body"]


def test_stock_update_syncs_available_from_holded(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    availability = _patch_availability(mocker, 42.0)
    stock = mocker.patch("src.handler.adjust_stock", return_value={"summary": {"adjustmentsUpdated": 1}, "results": []})

    resp = lambda_handler(_make_event(VALID_PAYLOAD), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "ok"
    availability.assert_called_once_with(product_id="prod_001", config=availability.call_args.kwargs["config"])
    stock.assert_called_once_with(sku="ABC-123", quantity=42.0, config=stock.call_args.kwargs["config"])


def test_stock_update_ignores_payload_calculated_stock(monkeypatch, mocker):
    """`available` is read from Holded's API, never taken from the payload."""
    _patch_settings(monkeypatch)
    _patch_availability(mocker, 7.0)
    stock = mocker.patch("src.handler.adjust_stock", return_value={"summary": {"adjustmentsUpdated": 1}, "results": []})

    payload = {**VALID_PAYLOAD, "variantId": ""}
    lambda_handler(_make_event(payload), None)

    assert stock.call_args.kwargs["quantity"] == 7.0


def test_variant_movement_uses_parent_available(monkeypatch, mocker):
    """The availability endpoint reports `available` only at product level."""
    _patch_settings(monkeypatch)
    _patch_availability(mocker, 7.0)
    stock = mocker.patch("src.handler.adjust_stock", return_value={"summary": {"adjustmentsUpdated": 1}, "results": []})

    payload = {**VALID_PAYLOAD, "variantId": "var_001"}
    lambda_handler(_make_event(payload), None)

    assert stock.call_args.kwargs["quantity"] == 7.0


def test_zero_variation_is_still_synced(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    _patch_availability(mocker)
    stock = mocker.patch("src.handler.adjust_stock", return_value={"summary": {"adjustmentsUpdated": 1}, "results": []})

    payload = {**VALID_PAYLOAD, "stockVariation": 0}
    resp = lambda_handler(_make_event(payload), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["status"] == "ok"
    stock.assert_called_once()


def test_negative_variation_is_still_synced(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    _patch_availability(mocker)
    stock = mocker.patch("src.handler.adjust_stock", return_value={"summary": {"adjustmentsUpdated": 1}, "results": []})

    payload = {**VALID_PAYLOAD, "stockVariation": -3}
    resp = lambda_handler(_make_event(payload), None)

    assert resp["statusCode"] == 200
    stock.assert_called_once()


def test_sale_action_is_synced(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    _patch_availability(mocker)
    stock = mocker.patch("src.handler.adjust_stock", return_value={"summary": {"adjustmentsUpdated": 1}, "results": []})

    payload = {**VALID_PAYLOAD, "action": "sales_receipt_stock_update", "stockVariation": -1}
    resp = lambda_handler(_make_event(payload), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["status"] == "ok"
    stock.assert_called_once()


def test_unknown_action_is_synced(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    _patch_availability(mocker)
    stock = mocker.patch("src.handler.adjust_stock", return_value={"summary": {"adjustmentsUpdated": 1}, "results": []})

    payload = {**VALID_PAYLOAD, "action": "some_action_holded_added_later"}
    resp = lambda_handler(_make_event(payload), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["status"] == "ok"
    stock.assert_called_once()


def test_null_action_is_synced(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    _patch_availability(mocker)
    stock = mocker.patch("src.handler.adjust_stock", return_value={"summary": {"adjustmentsUpdated": 1}, "results": []})

    payload = {**VALID_PAYLOAD, "action": None}
    resp = lambda_handler(_make_event(payload), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["status"] == "ok"
    stock.assert_called_once()


def test_empty_sku_returns_400(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    availability = _patch_availability(mocker)
    stock = mocker.patch("src.handler.adjust_stock")
    payload = {**VALID_PAYLOAD, "sku": ""}

    resp = lambda_handler(_make_event(payload), None)

    assert resp["statusCode"] == 400
    assert "Missing sku" in json.loads(resp["body"])["error"]
    availability.assert_not_called()
    stock.assert_not_called()


def test_holded_error_returns_500(monkeypatch, mocker):
    """A failed availability lookup makes Holded retry the delivery."""
    _patch_settings(monkeypatch)
    mocker.patch("src.handler.get_available_stock", side_effect=Exception("Holded API error"))
    stock = mocker.patch("src.handler.adjust_stock")

    resp = lambda_handler(_make_event(VALID_PAYLOAD), None)

    assert resp["statusCode"] == 500
    body = json.loads(resp["body"])
    assert "Internal server error" in body["error"]
    stock.assert_not_called()


def test_wink_client_error_returns_500(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    _patch_availability(mocker)
    mocker.patch("src.handler.adjust_stock", side_effect=Exception("Wink API error"))

    resp = lambda_handler(_make_event(VALID_PAYLOAD), None)
    assert resp["statusCode"] == 500
    body = json.loads(resp["body"])
    assert "Internal server error" in body["error"]


def test_wink_partial_failure_still_returns_200(monkeypatch, mocker):
    """Wink answers 200 with per-item failures; a retry would not fix them."""
    _patch_settings(monkeypatch)
    _patch_availability(mocker)
    mocker.patch(
        "src.handler.adjust_stock",
        return_value={
            "summary": {"adjustmentsUpdated": 0, "adjustmentsFailed": 1},
            "results": [{"sku": "ABC-123", "status": "failed", "reasons": {"sku_not_found": 1}}],
        },
    )

    resp = lambda_handler(_make_event(VALID_PAYLOAD), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["status"] == "ok"


def test_repeated_webhook_id_is_synced_again(monkeypatch, mocker):
    """replace is idempotent, so redeliveries need no dedupe."""
    _patch_settings(monkeypatch)
    _patch_availability(mocker)
    stock = mocker.patch("src.handler.adjust_stock", return_value={"summary": {"adjustmentsUpdated": 1}, "results": []})

    lambda_handler(_make_event(VALID_PAYLOAD), None)
    lambda_handler(_make_event(VALID_PAYLOAD), None)

    assert stock.call_count == 2


def test_base64_encoded_body(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    _patch_availability(mocker)
    mocker.patch("src.handler.adjust_stock", return_value={"summary": {}, "results": []})

    body = json.dumps(VALID_PAYLOAD).encode()

    event = {
        "body": base64.b64encode(body).decode(),
        "isBase64Encoded": True,
        "headers": {
            "x-holded-webhook-signature": f"sha256={_sign(body, SECRET)}",
            "x-holded-webhook-event": "stock.update",
        },
    }
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 200


PRODUCT_PAYLOAD = {
    "id": "prod_001",
    "name": "Creatina",
    "description": "Monohidrato",
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
            "cost": "6.00",
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

_OK = {"summary": {"adjustmentsUpdated": 1}, "results": []}


def _product_event(payload: dict) -> dict:
    return _make_event(payload, event="product.update")


def test_product_update_syncs_each_variant_price(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    adjust = mocker.patch("src.handler.adjust_price", return_value=_OK)

    resp = lambda_handler(_product_event(PRODUCT_PAYLOAD), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "ok"
    assert body["synced"] == 2
    assert adjust.call_count == 2
    assert [call.kwargs["sku"] for call in adjust.call_args_list] == ["CREA-500", "CREA-1000"]


def test_product_update_does_not_sync_parent_sku_when_variants_exist(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    adjust = mocker.patch("src.handler.adjust_price", return_value=_OK)

    lambda_handler(_product_event(PRODUCT_PAYLOAD), None)

    skus = [call.kwargs["sku"] for call in adjust.call_args_list]
    assert "CREA-GEN" not in skus


def test_product_update_coerces_price_string_to_float(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    adjust = mocker.patch("src.handler.adjust_price", return_value=_OK)

    lambda_handler(_product_event(PRODUCT_PAYLOAD), None)

    assert [call.kwargs["price"] for call in adjust.call_args_list] == [10.0, 18.5]


def test_product_update_falls_back_to_product_price(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    adjust = mocker.patch("src.handler.adjust_price", return_value=_OK)
    payload = {**PRODUCT_PAYLOAD, "kind": "simple", "variants": []}

    resp = lambda_handler(_product_event(payload), None)

    assert resp["statusCode"] == 200
    adjust.assert_called_once_with(sku="CREA-GEN", price=10.0, config=adjust.call_args.kwargs["config"])


def test_product_update_falls_back_when_variants_lack_usable_price(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    adjust = mocker.patch("src.handler.adjust_price", return_value=_OK)
    payload = {**PRODUCT_PAYLOAD, "variants": [{"id": "var_001", "sku": None, "price": None}]}

    lambda_handler(_product_event(payload), None)

    adjust.assert_called_once()
    assert adjust.call_args.kwargs["sku"] == "CREA-GEN"


def test_product_update_dedupes_duplicate_variant_skus(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    adjust = mocker.patch("src.handler.adjust_price", return_value=_OK)
    payload = {
        **PRODUCT_PAYLOAD,
        "variants": [
            {"id": "var_001", "sku": "CREA-500", "price": "10.00"},
            {"id": "var_002", "sku": "CREA-500", "price": "10.00"},
        ],
    }

    lambda_handler(_product_event(payload), None)

    adjust.assert_called_once()
    assert adjust.call_args.kwargs["sku"] == "CREA-500"


def test_product_update_skipped_when_no_price_targets(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    adjust = mocker.patch("src.handler.adjust_price", return_value=_OK)
    payload = {**PRODUCT_PAYLOAD, "sku": None, "price": None, "variants": []}

    resp = lambda_handler(_product_event(payload), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "skipped"
    assert body["reason"] == "no_price_targets"
    adjust.assert_not_called()


def test_product_update_partial_failure_returns_500(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    mocker.patch("src.handler.adjust_price", side_effect=[_OK, Exception("Wink timeout")])

    resp = lambda_handler(_product_event(PRODUCT_PAYLOAD), None)

    assert resp["statusCode"] == 500
    body = json.loads(resp["body"])
    assert body["status"] == "error"
    assert body["synced"] == 1
    assert body["failed"] == 1
    assert [r["status"] for r in body["results"]] == ["ok", "error"]


def test_unsupported_event_is_ignored(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    stock = mocker.patch("src.handler.adjust_stock", return_value=_OK)
    price = mocker.patch("src.handler.adjust_price", return_value=_OK)

    resp = lambda_handler(_make_event(VALID_PAYLOAD, event="invoice.create"), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "ignored"
    assert body["event"] == "invoice.create"
    stock.assert_not_called()
    price.assert_not_called()


def test_missing_event_header_is_ignored(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    body = json.dumps(VALID_PAYLOAD).encode()
    event = {
        "body": body.decode(),
        "isBase64Encoded": False,
        "headers": {"x-holded-webhook-signature": f"sha256={_sign(body, SECRET)}"},
    }

    resp = lambda_handler(event, None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["status"] == "ignored"


def test_signature_is_checked_before_event_routing(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    price = mocker.patch("src.handler.adjust_price", return_value=_OK)
    event = _product_event(PRODUCT_PAYLOAD)
    event["headers"]["x-holded-webhook-signature"] = "sha256=invalid"

    resp = lambda_handler(event, None)

    assert resp["statusCode"] == 401
    price.assert_not_called()


def test_price_sync_is_not_affected_by_stock_events(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    price = mocker.patch("src.handler.adjust_price", return_value=_OK)

    lambda_handler(_make_event(PRODUCT_PAYLOAD, event="product.update"), None)
    lambda_handler(_make_event(PRODUCT_PAYLOAD, event="product.update"), None)

    assert price.call_count == 4


SALE_ORDER_PAYLOAD = {
    "id": "so_001",
    "type": "salesorder",
    "documentNumber": "SO-001",
    "lines": [
        {"productId": "prod_001", "sku": "ABC-123", "units": 1},
        {"productId": "prod_002", "sku": "CREA-500", "units": 2},
    ],
}


def _sale_order_event(payload: dict, event: str = "salesorder.create") -> dict:
    return _make_event(payload, event=event)


def test_sale_order_syncs_each_line_availability(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    availability = mocker.patch("src.handler.get_available_stock", side_effect=[42.0, 7.0])
    stock = mocker.patch("src.handler.adjust_stock", return_value=_OK)

    resp = lambda_handler(_sale_order_event(SALE_ORDER_PAYLOAD), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "ok"
    assert body["synced"] == 2
    assert [call.kwargs["product_id"] for call in availability.call_args_list] == ["prod_001", "prod_002"]
    assert [call.kwargs["sku"] for call in stock.call_args_list] == ["ABC-123", "CREA-500"]
    assert [call.kwargs["quantity"] for call in stock.call_args_list] == [42.0, 7.0]


def test_sale_order_update_uses_same_flow(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    mocker.patch("src.handler.get_available_stock", return_value=42.0)
    stock = mocker.patch("src.handler.adjust_stock", return_value=_OK)

    resp = lambda_handler(_sale_order_event(SALE_ORDER_PAYLOAD, event="salesorder.update"), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["status"] == "ok"
    assert stock.call_count == 2


def test_sale_order_accepts_snake_case_lines(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    availability = mocker.patch("src.handler.get_available_stock", return_value=42.0)
    stock = mocker.patch("src.handler.adjust_stock", return_value=_OK)
    payload = {**SALE_ORDER_PAYLOAD, "lines": [{"product_id": "prod_001", "sku": "ABC-123"}]}

    resp = lambda_handler(_sale_order_event(payload), None)

    assert resp["statusCode"] == 200
    availability.assert_called_once()
    stock.assert_called_once_with(sku="ABC-123", quantity=42.0, config=stock.call_args.kwargs["config"])


def test_sale_order_skips_lines_without_product_or_sku(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    availability = mocker.patch("src.handler.get_available_stock", return_value=42.0)
    stock = mocker.patch("src.handler.adjust_stock", return_value=_OK)
    payload = {
        **SALE_ORDER_PAYLOAD,
        "lines": [
            {"productId": "prod_001", "sku": "ABC-123"},
            {"sku": "NO-PRODUCT"},
            {"productId": "prod_002", "sku": None},
        ],
    }

    resp = lambda_handler(_sale_order_event(payload), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["synced"] == 1
    availability.assert_called_once_with(product_id="prod_001", config=availability.call_args.kwargs["config"])
    stock.assert_called_once()


def test_sale_order_skipped_when_no_lines(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    stock = mocker.patch("src.handler.adjust_stock", return_value=_OK)
    payload = {**SALE_ORDER_PAYLOAD, "lines": []}

    resp = lambda_handler(_sale_order_event(payload), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "skipped"
    assert body["reason"] == "no_lines"
    stock.assert_not_called()


def test_sale_order_partial_failure_returns_500(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    mocker.patch("src.handler.get_available_stock", side_effect=[42.0, Exception("Holded API error")])
    stock = mocker.patch("src.handler.adjust_stock", return_value=_OK)

    resp = lambda_handler(_sale_order_event(SALE_ORDER_PAYLOAD), None)

    assert resp["statusCode"] == 500
    body = json.loads(resp["body"])
    assert body["status"] == "error"
    assert body["synced"] == 1
    assert body["failed"] == 1
    assert stock.call_count == 1


def test_sale_order_does_not_touch_stock_update_path(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    mocker.patch("src.handler.get_available_stock", return_value=42.0)
    stock = mocker.patch("src.handler.adjust_stock", return_value=_OK)

    lambda_handler(_make_event(VALID_PAYLOAD, event="stock.update"), None)
    lambda_handler(_sale_order_event(SALE_ORDER_PAYLOAD), None)

    assert stock.call_count == 3
