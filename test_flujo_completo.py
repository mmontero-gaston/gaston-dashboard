"""
Test del flujo completo de Gaston:
1. Lee emails de Redmine del Gmail de Marta
2. Clasifica con Bedrock Haiku
3. Guarda en DynamoDB
4. Mueve informativos a carpeta "Redmine No Urgentes"
5. Crea drafts para urgentes/para_marta
6. Envia resumen a Telegram (a Daniel para pruebas)
"""

import json
import sys
import os
import base64
from datetime import datetime, timezone
from email.mime.text import MIMEText

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import boto3
import urllib.request

# ============= CONFIG =============
MODEL_ID = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
REGION = "eu-west-1"
TABLE_NAME = "gaston_emails"
LABEL_NAME = "Redmine No Urgentes"
TELEGRAM_TOKEN = "8241884145:AAHxO2JrmZIzkTrJLU4RTHbEYxe1CkA7XG0"
DANIEL_CHAT_ID = 7676265797  # Pruebas van a Daniel, no a Marta


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
        "name": LABEL_NAME,
        "labelListVisibility": "labelShow",
        "messageListVisibility": "show",
    }).execute()
    return created["id"]


def leer_emails(service, max_results=5):
    response = service.users().messages().list(
        userId="me", maxResults=max_results,
        q="from:@mgpsa.com subject:(#)"
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
        emails.append({
            "email_id": msg_ref["id"],
            "remitente": headers.get("from", ""),
            "destinatario": headers.get("to", ""),
            "cc": headers.get("cc", ""),
            "asunto": headers.get("subject", ""),
            "cuerpo": cuerpo,
            "fecha": headers.get("date", ""),
        })
    return emails


def clasificar(email_data):
    bedrock = boto3.client("bedrock-runtime", region_name=REGION)
    system_prompt = """Eres Gaston. Clasifica emails de Redmine para Marta (mmontero@mgpsa.com).
INFORMATIVO: no requiere accion (notificaciones automaticas, CC, cerradas)
URGENTE: atencion inmediata (prioridad alta, bloqueantes)
PARA_MARTA: dirigido a ella o necesita su decision
MEDIO: relevante pero no requiere respuesta
DUDOSO: no encaja
Responde SOLO JSON."""

    user_prompt = f"""{{"clasificacion":"...","numero_incidencia":"...","proyecto":"...","resumen":"...","requiere_respuesta":false}}

De: {email_data['remitente']}
Para: {email_data['destinatario']}
Asunto: {email_data['asunto']}
Cuerpo: {email_data['cuerpo'][:2000]}"""

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 300,
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


def guardar_en_dynamo(email_data, clasificacion):
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table = dynamodb.Table(TABLE_NAME)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    table.put_item(Item={
        "email_id": email_data["email_id"],
        "timestamp": timestamp,
        "remitente": email_data.get("remitente", ""),
        "destinatario": email_data.get("destinatario", ""),
        "asunto": email_data.get("asunto", ""),
        "clasificacion": clasificacion.get("clasificacion", "DUDOSO"),
        "proyecto": clasificacion.get("proyecto", "N/A"),
        "numero_incidencia": clasificacion.get("numero_incidencia", "N/A"),
        "resumen": clasificacion.get("resumen", ""),
        "requiere_respuesta": clasificacion.get("requiere_respuesta", False),
        "accion_realizada": "",
    })
    return timestamp


def generar_draft_texto(email_data):
    bedrock = boto3.client("bedrock-runtime", region_name=REGION)
    prompt = f"""Redacta un borrador de respuesta profesional conciso en espanol para Marta. Firma como "Marta".

De: {email_data['remitente']}
Asunto: {email_data['asunto']}
Cuerpo: {email_data['cuerpo'][:1500]}

Solo el texto del borrador."""

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


def crear_draft(service, destinatario, asunto, cuerpo_draft):
    clean_dest = destinatario
    if "<" in destinatario and ">" in destinatario:
        clean_dest = destinatario.split("<")[1].split(">")[0]
    message = MIMEText(cuerpo_draft, "plain", "utf-8")
    message["to"] = clean_dest
    message["subject"] = f"Re: {asunto}"
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    draft = service.users().drafts().create(
        userId="me", body={"message": {"raw": raw}}
    ).execute()
    return draft.get("id")


def send_telegram(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req)


def main():
    num = int(sys.argv[1]) if len(sys.argv) > 1 else 5

    print("=" * 60)
    print("GASTON - Flujo completo")
    print("=" * 60)

    service = get_gmail_service()
    label_id = get_or_create_label(service)

    print(f"Leyendo {num} emails de Redmine...")
    emails = leer_emails(service, max_results=num)
    print(f"Encontrados: {len(emails)}\n")

    resultados = {"INFORMATIVO": 0, "URGENTE": 0, "PARA_MARTA": 0, "MEDIO": 0, "DUDOSO": 0}
    drafts = 0
    movidos = 0
    resumen_lines = []

    for i, email in enumerate(emails, 1):
        asunto_safe = email['asunto'].encode('ascii', 'replace').decode()
        print(f"[{i}/{len(emails)}] {asunto_safe[:65]}")

        try:
            clf = clasificar(email)
            tipo = clf.get("clasificacion", "DUDOSO")
            resultados[tipo] = resultados.get(tipo, 0) + 1

            # Guardar en DynamoDB
            guardar_en_dynamo(email, clf)

            resumen_safe = clf.get('resumen', '').encode('ascii', 'replace').decode()
            print(f"  => {tipo} | #{clf.get('numero_incidencia', 'N/A')} | {resumen_safe[:60]}")

            tag = {"INFORMATIVO": "[NO-URG]", "URGENTE": "[URGENT]", "PARA_MARTA": "[MARTA]", "MEDIO": "[MEDIO]", "DUDOSO": "[?]"}
            resumen_lines.append(f"{tag.get(tipo, '?')} #{clf.get('numero_incidencia', 'N/A')} ({clf.get('proyecto', 'N/A')}): {clf.get('resumen', '')}")

            if tipo == "INFORMATIVO":
                service.users().messages().modify(
                    userId="me", id=email["email_id"],
                    body={"addLabelIds": [label_id], "removeLabelIds": ["INBOX", "UNREAD"]}
                ).execute()
                print(f"  >> Movido a '{LABEL_NAME}'")
                movidos += 1

            elif tipo in ("URGENTE", "PARA_MARTA"):
                service.users().messages().modify(
                    userId="me", id=email["email_id"],
                    body={"removeLabelIds": ["UNREAD"]}
                ).execute()
                try:
                    draft_text = generar_draft_texto(email)
                    draft_id = crear_draft(service, email["remitente"], email["asunto"], draft_text)
                    print(f"  >> Draft creado: {draft_id}")
                    drafts += 1
                except Exception as e:
                    print(f"  >> Error draft: {e}")

            elif tipo == "MEDIO":
                service.users().messages().modify(
                    userId="me", id=email["email_id"],
                    body={"removeLabelIds": ["UNREAD"]}
                ).execute()
                print(f"  >> Marcado leido, en inbox")

        except Exception as e:
            print(f"  ERROR: {str(e)[:80]}")

    # Enviar resumen a Telegram (a Daniel)
    print(f"\nEnviando resumen a Telegram...")
    telegram_text = f"Gaston - Resumen de prueba\n\n"
    telegram_text += f"Emails procesados: {len(emails)}\n"
    telegram_text += f"Informativos (movidos): {movidos}\n"
    telegram_text += f"Drafts creados: {drafts}\n\n"
    for line in resumen_lines:
        telegram_text += f"{line}\n"

    send_telegram(DANIEL_CHAT_ID, telegram_text)
    print("Resumen enviado a tu Telegram!")

    print(f"\n{'=' * 60}")
    print(f"COMPLETADO: {len(emails)} emails, {movidos} movidos, {drafts} drafts")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
