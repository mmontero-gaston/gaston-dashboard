import json
import logging
import boto3

logger = logging.getLogger(__name__)

MODEL_ID = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
REGION = "eu-west-1"

bedrock = boto3.client("bedrock-runtime", region_name=REGION)

SYSTEM_PROMPT = """Eres Gaston, un asistente que clasifica emails de incidencias de Redmine
para Marta (mmontero@mgpsa.com), directora del departamento de desarrollo de negocio.

CONTEXTO DEL ENTORNO:
- Los emails vienen de Redmine y los envia automaticamente cuando hay cambios en incidencias.
- Los remitentes tipicos son: tecnologia@mgpsa.com, soporte@mgpsa.com y usuarios del dominio @mgpsa.com.
- El formato del asunto siempre es: [NOMBRE_REMITENTE] - Tipo #NUMERO (Estado) [PROYECTO] - PRE/PRO - Modulo - Titulo
- Ejemplo: "[WENDY (Shere Khan) - Desarrollo #63475] (Resuelta) [SHEREKHAN-BACK] - PRE - Modulo recibo - Modificar QR"
- El proyecto principal de Marta es SHEREKHAN (Shere Khan) en sus variantes BACK y FRONT.
- Otros proyectos relevantes: Smee, Negocio.

ESTADOS DE INCIDENCIAS (del asunto del email):
- Nueva: incidencia recien creada
- En curso: alguien de IT la esta atendiendo
- Preproduccion: aplicado en pre pero no en produccion
- En revision: IT la resolvio pero negocio reporto fallos
- Resuelta: antes de cerrarse, negocio la esta probando
- Cerrada: ya esta en produccion
- Descartada: IT cerro el ticket porque no era incidencia valida

REGLAS DE CLASIFICACION:

INFORMATIVO (mover a carpeta "Redmine No Urgentes", Marta borra en bloque):
- Cambios de estado automaticos que son solo notificaciones (ej: paso de "En curso" a "Preproduccion")
- Incidencias donde Marta NO esta en el campo "Para" ni mencionada en el cuerpo
- Estados "Cerrada" o "Descartada" cuando Marta no es la asignada
- Actualizaciones de progreso sin preguntas ni peticiones
- Emails donde Marta esta solo en CC
- Cualquier email que claramente no requiere accion de Marta

URGENTE (queda en inbox + Gaston prepara draft de respuesta + notifica Telegram):
- Incidencias con prioridad "Alta" o "Urgente" asignadas a Marta o su equipo
- Estado "En revision" (algo fallo tras resolverse, requiere atencion)
- Incidencias bloqueantes mencionadas en el cuerpo
- Emails que explicitamente piden una respuesta urgente

PARA_MARTA (queda en inbox + Gaston prepara draft de respuesta):
- Emails dirigidos a mmontero@mgpsa.com en el campo "Para"
- Emails que mencionan a Marta o "mmontero" en el cuerpo
- Incidencias en estado "Resuelta" de SHEREKHAN (Marta debe validar)
- Emails que hacen una pregunta o piden una decision
- Estado "Nueva" en proyectos SHEREKHAN (Marta debe estar al tanto)

MEDIO (queda en inbox, sin draft, Marta decide):
- Incidencias relevantes para SHEREKHAN pero que no requieren respuesta directa
- Cambios de estado importantes (ej: paso a "Preproduccion") en proyectos de Marta
- Informacion util que Marta deberia saber pero no necesita actuar

DUDOSO (queda en inbox, no se toca):
- No encaja claramente en ninguna categoria
- Emails de proyectos que no son SHEREKHAN/Smee/Negocio
- Contenido ambiguo o incompleto

IMPORTANTE: Responde SOLO con un objeto JSON valido, sin texto adicional."""

USER_PROMPT = """Analiza este email de Redmine y extrae la informacion:

1. clasificacion: INFORMATIVO | URGENTE | PARA_MARTA | MEDIO | DUDOSO
2. proyecto: nombre del proyecto en Redmine (si aparece)
3. numero_incidencia: numero de la incidencia (#XXXX) si aparece
4. prioridad_redmine: la prioridad que indica Redmine (Alta, Normal, Baja, Urgente) si aparece
5. asignado_a: a quien esta asignada la incidencia si aparece
6. remitente_tipo: SISTEMA_AUTOMATICO | PERSONA
7. resumen: resumen en 1 frase de que trata
8. motivo_clasificacion: por que elegiste esa clasificacion (1 frase)
9. requiere_respuesta: true si el email espera una respuesta de Marta
10. draft_sugerido: si requiere_respuesta es true, sugiere un texto breve de respuesta

Responde SOLO con este JSON:
{{
  "clasificacion": "...",
  "proyecto": "...",
  "numero_incidencia": "...",
  "prioridad_redmine": "...",
  "asignado_a": "...",
  "remitente_tipo": "...",
  "resumen": "...",
  "motivo_clasificacion": "...",
  "requiere_respuesta": false,
  "draft_sugerido": ""
}}

EMAIL:
De: {remitente}
Para: {destinatario}
CC: {cc}
Asunto: {asunto}
Cuerpo:
{cuerpo}"""


