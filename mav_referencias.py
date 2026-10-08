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


# ------------------------------------------------------------ curva de echeqs avalados
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_larga(fecha_iso):
    a, m, d = (int(x) for x in fecha_iso.split("-"))
    return "%d de %s de %d" % (d, MESES[m - 1], a)


def curva(text, sgrs):
    """ECHEQ avalados en pesos de las SGR elegidas: KPIs y un punto por tramo de la placa
    (tasa ponderada por monto, ubicada en el plazo promedio ponderado del tramo)."""
    ops = [r for r in mav.parse(text)
           if r["tipo"] == "ECHEQ" and r["moneda"] == "$" and r["segmento"] == "Avalado"
           and r["responsable"] in sgrs and r["tasa"] and r["tasa"] > 0 and r["plazo"] is not None]
    monto = sum(r["monto"] for r in ops)
    kpis = {"monto": monto, "n": len(ops),
            "tasa": sum(r["tasa"] * r["monto"] for r in ops) / monto if monto else None,
            "plazo": sum(r["plazo"] * r["monto"] for r in ops) / monto if monto else None}
    puntos = []
    for i in range(len(TRAMOS) + 1):  # los 12 tramos de la placa y uno más para +360 días
        sub = [r for r in ops if (tramo(r["plazo"]) == i if i < len(TRAMOS) else r["plazo"] > 360)]
        m = sum(r["monto"] for r in sub)
        if m:
            puntos.append({"x": sum(r["plazo"] * r["monto"] for r in sub) / m,
                           "y": sum(r["tasa"] * r["monto"] for r in sub) / m,
                           "n": len(sub), "monto": m})
    return kpis, puntos


