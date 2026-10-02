# -*- coding: utf-8 -*-
"""
Backfill de Instrumentos Operados en el repo privado de datos (MAV-datos).

Cada ejecución hace UNA sola llamada al MAV (la API exige 300 s entre llamadas):
busca un día hábil de DESDE a ayer que todavía no esté en GitHub, lo baja y lo
guarda en mav_cache/AAAA-MM-DD.csv.gz. Lo corre GitHub Actions cada 5 minutos
(.github/workflows/backfill.yml); también se puede correr a mano:

    set MAV_USER=... & set MAV_PASS=... & set GITHUB_TOKEN=... & python backfill.py

Variables: MAV_USER, MAV_PASS, GITHUB_TOKEN (Contents: Read and write sobre el repo
de datos), GITHUB_DATA_REPO (por defecto IgnacioGarcia01/MAV-datos), BACKFILL_DESDE
(por defecto 2026-01-02). No imprime datos de operaciones: solo fecha y cantidad de filas.
"""

import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

os.environ["TZ"] = "America/Argentina/Buenos_Aires"
if hasattr(time, "tzset"):
    time.tzset()

import mav_operados as mav  # noqa: E402
from github_cache import GitHubCache  # noqa: E402


def hoy_ar():
    return datetime.now(timezone(timedelta(hours=-3))).date()


def pendientes(guardados, desde, hasta):
    """Días hábiles (lun-vie) entre desde y hasta que faltan en GitHub, más recientes primero."""
    d, out = hasta, []
    while d >= desde:
        if d.weekday() < 5 and d.isoformat() not in guardados:
            out.append(d)
        d -= timedelta(days=1)
    return out


def main():
    mav.USER, mav.PASS = os.environ.get("MAV_USER", ""), os.environ.get("MAV_PASS", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not (mav.USER and mav.PASS and token):
        print("Faltan MAV_USER / MAV_PASS / GITHUB_TOKEN: no se hace nada.")
        return 0
    gh = GitHubCache(token, os.environ.get("GITHUB_DATA_REPO") or "IgnacioGarcia01/MAV-datos")
    gh.check_private()

    desde = date.fromisoformat(os.environ.get("BACKFILL_DESDE") or "2026-01-02")
    faltan = pendientes(set(gh.days()), desde, hoy_ar() - timedelta(days=1))
    if not faltan:
        print("Backfill completo: no faltan días desde %s." % desde)
        return 0
    # Se rota entre los pendientes según la franja de 5 minutos: si un día da error
    # siempre (p. ej. un feriado que el MAV rechaza), no frena a los demás.
    franja = int(time.time() // 300)
    d = faltan[0] if franja % 4 else faltan[franja // 4 % len(faltan)]
    print("Faltan %d días. Pidiendo %s…" % (len(faltan), d.isoformat()))

    mav.CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mav_cache")
    mav.STATE_FILE = os.path.join(mav.CACHE_DIR, "_ultima_llamada.txt")
    try:
        text, _ = mav.fetch_day(d)
    except RuntimeError as e:
        if str(e).endswith("respuesta vacía"):
            text = ""  # sin operaciones (feriado): se guarda vacío para no volver a pedirlo
        else:
            # El texto del MAV no trae datos de operaciones; se acorta por las dudas.
            print("No se pudo bajar %s: %s" % (d.isoformat(), str(e)[:160]))
            return 0
    filas = max(0, len([l for l in text.splitlines() if l.strip()]) - 1)
    gh.put(d.isoformat(), text)
    try:
        gh.delete_partial(d.isoformat())
    except Exception:
        pass
    print("Guardado %s (%d filas)." % (d.isoformat(), filas))
    return 0


if __name__ == "__main__":
    sys.exit(main())
