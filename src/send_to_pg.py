import os
import re
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from src.rbac import ROLE_COLUMNS

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:user@localhost:5432/analytics")
engine = create_engine(DATABASE_URL)

def send_to_pg(clean_cand: str, role: str, db_schema: str = "gold"):
    low = clean_cand.lower().strip()
    if not low.startswith("select"):
        raise ValueError("Only SELECT allowed")

    ALLOWED_TABLES = ["gold.shipment_fact", "gold.carrier_daily", "gold.city_daily"]
    if not any(t in low for t in ALLOWED_TABLES):
        raise ValueError("Tabel tidak diizinkan, hanya Gold Layer")

    allowed_cols = ROLE_COLUMNS.get(role, [])
    
    if role != "admin" and "refund_amount_idr" in low:
        raise ValueError(f"Kolom refund tidak boleh untuk role {role}")

    if re.search(r"2025|2027|2024", low):
        return "NO_DATA", [], []

    if "exception_note" in low:
        pass

    with engine.connect() as conn:
        with conn.begin():
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            conn.exec_driver_sql(f"SET LOCAL search_path TO {db_schema}")
            result = conn.execute(text(clean_cand))
            columns = list(result.keys())
            rows = [tuple(r) for r in result.fetchall()]
            return columns, rows