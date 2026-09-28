from __future__ import annotations

import hashlib
import hmac

from src.signature import verify_signature


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(key=secret.encode(), msg=body, digestmod=hashlib.sha256).hexdigest()


def test_valid_signature() -> None:
    secret = "whsec_test_secret"
    body = b'{"sku":"ABC-123","stockVariation":5}'
    sig = _sign(body, secret)

    assert verify_signature(body, f"sha256={sig}", secret) is True


def test_invalid_signature() -> None:
    body = b'{"sku":"ABC-123","stockVariation":5}'
    assert verify_signature(body, "sha256=deadbeef0000", "whsec_secret") is False


def test_missing_prefix_still_works() -> None:
    secret = "whsec_secret"
    body = b"test payload"
    sig = _sign(body, secret)

    assert verify_signature(body, sig, secret) is True


def test_empty_body() -> None:
    secret = "whsec_secret"
    body = b""
    sig = _sign(body, secret)

    assert verify_signature(body, f"sha256={sig}", secret) is True


def test_tampered_body() -> None:
    secret = "whsec_secret"
    body = b"original"
    sig = _sign(body, secret)

    assert verify_signature(body + b"x", f"sha256={sig}", secret) is False
