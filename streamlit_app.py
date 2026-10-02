# -*- coding: utf-8 -*-
"""
MAV · Tasas, versión Streamlit Cloud. Tres pestañas:

- Resumen: solo el día de hoy, API Consulta de Tasas (mav_tasas.py). Curvas de ECHEQ
  avalados en pesos y pagarés avalados en dólares, y recuadros de volumen.
- Instrumentos operados: reutiliza mav_operados.py (descarga, caché, parseo y la misma
  página HTML, con comparación de SGR). El día se elige en un calendario que pinta de
  verde los días guardados; los datos se inyectan en la página.
- Análisis histórico: series de tasa por tramo o por SGR sobre los días de Instrumentos
  Operados guardados en GitHub (mav_historico.py). backfill.py los completa solo.

Credenciales: st.secrets["MAV_USER"] y st.secrets["MAV_PASS"]
(Settings → Secrets en Streamlit Cloud, o .streamlit/secrets.toml en local).
Opcional: st.secrets["APP_PASSWORD"] pide una clave antes de mostrar el tablero.
Opcional: GITHUB_TOKEN + GITHUB_DATA_REPO guardan los días pasados en un repo
privado (ver github_cache.py), así no se pierden cuando Streamlit reinicia.
"""

import calendar as cal
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# Streamlit Cloud corre en UTC: sin esto "hoy" pasa al día siguiente a las 21 h.
os.environ["TZ"] = "America/Argentina/Buenos_Aires"
if hasattr(time, "tzset"):
    time.tzset()

import mav_operados as mav  # noqa: E402
import mav_historico as mh  # noqa: E402
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
    html = html.replace("__DATA__", data, 1)
    if hasattr(st, "iframe"):  # components.html quedó obsoleto en Streamlit 1.5x
        st.iframe(html, height=height)
    else:
        components.html(html, height=height, scrolling=True)


# ============================================================ guardado en GitHub
PARCIAL_CADA = 3600  # el parcial de hoy se sube a GitHub como máximo una vez por hora


@st.cache_resource
def _estado_parciales():
    return {"subido": {}, "restaurado": set()}


def avisar_github(accion, e):
    st.warning("No se pudo %s en GitHub: %s. Los datos se ven igual, pero no quedan guardados "
               "si la app se reinicia." % (accion, e))


def guardar_definitivo(cache, fecha_iso, text):
    """Guarda un día cerrado y borra su parcial. Devuelve el error o None."""
    try:
        cache.put(fecha_iso, text)
    except Exception as e:
        return e
    try:
        cache.delete_partial(fecha_iso)
    except Exception:
        pass  # un parcial que sobre no molesta: el definitivo tiene prioridad
    return None


def guardar_parcial(cache, d, text):
    if not cache:
        return
    k = (cache.folder, d.isoformat())
    subido = _estado_parciales()["subido"]
    if time.time() - subido.get(k, 0) < PARCIAL_CADA:
        return
    try:
        cache.put_partial(d.isoformat(), text)
        subido[k] = time.time()
    except Exception as e:
        avisar_github("guardar el parcial de hoy", e)


