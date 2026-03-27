"""
Test local de Gaston.
Lee emails reales del Gmail de Marta, los clasifica con Bedrock,
y muestra el resultado SIN ejecutar acciones (no mueve ni crea drafts).

Uso: python test_local.py
"""

import json
import sys
import os

# Usar las credenciales locales del token.json en vez de Secrets Manager
# para poder probar sin AWS Secrets Manager
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import boto3

# ============= GMAIL (usando token local) =============

def get_gmail_service():
    """Usa el token.json local para conectar a Gmail."""
    token_path = os.path.join(os.path.dirname(__file__), "setup", "token.json")
    creds = Credentials.from_authorized_user_file(token_path)
    if creds.expired:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


def leer_emails_redmine(service, max_results=10):
    """Lee los ultimos emails de Redmine de la bandeja de Marta."""
    response = service.users().messages().list(
        userId="me",
        maxResults=max_results,
        q="from:soporte@mgpsa.com OR from:tecnologia@mgpsa.com"
    ).execute()

    emails = []
    for msg_ref in response.get("messages", []):
        msg = service.users().messages().get(
            userId="me", id=msg_ref["id"], format="full"
        ).execute()

        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}

        # Extraer cuerpo
        cuerpo = ""
        payload = msg["payload"]
        import base64
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


# ============= BEDROCK (clasificacion) =============

def clasificar_con_bedrock(email_data):
    """Clasifica un email usando Bedrock Haiku."""
    bedrock = boto3.client("bedrock-runtime", region_name="eu-west-1")

    system_prompt = """Eres Gaston, un asistente que clasifica emails de incidencias de Redmine
para Marta (mmontero@mgpsa.com), directora del departamento de desarrollo de negocio.

Clasifica el email en: INFORMATIVO | URGENTE | PARA_MARTA | MEDIO | DUDOSO

INFORMATIVO: no requiere accion de Marta (cambios de estado automaticos, emails en CC, cerradas/descartadas)
URGENTE: requiere accion inmediata (prioridad alta, bloqueantes, piden respuesta urgente)
PARA_MARTA: dirigido a ella o necesita su decision (mencionada en Para/cuerpo, estado Resuelta en SHEREKHAN)
MEDIO: relevante pero no requiere respuesta (cambios de estado en sus proyectos, info util)
DUDOSO: no encaja en ninguna categoria

Responde SOLO con JSON valido."""

    user_prompt = f"""Analiza este email:

1. clasificacion: INFORMATIVO | URGENTE | PARA_MARTA | MEDIO | DUDOSO
2. numero_incidencia: numero (#XXXX) si aparece
3. proyecto: nombre del proyecto
4. resumen: 1 frase
5. motivo_clasificacion: por que esa clasificacion

JSON:
{{"clasificacion": "...", "numero_incidencia": "...", "proyecto": "...", "resumen": "...", "motivo_clasificacion": "..."}}

EMAIL:
De: {email_data['remitente']}
Para: {email_data['destinatario']}
CC: {email_data.get('cc', '')}
Asunto: {email_data['asunto']}
Cuerpo:
{email_data['cuerpo'][:2000]}"""

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 400,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}]
    })

    response = bedrock.invoke_model(
        modelId="eu.anthropic.claude-haiku-4-5-20251001-v1:0",
        body=body,
        contentType="application/json",
        accept="application/json"
    )

    result = json.loads(response["body"].read())
    text = result["content"][0]["text"].strip()

    # Parsear JSON
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


# ============= MAIN =============

EMOJI = {
    "INFORMATIVO": "[NO-URG]",
    "URGENTE": "[URGENT]",
    "PARA_MARTA": "[MARTA]",
    "MEDIO": "[MEDIO]",
    "DUDOSO": "[DUDOSO]",
}

def main():
    print("=" * 70)
    print("GASTON - Test de clasificacion local")
    print("=" * 70)
    print()

    # 1. Conectar a Gmail
    print("Conectando a Gmail de Marta...")
    service = get_gmail_service()
    profile = service.users().getProfile(userId="me").execute()
    print(f"Conectado: {profile['emailAddress']}")
    print()

    # 2. Leer emails de Redmine
    num_emails = 5
    if len(sys.argv) > 1:
        num_emails = int(sys.argv[1])

    print(f"Leyendo ultimos {num_emails} emails de Redmine...")
    emails = leer_emails_redmine(service, max_results=num_emails)
    print(f"Encontrados: {len(emails)}")
    print()

    # 3. Clasificar cada email
    print("Clasificando con Bedrock (Claude Haiku)...")
    print("=" * 70)

    conteos = {"INFORMATIVO": 0, "URGENTE": 0, "PARA_MARTA": 0, "MEDIO": 0, "DUDOSO": 0}

    for i, email in enumerate(emails, 1):
        print(f"\n--- Email {i}/{len(emails)} ---")
        print(f"De:     {email['remitente'][:60]}")
        print(f"Para:   {email['destinatario'][:60]}")
        print(f"Asunto: {email['asunto'][:80]}")

        try:
            resultado = clasificar_con_bedrock(email)
            tipo = resultado.get("clasificacion", "DUDOSO")
            emoji = EMOJI.get(tipo, "?")
            conteos[tipo] = conteos.get(tipo, 0) + 1

            print(f"\n{emoji} CLASIFICACION: {tipo}")
            print(f"   Incidencia: {resultado.get('numero_incidencia', 'N/A')}")
            print(f"   Proyecto:   {resultado.get('proyecto', 'N/A')}")
            print(f"   Resumen:    {resultado.get('resumen', '')}")
            print(f"   Motivo:     {resultado.get('motivo_clasificacion', '')}")

        except Exception as e:
            print(f"   ERROR: {e}")

    # 4. Resumen
    print("\n" + "=" * 70)
    print("RESUMEN")
    print("=" * 70)
    for tipo, count in conteos.items():
        if count > 0:
            print(f"  {EMOJI.get(tipo, '')} {tipo}: {count}")
    print()
    print("NOTA: Este test solo clasifica, NO mueve emails ni crea drafts.")
    print("=" * 70)


if __name__ == "__main__":
    main()
