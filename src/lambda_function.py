import json
import base64
import logging
import os
from gmail_client import get_new_messages, get_recent_messages, mover_a_no_urgentes
from clasificador import clasificar_email, responder_pregunta
from dynamodb_client import (
    guardar_email, actualizar_accion, resumen_ultimas_24h,
    get_last_history_id, save_history_id, get_todos_emails
)
from telegram_bot import send_message, enviar_resumen_diario, enviar_notificacion_urgente

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Chat ID de Marta en Telegram (se configura como env var)
MARTA_CHAT_ID = int(os.environ.get("GASTON_MARTA_CHAT_ID", "0"))


def lambda_handler(event, context):
    """
    Handler principal de Gaston. Soporta 4 tipos de invocacion:

    1. Pub/Sub webhook — email nuevo llega a Gmail
    2. EventBridge cron — clasificacion por lotes cada 10 min / resumen diario 8 AM
    3. Telegram webhook — Marta hace una pregunta
    4. API Gateway GET — dashboard Streamlit pide datos
    """
    logger.info("=== Gaston Lambda iniciada ===")
    logger.info(f"Event keys: {list(event.keys())}")
    if "body" in event:
        logger.info(f"Body preview: {str(event.get('body', ''))[:200]}")

    try:
        # Orden importa: Telegram antes de API porque ambos vienen por API Gateway
        if _is_cron(event):
            return _handle_cron(event)
        elif _is_telegram(event):
            return _handle_telegram(event)
        elif _is_pubsub(event):
            return _handle_pubsub(event)
        elif _is_api(event):
            return _handle_api(event)
        else:
            logger.warning(f"Evento no reconocido: {json.dumps(event)[:300]}")
            return _ok({"message": "Evento no reconocido"})

    except Exception as e:
        logger.error(f"Error en lambda_handler: {e}", exc_info=True)
        return _ok({"error": str(e)})


# ============= PUB/SUB (email nuevo en tiempo real) =============

def _handle_pubsub(event):
    """Procesa notificacion de Pub/Sub cuando llega un email nuevo a Gmail."""
    body = event.get("body", "{}")
    if isinstance(body, str):
        body = json.loads(body)

    pubsub_message = body.get("message", {})
    data_b64 = pubsub_message.get("data", "")

    if not data_b64:
        return _ok({"message": "Sin datos en Pub/Sub"})

    data_decoded = json.loads(base64.b64decode(data_b64).decode("utf-8"))
    history_id = str(data_decoded.get("historyId", ""))

    if not history_id:
        return _ok({"message": "Sin historyId"})

    emails = get_new_messages(history_id)
    procesados = _procesar_emails(emails)
    save_history_id(history_id)

    return _ok({"procesados": procesados, "total": len(emails)})


# ============= CRON =============

def _handle_cron(event):
    """
    Dos crons:
    - Cada 10 min: clasificar emails nuevos de Redmine
    - 8 AM: enviar resumen diario a Telegram
    """
    # Detectar si es el resumen diario
    input_data = event.get("detail", {}) if isinstance(event.get("detail"), dict) else {}
    action = ""
    # El input viene como string en el event de EventBridge
    if isinstance(event.get("body"), str):
        try:
            input_data = json.loads(event["body"])
        except Exception:
            pass
    # Tambien puede venir directo del Input del schedule
    if "action" in event:
        action = event["action"]
    elif "action" in input_data:
        action = input_data["action"]

    if action == "resumen_diario":
        return _handle_resumen_diario()

    # Cron diario: clasificar emails no leidos + enviar resumen
    logger.info("Cron diario: clasificando emails de Redmine + resumen")

    # Paso 1: Clasificar emails no leidos
    emails = get_recent_messages(
        max_results=50,
        query="from:@mgpsa.com subject:(#) is:unread after:2026/03/30"
    )
    procesados = _procesar_emails(emails)

    # Paso 2: Enviar resumen a Marta
    _handle_resumen_diario()

    return _ok({"procesados": procesados, "total": len(emails), "trigger": "cron_diario"})


def _handle_resumen_diario():
    """Envia el resumen de las ultimas 24h a Marta via Telegram."""
    logger.info("Cron: enviando resumen diario a Telegram")

    if not MARTA_CHAT_ID:
        logger.error("GASTON_MARTA_CHAT_ID no configurado")
        return _ok({"error": "Chat ID no configurado"})

    emails = resumen_ultimas_24h()
    enviar_resumen_diario(MARTA_CHAT_ID, emails)
    return _ok({"resumen_enviado": True, "emails_24h": len(emails)})


# ============= LOGICA DE PROCESAMIENTO =============

