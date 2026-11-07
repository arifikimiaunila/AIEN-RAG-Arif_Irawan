from __future__ import annotations

import base64
import io
import os
from typing import Any

import httpx
import streamlit as st

API_URL = os.getenv("AGENT_API_URL", "http://localhost:8000").rstrip("/")

def api_request(method: str, path: str, token: str, **kwargs: Any) -> dict | None:
    try:
        response = httpx.request(
            method,
            f"{API_URL}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=35,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", "Permintaan gagal")
        except ValueError:
            detail = "Permintaan gagal"
        if exc.response.status_code != 404:
            st.error(f"API {exc.response.status_code}: {detail}")
    except (httpx.RequestError, ValueError):
        st.error("Backend tidak tersedia atau respons tidak valid.")
    return None

def render_chart_from_message(message: dict):
    if not isinstance(message, dict):
        return
    chart_url = message.get("chart_url") or message.get("chart") or message.get("image_url")
    chart_b64 = message.get("chart_base64") or message.get("image_base64")
    if chart_b64:
        try:
            st.image(base64.b64decode(chart_b64), caption="Grafik")
            return
        except Exception:
            pass
    if chart_url:
        url = chart_url if chart_url.startswith("http") else f"{API_URL}{chart_url}"
        try:
            token = st.session_state.get("active_token", "")
            r = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=20)
            if r.status_code == 200:
                st.image(io.BytesIO(r.content), caption="Grafik")
            else:
                st.image(url, caption="Grafik")
        except Exception:
            st.image(url, caption="Grafik")

st.set_page_config(page_title="Agent Analitik Pengiriman & Validasi", page_icon="📦", layout="wide")
st.title("📦 Agent Analitik Pengiriman (Gold Layer)")
st.caption("Fakta analitik berasal dari Neon Gold. Percakapan demo disimpan oleh backend.")

st.sidebar.header("🔐 Autentikasi & Role")

token_options = {
    "-- Pilih Token Demo --": "",
    "Ops Logistik (token_kurir_ops)": "token_kurir_ops",
    "Manajemen Executive (token_exec)": "token_exec",
    "Customer Service (token_cs)": "token_cs",
    "Marketing Campaign (token_mkt)": "token_mkt",
    "Finance Anti-Fraud (token_fin)": "token_fin",
}

selected_token_key = st.sidebar.selectbox("Pilih Token Role Cepat", list(token_options.keys()))
default_token_value = token_options[selected_token_key] if selected_token_key != "-- Pilih Token Demo --" else ""

token = st.sidebar.text_input("Atau masukkan Bearer token demo", value=default_token_value, type="password")

if "active_token" not in st.session_state:
    st.session_state["active_token"] = token
    st.session_state["last_chart"] = {}
elif st.session_state.get("active_token") != token:
    st.session_state["active_token"] = token
    st.session_state["last_chart"] = {}

if not token:
    st.info("Silakan masukkan atau pilih token demo di sidebar untuk memulai.")
    st.stop()

role_mapping = {
    "token_kurir_ops": {"username": "logistik", "role": "ops_logistik_kurir"},
    "token_exec": {"username": "exec", "role": "manajemen_executive"},
    "token_cs": {"username": "cs", "role": "customer_service"},
    "token_mkt": {"username": "marketing", "role": "marketing_campaign"},
    "token_fin": {"username": "finance", "role": "finance_anti_fraud"}
}

current_user_info = role_mapping.get(token)

if current_user_info:
    nama_ramah = {
        "logistik": "Tim Logistik",
        "exec": "Manajemen",
        "cs": "Customer Service",
        "marketing": "Tim Marketing",
        "finance": "Tim Finance"
    }.get(current_user_info['username'], current_user_info['username'])
    st.sidebar.success(f"Login sebagai: **{nama_ramah}**")
else:
    st.sidebar.warning("Token kustom digunakan (validasi tetap dilakukan oleh backend).")

st.sidebar.markdown("---")

nama_role = current_user_info['username'] if current_user_info else "logistik"

