import os
from langchain_community.utilities import SQLDatabase
from sqlalchemy import create_engine, text


def connect_to_db(
    rag_database_url: str | None = None,
    db_schema: str = "gold",
    tables: list[str] | None = None,
) -> tuple[SQLDatabase, object]:
    """Menghubungkan ke database PostgreSQL, memverifikasi koneksi,

    serta mengembalikan objek SQLDatabase LangChain dan engine.
    """
    if rag_database_url is None:
        rag_database_url = os.getenv(
            "RAG_DATABASE_URL",
            "postgresql+psycopg2://user:user@localhost:5432/analytics",
        )

    if tables is None:
        tables = ["shipment_fact", "carrier_daily", "city_daily"]
    engine = create_engine(rag_database_url, pool_pre_ping=True)
    db = SQLDatabase(
        engine=engine,
        schema=db_schema,
        include_tables=tables,
        view_support=True,
        sample_rows_in_table_info=2,
    )

    with engine.connect() as connection:
        connection_info = (
            connection.execute(
                text(
                    "SELECT current_database() AS database, "
                    "current_user AS role, "
                    "current_setting('statement_timeout') AS statement_timeout"
                )
            )
            .mappings()
            .one()
        )

    available_tables = db.get_usable_table_names()
    missing_tables = sorted(set(tables) - set(available_tables))

    print(dict(connection_info))
    print("Tabel gold yang tersedia:", available_tables)

    if missing_tables:
        raise RuntimeError(
            "Tabel skema gold belum lengkap: "
            + ", ".join(missing_tables)
            + ". Pastikan skrip ETL atau setup database sudah dijalankan."
        )

    return db, engine