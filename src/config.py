from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    holded_webhook_secret: str
    wink_api_key: str
    wink_inventory_ids: str = Field(description="Comma-separated Wink inventory IDs")
    holded_stock_sync_actions: str = Field(
        default="",
        description=(
            "Comma-separated Holded stock.update actions to sync to Wink. "
            "Empty means no allowlist filtering, so every action is synced."
        ),
    )

    @property
    def wink_inventory_id_list(self) -> list[int]:
        return [int(x.strip()) for x in self.wink_inventory_ids.split(",") if x.strip()]

    @property
    def holded_stock_sync_action_set(self) -> set[str]:
        return {x.strip() for x in self.holded_stock_sync_actions.split(",") if x.strip()}


def get_settings() -> Settings:
    return Settings()