def _procesar_emails(emails: list[dict]) -> int:
    """
    Para cada email:
    1. Clasifica con Bedrock (+ contexto de Redmine si hay numero de incidencia)
    2. Guarda en DynamoDB
    3. Ejecuta accion: archivar, crear draft, o notificar
    """
    procesados = 0

    # Obtener IDs ya procesados para evitar duplicados y gastos innecesarios en Bedrock
    from dynamodb_client import email_ya_procesado

    for email_data in emails:
        # Saltar si ya fue procesado
        if email_ya_procesado(email_data["email_id"]):
            logger.info(f"Saltando (ya procesado): [{email_data['email_id']}] {email_data['asunto'][:40]}")
            continue

        logger.info(f"Procesando: [{email_data['email_id']}] {email_data['asunto'][:60]}")

        # 1. Clasificar con Bedrock
        clasificacion = clasificar_email(email_data)
        tipo = clasificacion.get("clasificacion", "DUDOSO")
        numero_inc = clasificacion.get("numero_incidencia", "N/A")

        logger.info(f"  -> {tipo} | #{numero_inc} | {clasificacion.get('resumen', '')[:80]}")

        # 2. Guardar en DynamoDB
        ok = guardar_email(email_data, clasificacion)
        if not ok:
            continue

        # 4. Ejecutar accion segun clasificacion
        #
        # Solo actua sobre emails de Redmine (tienen #XXXXX en el asunto)
        # INFORMATIVO de Redmine → mover a "Redmine No Urgentes" SIN marcar como leido
        # Todo lo demas → no tocar Gmail, solo registrar en DynamoDB + dashboard

        import re
        es_redmine = bool(re.search(r"#\d{3,}", email_data.get("asunto", "")))

        if tipo == "INFORMATIVO" and es_redmine:
            mover_a_no_urgentes(email_data["email_id"])
            logger.info(f"  -> Redmine informativo: movido a carpeta (sin leer)")
        else:
            # No tocar Gmail: queda en inbox sin leer, sin drafts, sin cambios
            logger.info(f"  -> {tipo}: registrado en dashboard, Gmail intacto")

        procesados += 1

    logger.info(f"=== Procesados {procesados}/{len(emails)} emails ===")
    return procesados


# ============= TELEGRAM (preguntas de Marta) =============

def _handle_telegram(event):
    """
    Marta escribe en Telegram, Gaston responde con contexto de
    DynamoDB (emails clasificados).
    """
    body = json.loads(event.get("body", "{}"))
    message = body.get("message", {})
    text = message.get("text", "")
    chat_id = message.get("chat", {}).get("id")

    if not text or not chat_id:
        return _ok()

    # Comando /start
    if text.strip() == "/start":
        send_message(chat_id,
            "Hola! Soy *Gaston*, tu asistente de incidencias.\n\n"
            "Comandos:\n"
            "/actualizar - Procesa emails nuevos ahora\n"
            "/resumen - Resumen de las ultimas 24h\n\n"
            "O preguntame lo que quieras:\n"
            "- Que incidencias urgentes hay?\n"
            "- Que dice la #63475?\n"
            "- Cuantas incidencias tiene SHEREKHAN?\n\n"
            "_Escribeme lo que necesites._"
        )
        return _ok()

    # Comando /actualizar - procesa emails en el momento
    if text.strip() == "/actualizar":
        send_message(chat_id, "Procesando emails nuevos... dame un momento.")
        emails = get_recent_messages(
            max_results=50,
            query="from:@mgpsa.com subject:(#) is:unread after:2026/03/30"
        )
        if not emails:
            send_message(chat_id, "No hay emails nuevos de Redmine sin leer.")
            return _ok()

        procesados = _procesar_emails(emails)
        send_message(chat_id,
            f"Listo! Procesados *{procesados}* emails nuevos de {len(emails)} encontrados.\n"
            f"Revisa tu Gmail y el dashboard para ver los detalles."
        )
        return _ok()

    # Comando /resumen - resumen de las ultimas 24h
    if text.strip() == "/resumen":
        emails_24h = resumen_ultimas_24h()
        enviar_resumen_diario(chat_id, emails_24h)
        return _ok()

    # Pregunta libre - Gaston responde con contexto de DynamoDB
    emails_recientes = resumen_ultimas_24h()
    contexto_emails = "\n".join([
        f"- [{e.get('clasificacion')}] #{e.get('numero_incidencia', 'N/A')} "
        f"({e.get('proyecto', 'N/A')}): {e.get('resumen', '')}"
        for e in emails_recientes[:20]
    ])

    respuesta = responder_pregunta(text, contexto_emails)
    send_message(chat_id, respuesta)

    return _ok()


# ============= API (dashboard Streamlit) =============

def _handle_api(event):
    """Endpoints para el dashboard."""
    path = event.get("path", "")
    method = event.get("httpMethod", "GET")

    if path == "/gaston/emails" and method == "GET":
        emails = get_todos_emails()
        return _ok(emails)

    elif path == "/gaston/resumen" and method == "GET":
        emails = resumen_ultimas_24h()
        return _ok(emails)

    return _ok({"message": "Ruta no encontrada"})


# ============= DETECCION DE TIPO DE EVENTO =============

def _is_pubsub(event):
    body = event.get("body", "")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except Exception:
            return False
    return isinstance(body, dict) and "message" in body and "data" in body.get("message", {})


def _is_cron(event):
    return (
        event.get("source") == "aws.events"
        or event.get("detail-type") == "Scheduled Event"
        or event.get("action") == "resumen_diario"
    )


def _is_telegram(event):
    body = event.get("body", "")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except Exception:
            return False
    return isinstance(body, dict) and "message" in body and "chat" in body.get("message", {})


def _is_api(event):
    return "path" in event and event.get("path", "").startswith("/gaston/")


def _ok(data=None):
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(data or {"status": "ok"}, default=str)
    }
