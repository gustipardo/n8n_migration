"""
Tests locales — probá cada parte del sistema sin necesitar MercadoLibre real.

Uso:
  python test_local.py              → corre todos los tests
  python test_local.py pdf          → solo prueba generación de PDF
  python test_local.py email        → solo prueba envío de email (necesita .env)
  python test_local.py server       → levanta el servidor y prueba los endpoints
  python test_local.py ml           → prueba conexión con MercadoLibre (necesita tokens)
"""

import sys
import os
import json

# Cargar .env si existe
from dotenv import load_dotenv

load_dotenv()


def test_pdf():
    """Genera un PDF de prueba y lo guarda en disco para que lo veas."""
    print("\n=== TEST: Generación de PDF ===")
    from services import generar_pdf_agradecimiento

    pdf_bytes = generar_pdf_agradecimiento("Juan Pérez", 123456789)

    archivo = "test_agradecimiento.pdf"
    with open(archivo, "wb") as f:
        f.write(pdf_bytes)

    size_kb = len(pdf_bytes) / 1024
    print(f"  ✓ PDF generado: {archivo} ({size_kb:.1f} KB)")
    print(f"  → Abrilo para verificar que se ve bien")
    return True


def test_email():
    """Envía un email de prueba (necesita GMAIL_USER y GMAIL_APP_PASSWORD en .env)."""
    print("\n=== TEST: Envío de email ===")
    from services import enviar_email, generar_pdf_agradecimiento

    gmail_user = os.getenv("GMAIL_USER")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD")

    if not gmail_user or not gmail_pass:
        print("  ✗ Falta GMAIL_USER y/o GMAIL_APP_PASSWORD en .env")
        print("  → Creá una contraseña de app en: https://myaccount.google.com/apppasswords")
        return False

    # Generar un PDF de prueba para adjuntar
    pdf = generar_pdf_agradecimiento("Test Local", 0)

    ok = enviar_email(
        asunto="[TEST] Etiqueta pedido - prueba local",
        cuerpo="Este es un email de prueba del sistema migrado de n8n.",
        adjuntos=[("test_agradecimiento.pdf", pdf)],
    )

    if ok:
        print(f"  ✓ Email enviado a {os.getenv('EMAIL_DESTINATARIOS')}")
    else:
        print("  ✗ Error enviando email. Revisá las credenciales.")
    return ok


def test_server():
    """Levanta el servidor Flask y prueba los endpoints."""
    print("\n=== TEST: Endpoints del servidor ===")

    # Importar sin iniciar el scheduler para el test
    os.environ["TESTING"] = "1"
    from app import app

    client = app.test_client()

    # Test GET /
    resp = client.get("/")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["status"] == "running"
    print(f"  ✓ GET /              → status={data['status']}")

    # Test GET /health
    resp = client.get("/health")
    data = resp.get_json()
    assert resp.status_code == 200
    print(f"  ✓ GET /health        → {data}")

    # Test POST /webhook/mercadolibre (simular notificación de ML)
    resp = client.post(
        "/webhook/mercadolibre",
        json={
            "topic": "orders_v2",
            "resource": "/orders/999999999",
            "user_id": 2442769421,
            "application_id": 1681042456336215,
        },
    )
    assert resp.status_code == 200
    print(f"  ✓ POST /webhook/ml   → {resp.status_code} (notificación recibida)")

    # Test GET /auth/login (debería redirigir a ML)
    resp = client.get("/auth/login")
    assert resp.status_code == 302
    print(f"  ✓ GET /auth/login    → redirect a MercadoLibre")

    print("\n  Todos los endpoints funcionan correctamente.")
    return True


def test_db():
    """Prueba el registro de pedidos procesados."""
    print("\n=== TEST: Base de datos de pedidos procesados ===")
    from services import ya_procesado, marcar_procesado

    test_id = "TEST_99999"

    # Verificar que no está procesado
    assert not ya_procesado(test_id)
    print(f"  ✓ Pedido {test_id} no está procesado (correcto)")

    # Marcar como procesado
    marcar_procesado(test_id)
    assert ya_procesado(test_id)
    print(f"  ✓ Pedido {test_id} marcado como procesado")

    # Limpiar
    db_file = "pedidos_procesados.json"
    if os.path.exists(db_file):
        with open(db_file) as f:
            data = json.load(f)
        data.remove(test_id)
        with open(db_file, "w") as f:
            json.dump(data, f)
    print(f"  ✓ Limpieza OK")
    return True


def test_ml():
    """Prueba la conexión real con MercadoLibre (necesita tokens válidos)."""
    print("\n=== TEST: Conexión con MercadoLibre ===")
    import mercadolibre as ml

    token = ml.get_access_token()
    if not token:
        print("  ✗ No hay access_token. Primero autorizá la app:")
        print("    1. Levantá el server: python app.py")
        print("    2. Andá a http://localhost:5000/auth/login")
        return False

    print(f"  Token: {token[:20]}...")

    try:
        pedidos = ml.obtener_pedidos_pagados(limit=3)
        print(f"  ✓ Pedidos pagados obtenidos: {len(pedidos)}")
        for p in pedidos:
            order_id = p.get("id")
            status = p.get("status")
            shipping_id = p.get("shipping", {}).get("id")
            print(f"    → Pedido #{order_id} | status={status} | shipping={shipping_id}")
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        if "401" in str(e):
            print("  → Token expirado. Intentando renovar...")
            try:
                ml.refrescar_token()
                print("  ✓ Token renovado. Volvé a correr el test.")
            except Exception as e2:
                print(f"  ✗ No se pudo renovar: {e2}")
                print("  → Autorizá la app de nuevo: python app.py → /auth/login")
        return False


# =============================================

if __name__ == "__main__":
    tests = {
        "pdf": test_pdf,
        "email": test_email,
        "server": test_server,
        "db": test_db,
        "ml": test_ml,
    }

    if len(sys.argv) > 1:
        nombre = sys.argv[1]
        if nombre in tests:
            tests[nombre]()
        else:
            print(f"Test desconocido: {nombre}")
            print(f"Tests disponibles: {', '.join(tests.keys())}")
    else:
        print("=" * 50)
        print("  TESTS LOCALES — Sistema ML")
        print("=" * 50)

        # Correr tests que no necesitan credenciales externas
        test_pdf()
        test_db()
        test_server()

        print("\n" + "=" * 50)
        print("  Tests que necesitan configuración:")
        print("    python test_local.py email   (necesita Gmail)")
        print("    python test_local.py ml      (necesita tokens ML)")
        print("=" * 50)
