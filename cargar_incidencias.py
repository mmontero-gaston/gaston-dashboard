"""
Carga incidencias reales de Redmine de los ultimos 2 dias.
Clasifica y guarda en DynamoDB con fecha del email original.
"""

import json
import sys
import os
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


def get_gmail_service():
    token_path = os.path.join(os.path.dirname(__file__), "setup", "token.json")
    creds = Credentials.from_authorized_user_file(token_path)
    if creds.expired:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


def leer_incidencias(service, max_results=50):
    """Lee emails de incidencias de Redmine de los ultimos 2 dias."""
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

        # Parsear fecha del email
        fecha_str = headers.get("date", "")
        fecha_iso = ""
        try:
            fecha_dt = parsedate_to_datetime(fecha_str)
            fecha_iso = fecha_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            fecha_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        emails.append({
            "email_id": msg_ref["id"],
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

INFORMATIVO: no requiere accion (notificaciones automaticas, CC, cerradas, descartadas)
URGENTE: atencion inmediata (prioridad alta, bloqueantes, piden respuesta urgente)
PARA_MARTA: dirigido a ella o necesita su decision
MEDIO: relevante pero no requiere respuesta directa
DUDOSO: no encaja

Del asunto extrae: numero de incidencia, proyecto, estado (Nueva/En curso/Preproduccion/En revision/Resuelta/Cerrada/Descartada).
Responde SOLO JSON."""

    user_prompt = f"""Clasifica este email de Redmine:
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


def guardar(email_data, clf):
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table = dynamodb.Table(TABLE_NAME)

    # Usar la fecha del email original como timestamp
    timestamp = email_data.get("fecha_iso", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    # Detectar si es de Redmine por formato del asunto (#XXXXX)
    import re
    asunto = email_data.get("asunto", "")
    es_redmine = bool(re.search(r"#\d{3,}", asunto))

    table.put_item(Item={
        "email_id": email_data["email_id"],
        "timestamp": timestamp,
        "fecha_email": email_data.get("fecha", ""),
        "remitente": email_data.get("remitente", ""),
        "destinatario": email_data.get("destinatario", ""),
        "asunto": email_data.get("asunto", ""),
        "clasificacion": clf.get("clasificacion", "DUDOSO"),
        "proyecto": clf.get("proyecto", "N/A"),
        "numero_incidencia": clf.get("numero_incidencia", "N/A"),
        "estado_redmine": clf.get("estado_redmine", "N/A"),
        "prioridad_redmine": clf.get("prioridad_redmine", "N/A"),
        "asignado_a": clf.get("asignado_a", "N/A"),
        "resumen": clf.get("resumen", ""),
        "requiere_respuesta": clf.get("requiere_respuesta", False),
        "accion_realizada": "",
        "es_redmine": es_redmine,
    })


def main():
    print("=" * 60)
    print("GASTON - Carga de incidencias reales (ultimos 2 dias)")
    print("=" * 60)

    service = get_gmail_service()
    emails = leer_incidencias(service, max_results=50)
    print(f"Incidencias encontradas: {len(emails)}\n")

    for i, email in enumerate(emails, 1):
        asunto_safe = email['asunto'].encode('ascii', 'replace').decode()
        fecha_corta = email['fecha_iso'][:16] if email.get('fecha_iso') else '?'
        print(f"[{i}/{len(emails)}] {fecha_corta} | {asunto_safe[:55]}")

        try:
            clf = clasificar(email)
            tipo = clf.get("clasificacion", "DUDOSO")
            tag = {"INFORMATIVO": "INFO", "URGENTE": "URGE", "PARA_MARTA": "MART", "MEDIO": "MEDI", "DUDOSO": "DUDO"}
            inc = clf.get("numero_incidencia", "N/A")
            estado = clf.get("estado_redmine", "?")

            print(f"  [{tag.get(tipo, '?')}] #{inc} | {estado} | {clf.get('resumen', '').encode('ascii', 'replace').decode()[:55]}")

            guardar(email, clf)

        except Exception as e:
            print(f"  ERROR: {str(e)[:60]}")

    print(f"\n{'=' * 60}")
    print(f"Cargados {len(emails)} emails en DynamoDB. Refresca el dashboard.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