def restaurar_parcial(cache, d, path):
    """Después de un reinicio, recupera la última foto de hoy desde GitHub (una vez por proceso)."""
    if not cache:
        return
    k = (cache.folder, d.isoformat())
    hechos = _estado_parciales()["restaurado"]
    if k in hechos or os.path.exists(path):
        return
    hechos.add(k)
    try:
        r = cache.get_partial(d.isoformat())
    except Exception as e:
        return avisar_github("leer el parcial de hoy", e)
    if r:
        text, ts = r
        os.makedirs(mav.CACHE_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.utime(path, (ts, ts))
        _estado_parciales()["subido"][k] = ts


def parcial_de_respaldo(cache, fecha_iso, error):
    """Si el MAV no responde por un día pasado, se usa el último parcial guardado (si hay)."""
    try:
        r = cache.get_partial(fecha_iso) if cache else None
    except Exception:
        r = None
    if not r:
        raise error
    st.warning("El MAV no respondió (%s). Se muestra la última foto guardada durante ese día, "
               "que puede estar incompleta." % error)
    return r[0]


# ====================================================================== Resumen
def tasas_hoy(forzar):
    """Hoy: se vuelve a pedir al MAV si la última foto tiene más de 5 minutos."""
    d = date.today()
    path = mt.snapshot_path(d)
    restaurar_parcial(gh_tasas, d, path)
    edad = time.time() - os.path.getmtime(path) if os.path.exists(path) else None
    aviso = None
    if edad is None or edad >= mt.MIN_INTERVAL or forzar:
        try:
            text = mt.fetch(d)
            os.makedirs(mav.CACHE_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            guardar_parcial(gh_tasas, d, text)
        except RuntimeError as e:
            if edad is None:
                raise
            aviso = str(e)
    with open(path, encoding="utf-8") as f:
        filas = mt.parse(f.read())
    hora = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%H:%M")
    return filas, "datos de hoy, actualizados a las " + hora, aviso


def tab_resumen():
    """Solo el día de hoy. El histórico está en la pestaña Análisis histórico."""
    c1, _ = st.columns([1, 5])
    with c1:
        actualizar = st.button("Actualizar", use_container_width=True,
                               help="Vuelve a pedir los datos de hoy al MAV (máx. una vez cada 5 min).")
    try:
        with st.spinner("Consultando las tasas de hoy…"):
            filas, nota, aviso = tasas_hoy(actualizar)
    except RuntimeError as e:
        st.error(str(e))
        return
    if aviso:
        st.caption("No se pudo actualizar: %s" % aviso)
    if not filas:
        st.info("Todavía no hay operaciones hoy. Si el mercado no abrió, probá más tarde.")
    render_page(mt.PAGE, {"fecha": date.today().isoformat(), "nota": nota, "filas": filas}, 1150)


# ======================================================== Instrumentos operados
@st.cache_data(ttl=60, show_spinner=False)
def github_days():
    return gh.days() if gh else []


@st.cache_data(show_spinner=False)
def load_past_day(fecha_iso):
    """Días pasados: no cambian. Orden: GitHub → MAV (y se guarda en GitHub).
    Devuelve (filas, origen, error_al_guardar)."""
    if gh:
        text = gh.get(fecha_iso)
        if text is not None:  # "" = día sin operaciones (feriado), guardado por el backfill
            return mav.parse(text), "github", None
        # Un CSV local que no está en GitHub puede ser un "hoy" parcial de otro día: se vuelve a bajar.
        local = mav.cache_path(date.fromisoformat(fecha_iso))
        if os.path.exists(local):
            os.remove(local)
    text, origen = mav.fetch_day(date.fromisoformat(fecha_iso))
    err = guardar_definitivo(gh, fecha_iso, text) if gh else None
    github_days.clear()
    return mav.parse(text), origen, err


def load(d, refrescar):
    # Días pasados, y hoy cuando el cierre de las 20 h ya quedó guardado en GitHub.
    if d < date.today() or (d.isoformat() in github_days() and not refrescar):
        try:
            filas, origen, err = load_past_day(d.isoformat())
        except RuntimeError as e:
            return mav.parse(parcial_de_respaldo(gh, d.isoformat(), e)), "parcial"
        if err:
            load_past_day.clear(d.isoformat())
            avisar_github("guardar el día", err)
        return filas, origen
    # Hoy todavía se opera: en GitHub va como parcial (se reemplaza al cerrar el día).
    text, origen = mav.fetch_day(d, force=refrescar)
    if origen == "api":
        guardar_parcial(gh, d, text)
    return mav.parse(text), origen


INIT_JS = ('estado().then(j=>{if(j.dias_cache.length)load(j.dias_cache[0]);'
           'else status("Elegí un día y tocá Consultar."+(j.espera?` (próxima llamada '
           'a la API disponible en ${j.espera} s)`:""))});')
assert INIT_JS in mav.PAGE, "Cambió el script de inicio de PAGE en mav_operados.py"
# Día / Consultar / Días guardados los maneja Streamlit; los datos se inyectan.
PAGE_OPERADOS = (mav.PAGE
                 .replace("</style>", ".filters>div:nth-child(-n+3){display:none}</style>", 1)
                 .replace(INIT_JS, "onData(__DATA__);", 1))

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
VERDE = "#1d7a5c"


def calendario(guardados, definitivos, elegido):
    """Calendario mensual: verde = día guardado (definitivo); borde verde = parcial de hoy;
    contorno = elegido."""
    hoy = date.today()
    if "cal_mes" not in st.session_state:
        st.session_state.cal_mes = (elegido.year, elegido.month)
    y, m = st.session_state.cal_mes

    def mover(delta):
        yy, mm = divmod(y * 12 + m - 1 + delta, 12)
        st.session_state.cal_mes = (yy, mm + 1)

    def elegir(iso):
        st.session_state.dia_op = iso

    css = [".st-key-calendario button{padding:0;min-height:34px;font-variant-numeric:tabular-nums}",
           ".st-key-calendario p{margin:0}"]
    with st.container(key="calendario"):
        a, b, c = st.columns([1, 4, 1], vertical_alignment="center")
        a.button("‹", key="cal_prev", on_click=mover, args=(-1,), use_container_width=True)
        b.markdown("<div style='text-align:center;font-weight:600'>%s %d</div>" % (MESES[m - 1].capitalize(), y),
                   unsafe_allow_html=True)
        c.button("›", key="cal_next", on_click=mover, args=(1,), use_container_width=True,
                 disabled=(y, m) >= (hoy.year, hoy.month))
        cols = st.columns(7)
        for col, dia in zip(cols, ["Lu", "Ma", "Mi", "Ju", "Vi", "Sá", "Do"]):
            col.markdown("<div style='text-align:center;font-size:12px;opacity:.6'>%s</div>" % dia,
                         unsafe_allow_html=True)
        for semana in cal.Calendar().monthdatescalendar(y, m):
            cols = st.columns(7)
            for col, d in zip(cols, semana):
                if d.month != m:
                    continue
                iso = d.isoformat()
                col.button(str(d.day), key="cal_" + iso, on_click=elegir, args=(iso,),
                           use_container_width=True, disabled=d > hoy or d.weekday() >= 5)
                sel_css = ".st-key-cal_%s button" % iso
                if iso in definitivos or (iso in guardados and d < hoy):
                    css.append("%s{background:%s;color:#fff;border-color:%s}" % (sel_css, VERDE, VERDE))
                elif iso in guardados:
                    css.append("%s{border:2px solid %s}" % (sel_css, VERDE))
                if d == elegido:
                    css.append("%s{outline:2px solid currentColor;outline-offset:2px;font-weight:700}" % sel_css)
    st.html("<style>%s</style>" % "".join(css))


def tab_operados():
    hoy = date.today()
    restaurar_parcial(gh, hoy, mav.cache_path(hoy))
    definitivos = set(github_days())
    guardados = definitivos | set(mav.cached_days())
    if "dia_op" not in st.session_state:
        pasados = sorted(g for g in guardados if g < hoy.isoformat())
        st.session_state.dia_op = pasados[-1] if pasados else hoy.isoformat()
    fecha = date.fromisoformat(st.session_state.dia_op)

    c_cal, c_info = st.columns([1.2, 2], gap="large")
    with c_cal:
        calendario(guardados, definitivos, fecha)
    with c_info:
        st.markdown("#### %s %d de %s de %d" % (["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado",
                                                   "Domingo"][fecha.weekday()], fecha.day, MESES[fecha.month - 1],
                                                  fecha.year))
        guardado = fecha.isoformat() in guardados
        en_2026 = sorted(g for g in guardados if g.startswith("2026") and g < hoy.isoformat())
        if fecha == hoy and fecha.isoformat() in definitivos:
            st.caption("Cierre del día guardado en GitHub (se guarda a las 20 h).")
        elif fecha == hoy:
            st.caption("Día en curso: se guarda como parcial; el cierre definitivo se guarda a las 20 h.")
        elif guardado:
            st.caption("Guardado en GitHub: se abre sin llamar al MAV.")
        else:
            st.caption("Todavía no está guardado: hay que pedirlo al MAV (una consulta cada 5 minutos).")
        consultar = (not guardado or fecha == hoy) and st.button("Consultar al MAV", type="primary")
        st.markdown(
            "<div style='font-size:12.5px;opacity:.75;margin-top:8px'>"
            "<span style='display:inline-block;width:11px;height:11px;border-radius:3px;background:%s;"
            "vertical-align:-1px'></span> guardado &nbsp; "
            "<span style='display:inline-block;width:11px;height:11px;border-radius:3px;border:2px solid %s;"
            "vertical-align:-1px'></span> parcial de hoy<br>%d días hábiles de 2026 guardados.</div>"
            % (VERDE, VERDE, len(en_2026)), unsafe_allow_html=True)

    if not (consultar or guardado):
        espera = max(0, mav.MIN_INTERVAL - (time.time() - mav.last_call_ts()))
        st.info("Elegí un día en el calendario y tocá Consultar al MAV."
                + (f" (próxima llamada a la API disponible en {int(espera)} s)" if espera else ""))
        return
    try:
        with st.spinner(f"Consultando {fecha:%d/%m/%Y}… (la API puede tardar)"):
            filas, origen = load(fecha, refrescar=consultar and fecha == hoy)
    except RuntimeError as e:
        st.error(str(e))
        return
    if consultar:
        github_days.clear()
    render_page(PAGE_OPERADOS, {"fecha": fecha.isoformat(), "origen": origen, "filas": filas}, 1350)


# ============================================================ Análisis histórico
@st.cache_resource
def _dias_agregados():
    return {}  # fecha → DataFrame agregado (los días cerrados no cambian)


def cargar_historico(dias):
    memo = _dias_agregados()
    faltan = [d for d in dias if d not in memo]
    if faltan:
        def bajar(d):
            return d, mh.agregar_dia(d, gh.get(d) or "")
        with st.spinner("Cargando %d días guardados desde GitHub…" % len(faltan)):
            with ThreadPoolExecutor(max_workers=8) as ex:
                for d, df in ex.map(bajar, faltan):
                    memo[d] = df
    partes = [memo[d] for d in dias if not memo[d].empty]
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()


def tab_historico():
    if not gh:
        st.info("El análisis histórico usa los días guardados en GitHub: falta configurar "
                "GITHUB_TOKEN y GITHUB_DATA_REPO en los secrets.")
        return
    dias = sorted(d for d in github_days() if d < date.today().isoformat())
    if not dias:
        st.info("Todavía no hay días guardados.")
        return
    primero, ultimo = date.fromisoformat(dias[0]), date.fromisoformat(dias[-1])

    f1, f2, f3, f4 = st.columns([2, 1.3, 1, 1])
    rango = f1.date_input("Período", value=(primero, ultimo), min_value=primero, max_value=ultimo,
                          format="DD/MM/YYYY", key="h_rango")
    desde, hasta = (rango if isinstance(rango, (tuple, list)) and len(rango) == 2 else (primero, ultimo))
    elegidos = [d for d in dias if desde.isoformat() <= d <= hasta.isoformat()]
    df = cargar_historico(elegidos)
    if df.empty:
        st.info("No hay operaciones en el período elegido.")
        return

    def opciones(col, grupos):
        return [""] + list(grupos) + sorted(df[col].dropna().unique())

    def idx(lista, valor):
        return lista.index(valor) if valor in lista else 0

    o_tipo = opciones("tipo", mh.GRUPOS_TIPO)
    o_mon = opciones("moneda", mh.GRUPOS_MONEDA)
    o_seg = [""] + sorted(df["segmento"].dropna().unique())
    todos = lambda v: v or "Todos"  # noqa: E731
    tipo = f2.selectbox("Instrumento", o_tipo, index=idx(o_tipo, "Cheques (ECHEQ + CPD)"), format_func=todos, key="h_tipo")
    moneda = f3.selectbox("Moneda", o_mon, index=idx(o_mon, "$"), format_func=lambda v: v or "Todas", key="h_mon")
    segmento = f4.selectbox("Segmento", o_seg, index=idx(o_seg, "Avalado"), format_func=todos, key="h_seg")
    base = mh.filtrar(df, tipo, moneda, segmento)

    g1, g2, g3, g4 = st.columns([1.1, 2.6, 2.2, 1.1])
    por = g1.radio("Comparar por", ["Tramo", "SGR"], horizontal=True, key="h_por")
    ranking = base.groupby("responsable")["monto"].sum().sort_values(ascending=False)
    sgrs = g2.multiselect("SGR / Responsable (hasta 8)", list(ranking.index), max_selections=8, key="h_sgr",
                          format_func=lambda s: s or "(sin responsable)",
                          placeholder="Todas" if por == "Tramo" else "Elegí SGR para comparar")
    tramos = g3.multiselect("Tramos", list(range(len(mh.TRAMOS))), default=list(range(len(mh.TRAMOS))),
                            format_func=lambda i: mh.TRAMOS[i], key="h_tramos")
    ponderado = g4.radio("Promedio", ["Ponderado", "Simple"], key="h_prom") == "Ponderado"
    incluir_total = por == "SGR" and st.checkbox("Incluir total del filtro", value=True, key="h_total")
    if not tramos:
        st.info("Elegí al menos un tramo.")
        return

    fechas = sorted(base["fecha"].unique())
    ser = mh.series(base, fechas, por, ponderado, sgrs, tramos, incluir_total)
    for i, s in enumerate(ser):  # color fijo: por tramo según el tramo, por SGR según el orden elegido
        s["slot"] = tramos[i] if por == "Tramo" else (i - (1 if incluir_total or not sgrs else 0))
    vol_base = base[base["tramo"].isin(tramos)]
    if sgrs:
        vol_base = vol_base[vol_base["responsable"].isin(sgrs)]
    vol = vol_base.groupby("fecha")["monto"].sum()

    filtro = " · ".join(x for x in [tipo or "Todos los instrumentos", moneda or "todas las monedas",
                                    segmento or "todos los segmentos"])
    titulo = "Tasa promedio %s por %s" % ("ponderada" if ponderado else "simple",
                                          "tramo" if por == "Tramo" else "SGR")
    sub = filtro + (" · " + ", ".join(s or "(sin responsable)" for s in sgrs) if por == "Tramo" and sgrs else "")
    if por == "SGR":
        sub += " · tramos: " + (", ".join(mh.TRAMOS[i] for i in tramos)
                                if len(tramos) < len(mh.TRAMOS) else "todos")
    st.caption("%d días con datos entre el %s y el %s." % (len(fechas), fmt_fecha(fechas[0]), fmt_fecha(fechas[-1]))
               if fechas else "Sin datos para estos filtros.")
    render_page(mh.PAGE, {"fechas": fechas, "series": ser, "titulo": titulo, "subtitulo": sub,
                          "volumen": [float(vol.get(f, 0.0)) for f in fechas]}, 1080)


resumen, operados, historico = st.tabs(["Resumen", "Instrumentos operados", "Análisis histórico"])
with resumen:
    tab_resumen()
with operados:
    tab_operados()
with historico:
    tab_historico()
