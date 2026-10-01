# -*- coding: utf-8 -*-
"""
MAV - Consulta de Tasas (cpd-tasas-csv) · datos del panel "Resumen".

Documentación: https://mav-sa.atlassian.net/wiki/spaces/TMA/pages/210371330
Una fila por grupo (vencimiento, instrumento, segmento, moneda, liquidación...) con
tasa máx./mín./prom., monto nominal/liquidado y cantidad de instrumentos.
Intervalo: 5 minutos entre llamadas. Se lleva un contador propio, separado del de
Instrumentos Operados (mav_operados.py).
"""

import csv
import io
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import mav_operados as mav

API_URL = ("https://trading.mav-sa.com.ar/cgi-bin/wspd_cgi.sh/WService%3Dwsbroker1/"
           "cpd-tasas-csv.r")
MIN_INTERVAL = 300
STATE_FILE = os.path.join(mav.CACHE_DIR, "_ultima_llamada_tasas.txt")


def last_call_ts():
    try:
        with open(STATE_FILE) as f:
            return float(f.read().strip())
    except Exception:
        return 0.0


def wait_seconds():
    return max(0, int(MIN_INTERVAL - (time.time() - last_call_ts())) + 1)


def snapshot_path(d):
    return os.path.join(mav.CACHE_DIR, "tasas_%s.csv" % d.isoformat())


def fetch(d):
    """Texto CSV del día (sin caché). Lanza RuntimeError con mensaje legible."""
    with mav._lock:
        if time.time() - last_call_ts() < MIN_INTERVAL:
            raise RuntimeError("El MAV exige 300 s entre consultas de tasas. Probá de nuevo en %d s."
                               % wait_seconds())
        qs = urllib.parse.urlencode({"mode": "ws", "id": mav.USER, "password": mav.PASS,
                                     "fecha": d.strftime("%d/%m/%y")}, safe="/")
        req = urllib.request.Request(API_URL + "?" + qs,
                                     headers={"User-Agent": "Rosental-Research/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=330) as r:
                raw = r.read()
        except urllib.error.URLError as e:
            raise RuntimeError("No se pudo conectar con el MAV: %s" % e)
        finally:
            os.makedirs(mav.CACHE_DIR, exist_ok=True)
            with open(STATE_FILE, "w") as f:
                f.write(str(time.time()))

    text = mav.decode(raw)
    if text.strip() and not mav.looks_like_data(text):
        raise RuntimeError("El MAV respondió: " + (" ".join(text.split())[:300]))
    return text


def parse(text):
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=";") if any(c.strip() for c in r)]
    if not rows:
        return []
    header = [mav.norm(h) for h in rows[0]]

    def col(name):
        return header.index(name) if name in header else next(
            (i for i, h in enumerate(header) if h.startswith(name)), None)

    ix = {k: col(n) for k, n in {
        "dias": "DIAS", "tipo": "TIPO INSTR", "segmento": "SEGMENTO", "liq": "PLAZO LIQ",
        "moneda": "MONEDA", "monto": "MONTO NOMINAL", "monto_liq": "MONTO LIQUIDADO",
        "tmax": "TASA MAX", "tmin": "TASA MIN", "tasa": "TASA PROM", "cant": "CANT INSTR",
        "calificado": "CALIFICADO", "tipo_gtia": "TIPO GTIA"}.items()}

    def g(r, k):
        i = ix[k]
        return r[i].strip() if i is not None and i < len(r) else ""

    out = []
    for r in rows[1:]:
        out.append({
            "dias": mav.num(g(r, "dias")),
            "tipo": mav.norm(g(r, "tipo")),          # CPD / ECHEQ / PAGARE / FCE
            "segmento": mav.norm(g(r, "segmento")),  # AVALADO / GARANTIZADO / NO GARANTIZADO
            "liq": g(r, "liq"),
            "moneda": g(r, "moneda").upper(),        # $ / U$S / U$D / DOL / EUR
            "monto": mav.num(g(r, "monto")) or 0.0,
            "monto_liq": mav.num(g(r, "monto_liq")) or 0.0,
            "tasa": mav.num(g(r, "tasa")),
            "tmax": mav.num(g(r, "tmax")),
            "tmin": mav.num(g(r, "tmin")),
            "cant": int(mav.num(g(r, "cant")) or 0),
            "calificado": g(r, "calificado"),
            "tipo_gtia": g(r, "tipo_gtia"),
        })
    return out


