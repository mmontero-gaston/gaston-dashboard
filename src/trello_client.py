"""
Gaston - Cliente Trello.

Permite mover tarjetas entre listas por numero de incidencia.
Solo actua cuando Marta lo pide explicitamente via Telegram.
"""

import json
import logging
import os
import urllib.request
import urllib.parse
from typing import Optional

logger = logging.getLogger(__name__)

TRELLO_API_KEY = os.environ.get("GASTON_TRELLO_API_KEY", "")
TRELLO_TOKEN = os.environ.get("GASTON_TRELLO_TOKEN", "")

# ============= TABLEROS PRINCIPALES (Shere Khan) =============

TABLEROS_PRINCIPALES = {
    "PRE": "624d6d9df846ca3a684c40a6",
    "PRO": "6686854359ad8ded89fe9f3a",
    "NEGOCIO": "68c14daa83a5798b2785a26f",
}

# Tableros secundarios
TABLEROS_SECUNDARIOS = {
    "SMEE": "66968179999a6c4ee5244187",
    "DESARROLLO_NEGOCIO": "61db2fe6e347d17c1d4c910c",
}

TODOS_LOS_TABLEROS = {**TABLEROS_PRINCIPALES, **TABLEROS_SECUNDARIOS}

# ============= LISTAS POR TABLERO =============

LISTAS = {
    # SHERE KHAN - PRE
    "624d6d9df846ca3a684c40a6": {
        "BACKLOG NUEVAS": "666c366c893096291dbdf7a2",
        "BACKLOG ERRORES": "68188664da1d56b5cb730c80",
        "EN PROCESO CRIS": "67091089d5e7b733e09abf9e",
        "EN PROCESO SALVA": "6709109fa420972d5a5b2e44",
        "EN PROCESO LUCAS": "670910aac8a25ac497f34508",
        "EN PROCESO GUMER": "67091096f8a540b821370e8c",
        "EN PROCESO PAOLA": "6925786b0a5a21eb4e061385",
        "EN PROCESO BORJA": "69298d1c585348c8794fa32f",
        "EN PROCESO SARA": "670910ba972c54362d25d379",
        "PDTE SUBIDA BACK": "666fea33195ddcc68e533ec1",
        "PDTE SUBIDA FRONT": "666fea5bdb6c2bd2c5bf45f2",
        "PDTE PROBAR NEGOCIO": "666fed19ecb1797bf4bd421a",
        "PROBADO CON ERRORES": "666fed250d629a87490273e3",
    },
    # SHERE KHAN - PRO
    "6686854359ad8ded89fe9f3a": {
        "PDTE SUBIDA BACK": "66868c4682f863e3f7cccc37",
        "PDTE SUBIDA FRONT": "66868c4ce37bd79228ee6c01",
        "PDTE PRUEBAS NEGOCIO": "6686b07080685636b04211b4",
        "PROBADO KO": "66fae8bbae408377a59858a2",
        "PROBADO OK": "66868c5593e51b0077bf08c1",
    },
    # SHERE KHAN - NEGOCIO
    "68c14daa83a5798b2785a26f": {
        "PENDIENTES CAMILO": "68c14fb1792465034a862d76",
        "EN PROCESO CAMILO": "68c1607ea8e9e2707cfcb605",
        "UTILIDADES": "68fb95861f4cc7d99e8bad24",
        "PENDIENTES GENERAL": "68c158d0fb798aa2bd868c89",
        "PENDIENTES LOGIN": "6984abbac0767493fa134d17",
        "PENDIENTES MOSSAD": "68d6537334d3ed7f008b04f1",
        "PENDIENTES EMISOR": "68c2a344b62ce42667032e81",
        "PENDIENTES BENEFICIARIO": "68c19f9a601a2de487653829",
        "PENDIENTES ENVIO": "68c40ff37e66a333d3d3dda8",
        "PENDIENTE CUBO": "68d6a37aba61cac0033c6011",
        "PENDIENTES ACTIVIDAD": "68d15a1ea0897a7443664bb8",
        "PENDIENTES CAJA CHICA": "68d247e0c2e75ef15274fc13",
        "PENDIENTES PRECIOS": "69c10763df5f011bca810c0b",
        "PENDIENTES CONFIGURACION": "6925958488025275a8e0177c",
        "PENDIENTES DOCUMENTACION": "68daa0cc362e583c9358c1a2",
        "PENDIENTES USUARIO": "69bc1b885474e2517f2fe21d",
        "INCIDENCIAS ABANDONADAS": "68dd41875fe8926fa6fcbfef",
        "DESARROLLOS ABANDONADOS": "69c0fa388d26e45dfe6cd8a7",
        "INCIDENCIAS EN DUDA": "69c11b6a15b3bee72b2ef63c",
    },
    # SMEE
    "66968179999a6c4ee5244187": {
        "REUNIONES": "688a35d6b346f41e9e233db4",
        "BACKLOG": "669681a5f1a91274ae3b73e5",
        "EN PROCESO BACK": "686eab6bc8249fa614900caf",
        "EN PROCESO FRONT": "6696827173c063b22ce7bca9",
        "PDTE SUBIDA BACK PRE": "6696828223d4974725303aff",
        "PDTE SUBIDA FRONT PRE": "66c6f3f6c8c7785dc592e82d",
        "PDTE PRUEBAS NEGOCIO": "66c6f3e95af819b73e392ff3",
        "PDTE SUBIDA BACK PRO": "686560cfa24128fca30077c7",
        "PDTE SUBIDA FRONT PRO": "686560d6878ac5f678da21b4",
        "PDTE PRUEBAS NEGOCIO PRO": "686560df0de3355db301e3b2",
        "PROBADO OK": "687624abdc4521ea9e86f148",
    },
    # DESARROLLO DE NEGOCIO
    "61db2fe6e347d17c1d4c910c": {
        "IDEAS BACKLOG": "61db30a9d9116b8c76565579",
        "EN DEFINICION": "61db30eff072428172f1b98d",
        "DESARROLLO": "61db30fac907224e6d399eb7",
        "BLOQUEADO": "6697ab9b07e39ecea4e84696",
        "PRUEBAS": "61db3104d44a9a69db698037",
        "PRODUCCION": "61db31153dbf6d568ff2494b",
    },
}

