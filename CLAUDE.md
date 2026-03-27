# Gaston - Agente de gestion de incidencias Redmine

## Que es
Agente serverless que gestiona la bandeja de Gmail de Marta (mmontero@mgpsa.com), directora de desarrollo de negocio. Clasifica emails de Redmine automaticamente, mueve los informativos a carpeta, crea drafts (reply en hilo) para los urgentes, y responde preguntas via Telegram.

## Stack
- Python 3.10, AWS Lambda (SAM), API Gateway, EventBridge
- AWS Bedrock (Claude Haiku 4.5), DynamoDB (gaston_emails)
- Gmail API (OAuth2)
- Telegram Bot API
- Streamlit Community Cloud (dashboard)

## Arquitectura
```
Gmail (Marta) → Lambda (gaston_handler)
  ├─ Gmail API (lee emails de Redmine)
  ├─ Bedrock Haiku (clasifica: INFORMATIVO / URGENTE / PARA_MARTA / MEDIO / DUDOSO)
  ├─ Gmail API (mueve informativos a carpeta, crea drafts reply para urgentes)
  └─ DynamoDB (guarda clasificaciones)
       │
       ├─ Telegram Bot (resumen diario 8 AM + /actualizar on-demand + preguntas)
       └─ Streamlit Cloud Dashboard
```

## Archivos
- `src/lambda_function.py` — Handler principal: cron diario, Telegram, API dashboard
- `src/clasificador.py` — Clasifica emails con Bedrock Haiku, genera drafts, responde preguntas
- `src/gmail_client.py` — Gmail API: leer, mover a carpeta "Redmine No Urgentes", crear drafts reply
- `src/dynamodb_client.py` — DynamoDB: guardar, consultar, anti-duplicados, resumen 24h
- `src/telegram_bot.py` — Telegram: enviar mensajes, resumen diario, notificaciones urgentes
- `src/aws_secrets.py` — Lee credenciales OAuth2 de AWS Secrets Manager
- `dashboard.py` — Streamlit Cloud: dashboard, por proyecto, atencion Marta, todos los emails
- `template.yaml` — SAM: Lambda, API Gateway, EventBridge cron diario 8 AM

## Contexto de negocio
- Emails de Redmine llegan de: tecnologia@mgpsa.com, soporte@mgpsa.com
- Formato asunto: `[NOMBRE] - Tipo #NUMERO (Estado) [PROYECTO] - PRE/PRO - Modulo - Titulo`
- Proyecto principal: SHEREKHAN (Shere Khan) en variantes BACK y FRONT
- Otros proyectos: Smee, Negocio
- Estados: Nueva, En curso, Preproduccion, En revision, Resuelta, Cerrada, Descartada

## Clasificacion
- INFORMATIVO → mover a carpeta "Redmine No Urgentes" (Marta borra en bloque)
- URGENTE → marcar leido + crear draft reply en hilo + notificar Telegram
- PARA_MARTA → marcar leido + crear draft reply en hilo
- MEDIO → marcar leido, queda en inbox sin draft
- DUDOSO → no tocar, queda en inbox

## Telegram comandos
- `/start` — Bienvenida y lista de comandos
- `/actualizar` — Procesa emails nuevos en el momento (on-demand)
- `/resumen` — Resumen de las ultimas 24h
- Pregunta libre — Gaston responde con contexto de DynamoDB

## Credenciales
- AWS Secrets Manager: `gaston/gmail/oauth-credentials` (client_id, client_secret, refresh_token)
- DynamoDB: `gaston_emails` (PK: email_id, SK: timestamp)
- Env vars Lambda: GASTON_TELEGRAM_TOKEN, GASTON_MARTA_CHAT_ID
- Streamlit Cloud Secrets: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION

## Ejecucion
```bash
# Deploy Lambda a AWS
sam build && sam deploy --no-confirm-changeset

# Dashboard en Streamlit Community Cloud
# Repo: mmontero-gaston/gaston-dashboard

# Setup OAuth (una vez, con Marta)
cd setup && python obtener_refresh_token.py
```

## Costes estimados
- Lambda + API Gateway + EventBridge: ~$0 (free tier)
- DynamoDB: ~$0 (free tier)
- Bedrock Haiku: ~$2-3/mes (cron diario + on-demand)
- Secrets Manager: ~$1/mes
- Total: ~$3-4/mes
