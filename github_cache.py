# -*- coding: utf-8 -*-
"""
Caché permanente de días del MAV en un repo de GitHub (API de contenidos, sin dependencias).

Cada día se guarda comprimido como <carpeta>/AAAA-MM-DD.csv.gz (mav_cache/ para
Instrumentos Operados, tasas_cache/ para Consulta de Tasas). Se usa desde
streamlit_app.py para que los días descargados no se pierdan cuando Streamlit
reinicia la app. Configuración (st.secrets o variables de entorno):

    GITHUB_TOKEN       token fine-grained con "Contents: Read and write" solo sobre el repo de datos
    GITHUB_DATA_REPO   p. ej. "IgnacioGarcia01/MAV-datos"  (debe ser PRIVADO)
    GITHUB_DATA_BRANCH opcional, por defecto "main"
"""

import base64
import gzip
import json
import urllib.error
import urllib.request

API = "https://api.github.com"
FOLDER = "mav_cache"


class GitHubCache:
    def __init__(self, token, repo, branch="main", folder=FOLDER):
        self.token, self.repo, self.branch = token, repo, branch or "main"
        self.folder = folder

    def _req(self, method, path, body=None, accept="application/vnd.github+json"):
        req = urllib.request.Request(
            API + "/repos/" + self.repo + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + self.token, "Accept": accept,
                     "X-GitHub-Api-Version": "2022-11-28",
                     "User-Agent": "Rosental-Research/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()

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

    def get(self, fecha_iso):
        """Texto CSV del día, o None si no está guardado."""
        try:
            raw = self._req("GET", "/contents/%s/%s.csv.gz?ref=%s" % (self.folder, fecha_iso, self.branch),
                            accept="application/vnd.github.raw")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        return gzip.decompress(raw).decode("utf-8")

    def put(self, fecha_iso, text):
        """Guarda el día. Si otro usuario lo guardó primero (422/409), no hace nada."""
        body = {"message": "Día %s" % fecha_iso, "branch": self.branch,
                "content": base64.b64encode(gzip.compress(text.encode("utf-8"))).decode()}
        try:
            self._req("PUT", "/contents/%s/%s.csv.gz" % (self.folder, fecha_iso), body)
        except urllib.error.HTTPError as e:
            if e.code not in (409, 422):
                raise
