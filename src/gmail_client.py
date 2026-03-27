import base64
import logging
from email.mime.text import MIMEText
from typing import Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from aws_secrets import get_gmail_credentials

logger = logging.getLogger(__name__)


def _build_service():
    """Construye el cliente autenticado de Gmail API."""
    creds_data = get_gmail_credentials()

    creds = Credentials(
        token=None,
        refresh_token=creds_data["refresh_token"],
        client_id=creds_data["client_id"],
        client_secret=creds_data["client_secret"],
        token_uri="https://oauth2.googleapis.com/token"
    )

    creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


# ============= LEER EMAILS =============

def get_new_messages(history_id: str) -> list[dict]:
    """
    Dado un historyId de Pub/Sub, devuelve los mensajes nuevos.
    Cada mensaje incluye: id, remitente, asunto, cuerpo, destinatario, etc.
    """
    service = _build_service()
    messages = []

    try:
        history_response = service.users().history().list(
            userId="me",
            startHistoryId=history_id,
            historyTypes=["messageAdded"]
        ).execute()

        history_records = history_response.get("history", [])
        if not history_records:
            logger.info("No hay mensajes nuevos en este historyId")
            return []

        message_ids = []
        for record in history_records:
            for msg in record.get("messagesAdded", []):
                message_ids.append(msg["message"]["id"])

        for msg_id in message_ids:
            msg_data = _read_message(service, msg_id)
            if msg_data:
                messages.append(msg_data)

    except Exception as e:
        logger.error(f"Error obteniendo mensajes: {e}")
        raise

    return messages


def get_recent_messages(max_results: int = 50, query: str = "") -> list[dict]:
    """
    Lee los ultimos emails de la bandeja. Util para el procesamiento
    inicial por lotes (sin depender de Pub/Sub).
    query: filtro de Gmail (ej: "from:redmine" o "is:unread")
    """
    service = _build_service()
    messages = []

    try:
        params = {"userId": "me", "maxResults": max_results}
        if query:
            params["q"] = query

        response = service.users().messages().list(**params).execute()
        message_ids = response.get("messages", [])

        for msg_ref in message_ids:
            msg_data = _read_message(service, msg_ref["id"])
            if msg_data:
                messages.append(msg_data)

    except Exception as e:
        logger.error(f"Error obteniendo mensajes recientes: {e}")
        raise

    return messages


def _read_message(service, msg_id: str) -> Optional[dict]:
    """Lee un mensaje completo."""
    try:
        msg = service.users().messages().get(
            userId="me",
            id=msg_id,
            format="full"
        ).execute()

        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        remitente = headers.get("from", "Desconocido")
        asunto = headers.get("subject", "Sin asunto")
        destinatario = headers.get("to", "")
        cc = headers.get("cc", "")
        fecha = headers.get("date", "")

        cuerpo = _extract_body(msg["payload"])
        labels = msg.get("labelIds", [])

        return {
            "email_id": msg_id,
            "thread_id": msg.get("threadId", ""),
            "message_id": headers.get("message-id", ""),
            "remitente": remitente,
            "asunto": asunto,
            "destinatario": destinatario,
            "cc": cc,
            "fecha": fecha,
            "cuerpo": cuerpo,
            "labels": labels,
            "is_unread": "UNREAD" in labels,
        }

    except Exception as e:
        logger.error(f"Error leyendo mensaje {msg_id}: {e}")
        return None


def _extract_body(payload: dict) -> str:
    """Extrae el texto plano del cuerpo del email."""
    if "body" in payload and payload["body"].get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")

    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part["body"].get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")

        if part.get("mimeType", "").startswith("multipart"):
            result = _extract_body(part)
            if result:
                return result

    return ""


# ============= ETIQUETA "REDMINE NO URGENTES" =============

LABEL_NO_URGENTES = "Redmine No Urgentes"
_label_id_cache = None


def _get_or_create_label(label_name: str = LABEL_NO_URGENTES) -> Optional[str]:
    """
    Obtiene el ID de la etiqueta. Si no existe, la crea una sola vez.
    Marta vera esta carpeta en su Gmail con los emails no urgentes
    para revisarlos y borrarlos en bloque cuando quiera.
    """
    global _label_id_cache
    if _label_id_cache:
        return _label_id_cache

    service = _build_service()
    try:
        # Buscar si ya existe
        results = service.users().labels().list(userId="me").execute()
        for label in results.get("labels", []):
            if label["name"] == label_name:
                _label_id_cache = label["id"]
                return _label_id_cache

        # No existe, crearla
        label_body = {
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        }
        created = service.users().labels().create(userId="me", body=label_body).execute()
        _label_id_cache = created["id"]
        logger.info(f"Etiqueta creada: '{label_name}' (ID: {_label_id_cache})")
        return _label_id_cache

    except Exception as e:
        logger.error(f"Error con etiqueta '{label_name}': {e}")
        return None


# ============= MOVER A NO URGENTES =============

def mover_a_no_urgentes(email_id: str) -> bool:
    """
    Mueve un email a la carpeta 'Redmine No Urgentes'.
    Lo quita del INBOX y lo marca como leido.
    Marta puede entrar a esa carpeta, revisar y borrar en bloque.
    """
    label_id = _get_or_create_label()
    if not label_id:
        return False

    service = _build_service()
    try:
        service.users().messages().modify(
            userId="me",
            id=email_id,
            body={
                "addLabelIds": [label_id],
                "removeLabelIds": ["INBOX", "UNREAD"]
            }
        ).execute()
        logger.info(f"Movido a '{LABEL_NO_URGENTES}': {email_id}")
        return True
    except Exception as e:
        logger.error(f"Error moviendo email {email_id}: {e}")
        return False


def marcar_como_leido(email_id: str) -> bool:
    """Marca un email como leido."""
    service = _build_service()
    try:
        service.users().messages().modify(
            userId="me",
            id=email_id,
            body={"removeLabelIds": ["UNREAD"]}
        ).execute()
        logger.info(f"Marcado como leido email {email_id}")
        return True
    except Exception as e:
        logger.error(f"Error marcando como leido {email_id}: {e}")
        return False


# ============= CREAR DRAFTS =============

def crear_draft(destinatario: str, asunto: str, cuerpo: str,
                reply_to_id: Optional[str] = None,
                thread_id: Optional[str] = None) -> Optional[str]:
    """
    Crea un borrador en el Gmail de Marta.
    Si reply_to_id y thread_id se proporcionan, el draft es una respuesta
    al email original (aparece en el mismo hilo).
    Retorna el ID del draft o None si falla.
    """
    service = _build_service()

    try:
        # Limpiar destinatario: si viene como "Nombre <email>", extraer solo el email
        clean_dest = destinatario
        if "<" in destinatario and ">" in destinatario:
            clean_dest = destinatario.split("<")[1].split(">")[0]

        message = MIMEText(cuerpo, "plain", "utf-8")
        message["to"] = clean_dest
        message["subject"] = asunto

        if reply_to_id:
            message["In-Reply-To"] = reply_to_id
            message["References"] = reply_to_id

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        draft_body = {"message": {"raw": raw}}
        if thread_id:
            draft_body["message"]["threadId"] = thread_id

        draft = service.users().drafts().create(
            userId="me",
            body=draft_body
        ).execute()

        draft_id = draft.get("id")
        logger.info(f"Draft creado: {draft_id} | Asunto: {asunto[:60]}")
        return draft_id

    except Exception as e:
        logger.error(f"Error creando draft: {e}")
        return None
