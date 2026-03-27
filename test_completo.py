"""
Test COMPLETO de Gaston.
Ejecuta el flujo real: clasifica, mueve no urgentes a carpeta, crea drafts.

USO: python test_completo.py [numero_emails]
Por defecto procesa 3 emails.

CUIDADO: Este test SI ejecuta acciones reales en el Gmail de Marta:
- Mueve emails INFORMATIVOS a carpeta "Redmine No Urgentes"
- Crea DRAFTS (borradores, NUNCA envia) para URGENTES/PARA_MARTA
"""

import json
import sys
import os
import base64
from email.mime.text import MIMEText

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import boto3

# ============= CONFIG =============
MODEL_ID = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
REGION = "eu-west-1"
LABEL_NAME = "Redmine No Urgentes"


def get_gmail_service():
    token_path = os.path.join(os.path.dirname(__file__), "setup", "token.json")
    creds = Credentials.from_authorized_user_file(token_path)
    if creds.expired:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


def get_or_create_label(service):
    """Crea la etiqueta si no existe, retorna el ID."""
    results = service.users().labels().list(userId="me").execute()
    for label in results.get("labels", []):
        if label["name"] == LABEL_NAME:
            print(f"  Etiqueta '{LABEL_NAME}' ya existe (ID: {label['id']})")
            return label["id"]

    created = service.users().labels().create(userId="me", body={
        "name": LABEL_NAME,
        "labelListVisibility": "labelShow",
        "messageListVisibility": "show",
    }).execute()
    print(f"  Etiqueta '{LABEL_NAME}' CREADA (ID: {created['id']})")
    return created["id"]


def leer_emails(service, max_results=3):
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
        })
    return emails


def clasificar(email_data):
    bedrock = boto3.client("bedrock-runtime", region_name=REGION)

    system_prompt = """Eres Gaston. Clasifica emails de Redmine para Marta (mmontero@mgpsa.com).
Categorias: INFORMATIVO | URGENTE | PARA_MARTA | MEDIO | DUDOSO
Responde SOLO con JSON valido."""

    user_prompt = f"""Clasifica:
1. clasificacion: INFORMATIVO | URGENTE | PARA_MARTA | MEDIO | DUDOSO
2. numero_incidencia: #XXXX
3. proyecto: nombre
4. resumen: 1 frase
5. requiere_respuesta: true/false

{{"clasificacion":"...","numero_incidencia":"...","proyecto":"...","resumen":"...","requiere_respuesta":false}}

De: {email_data['remitente']}
Para: {email_data['destinatario']}
CC: {email_data.get('cc', '')}
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


def mover_a_no_urgentes(service, email_id, label_id):
    service.users().messages().modify(
        userId="me", id=email_id,
        body={"addLabelIds": [label_id], "removeLabelIds": ["INBOX", "UNREAD"]}
    ).execute()


def crear_draft(service, destinatario, asunto, cuerpo_draft):
    message = MIMEText(cuerpo_draft, "plain", "utf-8")
    message["to"] = destinatario
    message["subject"] = f"Re: {asunto}"
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    draft = service.users().drafts().create(
        userId="me", body={"message": {"raw": raw}}
    ).execute()
    return draft.get("id")


def generar_draft_texto(email_data):
    bedrock = boto3.client("bedrock-runtime", region_name=REGION)
    prompt = f"""Redacta un borrador de respuesta profesional y conciso en espanol.
Es para Marta, directora de desarrollo de negocio. Firma como "Marta".

Email original:
De: {email_data['remitente']}
Asunto: {email_data['asunto']}
Cuerpo: {email_data['cuerpo'][:1500]}

Escribe SOLO el texto del borrador."""

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


# ============= MAIN =============

def main():
    num = int(sys.argv[1]) if len(sys.argv) > 1 else 3

    print("=" * 60)
    print("GASTON - Test COMPLETO (acciones reales)")
    print("=" * 60)

    # Confirmar
    print(f"\nVa a procesar {num} emails REALES del Gmail de Marta.")
    print("- INFORMATIVOS -> mover a carpeta 'Redmine No Urgentes'")
    print("- URGENTES/PARA_MARTA -> crear draft (NO envia)")
    resp = input("\nContinuar? (s/n): ").strip().lower()
    if resp != "s":
        print("Cancelado.")
        return

    service = get_gmail_service()
    profile = service.users().getProfile(userId="me").execute()
    print(f"\nConectado: {profile['emailAddress']}")

    # Crear etiqueta
    print("\nPreparando etiqueta...")
    label_id = get_or_create_label(service)

    # Leer emails
    print(f"\nLeyendo {num} emails de Redmine...")
    emails = leer_emails(service, max_results=num)
    print(f"Encontrados: {len(emails)}")

    movidos = 0
    drafts_creados = 0

    for i, email in enumerate(emails, 1):
        print(f"\n--- Email {i}/{len(emails)} ---")
        asunto_safe = email['asunto'].encode('ascii', 'replace').decode()
        print(f"Asunto: {asunto_safe[:70]}")

        # Clasificar
        try:
            resultado = clasificar(email)
        except Exception as e:
            print(f"  Error clasificando: {e}")
            continue

        tipo = resultado.get("clasificacion", "DUDOSO")
        print(f"  => {tipo} | #{resultado.get('numero_incidencia', 'N/A')} | {resultado.get('proyecto', 'N/A')}")

        resumen_safe = resultado.get('resumen', '').encode('ascii', 'replace').decode()
        print(f"  Resumen: {resumen_safe[:80]}")

        # Ejecutar accion
        if tipo == "INFORMATIVO":
            mover_a_no_urgentes(service, email["email_id"], label_id)
            print(f"  >> MOVIDO a '{LABEL_NAME}'")
            movidos += 1

        elif tipo in ("URGENTE", "PARA_MARTA"):
            # Marcar leido
            service.users().messages().modify(
                userId="me", id=email["email_id"],
                body={"removeLabelIds": ["UNREAD"]}
            ).execute()

            # Generar y crear draft
            try:
                draft_text = generar_draft_texto(email)
                draft_id = crear_draft(service, email["remitente"], email["asunto"], draft_text)
                print(f"  >> DRAFT creado (ID: {draft_id}) - NO enviado")
                drafts_creados += 1
            except Exception as e:
                print(f"  >> Error creando draft: {e}")

        elif tipo == "MEDIO":
            service.users().messages().modify(
                userId="me", id=email["email_id"],
                body={"removeLabelIds": ["UNREAD"]}
            ).execute()
            print(f"  >> Marcado leido, queda en inbox")

        else:
            print(f"  >> Sin accion (dudoso)")

    print(f"\n{'=' * 60}")
    print(f"RESULTADO:")
    print(f"  Emails procesados: {len(emails)}")
    print(f"  Movidos a '{LABEL_NAME}': {movidos}")
    print(f"  Drafts creados (NO enviados): {drafts_creados}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