PAGE = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MAV · Resumen</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#14171c;--muted:#5d6673;--line:#e3e6eb;--c1:#1f4e8c;--c2:#1d7a5c;--band1:rgba(31,78,140,.08);--band2:rgba(29,122,92,.08)}
@media (prefers-color-scheme:dark){:root{--bg:#121417;--card:#1b1e23;--ink:#e8eaed;--muted:#9aa3ad;--line:#2c3138;--c1:#6fa0e0;--c2:#4fc29a;--band1:rgba(111,160,224,.10);--band2:rgba(79,194,154,.10)}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{padding:8px 4px 24px}
.head{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:4px 16px;margin:0 2px 12px}
.head h1{font-size:19px;margin:0}.head p{margin:0;color:var(--muted);font-size:12.5px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin-bottom:14px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;border-top:3px solid var(--line)}
.kpi.c1{border-top-color:var(--c1)}.kpi.c2{border-top-color:var(--c2)}
.kpi span{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.kpi b{display:block;font-size:22px;font-variant-numeric:tabular-nums;margin-top:2px}.kpi small{color:var(--muted);font-size:12px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:860px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.card h2{font-size:15px;margin:0}.card .sub{color:var(--muted);font-size:12px;margin:2px 0 10px}
.chartbox{position:relative;height:400px}
.empty{height:400px;display:flex;align-items:center;justify-content:center;color:var(--muted);text-align:center;padding:20px}
.mini{display:flex;gap:18px;flex-wrap:wrap;margin:0 0 8px;font-size:12.5px;color:var(--muted)}.mini b{color:var(--ink);font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:12.5px;margin-top:10px}
th,td{padding:6px 6px;border-bottom:1px solid var(--line);text-align:right}th:first-child,td:first-child{text-align:left}
th{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;font-weight:600}
footer{color:var(--muted);font-size:11.5px;margin-top:12px}
</style></head><body><main>
<div class="head"><h1>Resumen de tasas · Avalados</h1><p id="meta"></p></div>
<div class="kpis">
  <div class="kpi c1"><span>ECHEQ avalados · $</span><b id="v1">–</b><small id="v1s"></small></div>
  <div class="kpi c2"><span>Pagarés avalados · USD</span><b id="v2">–</b><small id="v2s"></small></div>
  <div class="kpi"><span>Total operado en $</span><b id="vp">–</b><small id="vps"></small></div>
  <div class="kpi"><span>Total operado en USD</span><b id="vu">–</b><small id="vus"></small></div>
</div>
<div class="grid">
  <div class="card"><h2>ECHEQ avalados en pesos</h2><div class="sub" id="s1"></div><div class="mini" id="m1"></div><div id="b1"></div><table id="t1"></table></div>
  <div class="card"><h2>Pagarés avalados en dólares</h2><div class="sub" id="s2"></div><div class="mini" id="m2"></div><div id="b2"></div><table id="t2"></table></div>
</div>
<footer>Fuente: MAV, API Consulta de Tasas. Tasas en TNA. Cada punto es la tasa promedio del tramo ponderada por monto nominal,
ubicada en el plazo promedio del tramo; la línea es el ajuste logarítmico (tasa = a + b·ln(días)) sobre esos puntos.
Pagarés en dólares: monedas U$S y U$D. Se excluyen grupos sin tasa o con tasa 0.</footer>
</main>
<script>
const DATA=__DATA__;
const BUCKETS=[["1-30",0,30],["30-60",30,60],["60-90",60,90],["90-120",90,120],["120-180",120,180],["180-365",180,365],["+365",365,1e9]];
const $=id=>document.getElementById(id);
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmtPct=v=>v==null?"–":v.toLocaleString("es-AR",{minimumFractionDigits:2,maximumFractionDigits:2})+"%";
const fmtM=v=>{if(!v)return"–";const a=Math.abs(v);return a>=1e9?(v/1e9).toLocaleString("es-AR",{maximumFractionDigits:2})+" MM":a>=1e6?(v/1e6).toLocaleString("es-AR",{maximumFractionDigits:1})+" M":v.toLocaleString("es-AR",{maximumFractionDigits:0})};
const fmtN=v=>v.toLocaleString("es-AR");
const rows=DATA.filas.filter(r=>r.dias!=null);
const ok=r=>r.tasa!=null&&r.tasa>0;
// El MAV puede informar los e-cheqs como ECHEQ o como CPD: si hay ECHEQ se usan esos.
const chqTipo=rows.some(r=>r.tipo==="ECHEQ")?"ECHEQ":"CPD";
const S1=rows.filter(r=>r.segmento==="AVALADO"&&r.tipo===chqTipo&&r.moneda==="$");
const S2=rows.filter(r=>r.segmento==="AVALADO"&&r.tipo==="PAGARE"&&(r.moneda==="U$S"||r.moneda==="U$D"));
const USD=["U$S","U$D","DOL"];

function stats(set){
  const v=set.filter(ok);
  const b=BUCKETS.map(([lab,lo,hi])=>{
    const s=v.filter(r=>r.dias>lo&&r.dias<=hi||(lo===0&&r.dias<=0));
    const m=s.reduce((a,r)=>a+r.monto,0);
    return {lab,m,n:s.reduce((a,r)=>a+r.cant,0),
      t:m?s.reduce((a,r)=>a+r.tasa*r.monto,0)/m:null,
      x:m?s.reduce((a,r)=>a+r.dias*r.monto,0)/m:null,
      min:s.length?Math.min(...s.map(r=>r.tmin??r.tasa)):null,
      max:s.length?Math.max(...s.map(r=>r.tmax??r.tasa)):null};
  });
  const M=v.reduce((a,r)=>a+r.monto,0);
  return {b,M,N:set.reduce((a,r)=>a+r.cant,0),
    T:M?v.reduce((a,r)=>a+r.tasa*r.monto,0)/M:null,
    P:M?v.reduce((a,r)=>a+r.dias*r.monto,0)/M:null};
}
function logFit(pts){
  pts=pts.filter(p=>p.x>0&&p.y!=null);if(pts.length<2)return null;
  let n=pts.length,sx=0,sy=0,sxx=0,sxy=0;
  pts.forEach(p=>{const l=Math.log(p.x);sx+=l;sy+=p.y;sxx+=l*l;sxy+=l*p.y});
  const den=n*sxx-sx*sx;if(Math.abs(den)<1e-12)return null;
  const b=(n*sxy-sx*sy)/den,a=(sy-b*sx)/n;return x=>a+b*Math.log(x);
}
function curve(box,st,color,band){
  const pts=st.b.filter(s=>s.t!=null).map(s=>({x:s.x,y:s.t,s}));
  if(!pts.length){$(box).innerHTML='<div class="empty">Sin operaciones para este día.</div>';return}
  $(box).innerHTML='<div class="chartbox"><canvas></canvas></div>';
  const f=logFit(pts),x0=Math.min(...pts.map(p=>p.x)),x1=Math.max(...pts.map(p=>p.x));
  const line=f?Array.from({length:80},(_,i)=>{const x=x0+(x1-x0)*i/79;return{x,y:f(x)}}):[];
  const ys=pts.map(p=>p.y).concat(line.map(p=>p.y)),lo=Math.min(...ys),hi=Math.max(...ys),pad=Math.max(1,(hi-lo)*.25);
  const ink=css("--ink"),muted=css("--muted"),grid=css("--line");
  new Chart($(box).querySelector("canvas"),{data:{datasets:[
      {type:"line",data:line,borderColor:color,backgroundColor:band,fill:"start",borderWidth:2.5,pointRadius:0,tension:0,order:2},
      {type:"scatter",data:pts,backgroundColor:color,borderColor:css("--card"),borderWidth:2,pointRadius:7,pointHoverRadius:9,order:1}]},
    options:{maintainAspectRatio:false,animation:false,layout:{padding:{top:22,right:12}},
      plugins:{legend:{display:false},tooltip:{filter:i=>i.datasetIndex===1,callbacks:{
        title:c=>c[0].raw.s.lab+" días",label:c=>"Tasa "+fmtPct(c.raw.y)+" · plazo prom. "+Math.round(c.raw.x)+" d",
        afterLabel:c=>fmtN(c.raw.s.n)+" instr. · "+fmtM(c.raw.s.m)}}},
      scales:{x:{type:"linear",min:0,grid:{color:grid},ticks:{color:muted,callback:v=>v+" d"},title:{display:true,text:"Plazo (días)",color:muted}},
        y:{suggestedMin:Math.floor(lo-pad),suggestedMax:Math.ceil(hi+pad),grid:{color:grid},ticks:{color:muted,callback:v=>v+"%"}}}},
    plugins:[{id:"lbl",afterDatasetsDraw(c){const ctx=c.ctx;ctx.save();ctx.fillStyle=ink;ctx.font="600 12px system-ui";ctx.textAlign="center";
      c.getDatasetMeta(1).data.forEach((p,i)=>{ctx.fillStyle=ink;ctx.font="600 12px system-ui";
        // tramos cortos quedan juntos: etiquetas alternadas arriba / abajo
        ctx.fillText(fmtPct(pts[i].y),p.x,i%2?p.y+22:p.y-12)});ctx.restore()}}]});
}
function table(id,st){
  $(id).innerHTML="<thead><tr><th>Plazo</th><th>Instr.</th><th>Monto</th><th>Tasa prom.</th><th>Mín</th><th>Máx</th></tr></thead><tbody>"+
    st.b.map(s=>`<tr><td>${s.lab} d</td><td>${s.n?fmtN(s.n):"–"}</td><td>${fmtM(s.m)}</td><td>${fmtPct(s.t)}</td><td>${fmtPct(s.min)}</td><td>${fmtPct(s.max)}</td></tr>`).join("")+"</tbody>";
}
function mini(id,st){$(id).innerHTML=`<span>Tasa prom. <b>${fmtPct(st.T)}</b></span><span>Plazo prom. <b>${st.P?Math.round(st.P)+" d":"–"}</b></span><span>Instrumentos <b>${fmtN(st.N)}</b></span>`}

const st1=stats(S1),st2=stats(S2);
const sum=(set,k)=>set.reduce((a,r)=>a+r[k],0);
const pes=rows.filter(r=>r.moneda==="$"),usd=rows.filter(r=>USD.includes(r.moneda));
$("v1").textContent=fmtM(st1.M);$("v1s").textContent=fmtN(st1.N)+" instrumentos";
$("v2").textContent=fmtM(st2.M);$("v2s").textContent=fmtN(st2.N)+" instrumentos";
$("vp").textContent=fmtM(sum(pes,"monto"));$("vps").textContent=fmtN(sum(pes,"cant"))+" instr. · todos los segmentos";
$("vu").textContent=fmtM(sum(usd,"monto"));$("vus").textContent=fmtN(sum(usd,"cant"))+" instr. · todos los segmentos";
$("s1").textContent="Tasa promedio por plazo"+(chqTipo==="CPD"?" (el MAV los informa como CPD)":"");
$("s2").textContent="Tasa promedio por plazo · U$S y U$D";
mini("m1",st1);mini("m2",st2);table("t1",st1);table("t2",st2);
$("meta").textContent=DATA.fecha.split("-").reverse().join("/")+" · "+DATA.nota;
curve("b1",st1,css("--c1"),css("--band1"));curve("b2",st2,css("--c2"),css("--band2"));
</script></body></html>"""
