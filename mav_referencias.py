# -*- coding: utf-8 -*-
"""
Placa de referencia "Tasas CDP operadas en el día · Segmento Avalado" (pestaña Referencias).

Arma la tabla de tasas por SGR y tramo de 30 días con los datos de Instrumentos Operados
y dibuja la diapositiva completa (cabecera con logos, "Informe del día", tabla y línea de
cierre) con la geometría de "Tasa - Informe diario editable 2.pptx", a 1600 px de ancho,
para descargarla en PNG. La cabecera es la imagen de la diapositiva con el subtítulo
cambiado a "Segmento Avalado" (assets/header_avalado.png).

Cálculo: cheques (ECHEQ + CPD) en pesos, tasa promedio por tramo (ponderada por monto o
simple), sin operaciones con tasa 0. Tramos por PLAZO: hasta 30 días, 31-60, …, 331-360.
"""

import base64
import os
import unicodedata

import mav_operados as mav

# Tal cual la diapositiva, sin "días" (desde 121 son más compactas: si no, se pisan entre columnas).
TRAMOS = ["5 - 30", "31 - 60", "61 - 90", "91 - 120", "121 -150", "151 -180", "181 -210",
          "211- 240", "241 -270", "271 -300", "301 –330", "331 -360"]
SGR_PLACA = ["Garantizar S.G.R.", "Acindar Pymes S.G.R.", "Argenpymes S.G.R.", "Garantias Bind S.G.R.",
             "Campo Aval S.G.R.", "Integra Pymes S.G.R.", "Fintech S.G.R."]
CHEQUES = {"ECHEQ", "CPD"}