# Alias comunes para que Marta pueda escribir de forma natural
ALIAS_LISTAS = {
    "BACKLOG": "BACKLOG ERRORES",
    "NUEVAS": "BACKLOG NUEVAS",
    "ERRORES": "BACKLOG ERRORES",
    "PROBAR": "PDTE PROBAR NEGOCIO",
    "PROBAR NEGOCIO": "PDTE PROBAR NEGOCIO",
    "PRUEBAS": "PDTE PROBAR NEGOCIO",
    "PRUEBAS NEGOCIO": "PDTE PRUEBAS NEGOCIO",
    "SUBIDA BACK": "PDTE SUBIDA BACK",
    "SUBIDA FRONT": "PDTE SUBIDA FRONT",
    "PROBADO OK": "PROBADO OK",
    "PROBADO KO": "PROBADO KO",
    "OK": "PROBADO OK",
    "KO": "PROBADO KO",
    "ERRORES": "PROBADO CON ERRORES",
    "CON ERRORES": "PROBADO CON ERRORES",
    "ABANDONADA": "INCIDENCIAS ABANDONADAS",
    "DUDA": "INCIDENCIAS EN DUDA",
}

ALIAS_TABLEROS = {
    "PRE": "PRE",
    "PREPRODUCCION": "PRE",
    "PREPRODUCCIÓN": "PRE",
    "SHERE KHAN PRE": "PRE",
    "SK PRE": "PRE",
    "PRO": "PRO",
    "PRODUCCION": "PRO",
    "PRODUCCIÓN": "PRO",
    "SHERE KHAN PRO": "PRO",
    "SK PRO": "PRO",
    "NEGOCIO": "NEGOCIO",
    "SHERE KHAN NEGOCIO": "NEGOCIO",
    "SK NEGOCIO": "NEGOCIO",
    "SMEE": "SMEE",
    "DESARROLLO": "DESARROLLO_NEGOCIO",
}


