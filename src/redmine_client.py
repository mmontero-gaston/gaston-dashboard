"""
Gaston - Cliente Redmine (read-only).

Consulta incidencias para dar contexto a Gaston cuando:
- Clasifica emails (enriquece la clasificacion)
- Marta hace preguntas desde Telegram
- Se generan drafts de respuesta

NUNCA modifica, cierra ni reasigna incidencias.
"""

import json
import logging
import os
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

REDMINE_URL = os.environ.get("GASTON_REDMINE_URL", "")
REDMINE_API_KEY = os.environ.get("GASTON_REDMINE_API_KEY", "")


def _request(endpoint: str, params: dict = None) -> Optional[dict]:
    """Hace una peticion GET a la API de Redmine."""
    if not REDMINE_URL or not REDMINE_API_KEY:
        logger.warning("Redmine no configurado (GASTON_REDMINE_URL o GASTON_REDMINE_API_KEY vacios)")
        return None

    url = f"{REDMINE_URL.rstrip('/')}/{endpoint}.json"
    if params:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url += f"?{query}"

    req = urllib.request.Request(url, headers={
        "X-Redmine-API-Key": REDMINE_API_KEY,
        "Content-Type": "application/json"
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"Error consultando Redmine {endpoint}: {e}")
        return None


# ============= CONSULTAS DE INCIDENCIAS =============

def get_incidencia(numero: str) -> Optional[dict]:
    """
    Obtiene el detalle completo de una incidencia por su numero.
    Incluye: estado, prioridad, asignado, descripcion, journals (historial).
    """
    numero_limpio = numero.replace("#", "").strip()
    if not numero_limpio.isdigit():
        return None

    data = _request(f"issues/{numero_limpio}", {"include": "journals"})
    if not data or "issue" not in data:
        return None

    issue = data["issue"]
    return {
        "id": issue.get("id"),
        "proyecto": issue.get("project", {}).get("name", "N/A"),
        "tracker": issue.get("tracker", {}).get("name", "N/A"),
        "estado": issue.get("status", {}).get("name", "N/A"),
        "prioridad": issue.get("priority", {}).get("name", "N/A"),
        "asignado_a": issue.get("assigned_to", {}).get("name", "Sin asignar"),
        "autor": issue.get("author", {}).get("name", "N/A"),
        "asunto": issue.get("subject", ""),
        "descripcion": issue.get("description", "")[:1000],
        "creado": issue.get("created_on", ""),
        "actualizado": issue.get("updated_on", ""),
        "historial": _extraer_historial(issue.get("journals", [])),
    }


def get_incidencias_proyecto(proyecto: str, estado: str = "", limit: int = 20) -> list[dict]:
    """
    Lista incidencias de un proyecto. Filtra opcionalmente por estado.
    """
    params = {"project_id": proyecto, "limit": str(limit), "sort": "updated_on:desc"}

    # Mapear nombre de estado a ID (los IDs pueden variar por instalacion)
    if estado:
        params["status_id"] = _estado_a_filtro(estado)

    data = _request("issues", params)
    if not data:
        return []

    return [
        {
            "id": i.get("id"),
            "asunto": i.get("subject", ""),
            "estado": i.get("status", {}).get("name", "N/A"),
            "prioridad": i.get("priority", {}).get("name", "N/A"),
            "asignado_a": i.get("assigned_to", {}).get("name", "Sin asignar"),
            "actualizado": i.get("updated_on", ""),
        }
        for i in data.get("issues", [])
    ]


def get_incidencias_asignadas_a(nombre: str, limit: int = 20) -> list[dict]:
    """Lista incidencias asignadas a una persona (por nombre)."""
    params = {
        "assigned_to_id": "me" if nombre.lower() == "marta" else nombre,
        "limit": str(limit),
        "sort": "updated_on:desc",
        "status_id": "open"
    }

    data = _request("issues", params)
    if not data:
        return []

    return [
        {
            "id": i.get("id"),
            "proyecto": i.get("project", {}).get("name", "N/A"),
            "asunto": i.get("subject", ""),
            "estado": i.get("status", {}).get("name", "N/A"),
            "prioridad": i.get("priority", {}).get("name", "N/A"),
            "actualizado": i.get("updated_on", ""),
        }
        for i in data.get("issues", [])
    ]


def buscar_incidencias(texto: str, limit: int = 10) -> list[dict]:
    """Busca incidencias por texto libre."""
    data = _request("search", {
        "q": texto,
        "limit": str(limit),
        "issues": "1"
    })
    if not data:
        return []

    return [
        {"id": r.get("id"), "titulo": r.get("title", ""), "descripcion": r.get("description", "")[:200]}
        for r in data.get("results", [])
    ]


# ============= CONTEXTO PARA GASTON =============

def obtener_contexto_incidencia(numero: str) -> str:
    """
    Obtiene un resumen en texto de una incidencia para inyectar
    como contexto al clasificador o al generador de drafts.
    """
    incidencia = get_incidencia(numero)
    if not incidencia:
        return ""

    lineas = [
        f"Incidencia #{incidencia['id']} - {incidencia['asunto']}",
        f"Proyecto: {incidencia['proyecto']}",
        f"Estado: {incidencia['estado']} | Prioridad: {incidencia['prioridad']}",
        f"Asignado a: {incidencia['asignado_a']} | Autor: {incidencia['autor']}",
        f"Creado: {incidencia['creado']} | Actualizado: {incidencia['actualizado']}",
    ]

    if incidencia["descripcion"]:
        lineas.append(f"Descripcion: {incidencia['descripcion'][:500]}")

    if incidencia["historial"]:
        lineas.append("Ultimas actualizaciones:")
        for h in incidencia["historial"][-5:]:
            lineas.append(f"  - {h}")

    return "\n".join(lineas)


def obtener_resumen_proyectos() -> str:
    """
    Resumen rapido de los proyectos principales para contexto de Telegram.
    """
    proyectos_principales = ["sherekhan-back", "sherekhan-front", "smee", "negocio"]
    lineas = []

    for proyecto in proyectos_principales:
        incidencias = get_incidencias_proyecto(proyecto, limit=5)
        if incidencias:
            abiertas = len(incidencias)
            lineas.append(f"{proyecto.upper()}: {abiertas} incidencias recientes")
            for i in incidencias[:3]:
                lineas.append(f"  #{i['id']} [{i['estado']}] {i['asunto'][:60]}")

    return "\n".join(lineas) if lineas else "No se pudo consultar Redmine."


# ============= HELPERS =============

def _extraer_historial(journals: list) -> list[str]:
    """Extrae notas legibles del historial de una incidencia."""
    historial = []
    for j in journals:
        notas = j.get("notes", "").strip()
        if notas:
            usuario = j.get("user", {}).get("name", "?")
            fecha = j.get("created_on", "")[:10]
            historial.append(f"[{fecha}] {usuario}: {notas[:150]}")

        for detalle in j.get("details", []):
            if detalle.get("name") == "status_id":
                usuario = j.get("user", {}).get("name", "?")
                fecha = j.get("created_on", "")[:10]
                historial.append(f"[{fecha}] {usuario} cambio estado: {detalle.get('old_value')} -> {detalle.get('new_value')}")

    return historial


def _estado_a_filtro(estado: str) -> str:
    """Convierte nombre de estado a filtro de Redmine API."""
    estado_lower = estado.lower()
    if estado_lower in ("abierta", "abierto", "open"):
        return "open"
    elif estado_lower in ("cerrada", "cerrado", "closed"):
        return "closed"
    else:
        return "*"  # todos