def tramo(plazo):
    if plazo is None or plazo > 360:
        return None
    return max(0, int((plazo - 1) // 30))


def _asset(nombre):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", nombre), "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


HEADER = _asset("header_avalado.png")         # cabecera de la diapositiva, subtítulo "Segmento Avalado"
LOGO_ROSENTAL = _asset("logo_rosental.png")   # recortado de la misma cabecera, fondo transparente


def orden_alfabetico(sgrs):
    """Sin distinguir mayúsculas ni acentos (Garantías = Garantias)."""
    def clave(s):
        return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return sorted(sgrs, key=clave)


def calcular(text, sgrs, ponderado=True):
    """Filas de la placa (solo Avalado, una por SGR en orden alfabético):
    [{"label": nombre de la SGR, "vals": [12 tasas o None]}]."""
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

    return [{"label": s,
             "vals": promedios([r for r in filas if r["segmento"] == "Avalado" and r["responsable"] == s])}
            for s in orden_alfabetico(sgrs)]


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
<span id="msg">Diapositiva completa en PNG (1600 px de ancho, como la placa original).</span></div>
<div class="card"><canvas id="c"></canvas></div>
</main>
<script>
const D=__DATA__;
// Geometría de la diapositiva original de PowerPoint, en EMU (Tasa - Informe diario editable 2.pptx).
const SLIDE_W=13716000, W=1600, k=W/SLIDE_W, px=e=>e*k;
const HEADER={x:600807,y:494649,w:12283305,h:1524367};          // imagen con título y logos
const INFORME={right:12736514-91440,base:2237000};                // cuadro "Informe del día", alineado a la derecha
const TABLA={x:351693,y:2625458,fila:876937,
  cols:[2860430,961292,823913,826624,844061,815780,803027,834517,818772,803026,801540,814926,820712]};
const LINEA={x:954089,w:11782425,gap:13747,h:178056,margen:652994}; // línea azul de cierre y margen inferior
const NAVY="#002b55",TXT="#122a54",A="#bdd7ee",B="#e9ecf4",SEP="#f4fbff",BARRA="#003054";
const FONT='Calibri, Carlito, "Segoe UI", Arial, sans-serif';
const PT=pt=>px(pt*12700);                                          // puntos tipográficos → px
const fmt=v=>v==null?"":v.toLocaleString("es-AR",{minimumFractionDigits:2,maximumFractionDigits:2})+"%";
const cv=document.getElementById("c"),ctx=cv.getContext("2d");
const header=new Image();header.src=D.header;

function dibujar(){
  const n=D.filas.length,finTabla=TABLA.y+TABLA.fila*(n+1),yLinea=finTabla+LINEA.gap;
  const H=Math.round(px(yLinea+LINEA.h+LINEA.margen));
  cv.width=W;cv.height=H;ctx.imageSmoothingQuality="high";
  ctx.fillStyle="#ffffff";ctx.fillRect(0,0,W,H);
  if(header.complete&&header.naturalWidth)ctx.drawImage(header,px(HEADER.x),px(HEADER.y),px(HEADER.w),px(HEADER.h));
  // Informe del día dd-mm-aaaa
  ctx.fillStyle="#0c203b";ctx.font="bold "+PT(24)+"px "+FONT;ctx.textAlign="right";ctx.textBaseline="alphabetic";
  ctx.fillText("Informe del día "+D.fecha.split("-").reverse().join("-"),px(INFORME.right),px(INFORME.base));
  // tabla
  const x0=px(TABLA.x),y0=px(TABLA.y),fh=px(TABLA.fila);
  const xs=[x0];TABLA.cols.forEach(c=>xs.push(xs[xs.length-1]+px(c)));
  const ancho=xs[xs.length-1]-x0;
  ctx.fillStyle=NAVY;ctx.fillRect(x0,y0,ancho,fh);
  ctx.textAlign="center";ctx.textBaseline="middle";
  ctx.fillStyle="#ffffff";ctx.font=PT(16)+"px "+FONT;
  D.tramos.forEach((t,i)=>ctx.fillText(t,(xs[i+1]+xs[i+2])/2,y0+fh/2+1));
  D.filas.forEach((f,j)=>{
    const y=y0+fh*(j+1);
    ctx.fillStyle=j%2?B:A;ctx.fillRect(x0,y,ancho,fh);
    ctx.fillStyle=TXT;ctx.font="bold "+PT(16)+"px "+FONT;ctx.fillText(f.label,(xs[0]+xs[1])/2,y+fh/2+1,xs[1]-xs[0]-14);
    ctx.font=PT(16)+"px "+FONT;
    f.vals.forEach((v,i)=>{if(v!=null)ctx.fillText(fmt(v),(xs[i+1]+xs[i+2])/2,y+fh/2+1)});
  });
  // separadores claros entre celdas, línea de cierre de la tabla
  ctx.fillStyle=SEP;
  xs.slice(1,-1).forEach(x=>ctx.fillRect(Math.round(x)-1,y0,2,fh*(n+1)));
  for(let j=1;j<=n;j++)ctx.fillRect(x0,Math.round(y0+fh*j),ancho,1);
  ctx.fillStyle="#10161d";ctx.fillRect(x0,Math.round(px(finTabla))-1,ancho,2);
  // línea azul de "final" con su muesca, como en la diapositiva
  const lx=px(LINEA.x),lw=px(LINEA.w),ly=px(yLinea),lh=px(LINEA.h);
  ctx.fillStyle=BARRA;ctx.fillRect(lx,ly+lh*0.48,lw,lh*0.45);
  const mx=lx+lw-px(507000);                                        // muesca cerca del extremo derecho
  ctx.beginPath();ctx.moveTo(mx-px(94000),ly+lh*0.5);ctx.lineTo(mx,ly);ctx.lineTo(mx+px(94000),ly+lh*0.5);ctx.fill();
}
const nombre="tasas_cdp_avalados_"+D.fecha.split("-").reverse().join("-")+".png";
document.getElementById("dl").onclick=()=>cv.toBlob(b=>{const a=document.createElement("a");a.href=URL.createObjectURL(b);a.download=nombre;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),2000)},"image/png");
document.getElementById("cp").onclick=()=>cv.toBlob(async b=>{
  try{await navigator.clipboard.write([new ClipboardItem({"image/png":b})]);document.getElementById("msg").textContent="Imagen copiada: pegala con Ctrl+V."}
  catch(e){document.getElementById("msg").textContent="El navegador no dejó copiar: usá Descargar PNG."}},"image/png");
