# -*- coding: utf-8 -*-
"""
Backfill de Instrumentos Operados en el repo privado de datos (MAV-datos).

Busca días hábiles de DESDE a ayer (o a hoy, con BACKFILL_INCLUIR_HOY=1) que todavía
no estén en GitHub, los baja del más reciente al más viejo (5 min entre llamadas: la
API exige 300 s) y los guarda en mav_cache/AAAA-MM-DD.csv.gz. Lo corre GitHub Actions:
.github/workflows/backfill.yml (carga inicial, se apaga sola al completar) y
.github/workflows/cierre_diario.yml (20 h de cada día hábil). También a mano:

    set MAV_USER=... & set MAV_PASS=... & set GITHUB_TOKEN=... & python backfill.py

Variables: MAV_USER, MAV_PASS, GITHUB_TOKEN (Contents: Read and write sobre el repo
de datos), GITHUB_DATA_REPO (por defecto IgnacioGarcia01/MAV-datos), BACKFILL_DESDE
(por defecto 2026-01-02), BACKFILL_DIAS (por defecto 1: días a bajar en esta corrida)
BACKFILL_INCLUIR_HOY (1 = también el día de hoy, para el cierre de las 20 h) y
BACKFILL_FUERA_DE_HORARIO (1 = cortar al entrar en horario de mercado, lun-vie 9 a 18 h,
para no chocar con las consultas desde la app).
No imprime datos de operaciones: solo fecha y cantidad de filas. En Actions deja
completo=true en GITHUB_OUTPUT cuando no falta ningún día.
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


def en_horario_de_mercado():
    ahora = datetime.now(timezone(timedelta(hours=-3)))
    return ahora.weekday() < 5 and 9 <= ahora.hour < 18


def bajar(gh, d):
    """Pide un día al MAV y lo guarda. Devuelve True si quedó guardado."""
    try:
        text, _ = mav.fetch_day(d)
    except RuntimeError as e:
        if not str(e).endswith("respuesta vacía"):
            # El texto del MAV no trae datos de operaciones; se acorta por las dudas.
            print("No se pudo bajar %s: %s" % (d.isoformat(), str(e)[:160]), flush=True)
            return False
        text = ""  # sin operaciones (feriado): se guarda vacío para no volver a pedirlo
    filas = max(0, len([l for l in text.splitlines() if l.strip()]) - 1)
    gh.put(d.isoformat(), text)
    try:
        gh.delete_partial(d.isoformat())
    except Exception:
        pass
    print("Guardado %s (%d filas)." % (d.isoformat(), filas), flush=True)
    return True


def main():
    mav.USER, mav.PASS = os.environ.get("MAV_USER", ""), os.environ.get("MAV_PASS", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not (mav.USER and mav.PASS and token):
        print("Faltan MAV_USER / MAV_PASS / GITHUB_TOKEN: no se hace nada.")
        return 0
    gh = GitHubCache(token, os.environ.get("GITHUB_DATA_REPO") or "IgnacioGarcia01/MAV-datos")
    gh.check_private()
    mav.CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mav_cache")
    mav.STATE_FILE = os.path.join(mav.CACHE_DIR, "_ultima_llamada.txt")

    desde = date.fromisoformat(os.environ.get("BACKFILL_DESDE") or "2026-01-02")
    # BACKFILL_DIAS > 1 (corrida manual): varios días seguidos, esperando el intervalo del MAV.
    cuantos = max(1, int(os.environ.get("BACKFILL_DIAS") or 1))
    # El día en curso solo después de las 19 h: si el cierre de las 20 h arranca tarde (GitHub lo
    # demora, p. ej. a las 4:30 del día siguiente), no se guarda vacío un día que todavía no se operó.
    ahora = datetime.now(timezone(timedelta(hours=-3)))
    incluir_hoy = os.environ.get("BACKFILL_INCLUIR_HOY") == "1" and ahora.hour >= 19
    hasta = hoy_ar() if incluir_hoy else hoy_ar() - timedelta(days=1)
    fuera_de_horario = os.environ.get("BACKFILL_FUERA_DE_HORARIO") == "1"
    fallidos = set()
    for i in range(cuantos):
        if fuera_de_horario and en_horario_de_mercado():
            print("Horario de mercado: se corta acá y sigue a partir de las 18 h.")
            return 0
        pend = pendientes(set(gh.days()), desde, hasta)
        if not pend:
            print("Backfill completo: no faltan días desde %s." % desde)
            salida = os.environ.get("GITHUB_OUTPUT")
            if salida:
                with open(salida, "a") as f:
                    f.write("completo=true\n")
            return 0
        faltan = [d for d in pend if d not in fallidos]
        if not faltan:
            print("Quedan %d días que dieron error en esta corrida; se reintentan en la próxima." % len(pend))
            return 0
        if cuantos == 1:
            # Corrida programada: se rota entre los pendientes según la franja de 5 minutos,
            # así un día que da error siempre (p. ej. un feriado que el MAV rechaza) no frena al resto.
            franja = int(time.time() // 300)
            d = faltan[0] if franja % 4 else faltan[franja // 4 % len(faltan)]
        else:
            d = faltan[0]
        print("[%d/%d] Faltan %d días. Pidiendo %s…" % (i + 1, cuantos, len(faltan), d.isoformat()), flush=True)
        if not bajar(gh, d):
            fallidos.add(d)
        if i + 1 < cuantos:
            time.sleep(mav.MIN_INTERVAL + 5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
