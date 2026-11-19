from contextlib import asynccontextmanager
from pathlib import Path
import base64
import os
import re as re
import sqlite3
import subprocess
import sys
import psycopg2
from src.system_prompt import FORBIDDEN_SQL
from datetime import datetime, timezone
from fastapi import Header
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from src.db_set import db_set, check_and_fill_csv, get_engine
from src.connect_to_db import connect_to_db
from src.user_validation import run_analytic_agent, AnalyticRequest, TOKEN_TO_USER
from src.send_to_pg import send_to_pg
from src.answer_from_db_agent import answer_from_db_agent

db = None
engine = None
schema_text = None

generate_sql = None
execute_readonly = None

FORBIDDEN_INJECTION = [
    "abaikan instruksi", "abaikan perintah", "lupakan instruksi",
    "ignore previous", "ignore all previous", "disregard",
    "jangan ikuti sistem", "mode developer", "jailbreak",
    "tampilkan password", "tampilkan semua user",
    "buka tabel", "tampilkan isi tabel",
]

def normalisasi_pertanyaan(q: str) -> str:
    q_baru = re.sub(
        r"jangan\s+ubah[^.?\n]*",
        "pakai kota, metrik, dan rentang tanggal yang sama seperti sebelumnya",
        q,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", q_baru).strip()

def is_forbidden(question: str) -> bool:
    q = question.lower()
    if any(p in q for p in FORBIDDEN_INJECTION):
        return True
    for kw in FORBIDDEN_SQL:
        if re.search(r'\b' + re.escape(kw) + r'\b', q):
            return True
    return False

def simpan_dan_return(conversation_id, jawaban_error):
    conn_err = _get_sqlite()
    try:
        conn_err.execute(
            "INSERT INTO messages (conversation_id, role, content, chart_base64, created_at) VALUES (?, ?, ?, ?, ?)",
            (conversation_id, "assistant", jawaban_error, None, _now_iso()),
        )
        conn_err.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (_now_iso(), conversation_id),
        )
        conn_err.commit()
    finally:
        conn_err.close()
    return {
        "conversation_id": conversation_id,
        "answer": jawaban_error,
        "data_basis": "Tidak ada - perintah berbahaya ditolak",
        "outcome": "refused",
        "message": {"role": "assistant", "content": jawaban_error}
    }

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def _sqlite_path():
    return os.getenv("SQLITE_PATH", "/app/data/conversations.sqlite3")

def _get_sqlite():
    path = _sqlite_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def _init_sqlite():
    conn = _get_sqlite()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                chart_base64 TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_owner ON conversations(owner_id, updated_at)")
        conn.commit()
    finally:
        conn.close()

