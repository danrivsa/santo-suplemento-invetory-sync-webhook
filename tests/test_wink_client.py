from __future__ import annotations

import json

import httpx
import pytest

from src.config import Settings
from src.wink_client import adjust_stock


@pytest.fixture()
def config() -> Settings:
    return Settings(
        holded_webhook_secret="whsec_test",
        wink_api_key="wink_key_test",
        wink_inventory_ids="12",
    )


def _mock_httpx(mocker, response_json=None, status_code=200, raise_for_status=None):
    mock_response = mocker.Mock()
    mock_response.status_code = status_code
    mock_response.json.return_value = response_json or {"summary": {}, "results": []}
    if raise_for_status:
        mock_response.raise_for_status.side_effect = raise_for_status
    else:
        mock_response.raise_for_status = mocker.Mock()

    mock_instance = mocker.Mock(post=mocker.Mock(return_value=mock_response))
    mock_cls = mocker.patch("src.wink_client.httpx.Client")
    mock_cls.return_value.__enter__ = mocker.Mock(return_value=mock_instance)
    mock_cls.return_value.__exit__ = mocker.Mock(return_value=False)
    return mock_instance


def test_add_stock(mocker, config):
    instance = _mock_httpx(
        mocker,
        response_json={
            "summary": {"adjustmentsUpdated": 1},
            "results": [{"sku": "ABC-123", "status": "updated"}],
        },
    )

    result = adjust_stock("ABC-123", 10.0, config)

    assert result["summary"]["adjustmentsUpdated"] == 1
    instance.post.assert_called_once()
    assert "adjust-stock-by-sku" in instance.post.call_args[0][0]


def test_subtract_stock(mocker, config):
    instance = _mock_httpx(mocker)

    adjust_stock("ABC-123", -5.0, config)

    body = json.loads(instance.post.call_args[1]["content"])
    assert body["items"][0]["operation"] == "subtract"
    assert body["items"][0]["quantity"] == 5


def test_fractional_variation_rounds_down(mocker, config):
    instance = _mock_httpx(mocker)

    adjust_stock("ABC-123", 3.7, config)

    body = json.loads(instance.post.call_args[1]["content"])
    assert body["items"][0]["quantity"] == 3
    assert body["items"][0]["operation"] == "add"


def test_zero_variation_skips(config, mocker):
    _mock_httpx(mocker)

    result = adjust_stock("ABC-123", 0.0, config)

    assert result["skipped"] is True


def test_http_error_raises(mocker, config):
    error = httpx.HTTPStatusError(
        "403 Forbidden",
        request=mocker.Mock(),
        response=mocker.Mock(status_code=403),
    )
    _mock_httpx(mocker, raise_for_status=error)

    with pytest.raises(httpx.HTTPStatusError):
        adjust_stock("ABC-123", 10, config)