sapaan = {
    "logistik": "Tim Logistik",
    "exec": "Manajemen",
    "cs": "Customer Service",
    "marketing": "Tim Marketing",
    "finance": "Tim Finance"
}.get(nama_role, "Tim Logistik")

pertanyaan_per_role = {
    "logistik": {
        "judul": "Kamu bisa tanya soal performa pengiriman Q3.",
        "bisa": [
            "✅ **SLA** - Apakah pengiriman tepat waktu?",
            "✅ **Volume** - Berapa banyak paket yang dikirim?",
            "✅ **Refund** - Berapa banyak yang komplain / refund?",
        ],
        "contoh": [
            "📦 Gimana SLA pengiriman Q3?",
            "📊 Berapa volume pengiriman Q3?",
            "💸 Berapa refund Q3?",
        ]
    },
    "exec": {
        "judul": "Kamu bisa tanya ringkasan performa Q3 untuk keputusan bisnis.",
        "bisa": [
            "✅ **Ringkasan** - Gimana performa Q3 secara keseluruhan?",
            "✅ **Carrier** - Carrier mana yang paling bagus?",
            "✅ **Kota** - Kota mana yang paling banyak kirim?",
        ],
        "contoh": [
            "📈 Gimana ringkasan performa pengiriman Q3?",
            "🏆 Carrier mana yang SLA-nya paling bagus di Q3?",
            "🌆 Kota mana yang volume pengirimannya paling tinggi?",
        ]
    },
    "cs": {
        "judul": "Kamu bisa tanya soal komplain dan keterlambatan buat jawab customer.",
        "bisa": [
            "✅ **Refund** - Berapa banyak komplain / refund?",
            "✅ **SLA** - Carrier / kota mana yang sering telat?",
            "✅ **Volume** - Berapa banyak paket yang bermasalah?",
        ],
        "contoh": [
            "💸 Berapa refund Q3? Carrier mana yang paling banyak refund?",
            "⏰ Kota mana yang SLA-nya paling jelek di Q3?",
            "📦 Carrier mana yang paling sering telat?",
        ]
    },
    "marketing": {
        "judul": "Kamu bisa tanya soal volume buat bahan campaign.",
        "bisa": [
            "✅ **Volume** - Kota / carrier mana yang paling rame?",
            "✅ **SLA** - SLA kita bagus gak buat dijadiin promo?",
            "✅ **Tren** - Volume naik / turun di Q3?",
        ],
        "contoh": [
            "📊 Kota mana yang volume pengirimannya paling tinggi di Q3?",
            "🚀 Carrier mana yang paling banyak dipakai customer?",
            "📈 Gimana tren volume pengiriman di Q3?",
        ]
    },
    "finance": {
        "judul": "Kamu bisa tanya soal refund dan potensi fraud di Q3.",
        "bisa": [
            "✅ **Refund** - Berapa banyak refund? Di carrier / kota mana?",
            "✅ **Fraud** - Ada pola refund yang aneh gak?",
            "✅ **Volume** - Berapa total volume yang terkait refund?",
        ],
        "contoh": [
            "💸 Berapa total refund Q3? Carrier mana yang paling tinggi?",
            "🚨 Kota mana yang refund-nya paling tinggi dan mencurigakan?",
            "📊 Berapa volume dan refund per carrier di Q3?",
        ]
    },
}

data_role = pertanyaan_per_role.get(nama_role, pertanyaan_per_role["logistik"])

st.sidebar.subheader(f"👋 Halo, {sapaan}")
st.sidebar.markdown(data_role["judul"])
st.sidebar.markdown("**Yang bisa kamu tanya:**")
for item in data_role["bisa"]:
    st.sidebar.markdown(item)

st.sidebar.markdown("**Coba klik salah satu:**")
for q in data_role["contoh"]:
    if st.sidebar.button(q, key=f"btn_{nama_role}_{q[:20]}"):
        st.session_state["draft_pertanyaan"] = q
        st.rerun()