# ============= API =============

def _request(method: str, endpoint: str, params: dict = None) -> Optional[dict]:
    """Hace una peticion a la API de Trello."""
    if not TRELLO_API_KEY or not TRELLO_TOKEN:
        logger.warning("Trello no configurado (GASTON_TRELLO_API_KEY o GASTON_TRELLO_TOKEN vacios)")
        return None

    base_url = f"https://api.trello.com/1/{endpoint}"
    query_params = {"key": TRELLO_API_KEY, "token": TRELLO_TOKEN}
    if params:
        query_params.update(params)

    url = f"{base_url}?{urllib.parse.urlencode(query_params)}"

    req = urllib.request.Request(url, method=method)
    if method == "PUT":
        req.add_header("Content-Type", "application/json")
        req.data = b""

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"Error Trello API {endpoint}: {e}")
        return None


# ============= BUSCAR TARJETAS =============

def buscar_tarjeta(numero_incidencia: str, tablero_id: str = None) -> Optional[dict]:
    """
    Busca una tarjeta por numero de incidencia (#XXXXX) en el nombre.
    Si tablero_id se especifica, busca solo en ese tablero.
    Si no, busca en todos los tableros principales primero, luego secundarios.
    """
    numero_limpio = numero_incidencia.replace("#", "").strip()

    tableros_a_buscar = []
    if tablero_id:
        tableros_a_buscar = [tablero_id]
    else:
        # Principales primero
        tableros_a_buscar = list(TABLEROS_PRINCIPALES.values()) + list(TABLEROS_SECUNDARIOS.values())

    for board_id in tableros_a_buscar:
        cards = _request("GET", f"boards/{board_id}/cards", {"fields": "name,idList,url"})
        if not cards:
            continue

        for card in cards:
            # Buscar el numero en el nombre de la tarjeta
            if f"#{numero_limpio}" in card.get("name", "") or numero_limpio in card.get("name", ""):
                # Obtener nombre del tablero y lista actual
                board_name = _get_board_name(board_id)
                list_name = _get_list_name(card.get("idList", ""), board_id)
                return {
                    "card_id": card["id"],
                    "name": card["name"],
                    "board_id": board_id,
                    "board_name": board_name,
                    "list_id": card["idList"],
                    "list_name": list_name,
                    "url": card.get("url", ""),
                }

    return None


def mover_tarjeta(card_id: str, lista_destino_id: str) -> bool:
    """Mueve una tarjeta a otra lista."""
    result = _request("PUT", f"cards/{card_id}", {"idList": lista_destino_id})
    return result is not None


# ============= RESOLVER NOMBRES =============

def resolver_tablero(nombre: str) -> Optional[str]:
    """Resuelve el nombre de un tablero a su ID."""
    nombre_upper = nombre.strip().upper()

    # Buscar en alias
    if nombre_upper in ALIAS_TABLEROS:
        key = ALIAS_TABLEROS[nombre_upper]
        return TODOS_LOS_TABLEROS.get(key)

    # Buscar directo
    if nombre_upper in TODOS_LOS_TABLEROS:
        return TODOS_LOS_TABLEROS[nombre_upper]

    return None


def resolver_lista(nombre: str, tablero_id: str) -> Optional[str]:
    """Resuelve el nombre de una lista a su ID dentro de un tablero."""
    nombre_upper = nombre.strip().upper()

    listas_tablero = LISTAS.get(tablero_id, {})

    # Buscar en alias primero
    nombre_resuelto = ALIAS_LISTAS.get(nombre_upper, nombre_upper)

    # Buscar exacto
    if nombre_resuelto in listas_tablero:
        return listas_tablero[nombre_resuelto]

    # Buscar parcial (contiene)
    for lista_nombre, lista_id in listas_tablero.items():
        if nombre_upper in lista_nombre or lista_nombre in nombre_upper:
            return lista_id

    # Buscar con alias resuelto parcial
    for lista_nombre, lista_id in listas_tablero.items():
        if nombre_resuelto in lista_nombre or lista_nombre in nombre_resuelto:
            return lista_id

    return None


