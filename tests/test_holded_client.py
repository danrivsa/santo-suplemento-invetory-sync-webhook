from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from src.config import Settings
from src.holded_client import get_available_stock


@pytest.fixture()
def config() -> Settings:
    return Settings(
        holded_webhook_secret="whsec_test",
        holded_api_key="holded_key_test",
        wink_api_key="wink_key_test",
        wink_inventory_ids="12",
    )


def _mock_httpx(mocker, response_json=None, status_code=200, raise_for_status=None):
    mock_response = mocker.Mock()
    mock_response.status_code = status_code
    mock_response.json.return_value = response_json or {"product_id": "prod_001", "available": "42"}
    if raise_for_status:
        mock_response.raise_for_status.side_effect = raise_for_status
    else:
        mock_response.raise_for_status = mocker.Mock()

    mock_instance = mocker.Mock(get=mocker.Mock(return_value=mock_response))
    mock_cls = mocker.patch("src.holded_client.httpx.Client")
    mock_cls.return_value.__enter__ = mocker.Mock(return_value=mock_instance)
    mock_cls.return_value.__exit__ = mocker.Mock(return_value=False)
    return mock_instance


def test_returns_available_as_float(mocker, config):
    instance = _mock_httpx(mocker, response_json={"product_id": "prod_001", "available": "15.3"})

    assert get_available_stock("prod_001", config) == 15.3
    instance.get.assert_called_once()


def test_calls_products_stock_endpoint(mocker, config):
    instance = _mock_httpx(mocker)

    get_available_stock("507f1f77bcf86cd799439011", config)

    url = instance.get.call_args[0][0]
    assert url.endswith("/products/507f1f77bcf86cd799439011/stock")
    headers = instance.get.call_args[1]["headers"]
    assert headers["Authorization"] == "Bearer holded_key_test"
    assert headers["Accept"] == "application/json"


def test_strips_sale_order_line_suffix(mocker, config):
    instance = _mock_httpx(mocker)

    get_available_stock("507f1f77bcf86cd799439011#807f1f77bcf86cd799439022", config)

    url = instance.get.call_args[0][0]
    assert url.endswith("/products/507f1f77bcf86cd799439011/stock")
    assert "#" not in url


def test_zero_available_is_returned(mocker, config):
    _mock_httpx(mocker, response_json={"product_id": "prod_001", "available": "0"})

    assert get_available_stock("prod_001", config) == 0.0


def test_http_error_raises(mocker, config):
    error = httpx.HTTPStatusError(
        "404 Not Found",
        request=mocker.Mock(),
        response=mocker.Mock(status_code=404),
    )
    _mock_httpx(mocker, raise_for_status=error)

    with pytest.raises(httpx.HTTPStatusError):
        get_available_stock("prod_001", config)


def test_missing_available_raises(mocker, config):
    _mock_httpx(mocker, response_json={"product_id": "prod_001"})

    with pytest.raises(ValidationError):
        get_available_stock("prod_001", config)
