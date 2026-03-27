import boto3
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

TABLE_NAME = "gaston_emails"
REGION = "eu-west-1"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)

EMPTY_VALUES = ("", "#", "N/A", "No identificado", "No identificada", "No especificado", "no identificado", "no especificado", "No aplica")

def _clean_index_val(val):
    """DynamoDB no permite strings vacios en claves de indice secundario."""
    if not val or val.strip() in EMPTY_VALUES:
        return "N/A"
    return val.strip()


def guardar_email(email_data: dict, clasificacion: dict) -> bool:
    """
    Guarda un email clasificado en DynamoDB.
    PK: email_id | SK: timestamp
    """
    try:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        item = {
            # Claves
            "email_id": email_data["email_id"],
            "timestamp": timestamp,

            # Datos originales del email
            "remitente": email_data.get("remitente", ""),
            "destinatario": email_data.get("destinatario", ""),
            "asunto": email_data.get("asunto", ""),
            "fecha_email": email_data.get("fecha", ""),

            # Datos extraidos por Gaston (clasificador)
            "clasificacion": clasificacion.get("clasificacion", "DUDOSO"),
            "proyecto": _clean_index_val(clasificacion.get("proyecto", "N/A")),
            "numero_incidencia": _clean_index_val(clasificacion.get("numero_incidencia", "N/A")),
            "prioridad_redmine": clasificacion.get("prioridad_redmine", "N/A"),
            "asignado_a": clasificacion.get("asignado_a", "N/A"),
            "remitente_tipo": clasificacion.get("remitente_tipo", "DESCONOCIDO"),
            "resumen": clasificacion.get("resumen", ""),
            "motivo_clasificacion": clasificacion.get("motivo_clasificacion", ""),
            "requiere_respuesta": clasificacion.get("requiere_respuesta", False),

            # Metadata
            "es_redmine": bool(re.search(r"#\d{3,}", email_data.get("asunto", ""))),
            "estado_redmine": clasificacion.get("estado_redmine", "N/A"),

            # Estado de acciones de Gaston
            "accion_realizada": "",  # MOVIDO_NO_URGENTE, DRAFT_CREADO, MARCADO_LEIDO
            "draft_id": "",
        }

        table.put_item(Item=item)
        logger.info(
            f"Guardado: {email_data['email_id']} | "
            f"{clasificacion.get('clasificacion')} | "
            f"{clasificacion.get('resumen', '')[:60]}"
        )
        return True

    except Exception as e:
        logger.error(f"Error guardando en DynamoDB: {e}")
        return False


def email_ya_procesado(email_id: str) -> bool:
    """Verifica si un email ya fue procesado. Evita duplicados y gasto en Bedrock."""
    try:
        response = table.query(
            KeyConditionExpression="email_id = :eid",
            ExpressionAttributeValues={":eid": email_id},
            Limit=1
        )
        return len(response.get("Items", [])) > 0
    except Exception as e:
        logger.error(f"Error verificando duplicado {email_id}: {e}")
        return False


def actualizar_accion(email_id: str, timestamp: str, accion: str,
                      draft_id: str = "") -> bool:
    """Actualiza la accion realizada sobre un email."""
    try:
        update_expr = "SET accion_realizada = :accion"
        expr_values = {":accion": accion}

        if draft_id:
            update_expr += ", draft_id = :draft_id"
            expr_values[":draft_id"] = draft_id

        table.update_item(
            Key={"email_id": email_id, "timestamp": timestamp},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values,
        )
        return True
    except Exception as e:
        logger.error(f"Error actualizando accion: {e}")
        return False


def consultar_por_proyecto(proyecto: str) -> list[dict]:
    """Consulta emails de un proyecto especifico."""
    try:
        response = table.query(
            IndexName="gaston_proyecto_index",
            KeyConditionExpression="proyecto = :p",
            ExpressionAttributeValues={":p": proyecto},
            ScanIndexForward=False,
            Limit=20
        )
        return response.get("Items", [])
    except Exception as e:
        logger.error(f"Error consultando proyecto {proyecto}: {e}")
        return []


def consultar_por_incidencia(numero: str) -> list[dict]:
    """Consulta emails de una incidencia especifica."""
    try:
        response = table.query(
            IndexName="gaston_incidencia_index",
            KeyConditionExpression="numero_incidencia = :n",
            ExpressionAttributeValues={":n": numero},
            ScanIndexForward=False,
            Limit=10
        )
        return response.get("Items", [])
    except Exception as e:
        logger.error(f"Error consultando incidencia {numero}: {e}")
        return []


def resumen_del_dia() -> list[dict]:
    """Devuelve todos los emails procesados hoy."""
    try:
        hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        response = table.scan(
            FilterExpression="begins_with(#ts, :hoy) AND email_id <> :state",
            ExpressionAttributeNames={"#ts": "timestamp"},
            ExpressionAttributeValues={":hoy": hoy, ":state": "_STATE_"}
        )
        items = response.get("Items", [])
        items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return items

    except Exception as e:
        logger.error(f"Error obteniendo resumen del dia: {e}")
        return []


def resumen_ultimas_24h() -> list[dict]:
    """Devuelve emails de las ultimas 24 horas. Usado para el resumen de Telegram."""
    try:
        hace_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")

        response = table.scan(
            FilterExpression="#ts >= :desde AND email_id <> :state",
            ExpressionAttributeNames={"#ts": "timestamp"},
            ExpressionAttributeValues={":desde": hace_24h, ":state": "_STATE_"}
        )
        items = response.get("Items", [])
        items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return items

    except Exception as e:
        logger.error(f"Error obteniendo ultimas 24h: {e}")
        return []


def get_todos_emails() -> list[dict]:
    """Escanea todos los emails (para el dashboard). Paginado completo."""
    try:
        items = []
        response = table.scan()
        items.extend(response.get("Items", []))
        while "LastEvaluatedKey" in response:
            response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))
        items = [i for i in items if i.get("email_id") != "_STATE_"]
        items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return items
    except Exception as e:
        logger.error(f"Error escaneando DynamoDB: {e}")
        return []


# ============= STATE MANAGEMENT =============

def get_last_history_id() -> Optional[str]:
    """Recupera el ultimo historyId procesado."""
    try:
        response = table.get_item(
            Key={"email_id": "_STATE_", "timestamp": "last_history_id"}
        )
        item = response.get("Item")
        return item.get("value") if item else None
    except Exception as e:
        logger.error(f"Error leyendo last_history_id: {e}")
        return None


def save_history_id(history_id: str) -> bool:
    """Guarda el ultimo historyId procesado."""
    try:
        table.put_item(Item={
            "email_id": "_STATE_",
            "timestamp": "last_history_id",
            "value": history_id,
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        })
        return True
    except Exception as e:
        logger.error(f"Error guardando history_id: {e}")
        return False
