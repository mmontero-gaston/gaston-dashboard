"""
Gaston Telegram Bot - Funciones de notificacion y resumen diario.

Este modulo se invoca desde lambda_function.py.
El bot de Telegram se configura con un webhook apuntando a API Gateway.

Setup:
1. Habla con @BotFather en Telegram
2. Crea un bot: /newbot -> "Gaston" -> "gaston_incidencias_bot"
3. Copia el token
4. Configura el webhook:
   curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
     -H "Content-Type: application/json" \
     -d '{"url": "https://<API_GATEWAY_URL>/gaston/telegram"}'
5. Escribe /start al bot para obtener tu chat_id
"""

import json
import logging
import os
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)


def get_bot_token() -> str:
    return os.environ.get("GASTON_TELEGRAM_TOKEN", "")


def send_message(chat_id: int, text: str, parse_mode: str = "Markdown") -> bool:
    """Envia un mensaje a un chat de Telegram."""
    bot_token = get_bot_token()
    if not bot_token:
        logger.error("GASTON_TELEGRAM_TOKEN no configurado")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    # Telegram tiene limite de 4096 caracteres por mensaje
    if len(text) > 4000:
        text = text[:4000] + "\n\n... (truncado)"

    data = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req)
        return True
    except Exception as e:
        logger.error(f"Error enviando mensaje a Telegram: {e}")
        return False


def enviar_resumen_diario(chat_id: int, emails: list[dict]) -> bool:
    """
    Envia el resumen de las ultimas 24h a Telegram.
    Se invoca via EventBridge cron a las 8 AM.
    """
    if not emails:
        text = (
            "*Buenos dias Marta* \n\n"
            "No hay emails nuevos de Redmine en las ultimas 24 horas.\n"
            "Dia tranquilo!"
        )
        return send_message(chat_id, text)

    # Contar por clasificacion
    conteos = {}
    for e in emails:
        tipo = e.get("clasificacion", "DUDOSO")
        conteos[tipo] = conteos.get(tipo, 0) + 1

    archivados = conteos.get("INFORMATIVO", 0)
    urgentes = conteos.get("URGENTE", 0)
    para_marta = conteos.get("PARA_MARTA", 0)
    dudosos = conteos.get("DUDOSO", 0)

    # Contar drafts creados
    drafts = [e for e in emails if e.get("accion_realizada") == "DRAFT_CREADO"]

    # Construir mensaje
    lines = [
        "*Buenos dias Marta.* Resumen de las ultimas 24h:\n",
        f"- {len(emails)} emails nuevos de Redmine",
        f"- {archivados} archivados (informativos)",
    ]

    if drafts:
        lines.append(f"- {len(drafts)} drafts preparados")
    if urgentes:
        lines.append(f"- {urgentes} urgentes")
    if para_marta:
        lines.append(f"- {para_marta} dirigidos a ti")
    if dudosos:
        lines.append(f"- {dudosos} necesitan tu criterio")

    # Listar urgentes y para_marta
    importantes = [
        e for e in emails
        if e.get("clasificacion") in ("URGENTE", "PARA_MARTA")
    ]

    if importantes:
        lines.append("\n*Requieren tu atencion:*")
        for e in importantes[:10]:
            emoji = "🚨" if e.get("clasificacion") == "URGENTE" else "📝"
            incidencia = e.get("numero_incidencia", "N/A")
            proyecto = e.get("proyecto", "")
            resumen = e.get("resumen", "Sin resumen")
            draft_flag = " (draft listo)" if e.get("accion_realizada") == "DRAFT_CREADO" else ""
            lines.append(f"{emoji} {incidencia} ({proyecto}): {resumen}{draft_flag}")

    # Listar dudosos
    dudosos_list = [e for e in emails if e.get("clasificacion") == "DUDOSO"]
    if dudosos_list:
        lines.append("\n*Necesito tu criterio:*")
        for e in dudosos_list[:5]:
            incidencia = e.get("numero_incidencia", "N/A")
            resumen = e.get("resumen", "Sin resumen")
            lines.append(f"❓ {incidencia}: {resumen}")

    # Proyectos afectados
    proyectos = set(e.get("proyecto", "N/A") for e in emails if e.get("proyecto") != "N/A")
    if proyectos:
        lines.append(f"\n*Proyectos activos:* {', '.join(sorted(proyectos))}")

    lines.append("\n_Escribe cualquier pregunta y te respondo._")

    text = "\n".join(lines)
    return send_message(chat_id, text)


def enviar_notificacion_urgente(chat_id: int, email_data: dict, clasificacion: dict) -> bool:
    """
    Envia una notificacion inmediata cuando llega algo urgente.
    No espera al resumen diario.
    """
    incidencia = clasificacion.get("numero_incidencia", "N/A")
    proyecto = clasificacion.get("proyecto", "")
    resumen = clasificacion.get("resumen", "")
    remitente = email_data.get("remitente", "")

    text = (
        f"🚨 *Incidencia urgente*\n\n"
        f"*{incidencia}* ({proyecto})\n"
        f"{resumen}\n\n"
        f"De: {remitente[:50]}\n"
        f"Asunto: {email_data.get('asunto', '')[:80]}\n\n"
    )

    if clasificacion.get("requiere_respuesta"):
        text += "_Draft preparado en tu Gmail._"
    else:
        text += "_Revisa tu Gmail para mas detalle._"

    return send_message(chat_id, text)
