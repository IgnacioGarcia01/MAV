# -*- coding: utf-8 -*-
"""
Análisis histórico sobre los días de Instrumentos Operados guardados en GitHub.

Cada día se reduce a una tabla agregada (instrumento, moneda, segmento, responsable,
tramo) con sumas de monto, tasa×monto, tasa y cantidad, para poder calcular tasas
ponderadas o simples por fecha sin tener en memoria cada operación.
"""

import bisect

import pandas as pd

import mav_operados as mav

TRAMOS = ["1-30 días", "30-60 días", "60-90 días", "90-180 días", "180-365 días", "+365 días"]
_LIMITES = [30, 60, 90, 180, 365]  # límite superior incluido, como en el tablero diario

GRUPOS_TIPO = {"Cheques (ECHEQ + CPD)": {"ECHEQ", "CPD"}}
GRUPOS_MONEDA = {"U$S + U$D": {"U$S", "U$D"}}


def tramo(plazo):
    return bisect.bisect_left(_LIMITES, plazo)


def agregar_dia(fecha_iso, text):
    """DataFrame agregado de un día (solo operaciones con tasa > 0 y plazo)."""
    filas = [r for r in mav.parse(text) if r["tasa"] and r["tasa"] > 0 and r["plazo"] is not None]
    if not filas:
        return pd.DataFrame()
    df = pd.DataFrame(filas)[["tipo", "moneda", "segmento", "responsable", "plazo", "tasa", "monto"]]
    df["tramo"] = df["plazo"].map(tramo)
    df["tm"] = df["tasa"] * df["monto"]
    df["pm"] = df["plazo"] * df["monto"]
    g = (df.groupby(["tipo", "moneda", "segmento", "responsable", "tramo"], as_index=False)
           .agg(monto=("monto", "sum"), tm=("tm", "sum"), ts=("tasa", "sum"), n=("tasa", "size"),
                pm=("pm", "sum")))
    g.insert(0, "fecha", fecha_iso)
    return g


def filtrar(df, tipo, moneda, segmento):
    def en(col, valor, grupos):
        if not valor:
            return pd.Series(True, index=df.index)
        return df[col].isin(grupos.get(valor, {valor}))
    return df[en("tipo", tipo, GRUPOS_TIPO) & en("moneda", moneda, GRUPOS_MONEDA)
              & en("segmento", segmento, {})]


def tasa(g, ponderado):
    return (g["tm"] / g["monto"]) if ponderado else (g["ts"] / g["n"])


def series(df, fechas, por, ponderado, sgrs, tramos, incluir_total):
    """Lista de series {name, data (una por fecha, None si no hubo), total}."""
    def serie(name, sub, total=False):
        g = sub.groupby("fecha")[["monto", "tm", "ts", "n"]].sum()
        g = g[g["n"] > 0]
        t = tasa(g, ponderado).round(4)
        return {"name": name, "total": total,
                "data": [None if f not in t.index else float(t[f]) for f in fechas],
                "n": [0 if f not in g.index else int(g.loc[f, "n"]) for f in fechas],
                "monto": [0.0 if f not in g.index else float(g.loc[f, "monto"]) for f in fechas]}

    if por == "Tramo":
        base = df[df["responsable"].isin(sgrs)] if sgrs else df
        return [serie(TRAMOS[i], base[base["tramo"] == i]) for i in tramos]
    base = df[df["tramo"].isin(tramos)]
    out = [serie("Total del filtro", base, total=True)] if incluir_total or not sgrs else []
    return out + [serie(s or "(sin responsable)", base[base["responsable"] == s]) for s in sgrs]


PAGE = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MAV · Histórico</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#14171c;--muted:#5d6673;--line:#e3e6eb;--accent:#1f4e8c;--total:#8a919c;
  --s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300;--s7:#4a3aa7;--s8:#e34948}
