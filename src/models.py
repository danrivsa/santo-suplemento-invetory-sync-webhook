from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class HoldedStockPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    product_id: str = Field(alias="productId")
    variant_id: str = Field(alias="variantId")
    warehouse_id: str = Field(alias="warehouseId")
    sku: str
    stock_variation: float = Field(alias="stockVariation")
    calculated_stock: float = Field(alias="calculatedStock")
    calculated_variant_stock: float = Field(alias="calculatedVariantStock")
    description: str = ""
    date: str = ""
    created: str = ""
    action: str | None = None
    provider_origin_change: str | None = Field(default=None, alias="providerOriginChange")
    provider_id_origin_change: str | None = Field(default=None, alias="providerIdOriginChange")
    id_origin_change: str | None = Field(default=None, alias="idOriginChange")
    doc_hash: str | None = Field(default=None, alias="docHash")
    hash: str | None = None


class WinkAdjustItem(BaseModel):
    sku: str
    operation: str
    quantity: int


class WinkAdjustStockRequest(BaseModel):
    items: list[WinkAdjustItem]
    inventory_ids: list[int]


class WinkAdjustStockResponse(BaseModel):
    summary: dict
    results: list[dict]


class WinkSyncPriceRequest(BaseModel):
    sku: str
    price: float
    inventory_ids: list[int]


class HoldedProductVariant(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    sku: str | None = None
    price: float | None = None
    stock: float | None = None
    description: str | None = None


class HoldedProductPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str = ""
    description: str | None = None
    kind: str = "simple"
    sku: str | None = None
    barcode: str | None = None
    price: float | None = None
    cost: float | None = None
    stock: float = 0
    variants: list[HoldedProductVariant] = Field(default_factory=list)
    pack_items: list[dict] = Field(default_factory=list, alias="packItems")
