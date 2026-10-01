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

## Reglas
- Nunca commitear credenciales. Se leen de `.env` (en .gitignore) o variables de entorno.
- `mav_cache/` no se versiona.
- Antes de compartir fuera de la firma, revisar condiciones de uso de datos del MAV.

## Ideas pendientes
- Compartir: (1) red local con `MAV_HOST=0.0.0.0`; (2) snapshot estático publicado; (3) Streamlit Cloud con secrets.
- Backfill histórico respetando el intervalo, y serie temporal de tasa por tramo y SGR.
- Validar el intervalo por endpoint/usuario.
