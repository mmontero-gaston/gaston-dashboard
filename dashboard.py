import streamlit as st
import boto3
import pandas as pd
import base64
import os
from datetime import datetime, timezone, timedelta, date
from collections import defaultdict
import time

# ============= CONFIG =============
TABLE_NAME = "gaston_emails"
REGION = "eu-west-1"
AUTO_REFRESH_SECONDS = 30
LOGO_PATH = os.path.join(os.path.dirname(__file__), "Gaston.png")

# ============= AWS =============
@st.cache_resource
def get_table():
    # Si hay secrets de Streamlit Cloud, usarlos
    if hasattr(st, "secrets") and "aws" in st.secrets:
        session = boto3.Session(
            aws_access_key_id=st.secrets["aws"]["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=st.secrets["aws"]["AWS_SECRET_ACCESS_KEY"],
            region_name=st.secrets["aws"].get("AWS_DEFAULT_REGION", REGION)
        )
        dynamodb = session.resource("dynamodb", region_name=REGION)
    else:
        dynamodb = boto3.resource("dynamodb", region_name=REGION)
    return dynamodb.Table(TABLE_NAME)


def get_logo_base64():
    try:
        with open(LOGO_PATH, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except Exception:
        return ""


def get_emails() -> list[dict]:
    try:
        table = get_table()
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
        st.error(f"Error conectando con DynamoDB: {e}")
        return []


def agrupar_por_proyecto(emails):
    proyectos = defaultdict(list)
    for e in emails:
        proyectos[e.get("proyecto", "N/A")].append(e)
    for k in proyectos:
        proyectos[k].sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return dict(proyectos)


def agrupar_por_incidencia(emails):
    incidencias = defaultdict(list)
    for e in emails:
        incidencias[e.get("numero_incidencia", "N/A")].append(e)
    for k in incidencias:
        incidencias[k].sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return dict(incidencias)


def parse_fecha(ts_str):
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).date()
    except Exception:
        return None


def filtrar_por_rango(emails, fecha_inicio, fecha_fin):
    resultado = []
    for e in emails:
        f = parse_fecha(e.get("timestamp", ""))
        if f and fecha_inicio <= f <= fecha_fin:
            resultado.append(e)
    return resultado


# ============= PAGE CONFIG =============
st.set_page_config(
    page_title="Gaston - Gestor de Incidencias",
    page_icon="Gaston.png",
    layout="wide",
    initial_sidebar_state="expanded"
)

logo_b64 = get_logo_base64()

# ============= CSS =============
st.markdown(f"""
<style>
    .stApp {{ background: #fafafa; }}

    /* Sidebar */
    section[data-testid="stSidebar"] {{ background: #1a1a1a; }}
    section[data-testid="stSidebar"] * {{ color: #e0e0e0 !important; }}

    /* Toggle naranja */
    section[data-testid="stSidebar"] [data-testid="stToggle"] label span[data-checked] {{
        background-color: #FF6A00 !important;
    }}

    /* Slider - solo el thumb naranja, track sutil */
    section[data-testid="stSidebar"] [role="slider"] {{
        background: #FF6A00 !important;
    }}
    section[data-testid="stSidebar"] [data-testid="stSliderTrack"] > div:first-child {{
        background: #FF6A00 !important;
    }}

    /* Radio buttons sidebar - naranja cuando seleccionado */
    section[data-testid="stSidebar"] [role="radiogroup"] label[data-checked="true"] {{
        background: #FF6A00 !important;
        color: white !important;
        border-color: #FF6A00 !important;
    }}
    section[data-testid="stSidebar"] .stRadio label:hover {{
        border-color: #FF6A00 !important;
    }}

    /* Boton primario naranja */
    .stButton > button[kind="primary"],
    .stButton > button[data-testid="stBaseButton-primary"] {{
        background-color: #FF6A00 !important;
        border-color: #FF6A00 !important;
        color: white !important;
    }}
    .stButton > button[kind="primary"]:hover,
    .stButton > button[data-testid="stBaseButton-primary"]:hover {{
        background-color: #e55d00 !important;
        border-color: #e55d00 !important;
    }}

    /* Selectbox, multiselect, date_input - borde naranja on focus */
    .stSelectbox > div > div:focus-within,
    .stMultiSelect > div > div:focus-within,
    .stDateInput > div > div:focus-within,
    .stTextInput > div > div:focus-within {{
        border-color: #FF6A00 !important;
        box-shadow: 0 0 0 1px #FF6A00 !important;
    }}

    /* Multiselect tags naranja */
    .stMultiSelect [data-baseweb="tag"] {{
        background-color: #FF6A00 !important;
    }}

    /* Header */
    .gaston-header {{
        background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 50%, #FF6A00 150%);
        padding: 20px 28px; border-radius: 14px; color: white;
        margin-bottom: 24px; display: flex; align-items: center; gap: 20px;
        border-bottom: 3px solid #FF6A00;
    }}
    .gaston-header img {{ width: 60px; height: 60px; border-radius: 50%; border: 2px solid #FF6A00; }}
    .gaston-header .header-text h1 {{ margin: 0; color: white; font-size: 26px; font-weight: 700; }}
    .gaston-header .header-text p {{ margin: 2px 0 0; opacity: 0.6; font-size: 13px; }}

    /* Metric cards */
    .metric-row {{ display: flex; gap: 14px; margin-bottom: 24px; }}
    .metric-card {{
        flex: 1; background: white; border-radius: 12px; padding: 18px 22px;
        border-top: 4px solid #FF6A00; box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        transition: transform 0.2s;
    }}
    .metric-card:hover {{ transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
    .metric-card .value {{ font-size: 32px; font-weight: 800; color: #1a1a1a; }}
    .metric-card .label {{ font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 0.8px; margin-top: 2px; }}
    .mc-orange {{ border-top-color: #FF6A00; }}
    .mc-red    {{ border-top-color: #dc3545; }}
    .mc-amber  {{ border-top-color: #ffc107; }}
    .mc-green  {{ border-top-color: #28a745; }}
    .mc-blue   {{ border-top-color: #4a9eff; }}

    /* Pills */
    .pill {{
        display: inline-block; padding: 3px 14px; border-radius: 20px;
        font-size: 11px; font-weight: 700; color: white; letter-spacing: 0.3px;
    }}
    .pill-informativo {{ background: #6c757d; }}
    .pill-urgente     {{ background: #dc3545; }}
    .pill-para_marta  {{ background: #FF6A00; }}
    .pill-medio       {{ background: #ffc107; color: #333; }}
    .pill-dudoso      {{ background: #adb5bd; }}

    /* Alert rows */
    .urgente-row {{
        background: #fff5f5; border-left: 4px solid #dc3545;
        padding: 12px 16px; border-radius: 8px; margin-bottom: 8px;
    }}
    .marta-row {{
        background: #fff8f0; border-left: 4px solid #FF6A00;
        padding: 12px 16px; border-radius: 8px; margin-bottom: 8px;
    }}
    .medio-row {{
        background: #fffef5; border-left: 4px solid #ffc107;
        padding: 12px 16px; border-radius: 8px; margin-bottom: 8px;
    }}

    /* Incidencia card */
    .inc-card {{
        background: white; border-radius: 10px; padding: 14px 18px; margin-bottom: 10px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06); border-left: 4px solid #ddd;
    }}
    .inc-card.inc-urgente {{ border-left-color: #dc3545; }}
    .inc-card.inc-para_marta {{ border-left-color: #FF6A00; }}
    .inc-card.inc-medio {{ border-left-color: #ffc107; }}
    .inc-card.inc-informativo {{ border-left-color: #6c757d; }}
    .inc-card .inc-header {{ display: flex; justify-content: space-between; align-items: center; }}
    .inc-card .inc-num {{ font-weight: 700; font-size: 15px; color: #1a1a1a; }}
    .inc-card .inc-estado {{ font-size: 12px; color: #666; background: #f0f0f0; padding: 2px 10px; border-radius: 12px; }}
    .inc-card .inc-resumen {{ color: #555; font-size: 14px; margin-top: 6px; }}
    .inc-card .inc-meta {{ color: #999; font-size: 12px; margin-top: 6px; }}

    /* Timeline */
    .timeline-item {{
        border-left: 3px solid #FF6A00; padding: 10px 0 10px 18px; margin-left: 8px; position: relative;
    }}
    .timeline-item::before {{
        content: ""; position: absolute; left: -7px; top: 16px;
        width: 11px; height: 11px; border-radius: 50%; background: #FF6A00;
    }}
    .timeline-date {{ font-size: 11px; color: #999; }}
    .timeline-text {{ font-size: 14px; margin-top: 3px; }}

    /* Section titles */
    .section-title {{
        font-size: 18px; font-weight: 700; color: #1a1a1a;
        border-left: 4px solid #FF6A00; padding-left: 12px; margin: 24px 0 16px;
    }}

    /* Sidebar logo */
    .sidebar-logo {{ text-align: center; padding: 16px 0; }}
    .sidebar-logo img {{ width: 80px; height: 80px; border-radius: 50%; border: 3px solid #FF6A00; }}
    .sidebar-logo h3 {{ color: #FF6A00 !important; margin: 8px 0 0; font-size: 20px; }}
    .sidebar-logo p {{ color: #888 !important; font-size: 11px; margin: 2px 0 0; }}

    /* Stat box for project view */
    .stat-box {{
        background: white; border-radius: 10px; padding: 12px 16px; text-align: center;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06); border-top: 3px solid #FF6A00;
    }}
    .stat-box .stat-val {{ font-size: 24px; font-weight: 800; color: #1a1a1a; }}
    .stat-box .stat-lbl {{ font-size: 10px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }}

    /* Footer */
    .gaston-footer {{
        text-align: center; padding: 20px 0; margin-top: 30px;
        border-top: 1px solid #eee; color: #bbb; font-size: 12px;
    }}
</style>
""", unsafe_allow_html=True)

# ============= HEADER =============
st.markdown(f"""
<div class="gaston-header">
    <img src="data:image/png;base64,{logo_b64}" alt="Gaston">
    <div class="header-text">
        <h1>Gaston</h1>
        <p>Gestor inteligente de incidencias Redmine</p>
    </div>
</div>
""", unsafe_allow_html=True)

# ============= SIDEBAR =============
with st.sidebar:
    st.markdown(f"""
    <div class="sidebar-logo">
        <img src="data:image/png;base64,{logo_b64}" alt="Gaston">
        <h3>Gaston</h3>
        <p>Gestor de Incidencias</p>
    </div>
    """, unsafe_allow_html=True)

    st.divider()
    auto_refresh = st.toggle("Auto-refresh", value=True)
    refresh_interval = st.slider("Intervalo (seg)", 10, 120, AUTO_REFRESH_SECONDS)
    st.divider()

    if st.button("Refrescar", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    vista = st.radio(
        "Navegacion",
        ["Dashboard", "Por Proyecto", "Atencion Marta", "Todos los emails"],
        label_visibility="collapsed"
    )
    st.divider()
    st.caption(f"Ultima carga: {datetime.now().strftime('%H:%M:%S')}")

# ============= DATA =============
emails = get_emails()

if not emails:
    st.info("No hay emails procesados. Gaston esta esperando incidencias de Redmine.")
    if auto_refresh:
        time.sleep(refresh_interval)
        st.rerun()
    st.stop()

# Helpers
def fmt_ts(ts_str):
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return ts.strftime("%d/%m %H:%M")
    except Exception:
        return ts_str[:16] if ts_str else "-"

def fmt_ts_full(ts_str):
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return ts.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return ts_str or "-"

TIPO_PILL = {
    "INFORMATIVO": "pill-informativo",
    "URGENTE": "pill-urgente",
    "PARA_MARTA": "pill-para_marta",
    "MEDIO": "pill-medio",
    "DUDOSO": "pill-dudoso",
}
NA_VALUES = ("N/A", "No especificado", "No identificado", "No identificada", "No aplica", "no identificado", "no especificado")

def pill_html(tipo):
    css = TIPO_PILL.get(tipo, "pill-dudoso")
    return f'<span class="pill {css}">{tipo}</span>'

def clean_val(val):
    return "" if not val or val in NA_VALUES else val


# Datos globales
proyectos = agrupar_por_proyecto(emails)
proyectos_reales = {k: v for k, v in proyectos.items() if k not in NA_VALUES}
total_emails = len(emails)
urgentes = [e for e in emails if e.get("clasificacion") == "URGENTE"]
para_marta = [e for e in emails if e.get("clasificacion") == "PARA_MARTA"]
informativos = [e for e in emails if e.get("clasificacion") == "INFORMATIVO"]
medios = [e for e in emails if e.get("clasificacion") == "MEDIO"]
dudosos = [e for e in emails if e.get("clasificacion") == "DUDOSO"]

todas_fechas = [parse_fecha(e.get("timestamp", "")) for e in emails]
todas_fechas = [f for f in todas_fechas if f]
fecha_min = min(todas_fechas) if todas_fechas else date.today() - timedelta(days=7)
fecha_max = max(todas_fechas) if todas_fechas else date.today()
default_inicio = date.today() - timedelta(days=7)
default_fin = date.today()
# Asegurar que min_value no sea mayor que default_inicio
fecha_min_safe = min(fecha_min, default_inicio)


# ===================================================================
#                         DASHBOARD
# ===================================================================
if vista == "Dashboard":

    # Filtro de fechas - ultimos 7 dias por defecto
    col_date1, col_date2, _ = st.columns([1, 1, 2])
    with col_date1:
        d_inicio = st.date_input("Desde", value=default_inicio, min_value=fecha_min_safe, max_value=default_fin)
    with col_date2:
        d_fin = st.date_input("Hasta", value=default_fin, min_value=fecha_min_safe, max_value=default_fin)

    emails_rango = filtrar_por_rango(emails, d_inicio, d_fin)
    urg_rango = [e for e in emails_rango if e.get("clasificacion") == "URGENTE"]
    marta_rango = [e for e in emails_rango if e.get("clasificacion") == "PARA_MARTA"]
    info_rango = [e for e in emails_rango if e.get("clasificacion") == "INFORMATIVO"]
    hoy_str = date.today().isoformat()
    hoy_rango = [e for e in emails_rango if e.get("timestamp", "").startswith(hoy_str)]

    st.markdown(f"""
    <div class="metric-row">
        <div class="metric-card mc-orange">
            <div class="value">{len(emails_rango)}</div>
            <div class="label">En periodo</div>
        </div>
        <div class="metric-card mc-red">
            <div class="value">{len(urg_rango)}</div>
            <div class="label">Urgentes</div>
        </div>
        <div class="metric-card mc-amber">
            <div class="value">{len(marta_rango)}</div>
            <div class="label">Para Marta</div>
        </div>
        <div class="metric-card mc-green">
            <div class="value">{len(info_rango)}</div>
            <div class="label">Archivados</div>
        </div>
        <div class="metric-card mc-blue">
            <div class="value">{len(hoy_rango)}</div>
            <div class="label">Hoy</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_g1, col_g2 = st.columns([1, 1])

    with col_g1:
        st.markdown('<div class="section-title">Clasificacion</div>', unsafe_allow_html=True)
        conteos_rango = defaultdict(int)
        for e in emails_rango:
            conteos_rango[e.get("clasificacion", "DUDOSO")] += 1
        if conteos_rango:
            df_tipos = pd.DataFrame(
                [{"Tipo": k, "Cantidad": v} for k, v in conteos_rango.items() if v > 0]
            ).sort_values("Cantidad", ascending=True)
            st.bar_chart(df_tipos, x="Tipo", y="Cantidad", horizontal=True, color="#FF6A00")

    with col_g2:
        st.markdown('<div class="section-title">Evolucion diaria</div>', unsafe_allow_html=True)
        fecha_conteo = defaultdict(int)
        for e in emails_rango:
            dia = e.get("timestamp", "")[:10]
            if dia:
                fecha_conteo[dia] += 1
        if fecha_conteo:
            # Rellenar dias sin datos con 0 para linea continua
            all_days = []
            d = d_inicio
            while d <= d_fin:
                day_str = d.isoformat()
                all_days.append({"Fecha": day_str, "Emails": fecha_conteo.get(day_str, 0)})
                d += timedelta(days=1)
            df_dias = pd.DataFrame(all_days)
            st.line_chart(df_dias, x="Fecha", y="Emails", color="#FF6A00")
        else:
            st.caption("Sin datos en este rango")

    # Proyectos activos en el rango
    proy_rango = defaultdict(int)
    for e in emails_rango:
        p = clean_val(e.get("proyecto"))
        if p:
            proy_rango[p] += 1
    if proy_rango:
        st.markdown('<div class="section-title">Proyectos activos</div>', unsafe_allow_html=True)
        cols = st.columns(min(len(proy_rango), 5))
        for idx, (p, c) in enumerate(sorted(proy_rango.items(), key=lambda x: x[1], reverse=True)[:5]):
            with cols[idx]:
                st.markdown(f"""
                <div class="stat-box">
                    <div class="stat-val">{c}</div>
                    <div class="stat-lbl">{p}</div>
                </div>
                """, unsafe_allow_html=True)

    # Urgentes
    urg_rango_emails = [e for e in emails_rango if e.get("clasificacion") == "URGENTE"]
    if urg_rango_emails:
        st.markdown('<div class="section-title">Urgentes</div>', unsafe_allow_html=True)
        for e in urg_rango_emails[:5]:
            estado = clean_val(e.get("estado_redmine"))
            estado_html = f'<span class="inc-estado">{estado}</span>' if estado else ""
            st.markdown(f"""
            <div class="urgente-row">
                <strong>#{clean_val(e.get('numero_incidencia')) or '?'}</strong> {pill_html('URGENTE')}
                {estado_html}
                &nbsp;&middot;&nbsp; <em>{clean_val(e.get('proyecto')) or '?'}</em>
                &nbsp;&middot;&nbsp; <span style="color:#999; font-size:12px">{fmt_ts(e.get('timestamp', ''))}</span>
                <br><span style="color:#555; margin-top:4px; display:block">{e.get('resumen', '')[:120]}</span>
            </div>
            """, unsafe_allow_html=True)

    # Ultimos emails del rango
    st.markdown('<div class="section-title">Ultimos emails</div>', unsafe_allow_html=True)
    for e in emails_rango[:12]:
        tipo = e.get("clasificacion", "DUDOSO")
        estado = clean_val(e.get("estado_redmine"))
        estado_txt = f" [{estado}]" if estado else ""
        inc = clean_val(e.get("numero_incidencia"))
        inc_txt = f"**#{inc}**" if inc else ""
        proy = clean_val(e.get("proyecto"))
        proy_txt = f"_{proy}_" if proy else ""

        st.markdown(
            f"`{fmt_ts(e.get('timestamp',''))}` "
            f"{pill_html(tipo)} "
            f"{inc_txt}{estado_txt} "
            f"{proy_txt} - "
            f"{e.get('resumen', '')[:70]}",
            unsafe_allow_html=True
        )

    st.markdown('<div class="gaston-footer">Gaston v1.0 - Gestor de incidencias Redmine</div>', unsafe_allow_html=True)


# ===================================================================
#                         POR PROYECTO
# ===================================================================
elif vista == "Por Proyecto":
    st.markdown('<div class="section-title">Incidencias por proyecto</div>', unsafe_allow_html=True)

    if not proyectos_reales:
        st.info("No hay proyectos identificados.")
        st.stop()

    # Buscador + desplegable
    buscar_proy = st.text_input("Buscar proyecto", placeholder="Escribe para filtrar...")
    opciones = sorted(proyectos_reales.keys())
    if buscar_proy:
        opciones = [p for p in opciones if buscar_proy.lower() in p.lower()]

    if not opciones:
        st.warning(f"No se encontro ningun proyecto con '{buscar_proy}'")
        st.stop()

    proyecto_sel = st.selectbox("Proyecto", opciones, index=0, label_visibility="collapsed")

    if proyecto_sel and proyecto_sel in proyectos_reales:
        emails_proy = proyectos_reales[proyecto_sel]
        incidencias_proy = agrupar_por_incidencia(emails_proy)
        incidencias_proy = {k: v for k, v in incidencias_proy.items() if k not in NA_VALUES}

        # Metricas del proyecto
        urg_proy = len([e for e in emails_proy if e.get("clasificacion") in ("URGENTE", "PARA_MARTA")])
        cols = st.columns(4)
        with cols[0]:
            st.markdown(f'<div class="stat-box"><div class="stat-val">{len(emails_proy)}</div><div class="stat-lbl">Emails</div></div>', unsafe_allow_html=True)
        with cols[1]:
            st.markdown(f'<div class="stat-box"><div class="stat-val">{len(incidencias_proy)}</div><div class="stat-lbl">Incidencias</div></div>', unsafe_allow_html=True)
        with cols[2]:
            st.markdown(f'<div class="stat-box"><div class="stat-val">{urg_proy}</div><div class="stat-lbl">Requieren atencion</div></div>', unsafe_allow_html=True)
        with cols[3]:
            # Fecha mas reciente
            ultima = fmt_ts(emails_proy[0].get("timestamp", "")) if emails_proy else "-"
            st.markdown(f'<div class="stat-box"><div class="stat-val" style="font-size:16px">{ultima}</div><div class="stat-lbl">Ultima actividad</div></div>', unsafe_allow_html=True)

        st.markdown("")

        for inc_num, lista in sorted(incidencias_proy.items(), key=lambda x: x[1][0].get("timestamp", ""), reverse=True):
            ultimo = lista[0]
            tipo = ultimo.get("clasificacion", "DUDOSO")
            estado = clean_val(ultimo.get("estado_redmine"))
            asignado = clean_val(ultimo.get("asignado_a"))
            prioridad = clean_val(ultimo.get("prioridad_redmine"))
            n_emails = len(lista)

            tipo_class = f"inc-{tipo.lower()}" if tipo.lower() in ("urgente", "para_marta", "medio", "informativo") else ""
            estado_html = f'<span class="inc-estado">{estado}</span>' if estado else ""
            asignado_txt = f" | Asignado: {asignado}" if asignado else ""
            prioridad_txt = f" | Prioridad: {prioridad}" if prioridad else ""

            st.markdown(f"""
            <div class="inc-card {tipo_class}">
                <div class="inc-header">
                    <span class="inc-num">#{inc_num}</span>
                    <span>{pill_html(tipo)} {estado_html}</span>
                </div>
                <div class="inc-resumen">{ultimo.get('resumen', '-')}</div>
                <div class="inc-meta">
                    {fmt_ts(ultimo.get('timestamp', ''))} | {n_emails} email{'s' if n_emails > 1 else ''}{asignado_txt}{prioridad_txt}
                </div>
            </div>
            """, unsafe_allow_html=True)

            if n_emails > 1:
                with st.expander(f"Evolucion de #{inc_num} ({n_emails} emails)"):
                    for e in lista:
                        e_tipo = e.get("clasificacion", "DUDOSO")
                        e_estado = clean_val(e.get("estado_redmine"))
                        e_estado_txt = f" [{e_estado}]" if e_estado else ""
                        st.markdown(f"""
                        <div class="timeline-item">
                            <div class="timeline-date">{fmt_ts_full(e.get('timestamp', ''))}</div>
                            <div class="timeline-text">
                                {pill_html(e_tipo)}{e_estado_txt} {e.get('resumen', '-')[:120]}
                                <br><span style="color:#999; font-size:12px">De: {e.get('remitente', '')[:50]}</span>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

    st.markdown('<div class="gaston-footer">Gaston v1.0 - Gestor de incidencias Redmine</div>', unsafe_allow_html=True)


# ===================================================================
#                    ATENCION MARTA
# ===================================================================
elif vista == "Atencion Marta":
    st.markdown('<div class="section-title">Requiere atencion de Marta</div>', unsafe_allow_html=True)

    importantes = [e for e in emails if e.get("clasificacion") in ("URGENTE", "PARA_MARTA", "MEDIO")]

    if not importantes:
        st.success("Sin emails pendientes. Todo gestionado por Gaston.")
    else:
        cols = st.columns(3)
        with cols[0]:
            st.markdown(f'<div class="stat-box" style="border-top-color:#dc3545"><div class="stat-val">{len(urgentes)}</div><div class="stat-lbl">Urgentes</div></div>', unsafe_allow_html=True)
        with cols[1]:
            st.markdown(f'<div class="stat-box"><div class="stat-val">{len(para_marta)}</div><div class="stat-lbl">Para Marta</div></div>', unsafe_allow_html=True)
        with cols[2]:
            st.markdown(f'<div class="stat-box" style="border-top-color:#ffc107"><div class="stat-val">{len(medios)}</div><div class="stat-lbl">Prioridad media</div></div>', unsafe_allow_html=True)

        st.markdown("")

        # Filtro rapido
        filtro_atencion = st.radio(
            "Filtrar", ["Todos", "Solo urgentes", "Solo para Marta", "Solo medio"],
            horizontal=True, label_visibility="collapsed"
        )
        if filtro_atencion == "Solo urgentes":
            importantes = [e for e in importantes if e.get("clasificacion") == "URGENTE"]
        elif filtro_atencion == "Solo para Marta":
            importantes = [e for e in importantes if e.get("clasificacion") == "PARA_MARTA"]
        elif filtro_atencion == "Solo medio":
            importantes = [e for e in importantes if e.get("clasificacion") == "MEDIO"]

        for e in importantes:
            tipo = e.get("clasificacion", "DUDOSO")
            row_class = "urgente-row" if tipo == "URGENTE" else ("marta-row" if tipo == "PARA_MARTA" else "medio-row")
            estado = clean_val(e.get("estado_redmine"))
            estado_html = f'<span class="inc-estado">{estado}</span>' if estado else ""
            inc = clean_val(e.get("numero_incidencia"))
            inc_txt = f"#{inc}" if inc else ""

            st.markdown(f"""
            <div class="{row_class}">
                <strong>{inc_txt}</strong>
                {pill_html(tipo)} {estado_html}
                &nbsp;&middot;&nbsp; <em>{clean_val(e.get('proyecto')) or '-'}</em>
                &nbsp;&middot;&nbsp; <span style="color:#999; font-size:12px">{fmt_ts_full(e.get('timestamp', ''))}</span>
                <br>
                <span style="color:#444; margin-top:4px; display:block">{e.get('resumen', '')}</span>
                <span style="color:#aaa; font-size:12px">De: {e.get('remitente', '')[:50]}</span>
            </div>
            """, unsafe_allow_html=True)

    st.markdown('<div class="gaston-footer">Gaston v1.0 - Gestor de incidencias Redmine</div>', unsafe_allow_html=True)


# ===================================================================
#                     TODOS LOS EMAILS
# ===================================================================
elif vista == "Todos los emails":
    st.markdown('<div class="section-title">Registro completo</div>', unsafe_allow_html=True)

    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        tipos_disponibles = sorted(set(e.get("clasificacion", "DUDOSO") for e in emails))
        tipo_filtro = st.multiselect("Clasificacion", tipos_disponibles, default=tipos_disponibles)
    with col_f2:
        proyectos_disp = sorted(set(clean_val(e.get("proyecto")) or "Sin proyecto" for e in emails))
        proy_filtro = st.multiselect("Proyecto", proyectos_disp, default=proyectos_disp)
    with col_f3:
        buscar = st.text_input("Buscar", placeholder="Incidencia, asunto, resumen...")

    emails_filtrados = emails
    if tipo_filtro:
        emails_filtrados = [e for e in emails_filtrados if e.get("clasificacion") in tipo_filtro]
    if proy_filtro:
        emails_filtrados = [e for e in emails_filtrados if (clean_val(e.get("proyecto")) or "Sin proyecto") in proy_filtro]
    if buscar:
        buscar_lower = buscar.lower()
        emails_filtrados = [
            e for e in emails_filtrados
            if buscar_lower in e.get("asunto", "").lower()
            or buscar_lower in e.get("resumen", "").lower()
            or buscar_lower in e.get("numero_incidencia", "").lower()
            or buscar_lower in e.get("proyecto", "").lower()
        ]

    st.caption(f"Mostrando {len(emails_filtrados)} de {total_emails} emails")

    if not emails_filtrados:
        st.warning("No hay emails que coincidan con los filtros.")
    else:
        df = pd.DataFrame([
            {
                "Fecha": fmt_ts(e.get("timestamp", "")),
                "Clasif.": e.get("clasificacion", "DUDOSO"),
                "#": clean_val(e.get("numero_incidencia")) or "-",
                "Proyecto": clean_val(e.get("proyecto")) or "-",
                "Estado": clean_val(e.get("estado_redmine")) or "-",
                "Resumen": e.get("resumen", "")[:80],
            }
            for e in emails_filtrados
        ])
        st.dataframe(
            df, use_container_width=True, hide_index=True,
            column_config={
                "#": st.column_config.TextColumn(width="small"),
                "Clasif.": st.column_config.TextColumn(width="small"),
                "Estado": st.column_config.TextColumn(width="small"),
            }
        )

    # Detalle
    st.markdown("---")
    st.markdown('<div class="section-title">Detalle</div>', unsafe_allow_html=True)
    email_labels = [
        f"{fmt_ts(e.get('timestamp',''))} | #{clean_val(e.get('numero_incidencia')) or '?'} | {e.get('resumen','')[:40]}"
        for e in emails_filtrados
    ]
    if email_labels:
        sel_idx = st.selectbox("Selecciona un email", range(len(email_labels)), format_func=lambda i: email_labels[i])
        sel = emails_filtrados[sel_idx]
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            st.json({
                "email_id": sel.get("email_id"),
                "fecha": fmt_ts_full(sel.get("timestamp", "")),
                "remitente": sel.get("remitente"),
                "destinatario": sel.get("destinatario"),
                "asunto": sel.get("asunto"),
            })
        with col_d2:
            st.json({
                "clasificacion": sel.get("clasificacion"),
                "proyecto": sel.get("proyecto"),
                "numero_incidencia": sel.get("numero_incidencia"),
                "estado_redmine": sel.get("estado_redmine"),
                "prioridad_redmine": sel.get("prioridad_redmine"),
                "asignado_a": sel.get("asignado_a"),
                "resumen": sel.get("resumen"),
                "requiere_respuesta": sel.get("requiere_respuesta"),
            })

    st.markdown('<div class="gaston-footer">Gaston v1.0 - Gestor de incidencias Redmine</div>', unsafe_allow_html=True)


# ============= AUTO REFRESH =============
if auto_refresh:
    time.sleep(refresh_interval)
    st.rerun()