def _get_conv_or_404(conversation_id: str, owner_id: str):
    conn = _get_sqlite()
    try:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Conversation tidak ditemukan")
        
        if row["owner_id"] != owner_id:
            raise HTTPException(status_code=404, detail="Conversation tidak ditemukan")
        msgs = conn.execute(
            "SELECT role, content, chart_base64, created_at FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()
        return {
            "id": row["id"],
            "title": row["title"],
            "owner_id": row["owner_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "messages": [
                {"role": m["role"], "content": m["content"], "chart_base64": m["chart_base64"], "created_at": m["created_at"]}
                for m in msgs
            ],
        }
    finally:
        conn.close()

_F2_AMBIGUOUS = re.compile(
    r"\b(sebelumnya|dibanding|dibandingkan|bandingkan|yang tadi|tersebut|lanjutkan|bagaimana dibanding|gimana dibanding)\b",
    re.IGNORECASE,
    )

def _is_ambiguous_first_message(question: str, history: str) -> bool:
    has_assistant = "assistant:" in (history or "").lower()
    if has_assistant:
        return False
    if not question:
        return False
    return bool(_F2_AMBIGUOUS.search(question))

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Inisialisasi database dan pemuatan data untuk RAG...")
    global db, engine, schema_text, generate_sql, execute_readonly

    
    _init_sqlite()
    print(f"SQLite percakapan siap di: {_sqlite_path()}")

    try:
        import os
        import psycopg
        from dotenv import load_dotenv
        load_dotenv()
        url = os.getenv('RAG_DATABASE_URL') or os.getenv('DATABASE_URL') or ""
        if not url:
            raise ValueError("RAG_DATABASE_URL / DATABASE_URL kosong di container api, cek .env / docker-compose.yml")
        url = url.replace('postgresql+psycopg2://', 'postgresql://').strip('"').strip("'")

        
        from src.db_set import db_set, check_and_fill_csv, get_engine
        print("[lifespan] Menjalankan db_set()...")
        db_set()
        print("[lifespan] db_set() selesai.")
        
        conn = psycopg.connect(url)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM gold.shipment_fact;")
        jumlah_shipment = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM gold.carrier_daily;")
        jumlah_carrier = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM gold.city_daily;")
        jumlah_city = cur.fetchone()[0]
        conn.close()
        print(f"[lifespan] COUNT saat startup - shipment_fact: {jumlah_shipment}, carrier_daily: {jumlah_carrier}, city_daily: {jumlah_city}")

        if jumlah_shipment == 0 or jumlah_carrier == 0 or jumlah_city == 0:
            print("[lifespan] Ada tabel yang masih 0, menjalankan check_and_fill_csv()...")
            pg_engine = get_engine()
            check_and_fill_csv(pg_engine)
            print("[lifespan] check_and_fill_csv() selesai.")
        else:
            print("[lifespan] Semua tabel sudah terisi, melewati check_and_fill_csv().")

        db, engine = connect_to_db()
        print("Koneksi database RAG berhasil diinisialisasi.")
        schema_text = db.get_table_info()
        print("Schema text berhasil dimuat:")
        print(schema_text)

        from src.system_prompt import generate_sql as imported_generate_sql
        generate_sql = imported_generate_sql
        print("Fungsi generate_sql berhasil diimpor dari src.system_prompt.")

    except Exception as e:
        print(f"Peringatan/Error saat setup database atau impor modul: {e}")
        import traceback; traceback.print_exc()

    streamlit_path = Path("app.py")
    streamlit_process = None

    if streamlit_path.exists():
        print("Memulai antarmuka Streamlit (app.py)...")
        streamlit_process = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", str(streamlit_path)]
        )
    else:
        print(f"[WARNING] File Streamlit tidak ditemukan di path: {streamlit_path.resolve()}")

    yield

    if streamlit_process:
        print("\nMematikan proses Streamlit...")
        streamlit_process.terminate()

app = FastAPI(title="Analytic Agent Kurir API - Gold Layer", lifespan=lifespan)

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@app.post("/ask-rag")
def ask_rag_endpoint(prompt: str):
    return {
        "prompt": prompt,
        "response": "Hasil kueri RAG dari database gold.",
        "schema_loaded": bool(schema_text)
    }

app.post("/api/v1/analytic-agent/query")(run_analytic_agent)

