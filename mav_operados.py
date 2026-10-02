# -*- coding: utf-8 -*-
"""
MAV - Instrumentos Operados V3 · Tasa promedio por plazo
Rosental Inversiones / Research

Levanta una página local (http://127.0.0.1:8765) que consulta la API
"Instrumentos Operados V3" del MAV y grafica la tasa promedio por tramo de
plazo, con filtros por día, SGR (Nombre Responsable), segmento, instrumento
y moneda.

Uso (Windows / Mac / Linux, Python 3.8+ y sin dependencias externas):
    python mav_operados.py

Credenciales: archivo .env junto al script (ver .env.example) o variables de
entorno MAV_USER / MAV_PASS; si no están, el script las pide por consola.
El .env está en .gitignore: nunca se sube al repositorio.

Cada día descargado se guarda en ./mav_cache/AAAA-MM-DD.csv. Los días
pasados no se vuelven a pedir. El día de hoy se puede refrescar. La API exige
300 segundos entre llamadas, y el script controla ese intervalo.
"""

import csv
import getpass
import io
import json
import os
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8765
API_URL = ("https://trading.mav-sa.com.ar/cgi-bin/wspd_cgi.sh/WService%3Dwsbroker1/"
           "cpd-instrumentos-operados-csv_v3.r")
MIN_INTERVAL = 300  # segundos entre llamadas (regla del MAV)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "mav_cache")
STATE_FILE = os.path.join(CACHE_DIR, "_ultima_llamada.txt")

def _load_dotenv(path):
    """Carga KEY=VALUE de un archivo .env (sin dependencias). No pisa variables ya definidas."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(os.path.join(BASE_DIR, ".env"))
USER = os.environ.get("MAV_USER", "")
PASS = os.environ.get("MAV_PASS", "")
HOST = os.environ.get("MAV_HOST", "127.0.0.1")  # 0.0.0.0 para compartir en la red local
_lock = threading.Lock()


# ----------------------------------------------------------------- utilidades
def norm(s):
    """Normaliza encabezados: sin acentos, mayúsculas, sin puntos/espacios extra."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = s.upper().replace(".", " ").replace("/", " ").replace("-", " ")
    return " ".join(s.split())


def num(s):
    s = (s or "").strip()
    if not s:
        return None
    s = s.replace(".", "").replace(",", ".") if "," in s else s
    try:
        return float(s)
    except ValueError:
        return None


def last_call_ts():
    try:
        with open(STATE_FILE) as f:
            return float(f.read().strip())
    except Exception:
        return 0.0


def set_last_call_ts():
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        f.write(str(time.time()))


def decode(raw):
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", "replace")


def looks_like_data(text):
    first = text.strip().splitlines()[0] if text.strip() else ""
    return ";" in first and "TASA" in norm(first)


# ---------------------------------------------------------------- API + cache
def cache_path(d):
    return os.path.join(CACHE_DIR, d.isoformat() + ".csv")