def clasificar_email(email_data: dict) -> dict:
    """
    Clasifica un email usando Claude Haiku via Bedrock.
    Retorna dict con clasificacion y metadata extraida.
    """
    try:
        prompt = USER_PROMPT.format(
            remitente=email_data.get("remitente", ""),
            destinatario=email_data.get("destinatario", ""),
            cc=email_data.get("cc", ""),
            asunto=email_data.get("asunto", ""),
            cuerpo=email_data.get("cuerpo", "")[:3000]
        )

        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 600,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}]
        })

        response = bedrock.invoke_model(
            modelId=MODEL_ID,
            body=body,
            contentType="application/json",
            accept="application/json"
        )

        result = json.loads(response["body"].read())
        return _parse_response(result["content"][0]["text"])

    except Exception as e:
        logger.error(f"Error clasificando email {email_data.get('email_id')}: {e}")
        return _fallback_error(str(e))


def generar_draft(email_data: dict, contexto_redmine: str = "") -> str:
    """
    Genera un borrador de respuesta para un email urgente/para Marta.
    Usa mas contexto y un prompt especifico para redaccion.
    """
    try:
        prompt = f"""Redacta un borrador de respuesta profesional para este email.
El borrador es para que Marta (jefa del departamento) lo revise y envie.
Debe ser conciso, profesional y en espanol.

EMAIL ORIGINAL:
De: {email_data.get('remitente', '')}
Asunto: {email_data.get('asunto', '')}
Cuerpo:
{email_data.get('cuerpo', '')[:2000]}

{f'CONTEXTO ADICIONAL DE REDMINE:{chr(10)}{contexto_redmine}' if contexto_redmine else ''}

Escribe SOLO el texto del borrador, sin saludos tipo "Estimado" generico.
Usa un tono profesional pero directo. Firma como "Marta"."""

        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 800,
            "system": "Eres un asistente que redacta emails profesionales concisos en espanol.",
            "messages": [{"role": "user", "content": prompt}]
        })

        response = bedrock.invoke_model(
            modelId=MODEL_ID,
            body=body,
            contentType="application/json",
            accept="application/json"
        )

        result = json.loads(response["body"].read())
        return result["content"][0]["text"].strip()

    except Exception as e:
        logger.error(f"Error generando draft: {e}")
        return ""


def responder_pregunta(pregunta: str, contexto_emails: str, contexto_redmine: str = "") -> str:
    """
    Responde una pregunta de Marta sobre las incidencias.
    Usado por el bot de Telegram.
    """
    try:
        prompt = f"""Marta te hace esta pregunta sobre las incidencias:

PREGUNTA: {pregunta}

CONTEXTO (emails recientes clasificados):
{contexto_emails[:4000]}

{f'CONTEXTO REDMINE:{chr(10)}{contexto_redmine[:2000]}' if contexto_redmine else ''}

Responde de forma clara y concisa en espanol. Si no tienes informacion
suficiente para responder, dilo honestamente."""

        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1000,
            "system": "Eres Gaston, asistente de Marta para gestionar incidencias de Redmine. Respondes de forma concisa y util.",
            "messages": [{"role": "user", "content": prompt}]
        })

        response = bedrock.invoke_model(
            modelId=MODEL_ID,
            body=body,
            contentType="application/json",
            accept="application/json"
        )

        result = json.loads(response["body"].read())
        return result["content"][0]["text"].strip()

    except Exception as e:
        logger.error(f"Error respondiendo pregunta: {e}")
        return "Lo siento, hubo un error procesando tu pregunta. Intentalo de nuevo."


def _parse_response(text: str) -> dict:
    """Parsea la respuesta JSON de Claude."""
    try:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except json.JSONDecodeError:
        logger.error(f"Claude no devolvio JSON valido: {text[:200]}")
        return _fallback_error("JSON invalido en respuesta de Claude")


def _fallback_error(motivo: str) -> dict:
    return {
        "clasificacion": "DUDOSO",
        "proyecto": "N/A",
        "numero_incidencia": "N/A",
        "prioridad_redmine": "N/A",
        "asignado_a": "N/A",
        "remitente_tipo": "DESCONOCIDO",
        "resumen": f"Error al clasificar: {motivo[:100]}",
        "motivo_clasificacion": "Error en el procesamiento",
        "requiere_respuesta": False,
        "draft_sugerido": ""
    }
