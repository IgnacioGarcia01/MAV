# MAV · Tasa promedio por plazo

Tablero local que consulta la API **Instrumentos Operados V3** del Mercado Argentino de Valores (MAV) y muestra la tasa promedio por tramo de plazo de cheques, pagarés y FCE, con filtros por día, moneda, segmento, instrumento y SGR / responsable.

Rosental Inversiones / Research.

## Requisitos
- Python 3.8+ (solo librería estándar).
- Un usuario de Trading MAV con perfil **89 – Consultas Web Services / REST**.

## Uso
1. Copiar `.env.example` como `.env` y completar `MAV_USER` y `MAV_PASS`.
2. Ejecutar `abrir_mav_tasas.bat` (Windows) o `python mav_operados.py`.
3. Se abre `http://127.0.0.1:8765`. Elegir el día y tocar **Consultar**.

Los días descargados quedan en `mav_cache/` y no se vuelven a pedir.

## Límites de la API
- **300 segundos entre llamadas** (verificado: el MAV responde HTTP 200 con el texto
  "Se debe respetar el intervalo de 300 segundos…"). El script controla ese intervalo.
- La API solo acepta CORS desde `www.mav-sa.com.ar`, por eso existe el proxy local en Python.

## Tramos de plazo
1-30, 30-60, 60-90, 90-180, 180-365 y más de 365 días (límite superior incluido).
Tasa ponderada por monto nominal; se excluyen operaciones con tasa vacía o 0.

## Streamlit Cloud
`streamlit_app.py` reutiliza `mav_operados.py` (descarga, caché y la misma página) y solo
reemplaza el selector de día por controles de Streamlit.

1. En share.streamlit.io: **Create app** → repo `IgnacioGarcia01/MAV`, rama `main`,
   archivo `streamlit_app.py`.
2. En **Settings → Secrets** pegar:
   ```toml
   MAV_USER = "tu_usuario"
   MAV_PASS = "tu_clave"
   # APP_PASSWORD = "opcional, pide una clave para ver el tablero"
   ```
3. Conviene dejar la app privada (Settings → Sharing): usa tus credenciales y el cupo de
   una llamada cada 300 s.

La caché `mav_cache/` en la nube se pierde cuando la app se reinicia. Para que no se pierda,
los días pasados se pueden guardar en un **repo privado** de GitHub (`github_cache.py`),
comprimidos (~100 KB por día). Agregar en Secrets:
```toml
GITHUB_TOKEN = "github_pat_..."   # fine-grained, solo ese repo, Contents: Read and write
GITHUB_DATA_REPO = "IgnacioGarcia01/MAV-datos"
```
La app se niega a escribir si el repo de datos es público. El día de hoy se guarda como
*parcial* (como máximo una vez por hora) y se reemplaza por el definitivo cuando el día cierra.
