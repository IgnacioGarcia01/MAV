# -*- coding: utf-8 -*-
"""
MAV · Tasa promedio por plazo, versión Streamlit Cloud.

Reutiliza mav_operados.py tal cual: la descarga, la caché y el parseo son los
mismos, y el tablero es la misma página HTML (PAGE). La única diferencia es que
el día se elige con controles de Streamlit y los datos se inyectan en la página
en vez de pedirse al proxy local.

Credenciales: st.secrets["MAV_USER"] y st.secrets["MAV_PASS"]
(Settings → Secrets en Streamlit Cloud, o .streamlit/secrets.toml en local).
Opcional: st.secrets["APP_PASSWORD"] pide una clave antes de mostrar el tablero.
"""

import json
import os
import time
from datetime import date

import streamlit as st
import streamlit.components.v1 as components

# Streamlit Cloud corre en UTC: sin esto "hoy" pasa al día siguiente a las 21 h.
os.environ["TZ"] = "America/Argentina/Buenos_Aires"
if hasattr(time, "tzset"):
    time.tzset()

import mav_operados as mav  # noqa: E402

st.set_page_config(page_title="MAV · Tasas por plazo", layout="wide")


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


@st.cache_data(show_spinner=False)
def load_past_day(fecha_iso):
    """Días pasados: no cambian, se guardan en memoria además de mav_cache/."""
    text, origen = mav.fetch_day(date.fromisoformat(fecha_iso))
    return mav.parse(text), origen


def load(d, refrescar):
    if d < date.today():
        return load_past_day(d.isoformat())
    text, origen = mav.fetch_day(d, force=refrescar)
    return mav.parse(text), origen


# --------------------------------------------------------------- selección día
guardados = mav.cached_days()
c1, c2, c3 = st.columns([2, 1, 2])
with c3:
    elegido = st.selectbox("Días guardados", ["—"] + guardados,
                           format_func=lambda s: s if s == "—" else "/".join(reversed(s.split("-"))))
default = date.fromisoformat(elegido) if elegido != "—" else (
    date.fromisoformat(guardados[0]) if guardados else date.today())
with c1:
    fecha = st.date_input("Día", value=default, max_value=date.today(), format="DD/MM/YYYY")
with c2:
    st.write("")
    consultar = st.button("Consultar", type="primary", use_container_width=True)

ya_guardado = fecha.isoformat() in guardados
if not (consultar or ya_guardado):
    espera = max(0, mav.MIN_INTERVAL - (time.time() - mav.last_call_ts()))
    st.info("Elegí un día y tocá Consultar."
            + (f" (próxima llamada a la API disponible en {int(espera)} s)" if espera else ""))
    st.stop()

try:
    with st.spinner(f"Consultando {fecha:%d/%m/%Y}… (la API puede tardar)"):
        filas, origen = load(fecha, refrescar=consultar and fecha == date.today())
except RuntimeError as e:
    st.error(str(e))
    st.stop()

# ------------------------------------------------------------ tablero (PAGE)
data = json.dumps({"fecha": fecha.isoformat(), "origen": origen, "filas": filas},
                  ensure_ascii=False).replace("</", "<\\/")

INIT_JS = ('estado().then(j=>{if(j.dias_cache.length)load(j.dias_cache[0]);'
           'else status("Elegí un día y tocá Consultar."+(j.espera?` (próxima llamada '
           'a la API disponible en ${j.espera} s)`:""))});')
assert INIT_JS in mav.PAGE, "Cambió el script de inicio de PAGE en mav_operados.py"

page = (mav.PAGE
        # Día / Consultar / Días guardados los maneja Streamlit arriba.
        .replace("</style>", ".filters>div:nth-child(-n+3){display:none}</style>", 1)
        .replace(INIT_JS, "onData(" + data + ");", 1))

components.html(page, height=1250, scrolling=True)
