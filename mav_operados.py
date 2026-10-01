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
:root{--bg:#f6f7f9;--card:#fff;--ink:#14171c;--muted:#5d6673;--line:#e3e6eb;--accent:#1f4e8c;--accent2:#9db7da;--err:#a3271f}
@media (prefers-color-scheme:dark){:root{--bg:#121417;--card:#1b1e23;--ink:#e8eaed;--muted:#9aa3ad;--line:#2c3138;--accent:#6fa0e0;--accent2:#33507a;--err:#ff8a80}}
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
.card h2{font-size:14px;margin:0 0 10px}.chartbox{position:relative;height:340px}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:13px}
th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:right}th:first-child,td:first-child{text-align:left}
th{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;font-weight:600}
.seg{display:flex;gap:6px}.seg button{background:var(--bg);color:var(--ink);border:1px solid var(--line);font-weight:500}.seg button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
footer{color:var(--muted);font-size:11.5px;margin-top:8px}
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
  <div class="wide"><label>SGR / Responsable</label><select id="resp"></select></div>
  <div><label>Promedio</label><div class="seg"><button id="wpond" class="on">Ponderado</button><button id="wsimp">Simple</button></div></div>
</div>
<div class="status" id="status"></div>
<div class="kpis">
  <div class="kpi"><span>Operaciones</span><b id="k_n">–</b></div>
  <div class="kpi"><span>Monto operado</span><b id="k_m">–</b></div>
  <div class="kpi"><span>Tasa promedio</span><b id="k_t">–</b></div>
  <div class="kpi"><span>Plazo promedio</span><b id="k_p">–</b></div>
</div>
<div class="card"><h2 id="ctitle">Tasa promedio por plazo</h2><div class="chartbox"><canvas id="chart"></canvas></div></div>
<div class="card"><h2>Detalle por tramo</h2>
<table><thead><tr><th>Plazo</th><th>Operaciones</th><th>Monto</th><th>Tasa pond.</th><th>Tasa simple</th><th>Mín</th><th>Máx</th></tr></thead><tbody id="tbody"></tbody></table>
<footer>Tasas en TNA tal como las informa el MAV. El promedio ponderado usa el monto nominal. Se excluyen las operaciones sin tasa o con tasa 0 (p. ej. valor producto). Tramos: hasta 30 días, 31–60, 61–90, 91–180, 181–365 y más de 365.</footer></div>
</main>
<script>
const BUCKETS=[["1-30 días",0,30],["30-60 días",30,60],["60-90 días",60,90],["90-180 días",90,180],["180-365 días",180,365],["+365 días",365,1e9]];
let rows=[],weighted=true,chart=null;
const $=id=>document.getElementById(id);
const fmtPct=v=>v==null?"–":v.toLocaleString("es-AR",{minimumFractionDigits:2,maximumFractionDigits:2})+"%";
const fmtM=v=>{if(!v)return"–";const a=Math.abs(v);return a>=1e9?(v/1e9).toLocaleString("es-AR",{maximumFractionDigits:2})+" MM":a>=1e6?(v/1e6).toLocaleString("es-AR",{maximumFractionDigits:1})+" M":v.toLocaleString("es-AR",{maximumFractionDigits:0})};
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function status(t,err){$("status").textContent=t||"";$("status").className="status"+(err?" err":"")}

function opts(sel,values,allLabel,keep){
  const prev=keep?sel.value:"";sel.innerHTML="";
  if(allLabel){const o=new Option(allLabel,"");sel.add(o)}
  values.forEach(v=>sel.add(new Option(v||"(sin dato)",v)));
  if(keep&&[...sel.options].some(o=>o.value===prev))sel.value=prev;
}
const uniq=a=>[...new Set(a)].sort((x,y)=>x.localeCompare(y,"es"));

function base(){ // filtros salvo responsable
  return rows.filter(r=>r.tasa!=null&&r.tasa>0&&r.plazo!=null
    &&(!$("moneda").value||r.moneda===$("moneda").value)
    &&(!$("segmento").value||r.segmento===$("segmento").value)
    &&(!$("tipo").value||r.tipo===$("tipo").value));
}
function refreshResp(){
  const b=base();const m={};b.forEach(r=>{m[r.responsable]=(m[r.responsable]||0)+r.monto});
  const vals=Object.keys(m).sort((a,c)=>m[c]-m[a]);
  const prev=$("resp").value;$("resp").innerHTML="";$("resp").add(new Option("Todos ("+vals.length+")",""));
  vals.forEach(v=>$("resp").add(new Option((v||"(sin responsable)")+" · "+fmtM(m[v]),v)));
  if([...$("resp").options].some(o=>o.value===prev))$("resp").value=prev;
}
function render(){
  const d=base().filter(r=>!$("resp").value||r.responsable===$("resp").value);
  const stats=BUCKETS.map(([lab,lo,hi])=>{
    const s=d.filter(r=>r.plazo>lo&&r.plazo<=hi||(lo===0&&r.plazo<=0));
    const m=s.reduce((a,r)=>a+r.monto,0);
    const tp=m?s.reduce((a,r)=>a+r.tasa*r.monto,0)/m:null;
    const ts=s.length?s.reduce((a,r)=>a+r.tasa,0)/s.length:null;
    return {lab,n:s.length,m,tp,ts,min:s.length?Math.min(...s.map(r=>r.tasa)):null,max:s.length?Math.max(...s.map(r=>r.tasa)):null};
  });
  const M=d.reduce((a,r)=>a+r.monto,0);
  $("k_n").textContent=d.length.toLocaleString("es-AR");
  $("k_m").textContent=fmtM(M);
  $("k_t").textContent=fmtPct(weighted?(M?d.reduce((a,r)=>a+r.tasa*r.monto,0)/M:null):(d.length?d.reduce((a,r)=>a+r.tasa,0)/d.length:null));
  $("k_p").textContent=d.length?Math.round(M?d.reduce((a,r)=>a+r.plazo*r.monto,0)/M:0)+" días":"–";
  $("tbody").innerHTML=stats.map(s=>`<tr><td>${s.lab}</td><td>${s.n||"–"}</td><td>${fmtM(s.m)}</td><td>${fmtPct(s.tp)}</td><td>${fmtPct(s.ts)}</td><td>${fmtPct(s.min)}</td><td>${fmtPct(s.max)}</td></tr>`).join("");
  const r=$("resp").value;
  $("ctitle").textContent="Tasa promedio "+(weighted?"ponderada":"simple")+" por plazo"+(r?" · "+r:"");
  const vals=stats.map(s=>weighted?s.tp:s.ts);
  const ink=css("--ink"),muted=css("--muted"),line=css("--line"),acc=css("--accent");
  const cfg={type:"bar",data:{labels:stats.map(s=>s.lab),datasets:[{data:vals,backgroundColor:acc,borderRadius:4,maxBarThickness:70}]},
    options:{maintainAspectRatio:false,animation:false,plugins:{legend:{display:false},
      tooltip:{callbacks:{label:c=>fmtPct(c.raw),afterLabel:c=>stats[c.dataIndex].n+" ops · "+fmtM(stats[c.dataIndex].m)}}},
      scales:{x:{grid:{display:false},ticks:{color:muted}},y:{beginAtZero:true,grid:{color:line},ticks:{color:muted,callback:v=>v+"%"}}}},
    plugins:[{id:"lbl",afterDatasetsDraw(c){const ctx=c.ctx;ctx.save();ctx.fillStyle=ink;ctx.font="600 12px system-ui";ctx.textAlign="center";
      c.getDatasetMeta(0).data.forEach((b,i)=>{if(vals[i]!=null)ctx.fillText(fmtPct(vals[i]),b.x,b.y-6)});ctx.restore()}}]};
  if(chart)chart.destroy();chart=new Chart($("chart"),cfg);
}
function onData(j){
  rows=j.filas;
  opts($("moneda"),uniq(rows.map(r=>r.moneda)),"Todas",true);
  if(!$("moneda").dataset.init){$("moneda").dataset.init=1;if(rows.some(r=>r.moneda==="$"))$("moneda").value="$"}
  opts($("segmento"),uniq(rows.map(r=>r.segmento)),"Todos",true);
  opts($("tipo"),uniq(rows.map(r=>r.tipo)),"Todos",true);
  refreshResp();render();
  status(`${j.fecha.split("-").reverse().join("/")} · ${rows.length} instrumentos operados · `+(j.origen==="api"?"recién bajado del MAV":"desde caché local"));
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
$("resp").onchange=render;
$("wpond").onclick=()=>{weighted=true;$("wpond").classList.add("on");$("wsimp").classList.remove("on");render()};
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