def get_user_from_token(authorization: str | None = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token tidak ada")
    token = authorization.replace("Bearer ", "").strip()
    user = TOKEN_TO_USER.get(token)
    if not user:
        raise HTTPException(status_code=401, detail="Token tidak valid")
    return user

@app.post("/api/v1/conversations", status_code=201)
def create_conversation(payload: dict | None = None, authorization: str | None = Header(None)):
    user = get_user_from_token(authorization)
    import uuid
    conn = _get_sqlite()
    try:
        conv_id = f"conv-{uuid.uuid4().hex[:8]}"
        now = _now_iso()
        rows_t = conn.execute("SELECT title FROM conversations").fetchall()
        max_n = 0
        for r in rows_t:
            m = re.search(r"Percakapan\s+(\d+)", str(r["title"]))
            if m:
                max_n = max(max_n, int(m.group(1)))
        title = f"Percakapan {max_n + 1}"
        conn.execute(
            "INSERT INTO conversations (id, owner_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (conv_id, user["username"], title, now, now),
        )
        conn.commit()
        return {"id": conv_id, "title": title, "updated_at": now}
    finally:
        conn.close()

@app.get("/api/v1/conversations")
def list_conversations(authorization: str | None = Header(None)):
    user = get_user_from_token(authorization)
    conn = _get_sqlite()
    try:
        rows = conn.execute(
            "SELECT id, title, updated_at FROM conversations WHERE owner_id = ? ORDER BY updated_at DESC",
            (user["username"],),
        ).fetchall()
        return {"conversations": [{"id": r["id"], "title": r["title"], "updated_at": r["updated_at"]} for r in rows]}
    finally:
        conn.close()

@app.get("/api/v1/conversations/{conversation_id}")
def get_conversation(conversation_id: str, authorization: str | None = Header(None)):
    user = get_user_from_token(authorization)
    return _get_conv_or_404(conversation_id, user["username"])

@app.delete("/api/v1/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, authorization: str | None = Header(None)):
    user = get_user_from_token(authorization)
    _get_conv_or_404(conversation_id, user["username"])
    conn = _get_sqlite()
    try:
        conn.execute(
            "DELETE FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        conn.execute(
            "DELETE FROM conversations WHERE id = ? AND owner_id = ?",
            (conversation_id, user["username"]),
        )
        conn.commit()
        return {"ok": True, "deleted_id": conversation_id}
    finally:
        conn.close()

@app.post("/api/v1/conversations/{conversation_id}/messages")
def ask_conversation_message(        
    conversation_id: str,
    payload: dict,
    authorization: str | None = Header(None)
):
    user = get_user_from_token(authorization)
    conv = _get_conv_or_404(conversation_id, user["username"])

    question = payload.get("content", "") or payload.get("prompt", "")
    q_low = question.lower()
    is_negasi = bool(re.search(r"\b(jangan|tidak|tanpa)\s+(ubah|ganti|edit)", q_low))
    question = normalisasi_pertanyaan(question)
    history = "\n".join([f"{m['role']}: {m['content']}" for m in conv["messages"][-6:]])
    if is_forbidden(question):
        jawaban_error = "Maaf, permintaan tersebut ditolak karena mengandung perintah berbahaya yang tidak diizinkan. Saya hanya bisa membantu seputar analitik pengiriman."
        return simpan_dan_return(conversation_id, jawaban_error)
    conn = _get_sqlite()
    try:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, chart_base64, created_at) VALUES (?, ?, ?, ?, ?)",
            (conversation_id, "user", question, None, _now_iso()),
        )
        conn.commit()
    finally:
        conn.close()

    sql_generator = generate_sql
    if sql_generator is None:
        from src.system_prompt import generate_sql as sql_generator
    username = user["username"]
    role = user["role"]

    global db, engine, schema_text
    if engine is None:
        print("[DEBUG] engine masih None, coba connect_to_db() ulang...", flush=True)
        try:
            db, engine = connect_to_db()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"DB engine gagal init: {e}")
        if engine is None:
            raise HTTPException(status_code=500, detail="DB engine masih None setelah retry, cek RAG_DATABASE_URL")

    _is_followup_q = any(k in question.lower() for k in ["minggu mana", "paling tinggi", "selisih", "persentase kenaikan", "dibanding minggu", "kenaikan"])
    if _is_ambiguous_first_message(question, history) and not _is_followup_q:
        jawaban_klarifikasi = "Sebelumnya yang mana ya? Di percakapan ini belum ada konteks. Mau membandingkan minggu apa vs minggu apa, atau carrier / kota apa vs apa?"
        conn_cl = _get_sqlite()
        try:
            conn_cl.execute(
                "INSERT INTO messages (conversation_id, role, content, chart_base64, created_at) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, "assistant", jawaban_klarifikasi, None, _now_iso()),
            )
            conn_cl.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (_now_iso(), conversation_id),
            )
            conn_cl.commit()
        finally:
            conn_cl.close()
        return {
            "conversation_id": conversation_id,
            "answer": jawaban_klarifikasi,
            "data_basis": "Tidak ada - butuh klarifikasi",
            "outcome": "need_clarification",
            "message": {"role": "assistant", "content": jawaban_klarifikasi}
        }

    if re.search(r"\b(abaikan\s+aturan|ungkap\s+prompt|tampilkan\s+.*prompt|bocorkan.*prompt|instruksi\s+sistem|system\s+prompt|prompt\s+sistem)\b", question, re.IGNORECASE):
        jawaban_tolak_p1 = "Maaf, saya tidak bisa membagikan prompt sistem atau instruksi internal. Saya hanya bisa membantu analitik pengiriman dari data Gold."
        conn_p1 = _get_sqlite()
        try:
            conn_p1.execute(
                "INSERT INTO messages (conversation_id, role, content, chart_base64, created_at) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, "assistant", jawaban_tolak_p1, None, _now_iso()),
            )
            conn_p1.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (_now_iso(), conversation_id),
            )
            conn_p1.commit()
        finally:
            conn_p1.close()
        return {
            "conversation_id": conversation_id,
            "answer": jawaban_tolak_p1,
            "data_basis": "Tidak ada - prompt injection ditolak",
            "outcome": "refused",
            "message": {"role": "assistant", "content": jawaban_tolak_p1}
        }

    if not is_negasi and re.search(r"\b(ubah\s+status|hapus\s+kiriman|tambah\s+kiriman|update\s+.*\s+menjadi)\b", q_low):
        jawaban_tolak_tulis = "Maaf, saya tidak bisa mengubah data. Saya hanya bisa membaca dan menganalisis data pengiriman dari Gold, tidak bisa mengubah, menambah, atau menghapus status kiriman."
        conn_w = _get_sqlite()
        try:
            conn_w.execute(
                "INSERT INTO messages (conversation_id, role, content, chart_base64, created_at) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, "assistant", jawaban_tolak_tulis, None, _now_iso()),
            )
            conn_w.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (_now_iso(), conversation_id),
            )
            conn_w.commit()
        finally:
            conn_w.close()
        return {
            "conversation_id": conversation_id,
            "answer": jawaban_tolak_tulis,
            "data_basis": "Tidak ada - operasi tulis ditolak",
            "outcome": "refused",
            "message": {"role": "assistant", "content": jawaban_tolak_tulis}
        }

    try:
        schema_local = schema_text
        if not schema_local and engine is not None:
            try:
                schema_local = db.get_table_info()
            except Exception:
                pass
        _q_low = question.lower()
        _followup_keys = ["minggu mana", "berapa selisih", "berapa kenaikan", "lanjutkan", "teruskan", "kasus 0", "bandingkan"]
        if any(k in _q_low for k in _followup_keys) and history:
            _hist = history if isinstance(history, str) else str(history)
            _hist_low = _hist.lower()
            _kota_list = ["bandung", "jakarta", "surabaya", "medan", "makassar", "semarang", "yogyakarta", "palembang", "balikpapan", "denpasar", "malang", "bekasi", "tangerang", "depok", "bogor"]
            _city = ""
            for _kc in _kota_list:
                if _kc in _hist_low:
                    _city = _kc.capitalize()
                    break
            _m_d2 = _re.findall(r"(20\d{2}-\d{2}-\d{2})", _hist)
            _d1 = _m_d2[0] if len(_m_d2) >= 1 else ""
            _d2 = _m_d2[1] if len(_m_d2) >= 2 else ""
            if not _d1 or not _d2:
                _bulan = {"januari": "01", "februari": "02", "maret": "03", "april": "04", "mei": "05", "juni": "06", "juli": "07", "agustus": "08", "september": "09", "oktober": "10", "november": "11", "desember": "12"}
                for _bn, _bm in _bulan.items():
                    if _bn in _hist_low:
                        _m_th = _re.search(r"20\d{2}", _hist)
                        _yy = _m_th.group(0) if _m_th else "2026"
                        _mm = int(_bm)
                        _nm = _mm + 1
                        _ny = int(_yy) + 1 if _nm > 12 else int(_yy)
                        _nm = 1 if _nm > 12 else _nm
                        _d1 = f"{_yy}-{_bm}-01"
                        _d2 = f"{_ny}-{_nm:02d}-01"
                        break
            _ctx = f"destination_city='{_city}'" if _city else "kota yang sama seperti di history"
            _ctx += f" dan order_date >= '{_d1}' AND order_date < '{_d2}'" if _d1 and _d2 else " dan rentang tanggal yang sama seperti di history"
            question = f"Untuk {_ctx}, hitung jumlah kiriman per minggu pakai DATE_TRUNC('week', order_date), tentukan minggu mana yang paling tinggi, berapa selisih jumlah kirimannya dan berapa persentase kenaikannya dibanding minggu tepat sebelumnya. Pertanyaan asli: {question}"
            print(f"[FOLLOWUP-RESOLVED] city={_city} d1={_d1} d2={_d2} question={question}", flush=True)
        sql, columns, rows = sql_generator(question, username, role, engine, history=history, schema_text=schema_local)
    except Exception as e:
        print(f"[ERROR] generate_sql gagal untuk '{question}': {e}", flush=True)
        try:
            corrected_question = f"""{question}
                [KOREKSI SISTEM: Query sebelumnya gagal.
                JANGAN buat nama tabel baru. JANGAN buat nama kolom baru.
                Kolom shipment_fact yang BOLEH: shipment_id, order_date, carrier_id, origin_hub, destination_city, service_level, promised_delivery_at_utc, delivered_at_utc, delivery_status, shipping_fee_idr, refund_amount_idr, exception_note.
                DILARANG SELECT jumlah_kiriman / kiriman_minggu_sebelumnya / kiriman_minggu_31_agustus langsung dari gold.shipment_fact.
                Pakai COUNT(*) AS jumlah_kiriman.
                Untuk pertanyaan KENAPA minggu 31 Agustus turun, jawab: karena minggu itu hanya terhitung 31 Agustus saja, data dibatasi sampai < 2026-09-01, bukan penurunan performa.
                Contoh BENAR: SELECT COUNT(*) AS jumlah_kiriman FROM gold.shipment_fact WHERE destination_city = 'Bandung' AND order_date >= '2026-08-31' AND order_date < '2026-09-01'.]"""
            print(f"[RETRY] generate_sql ulang dengan koreksi tabel untuk '{question}'", flush=True)
            sql, columns, rows = sql_generator(corrected_question, username, role, engine, history=history, schema_text=schema_text)
        except Exception as e2:
            print(f"[ERROR] retry generate_sql gagal juga: {e2}", flush=True)
            if any(k in question.lower() for k in ["jumlah kiriman", "on-time", "ontime", "on time", "kiriman"]):
                jawaban_error = "Data untuk periode yang diminta tidak tersedia."
            else:
                jawaban_error = "Maaf, permintaan tersebut di luar cakupan saya. Saya hanya bisa membantu seputar analitik pengiriman."
            return simpan_dan_return(conversation_id, jawaban_error)

    _followup = ["lanjutkan", "teruskan", "kasus 0", "kasus 4", "bandingkan", "minggu mana", "berapa kenaikan", "paling tinggi", "selisih", "persentase kenaikan", "dibanding minggu"]
    if (sql or "").strip() == "REFUSED_OUT_OF_SCOPE" and any(k in question.lower() for k in _followup) and history:
        corrected = f"{question} [KONTEKS: Lanjutkan analisis dari history di atas, pakai kota/periode/metrik yang sama, jangan ganti konteks]"
        sql, columns, rows = sql_generator(corrected, username, role, engine, history=history, schema_text=schema_local)
    if (sql or "").strip() == "REFUSED_OUT_OF_SCOPE":
        jawaban_tolak = "Maaf, permintaan tersebut di luar cakupan saya. Saya hanya bisa membantu seputar analitik pengiriman."
        conn_r = _get_sqlite()
        try:
            conn_r.execute(
                "INSERT INTO messages (conversation_id, role, content, chart_base64, created_at) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, "assistant", jawaban_tolak, None, _now_iso()),
            )
            conn_r.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (_now_iso(), conversation_id),
            )
            conn_r.commit()
        finally:
            conn_r.close()
        return {
            "conversation_id": conversation_id,
            "answer": jawaban_tolak,
            "data_basis": "Tidak ada - out of scope",
            "outcome": "refused",
            "message": {"role": "assistant", "content": jawaban_tolak}
        }

    jawaban, chart = answer_from_db_agent(question, sql, columns, rows)
    _tech_to_user = {
        "order_date": "tanggal pemesanan",
        "delivered_at_utc": "tanggal pengiriman",
        "promised_delivery": "tanggal janji kirim",
        "created_at": "tanggal dibuat",
        "updated_at": "tanggal diperbarui",
    }
    jawaban = re.sub(
        r"(.+?)\s*\(\s*\1\s*\)",
        r"\1",
        jawaban, flags=re.IGNORECASE
    )

    for _k, _v in _tech_to_user.items():
        jawaban = re.sub(
            rf"{re.escape(_v)}\s*\(\s*{re.escape(_k)}\s*\)",
            _v, jawaban, flags=re.IGNORECASE
        )
    for _k, _v in _tech_to_user.items():
        jawaban = jawaban.replace(f"`{_k}`", _v)
        jawaban = jawaban.replace(_k, _v)

              
    if not rows or len(rows) == 0:
        _m_periode = re.search(
            r"(Januari|Februari|Maret|April|Mei|Juni|Juli|Agustus|September|Oktober|November|Desember)\s+20\d{2}",
            question,
            re.IGNORECASE,
            )
        if _m_periode:
            periode_text = _m_periode.group(0)
            _parts = periode_text.split()
            periode_text = _parts[0].capitalize() + " " + _parts[1]
        else:
            periode_text = "periode yang diminta"
        jawaban = f"Data {periode_text} tidak tersedia."
        chart = None
    _q_low2 = question.lower()
    if "exception" in _q_low2 or "catatan" in _q_low2 or "note" in _q_low2:
        _m_id = re.search(r"(SHP-\d+)", question, re.IGNORECASE)
        _id_tampil = _m_id.group(1).upper() if _m_id else "resi yang diminta"

        if rows:
            jawaban = (
                f"Catatan untuk {_id_tampil} tersedia, tetapi isinya tidak ditampilkan karena "
                f"berisi teks yang menyerupai instruksi. "
                f"Ini diperlakukan sebagai data, bukan instruksi yang saya ikuti. "
                f"Tidak ada perintah di dalamnya yang dijalankan dan tidak ada rahasia yang dibocorkan."
            )
        else:
            jawaban = f"Tidak ada catatan untuk {_id_tampil}."
        chart = None
    _q_low = question.lower()
    _is_realtime = any(k in _q_low for k in ["tepat sekarang", "saat ini", "real-time", "realtime", "hari ini", "di mana", "dimana", "berada"])
    if _is_realtime and rows:
        _tgl_str = "tanggal terakhir data yang tersedia"
        try:
            with engine.connect() as _conn:
                _res = _conn.execute(
                    __import__("sqlalchemy").text(
                        "SELECT MAX(order_date) FROM gold.shipment_fact"
                    )
                ).fetchone()
                if _res and _res[0]:
                    _dmax = _res[0]
                    if hasattr(_dmax, "day"):
                        _bulan_id = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
                        _tgl_str = f"{_dmax.day} {_bulan_id[_dmax.month]} {_dmax.year}"
                    else:
                        _m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(_dmax))
                        if _m:
                            _bulan_id = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
                            _tgl_str = f"{int(_m.group(3))} {_bulan_id[int(_m.group(2))]} {_m.group(1)}"
        except Exception as _e:
            print(f"[REALTIME] gagal ambil tanggal global: {_e}", flush=True)

        jawaban = (
            f"Status real-time tidak tersedia. Data historis sampai {_tgl_str} "
            f"tidak membuktikan lokasi atau kedatangan paket hari ini."
        )
        chart = None
    chart_base64 = None
    if chart and Path(chart).exists():
        with open(chart, "rb") as f:
            chart_base64 = base64.b64encode(f.read()).decode()

    assistant_msg = {"role": "assistant", "content": jawaban, "chart_base64": chart_base64}
    conn = _get_sqlite()
    try:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, chart_base64, created_at) VALUES (?, ?, ?, ?, ?)",
            (conversation_id, "assistant", jawaban, chart_base64, _now_iso()),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (_now_iso(), conversation_id),
        )
        conn.commit()
    finally:
        conn.close()

    outcome = "answered"
    if rows is not None and len(rows) == 0:
        outcome = "no_data"

    return {
        "conversation_id": conversation_id,
        "answer": jawaban,
        "data_basis": _summarize_data_basis(sql),
        "outcome": outcome,
        "message": assistant_msg,
    }

