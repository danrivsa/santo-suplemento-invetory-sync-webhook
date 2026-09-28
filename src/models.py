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
