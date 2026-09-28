from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    holded_webhook_secret: str
    wink_api_key: str
    wink_inventory_ids: str = Field(description="Comma-separated Wink inventory IDs")

    @property
    def wink_inventory_id_list(self) -> list[int]:
        return [int(x.strip()) for x in self.wink_inventory_ids.split(",") if x.strip()]


def get_settings() -> Settings:
    return Settings()
