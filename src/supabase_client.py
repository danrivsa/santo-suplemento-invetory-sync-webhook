import os

from dotenv import load_dotenv
from supabase import Client, create_client

# Load environment variables from .env
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY in environment variables.")

# Initialize the Supabase Client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def _fetch_table_data():
    try:
        # Target your specific table using the .table() modifier
        # Replace 'users' with your exact Supabase table name
        response = supabase.table("sale_order").select("*").limit(10).execute()

        print("Successfully connected and fetched data!")
        print("Data entries:", response.data)
        return response.data
    except Exception as e:
        print(f"An error occurred while communicating with Supabase: {e}")


def get_order_lines(sale_order_id: str) -> list[dict]:
    try:
        response = supabase.table("sale_order_line").select("*").eq("sale_order_holded_id", sale_order_id).execute()
        return response.data
    except Exception as e:
        print(f"An error occurred while fetching order lines: {e}")
        return []


def register_sale_order(holded_id: str, lines: list[dict]) -> None:
    try:
        # Insert the sale order lines
        for line in lines:
            supabase.table("sale_order_line").insert(
                {"sale_order_holded_id": holded_id, "product_id": line["product_id"], "sku": line["sku"]}
            ).execute()
    except Exception as e:
        print(f"An error occurred while registering sale order: {e}")


def delete_order_lines(holded_id: str) -> None:
    try:
        supabase.table("sale_order_line").delete().eq("sale_order_holded_id", holded_id).execute()
    except Exception as e:
        print(f"An error occurred while deleting order lines: {e}")


if __name__ == "__main__":
    _fetch_table_data()
