"""Cliente para la API de MercadoLibre: autenticación, pedidos, envíos y etiquetas."""

import os
import time
import requests

# --- Estado de tokens en memoria (se persisten en tokens.json) ---
import json

TOKENS_FILE = "tokens.json"


def _load_tokens():
    if os.path.exists(TOKENS_FILE):
        with open(TOKENS_FILE) as f:
            return json.load(f)
    return {
        "access_token": os.getenv("ML_ACCESS_TOKEN", ""),
        "refresh_token": os.getenv("ML_REFRESH_TOKEN", ""),
        "updated_at": 0,
    }


def _save_tokens(data):
    with open(TOKENS_FILE, "w") as f:
        json.dump(data, f)


def get_access_token():
    tokens = _load_tokens()
    return tokens.get("access_token", "")


def get_refresh_token():
    tokens = _load_tokens()
    return tokens.get("refresh_token", "")


# --- Auth ---


def intercambiar_code(code: str) -> dict:
    """Intercambia el authorization code por tokens (primer uso)."""
    resp = requests.post(
        "https://api.mercadolibre.com/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": os.getenv("ML_CLIENT_ID"),
            "client_secret": os.getenv("ML_CLIENT_SECRET"),
            "code": code,
            "redirect_uri": os.getenv("ML_REDIRECT_URI"),
        },
    )
    resp.raise_for_status()
    data = resp.json()
    _save_tokens(
        {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "updated_at": time.time(),
        }
    )
    return data


def refrescar_token() -> dict:
    """Renueva el access_token usando el refresh_token."""
    refresh = get_refresh_token()
    if not refresh:
        raise ValueError("No hay refresh_token disponible. Autorizá la app primero.")

    resp = requests.post(
        "https://api.mercadolibre.com/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": os.getenv("ML_CLIENT_ID"),
            "client_secret": os.getenv("ML_CLIENT_SECRET"),
            "refresh_token": refresh,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    _save_tokens(
        {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "updated_at": time.time(),
        }
    )
    print(f"[ML] Token renovado OK")
    return data


def _headers():
    return {"Authorization": f"Bearer {get_access_token()}"}


def _get_con_retry(url, params=None):
    """GET con retry automático si el token expiró (401)."""
    resp = requests.get(url, headers=_headers(), params=params)
    if resp.status_code == 401:
        print("[ML] Token expirado, renovando...")
        refrescar_token()
        resp = requests.get(url, headers=_headers(), params=params)
    resp.raise_for_status()
    return resp


# --- Pedidos ---


def obtener_pedidos_pagados(limit=10) -> list:
    """Obtiene los últimos pedidos con status=paid."""
    seller_id = os.getenv("ML_SELLER_ID")
    resp = _get_con_retry(
        "https://api.mercadolibre.com/orders/search",
        params={
            "seller": seller_id,
            "order.status": "paid",
            "sort": "date_desc",
            "limit": limit,
        },
    )
    return resp.json().get("results", [])


def obtener_estado_envio(shipping_id) -> dict:
    """Obtiene el estado de un envío."""
    resp = _get_con_retry(
        f"https://api.mercadolibre.com/shipments/{shipping_id}"
    )
    return resp.json()


def obtener_orden(order_id) -> dict:
    """Obtiene los detalles completos de una orden."""
    resp = _get_con_retry(
        f"https://api.mercadolibre.com/orders/{order_id}"
    )
    return resp.json()


def descargar_etiqueta_pdf(shipment_id) -> bytes:
    """Descarga la etiqueta de envío en PDF."""
    resp = requests.get(
        "https://api.mercadolibre.com/shipment_labels",
        headers=_headers(),
        params={
            "shipment_ids": shipment_id,
            "response_type": "pdf",
        },
    )
    if resp.status_code == 401:
        refrescar_token()
        resp = requests.get(
            "https://api.mercadolibre.com/shipment_labels",
            headers=_headers(),
            params={
                "shipment_ids": shipment_id,
                "response_type": "pdf",
            },
        )
    resp.raise_for_status()
    return resp.content
