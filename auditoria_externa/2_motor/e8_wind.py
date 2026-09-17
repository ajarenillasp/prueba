#!/usr/bin/env python3
"""
Viento HORARIO en el punto del incendio (reanálisis ERA5 vía Open-Meteo, sin clave).

Por qué: hasta ahora el modelo usaba la media DIARIA de la estación Meteostat más
cercana, que puede estar a 100 km. En el incendio del 2025-07-29 la estación decía
viento del 68° (soplando hacia 248°) y el reanálisis en el punto dice 40-50°
(soplando hacia 220-230°). El incendio se propagó hacia el 221°. Además la humedad
relativa real era del 22%, no del 55% de la estación.

Devuelve una serie por hora desde la ignición, que es como sopla el viento de verdad:
cambiando.
"""
import json, os, urllib.request, urllib.parse, datetime

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wind_cache')
os.makedirs(CACHE, exist_ok=True)


# 2026-08-19 · FUENTE DE VIENTO SELECCIONABLE.
# Todo el proyecto ha usado ERA5, que son celdas de ~31 km, y el error de dirección
# (27,1° con referencia buena) se atribuye a esa resolución. ERA5-Land es el MISMO
# reanálisis a ~9 km y con archivo histórico, así que sirve para los incendios de
# 2017-2025 que ya están validados. Lo refutado es el viento DE ESTACIÓN (`c36`: un
# punto medido pierde contra un campo) y la pendiente como sustituto (`c27`);
# ninguna de las dos cosa refuta el mismo dato con 3x de resolución.
# Por defecto vacío = ERA5, para no cambiar nada de lo ya medido. La caché va
# separada por modelo, o se mezclarían las dos fuentes sin avisar.
MODELO = os.environ.get('WIND_MODEL', '').strip()


def hourly(lat, lon, date, days=2):
    """Serie horaria (viento, T, HR) del día del incendio y el siguiente."""
    key = f'{lat:.3f}_{lon:.3f}_{date}_{days}{"_" + MODELO if MODELO else ""}.json'
    p = os.path.join(CACHE, key)
    if os.path.exists(p):
        return json.load(open(p))
    d0 = datetime.date.fromisoformat(date)
    d1 = d0 + datetime.timedelta(days=days - 1)
    q = urllib.parse.urlencode({
        'latitude': f'{lat:.4f}', 'longitude': f'{lon:.4f}',
        'start_date': d0.isoformat(), 'end_date': d1.isoformat(),
        'hourly': 'wind_speed_10m,wind_direction_10m,temperature_2m,relative_humidity_2m',
        'timezone': 'UTC'}
        | ({'models': MODELO} if MODELO else {}))
    url = f'https://archive-api.open-meteo.com/v1/archive?{q}'
    j = json.loads(urllib.request.urlopen(url, timeout=120).read().decode())
    h = j.get('hourly') or {}
    if not h.get('time'):
        raise RuntimeError(f'sin datos horarios: {str(j)[:200]}')
    out = dict(time=h['time'], wspd=h['wind_speed_10m'], wdir=h['wind_direction_10m'],
               temp=h['temperature_2m'], rhum=h['relative_humidity_2m'],
               elevation=j.get('elevation'))
    json.dump(out, open(p, 'w'))
    return out


def series_from(lat, lon, date, hour_utc, n=36):
    """Lista [(km/h, grados)] por hora EMPEZANDO en la hora de la ignición."""
    h = hourly(lat, lon, date, days=3)
    stamp = f'{date}T{int(hour_utc):02d}:00'
    try:
        i0 = h['time'].index(stamp)
    except ValueError:
        i0 = 0
    out = []
    for i in range(i0, min(i0 + n, len(h['time']))):
        ws, wd = h['wspd'][i], h['wdir'][i]
        if ws is None or wd is None:
            ws, wd = (out[-1] if out else (12.0, 270.0))
        out.append((float(ws), float(wd)))
    return out or [(12.0, 270.0)]


def rh_series_from(lat, lon, date, hour_utc, n=36):
    """Humedad relativa por hora desde la ignición (la que mueve el ciclo diurno)."""
    h = hourly(lat, lon, date, days=3)
    stamp = f'{date}T{int(hour_utc):02d}:00'
    try:
        i0 = h['time'].index(stamp)
    except ValueError:
        i0 = 0
    out = []
    for i in range(i0, min(i0 + n, len(h['time']))):
        v = h['rhum'][i]
        out.append(float(v) if v is not None else (out[-1] if out else 45.0))
    return out or [45.0]


def mean_rhum(lat, lon, date, hour_utc, n=12):
    h = hourly(lat, lon, date, days=3)
    stamp = f'{date}T{int(hour_utc):02d}:00'
    try:
        i0 = h['time'].index(stamp)
    except ValueError:
        i0 = 0
    v = [x for x in h['rhum'][i0:i0 + n] if x is not None]
    return sum(v) / len(v) if v else None


if __name__ == '__main__':
    s = series_from(40.36756, -6.27336, '2025-07-29', 14)
    print('primeras 14 horas desde la ignición:')
    for i, (ws, wd) in enumerate(s[:14]):
        print(f'  +{i:>2} h · {ws:>5.1f} km/h del {wd:>3.0f}° → sopla hacia {(wd+180)%360:>3.0f}°')
    print('HR media 12 h:', round(mean_rhum(40.36756, -6.27336, '2025-07-29', 14), 1), '%')
