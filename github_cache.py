# -*- coding: utf-8 -*-
"""
Caché permanente de días del MAV en un repo de GitHub (API de contenidos, sin dependencias).

Cada día se guarda comprimido como <carpeta>/AAAA-MM-DD.csv.gz (mav_cache/ para
Instrumentos Operados, tasas_cache/ para Consulta de Tasas). El día en curso va
aparte, en <carpeta>/parcial/AAAA-MM-DD.csv.gz: se sobrescribe durante el día y se
borra cuando se guarda el definitivo. Se usa desde
streamlit_app.py para que los días descargados no se pierdan cuando Streamlit
reinicia la app. Configuración (st.secrets o variables de entorno):

    GITHUB_TOKEN       token fine-grained con "Contents: Read and write" solo sobre el repo de datos
    GITHUB_DATA_REPO   p. ej. "IgnacioGarcia01/MAV-datos"  (debe ser PRIVADO)
    GITHUB_DATA_BRANCH opcional, por defecto "main"
"""

import base64
import gzip
import json
import struct
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
FOLDER = "mav_cache"


class GitHubCache:
    def __init__(self, token, repo, branch="main", folder=FOLDER):
        self.token, self.repo, self.branch = token, repo, branch or "main"
        self.folder = folder

    def _req(self, method, path, body=None, accept="application/vnd.github+json", intentos=4):
        """Llamada a la API. Reintenta errores temporales (5xx, límite de uso, red) con espera."""
        for i in range(intentos):
            req = urllib.request.Request(
                API + "/repos/" + self.repo + path, method=method,
                data=json.dumps(body).encode() if body is not None else None,
                headers={"Authorization": "Bearer " + self.token, "Accept": accept,
                         "X-GitHub-Api-Version": "2022-11-28",
                         "User-Agent": "Rosental-Research/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                temporal = e.code >= 500 or e.code == 429 or (e.code == 403 and "rate limit" in str(e.reason).lower())
                if not temporal or i == intentos - 1:
                    raise
            except (urllib.error.URLError, OSError):  # red / timeout (OSError incluye TimeoutError)
                if i == intentos - 1:
                    raise
            time.sleep(10 * (i + 1))

    def check_private(self):
        """Se niega a usar un repo público: los CSV traen libradores, CUIT y beneficiarios."""
        info = json.loads(self._req("GET", ""))
        if not info.get("private"):
            raise RuntimeError("El repo de datos %s es público; no se guardan datos del MAV ahí."
                               % self.repo)

    def days(self):
        """Fechas guardadas (AAAA-MM-DD), más recientes primero."""
        try:
            items = json.loads(self._req("GET", "/contents/%s?ref=%s" % (self.folder, self.branch)))
        except urllib.error.HTTPError as e:
            if e.code == 404:  # carpeta todavía vacía
                return []
            raise
        return sorted((i["name"][:10] for i in items if i["name"].endswith(".csv.gz")),
                      reverse=True)

    def get(self, fecha_iso, con_hora=False):
        """Texto CSV del día, o None si no está guardado. con_hora=True devuelve (texto, timestamp
        de cuando se guardó, tomado del encabezado gzip)."""
        try:
            raw = self._req("GET", "/contents/%s/%s.csv.gz?ref=%s" % (self.folder, fecha_iso, self.branch),
                            accept="application/vnd.github.raw")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        text = gzip.decompress(raw).decode("utf-8")
        return (text, struct.unpack("<I", raw[4:8])[0]) if con_hora else text

    def put(self, fecha_iso, text):
        """Guarda el día. Si otro usuario lo guardó primero (422/409), no hace nada."""
        body = {"message": "Día %s" % fecha_iso, "branch": self.branch,
                # la hora va en el encabezado gzip (algunas versiones de Python ponen 0 si no se indica)
                "content": base64.b64encode(gzip.compress(text.encode("utf-8"), mtime=int(time.time()))).decode()}
        try:
            self._req("PUT", "/contents/%s/%s.csv.gz" % (self.folder, fecha_iso), body)
        except urllib.error.HTTPError as e:
            if e.code not in (409, 422):
                raise

    # ------------------------------------------------- día en curso (parcial)
    def _parcial(self, fecha_iso):
        return "/contents/%s/parcial/%s.csv.gz" % (self.folder, fecha_iso)

    def _sha(self, path):
        try:
            return json.loads(self._req("GET", path + "?ref=" + self.branch))["sha"]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def get_partial(self, fecha_iso):
        """(texto, timestamp de la foto) del día en curso, o None."""
        try:
            raw = self._req("GET", self._parcial(fecha_iso) + "?ref=" + self.branch,
                            accept="application/vnd.github.raw")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        ts = struct.unpack("<I", raw[4:8])[0]  # MTIME del encabezado gzip = hora de la foto
        return gzip.decompress(raw).decode("utf-8"), ts

    def put_partial(self, fecha_iso, text, ts=None):
        path = self._parcial(fecha_iso)
        gz = gzip.compress(text.encode("utf-8"), mtime=int(ts or time.time()))
        body = {"message": "Día %s (parcial)" % fecha_iso, "branch": self.branch,
                "content": base64.b64encode(gz).decode()}
        sha = self._sha(path)
        if sha:
            body["sha"] = sha
        try:
            self._req("PUT", path, body)
        except urllib.error.HTTPError as e:
            if e.code not in (409, 422):  # otro usuario lo actualizó al mismo tiempo
                raise

    def delete_partial(self, fecha_iso):
        path = self._parcial(fecha_iso)
        sha = self._sha(path)
        if sha:
            self._req("DELETE", path, {"message": "Día %s: queda el definitivo" % fecha_iso,
                                       "branch": self.branch, "sha": sha})