if st.sidebar.button("🔍 Cek Akses Saya"):
    payload = {
        "query_target": "Performa SLA Pengiriman Q3",
        "metrics": ["sla", "volume", "refund"]
    }
    with st.spinner("Mengecek akses kamu..."):
        res = api_request("POST", "/api/v1/analytic-agent/query", token, json=payload)
        if res and res.get("status") == "success":
            st.sidebar.success("✅ Akses kamu aktif!")
            st.sidebar.markdown(f"**Pengguna:** {res.get('user', sapaan)}")
            st.sidebar.markdown("**Kamu boleh lihat:** SLA, Volume, Refund")
        elif res:
            st.sidebar.error("Akses ditolak. Coba ganti peran di atas.")

st.sidebar.markdown("---")

if st.sidebar.button("Percakapan baru"):
    created = api_request("POST", "/api/v1/conversations", token, json={})
    if created:
        st.session_state["conversation_id"] = created["id"]
        st.session_state["draft_pertanyaan"] = ""
        st.session_state["last_chart"] = {}
        st.session_state.pop("confirm_delete", None)
        st.session_state.pop("just_deleted", None)
        st.rerun()

listing = api_request("GET", "/api/v1/conversations", token)
conversations = listing.get("conversations", []) if listing else []
ids = [item["id"] for item in conversations]
if ids:
    current = st.session_state.get("conversation_id")
    if current not in ids:
        current = None
        st.session_state["conversation_id"] = None
        st.session_state.pop("just_deleted", None)

    if st.session_state.get("conversation_id"):
        selected = st.sidebar.selectbox(
            "Percakapan saya",
            ids,
            index=ids.index(st.session_state["conversation_id"]) if st.session_state["conversation_id"] in ids else 0,
            format_func=lambda value: next(
                (item.get("title") or value for item in conversations if item["id"] == value),
                value,
            ),
        )
        if selected != st.session_state.get("conversation_id"):
            st.session_state["conversation_id"] = selected
            st.session_state.pop("confirm_delete", None)
            st.rerun()

        st.sidebar.markdown("---")
        if not st.session_state.get("confirm_delete"):
            if st.sidebar.button("🗑️ Hapus Percakapan", key="btn_hapus"):
                st.session_state["confirm_delete"] = True
                st.rerun()
        else:
            st.sidebar.warning("Hapus percakapan ini? History tidak bisa dikembalikan.")
            col1, col2 = st.sidebar.columns(2)
            with col1:
                if st.button("✅ Ya, Hapus", key="btn_confirm_hapus", use_container_width=True):
                    cid = st.session_state.get("conversation_id")
                    api_request("DELETE", f"/api/v1/conversations/{cid}", token)
                    st.session_state["conversation_id"] = None
                    st.session_state["draft_pertanyaan"] = ""
                    st.session_state["last_chart"] = {}
                    st.session_state["just_deleted"] = True
                    st.session_state.pop("confirm_delete", None)
                    st.success("Percakapan dihapus.")
                    st.rerun()
            with col2:
                if st.button("Batal", key="btn_batal_hapus", use_container_width=True):
                    st.session_state.pop("confirm_delete", None)
                    st.rerun()
else:
    st.info("Buat percakapan baru untuk mulai bertanya.")

conversation_id = st.session_state.get("conversation_id")
if conversation_id:
    detail = api_request("GET", f"/api/v1/conversations/{conversation_id}", token)
    if detail:
        for message in detail.get("messages", []):
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
                render_chart_from_message(message)

        draft = st.session_state.get("draft_pertanyaan", "")
        with st.form("form_chat", clear_on_submit=True):
            prompt = st.text_input(
                "Tanya tentang volume, SLA, refund, carrier, atau kota",
                value=draft,
                placeholder="Tanya tentang volume, SLA, refund, carrier, atau kota",
                label_visibility="collapsed",
            )
            kirim = st.form_submit_button("➤ Kirim")

        if kirim and prompt:
            st.session_state["draft_pertanyaan"] = ""
            result = api_request(
                "POST",
                f"/api/v1/conversations/{conversation_id}/messages",
                token,
                json={"content": prompt},
            )
            if result:
                st.rerun()
    else:
        st.session_state["conversation_id"] = None
        st.session_state["draft_pertanyaan"] = ""
        st.rerun()