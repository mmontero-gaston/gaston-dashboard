"""
GASTON - Carga de produccion.
1. Limpia DynamoDB
2. Lee emails de Redmine de los ultimos 2 dias
3. Clasifica con Bedrock
4. Guarda en DynamoDB
5. Mueve INFORMATIVOS de Redmine a carpeta "Redmine No Urgentes"
6. Crea drafts como REPLY para URGENTES/PARA_MARTA
"""

import json
import sys
import os
import re
import base64
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import boto3

MODEL_ID = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
REGION = "eu-west-1"
TABLE_NAME = "gaston_emails"
LABEL_NAME = "Redmine No Urgentes"
EMPTY_INDEX_VALUES = ("", "#", "N/A", "No identificado", "No identificada", "No especificado",
                      "no identificado", "no especificado", "No aplica", "no_identificado")


def get_gmail_service():
    token_path = os.path.join(os.path.dirname(__file__), "setup", "token.json")
    creds = Credentials.from_authorized_user_file(token_path)
    if creds.expired:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


def get_or_create_label(service):
    results = service.users().labels().list(userId="me").execute()
    for label in results.get("labels", []):
        if label["name"] == LABEL_NAME:
            return label["id"]
    created = service.users().labels().create(userId="me", body={
        "name": LABEL_NAME, "labelListVisibility": "labelShow", "messageListVisibility": "show",
    }).execute()
    return created["id"]


def clean_index_val(val):
    if not val or val.strip() in EMPTY_INDEX_VALUES:
        return "N/A"
    return val.strip()


def limpiar_dynamo():
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table = dynamodb.Table(TABLE_NAME)
    response = table.scan()
    items = response.get("Items", [])
    for item in items:
        table.delete_item(Key={"email_id": item["email_id"], "timestamp": item["timestamp"]})
    return len(items)


def leer_emails(service, max_results=100):
    response = service.users().messages().list(
        userId="me", maxResults=max_results,
        q="from:@mgpsa.com subject:(#) newer_than:2d"
    ).execute()

    emails = []
    for msg_ref in response.get("messages", []):
        msg = service.users().messages().get(
            userId="me", id=msg_ref["id"], format="full"
        ).execute()

        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}

        cuerpo = ""
        payload = msg["payload"]
        if "body" in payload and payload["body"].get("data"):
            cuerpo = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")
        else:
            for part in payload.get("parts", []):
                if part.get("mimeType") == "text/plain" and part["body"].get("data"):
                    cuerpo = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")
                    break

        fecha_str = headers.get("date", "")
        fecha_iso = ""
        try:
            fecha_dt = parsedate_to_datetime(fecha_str)
            fecha_iso = fecha_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            fecha_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        emails.append({
            "email_id": msg_ref["id"],
            "thread_id": msg.get("threadId", ""),
            "message_id": headers.get("message-id", ""),
            "remitente": headers.get("from", ""),
            "destinatario": headers.get("to", ""),
            "cc": headers.get("cc", ""),
            "asunto": headers.get("subject", ""),
            "cuerpo": cuerpo,
            "fecha": fecha_str,
            "fecha_iso": fecha_iso,
        })
    return emails


def clasificar(email_data):
    bedrock = boto3.client("bedrock-runtime", region_name=REGION)
    system_prompt = """Eres Gaston. Clasifica emails de incidencias de Redmine para Marta (mmontero@mgpsa.com).

INFORMATIVO: no requiere accion (notificaciones automaticas, CC, cerradas, descartadas, cambios de estado sin preguntas)
URGENTE: atencion inmediata (prioridad alta, bloqueantes, piden respuesta urgente)
PARA_MARTA: dirigido a ella explicitamente o necesita su decision
MEDIO: relevante pero no requiere respuesta directa
DUDOSO: no encaja

Del asunto extrae: numero de incidencia, proyecto, estado.
Responde SOLO JSON."""

    user_prompt = f"""Clasifica:
{{"clasificacion":"...","numero_incidencia":"...","proyecto":"...","estado_redmine":"...","prioridad_redmine":"...","asignado_a":"...","resumen":"...","requiere_respuesta":false}}

De: {email_data['remitente']}
Para: {email_data['destinatario']}
CC: {email_data.get('cc', '')}
Asunto: {email_data['asunto']}
Cuerpo: {email_data['cuerpo'][:2000]}"""

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 400,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}]
    })
    response = bedrock.invoke_model(modelId=MODEL_ID, body=body,
        contentType="application/json", accept="application/json")
    result = json.loads(response["body"].read())
    text = result["content"][0]["text"].strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def generar_draft_texto(email_data):
    bedrock = boto3.client("bedrock-runtime", region_name=REGION)
    prompt = f"""Redacta un borrador de respuesta profesional y conciso en espanol.
Es para Marta, directora de desarrollo de negocio. Firma como "Marta".

De: {email_data['remitente']}
Asunto: {email_data['asunto']}
Cuerpo: {email_data['cuerpo'][:1500]}

Solo el texto del borrador, sin explicaciones."""

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 500,
        "system": "Redactas emails profesionales concisos en espanol.",
        "messages": [{"role": "user", "content": prompt}]
    })
    response = bedrock.invoke_model(modelId=MODEL_ID, body=body,
        contentType="application/json", accept="application/json")
    result = json.loads(response["body"].read())
    return result["content"][0]["text"].strip()


