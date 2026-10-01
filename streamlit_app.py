# -*- coding: utf-8 -*-
"""
MAV · Tasas, versión Streamlit Cloud. Dos pestañas:

- Resumen: API Consulta de Tasas (mav_tasas.py). Curvas de ECHEQ avalados en pesos
  y pagarés avalados en dólares, y recuadros de volumen. Por defecto, el día de hoy.
- Instrumentos operados: reutiliza mav_operados.py tal cual (descarga, caché, parseo
  y la misma página HTML); el día se elige con controles de Streamlit y los datos se
  inyectan en la página en vez de pedirse al proxy local.

Credenciales: st.secrets["MAV_USER"] y st.secrets["MAV_PASS"]
(Settings → Secrets en Streamlit Cloud, o .streamlit/secrets.toml en local).
Opcional: st.secrets["APP_PASSWORD"] pide una clave antes de mostrar el tablero.
Opcional: GITHUB_TOKEN + GITHUB_DATA_REPO guardan los días pasados en un repo
privado (ver github_cache.py), así no se pierden cuando Streamlit reinicia.
"""

import json
import os
import time
from datetime import date, datetime

import streamlit as st
import streamlit.components.v1 as components

# Streamlit Cloud corre en UTC: sin esto "hoy" pasa al día siguiente a las 21 h.
os.environ["TZ"] = "America/Argentina/Buenos_Aires"
if hasattr(time, "tzset"):
    time.tzset()

import mav_operados as mav  # noqa: E402
import mav_tasas as mt  # noqa: E402
from github_cache import GitHubCache  # noqa: E402

st.set_page_config(page_title="MAV · Tasas", layout="wide")


def secret(key):
    try:
        return st.secrets.get(key, "")
    except Exception:  # sin secrets.toml
        return ""


mav.USER = secret("MAV_USER") or mav.USER
mav.PASS = secret("MAV_PASS") or mav.PASS

app_password = secret("APP_PASSWORD")
if app_password and not st.session_state.get("auth"):
    clave = st.text_input("Clave de acceso", type="password")
    if clave and clave == app_password:
        st.session_state["auth"] = True
        st.rerun()
    elif clave:
        st.error("Clave incorrecta.")
    st.stop()

if not (mav.USER and mav.PASS):
    st.error("Faltan MAV_USER / MAV_PASS en los secrets de la app.")
    st.stop()


@st.cache_resource(show_spinner=False)
def github_caches():
    """(operados, tasas) en un repo privado de GitHub; (None, None) si no está configurado."""
    token, repo = secret("GITHUB_TOKEN"), secret("GITHUB_DATA_REPO")
    if not (token and repo):
        return None, None
    branch = secret("GITHUB_DATA_BRANCH")
    gh = GitHubCache(token, repo, branch)
    gh.check_private()
    return gh, GitHubCache(token, repo, branch, folder="tasas_cache")


try:
    gh, gh_tasas = github_caches()
except Exception as e:
    st.warning("Caché en GitHub desactivada: %s" % e)
    gh = gh_tasas = None


def fmt_fecha(iso):
    return "/".join(reversed(iso.split("-")))


def render_page(html, data, height):
    data = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    components.html(html.replace("__DATA__", data, 1), height=height, scrolling=True)


