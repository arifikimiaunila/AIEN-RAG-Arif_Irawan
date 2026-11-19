import os
import re
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from src.rbac import ROLE_COLUMNS

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("RAG_DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL belum di-set")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

def send_to_pg(clean_cand: str, role: str, db_schema: str = "gold"):
    low = clean_cand.lower().strip()
    if not low.startswith("select"):
        raise ValueError("Only SELECT allowed")

    ALLOWED_TABLES = ["gold.shipment_fact", "gold.carrier_daily", "gold.city_daily"]
    if not any(t in low for t in ALLOWED_TABLES):
        raise ValueError("Tabel tidak diizinkan, hanya Gold Layer")

    if role != "admin" and "refund_amount_idr" in low:
        raise ValueError(f"Kolom refund tidak boleh untuk role {role}")
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f'SET LOCAL search_path TO "{db_schema}"'))
            result = conn.execute(text(clean_cand))
            columns = list(result.keys())
            rows = [tuple(r) for r in result.fetchall()]
            return columns, rows
