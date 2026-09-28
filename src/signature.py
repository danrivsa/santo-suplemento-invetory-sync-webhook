from __future__ import annotations

import hashlib
import hmac


def verify_signature(body: bytes, signature_header: str, secret: str) -> bool:
    """Verify Holded webhook HMAC-SHA256 signature.

    The header arrives with a ``sha256=`` prefix that must be stripped before
    comparison.  Uses ``hmac.compare_digest`` for timing-safe comparison.
    """
    received = signature_header.removeprefix("sha256=")

    expected = hmac.new(
        key=secret.encode(),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(received, expected)
