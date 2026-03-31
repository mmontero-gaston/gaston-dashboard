# Gaston - Agente de gestion de incidencias Redmine

## Que es
Agente serverless que gestiona la bandeja de Gmail de Marta (mmontero@mgpsa.com), directora de desarrollo de negocio. Clasifica emails de incidencias de Redmine automaticamente, mueve los informativos a una carpeta dedicada (sin marcarlos como leidos), y registra todo en un dashboard. Tambien permite mover tarjetas en Trello via Telegram.

## Stack
- Python 3.10, AWS Lambda (SAM), API Gateway, EventBridge
- AWS Bedrock (Claude Haiku 4.5), DynamoDB (gaston_emails)
- Gmail API (OAuth2) — cuenta corporativa de Marta
- Telegram Bot API (@gaston_mgpsa_bot)
- Trello API (tableros de Shere Khan)
- Streamlit Community Cloud (dashboard)

## Arquitectura
```
Gmail (Marta) → Lambda (gaston_handler)
  ├─ Gmail API (lee emails de Redmine, ultimas 24h)
  ├─ Bedrock Haiku (clasifica: MUY_URGENTE / URGENTE / INFORMATIVO)
  ├─ Gmail API (mueve informativos a carpeta "Redmine No Urgentes" sin marcar leido)
  └─ DynamoDB (guarda clasificaciones)
       │
       ├─ Telegram Bot
       │    ├─ Resumen diario 8 AM
       │    ├─ /actualizar (on-demand)
       │    ├─ /resumen
       │    ├─ Preguntas libres
       │    └─ Comandos Trello (mover tarjetas)
       │
       └─ Streamlit Cloud Dashboard
```

## Reglas de negocio

### Clasificacion de emails
- **MUY_URGENTE**: "Subida Produccion" o "Subida Prod" en el asunto → Gmail intacto
- **URGENTE**: Dirigidos a Marta, soporte@ en CC con remitente persona, preguntas directas → Gmail intacto
- **INFORMATIVO**: Notificaciones automaticas, cambios de estado, Marta en CC → Mover a carpeta sin leer

### Que NO hace Gaston
- No crea drafts ni borradores
- No marca emails como leidos
- No toca emails que no sean de Redmine (#XXXXX en asunto)
- No toca emails anteriores al periodo de las ultimas 24h
- No toca emails programados
- No modifica ni cierra incidencias en Redmine

### Trello
- Solo actua cuando Marta lo pide explicitamente via Telegram
- Puede mover tarjetas entre listas/columnas
- Añade comentario con fecha si Marta la menciona
- Tableros principales: SHERE KHAN - PRE, SHERE KHAN - PRO, SHERE KHAN - NEGOCIO
- Tableros secundarios: Smee, Desarrollo de Negocio

## Archivos
- `src/lambda_function.py` — Handler principal: cron diario, Telegram (comandos + preguntas), API dashboard
- `src/clasificador.py` — Clasifica emails con Bedrock Haiku, responde preguntas
- `src/gmail_client.py` — Gmail API: leer, mover a carpeta "Redmine No Urgentes" (sin marcar leido)
- `src/dynamodb_client.py` — DynamoDB: guardar, consultar, anti-duplicados, resumen 24h
- `src/telegram_bot.py` — Telegram: enviar mensajes, resumen diario, notificaciones
- `src/trello_client.py` — Trello API: buscar tarjetas, mover entre listas, comentar
- `src/aws_secrets.py` — Lee credenciales OAuth2 de AWS Secrets Manager
- `dashboard.py` — Streamlit Cloud: dashboard, por proyecto, atencion Marta, todos los emails
- `template.yaml` — SAM: Lambda, API Gateway, EventBridge cron diario 8 AM

## Contexto de negocio
- Emails de Redmine llegan de: tecnologia@mgpsa.com, soporte@mgpsa.com
- Formato asunto: `[NOMBRE] - Tipo #NUMERO (Estado) [PROYECTO] - PRE/PRO - Modulo - Titulo`
- Proyecto principal: SHEREKHAN (Shere Khan) en variantes BACK y FRONT
- Otros proyectos: Smee, Negocio
- Estados Redmine: Nueva, En curso, Preproduccion, En revision, Resuelta, Cerrada, Descartada

## Credenciales
- AWS Secrets Manager: `gaston/gmail/oauth-credentials` (client_id, client_secret, refresh_token)
- DynamoDB: `gaston_emails` (PK: email_id, SK: timestamp)
- Env vars Lambda: GASTON_TELEGRAM_TOKEN, GASTON_MARTA_CHAT_ID, GASTON_TRELLO_API_KEY, GASTON_TRELLO_TOKEN
- Streamlit Cloud Secrets: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION
- Google Cloud Project: Gaston (cuenta mmontero@mgpsa.com, OAuth interno, no caduca)
- Trello Power-Up: Gaston (API Key + Token permanente)

## Ejecucion
```bash
# Deploy Lambda a AWS
sam build && sam deploy --no-confirm-changeset

# Dashboard en Streamlit Community Cloud
# Repo: mmontero-gaston/gaston-dashboard

# Setup OAuth Gmail (una vez, con Marta)
cd setup && python obtener_refresh_token.py
```

## Costes estimados
- Lambda + API Gateway + EventBridge: ~$0 (free tier)
- DynamoDB: ~$0 (free tier)
- Bedrock Haiku: ~$2-3/mes (cron diario + on-demand)
- Secrets Manager: ~$1/mes
- Trello API: $0 (gratis)
- Streamlit Cloud: $0 (gratis)
- Total: ~$3-4/mes
