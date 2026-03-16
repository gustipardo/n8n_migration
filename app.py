"""
Servidor principal — reemplaza el workflow de n8n para MercadoLibre.

Funcionalidades:
  1. Webhook de ML: recibe notificaciones cuando hay un pedido nuevo (real-time)
  2. Polling: cada 5 min revisa pedidos pagados (respaldo)
  3. Token refresh: cada 5 horas renueva tokens automáticamente
  4. Auth: ruta /auth/callback para la autorización inicial de ML
"""

import os
import traceback

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, request, jsonify, redirect
from apscheduler.schedulers.background import BackgroundScheduler

import mercadolibre as ml
import services

app = Flask(__name__)


# =============================================
# LÓGICA PRINCIPAL: procesar pedidos
# =============================================


def procesar_pedidos():
    """Revisa pedidos pagados y procesa los que están listos para enviar."""
    print("[PROC] Revisando pedidos pagados...")
    try:
        pedidos = ml.obtener_pedidos_pagados(limit=10)
    except Exception as e:
        print(f"[PROC] Error obteniendo pedidos: {e}")
        return

    procesados = 0
    for pedido in pedidos:
        order_id = pedido.get("id")
        shipping_id = pedido.get("shipping", {}).get("id")

        if not order_id or not shipping_id:
            continue

        if services.ya_procesado(order_id):
            continue

        # Verificar estado del envío
        try:
            envio = ml.obtener_estado_envio(shipping_id)
        except Exception as e:
            print(f"[PROC] Error obteniendo envío {shipping_id}: {e}")
            continue

        status = envio.get("status", "")
        substatus = envio.get("substatus", "")

        if status != "ready_to_ship" or "printed" not in substatus:
            print(f"[PROC] Pedido {order_id}: no listo (status={status}, substatus={substatus})")
            continue

        # --- Pedido listo para enviar ---
        print(f"[PROC] Procesando pedido {order_id}...")

        try:
            # 1. Descargar etiqueta de envío
            etiqueta_pdf = ml.descargar_etiqueta_pdf(shipping_id)

            # 2. Obtener datos de la orden (nombre del comprador)
            orden = ml.obtener_orden(order_id)
            buyer = orden.get("buyer", {})
            nombre = f"{buyer.get('first_name', '')} {buyer.get('last_name', '')}".strip()
            if not nombre:
                nombre = buyer.get("nickname", "Cliente")

            # 3. Generar PDF de agradecimiento
            agradecimiento_pdf = services.generar_pdf_agradecimiento(nombre, order_id)

            # 4. Enviar email con ambos PDFs
            enviado = services.enviar_email(
                asunto=f"Etiqueta pedido #{order_id}",
                cuerpo="Tu etiqueta de envío está lista para imprimir.",
                adjuntos=[
                    (f"etiqueta_{order_id}.pdf", etiqueta_pdf),
                    (f"gracias_{nombre.replace(' ', '_')}.pdf", agradecimiento_pdf),
                ],
            )

            if enviado:
                # 5. Registrar como procesado
                services.marcar_procesado(order_id)
                procesados += 1
                print(f"[PROC] Pedido {order_id} procesado OK ({nombre})")
            else:
                print(f"[PROC] Pedido {order_id}: email no enviado, no se marca como procesado")

        except Exception as e:
            print(f"[PROC] Error procesando pedido {order_id}: {e}")
            traceback.print_exc()

    print(f"[PROC] Revisión completa. {procesados} pedidos nuevos procesados.")


# =============================================
# RUTAS
# =============================================


@app.route("/")
def index():
    return jsonify({
        "status": "running",
        "endpoints": {
            "/auth/login": "Iniciar autorización con MercadoLibre",
            "/auth/callback": "Callback de OAuth (automático)",
            "/webhook/mercadolibre": "Webhook para notificaciones de ML",
            "/procesar": "Forzar revisión de pedidos manualmente",
        },
    })


@app.route("/auth/login")
def auth_login():
    """Redirige al usuario a MercadoLibre para autorizar la app."""
    client_id = os.getenv("ML_CLIENT_ID")
    redirect_uri = os.getenv("ML_REDIRECT_URI")
    url = (
        f"https://auth.mercadolibre.com.ar/authorization"
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
    )
    return redirect(url)


@app.route("/auth/callback")
def auth_callback():
    """Recibe el code de ML y obtiene los tokens."""
    code = request.args.get("code")
    if not code:
        return jsonify({"error": "No se recibió el code"}), 400

    try:
        data = ml.intercambiar_code(code)
        return jsonify({
            "ok": True,
            "mensaje": "Autorización exitosa. Los tokens se guardaron.",
            "access_token": data["access_token"][:20] + "...",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/auth/tokens")
def auth_tokens():
    """Muestra los tokens actuales (para copiarlos a las variables de entorno como backup)."""
    tokens = ml._load_tokens()
    return jsonify({
        "access_token": tokens.get("access_token", ""),
        "refresh_token": tokens.get("refresh_token", ""),
        "mensaje": "Copiá el refresh_token a la variable ML_REFRESH_TOKEN en Render para que sobreviva redeploys.",
    })


@app.route("/webhook/mercadolibre", methods=["POST"])
def webhook_ml():
    """
    Recibe notificaciones de MercadoLibre.
    ML envía un POST cuando hay cambios en pedidos.
    """
    data = request.get_json(silent=True) or {}
    topic = data.get("topic", "")
    resource = data.get("resource", "")

    print(f"[WEBHOOK] Notificación: topic={topic}, resource={resource}")

    if topic == "orders_v2":
        # Hay un cambio en un pedido — ejecutar procesamiento
        procesar_pedidos()

    return "", 200


@app.route("/procesar")
def forzar_procesamiento():
    """Endpoint manual para forzar la revisión de pedidos."""
    procesar_pedidos()
    return jsonify({"ok": True, "mensaje": "Procesamiento ejecutado"})


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# =============================================
# SCHEDULER (tareas periódicas)
# =============================================


def iniciar_scheduler():
    scheduler = BackgroundScheduler()

    # Renovar token cada 5 horas
    scheduler.add_job(
        ml.refrescar_token,
        "interval",
        hours=5,
        id="refresh_token",
        misfire_grace_time=300,
    )

    # Polling de pedidos cada 5 minutos (respaldo del webhook)
    intervalo = int(os.getenv("POLLING_INTERVAL", "300"))
    scheduler.add_job(
        procesar_pedidos,
        "interval",
        seconds=intervalo,
        id="polling_pedidos",
        misfire_grace_time=60,
    )

    scheduler.start()
    print(f"[SCHED] Scheduler iniciado: refresh cada 5h, polling cada {intervalo}s")


# =============================================
# MAIN
# =============================================

# Iniciar scheduler al cargar el módulo (funciona con gunicorn y python app.py)
# No iniciar en modo testing
if not os.getenv("TESTING"):
    iniciar_scheduler()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"[APP] Servidor iniciado en puerto {port}")
    # use_reloader=False para evitar doble scheduler en desarrollo
    app.run(host="0.0.0.0", port=port, use_reloader=False)
