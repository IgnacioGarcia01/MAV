# Contexto del proyecto (para Claude Code)

## Qué es
Tablero local (`mav_operados.py`, un solo archivo, sin dependencias) que actúa como proxy de la API del MAV
y sirve una página con Chart.js (CDN cdnjs) en `http://127.0.0.1:8765`.
Endpoints locales: `/` (HTML embebido en la constante PAGE), `/api/estado`, `/api/dia?fecha=AAAA-MM-DD[&refrescar=1]`.

## API del MAV (documentación: https://mav-sa.atlassian.net/wiki/spaces/TMA)
- Base: `https://trading.mav-sa.com.ar/cgi-bin/wspd_cgi.sh/WService%3Dwsbroker1/<endpoint>.r?mode=ws&id=USER&password=PASS&...`
- Autenticación: usuario/clave en la query string. Perfil requerido "89 – Consultas Web Services / REST",
  lo crea un usuario del agente con atributo Máster (Gestión de Usuarios → Adm. de Usuarios).
- Respuesta: CSV `;`, coma decimal, **codificación cp1252**, `Content-Disposition: attachment`.
- Errores y rechazos llegan con **HTTP 200** y texto plano en el cuerpo → validar contenido, no status.
- CORS: `Access-Control-Allow-Origin: https://www.mav-sa.com.ar` → un HTML externo no puede llamar directo.
- Desde la nube de Claude el host está bloqueado por el proxy de salida; se probó desde la PC del usuario.

### Endpoints relevantes
| Endpoint | Intervalo | Uso |
|---|---|---|
| `cpd-instrumentos-operados-csv_v3` (fecha) | 300 s (verificado) | el que usa este tablero |
| `cpd-operaciones-csv_v2` (fecha, segmento opc.) | 60 s (doc) | alternativa para backfill; trae tasa, días, segmento, nombre/código responsable |
| `cpd-tasas-csv` (fecha, segmento, instrumento, moneda, liquidacion) | 300 s (doc) | tasas máx/mín/prom agregadas; NO abre por SGR |
| `cpd-registro-operaciones-csv_v5` (desde/hasta ≤ 1 mes) | 300 s | operaciones propias del agente |
| `n-concertacion-csv_v1` (SEN) | 300 s | cauciones/contado propias; no hay datos de mercado de caución |

No verificado todavía: si el intervalo es por endpoint o compartido por usuario, y si cambiar la fecha evita el bloqueo.

## Formato real de Instrumentos Operados V3 (verificado 30/09/2026, 2706 filas)
Columnas (35): IDENT;COD.INSTRUMENTO;TIPO INSTRUMENTO;SEGMENTO;1-NEG;PYME;SELLO;CARAC.;DÍAS ACRED.;FECHA PAGO;
FECHA COBRO;PLAZO;TASA;MONTO;MONEDA;MONTO LIQUIDADO;NOMBRE BANCO;NRO.BANCO;NRO.SUCURSAL;PLAZA;NRO.CHEQUE/PAGARE;
NRO.CTA.LIBR.;ECHEQID;CUSTODIO/REGISTRO;SIN RECURSO;WARRANT/CONTRATO;EXP.LIBRADOR;CODIGO RESPONSABLE;
CUIT RESPONSABLE;NOMBRE RESPONSABLE;CARACTER;CUIT BENEF.;RAZÓN BENEF.;COND. PYME;V.N.

Observaciones:
- Faltan CANJE / CALIFICADO / TIPO GTIA. que la doc dice agregados el 21/09/2026.
- Siguen apareciendo segmentos "No Garantizado Calificado" y "Garantizado Calificado" (la doc dice eliminados).
- NOMBRE RESPONSABLE en Avalado incluye SGR y también bancos/fondos de garantía (Banco Industrial, Comafi,
  Fdo. de Gtía. Pub. La Rioja). En No Garantizado trae el librador; en FCE la empresa obligada al pago.
- Monedas: $, DOL, U$D, U$S. Hay pagarés U$D con tasa 0 → excluidos de promedios.
- Plazo en días: mín 6, máx 1967 en la muestra.
- Referencia para tests (30/09/2026, $, Avalado, Argenpymes S.G.R., ponderado): 25,67 / 25,50 / 26,49 / 27,96 / 31,32 / –

