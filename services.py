"""Servicios auxiliares: generación de PDF, envío de email, base de datos de pedidos procesados."""

import os
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

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


# --- Envío de emails ---


def enviar_email(
    asunto: str,
    cuerpo: str,
    adjuntos: list[tuple[str, bytes]],
):
    """
    Envía un email con adjuntos a todos los destinatarios.
    adjuntos: lista de (nombre_archivo, bytes_contenido)
    """
    gmail_user = os.getenv("GMAIL_USER")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")
    destinatarios = os.getenv("EMAIL_DESTINATARIOS", "").split(",")
    destinatarios = [d.strip() for d in destinatarios if d.strip()]

    if not gmail_user or not gmail_password:
        print("[EMAIL] Error: GMAIL_USER y GMAIL_APP_PASSWORD no configurados")
        return False

    if not destinatarios:
        print("[EMAIL] Error: EMAIL_DESTINATARIOS no configurado")
        return False

    msg = MIMEMultipart()
    msg["From"] = gmail_user
    msg["To"] = ", ".join(destinatarios)
    msg["Subject"] = asunto

    msg.attach(MIMEText(cuerpo, "plain"))

    for nombre, contenido in adjuntos:
        part = MIMEApplication(contenido, Name=nombre)
        part["Content-Disposition"] = f'attachment; filename="{nombre}"'
        msg.attach(part)

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=30)
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, destinatarios, msg.as_string())
        server.quit()
        print(f"[EMAIL] Enviado a {destinatarios}")
        return True
    except Exception as e:
        print(f"[EMAIL] Error enviando email: {e}")
        return False