// Se dibuja ya y otra vez cuando terminan de cargar la imagen y las fuentes o cuando la pestaña
// se muestra: en una pestaña oculta de Streamlit esas esperas pueden no resolverse hasta verla.
dibujar();header.addEventListener("load",dibujar);
if(document.fonts&&document.fonts.ready)document.fonts.ready.then(dibujar);
let ultimoAncho=0;new ResizeObserver(()=>{const w=document.body.clientWidth;if(w&&w!==ultimoAncho){ultimoAncho=w;dibujar()}}).observe(document.body);
</script></body></html>"""


# ------------------------------------------------------------ curva de echeqs avalados
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_larga(fecha_iso):
    a, m, d = (int(x) for x in fecha_iso.split("-"))
    return "%d de %s de %d" % (d, MESES[m - 1], a)


def _puntos(ops):
    """Un punto por tramo de la placa (hasta 360 días, como el cuadro): tasa ponderada por monto,
    ubicada en el plazo promedio ponderado del tramo. Lo de más de 360 días no entra en la curva."""
    puntos = []
    for i in range(len(TRAMOS)):
        sub = [r for r in ops if tramo(r["plazo"]) == i]
        m = sum(r["monto"] for r in sub)
        if m:
            puntos.append({"x": sum(r["plazo"] * r["monto"] for r in sub) / m,
                           "y": sum(r["tasa"] * r["monto"] for r in sub) / m,
                           "n": len(sub), "monto": m})
    return puntos


def curva(text, sgrs):
    """ECHEQ avalados en pesos. Los KPIs son del total de avalados (todas las SGR y todos los plazos,
    también los de más de 360 días); las series
    son una curva por SGR elegida, el promedio del mercado (todas las SGR) y el promedio de las
    SGR elegidas (todas sus operaciones juntas)."""
    ops = [r for r in mav.parse(text)
           if r["tipo"] == "ECHEQ" and r["moneda"] == "$" and r["segmento"] == "Avalado"
           and r["tasa"] and r["tasa"] > 0 and r["plazo"] is not None]
    monto = sum(r["monto"] for r in ops)
    kpis = {"monto": monto, "n": len(ops),
            "tasa": sum(r["tasa"] * r["monto"] for r in ops) / monto if monto else None,
            "plazo": sum(r["plazo"] * r["monto"] for r in ops) / monto if monto else None}
    elegidas = orden_alfabetico(sgrs)[:MAX_CURVAS]
    series = [{"name": s, "puntos": _puntos([r for r in ops if r["responsable"] == s])} for s in elegidas]
    mercado = {"name": "Promedio del mercado", "puntos": _puntos(ops)}
    seleccion = {"name": "Promedio SGR seleccionadas",
                 "puntos": _puntos([r for r in ops if r["responsable"] in set(elegidas)])}
    return kpis, {"sgrs": series, "mercado": mercado, "seleccion": seleccion}


MAX_CURVAS = 8  # una por color de la paleta categórica; más curvas no se distinguen


PAGE_CURVA = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Curva de echeqs avalados</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#14171c;--muted:#5d6673;--line:#e3e6eb;--accent:#002b55}
@media (prefers-color-scheme:dark){:root{--bg:#121417;--card:#1b1e23;--ink:#e8eaed;--muted:#9aa3ad;--line:#2c3138;--accent:#6fa0e0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{padding:8px 4px 24px}
.bar{display:flex;gap:10px 18px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
.bar button{font:inherit;font-weight:600;padding:9px 16px;border-radius:8px;border:0;background:#002b55;color:#fff;cursor:pointer}
.bar button.sec{background:var(--card);color:var(--ink);border:1px solid var(--line)}
.bar label{display:flex;gap:6px;align-items:center;cursor:pointer;user-select:none}
.bar .sep{width:1px;height:26px;background:var(--line)}
.hint{color:var(--muted);font-size:12.5px;margin:0 0 10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
canvas#c{width:100%;height:auto;display:block;border:1px solid var(--line);border-radius:6px;cursor:default}
</style></head><body><main>
<div class="bar">
  <button id="dl">Descargar PNG</button><button id="cp" class="sec">Copiar imagen</button><span class="sep"></span>
  <label><input type="checkbox" id="o_puntos"> Puntos</label>
  <label><input type="checkbox" id="o_etiq"> Etiquetas de datos</label>
  <label><input type="checkbox" id="o_merc"> Promedio del mercado</label>
  <label><input type="checkbox" id="o_sel"> Promedio SGR seleccionadas</label>
</div>
<p class="hint" id="msg">Tocá una SGR en las referencias (arriba a la derecha) para mostrar u ocultar su curva. La imagen descargada sale limpia: solo con las curvas visibles.</p>
<div class="card"><canvas id="c"></canvas></div>
</main>
<script>
const D=__DATA__;
// La imagen siempre sale en modo claro (es para compartir), aunque la app esté en oscuro.
const NAVY="#002b55",INK="#14171c",GRIS="#6b7480",GRIS_CLARO="#c3c8cf",LINEA="#e6e9ee";
// Paleta Rosental ampliada (azules, violetas y verdes), validada para daltonismo entre todos los
// pares: 8 colores fijos; el color sigue a la SGR, no a su posición en pantalla.
const PALETA=["#364f8c","#ba67ef","#096338","#507fbb","#38c4a6","#8439c3","#91a8ee","#1d9363"];
const FONT='"Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif';
const W=1600,PAD=72,ANCHO=W-2*PAD;
const pct=v=>v==null?"–":v.toLocaleString("es-AR",{minimumFractionDigits:2,maximumFractionDigits:2})+"%";
const mill=v=>!v?"–":"$ "+(v/1e6).toLocaleString("es-AR",{maximumFractionDigits:0})+" M";
const cv=document.getElementById("c"),ctx=cv.getContext("2d");
const logo=new Image();logo.src=D.logo;

const SERIES=D.series.sgrs.map((s,i)=>({...s,color:PALETA[i],dash:[],visible:true}));
const MERCADO={...D.series.mercado,color:NAVY,dash:[16,10],visible:false,promedio:true};
const SELEC={...D.series.seleccion,color:GRIS,dash:[6,8],visible:false,promedio:true};
const $=id=>document.getElementById(id);
let zonas=[]; // áreas clickeables de las referencias (solo en la vista previa)

function logFit(pts){ // tasa = a + b·ln(días), sobre los puntos de cada tramo
  if(pts.length<2)return null;let n=pts.length,sx=0,sy=0,sxx=0,sxy=0;
  pts.forEach(p=>{const l=Math.log(p.x);sx+=l;sy+=p.y;sxx+=l*l;sxy+=l*p.y});
  const den=n*sxx-sx*sx;if(Math.abs(den)<1e-12)return null;
  const b=(n*sxy-sx*sy)/den,a=(sy-b*sx)/n;return x=>a+b*Math.log(x);
}
function todas(){MERCADO.visible=$("o_merc").checked;SELEC.visible=$("o_sel").checked;return [...SERIES,MERCADO,SELEC]}

function grafico(w,h,visibles,puntos,etiq){ // Chart.js en un canvas aparte, sin animación
  const off=document.createElement("canvas");off.width=w;off.height=h;
  const ds=[],ys=[],marcas=[];
  visibles.forEach(s=>{
    const pts=s.puntos;if(!pts.length)return;
    const f=logFit(pts),x0=Math.min(...pts.map(p=>p.x)),x1=Math.max(...pts.map(p=>p.x));
    const line=f?Array.from({length:100},(_,i)=>{const x=x0+(x1-x0)*i/99;return{x,y:f(x)}}):[];
    ys.push(...pts.map(p=>p.y),...line.map(p=>p.y));
    ds.push({type:"line",data:line,borderColor:s.color,borderWidth:4,borderDash:s.dash,pointRadius:0,tension:0,fill:false});
    // con un solo tramo no hay curva: se muestra el punto aunque los puntos estén apagados
    if(puntos||!f){ds.push({type:"scatter",data:pts,backgroundColor:s.color,borderColor:"#fff",borderWidth:2.5,pointRadius:9});}
    if(etiq)pts.forEach(p=>marcas.push({p,color:s.color}));
  });
  if(!ds.length)return off;
  const lo=Math.min(...ys),hi=Math.max(...ys),pad=Math.max(1,(hi-lo)*.15);
  new Chart(off,{data:{datasets:ds},
    options:{responsive:false,animation:false,devicePixelRatio:1,layout:{padding:{top:30,right:30,left:6,bottom:4}},
      plugins:{legend:{display:false},tooltip:{enabled:false}},
      scales:{x:{type:"linear",min:0,max:360,grid:{color:LINEA},border:{display:false},
                 ticks:{color:GRIS,font:{size:20,family:FONT},stepSize:60,callback:v=>v+" d"},
                 title:{display:true,text:"Plazo (días)",color:GRIS,font:{size:20,family:FONT}}},
              y:{suggestedMin:Math.floor(lo-pad),suggestedMax:Math.ceil(hi+pad),grid:{color:LINEA},border:{display:false},
                 ticks:{color:GRIS,font:{size:20,family:FONT},callback:v=>v+"%"}}}},
    plugins:[{id:"lbl",afterDatasetsDraw(c){if(!marcas.length)return;const g=c.ctx,sx=c.scales.x,sy=c.scales.y;
      g.save();g.textAlign="center";g.font="600 19px "+FONT;
      marcas.forEach(({p},i)=>{const x=sx.getPixelForValue(p.x),y=sy.getPixelForValue(p.y);
        g.lineWidth=5;g.strokeStyle="#fff";g.strokeText(pct(p.y),x,y-16);g.fillStyle=INK;g.fillText(pct(p.y),x,y-16)});
      g.restore()}}]});
  return off;
}

// Referencias arriba a la derecha. En la vista previa llevan casilla y las ocultas quedan grises;
// en la exportación solo aparecen las visibles, sin casillas.
function referencias(g,lista,yTop,exportar){
  g.font="20px "+FONT;g.textBaseline="middle";
  const items=(exportar?lista.filter(s=>s.visible):lista).filter(s=>!s.promedio||s.visible);
  const w=s=>(exportar?0:30)+40+g.measureText(s.name).width;
  const filas=[[]];let ancho=0;
  items.forEach(s=>{const wi=w(s)+26;if(ancho+wi>ANCHO&&filas[filas.length-1].length){filas.push([]);ancho=0}filas[filas.length-1].push(s);ancho+=wi});
  if(!exportar)zonas=[];
  filas.forEach((f,r)=>{
    let x=PAD+ANCHO-f.reduce((a,s)=>a+w(s)+26,0)+26;const y=yTop+r*34;
    f.forEach(s=>{
      const x0=x,on=s.visible;
      if(!exportar&&!s.promedio){ // casilla
        g.strokeStyle=on?NAVY:GRIS_CLARO;g.lineWidth=2;g.strokeRect(x+2,y-10,20,20);
        if(on){g.fillStyle=NAVY;g.fillRect(x+6,y-6,12,12)}x+=30;
      }
      g.strokeStyle=on?s.color:GRIS_CLARO;g.lineWidth=4;g.setLineDash(s.dash);g.beginPath();g.moveTo(x,y);g.lineTo(x+30,y);g.stroke();g.setLineDash([]);
      x+=40;g.fillStyle=on?INK:GRIS_CLARO;g.textAlign="left";g.fillText(s.name,x,y);x+=g.measureText(s.name).width+26;
      if(!exportar&&!s.promedio)zonas.push({x0,x1:x-26,y0:y-16,y1:y+16,s});
    });
  });
  return items.length?filas.length*34:0;
}

function dibujar(g,exportar){
  const lista=todas(),visibles=lista.filter(s=>s.visible);
  const puntos=$("o_puntos").checked,etiq=$("o_etiq").checked;
  const yKpi=210,hKpi=130;
  // altura de las referencias (se mide antes de dimensionar el lienzo)
  g.canvas.width=W;g.canvas.height=10;const hRef=referencias(g,lista,0,exportar);
  const yRef=yKpi+hKpi+70,yGraf=yRef+hRef+(hRef?14:0),hGraf=620,yPie=yGraf+hGraf+46;
  const H=yPie+30+PAD-20;
  g.canvas.width=W;g.canvas.height=H;
  g.fillStyle="#ffffff";g.fillRect(0,0,W,H);
  g.fillStyle=NAVY;g.fillRect(0,0,W,10);
  g.textBaseline="alphabetic";g.textAlign="left";
  g.fillStyle=NAVY;g.font="700 50px "+FONT;g.fillText("Curva de echeqs avalados",PAD,110);
  g.fillStyle=GRIS;g.font="28px "+FONT;g.fillText(D.fecha_larga,PAD,158);
  // tres recuadros del mismo ancho (total de avalados) que, juntos, ocupan el ancho del gráfico
  const gap=28,wK=(ANCHO-2*gap)/3;
  [[mill(D.kpis.monto),"Monto total operado"],[pct(D.kpis.tasa),"Tasa promedio ponderada"],
   [D.kpis.plazo?Math.round(D.kpis.plazo)+" días":"–","Plazo promedio ponderado"]].forEach(([v,t],i)=>{
    const x=PAD+i*(wK+gap);
    g.fillStyle=NAVY;g.beginPath();g.roundRect(x,yKpi,wK,hKpi,18);g.fill();
    g.fillStyle="#ffffff";g.font="700 54px "+FONT;g.textAlign="center";g.textBaseline="middle";g.fillText(v,x+wK/2,yKpi+hKpi/2+2);
    g.fillStyle=GRIS;g.font="22px "+FONT;g.textBaseline="alphabetic";g.fillText(t,x+wK/2,yKpi+hKpi+36);
  });
  referencias(g,lista,yRef+12,exportar);
  if(logo.complete&&logo.naturalWidth){ // marca de agua: logo de Rosental, transparente, en el centro del gráfico
    const lw=ANCHO*0.42,lh=lw*logo.naturalHeight/logo.naturalWidth;
    g.save();g.globalAlpha=0.09;g.drawImage(logo,PAD+(ANCHO-lw)/2,yGraf+(hGraf-lh)/2-20,lw,lh);g.restore();
  }
  if(visibles.some(s=>s.puntos.length))g.drawImage(grafico(ANCHO,hGraf,visibles,puntos,etiq),PAD,yGraf);
  else{g.fillStyle=GRIS;g.font="26px "+FONT;g.textAlign="center";g.fillText("Elegí al menos una curva para mostrar.",W/2,yGraf+hGraf/2)}
  g.textAlign="left";g.textBaseline="alphabetic";
  g.fillStyle=LINEA;g.fillRect(PAD,yPie-30,ANCHO,2);
  g.fillStyle=INK;g.font="600 22px "+FONT;g.fillText("Rosental Inversiones en base a MAV",PAD,yPie+6);
}
const vista=()=>dibujar(ctx,false);
function exportar(cb){const off=document.createElement("canvas");dibujar(off.getContext("2d"),true);off.toBlob(cb,"image/png")}

cv.addEventListener("click",e=>{ // tildar / destildar una SGR desde las referencias
  const r=cv.getBoundingClientRect(),x=(e.clientX-r.left)*cv.width/r.width,y=(e.clientY-r.top)*cv.height/r.height;
  const z=zonas.find(z=>x>=z.x0&&x<=z.x1&&y>=z.y0&&y<=z.y1);if(z){z.s.visible=!z.s.visible;vista()}
});
cv.addEventListener("mousemove",e=>{
  const r=cv.getBoundingClientRect(),x=(e.clientX-r.left)*cv.width/r.width,y=(e.clientY-r.top)*cv.height/r.height;
  cv.style.cursor=zonas.some(z=>x>=z.x0&&x<=z.x1&&y>=z.y0&&y<=z.y1)?"pointer":"default";
});
["o_puntos","o_etiq","o_merc","o_sel"].forEach(id=>$(id).onchange=vista);
const nombre="curva_echeqs_avalados_"+D.fecha.split("-").reverse().join("-")+".png";
$("dl").onclick=()=>exportar(b=>{const a=document.createElement("a");a.href=URL.createObjectURL(b);a.download=nombre;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),2000)});
$("cp").onclick=()=>exportar(async b=>{
  try{await navigator.clipboard.write([new ClipboardItem({"image/png":b})]);$("msg").textContent="Imagen copiada: pegala con Ctrl+V."}
  catch(e){$("msg").textContent="El navegador no dejó copiar: usá Descargar PNG."}});
// Se dibuja ya y otra vez cuando cargan el logo y las fuentes o cuando la pestaña se muestra.
vista();logo.addEventListener("load",vista);
if(document.fonts&&document.fonts.ready)document.fonts.ready.then(vista);
let ultimoAncho=0;new ResizeObserver(()=>{const w=document.body.clientWidth;if(w&&w!==ultimoAncho){ultimoAncho=w;vista()}}).observe(document.body);
</script></body></html>"""
