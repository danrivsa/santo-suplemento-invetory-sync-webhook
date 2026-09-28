# Holded Stock Webhook

AWS Lambda that syncs stock changes from [Holded](https://www.holded.com/) to [Wink](https://www.winktienda.com/) via their APIs.

When a product's stock is updated in Holded, a `stock.update` webhook fires and this Lambda adjusts the stock on Wink by calling the `adjust-stock-by-sku` endpoint.

## Architecture

```mermaid
flowchart LR
    subgraph External["External services"]
        Holded["Holded<br/><i>stock.update webhook</i>"]
        Wink["Wink API<br/><i>adjust-stock-by-sku</i>"]
    end

    subgraph Lambda["AWS Lambda (holded-stock-webhook)"]
        direction TB
        Handler["<b>handler.py</b><br/>lambda_handler()<br/>─────────<br/>_extract_body()<br/>_extract_header()<br/>_response()"]

        Sig["<b>signature.py</b><br/>verify_signature()"]
        Models["<b>models.py</b><br/>HoldedStockPayload<br/>WinkAdjustItem<br/>WinkAdjustStockRequest"]
        Client["<b>wink_client.py</b><br/>adjust_stock()"]
        Config["<b>config.py</b><br/>Settings<br/>get_settings()"]

        Handler -->|"raw body + secret"| Sig
        Handler -->|"validates JSON"| Models
        Handler -->|"sku, variation"| Client
        Handler -->|"env vars"| Config
        Client -->|"builds request body"| Models
        Client -->|"reads api key + inventory ids"| Config
    end

    Holded -->|"POST<br/>x-holded-webhook-signature"| Handler
    Client -->|"POST<br/>x-api-key"| Wink
    Wink -->|"summary + results"| Client
```

### Request flow

```mermaid
sequenceDiagram
    autonumber
    participant H as Holded
    participant L as lambda_handler
    participant S as verify_signature
    participant M as HoldedStockPayload
    participant W as adjust_stock
    participant A as Wink API

    H->>L: POST stock.update (body + signature header)
    L->>L: _extract_body() — base64 or plain
    L->>L: _extract_header("x-holded-webhook-signature")

    alt signature missing
        L-->>H: 401 Missing signature
    else HMAC mismatch
        L->>S: verify_signature(raw_body, signature, secret)
        S-->>L: false
        L-->>H: 401 Invalid signature
    else valid signature
        L->>M: model_validate_json(raw_body)
        alt empty sku
            L-->>H: 400 Missing sku
        else stockVariation is zero
            L-->>H: 200 skipped — zero_variation
        else adjustment needed
            L->>W: adjust_stock(sku, stock_variation, config)
            Note over W: positive variation maps to add<br/>negative variation maps to subtract<br/>quantity is the truncated absolute value
            W->>A: POST /product-inventory/adjust-stock-by-sku
            A-->>W: 200 with summary and results
            W-->>L: result dict
            L-->>H: 200 with status ok and result
        end
    end
```

### Module dependencies

```mermaid
graph TD
    Main["main.py<br/><i>local test harness</i>"] --> Handler["src/handler.py"]
    T1["tests/test_handler.py"] --> Handler
    T2["tests/test_signature.py"] --> Sig["src/signature.py"]
    T3["tests/test_wink_client.py"] --> Client["src/wink_client.py"]

    Handler --> Sig
    Handler --> Models["src/models.py"]
    Handler --> Client
    Handler --> Config["src/config.py"]
    Client --> Models
    Client --> Config

    style Handler fill:#1f6feb,color:#fff
    style Sig fill:#238636,color:#fff
    style Models fill:#8957e5,color:#fff
    style Client fill:#8957e5,color:#fff
    style Config fill:#8957e5,color:#fff
```

## Project Structure

```
src/
├── config.py        # Settings loaded from environment variables
├── models.py        # Pydantic models (Holded payload, Wink request)
├── signature.py     # HMAC-SHA256 webhook signature verification
├── wink_client.py   # httpx client for the Wink API
└── handler.py       # AWS Lambda entry point
tests/
├── test_handler.py      # 8 tests — routing, auth, error paths
├── test_signature.py    # 5 tests — HMAC verification
└── test_wink_client.py  # 5 tests — add/subtract mapping
main.py              # Builds a sample event and calls lambda_handler
```

## Prerequisites

- [Python 3.13+](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/) (package manager)

## Setup

```bash
# Clone the repo
git clone <repo-url>
cd holded-stock-webhook

# Install dependencies
uv sync
```

## Environment Variables

Create a `.env` file from the example:

```bash
cp .env.example .env
```

| Variable | Description |
|----------|-------------|
| `HOLDED_WEBHOOK_SECRET` | Webhook signing secret from Holded (`whsec_...`) |
| `WINK_API_KEY` | API key from Wink Backoffice (API & Webhooks section) |
| `WINK_INVENTORY_IDS` | Comma-separated Wink inventory/sede IDs (e.g. `12`) |

## Testing

### Run all tests

```bash
uv run pytest tests/ -v
```

### Run a specific test file

```bash
uv run pytest tests/test_signature.py -v
uv run pytest tests/test_handler.py -v
uv run pytest tests/test_wink_client.py -v
```

### Run a specific test by name

```bash
uv run pytest tests/ -v -k "test_valid_signature"
uv run pytest tests/ -v -k "test_add_stock"
```

### Run tests with coverage

```bash
uv run pytest tests/ --cov=src --cov-report=term-missing
```

> **Note:** To run the coverage command, add `pytest-cov` to the dev dependencies in `pyproject.toml`.

### Lint and format

```bash
# Check lint
uv run ruff check src/ tests/ main.py

# Auto-fix lint issues
uv run ruff check --fix src/ tests/ main.py

# Check formatting
uv run ruff format --check src/ tests/ main.py

# Apply formatting
uv run ruff format src/ tests/ main.py
```

### Test locally

You can invoke the Lambda handler directly to verify it works end-to-end with real credentials:

```bash
uv run python main.py
```

This runs `main.py` which builds a sample event and calls `lambda_handler`. Make sure your `.env` file is configured before running.

## Webhook Behaviour

1. Holded fires a `stock.update` webhook when a product's stock changes.
2. The Lambda verifies the HMAC-SHA256 signature.
3. It parses the payload (SKU, stock variation).
4. It maps `stockVariation` to a Wink `add` or `subtract` operation.
5. It calls `POST https://api.winktienda.com/product-inventory/adjust-stock-by-sku`.

### Response codes

| Status | When |
|--------|------|
| `200` | Stock adjusted, or skipped because `stockVariation` was `0` |
| `400` | Payload has an empty `sku` |
| `401` | Signature header missing or HMAC mismatch |
| `500` | Unhandled error (Wink API failure, invalid JSON, missing config) |

## Deploying

Deployment is handled via GitHub Actions. Pushing to `main` triggers the CI/CD pipeline which runs tests and deploys the Lambda. See `.github/workflows/deploy.yml` for details.

## License

MIT
