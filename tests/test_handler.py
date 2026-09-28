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


def _make_event(payload: dict, secret: str = SECRET) -> dict:
    body = json.dumps(payload).encode()
    sig = _sign(body, secret)
    return {
        "body": body.decode(),
        "isBase64Encoded": False,
        "headers": {
            "x-holded-webhook-signature": f"sha256={sig}",
            "x-holded-webhook-event": "stock.update",
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
        },
    }
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 200