## Streamlit (streamlit_app.py)
- Pestaña **Resumen** (primera): `cpd-tasas-csv` vía `mav_tasas.py`, una llamada por día sin filtros
  (se filtra en el cliente). Curvas de ECHEQ avalados $ y pagarés avalados U$S+U$D con ajuste
  logarítmico sobre el promedio ponderado de cada tramo (1-30, 30-60, 60-90, 90-120, 120-180,
  180-365, +365). Hoy se vuelve a pedir si la foto tiene más de 5 min.
- Contadores de 300 s separados por endpoint (`_ultima_llamada.txt` y `_ultima_llamada_tasas.txt`);
  si el MAV resulta compartir el límite por usuario, responde con el texto de intervalo y se muestra.
- No verificado con datos reales: si los e-cheqs llegan como "ECHEQ" o "CPD" en Tipo Instr.
  (si no hay ECHEQ se usan los CPD y se aclara en el gráfico).
- Pestaña **Instrumentos operados**: la página PAGE de mav_operados.py, con botón Barras / Curva.
- Días pasados en GitHub privado (`github_cache.py`): carpetas `mav_cache/` y `tasas_cache/`.
  El día en curso va en `<carpeta>/parcial/AAAA-MM-DD.csv.gz` (como máximo 1 subida por hora; la hora de
  la foto va en el MTIME del gzip). Tras un reinicio se restaura desde ahí; al guardar el definitivo se
  borra. Si el MAV no responde por un día pasado sin definitivo, se muestra el parcial con aviso.
  Probado con GitHub y MAV falsos (reinicio = borrar mav_cache/ y relanzar), 02/10/2026.
- Las páginas se embeben con `st.iframe` (components.html está obsoleto). En la pestaña que arranca
  oculta Chart.js nace en 0×0: un ResizeObserver sobre body redibuja al mostrarse.

## Datos reales (verificado 02/10/2026 con días guardados)
- TIPO INSTRUMENTO en operados y Tipo Instr. en tasas: ECHEQ, PAGARE, FCE, CPD (pocos) y a veces
  "PAGARE AJUSTE TAMAR". ECHEQ y CPD vienen separados.
- MONEDA: $, DOL, U$D, U$S. ~44 responsables distintos en Avalado por día.

## Pestañas y backfill (desde 02/10/2026)
- Resumen = solo hoy. Instrumentos operados = calendario (botones con key `cal_AAAA-MM-DD`
  pintados por CSS `.st-key-...`) + página con selector múltiple de SGR (máx. 8, paleta categórica
  validada de 8 colores; el color sigue a la SGR mientras está elegida).
- Análisis histórico (`mav_historico.py`): cada día se agrega con pandas por
  (tipo, moneda, segmento, responsable, tramo) y queda en memoria (`st.cache_resource`).
- `backfill.py` + workflow: cron horario, pero GitHub saltea muchas corridas (fin de semana 03-04/10: ~17 de
  ~60, sin errores del MAV). Por eso cada corrida sigue hasta ~70 días o hasta las 9 h de un día hábil; día vacío (feriado) se guarda como "" para no
  repedirlo; 1 de cada 4 corridas rota entre pendientes para que un día con error no trabe el resto.

- Carga inicial (backfill.yml) se autodesactiva con `gh workflow disable` cuando backfill.py deja
  completo=true. Si algún día de 2025 da error siempre (p. ej. el MAV no guarda historia tan vieja),
  nunca queda "completo": habría que subir BACKFILL_DESDE o desactivarla a mano.
- cierre_diario.yml: 20:00 ART lun-vie, BACKFILL_INCLUIR_HOY=1, comparte concurrency con backfill.
  La app abre "hoy" desde GitHub cuando ya está el cierre.

## Reglas
- Nunca commitear credenciales. Se leen de `.env` (en .gitignore) o variables de entorno.
- `mav_cache/` no se versiona.
- Antes de compartir fuera de la firma, revisar condiciones de uso de datos del MAV.

## Ideas pendientes
- Compartir: (1) red local con `MAV_HOST=0.0.0.0`; (2) snapshot estático publicado; (3) Streamlit Cloud con secrets.
- Backfill histórico respetando el intervalo, y serie temporal de tasa por tramo y SGR.
- Validar el intervalo por endpoint/usuario.
