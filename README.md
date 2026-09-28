# Holded Stock Webhook

AWS Lambda that syncs stock changes from [Holded](https://www.holded.com/) to [Wink](https://www.winktienda.com/) via their APIs.

When a product's stock is updated in Holded, a `stock.update` webhook fires and this Lambda adjusts the stock on Wink by calling the `adjust-stock-by-sku` endpoint.

## Architecture

```mermaid
flowchart LR
    subgraph External["External services"]
        Holded["Holded webhooks<br/><i>stock.update · product.update</i>"]
        Wink["Wink API<br/><i>adjust-stock-by-sku<br/>update-price-by-sku</i>"]
    end

    subgraph Lambda["AWS Lambda (holded-stock-webhook)"]
        direction TB
        Handler["<b>handler.py</b><br/>lambda_handler()<br/>─────────<br/>_extract_body()<br/>_extract_header()<br/>_extract_price_targets()<br/>_handle_stock_update()<br/>_handle_product_update()<br/>_response()"]

        Sig["<b>signature.py</b><br/>verify_signature()"]
        Models["<b>models.py</b><br/>HoldedStockPayload<br/>HoldedProductPayload<br/>HoldedProductVariant<br/>WinkAdjustItem / StockRequest<br/>WinkSyncPriceRequest"]
        Client["<b>wink_client.py</b><br/>adjust_stock()<br/>adjust_price()"]
        Config["<b>config.py</b><br/>Settings<br/>get_settings()"]

        Handler -->|"raw body + secret"| Sig
        Handler -->|"validates JSON"| Models
        Handler -->|"sku, variation"| Client
        Handler -->|"env vars"| Config
        Client -->|"builds request body"| Models
        Client -->|"reads api key + inventory ids"| Config
    end

    Holded -->|"POST<br/>x-holded-webhook-event<br/>x-holded-webhook-signature"| Handler
    Client -->|"POST<br/>x-api-key"| Wink
    Wink -->|"summary + results"| Client
```

### Event routing

| `x-holded-webhook-event` | Action | Wink endpoint |
|--------------------------|--------|---------------|
| `stock.update` | Apply `stockVariation` as a delta | `adjust-stock-by-sku` |
| `product.update` | Push `price` for each SKU | `update-price-by-sku` |
| anything else | `200 {"status": "ignored"}` | — |

Signature verification runs **before** routing, so an unsigned or tampered event never reaches either Wink call.

### Request flow

```mermaid
sequenceDiagram
    autonumber
    participant H as Holded
    participant L as lambda_handler
    participant S as verify_signature
    participant M as Pydantic models
    participant W as Wink clients
    participant A as Wink API

    H->>L: POST webhook (body + event + signature headers)
    L->>L: _extract_body() — base64 or plain
    L->>L: _extract_header("x-holded-webhook-signature")

    alt signature missing
        L-->>H: 401 Missing signature
    else HMAC mismatch
        L->>S: verify_signature(raw_body, signature, secret)
        S-->>L: false
        L-->>H: 401 Invalid signature
    else valid signature
        L->>L: _extract_header("x-holded-webhook-event")

        alt stock.update
            L->>M: HoldedStockPayload.model_validate_json()
            alt empty sku
                L-->>H: 400 Missing sku
            else stockVariation is zero
                L-->>H: 200 skipped — zero_variation
            else adjustment needed
                L->>W: adjust_stock(sku, variation, config)
                Note over W: positive variation maps to add<br/>negative variation maps to subtract<br/>quantity is the truncated absolute value
                W->>A: POST /product-inventory/adjust-stock-by-sku
                A-->>W: 200 with summary and results
                W-->>L: result dict
                L-->>H: 200 with status ok
            end
        else product.update
            L->>M: HoldedProductPayload.model_validate_json()
            L->>L: _extract_price_targets() — variants first, product as fallback
            alt no sku with a usable price
                L-->>H: 200 skipped — no_price_targets
            else skus to sync
                loop one call per SKU
                    L->>W: adjust_price(sku, price, config)
                    W->>A: POST /product-inventory/update-price-by-sku
                    A-->>W: 200 with summary and results
                end
                alt any SKU failed
                    L-->>H: 500 with synced and failed counts
                else all SKUs synced
                    L-->>H: 200 with synced count and per-SKU results
                end
            end
        else unsupported event
            L-->>H: 200 ignored
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
├── models.py        # Pydantic models (Holded payloads, Wink requests)
├── signature.py     # HMAC-SHA256 webhook signature verification
├── wink_client.py   # httpx clients: adjust_stock() and adjust_price()
└── handler.py       # AWS Lambda entry point + event routing
tests/
├── test_handler.py      # routing, auth, stock + price paths, error handling
├── test_signature.py    # HMAC verification
└── test_wink_client.py  # add/subtract mapping and price sync
main.py              # Builds signed sample events and calls lambda_handler
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

1. Holded fires a `stock.update` or `product.update` webhook.
2. The Lambda verifies the HMAC-SHA256 signature before doing anything else.
3. It routes on the `x-holded-webhook-event` header.
4. `stock.update` → applies the `stockVariation` delta via `adjust-stock-by-sku`.
5. `product.update` → pushes `price` per SKU via `update-price-by-sku`.
6. Any other event is acknowledged with `200 {"status": "ignored"}` so Holded does not retry it.

### Price sync rules

- `price` arrives from Holded as a string (`"12.50"`) and is coerced to `float`.
- Variants win over the product: if any variant has a SKU and a price, only variants are synced. The product-level `sku`/`price` is used only as a fallback.
- SKUs that are empty, duplicated within the event, or have a `null`/negative price are dropped.
- Prices are absolute, so a Holded retry re-applies already-synced SKUs harmlessly.

### Response codes

| Status | When |
|--------|------|
| `200` | Stock adjusted, prices synced, or skipped (`zero_variation`, `no_price_targets`, `ignored`) |
| `400` | `stock.update` payload has an empty `sku` |
| `401` | Signature header missing or HMAC mismatch |
| `500` | Unhandled error, or at least one SKU failed during `product.update` |

## Deploying

Deployment is handled by `.github/workflows/deploy.yaml`.

```mermaid
flowchart LR
    Push["push to main"] --> Test["test job<br/>ruff check · ruff format --check · pytest"]
    Test -->|pass| Deploy["deploy job<br/>build zip · verify import"]
    Deploy --> Aws["AWS Lambda<br/>holded-stock-webhook<br/>python3.13 · 256MB · 30s"]
    Aws --> Url["Function URL<br/>webhook target for Holded"]
    PR["pull request"] -.-> Test
    Test -.->|fails| NoDeploy["no deploy"]
```

The `test` job runs on every push and pull request. The `deploy` job has `needs: test`, so it only runs when the checks pass and only on `main` (never on pull requests). It can also be triggered manually with **Actions → CI/CD → Run workflow**.

### Required repository secrets

| Secret | Value |
|--------|-------|
| `AWS_ACCESS_KEY_ID` | IAM key with permission to update the Lambda |
| `AWS_SECRET_ACCESS_KEY` | Same IAM key's secret |
| `LAMBDA_ROLE_ARN` | Execution role ARN, only used when the function is first created |
| `HOLDED_WEBHOOK_SECRET` | Same value as `HOLDED_WEBHOOK_SECRET` in your local `.env` |
| `WINK_API_KEY` | Same value as `WINK_API_KEY` in your local `.env` |
| `WINK_INVENTORY_IDS` | Same value as `WINK_INVENTORY_IDS` in your local `.env` |

A missing secret fails the run with an explicit `::error::` message rather than deploying a broken function.

### What the deploy job does

1. Exports and installs production dependencies into `build/package` and copies `src/` alongside them.
2. Zips it (about 3 MB) and asserts that `src.handler.lambda_handler` imports from the built package, so a wrong handler path fails in CI instead of in production.
3. Creates the function on first run, or updates code and configuration on later runs.
4. Creates or updates the Function URL and makes it publicly invokable, then prints the URL.

The Lambda has no `.env` file: pydantic-settings reads `HOLDED_WEBHOOK_SECRET`, `WINK_API_KEY` and `WINK_INVENTORY_IDS` from the function's environment variables, which the workflow sets from the secrets above. Register the printed URL in Holded for the `stock.update` and `product.update` events.

The function URL uses `--auth-type NONE`, so requests are unauthenticated at the transport level. The HMAC signature check in the handler is the actual authentication, so `HOLDED_WEBHOOK_SECRET` must be set both in Holded and in the Lambda.


## License

MIT
