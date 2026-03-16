"""Servicios auxiliares: generación de PDF, envío de email, base de datos de pedidos procesados."""

import os
import json
import base64

import requests
from fpdf import FPDF

# --- Base de datos simple (JSON file) para pedidos ya procesados ---

DB_FILE = "pedidos_procesados.json"


def _load_db() -> set:
    if os.path.exists(DB_FILE):
        with open(DB_FILE) as f:
            return set(json.load(f))
    return set()


def _save_db(ids: set):
    with open(DB_FILE, "w") as f:
        json.dump(list(ids), f)


def ya_procesado(order_id) -> bool:
    return str(order_id) in _load_db()


def marcar_procesado(order_id):
    ids = _load_db()
    ids.add(str(order_id))
    _save_db(ids)


# --- Generación de PDF de agradecimiento ---


def generar_pdf_agradecimiento(nombre_comprador: str, order_id) -> bytes:
    """Genera un PDF con mensaje de agradecimiento. Retorna los bytes del PDF."""
    telefono = os.getenv("TELEFONO_CONTACTO", "+54 11 1234-5678")

    pdf = FPDF()
    pdf.add_page()

    # Título
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 20, "Gracias por tu compra", ln=True)

    pdf.ln(10)

    # Mensaje
    pdf.set_font("Helvetica", "", 13)
    pdf.cell(0, 10, f"Hola {nombre_comprador},", ln=True)
    pdf.cell(0, 10, "gracias por tu compra.", ln=True)

    pdf.ln(10)

    pdf.cell(0, 10, "Por cualquier inconveniente te podes", ln=True)
    pdf.cell(0, 10, "comunicar con nosotros a traves de este numero:", ln=True)

    pdf.ln(5)

    # Teléfono destacado
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 10, telefono, ln=True)

    return pdf.output()


# --- Envío de emails via Resend (HTTP API) ---


def enviar_email(
    asunto: str,
    cuerpo: str,
    adjuntos: list[tuple[str, bytes]],
):
    """
    Envía un email con adjuntos a todos los destinatarios usando Resend API.
    adjuntos: lista de (nombre_archivo, bytes_contenido)
    """
    api_key = os.getenv("RESEND_API_KEY")
    from_email = os.getenv("RESEND_FROM", "onboarding@resend.dev")
    destinatarios = os.getenv("EMAIL_DESTINATARIOS", "").split(",")
    destinatarios = [d.strip() for d in destinatarios if d.strip()]

    if not api_key:
        print("[EMAIL] Error: RESEND_API_KEY no configurado")
        return False

    if not destinatarios:
        print("[EMAIL] Error: EMAIL_DESTINATARIOS no configurado")
        return False

    # Preparar adjuntos en formato Resend (base64)
    attachments = []
    for nombre, contenido in adjuntos:
        attachments.append({
            "filename": nombre,
            "content": base64.b64encode(contenido).decode("utf-8"),
        })

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": from_email,
                "to": destinatarios,
                "subject": asunto,
                "text": cuerpo,
                "attachments": attachments,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            print(f"[EMAIL] Enviado a {destinatarios}")
            return True
        else:
            print(f"[EMAIL] Error Resend: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        print(f"[EMAIL] Error enviando email: {e}")
        return False