# ====================================================================== Resumen
@st.cache_data(show_spinner=False)
def tasas_dia_pasado(fecha_iso):
    """Días pasados: GitHub → archivo local bajado después de ese día → MAV."""
    d = date.fromisoformat(fecha_iso)
    if gh_tasas:
        text = gh_tasas.get(fecha_iso)
        if text is not None:
            return mt.parse(text)
    path = mt.snapshot_path(d)
    # Un archivo bajado ese mismo día es parcial (se seguía operando): no sirve.
    if os.path.exists(path) and datetime.fromtimestamp(os.path.getmtime(path)).date() > d:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    else:
        text = mt.fetch(d)
        os.makedirs(mav.CACHE_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    if gh_tasas:
        gh_tasas.put(fecha_iso, text)
    return mt.parse(text)


def tasas_hoy(forzar):
    """Hoy: se vuelve a pedir al MAV si la última foto tiene más de 5 minutos."""
    d = date.today()
    path = mt.snapshot_path(d)
    edad = time.time() - os.path.getmtime(path) if os.path.exists(path) else None
    aviso = None
    if edad is None or edad >= mt.MIN_INTERVAL or forzar:
        try:
            text = mt.fetch(d)
            os.makedirs(mav.CACHE_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        except RuntimeError as e:
            if edad is None:
                raise
            aviso = str(e)
    with open(path, encoding="utf-8") as f:
        filas = mt.parse(f.read())
    hora = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%H:%M")
    return filas, "datos de hoy, actualizados a las " + hora, aviso


def tab_resumen():
    c1, c2, _ = st.columns([2, 1, 3])
    with c1:
        fecha = st.date_input("Día", value=date.today(), max_value=date.today(),
                              format="DD/MM/YYYY", key="fecha_resumen")
    es_hoy = fecha == date.today()
    with c2:
        st.write("")
        actualizar = st.button("Actualizar", use_container_width=True, disabled=not es_hoy,
                               help="Vuelve a pedir los datos de hoy al MAV (máx. una vez cada 5 min).")
    try:
        with st.spinner("Consultando tasas del %s…" % fecha.strftime("%d/%m/%Y")):
            if es_hoy:
                filas, nota, aviso = tasas_hoy(actualizar)
            else:
                filas, nota, aviso = tasas_dia_pasado(fecha.isoformat()), "día cerrado", None
    except RuntimeError as e:
        st.error(str(e))
        return
    if aviso:
        st.caption("No se pudo actualizar: %s" % aviso)
    if not filas:
        st.info("El MAV no informa operaciones para el %s." % fecha.strftime("%d/%m/%Y")
                + (" Si el mercado todavía no abrió, probá más tarde o elegí un día anterior." if es_hoy else ""))
    render_page(mt.PAGE, {"fecha": fecha.isoformat(), "nota": nota, "filas": filas}, 1150)


# ======================================================== Instrumentos operados
@st.cache_data(ttl=60, show_spinner=False)
def github_days():
    return gh.days() if gh else []


@st.cache_data(show_spinner=False)
def load_past_day(fecha_iso):
    """Días pasados: no cambian. Orden: GitHub → MAV (y se guarda en GitHub)."""
    if gh:
        text = gh.get(fecha_iso)
        if text:
            return mav.parse(text), "github"
        # Un CSV local que no está en GitHub puede ser un "hoy" parcial de otro día: se vuelve a bajar.
        local = mav.cache_path(date.fromisoformat(fecha_iso))
        if os.path.exists(local):
            os.remove(local)
    text, origen = mav.fetch_day(date.fromisoformat(fecha_iso))
    if gh:
        gh.put(fecha_iso, text)
        github_days.clear()
    return mav.parse(text), origen


def load(d, refrescar):
    if d < date.today():
        return load_past_day(d.isoformat())
    # Hoy todavía se opera: queda solo en el disco de la app, no en GitHub.
    text, origen = mav.fetch_day(d, force=refrescar)
    return mav.parse(text), origen


INIT_JS = ('estado().then(j=>{if(j.dias_cache.length)load(j.dias_cache[0]);'
           'else status("Elegí un día y tocá Consultar."+(j.espera?` (próxima llamada '
           'a la API disponible en ${j.espera} s)`:""))});')
assert INIT_JS in mav.PAGE, "Cambió el script de inicio de PAGE en mav_operados.py"
# Día / Consultar / Días guardados los maneja Streamlit; los datos se inyectan.
PAGE_OPERADOS = (mav.PAGE
                 .replace("</style>", ".filters>div:nth-child(-n+3){display:none}</style>", 1)
                 .replace(INIT_JS, "onData(__DATA__);", 1))


def tab_operados():
    guardados = sorted(set(github_days()) | set(mav.cached_days()), reverse=True)
    c1, c2, c3 = st.columns([2, 1, 2])
    with c3:
        elegido = st.selectbox("Días guardados", ["—"] + guardados,
                               format_func=lambda s: s if s == "—" else fmt_fecha(s))
    default = date.fromisoformat(elegido) if elegido != "—" else (
        date.fromisoformat(guardados[0]) if guardados else date.today())
    with c1:
        fecha = st.date_input("Día", value=default, max_value=date.today(), format="DD/MM/YYYY")
    with c2:
        st.write("")
        consultar = st.button("Consultar", type="primary", use_container_width=True)

    if not (consultar or fecha.isoformat() in guardados):
        espera = max(0, mav.MIN_INTERVAL - (time.time() - mav.last_call_ts()))
        st.info("Elegí un día y tocá Consultar."
                + (f" (próxima llamada a la API disponible en {int(espera)} s)" if espera else ""))
        return
    try:
        with st.spinner(f"Consultando {fecha:%d/%m/%Y}… (la API puede tardar)"):
            filas, origen = load(fecha, refrescar=consultar and fecha == date.today())
    except RuntimeError as e:
        st.error(str(e))
        return
    render_page(PAGE_OPERADOS, {"fecha": fecha.isoformat(), "origen": origen, "filas": filas}, 1250)


resumen, operados = st.tabs(["Resumen", "Instrumentos operados"])
with resumen:
    tab_resumen()
with operados:
    tab_operados()