def fetch_day(d, force=False):
    """Devuelve (texto_csv, origen). Lanza RuntimeError con mensaje legible."""
    path = cache_path(d)
    is_today = d == date.today()
    if os.path.exists(path) and not (force and is_today):
        with open(path, encoding="utf-8") as f:
            return f.read(), "cache"

    with _lock:
        wait = MIN_INTERVAL - (time.time() - last_call_ts())
        if wait > 0:
            raise RuntimeError(
                "El MAV exige 300 s entre consultas. Probá de nuevo en %d s." % (int(wait) + 1))
        qs = urllib.parse.urlencode({
            "mode": "ws", "id": USER, "password": PASS,
            "fecha": d.strftime("%d/%m/%y")}, safe="/")
        req = urllib.request.Request(API_URL + "?" + qs,
                                     headers={"User-Agent": "Rosental-Research/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=330) as r:
                raw = r.read()
        except urllib.error.URLError as e:
            raise RuntimeError("No se pudo conectar con el MAV: %s" % e)
        finally:
            set_last_call_ts()

    text = decode(raw)
    if not looks_like_data(text):
        msg = " ".join(text.split())[:300] or "respuesta vacía"
        raise RuntimeError("El MAV respondió: " + msg)

    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return text, "api"


def parse(text):
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return []
    header = [norm(h) for h in rows[0]]

    def col(*names):
        for n in names:
            if n in header:
                return header.index(n)
        for n in names:  # coincidencia parcial
            for i, h in enumerate(header):
                if h.startswith(n):
                    return i
        return None

    ix = {
        "tipo": col("TIPO INSTRUMENTO", "TIPO INSTR"),
        "segmento": col("SEGMENTO"),
        "plazo": col("PLAZO"),
        "dias": col("DIAS ACRED"),
        "tasa": col("TASA"),
        "monto": col("MONTO"),
        "monto_liq": col("MONTO LIQUIDADO"),
        "moneda": col("MONEDA"),
        "resp": col("NOMBRE RESPONSABLE"),
        "cod_resp": col("CODIGO RESPONSABLE"),
        "fecha_pago": col("FECHA PAGO"),
        "tipo_gtia": col("TIPO GTIA"),
    }

    def g(r, k):
        i = ix[k]
        return r[i].strip() if i is not None and i < len(r) else ""

    out = []
    for r in rows[1:]:
        plazo = num(g(r, "plazo"))
        if plazo is None:
            plazo = num(g(r, "dias"))
        out.append({
            "tipo": g(r, "tipo"),
            "segmento": g(r, "segmento"),
            "plazo": plazo,
            "tasa": num(g(r, "tasa")),
            "monto": num(g(r, "monto")) or 0.0,
            "monto_liq": num(g(r, "monto_liq")) or 0.0,
            "moneda": g(r, "moneda"),
            "responsable": g(r, "resp"),
            "cod_responsable": g(r, "cod_resp"),
            "fecha_pago": g(r, "fecha_pago"),
            "tipo_gtia": g(r, "tipo_gtia"),
        })
    return out


def cached_days():
    if not os.path.isdir(CACHE_DIR):
        return []
    return sorted((f[:-4] for f in os.listdir(CACHE_DIR)
                   if f.endswith(".csv") and len(f) == 14), reverse=True)


# ---------------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/":
            return self.send(200, PAGE, "text/html; charset=utf-8")
        if u.path == "/api/estado":
            wait = max(0, MIN_INTERVAL - (time.time() - last_call_ts()))
            return self.send(200, json.dumps({"dias_cache": cached_days(),
                                              "espera": int(wait),
                                              "hoy": date.today().isoformat()}))
        if u.path == "/api/dia":
            try:
                d = datetime.strptime(q.get("fecha", [""])[0], "%Y-%m-%d").date()
            except ValueError:
                return self.send(400, json.dumps({"error": "Fecha inválida"}))
            try:
                text, origen = fetch_day(d, force=q.get("refrescar", ["0"])[0] == "1")
            except RuntimeError as e:
                return self.send(503, json.dumps({"error": str(e)}))
            return self.send(200, json.dumps({"fecha": d.isoformat(), "origen": origen,
                                              "filas": parse(text)}))
        self.send(404, json.dumps({"error": "no encontrado"}))


PAGE = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MAV · Tasas por plazo</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#14171c;--muted:#5d6673;--line:#e3e6eb;--accent:#1f4e8c;--accent2:#9db7da;--err:#a3271f;--total:#8a919c;
  --s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300;--s7:#4a3aa7;--s8:#e34948}
@media (prefers-color-scheme:dark){:root{--bg:#121417;--card:#1b1e23;--ink:#e8eaed;--muted:#9aa3ad;--line:#2c3138;--accent:#6fa0e0;--accent2:#33507a;--err:#ff8a80;--total:#7d848e;
  --s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300;--s7:#9085e9;--s8:#e66767}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{padding:18px 24px 6px}h1{font-size:19px;margin:0}header p{margin:2px 0 0;color:var(--muted);font-size:12.5px}
main{padding:12px 24px 32px;max-width:1200px}
.filters{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
label{display:block;font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px}
select,input,button{width:100%;font:inherit;padding:7px 9px;border:1px solid var(--line);border-radius:7px;background:var(--bg);color:var(--ink)}
button{background:var(--accent);color:#fff;border:0;cursor:pointer;font-weight:600}button:disabled{opacity:.5;cursor:default}
.wide{grid-column:span 2}@media(max-width:620px){.wide{grid-column:span 1}}
.status{margin:10px 2px;font-size:12.5px;color:var(--muted);min-height:18px}.status.err{color:var(--err)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:6px 0 12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}.kpi b{display:block;font-size:20px;font-variant-numeric:tabular-nums}.kpi span{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:12px}
.card h2{font-size:14px;margin:0 0 10px}.chartbox{position:relative;height:360px}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:13px}
th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:right}th:first-child,td:first-child{text-align:left}
th{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;font-weight:600}
td small{color:var(--muted);font-size:11.5px}
.seg{display:flex;gap:6px}.seg button{background:var(--bg);color:var(--ink);border:1px solid var(--line);font-weight:500}.seg button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
footer{color:var(--muted);font-size:11.5px;margin-top:8px}
.chead{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px}.chead h2{margin:0}.vista button{width:auto;padding:5px 12px}
.tablewrap{overflow-x:auto}
/* selector múltiple de SGR */
.ms{position:relative}
.msbtn{background:var(--bg);color:var(--ink);border:1px solid var(--line);font-weight:500;text-align:left;display:flex;justify-content:space-between}
.msbtn::after{content:"▾";color:var(--muted)}
.mspanel{position:absolute;z-index:10;top:calc(100% + 4px);left:0;right:0;background:var(--card);border:1px solid var(--line);border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.14);padding:8px}
.msacts{display:flex;justify-content:space-between;align-items:center;margin:6px 2px;font-size:12.5px;color:var(--muted)}
.msacts a{color:var(--accent);cursor:pointer}
.mslist{max-height:260px;overflow:auto}
.mslist label{display:flex;gap:8px;align-items:center;text-transform:none;letter-spacing:0;font-size:13px;color:var(--ink);margin:0;padding:5px 4px;border-radius:5px;cursor:pointer}
.mslist label:hover{background:var(--bg)}.mslist label.off{opacity:.45;cursor:default}
.mslist input{width:auto;margin:0}.mslist .m{margin-left:auto;color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.chip{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:999px;padding:2px 4px 2px 8px;font-size:12px;background:var(--bg)}
.chip i{width:9px;height:9px;border-radius:50%;display:inline-block}
.chip button{width:auto;padding:0 6px;background:none;color:var(--muted);font-weight:400}
.inc{display:flex;gap:6px;align-items:center;text-transform:none;letter-spacing:0;font-size:12.5px;color:var(--muted);margin:0}.inc input{width:auto}
[hidden]{display:none!important}
</style></head><body>
<header><h1>MAV · Instrumentos operados: tasa promedio por plazo</h1>
<p>Rosental Inversiones / Research · Fuente: MAV, API Instrumentos Operados V3</p></header>
<main>
<div class="filters">
  <div><label>Día</label><input type="date" id="fecha"></div>
  <div><label>&nbsp;</label><button id="cargar">Consultar</button></div>
  <div><label>Días guardados</label><select id="cache"><option value="">—</option></select></div>
  <div><label>Moneda</label><select id="moneda"></select></div>
  <div><label>Segmento</label><select id="segmento"></select></div>
  <div><label>Instrumento</label><select id="tipo"></select></div>
  <div class="wide"><label>SGR / Responsable · comparar hasta 8</label>
    <div class="ms"><button type="button" id="msbtn" class="msbtn">Todos</button>
      <div class="mspanel" id="mspanel" hidden>
        <input id="msq" placeholder="Buscar SGR / responsable…" autocomplete="off">
        <div class="msacts"><a id="msclear">Limpiar selección</a><span id="mscount"></span></div>
        <div class="mslist" id="mslist"></div>
      </div></div>
    <div class="chips" id="chips"></div>
  </div>
  <div><label>Promedio</label><div class="seg"><button id="wpond" class="on">Ponderado</button><button id="wsimp">Simple</button></div></div>
</div>
<div class="status" id="status"></div>
<div class="kpis">
  <div class="kpi"><span>Operaciones</span><b id="k_n">–</b></div>
  <div class="kpi"><span>Monto operado</span><b id="k_m">–</b></div>
  <div class="kpi"><span>Tasa promedio</span><b id="k_t">–</b></div>
  <div class="kpi"><span>Plazo promedio</span><b id="k_p">–</b></div>
</div>
<div class="card"><div class="chead"><h2 id="ctitle">Tasa promedio por plazo</h2>
  <div style="display:flex;gap:14px;align-items:center"><label class="inc" id="incwrap" hidden><input type="checkbox" id="inctotal" checked> Incluir total del filtro</label>
  <div class="seg vista"><button id="vbar" class="on">Barras</button><button id="vcur">Curva</button></div></div></div>
  <div class="chartbox"><canvas id="chart"></canvas></div></div>
<div class="card"><h2>Detalle por tramo</h2>
<div class="tablewrap"><table><thead id="thead"></thead><tbody id="tbody"></tbody></table></div>
<footer>Tasas en TNA tal como las informa el MAV. El promedio ponderado usa el monto nominal. Se excluyen las operaciones sin tasa o con tasa 0 (p. ej. valor producto). Tramos: hasta 30 días, 31–60, 61–90, 91–180, 181–365 y más de 365. En la curva, cada punto es el promedio del tramo ubicado en su plazo promedio y la línea es el ajuste logarítmico.</footer></div>
</main>
<script>
const BUCKETS=[["1-30 días",0,30],["30-60 días",30,60],["60-90 días",60,90],["90-180 días",90,180],["180-365 días",180,365],["+365 días",365,1e9]];
// Grupos de filtros: se pueden ver combinados o por separado.
const GRUPOS={moneda:{"__USD":["U$S + U$D",r=>r.moneda==="U$S"||r.moneda==="U$D"]},
              tipo:{"__CHQ":["Cheques (ECHEQ + CPD)",r=>r.tipo==="ECHEQ"||r.tipo==="CPD"]}};
const MAXSEL=8;
let rows=[],weighted=true,curva=false,chart=null,sel=[],slot={};
const $=id=>document.getElementById(id);
const fmtPct=v=>v==null?"–":v.toLocaleString("es-AR",{minimumFractionDigits:2,maximumFractionDigits:2})+"%";
const fmtM=v=>{if(!v)return"–";const a=Math.abs(v);return a>=1e9?(v/1e9).toLocaleString("es-AR",{maximumFractionDigits:2})+" MM":a>=1e6?(v/1e6).toLocaleString("es-AR",{maximumFractionDigits:1})+" M":v.toLocaleString("es-AR",{maximumFractionDigits:0})};
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function status(t,err){$("status").textContent=t||"";$("status").className="status"+(err?" err":"")}

function opts(sel,values,allLabel,keep,grupos){
  const prev=keep?sel.value:"";sel.innerHTML="";
  if(allLabel)sel.add(new Option(allLabel,""));
  Object.entries(grupos||{}).forEach(([k,[lab]])=>sel.add(new Option(lab,k)));
  values.forEach(v=>sel.add(new Option(v||"(sin dato)",v)));
  if(keep&&[...sel.options].some(o=>o.value===prev))sel.value=prev;
}
const uniq=a=>[...new Set(a)].sort((x,y)=>x.localeCompare(y,"es"));
function pasa(campo,r){const v=$(campo).value;if(!v)return true;const g=(GRUPOS[campo]||{})[v];return g?g[1](r):r[campo]===v}

function base(){ // filtros salvo responsable
  return rows.filter(r=>r.tasa!=null&&r.tasa>0&&r.plazo!=null&&pasa("moneda",r)&&pasa("segmento",r)&&pasa("tipo",r));
}
// ---- selector múltiple: el color sigue a la SGR mientras esté elegida (no al orden)
function colorDe(n){return css("--s"+(slot[n]+1))}
function toggle(n){
  if(sel.includes(n)){sel=sel.filter(x=>x!==n);delete slot[n]}
  else if(sel.length<MAXSEL){sel.push(n);const usados=new Set(Object.values(slot));let i=0;while(usados.has(i))i++;slot[n]=i}
  refreshResp();render();
}
function refreshResp(){
  const m={};base().forEach(r=>{m[r.responsable]=(m[r.responsable]||0)+r.monto});
  const vals=Object.keys(m).sort((a,c)=>m[c]-m[a]);
  const q=$("msq").value.trim().toLowerCase(),lleno=sel.length>=MAXSEL;
  $("mslist").innerHTML=vals.filter(v=>!q||(v||"").toLowerCase().includes(q)).map(v=>{
    const on=sel.includes(v),off=!on&&lleno;
    return `<label class="${off?"off":""}"><input type="checkbox" data-v="${esc(v)}" ${on?"checked":""} ${off?"disabled":""}>${esc(v||"(sin responsable)")}<span class="m">${fmtM(m[v])}</span></label>`}).join("")
    ||'<div style="padding:6px;color:var(--muted)">Sin resultados</div>';
  $("mscount").textContent=vals.length+" con operaciones";
  $("msbtn").textContent=sel.length?sel.length+" seleccionada"+(sel.length>1?"s":""):"Todos ("+vals.length+")";
  $("chips").innerHTML=sel.map(n=>`<span class="chip"><i style="background:${colorDe(n)}"></i>${esc(n||"(sin responsable)")}<button data-v="${esc(n)}" title="Quitar">×</button></span>`).join("");
  $("incwrap").hidden=!sel.length;
}
$("msbtn").onclick=e=>{e.stopPropagation();$("mspanel").hidden=!$("mspanel").hidden;if(!$("mspanel").hidden)$("msq").focus()};
$("mspanel").onclick=e=>e.stopPropagation();
document.addEventListener("click",()=>$("mspanel").hidden=true);
$("mslist").onchange=e=>{if(e.target.dataset.v!==undefined)toggle(e.target.dataset.v)};
$("chips").onclick=e=>{if(e.target.dataset.v!==undefined)toggle(e.target.dataset.v)};
$("msq").oninput=refreshResp;
$("msclear").onclick=()=>{sel=[];slot={};refreshResp();render()};
$("inctotal").onchange=render;

function stats(d){
  return BUCKETS.map(([lab,lo,hi])=>{
    const s=d.filter(r=>r.plazo>lo&&r.plazo<=hi||(lo===0&&r.plazo<=0));
    const m=s.reduce((a,r)=>a+r.monto,0);
    const tp=m?s.reduce((a,r)=>a+r.tasa*r.monto,0)/m:null;
    const ts=s.length?s.reduce((a,r)=>a+r.tasa,0)/s.length:null;
    const xp=m?s.reduce((a,r)=>a+r.plazo*r.monto,0)/m:null,xs=s.length?s.reduce((a,r)=>a+r.plazo,0)/s.length:null;
    return {lab,n:s.length,m,tp,ts,xp,xs,min:s.length?Math.min(...s.map(r=>r.tasa)):null,max:s.length?Math.max(...s.map(r=>r.tasa)):null};
  });
}
function render(){
  const b=base();
  const d=sel.length?b.filter(r=>sel.includes(r.responsable)):b;
  // series: una por SGR elegida (+ total del filtro como referencia), o solo el total
  const series=sel.length
    ?[...($("inctotal").checked?[{name:"Total del filtro",d:b,color:css("--total"),total:true}]:[]),...sel.map(n=>({name:n||"(sin responsable)",d:b.filter(r=>r.responsable===n),color:colorDe(n)}))]
    :[{name:"Total",d:b,color:css("--s1")}];
  series.forEach(s=>{s.st=stats(s.d);s.vals=s.st.map(x=>weighted?x.tp:x.ts)});
  const M=d.reduce((a,r)=>a+r.monto,0);
  $("k_n").textContent=d.length.toLocaleString("es-AR");
  $("k_m").textContent=fmtM(M);
  $("k_t").textContent=fmtPct(weighted?(M?d.reduce((a,r)=>a+r.tasa*r.monto,0)/M:null):(d.length?d.reduce((a,r)=>a+r.tasa,0)/d.length:null));
  $("k_p").textContent=d.length?Math.round(M?d.reduce((a,r)=>a+r.plazo*r.monto,0)/M:0)+" días":"–";
  const solo=series.length===1;
  if(solo){
    const st=series[0].st;
    $("thead").innerHTML="<tr><th>Plazo</th><th>Operaciones</th><th>Monto</th><th>Tasa pond.</th><th>Tasa simple</th><th>Mín</th><th>Máx</th></tr>";
    $("tbody").innerHTML=st.map(s=>`<tr><td>${s.lab}</td><td>${s.n||"–"}</td><td>${fmtM(s.m)}</td><td>${fmtPct(s.tp)}</td><td>${fmtPct(s.ts)}</td><td>${fmtPct(s.min)}</td><td>${fmtPct(s.max)}</td></tr>`).join("");
  }else{
    $("thead").innerHTML="<tr><th>Plazo</th>"+series.map(s=>`<th><i style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${s.color};margin-right:5px"></i>${esc(s.name)}</th>`).join("")+"</tr>";
    $("tbody").innerHTML=BUCKETS.map((bk,i)=>`<tr><td>${bk[0]}</td>`+series.map(s=>{const x=s.st[i];return `<td>${fmtPct(s.vals[i])}<br><small>${x.n?x.n+" ops · "+fmtM(x.m):"sin ops"}</small></td>`}).join("")+"</tr>").join("");
  }
  $("ctitle").textContent="Tasa promedio "+(weighted?"ponderada":"simple")+" por plazo"+(sel.length===1?" · "+(sel[0]||"(sin responsable)"):sel.length>1?" · comparación de "+sel.length:"");
  if(chart)chart.destroy();chart=new Chart($("chart"),curva?curveCfg(series):barCfg(series));
}
function legendOpts(n){const muted=css("--muted");
  return {display:n>1,position:"top",align:"start",labels:{color:css("--ink"),usePointStyle:true,pointStyle:"circle",boxWidth:8,boxHeight:8,padding:14,
    filter:i=>!i.text.startsWith("~")}}}
function barCfg(series){
  const ink=css("--ink"),muted=css("--muted"),line=css("--line"),solo=series.length===1;
  return {type:"bar",data:{labels:BUCKETS.map(b=>b[0]),datasets:series.map(s=>({label:s.name,data:s.vals,backgroundColor:s.color,
      borderRadius:4,borderColor:css("--card"),borderWidth:solo?0:{top:0,right:1,bottom:0,left:1},maxBarThickness:solo?70:34}))},
    options:{maintainAspectRatio:false,animation:false,layout:{padding:{top:solo?18:0}},plugins:{legend:legendOpts(series.length),
      tooltip:{callbacks:{label:c=>c.dataset.label+": "+fmtPct(c.raw),afterLabel:c=>{const x=series[c.datasetIndex].st[c.dataIndex];return x.n+" ops · "+fmtM(x.m)}}}},
      scales:{x:{grid:{display:false},ticks:{color:muted}},y:{beginAtZero:true,grid:{color:line},ticks:{color:muted,callback:v=>v+"%"}}}},
    plugins:solo?[{id:"lbl",afterDatasetsDraw(c){const ctx=c.ctx,vals=series[0].vals;ctx.save();ctx.fillStyle=ink;ctx.font="600 12px system-ui";ctx.textAlign="center";
      c.getDatasetMeta(0).data.forEach((b,i)=>{if(vals[i]!=null)ctx.fillText(fmtPct(vals[i]),b.x,b.y-6)});ctx.restore()}}]:[]};
}
function logFit(pts){ // tasa = a + b·ln(días), sobre los puntos de cada tramo
  if(pts.length<2)return null;let n=pts.length,sx=0,sy=0,sxx=0,sxy=0;
  pts.forEach(p=>{const l=Math.log(p.x);sx+=l;sy+=p.y;sxx+=l*l;sxy+=l*p.y});
  const den=n*sxx-sx*sx;if(Math.abs(den)<1e-12)return null;
  const b=(n*sxy-sx*sy)/den,a=(sy-b*sx)/n;return x=>a+b*Math.log(x);
}
function curveCfg(series){
  const ink=css("--ink"),muted=css("--muted"),grid=css("--line"),card=css("--card"),solo=series.length===1;
  const ds=[],ys=[];
  series.forEach(s=>{
    const pts=s.st.map((x,i)=>({x:weighted?x.xp:x.xs,y:s.vals[i],s:x})).filter(p=>p.y!=null&&p.x>0);
    const f=logFit(pts),x0=pts.length?Math.min(...pts.map(p=>p.x)):0,x1=pts.length?Math.max(...pts.map(p=>p.x)):1;
    const line=f?Array.from({length:80},(_,i)=>{const x=x0+(x1-x0)*i/79;return{x,y:f(x)}}):[];
    ys.push(...pts.map(p=>p.y),...line.map(p=>p.y));
    ds.push({type:"line",label:s.name,data:line,borderColor:s.color,backgroundColor:s.color,borderWidth:2,borderDash:s.total?[6,4]:[],pointRadius:0,order:2});
    ds.push({type:"scatter",label:"~"+s.name,data:pts,backgroundColor:s.color,borderColor:card,borderWidth:2,pointRadius:solo?7:5.5,pointHoverRadius:8,order:1});
  });
  const lo=ys.length?Math.min(...ys):0,hi=ys.length?Math.max(...ys):1,pad=Math.max(1,(hi-lo)*.2);
  return {data:{datasets:ds},
    options:{maintainAspectRatio:false,animation:false,layout:{padding:{top:solo?22:0,right:12}},
      plugins:{legend:legendOpts(series.length),tooltip:{filter:i=>i.dataset.type==="scatter",callbacks:{
        title:c=>c[0].raw.s.lab,label:c=>c.dataset.label.slice(1)+": "+fmtPct(c.raw.y)+" · plazo prom. "+Math.round(c.raw.x)+" días",
        afterLabel:c=>c.raw.s.n+" ops · "+fmtM(c.raw.s.m)}}},
      scales:{x:{type:"linear",min:0,grid:{color:grid},ticks:{color:muted,callback:v=>v+" d"},title:{display:true,text:"Plazo (días)",color:muted}},
        y:{suggestedMin:Math.floor(lo-pad),suggestedMax:Math.ceil(hi+pad),grid:{color:grid},ticks:{color:muted,callback:v=>v+"%"}}}},
    // con varias series las etiquetas se pisan: solo se rotulan los puntos de una curva sola
    plugins:solo?[{id:"lbl",afterDatasetsDraw(c){const ctx=c.ctx,pts=c.data.datasets[1].data;ctx.save();ctx.textAlign="center";ctx.fillStyle=ink;ctx.font="600 12px system-ui";
      // tramos cortos quedan juntos: etiquetas alternadas arriba / abajo
      c.getDatasetMeta(1).data.forEach((p,i)=>ctx.fillText(fmtPct(pts[i].y),p.x,i%2?p.y+22:p.y-12));ctx.restore()}}]:[]};
}
function onData(j){
  rows=j.filas;
  opts($("moneda"),uniq(rows.map(r=>r.moneda)),"Todas",true,GRUPOS.moneda);
  if(!$("moneda").dataset.init){$("moneda").dataset.init=1;if(rows.some(r=>r.moneda==="$"))$("moneda").value="$"}
  opts($("segmento"),uniq(rows.map(r=>r.segmento)),"Todos",true);
  opts($("tipo"),uniq(rows.map(r=>r.tipo)),"Todos",true,GRUPOS.tipo);
  refreshResp();render();
  status(`${j.fecha.split("-").reverse().join("/")} · ${rows.length} instrumentos operados · `+({api:"recién bajado del MAV",github:"guardado en GitHub",parcial:"guardado en GitHub (parcial del día)"}[j.origen]||"desde caché local"));
}
async function load(f,refrescar){
  if(!f)return status("Elegí un día.",true);
  $("cargar").disabled=true;status("Consultando "+f.split("-").reverse().join("/")+"… (la API puede tardar)");
  try{const r=await fetch(`/api/dia?fecha=${f}${refrescar?"&refrescar=1":""}`);const j=await r.json();
    if(!r.ok)throw new Error(j.error);onData(j);await estado()}
  catch(e){status(e.message,true)}finally{$("cargar").disabled=false}
}
async function estado(){
  const j=await(await fetch("/api/estado")).json();
  const prev=$("cache").value;$("cache").innerHTML='<option value="">—</option>';
  j.dias_cache.forEach(d=>$("cache").add(new Option(d.split("-").reverse().join("/"),d)));$("cache").value=prev;
  if(!$("fecha").value)$("fecha").value=j.dias_cache[0]||j.hoy;
  return j;
}
$("cargar").onclick=()=>load($("fecha").value,$("fecha").value===new Date().toISOString().slice(0,10));
$("cache").onchange=e=>{if(e.target.value){$("fecha").value=e.target.value;load(e.target.value)}};
["moneda","segmento","tipo"].forEach(id=>$(id).onchange=()=>{refreshResp();render()});
// En una pestaña oculta el gráfico nace en 0×0: se redibuja cuando la página toma tamaño.
let lastW=0;new ResizeObserver(()=>{const w=document.body.clientWidth;if(w&&w!==lastW){lastW=w;if(rows.length)render()}}).observe(document.body);
$("wpond").onclick=()=>{weighted=true;$("wpond").classList.add("on");$("wsimp").classList.remove("on");render()};
$("vbar").onclick=()=>{curva=false;$("vbar").classList.add("on");$("vcur").classList.remove("on");render()};
$("vcur").onclick=()=>{curva=true;$("vcur").classList.add("on");$("vbar").classList.remove("on");render()};
$("wsimp").onclick=()=>{weighted=false;$("wsimp").classList.add("on");$("wpond").classList.remove("on");render()};
estado().then(j=>{if(j.dias_cache.length)load(j.dias_cache[0]);else status("Elegí un día y tocá Consultar."+(j.espera?` (próxima llamada a la API disponible en ${j.espera} s)`:""))});
</script></body></html>"""


def main():
    global USER, PASS
    if not USER:
        USER = input("Usuario MAV (Consultas Web Services): ").strip()
    if not PASS:
        PASS = getpass.getpass("Contraseña MAV: ")
    os.makedirs(CACHE_DIR, exist_ok=True)
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    url = "http://127.0.0.1:%d/" % PORT
    print("MAV · Tasas por plazo en", url, "(Ctrl+C para cerrar)")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrado.")


if __name__ == "__main__":
    main()