def crear_draft_reply(service, email_data, draft_text):
    """Crea draft como respuesta al email original (dentro del hilo)."""
    destinatario = email_data.get("remitente", "")
    if "<" in destinatario and ">" in destinatario:
        destinatario = destinatario.split("<")[1].split(">")[0]

    asunto = email_data.get("asunto", "")
    if not asunto.startswith("Re:"):
        asunto = f"Re: {asunto}"

    message = MIMEText(draft_text, "plain", "utf-8")
    message["to"] = destinatario
    message["subject"] = asunto

    # Headers para que sea respuesta en el hilo
    msg_id = email_data.get("message_id", "")
    if msg_id:
        message["In-Reply-To"] = msg_id
        message["References"] = msg_id

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    draft_body = {"message": {"raw": raw}}
    thread_id = email_data.get("thread_id", "")
    if thread_id:
        draft_body["message"]["threadId"] = thread_id

    draft = service.users().drafts().create(userId="me", body=draft_body).execute()
    return draft.get("id")


def guardar(email_data, clf, accion=""):
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table = dynamodb.Table(TABLE_NAME)

    timestamp = email_data.get("fecha_iso", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    es_redmine = bool(re.search(r"#\d{3,}", email_data.get("asunto", "")))

    table.put_item(Item={
        "email_id": email_data["email_id"],
        "timestamp": timestamp,
        "fecha_email": email_data.get("fecha", ""),
        "remitente": email_data.get("remitente", ""),
        "destinatario": email_data.get("destinatario", ""),
        "asunto": email_data.get("asunto", ""),
        "clasificacion": clf.get("clasificacion", "DUDOSO"),
        "proyecto": clean_index_val(clf.get("proyecto", "N/A")),
        "numero_incidencia": clean_index_val(clf.get("numero_incidencia", "N/A")),
        "estado_redmine": clf.get("estado_redmine", "N/A"),
        "prioridad_redmine": clf.get("prioridad_redmine", "N/A"),
        "asignado_a": clf.get("asignado_a", "N/A"),
        "resumen": clf.get("resumen", ""),
        "requiere_respuesta": clf.get("requiere_respuesta", False),
        "accion_realizada": accion,
        "es_redmine": es_redmine,
    })


def main():
    print("=" * 60)
    print("GASTON - Produccion")
    print("=" * 60)

    # 1. Limpiar DynamoDB
    print("\n[1/5] Limpiando DynamoDB...")
    borrados = limpiar_dynamo()
    print(f"  Borrados {borrados} registros de prueba")

    # 2. Conectar Gmail
    print("\n[2/5] Conectando a Gmail...")
    service = get_gmail_service()
    label_id = get_or_create_label(service)
    print(f"  Etiqueta '{LABEL_NAME}' lista")

    # 3. Leer emails
    print("\n[3/5] Leyendo emails de Redmine (ultimos 2 dias)...")
    emails = leer_emails(service, max_results=100)
    print(f"  Encontrados: {len(emails)}")

    # 4. Clasificar y actuar
    print(f"\n[4/5] Clasificando y ejecutando acciones...")
    movidos = 0
    drafts = 0
    errores = 0

    for i, email in enumerate(emails, 1):
        asunto_safe = email['asunto'].encode('ascii', 'replace').decode()
        print(f"\n  [{i}/{len(emails)}] {asunto_safe[:60]}")

        try:
            clf = clasificar(email)
            tipo = clf.get("clasificacion", "DUDOSO")
            inc = clean_index_val(clf.get("numero_incidencia", "N/A"))
            es_redmine = bool(re.search(r"#\d{3,}", email.get("asunto", "")))

            tag = {"INFORMATIVO": "INFO", "URGENTE": "URGE", "PARA_MARTA": "MART", "MEDIO": "MEDI", "DUDOSO": "DUDO"}
            print(f"    {tag.get(tipo, '?')} | #{inc} | {clf.get('resumen', '').encode('ascii', 'replace').decode()[:50]}")

            accion = ""

            if tipo == "INFORMATIVO" and es_redmine:
                # Mover a carpeta "Redmine No Urgentes"
                service.users().messages().modify(
                    userId="me", id=email["email_id"],
                    body={"addLabelIds": [label_id], "removeLabelIds": ["INBOX", "UNREAD"]}
                ).execute()
                accion = "MOVIDO_NO_URGENTE"
                movidos += 1
                print(f"    >> Movido a '{LABEL_NAME}'")

            elif tipo in ("URGENTE", "PARA_MARTA"):
                # Marcar como leido
                service.users().messages().modify(
                    userId="me", id=email["email_id"],
                    body={"removeLabelIds": ["UNREAD"]}
                ).execute()

                # Crear draft como reply en el hilo
                try:
                    draft_text = generar_draft_texto(email)
                    draft_id = crear_draft_reply(service, email, draft_text)
                    accion = "DRAFT_REPLY_CREADO"
                    drafts += 1
                    print(f"    >> Draft reply creado: {draft_id}")
                except Exception as e:
                    print(f"    >> Error creando draft: {str(e)[:50]}")
                    accion = "DRAFT_ERROR"

            elif tipo == "MEDIO":
                service.users().messages().modify(
                    userId="me", id=email["email_id"],
                    body={"removeLabelIds": ["UNREAD"]}
                ).execute()
                accion = "MARCADO_LEIDO"
                print(f"    >> Marcado leido, en inbox")

            else:
                accion = "SIN_ACCION"
                print(f"    >> Sin accion")

            guardar(email, clf, accion)

        except Exception as e:
            errores += 1
            print(f"    ERROR: {str(e)[:60]}")

    # 5. Resumen
    print(f"\n{'=' * 60}")
    print(f"[5/5] PRODUCCION COMPLETADA")
    print(f"  Emails procesados: {len(emails)}")
    print(f"  Movidos a '{LABEL_NAME}': {movidos}")
    print(f"  Drafts reply creados: {drafts}")
    print(f"  Errores: {errores}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
