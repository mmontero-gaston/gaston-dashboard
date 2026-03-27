# Gaston - Agente de gestion de incidencias Redmine

## Que es
Agente serverless que gestiona la bandeja de Gmail de Marta (mmontero@mgpsa.com), directora de desarrollo de negocio. Clasifica emails de Redmine automaticamente, archiva los informativos, crea drafts para los urgentes, y responde preguntas via Telegram.

## Stack
- Python 3.12, AWS Lambda (SAM), API Gateway, EventBridge
- AWS Bedrock (Claude Haiku 4.5), DynamoDB (gaston_emails)
- Gmail API (OAuth2), Google Pub/Sub
- Telegram Bot API
- Redmine API (read-only)
- Streamlit (dashboard local)

## Arquitectura
```
Gmail (Marta) → Pub/Sub → API Gateway → Lambda (gaston_handler)
  ├─ Gmail API (lee emails de Redmine)
  ├─ Bedrock Haiku (clasifica: INFORMATIVO / URGENTE / PARA_MARTA / DUDOSO)
  ├─ Redmine API (contexto read-only de incidencias)
  ├─ Gmail API (archiva informativos, crea drafts para urgentes)
  └─ DynamoDB (guarda clasificaciones)
       │
       ├─ Telegram Bot (resumen diario 8 AM + preguntas de Marta)
       └─ Streamlit Dashboard (vista completa local)
```

## Archivos
- `src/lambda_function.py` — Handler principal: orquesta Pub/Sub, cron, Telegram y API
- `src/clasificador.py` — Clasifica emails con Bedrock Haiku, genera drafts, responde preguntas
- `src/gmail_client.py` — Gmail API: leer, archivar, marcar leido, crear drafts
- `src/dynamodb_client.py` — DynamoDB: guardar, consultar por proyecto/incidencia, resumen 24h
- `src/redmine_client.py` — Redmine API read-only: detalle incidencias, proyectos, historial
- `src/telegram_bot.py` — Telegram: enviar mensajes, resumen diario, notificaciones urgentes
- `src/secrets.py` — Lee credenciales OAuth2 de AWS Secrets Manager
- `dashboard.py` — Streamlit: dashboard, por proyecto, urgentes, todos los emails
- `template.yaml` — SAM: Lambda, DynamoDB (con TTL), API Gateway, EventBridge crons
- `setup/obtener_refresh_token.py` — Setup one-time OAuth2 con Marta

## Contexto de negocio
- Emails de Redmine llegan de: tecnologia@mgpsa.com, soporte@mgpsa.com
- Formato asunto: `[NOMBRE] - Tipo #NUMERO (Estado) [PROYECTO] - PRE/PRO - Modulo - Titulo`
- Proyecto principal: SHEREKHAN (Shere Khan) en variantes BACK y FRONT
- Otros proyectos: Smee, Negocio
- Estados: Nueva, En curso, Preproduccion, En revision, Resuelta, Cerrada, Descartada

## Clasificacion
- INFORMATIVO → archivar (quitar de inbox) + marcar leido
- URGENTE → marcar leido + crear draft + notificar Telegram inmediatamente
- PARA_MARTA → marcar leido + crear draft si requiere respuesta
- DUDOSO → no tocar, queda en inbox

## Credenciales
- AWS Secrets Manager: `gaston/gmail/oauth-credentials` (client_id, client_secret, refresh_token)
- DynamoDB: `gaston_emails` (PK: email_id, SK: timestamp, TTL habilitado)
- Env vars: GASTON_TELEGRAM_TOKEN, GASTON_MARTA_CHAT_ID, GASTON_REDMINE_URL, GASTON_REDMINE_API_KEY

## Ejecucion
```bash
# Dashboard local
streamlit run dashboard.py

# Deploy a AWS
sam build && sam deploy --guided

# Setup OAuth (una vez, con Marta)
cd setup && python obtener_refresh_token.py
```

## Costes estimados
- Lambda + API Gateway + EventBridge: ~$0 (free tier)
- DynamoDB: ~$0 (free tier, TTL limpia registros antiguos)
- Bedrock Haiku: ~$3-5/mes (100 emails/dia)
- Secrets Manager: ~$1/mes
- Total: ~$5/mes
