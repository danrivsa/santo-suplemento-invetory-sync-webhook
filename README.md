# Holded Stock Webhook

AWS Lambda that syncs stock changes from [Holded](https://www.holded.com/) to [Wink](https://www.winktienda.com/) via their APIs.

When a product's stock is updated in Holded, a `stock.update` webhook fires and this Lambda sets the stock on Wink to Holded's `available` stock (read back from the Holded API), via the `adjust-stock-by-sku` endpoint. Sales orders (`salesorder.create` / `salesorder.update`) are listened to as well, so the stock reserved by a sale keeps Wink in sync even when no `stock.update` event fires.

## Architecture

```mermaid
flowchart LR
    subgraph External["External services"]
        Holded["Holded webhooks<br/><i>stock.update · product.update<br/>salesorder.create · salesorder.update</i>"]
        HoldedApi["Holded API<br/><i>GET products/{id}/stock</i>"]
        Wink["Wink API<br/><i>adjust-stock-by-sku<br/>update-price-by-sku</i>"]
    end

    subgraph Lambda["AWS Lambda (holded-stock-webhook)"]
        direction TB
        Handler["<b>handler.py</b><br/>lambda_handler()<br/>─────────<br/>_extract_body()<br/>_extract_header()<br/>_extract_price_targets()<br/>_handle_stock_update()<br/>_handle_product_update()<br/>_handle_sale_order()<br/>_log_wink_rejections()<br/>_response()"]

        Sig["<b>signature.py</b><br/>verify_signature()"]
        Models["<b>models.py</b><br/>HoldedStockPayload<br/>HoldedStockAvailability<br/>HoldedProductPayload<br/>HoldedProductVariant<br/>HoldedSaleOrderPayload<br/>HoldedSaleOrderLine<br/>WinkAdjustItem / StockRequest<br/>WinkSyncPriceRequest"]
        HoldedClient["<b>holded_client.py</b><br/>get_available_stock()"]
        Client["<b>wink_client.py</b><br/>adjust_stock()<br/>adjust_price()"]
        Config["<b>config.py</b><br/>Settings<br/>get_settings()"]

        Handler -->|"raw body + secret"| Sig
        Handler -->|"validates JSON"| Models
        Handler -->|"product_id"| HoldedClient
        Handler -->|"sku, available stock"| Client
        Handler -->|"env vars"| Config
        HoldedClient -->|"builds response model"| Models
        HoldedClient -->|"reads api key"| Config
        Client -->|"builds request body"| Models
        Client -->|"reads api key + inventory ids"| Config
    end

    Holded -->|"POST<br/>x-holded-webhook-event<br/>x-holded-webhook-signature"| Handler
    HoldedClient -->|"GET Bearer<br/>products/{id}/stock"| HoldedApi
    HoldedApi -->|"available"| HoldedClient
    Client -->|"POST<br/>x-api-key"| Wink
    Wink -->|"summary + results"| Client
```

### Event routing

| `x-holded-webhook-event` | Action | Wink endpoint |
|--------------------------|--------|---------------|
| `stock.update` | Read the product's `available` stock from the Holded API, then set the SKU's stock to it via `replace` | `adjust-stock-by-sku` |
| `product.update` | Push `price` for each SKU | `update-price-by-sku` |
| `salesorder.create` · `salesorder.update` | For each line's product, read `available` from the Holded API, then set the line's SKU stock to it via `replace` | `adjust-stock-by-sku` |
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
    participant HD as holded_client
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
            else sku present
                L->>HD: get_available_stock(product_id, config)
                HD->>H: GET /api/v2/products/{productId}/stock
                H-->>HD: 200 with available (decimal string)
                alt availability call failed
                    HD-->>L: raises
                    L-->>H: 500 — Holded retries
                else available resolved
                    HD-->>L: available as float
                    L->>W: adjust_stock(sku, available, config)
                    Note over W: rounds to the nearest unit, clamps at 0<br/>and always sends operation "replace"
                    W->>A: POST /product-inventory/adjust-stock-by-sku
                    A-->>W: 200 with summary and results
                    W-->>L: result dict
                    L-->>H: 200 with status ok
                end
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
        else salesorder.create / salesorder.update
            L->>M: HoldedSaleOrderPayload.model_validate_json()
            alt no lines
                L-->>H: 200 skipped — no_lines
            else lines present
                loop one call per line with productId + sku
                    L->>HD: get_available_stock(line.product_id, config)
                    HD->>H: GET /api/v2/products/{productId}/stock
                    H-->>HD: 200 with available (decimal string)
                    alt availability or Wink call failed
                        L-->>H: 500 — Holded retries (replace is idempotent)
                    else available resolved
                        HD-->>L: available as float
                        L->>W: adjust_stock(line.sku, available, config)
                        W->>A: POST /product-inventory/adjust-stock-by-sku
                        A-->>W: 200 with summary and results
                    end
                end
                alt any line failed
                    L-->>H: 500 with synced and failed counts
                else all lines synced
                    L-->>H: 200 with synced count and per-line results
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
    T4["tests/test_holded_client.py"] --> HoldedClient["src/holded_client.py"]

    Handler --> Sig
    Handler --> Models["src/models.py"]
    Handler --> HoldedClient
    Handler --> Client
    Handler --> Config["src/config.py"]
    HoldedClient --> Models
    HoldedClient --> Config
    Client --> Models
    Client --> Config

    style Handler fill:#1f6feb,color:#fff
    style Sig fill:#238636,color:#fff
    style Models fill:#8957e5,color:#fff
    style HoldedClient fill:#8957e5,color:#fff
    style Client fill:#8957e5,color:#fff
    style Config fill:#8957e5,color:#fff
```

Interactive versions of these diagrams (event flow, stock-sync sequence, and module dependencies) live in [`.documentation/diagrams/`](.documentation/diagrams/), indexed in [`.documentation/README.md`](.documentation/README.md).

## Project Structure

```
src/
├── config.py         # Settings loaded from environment variables
├── holded_client.py  # httpx client: get_available_stock() reads Holded's `available`
├── models.py         # Pydantic models (Holded payloads, Wink requests)
├── signature.py      # HMAC-SHA256 webhook signature verification
├── wink_client.py    # httpx clients: adjust_stock() and adjust_price()
└── handler.py        # AWS Lambda entry point + event routing
tests/
├── test_handler.py       # routing, auth, stock + price + sale order paths, error handling
├── test_holded_client.py # availability endpoint and error propagation
├── test_signature.py     # HMAC verification
└── test_wink_client.py   # replace mapping and price sync
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
| `HOLDED_API_KEY` | Holded API key, sent as `Bearer` to read product availability |
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
uv run pytest tests/test_holded_client.py -v
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

1. Holded fires a `stock.update`, `product.update`, `salesorder.create` or `salesorder.update` webhook.
2. The Lambda verifies the HMAC-SHA256 signature before doing anything else.
3. It routes on the `x-holded-webhook-event` header.
4. `stock.update` → reads the product's `available` stock from the Holded API and **sets** the Wink stock for the SKU to that value, via the `replace` operation of `adjust-stock-by-sku`.
5. `product.update` → pushes `price` per SKU via `update-price-by-sku`.
6. `salesorder.create` / `salesorder.update` → iterates the order's `lines` and, for each line that names a product, reads that product's `available` stock from the Holded API and **sets** the line's SKU in Wink to that value via `replace`.
7. Any other event is acknowledged with `200 {"status": "ignored"}` so Holded does not retry it.

### Observability

Every invocation logs the full event received from Holded (headers and body) via `logger.info` at the top of `lambda_handler`, so the raw payload is available in CloudWatch Logs — including unsupported events and lines that were skipped.

### Stock sync rules

The sync is **absolute, not a delta**: every `stock.update` — whatever its
`action` — tells Wink to *set* the existence of the SKU to the stock Holded
reports:

- **Which value**: `available` from `GET /api/v2/products/{productId}/stock`,
  Holded's sellable stock (total minus stock reserved by pending sales orders),
  read with the `productId` the webhook already carries. The payload's
  `calculatedStock`/`calculatedVariantStock` are ignored. `available` is
  product-level, so a variant movement pushes the parent product's availability
  too — Wink may then reject the parent SKU with `product_has_variants`.
- **Which operation**: always `replace`. Re-sending the same value is
  idempotent, so Holded's automatic retries and the Wink↔Holded feedback loop
  (a Wink sale lowering stock in both systems) need no guard: the value simply
  lands on the same number again.
- **Normalisation**: the quantity is rounded to the nearest unit and clamped at
  0, since Wink requires an integer ≥ 0 and would reject the whole request
  otherwise. A stock of 0 is still sent — it means *agotado*.
- **Empty `sku`** returns `400`, checked before the availability lookup.
- **Sale order events** (`salesorder.create` / `salesorder.update`) run the same per-product flow as `stock.update`: for each line carrying a `productId` and a `sku`, the product's `available` is read from the Holded API and the line's SKU stock is set to it with `replace`. Lines without a product or SKU (e.g. free-text lines) are skipped with a warning; a sale order with no lines at all answers `200 {"status": "skipped", "reason": "no_lines"}`.
- **Holded availability failure** (401/404/timeout, bad payload) returns `500`
  so Holded retries the delivery instead of leaving Wink out of sync.
- Wink answers `200` even when an individual adjustment failed
  (`sku_not_found`, `product_has_variants`, `negative_result`, …). Those rows
  are logged as warnings and the delivery still returns `200`: a retry would
  not fix them, and Holded would otherwise retry forever.

### Price sync rules

- `price` arrives from Holded as a string (`"12.50"`) and is coerced to `float`.
- Variants win over the product: if any variant has a SKU and a price, only variants are synced. The product-level `sku`/`price` is used only as a fallback.
- SKUs that are empty, duplicated within the event, or have a `null`/negative price are dropped.
- Prices are absolute, so a Holded retry re-applies already-synced SKUs harmlessly.

### Response codes

| Status | When |
|--------|------|
| `200` | Stock set, prices synced, sale order lines synced, or skipped (`no_price_targets`, `no_lines`, `ignored`) |
| `400` | `stock.update` payload has an empty `sku` |
| `401` | Signature header missing or HMAC mismatch |
| `500` | Unhandled error, failed Holded availability lookup, at least one SKU failed during `product.update`, or at least one line failed during a sale order event |

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
| `HOLDED_API_KEY` | Same value as `HOLDED_API_KEY` in your local `.env` |
| `WINK_API_KEY` | Same value as `WINK_API_KEY` in your local `.env` |
| `WINK_INVENTORY_IDS` | Same value as `WINK_INVENTORY_IDS` in your local `.env` |

A missing secret fails the run with an explicit `::error::` message rather than deploying a broken function.

### What the deploy job does

1. Exports and installs production dependencies into `build/package` and copies `src/` alongside them.
2. Zips it (about 3 MB) and asserts that `src.handler.lambda_handler` imports from the built package, so a wrong handler path fails in CI instead of in production.
3. Creates the function on first run, or updates code and configuration on later runs.
4. Creates or updates the Function URL and makes it publicly invokable, then prints the URL.

The Lambda has no `.env` file: pydantic-settings reads `HOLDED_WEBHOOK_SECRET`, `HOLDED_API_KEY`, `WINK_API_KEY` and `WINK_INVENTORY_IDS` from the function's environment variables, which the workflow sets from the secrets above. Register the printed URL in Holded for the `stock.update`, `product.update`, `salesorder.create` and `salesorder.update` events.

The function URL uses `--auth-type NONE`, so requests are unauthenticated at the transport level. The HMAC signature check in the handler is the actual authentication, so `HOLDED_WEBHOOK_SECRET` must be set both in Holded and in the Lambda.


## License

MIT
