from __future__ import annotations

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
    return {
        "body": body.decode(),
        "isBase64Encoded": False,
        "headers": {
            "x-holded-webhook-signature": f"sha256={sig}",
            "x-holded-webhook-event": event,
        },
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


def _patch_settings(monkeypatch):
    monkeypatch.setenv("HOLDED_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("WINK_API_KEY", API_KEY)
    monkeypatch.setenv("WINK_INVENTORY_IDS", str(INVENTORY_ID))


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


def test_valid_stock_increase(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    mocker.patch("src.handler.adjust_stock", return_value={"summary": {"adjustmentsUpdated": 1}, "results": []})

    resp = lambda_handler(_make_event(VALID_PAYLOAD), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "ok"


def test_valid_stock_decrease(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    mocker.patch("src.handler.adjust_stock", return_value={"summary": {"adjustmentsUpdated": 1}, "results": []})

    payload = {**VALID_PAYLOAD, "stockVariation": -3}
    resp = lambda_handler(_make_event(payload), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "ok"


def test_zero_variation_skips(monkeypatch):
    _patch_settings(monkeypatch)
    payload = {**VALID_PAYLOAD, "stockVariation": 0}
    resp = lambda_handler(_make_event(payload), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "skipped"
    assert body["reason"] == "zero_variation"


def test_empty_sku_returns_400(monkeypatch):
    _patch_settings(monkeypatch)
    payload = {**VALID_PAYLOAD, "sku": ""}
    resp = lambda_handler(_make_event(payload), None)
    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert "Missing sku" in body["error"]


def test_wink_client_error_returns_500(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    mocker.patch("src.handler.adjust_stock", side_effect=Exception("Wink API error"))

    resp = lambda_handler(_make_event(VALID_PAYLOAD), None)
    assert resp["statusCode"] == 500
    body = json.loads(resp["body"])
    assert "Internal server error" in body["error"]


def test_base64_encoded_body(monkeypatch, mocker):
    _patch_settings(monkeypatch)
    mocker.patch("src.handler.adjust_stock", return_value={"summary": {}, "results": []})

    body = json.dumps(VALID_PAYLOAD).encode()
    import base64

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