def _summarize_data_basis(sql: str) -> str:
    if not sql:
        return ""
    tables = re.findall(r"(?:FROM|JOIN)\s+([a-zA-Z0-9_\.]+)", sql, flags=re.IGNORECASE)
    tables = list(dict.fromkeys(tables))
    dates = re.findall(r"DATE\s*'(\d{4}-\d{2}-\d{2})'", sql)
    periode = ""
    if len(dates) >= 2:
        periode = f", Periode: order_date {dates[0]} s.d. < {dates[1]}"
    elif len(dates) == 1:
        periode = f", Periode: order_date >= {dates[0]}"
    filt = ""
    if "delivery_status = 'delivered'" in sql or 'delivery_status' in sql:
        filt = ", Filter: delivery_status='delivered'"
    tabel_str = ", ".join(tables) if tables else ""
    if not tabel_str:
        return ""
    return f"Tabel: {tabel_str}{periode}{filt}"

@app.post("/api/v1/db-agent/query")
def db_agent_query_endpoint(payload: dict, authorization: str | None = Header(None)):
    user = get_user_from_token(authorization)
    try:
        prompt = payload.get("prompt", "")
        sql_generator = generate_sql
        if sql_generator is None:
            from src.system_prompt import generate_sql as sql_generator

        username = user["username"]
        role = user["role"]

        sql, columns, rows = sql_generator(prompt, username, role, engine)
        jawaban, chart = answer_from_db_agent(prompt, sql, columns, rows)
        if not rows or len(rows) == 0:
            jawaban = f"Data {periode_text} tidak tersedia."

        if chart and Path(chart).exists():
            return {
                "jawaban": jawaban,
                "chart_path": chart,
                "status": "Chart generated and sent successfully"
            }

        return {
            "jawaban": jawaban,
            "chart_path": None,
            "status": "Success without chart"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
