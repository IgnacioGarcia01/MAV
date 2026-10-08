# -*- coding: utf-8 -*-
"""
Placa de referencia "Tasas CDP operadas en el día" (pestaña Referencias).

Arma la tabla de tasas por SGR y tramo de 30 días con los datos de Instrumentos Operados
y la dibuja en un canvas al mismo tamaño y con la misma estética que la placa que envía
la firma (1496 × 1023 px, medida sobre la placa del 07/10/2026), para descargarla en PNG
y pegarla en la plantilla.

Cálculo: cheques (ECHEQ + CPD) en pesos, tasa promedio por tramo (ponderada por monto o
simple), sin operaciones con tasa 0. Tramos por PLAZO: hasta 30 días, 31-60, …, 331-360.
"""

import mav_operados as mav

# Etiquetas tal cual la placa original (más compactas desde 121: si no, no entran en la columna).
TRAMOS = ["5 - 30", "31 - 60", "61 - 90", "91 - 120", "121 -150", "151 -180", "181 -210",
          "211- 240", "241 -270", "271 -300", "301 –330", "331 -360"]
SGR_PLACA = ["Garantizar S.G.R.", "Acindar Pymes S.G.R.", "Argenpymes S.G.R.", "Garantias Bind S.G.R.",
             "Campo Aval S.G.R.", "Integra Pymes S.G.R.", "Fintech S.G.R."]
CHEQUES = {"ECHEQ", "CPD"}


def tramo(plazo):
    if plazo is None or plazo > 360:
        return None
    return max(0, int((plazo - 1) // 30))


def calcular(text, sgrs, ponderado=True):
    """Filas de la placa: [{"label", "vals": [12 tasas o None], "grupo": "avalado" | "otro"}]."""
    filas = [r for r in mav.parse(text)
             if r["tipo"] in CHEQUES and r["moneda"] == "$" and r["tasa"] and r["tasa"] > 0]

    def promedios(sub):
        acc = [[0.0, 0.0, 0.0, 0] for _ in TRAMOS]
        for r in sub:
            i = tramo(r["plazo"])
            if i is None:
                continue
            a = acc[i]
            a[0] += r["tasa"] * r["monto"]; a[1] += r["monto"]; a[2] += r["tasa"]; a[3] += 1
        return [(a[0] / a[1] if ponderado and a[1] else a[2] / a[3]) if a[3] else None for a in acc]

    out = [{"label": "Avalado -" + s, "grupo": "avalado",
            "vals": promedios([r for r in filas if r["segmento"] == "Avalado" and r["responsable"] == s])}
           for s in sgrs]
    out.append({"label": "Garantizado EPYME", "grupo": "otro",
                "vals": promedios([r for r in filas if r["segmento"] == "Garantizado"])})
    out.append({"label": "No Garantizado EPYME", "grupo": "otro",
                "vals": promedios([r for r in filas if r["segmento"] == "No Garantizado"])})
    return out


PAGE = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Placa de tasas</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#14171c;--muted:#5d6673;--line:#e3e6eb;--accent:#002b55}
@media (prefers-color-scheme:dark){:root{--bg:#121417;--card:#1b1e23;--ink:#e8eaed;--muted:#9aa3ad;--line:#2c3138;--accent:#6fa0e0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{padding:8px 4px 24px}
.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.bar button{font:inherit;font-weight:600;padding:9px 16px;border-radius:8px;border:0;background:#002b55;color:#fff;cursor:pointer}
.bar button.sec{background:var(--card);color:var(--ink);border:1px solid var(--line)}
.bar span{color:var(--muted);font-size:12.5px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
canvas{width:100%;height:auto;display:block;border:1px solid var(--line)}
</style></head><body><main>
<div class="bar"><button id="dl">Descargar PNG</button><button id="cp" class="sec">Copiar imagen</button>
<span id="msg">PNG de 1496 × 1023 px, listo para pegar en la plantilla.</span></div>
<div class="card"><canvas id="c"></canvas></div>
</main>
<script>
const D=__DATA__;
// Geometría y colores medidos sobre la placa original (px).
const W=1496, HEAD=101, ROW=102, C0=333;
const COLS=[333,445.5,541.5,638,736.5,831.5,925.5,1022.5,1118.5,1211.5,1305.5,1400.5,1496];
const NAVY="#002b55", TXT="#0b2545", A="#bdd7ee", B="#e9ecf4", G="#deeaf6", SEP="#f4fbff", LINEA="#24353f";
const FONT='Calibri, Carlito, "Segoe UI", Arial, sans-serif';
const fmt=v=>v==null?"":v.toLocaleString("es-AR",{minimumFractionDigits:2,maximumFractionDigits:2})+"%";
const cv=document.getElementById("c"),ctx=cv.getContext("2d");
function dibujar(){
  const filas=D.filas,nAv=filas.filter(f=>f.grupo==="avalado").length,H=HEAD+ROW*filas.length+4;
  cv.width=W;cv.height=H;
  ctx.fillStyle="#ffffff";ctx.fillRect(0,0,W,H);
  // encabezado
  ctx.fillStyle=NAVY;ctx.fillRect(0,0,W,HEAD);
  ctx.fillStyle="#ffffff";ctx.font="24px "+FONT;ctx.textAlign="center";ctx.textBaseline="middle";
  D.tramos.forEach((t,i)=>{const x=(COLS[i]+COLS[i+1])/2;ctx.fillText(t,x,HEAD/2-14);ctx.fillText("días",x,HEAD/2+15)});
  // filas: avaladas alternan celeste / gris; Garantizado claro; No Garantizado celeste
  filas.forEach((f,k)=>{
    const y=HEAD+ROW*k;
    ctx.fillStyle=f.grupo==="avalado"?(k%2?B:A):(k===nAv?G:A);ctx.fillRect(0,y,W,ROW);
    ctx.fillStyle=TXT;ctx.font="bold 25px "+FONT;ctx.textAlign="center";ctx.fillText(f.label,C0/2,y+ROW/2+1,C0-16);
    ctx.font="25px "+FONT;
    f.vals.forEach((v,i)=>{if(v!=null)ctx.fillText(fmt(v),(COLS[i]+COLS[i+1])/2,y+ROW/2+1)});
  });
  // separadores claros (verticales y entre filas)
  ctx.fillStyle=SEP;
  COLS.slice(0,-1).forEach(x=>ctx.fillRect(Math.round(x),0,2,H-3));
  for(let k=1;k<filas.length;k++)ctx.fillRect(0,HEAD+ROW*k,W,1);
  // línea oscura entre avaladas y el resto, y línea de cierre
  ctx.fillStyle=LINEA;if(nAv&&nAv<filas.length)ctx.fillRect(0,HEAD+ROW*nAv-1,W,2);
  ctx.fillStyle="#10161d";ctx.fillRect(0,H-3,W,2);
}
const nombre="tasas_cdp_"+D.fecha.split("-").reverse().join("-")+".png";
document.getElementById("dl").onclick=()=>cv.toBlob(b=>{const a=document.createElement("a");a.href=URL.createObjectURL(b);a.download=nombre;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),2000)},"image/png");
document.getElementById("cp").onclick=()=>cv.toBlob(async b=>{
  try{await navigator.clipboard.write([new ClipboardItem({"image/png":b})]);document.getElementById("msg").textContent="Imagen copiada: pegala en la plantilla con Ctrl+V."}
  catch(e){document.getElementById("msg").textContent="El navegador no dejó copiar: usá Descargar PNG."}},"image/png");
(document.fonts&&document.fonts.ready?document.fonts.ready:Promise.resolve()).then(dibujar);
</script></body></html>"""
