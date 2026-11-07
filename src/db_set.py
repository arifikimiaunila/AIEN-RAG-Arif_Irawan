from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine, text
import os

ROOT = Path(__file__).resolve().parent.parent

def get_engine():
    db_url = os.getenv("RAG_DATABASE_URL") or os.getenv("DATABASE_URL") or "postgresql+psycopg2://user:user@localhost:5432/analytics"
    return create_engine(db_url)

def run_sql(connection, file_path: Path):
    if file_path.exists():
        sql_content = file_path.read_text(encoding="utf-8")
        connection.exec_driver_sql(sql_content)
        print(f"Berhasil mengeksekusi {file_path.name}")
    else:
        print(f"File SQL {file_path.name} tidak ditemukan di {file_path}, dilewati.")

def db_set():
    engine = get_engine()
    setup_sql_path = ROOT / "setup.sql"
    print("Memulai eksekusi skrip SQL...")
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS gold;"))
        conn.execute(text("SET search_path TO gold, public;"))
        run_sql(conn, setup_sql_path)
    print("Eksekusi SQL selesai.\n")

def check_and_fill_csv(engine):
    COLS = {
        "carrier_daily": [
            "metric_date", "carrier_id",
            "shipment_count", "delivered_count",
            "on_time_delivered_count", "late_delivered_count", "in_transit_count",
            "shipping_fee_idr", "refund_amount_idr"
        ],
        "city_daily": [
            "metric_date", "destination_city",
            "shipment_count", "delivered_count",
            "on_time_delivered_count", "late_delivered_count", "in_transit_count",
            "shipping_fee_idr", "refund_amount_idr"
        ],
        "shipment_fact": [
            "shipment_id", "order_date", "carrier_id", "origin_hub", "destination_city",
            "service_level", "promised_delivery_at_utc", "delivered_at_utc",
            "delivery_status", "shipping_cost", "refund_amount", "refund_reason"
        ],
    }

    jobs = [
        ("carrier_daily", ROOT / "data" / "carrier_daily.csv"),
        ("shipment_fact", ROOT / "data" / "shipment_fact.csv"),
        ("city_daily", ROOT / "data" / "city_daily.csv"),
    ]

    for table, csv_path in jobs:
        with engine.begin() as conn:
            result = conn.execute(text(f"SELECT COUNT(*) FROM gold.{table};")).scalar()
            if result != 0:
                print(f"Tabel {table} sudah memiliki {result} baris, dilewati.")
                continue

            print(f"Tabel {table} kosong. Mengisi dari {csv_path}...")
            if not csv_path.exists():
                print(f"File {csv_path} tidak ditemukan, gagal mengisi.")
                continue

            with open(csv_path, encoding="utf-8") as f:
                first_line = f.readline().strip()

            if "metric_date" in first_line or "shipment_id" in first_line:
                df = pd.read_csv(csv_path)
            else:
                print(f"File {csv_path.name} tidak ada header, pakai names manual.")
                df = pd.read_csv(csv_path, header=None, names=COLS[table])

            if "metric_date" in df.columns:
                df["metric_date"] = pd.to_datetime(df["metric_date"]).dt.date
            if "order_date" in df.columns:
                df["order_date"] = pd.to_datetime(df["order_date"]).dt.date
            if "promised_delivery_at_utc" in df.columns:
                df["promised_delivery_at_utc"] = pd.to_datetime(df["promised_delivery_at_utc"], utc=True)
            if "delivered_at_utc" in df.columns:
                df["delivered_at_utc"] = pd.to_datetime(df["delivered_at_utc"], utc=True)

            df.to_sql(name=table, con=conn, schema="gold", if_exists="append", index=False)
            print(f"Data {csv_path.name} berhasil masuk ke {table} ({len(df)} baris).")

    print("\nPemeriksaan/pengisian data CSV selesai!")

if __name__ == "__main__":
    eng = get_engine()
    db_set()
    check_and_fill_csv(eng)