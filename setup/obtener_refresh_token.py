"""
=== GASTON — Obtener Refresh Token de Gmail (OAuth2) ===

Este script se ejecuta UNA SOLA VEZ con Marta presente.
Abre el navegador, Marta autoriza con su cuenta corporativa,
y obtenemos el refresh_token permanente.

ANTES DE EJECUTAR:
1. Crea un proyecto en Google Cloud Console (o usa el existente)
2. Habilita la Gmail API
3. Crea credenciales OAuth2 (tipo "Desktop App")
4. Descarga el JSON de credenciales y ponlo en esta carpeta como "credentials.json"
5. Ejecuta: python obtener_refresh_token.py

IMPORTANTE: Con Marta delante, ella debe hacer login con su cuenta corporativa.
"""

import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# Permisos que necesita Gaston sobre el Gmail de Marta
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",    # Leer emails
    "https://www.googleapis.com/auth/gmail.modify",      # Mover a etiquetas/carpetas + marcar leido
    "https://www.googleapis.com/auth/gmail.compose",     # Crear drafts
    "https://www.googleapis.com/auth/gmail.labels",      # Crear etiquetas/carpetas (Redmine No Urgentes)
]

CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"


def main():
    creds = None

    # Si ya existe un token guardado, intentar usarlo
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # Si no hay credenciales validas, hacer el flujo OAuth
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Renovando token existente...")
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                print("=" * 60)
                print("ERROR: No se encuentra 'credentials.json'")
                print()
                print("Pasos para obtenerlo:")
                print("1. Ve a https://console.cloud.google.com/")
                print("2. Selecciona o crea un proyecto")
                print("3. APIs & Services > Enable APIs > Gmail API")
                print("4. APIs & Services > Credentials > Create Credentials")
                print("5. Tipo: OAuth client ID > Desktop App")
                print("6. Descarga el JSON y renombralo 'credentials.json'")
                print("7. Ponlo en esta carpeta y vuelve a ejecutar")
                print("=" * 60)
                return

            print("=" * 60)
            print("GASTON — Autorizacion de Gmail")
            print("=" * 60)
            print()
            print("Se va a abrir el navegador.")
            print("Marta debe iniciar sesion con su cuenta corporativa")
            print("y aceptar los permisos.")
            print()

            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=8080)

        # Guardar token para futuras ejecuciones
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    # Verificar que funciona
    print()
    print("Verificando acceso al Gmail...")
    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()

    print()
    print("=" * 60)
    print("AUTORIZACION EXITOSA!")
    print("=" * 60)
    print(f"  Email:          {profile.get('emailAddress')}")
    print(f"  Total mensajes: {profile.get('messagesTotal')}")
    print()

    # Mostrar los datos que hay que guardar en AWS Secrets Manager
    token_data = json.loads(creds.to_json())
    print("=" * 60)
    print("DATOS PARA AWS SECRETS MANAGER")
    print("=" * 60)
    print()
    print("Guarda este JSON en AWS Secrets Manager como 'gaston/gmail/oauth-credentials':")
    print()

    secret_json = {
        "client_id": token_data.get("client_id"),
        "client_secret": token_data.get("client_secret"),
        "refresh_token": token_data.get("refresh_token"),
    }
    print(json.dumps(secret_json, indent=2))
    print()
    print("Comando para guardarlo en AWS:")
    print()
    print(f'aws secretsmanager create-secret --name "gaston/gmail/oauth-credentials" --secret-string \'{json.dumps(secret_json)}\' --region eu-west-1')
    print()
    print("=" * 60)
    print("El refresh_token NO caduca si publicas la app en modo Production.")
    print("Token guardado localmente en 'token.json' como backup.")
    print("=" * 60)


if __name__ == "__main__":
    main()