@media (prefers-color-scheme:dark){:root{--bg:#121417;--card:#1b1e23;--ink:#e8eaed;--muted:#9aa3ad;--line:#2c3138;--accent:#6fa0e0;--total:#7d848e;
  --s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300;--s7:#9085e9;--s8:#e66767}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{padding:8px 4px 24px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:14px}
.card h2{font-size:15px;margin:0}.card .sub{color:var(--muted);font-size:12px;margin:2px 0 10px}
.chartbox{position:relative;height:380px}.chartbox.small{height:200px}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:13px}
th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:right}th:first-child,td:first-child{text-align:left}
th{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;font-weight:600}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}
.tablewrap{overflow-x:auto}footer{color:var(--muted);font-size:11.5px;margin-top:8px}
</style></head><body><main>
<div class="card"><h2 id="t1"></h2><div class="sub" id="s1"></div><div class="chartbox"><canvas id="c1"></canvas></div></div>
<div class="card"><h2>Monto operado por día</h2><div class="sub">Suma del monto nominal con los filtros elegidos</div><div class="chartbox small"><canvas id="c2"></canvas></div></div>
<div class="card"><h2>Resumen del período</h2><div class="tablewrap"><table><thead><tr><th>Serie</th><th>Último</th><th>Promedio</th><th>Mín</th><th>Máx</th><th>Días con ops</th><th>Monto</th></tr></thead><tbody id="tb"></tbody></table></div>
<footer>Tasas en TNA. Promedio del período: simple sobre los días con operaciones. Los días sin operaciones para una serie quedan en blanco (la línea se corta).</footer></div>
</main>
<script>
const D=__DATA__;
const $=id=>document.getElementById(id);
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmtPct=v=>v==null?"–":v.toLocaleString("es-AR",{minimumFractionDigits:2,maximumFractionDigits:2})+"%";
const fmtM=v=>{if(!v)return"–";const a=Math.abs(v);return a>=1e9?(v/1e9).toLocaleString("es-AR",{maximumFractionDigits:2})+" MM":a>=1e6?(v/1e6).toLocaleString("es-AR",{maximumFractionDigits:1})+" M":v.toLocaleString("es-AR",{maximumFractionDigits:0})};
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const fl=f=>f.split("-").reverse().slice(0,2).join("/");
const charts=[];
function color(s,i){return s.total?css("--total"):css("--s"+(s.slot+1))}
function draw(){
  charts.forEach(c=>c.destroy());charts.length=0;
  const ink=css("--ink"),muted=css("--muted"),grid=css("--line"),card=css("--card"),many=D.series.length>1;
  $("t1").textContent=D.titulo;$("s1").textContent=D.subtitulo;
  charts.push(new Chart($("c1"),{type:"line",data:{labels:D.fechas.map(fl),datasets:D.series.map((s,i)=>({label:s.name,data:s.data,
      borderColor:color(s,i),backgroundColor:color(s,i),borderWidth:2,borderDash:s.total?[6,4]:[],tension:.15,spanGaps:false,
      pointRadius:D.fechas.length>40?0:3,pointHoverRadius:6,pointBorderColor:card,pointBorderWidth:1.5}))},
    options:{maintainAspectRatio:false,animation:false,interaction:{mode:"index",intersect:false},
      plugins:{legend:{display:many,position:"top",align:"start",labels:{color:ink,usePointStyle:true,pointStyle:"circle",boxWidth:8,boxHeight:8,padding:14}},
        tooltip:{itemSort:(a,b)=>(b.raw??-1)-(a.raw??-1),callbacks:{title:c=>D.fechas[c[0].dataIndex].split("-").reverse().join("/"),
          label:c=>c.dataset.label+": "+fmtPct(c.raw)+"  ("+D.series[c.datasetIndex].n[c.dataIndex]+" ops)"}}},
      scales:{x:{grid:{display:false},ticks:{color:muted,autoSkip:true,maxRotation:0}},y:{grid:{color:grid},ticks:{color:muted,callback:v=>v+"%"}}}}}));
  charts.push(new Chart($("c2"),{type:"bar",data:{labels:D.fechas.map(fl),datasets:[{data:D.volumen,backgroundColor:css("--s1"),borderRadius:3,maxBarThickness:22}]},
    options:{maintainAspectRatio:false,animation:false,plugins:{legend:{display:false},tooltip:{callbacks:{
        title:c=>D.fechas[c[0].dataIndex].split("-").reverse().join("/"),label:c=>fmtM(c.raw)}}},
      scales:{x:{grid:{display:false},ticks:{color:muted,autoSkip:true,maxRotation:0}},y:{beginAtZero:true,grid:{color:grid},ticks:{color:muted,callback:v=>fmtM(v)}}}}}));
  $("tb").innerHTML=D.series.map((s,i)=>{const v=s.data.filter(x=>x!=null),last=[...s.data].reverse().find(x=>x!=null);
    return `<tr><td><span class="dot" style="background:${color(s,i)}"></span>${esc(s.name)}</td><td>${fmtPct(last??null)}</td><td>${fmtPct(v.length?v.reduce((a,b)=>a+b,0)/v.length:null)}</td><td>${fmtPct(v.length?Math.min(...v):null)}</td><td>${fmtPct(v.length?Math.max(...v):null)}</td><td>${v.length}</td><td>${fmtM(s.monto.reduce((a,b)=>a+b,0))}</td></tr>`}).join("");
}
draw();
// En una pestaña oculta los gráficos nacen en 0×0: se redibujan cuando la página toma tamaño.
let lastW=0;new ResizeObserver(()=>{const w=document.body.clientWidth;if(w&&w!==lastW){lastW=w;draw()}}).observe(document.body);
</script></body></html>"""