def listar_listas_tablero(tablero_id: str) -> list[str]:
    """Devuelve los nombres de las listas de un tablero."""
    return list(LISTAS.get(tablero_id, {}).keys())


# ============= HELPERS =============

def _get_board_name(board_id: str) -> str:
    """Devuelve el nombre legible del tablero."""
    for name, bid in TODOS_LOS_TABLEROS.items():
        if bid == board_id:
            return f"SHERE KHAN - {name}" if name in ("PRE", "PRO", "NEGOCIO") else name
    return "Desconocido"


def _get_list_name(list_id: str, board_id: str) -> str:
    """Devuelve el nombre legible de una lista."""
    listas = LISTAS.get(board_id, {})
    for name, lid in listas.items():
        if lid == list_id:
            return name
    return "Desconocida"


# ============= FUNCION PRINCIPAL PARA GASTON =============

def procesar_comando_trello(texto: str) -> str:
    """
    Procesa un comando de Marta para mover tarjetas en Trello.
    Ejemplo: "mueve #61873 y #62311 a Pdte Probar Negocio en PRE"

    Retorna un mensaje de respuesta para Telegram.
    """
    import re

    # Extraer numeros de incidencia
    numeros = re.findall(r"#(\d+)", texto)
    if not numeros:
        return "No encontre numeros de incidencia en tu mensaje. Usa el formato #XXXXX."

    # Extraer tablero (buscar "en PRE", "en PRO", "en NEGOCIO", etc.)
    tablero_match = re.search(r"(?:en|de|del?)\s+(PRE|PRO|NEGOCIO|SMEE|PREPRODUCCION|PRODUCCION)", texto, re.IGNORECASE)
    tablero_id = None
    tablero_nombre = ""
    if tablero_match:
        tablero_key = ALIAS_TABLEROS.get(tablero_match.group(1).upper(), tablero_match.group(1).upper())
        tablero_id = TODOS_LOS_TABLEROS.get(tablero_key)
        tablero_nombre = tablero_key

    # Extraer lista destino (buscar "a XXXX")
    lista_match = re.search(r"(?:a|al?|hacia)\s+(.+?)(?:\s+en\s+|\s*$)", texto, re.IGNORECASE)
    if not lista_match:
        return "No entendi a que lista quieres mover las tarjetas. Ejemplo: 'mueve #61873 a Pdte Probar Negocio en PRE'"

    lista_nombre = lista_match.group(1).strip()

    # Procesar cada tarjeta
    resultados = []
    errores = []

    for numero in numeros:
        # Buscar tarjeta
        tarjeta = buscar_tarjeta(numero, tablero_id)
        if not tarjeta:
            errores.append(f"#{numero}: no encontrada en Trello")
            continue

        # Si no se especifico tablero, usar el del tablero donde esta la tarjeta
        board_id = tablero_id or tarjeta["board_id"]

        # Resolver lista destino
        lista_id = resolver_lista(lista_nombre, board_id)
        if not lista_id:
            listas_disponibles = listar_listas_tablero(board_id)
            errores.append(
                f"#{numero}: no encontre la lista '{lista_nombre}' en {_get_board_name(board_id)}.\n"
                f"Listas disponibles: {', '.join(listas_disponibles[:8])}"
            )
            continue

        # Mover
        ok = mover_tarjeta(tarjeta["card_id"], lista_id)
        if ok:
            lista_destino_nombre = _get_list_name(lista_id, board_id)
            resultados.append(
                f"#{numero} -> {lista_destino_nombre} ({_get_board_name(board_id)})"
            )
        else:
            errores.append(f"#{numero}: error al mover en Trello")

    # Construir respuesta
    respuesta = ""
    if resultados:
        respuesta += "Movidas:\n" + "\n".join(f"  {r}" for r in resultados)
    if errores:
        if respuesta:
            respuesta += "\n\n"
        respuesta += "Errores:\n" + "\n".join(f"  {e}" for e in errores)

    return respuesta or "No pude procesar el comando."
