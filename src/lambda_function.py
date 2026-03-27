import json
import base64
import logging
import os
from gmail_client import get_new_messages, get_recent_messages, mover_a_no_urgentes, crear_draft, marcar_como_leido
from clasificador import clasificar_email, generar_draft, responder_pregunta
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

    # Cron normal: clasificar emails
    logger.info("Cron: clasificando emails de Redmine")
    emails = get_recent_messages(
        max_results=30,
        query="from:@mgpsa.com subject:(#) is:unread"
    )
    procesados = _procesar_emails(emails)
    return _ok({"procesados": procesados, "total": len(emails), "trigger": "cron"})


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

    for email_data in emails:
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
        # URGENTE / PARA_MARTA → queda en inbox + draft preparado + notifica Telegram
        # MEDIO                → queda en inbox, sin draft, Marta decide
        # INFORMATIVO          → mover a carpeta "Redmine No Urgentes" (Marta borra en bloque)
        # DUDOSO               → queda en inbox, no se toca

        # Detectar si es de Redmine (tiene #XXXXX en el asunto)
        import re
        es_redmine = bool(re.search(r"#\d{3,}", email_data.get("asunto", "")))

        if tipo == "INFORMATIVO":
            if es_redmine:
                # Solo mover a carpeta "Redmine No Urgentes" si es de Redmine
                mover_a_no_urgentes(email_data["email_id"])
                logger.info(f"  -> Movido a 'Redmine No Urgentes'")
            else:
                # No es de Redmine, no tocar
                marcar_como_leido(email_data["email_id"])
                logger.info(f"  -> Informativo no-Redmine, marcado leido")

        elif tipo in ("URGENTE", "PARA_MARTA"):
            # Queda en inbox, marcar como leido
            marcar_como_leido(email_data["email_id"])

            # Generar draft como RESPUESTA al email original (aparece en el hilo)
            draft_text = generar_draft(email_data)
            if draft_text:
                asunto_original = email_data.get("asunto", "")
                asunto_reply = asunto_original if asunto_original.startswith("Re:") else f"Re: {asunto_original}"
                draft_id = crear_draft(
                    destinatario=email_data.get("remitente", ""),
                    asunto=asunto_reply,
                    cuerpo=draft_text,
                    reply_to_id=email_data.get("message_id", ""),
                    thread_id=email_data.get("thread_id", ""),
                )
                if draft_id:
                    logger.info(f"  -> Draft creado en hilo (NO enviado): {draft_id}")

            # Notificar urgentes a Telegram inmediatamente
            if tipo == "URGENTE" and MARTA_CHAT_ID:
                enviar_notificacion_urgente(MARTA_CHAT_ID, email_data, clasificacion)

        elif tipo == "MEDIO":
            # Queda en inbox, marcar como leido, sin draft
            marcar_como_leido(email_data["email_id"])
            logger.info(f"  -> Medio, queda en inbox sin draft")

        elif tipo == "DUDOSO":
            # Queda en inbox, no se toca
            logger.info(f"  -> Dudoso, sin accion automatica")

        procesados += 1

    logger.info(f"=== Procesados {procesados}/{len(emails)} emails ===")
    return procesados


# ============= TELEGRAM (preguntas de Marta) =============

def _handle_telegram(event):
    """
    Marta escribe en Telegram, Gaston responde con contexto de
    DynamoDB (emails clasificados) + Redmine (detalle de incidencias).
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
            "Puedes preguntarme cosas como:\n"
            "- Que incidencias urgentes hay?\n"
            "- Resumen de hoy\n"
            "- Que dice la #63475?\n"
            "- Cuantas incidencias tiene SHEREKHAN?\n"
            "- Que tengo pendiente?\n\n"
            "_Escribeme lo que necesites._"
        )
        return _ok()

    # Contexto de emails recientes de DynamoDB
    emails_recientes = resumen_ultimas_24h()
    contexto_emails = "\n".join([
        f"- [{e.get('clasificacion')}] #{e.get('numero_incidencia', 'N/A')} "
        f"({e.get('proyecto', 'N/A')}): {e.get('resumen', '')}"
        for e in emails_recientes[:20]
    ])

    # Generar respuesta con todo el contexto
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
