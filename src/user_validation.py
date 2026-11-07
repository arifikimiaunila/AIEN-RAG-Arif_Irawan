from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import List, Dict, Any

app = FastAPI(title="Analytic Agent Kurir API - Gold Layer")

security = HTTPBearer()

ALLOWED_ROLES = {
    "ops_logistik_kurir",
    "manajemen_executive",
    "customer_service",
    "marketing_campaign",
    "finance_anti_fraud"
}

TOKEN_TO_USER = {
    "token_kurir_ops": {"username": "logistik", "role": "ops_logistik_kurir", "layer": "gold"},
    "token_exec": {"username": "exec", "role": "manajemen_executive", "layer": "gold"},
    "token_cs": {"username": "cs", "role": "customer_service", "layer": "gold"},
    "token_mkt": {"username": "marketing", "role": "marketing_campaign", "layer": "gold"},
    "token_fin": {"username": "finance", "role": "finance_anti_fraud", "layer": "gold"},
}

def decode_token_service(token: str) -> Dict[str, Any]:
    """
    Fungsi utilitas untuk mendekode token atau mencocokkannya dengan database/penyimpanan.
    (Bisa diganti dengan JWT decode menggunakan PyJWT atau python-jose di produksi).
    """
    user = TOKEN_TO_USER.get(token)
    if user is None:
        raise ValueError("Invalid token")
    return user

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    """
    Fungsi dependency FastAPI untuk mengambil dan memvalidasi token dari header Authorization.
    """
    token = credentials.credentials
    try:
        user = decode_token_service(token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials or token not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials or token not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

def verify_gold_layer_access(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """
    Fungsi dependency khusus untuk memverifikasi apakah user memiliki hak akses
    ke Gold Layer Analytic Agent berdasarkan role dan layer-nya.
    """
    user_role = current_user.get("role")
    user_layer = current_user.get("layer")

    if user_role not in ALLOWED_ROLES or user_layer != "gold":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Analytic Agent Kurir is restricted to authorized Gold Layer roles only."
        )
    return current_user

class AnalyticRequest(BaseModel):
    query_target: str
    metrics: List[str]

@app.post("/api/v1/analytic-agent/query")
def run_analytic_agent(
    payload: AnalyticRequest,
    current_user: Dict[str, Any] = Depends(verify_gold_layer_access)
):
    """
    Endpoint Analytic Agent Kurir khusus Gold Layer.
    Hanya bisa diakses oleh Ops & Logistik, Executive, CS, Marketing, dan Finance.
    """
    return {
        "status": "success",
        "user": current_user["username"],
        "role": current_user["role"],
        "message": f"Akses diizinkan ke Analytic Agent untuk analisis: {payload.query_target}",
        "authorized_metrics": payload.metrics
    }