PAGE_CURVA = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Curva de echeqs avalados</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#14171c;--muted:#5d6673;--line:#e3e6eb}
@media (prefers-color-scheme:dark){:root{--bg:#121417;--card:#1b1e23;--ink:#e8eaed;--muted:#9aa3ad;--line:#2c3138}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{padding:8px 4px 24px}
.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.bar button{font:inherit;font-weight:600;padding:9px 16px;border-radius:8px;border:0;background:#002b55;color:#fff;cursor:pointer}
.bar button.sec{background:var(--card);color:var(--ink);border:1px solid var(--line)}
.bar span{color:var(--muted);font-size:12.5px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
canvas#c{width:100%;height:auto;display:block;border:1px solid var(--line);border-radius:6px}
</style></head><body><main>
<div class="bar"><button id="dl">Descargar PNG</button><button id="cp" class="sec">Copiar imagen</button>
<span id="msg">Imagen de 1600 px de ancho, lista para compartir.</span></div>
<div class="card"><canvas id="c"></canvas></div>
</main>
<script>
const D=__DATA__;
// La imagen siempre sale en modo claro (es para compartir), aunque la app esté en oscuro.
const NAVY="#002b55",AZUL="#1f6fd1",INK="#14171c",GRIS="#6b7480",LINEA="#e6e9ee";
const FONT='"Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif';
const W=1600,PAD=72,ANCHO=W-2*PAD;
const pct=v=>v==null?"–":v.toLocaleString("es-AR",{minimumFractionDigits:2,maximumFractionDigits:2})+"%";
const mill=v=>!v?"–":"$ "+(v/1e6).toLocaleString("es-AR",{maximumFractionDigits:0})+" M";
const cv=document.getElementById("c"),ctx=cv.getContext("2d");

function partir(texto,max){ // corta la nota de SGR en renglones que entren en el ancho
  const pal=texto.split(" "),out=[];let l="";
  pal.forEach(p=>{const t=l?l+" "+p:p;if(ctx.measureText(t).width>max&&l){out.push(l);l=p}else l=t});
  if(l)out.push(l);return out;
}
function logFit(pts){ // tasa = a + b·ln(días), sobre los puntos de cada tramo
  if(pts.length<2)return null;let n=pts.length,sx=0,sy=0,sxx=0,sxy=0;
  pts.forEach(p=>{const l=Math.log(p.x);sx+=l;sy+=p.y;sxx+=l*l;sxy+=l*p.y});
  const den=n*sxx-sx*sx;if(Math.abs(den)<1e-12)return null;
  const b=(n*sxy-sx*sy)/den,a=(sy-b*sx)/n;return x=>a+b*Math.log(x);
}
function grafico(w,h){ // Chart.js en un canvas aparte, sin animación ni escalado por pantalla
  const off=document.createElement("canvas");off.width=w;off.height=h;
  const pts=D.puntos,f=logFit(pts);
  const x0=Math.min(...pts.map(p=>p.x)),x1=Math.max(...pts.map(p=>p.x));
  const line=f?Array.from({length:100},(_,i)=>{const x=x0+(x1-x0)*i/99;return{x,y:f(x)}}):[];
  const ys=pts.map(p=>p.y).concat(line.map(p=>p.y)),lo=Math.min(...ys),hi=Math.max(...ys),pad=Math.max(1,(hi-lo)*.25);
  new Chart(off,{data:{datasets:[
      {type:"line",data:line,borderColor:AZUL,backgroundColor:"rgba(31,111,209,.08)",fill:"start",borderWidth:4,pointRadius:0,tension:0},
      {type:"scatter",data:pts,backgroundColor:NAVY,borderColor:"#fff",borderWidth:3,pointRadius:11}]},
    options:{responsive:false,animation:false,devicePixelRatio:1,layout:{padding:{top:40,right:30,left:6,bottom:4}},
      plugins:{legend:{display:false},tooltip:{enabled:false}},
      scales:{x:{type:"linear",min:0,grid:{color:LINEA},border:{display:false},
                 ticks:{color:GRIS,font:{size:20,family:FONT},callback:v=>v+" d"},
                 title:{display:true,text:"Plazo (días)",color:GRIS,font:{size:20,family:FONT}}},
              y:{suggestedMin:Math.floor(lo-pad),suggestedMax:Math.ceil(hi+pad),grid:{color:LINEA},border:{display:false},
                 ticks:{color:GRIS,font:{size:20,family:FONT},callback:v=>v+"%"}}}},
    plugins:[{id:"lbl",afterDatasetsDraw(c){const g=c.ctx;g.save();g.textAlign="center";
      // tramos cortos quedan juntos: etiquetas alternadas arriba / abajo
      c.getDatasetMeta(1).data.forEach((p,i)=>{g.fillStyle=INK;g.font="600 21px "+FONT;
        g.fillText(pct(pts[i].y),p.x,i%2?p.y+40:p.y-22)});g.restore()}}]});
  return off;
}
function dibujar(){
  ctx.font="20px "+FONT;
  const nota=partir("SGRs seleccionadas: "+(D.sgrs.length?D.sgrs.join("; "):"ninguna"),ANCHO);
  const yKpi=210,hKpi=130,yGraf=yKpi+hKpi+80,hGraf=620,yPie=yGraf+hGraf+46;
  const H=yPie+44+nota.length*30+PAD-20;
  cv.width=W;cv.height=H;
  ctx.font="20px "+FONT;
  ctx.fillStyle="#ffffff";ctx.fillRect(0,0,W,H);
  ctx.fillStyle=NAVY;ctx.fillRect(0,0,W,10);                       // franja superior
  ctx.textBaseline="alphabetic";ctx.textAlign="left";
  ctx.fillStyle=NAVY;ctx.font="700 50px "+FONT;ctx.fillText("Curva de echeqs avalados",PAD,110);
  ctx.fillStyle=GRIS;ctx.font="28px "+FONT;ctx.fillText(D.fecha_larga,PAD,158);
  // tres recuadros del mismo ancho que, juntos, ocupan el ancho del gráfico
  const gap=28,wK=(ANCHO-2*gap)/3;
  [[mill(D.kpis.monto),"Monto total operado"],[pct(D.kpis.tasa),"Tasa promedio ponderada"],
   [D.kpis.plazo?Math.round(D.kpis.plazo)+" días":"–","Plazo promedio ponderado"]].forEach(([v,t],i)=>{
    const x=PAD+i*(wK+gap);
    ctx.fillStyle=NAVY;ctx.beginPath();ctx.roundRect(x,yKpi,wK,hKpi,18);ctx.fill();
    ctx.fillStyle="#ffffff";ctx.font="700 54px "+FONT;ctx.textAlign="center";ctx.textBaseline="middle";
    ctx.fillText(v,x+wK/2,yKpi+hKpi/2+2);
    ctx.fillStyle=GRIS;ctx.font="22px "+FONT;ctx.textBaseline="alphabetic";ctx.fillText(t,x+wK/2,yKpi+hKpi+36);
  });
  if(D.puntos.length)ctx.drawImage(grafico(ANCHO,hGraf),PAD,yGraf);
  else{ctx.fillStyle=GRIS;ctx.font="26px "+FONT;ctx.textAlign="center";ctx.fillText("Sin operaciones para las SGR seleccionadas.",W/2,yGraf+hGraf/2)}
  ctx.textAlign="left";ctx.textBaseline="alphabetic";
  ctx.fillStyle=LINEA;ctx.fillRect(PAD,yPie-30,ANCHO,2);
  ctx.fillStyle=INK;ctx.font="600 22px "+FONT;ctx.fillText("Rosental Inversiones en base a MAV",PAD,yPie+6);
  ctx.fillStyle=GRIS;ctx.font="20px "+FONT;nota.forEach((l,i)=>ctx.fillText(l,PAD,yPie+46+i*30));
}
const nombre="curva_echeqs_avalados_"+D.fecha.split("-").reverse().join("-")+".png";
document.getElementById("dl").onclick=()=>cv.toBlob(b=>{const a=document.createElement("a");a.href=URL.createObjectURL(b);a.download=nombre;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),2000)},"image/png");
document.getElementById("cp").onclick=()=>cv.toBlob(async b=>{
  try{await navigator.clipboard.write([new ClipboardItem({"image/png":b})]);document.getElementById("msg").textContent="Imagen copiada: pegala con Ctrl+V."}
  catch(e){document.getElementById("msg").textContent="El navegador no dejó copiar: usá Descargar PNG."}},"image/png");
(document.fonts&&document.fonts.ready?document.fonts.ready:Promise.resolve()).then(dibujar);
</script></body></html>"""
