#!/usr/bin/env python3
"""
e56 · ¿ACIERTA EL MODELO EL ORDEN EN QUE ARDEN LAS COSAS? (2026-08-09)

POR QUÉ ESTA MEDIDA Y NO LA DE SIEMPRE
Hasta hoy se comparaba la MANCHA final (cicatriz dNBR) con la mancha simulada.
Dos problemas, los dos medidos:
  1. La cicatriz es de un incendio que alguien intentó apagar, y no hay forma de
     saber qué se desplegó (lo planteó el usuario y es cierto: no existe registro
     público por incendio). El modelo simula fuego libre → se compara una cosa
     con otra.
  2. La medida es roma: un círculo tonto saca 0,29-0,34 de Dice porque una mancha
     compacta se solapa con otra mancha compacta. Las diferencias entre modelos
     caen dentro del ruido y llevamos semanas de empates de 0,02.

Aquí se usa un dato que se estaba TIRANDO: **cada detección de VIIRS trae su
hora**. En vez de aplastar todo en una mancha, se mide si el modelo acierta el
ORDEN: las celdas que el satélite vio arder antes, ¿las quema antes el modelo?

Eso ataca los dos problemas a la vez:
  · Los medios tardan horas en organizarse, así que las primeras horas son lo más
    parecido a fuego libre que hay en datos reales. Se informa la medida completa
    y la de la VENTANA TEMPRANA (12 h), que es la menos contaminada.
  · Un círculo predice "arde antes lo más cercano al foco", que no es una
    predicción trivial pero tampoco usa viento ni pendiente ni combustible. Si
    nuestro modelo no le gana AQUÍ, es que no aporta nada.

MÉTRICA: concordancia por parejas (equivalente a un AUC / D de Somers).
De todas las parejas de celdas que ardieron en momentos DISTINTOS, ¿en cuántas
acierta el modelo cuál ardió antes? 0,50 = cara o cruz. 1,00 = perfecto.
Se calcula exacta (no muestreada): VIIRS tiene pocas pasadas, así que las horas
observadas forman pocos grupos y las parejas entre grupos se cuentan con dos
listas ordenadas.

VENTAJA COLATERAL: esta medida NO necesita la cicatriz dNBR, así que entran
también los incendios que se descartaban por "cicatriz > 2x el episodio" (15 de
40 en la tanda nueva). Se evalúa sobre TODAS las cohortes.

Uso:  python3 e56_orden.py        (SOLO=nueva para sólo la tanda u1200+)
"""
import bisect, json, math, os, statistics, sys, time

SCR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCR)
ROOT = '/mnt/qnap/greenhouse3'

os.environ.setdefault('PLAN', f'{SCR}/e6_plan.json')
import validate_block_a as V      # noqa: E402
import e7_calibrate as E          # noqa: E402
import e8_wind                    # noqa: E402

COHORTES = [
    ('calibración 14', 'e6_plan.json', 'e5_cases.json'),
    ('reserva 10', 'e23_plan.json', 'e5_cases.json'),
    ('barrido 40', 'e35_plan.json', 'e34_cases50.json'),
    ('mediterráneo 107', 'e37_plan100.json', 'e37_cases100.json'),
    ('nueva 40', 'e52_plan.json', 'e52_cases.json'),
]
# ── 4-sep · LA COHORTE NO VISTA (§103bis) · SÓLO SI SE PIDE ──────────────────
# Entra únicamente con NO_VISTA=1, y nunca por defecto: los 208 de arriba son la
# cohorte con la que están ancladas TODAS las cifras del documento, y añadir 39
# casos nuevos al montón rompería cada ancla emparejada de golpe (§18). Con
# NO_VISTA=1 y SOLO='no vista' se corre SÓLO sobre lo que jamás eligió un valor.
if os.environ.get('NO_VISTA'):
    COHORTES = COHORTES + [
        ('no vista e60', 'e60_plan.json', 'e60_cases.json'),
        ('no vista e62', 'e62_plan.json', 'e62_cases.json'),
    ]

# ── 16-sep · LA COHORTE DE MADRUGADA (§172) · SÓLO SI SE PIDE ───────────────
# Mismo criterio que `NO_VISTA`: nunca por defecto, porque añadirla al montón
# rompería de golpe todas las anclas emparejadas de los 208 (§18). Entra con
# MADRUGADA=1, y con SOLO='madrugada' se corre SÓLO sobre ella.
# Nace de §171.9: el candidato de `c178` arregla la madrugada y cobra un precio
# en el lado corto, y NINGUNA cohorte existente puede juzgarlo — la no vista da
# 3 incendios de madrugada medibles (17 en la cohorte, pero sólo 3 con una pasada
# de satélite útil en la ventana de 0-3 h) y el juez pide 25.
# Dos ficheros a propósito: la franja de día es el CONTROL, reunido con los MISMOS
# filtros, las mismas zonas y la misma temporada, y cambiando SÓLO la hora
# (comparar igual con igual). El juez de `c172` exige n ≥ 25 en las dos.
if os.environ.get('MADRUGADA'):
    COHORTES = COHORTES + [
        ('madrugada', 'madrug_plan.json', 'madrug_cases.json'),
        ('madrugada control de día', 'madrugd_plan.json', 'madrugd_cases.json'),
    ]

SOLO = os.environ.get('SOLO', '')
VIIRS_R = 187.0            # media huella de VIIRS, como en el resto del arnés
TEMPRANA_H = 12            # ventana "antes de que se organice la extinción"


def aplica():
    """Configuración de producción (v=20260811b). Actualizada aquí a mano cada vez
    que cambia producción de verdad — quien llame a esta función y luego NO pise
    V.LB_MAX/V.USE_WIND_CONF debe obtener la config vigente, no una vieja. (Antes
    fijaba LB_MAX=3,0 de v=20260806k; f24_diagnostico_fondo.py cayó en la trampa
    el 2026-08-11 al no pisarlo — el mismo defecto que ya mordió con FLAM_MIN,
    MIN_ROS y RATIO_MAX. Se corrige aquí, en la fuente, no en cada script.)"""
    V.ROS_MAX = 20.5; V.MIN_ROS = 0.05   # 2026-09-14: 28 → 20,5 con la LST de día (§161). Crudos anteriores: 28 + LST de noche
    V.LB_MAX = 2.5; V.HEAD_MAX = 12.0     # 2026-08-13: 1,5 → 2,5 (c03, máximo interior del Dice)
    V.SLOPE_WIND_K = 45.0; V.LC_POW = 1.0
    V.CURE_BASE = 0.35; V.FLAM_MIN = 0.02
    V.USE_LANDCOVER = True; V.USE_EXTINCTION = False
    V.USE_NB16 = True; V.FLANK_MIN = 0.05
    V.BARRIER_MIN = 0.50; V.SLOPE_QUAD = True
    V.USE_POWER_WIND = True; V.WIND_A, V.WIND_B = 0.60, 1.5
    V.USE_WIND_CONF = True; V.WIND_CONF_WINDOW_H = 3; V.WIND_CONF_GAMMA = 2.0
    # 2026-08-19: LOS INTERRUPTORES DE MECANISMO, TAMBIÉN AQUÍ. Faltaban, y por eso
    # `a21` midió basura en 8 de sus 16 filas: aplicaba variantes con `setattr` sin
    # deshacerlas, así que «sin relieve» dejaba el relieve apagado para todas las
    # siguientes y «freno por edad» lo dejaba encendido. Se arregla EN LA FUENTE,
    # como se hizo con LB_MAX, FLAM_MIN, MIN_ROS y RATIO_MAX — es el mismo defecto
    # por quinta vez. Los valores son los de producción, así que esto NO cambia
    # ningún resultado: sólo impide que una variante se filtre a la siguiente.
    # OJO, y está documentado en `c46_freno_edad.py:207`: quien quiera correr con el
    # freno encendido tiene que ponerlo DESPUÉS de llamar a esta función.
    V.USE_SPOTTING = False; V.USE_TERRAIN = True
    V.USE_AGE_BRAKE = False
    V.AGE_T0_H = 6.0; V.AGE_TAU_H = 12.0; V.AGE_FLOOR = 0.05
    # 2026-08-19 (tarde): y los de INTENSIDAD, que son nuevos. Si no se reinician
    # aquí, una variante que los toque se filtra a todas las siguientes: es
    # exactamente la fuga que invalidó 8 filas de `a21` esta mañana.
    # 2026-08-20: ENCENDIDO, es ya la configuración de producción (ver la nota en
    # `validate_block_a.py`). Quien quiera el control con la regla vieja de
    # velocidad tiene que apagarlo DESPUÉS de llamar a esta función.
    V.USE_INTENSIDAD = True; V.HPUA_MAX = 750.0; V.HPUA_MIN = 40.0
    # 2026-09-15 · CANDIDATO DE MOTOR POR ENTORNO (cola del 15-sep, §169). `MOTOR_CFG` es un JSON
    # {"ROS_MAX": .., "AMP_DIURNA": .., "HUM_S": .., "FASE_H": ..} que se aplica DESPUÉS de producción.
    # Sin la variable no hace nada: producción exacta (lo comprueba el ancla de `c172`).
    if os.environ.get('MOTOR_CFG'):
        for _k, _v in json.loads(os.environ['MOTOR_CFG']).items():
            if not hasattr(V, _k):
                raise SystemExit(f'MOTOR_CFG: {_k} no existe en validate_block_a')
            setattr(V, _k, _v)


def prepara(pl, c):
    """Como el arnés de siempre, pero SIN exigir cicatriz: aquí la referencia son
    las horas de las detecciones, no la mancha final."""
    snap = f'{ROOT}/users/u{pl["uid"]}/snapshot/{pl["date"]}'
    if not os.path.exists(f'{snap}/ndvi_data.json'):
        return None
    V.SNAP = snap
    aplica()
    try:
        fwi = json.load(open(f'{snap}/metadata.json'))['layers']['fire']['stats']['mean']
    except Exception:
        fwi = 30.0
    G = V.Grid(fwi=fwi)
    bbox = V.load_layer('ndvi')[2]
    nc, nr = G.nc, G.nr

    def cell_of(lat, lon):
        j = int((lon - bbox['lon_min']) / (bbox['lon_max'] - bbox['lon_min']) * nc)
        i2 = int((bbox['lat_max'] - lat) / (bbox['lat_max'] - bbox['lat_min']) * nr)
        return i2 * nc + j if 0 <= i2 < nr and 0 <= j < nc else None

    pts = sorted(c['pts'], key=lambda q: q['t'])
    t0 = pts[0]['t']
    seeds = sorted({cell_of(q['lat'], q['lon']) for q in pts if q['t'] <= t0 + 60} - {None})
    if not seeds:
        return None

    # Hora observada por celda = la PRIMERA vez que el satélite la vio arder,
    # extendida a la huella de VIIRS (una detección no es un punto, es ~375 m).
    ri = max(1, int(round(VIIRS_R / G.dym))); rj = max(1, int(round(VIIRS_R / G.dxm)))
    obs_t = {}
    for q in pts:
        k = cell_of(q['lat'], q['lon'])
        if k is None:
            continue
        ci_, cj_ = divmod(k, nc)
        rel = q['t'] - t0
        for di in range(-ri, ri + 1):
            for dj in range(-rj, rj + 1):
                if (di * G.dym) ** 2 + (dj * G.dxm) ** 2 <= VIIRS_R ** 2:
                    ni, nj = ci_ + di, cj_ + dj
                    if 0 <= ni < nr and 0 <= nj < nc:
                        kk = ni * nc + nj
                        if rel < obs_t.get(kk, 1e9):
                            obs_t[kk] = rel
    # Las celdas del foco se quitan: que ardan primero no es una predicción.
    for k in seeds:
        obs_t.pop(k, None)
    if len(set(obs_t.values())) < 2:      # una sola pasada: no hay orden que juzgar
        return None

    met = E.meteo_for(pl['uid'], c['start_date'])
    try:
        ws = e8_wind.series_from(c['start_lat'], c['start_lon'], c['start_date'],
                                 int(c['start_time'][:2]))
        rh = e8_wind.rh_series_from(c['start_lat'], c['start_lon'], c['start_date'],
                                    int(c['start_time'][:2]))
    except Exception:
        ws = rh = None
    if not met:
        if not ws:
            return None
        t12 = ws[:12]
        vx = sum(u * math.sin(math.radians(a)) for u, a in t12) / len(t12)
        vy = sum(u * math.cos(math.radians(a)) for u, a in t12) / len(t12)
        met = dict(wspd=math.hypot(vx, vy),
                   wdir=(math.degrees(math.atan2(vx, vy)) + 360) % 360)

    ci = sum(k // nc for k in seeds) / len(seeds)
    cj = sum(k % nc for k in seeds) / len(seeds)
    circ = {k: math.hypot((k // nc - ci) * G.dym, (k % nc - cj) * G.dxm) for k in obs_t}
    return dict(uid=pl['uid'], snap=snap, G=G, seeds=seeds, obs_t=obs_t, circ=circ,
                met=met, ws=ws, rh=rh, start_h=(int(pts[0]['time'][:2]) + 2) % 24)


def concordancia(obs_t, pred):
    """De las parejas de celdas con hora observada DISTINTA, fracción en que el
    orden predicho coincide. Exacta: se agrupan por hora observada (VIIRS da
    pocas pasadas) y se cuentan las parejas entre grupos con listas ordenadas.
    Los empates de la predicción cuentan medio acierto, que es lo neutral."""
    grupos = {}
    for k, t in obs_t.items():
        grupos.setdefault(t, []).append(pred[k])
    horas = sorted(grupos)
    if len(horas) < 2:
        return None
    for h in horas:
        grupos[h].sort()
    bien = total = 0.0
    for a in range(len(horas)):
        ga = grupos[horas[a]]
        for b in range(a + 1, len(horas)):
            gb = grupos[horas[b]]          # gb ardió DESPUÉS que ga
            for v in ga:
                # aciertos: los de gb con predicción mayor que v
                mayores = len(gb) - bisect.bisect_right(gb, v)
                iguales = bisect.bisect_right(gb, v) - bisect.bisect_left(gb, v)
                bien += mayores + 0.5 * iguales
            total += len(ga) * len(gb)
    return bien / total if total else None


def carga():
    # ── Cargar casos ─────────────────────────────────────────────────────────────
    print('Preparando casos (sin exigir cicatriz)…', flush=True)
    CASOS = []
    for nombre, fplan, fcases in COHORTES:
        if SOLO and SOLO not in nombre:
            continue
        try:
            plan = json.load(open(f'{SCR}/{fplan}'))
            casos = json.load(open(f'{SCR}/{fcases}'))
        except Exception as e:
            print(f'  {nombre}: no disponible ({e})')
            continue
        malos = [p['uid'] for p in plan if casos[p['i']]['start_date'] != p['start']]
        if malos:
            sys.exit(f'ABORTA: {fplan} y {fcases} no casan (u{malos[0]}…).')
        n0 = len(CASOS)
        for pl in plan:
            d = prepara(pl, casos[pl['i']])
            if d:
                CASOS.append(d)
        print(f'  {nombre}: +{len(CASOS)-n0} (total {len(CASOS)})', flush=True)
    
    if not CASOS:
        sys.exit('sin casos evaluables')
    return CASOS
    

def principal(CASOS):
    # ── Medir ────────────────────────────────────────────────────────────────────
    t0 = time.time()
    filas = []
    for c in CASOS:
        V.SNAP = c['snap']
        aplica()
        arr, _ = V.dijkstra(c['G'], c['seeds'], wspd=c['met']['wspd'], wdir=c['met']['wdir'],
                            start_h=c['start_h'], wind_series=c['ws'], rh_series=c['rh'])
        pred = {k: (arr[k] if arr[k] != V.INF else 1e9) for k in c['obs_t']}
        fila = dict(uid=c['uid'],
                    modelo=concordancia(c['obs_t'], pred),
                    circulo=concordancia(c['obs_t'], c['circ']),
                    celdas=len(c['obs_t']))
        temprana = {k: t for k, t in c['obs_t'].items() if t <= TEMPRANA_H * 60}
        if len(set(temprana.values())) >= 2:
            fila['modelo_temp'] = concordancia(temprana, pred)
            fila['circulo_temp'] = concordancia(temprana, c['circ'])
        filas.append(fila)
    
    filas = [f for f in filas if f['modelo'] is not None and f['circulo'] is not None]
    print(f'\n{len(filas)} incendios evaluados · [{(time.time()-t0)/60:.0f} min]\n')
    
    
    def binom_p(k, n, p=0.5):
        return sum(math.comb(n, i) * p**i * (1-p)**(n-i) for i in range(k, n+1)) if n else 1.0
    
    
    def resume(titulo, clave_m, clave_c):
        v = [(f[clave_m], f[clave_c]) for f in filas if f.get(clave_m) is not None]
        if not v:
            print(f'{titulo}: sin datos'); return None
        m = statistics.mean(x for x, _ in v); c = statistics.mean(y for _, y in v)
        gana = sum(1 for x, y in v if x > y)
        p = binom_p(gana, len(v))
        print(f'{titulo} (n={len(v)})')
        print(f'   modelo  {m:.4f}   ← 0,50 es cara o cruz')
        print(f'   círculo {c:.4f}')
        print(f'   gana en {gana}/{len(v)} ({gana/len(v):.0%}) · margen {m-c:+.4f} · p = {p:.4f}')
        return dict(n=len(v), modelo=m, circulo=c, gana=gana, margen=m-c, p=p)
    
    print('═' * 68)
    print('¿ACIERTA EL ORDEN EN QUE ARDIERON LAS CELDAS?')
    print('(de cada 100 parejas de celdas que ardieron en momentos distintos,')
    print(' en cuántas acierta cuál ardió antes)\n')
    todo = resume('EPISODIO COMPLETO', 'modelo', 'circulo')
    print()
    temp = resume(f'VENTANA TEMPRANA (primeras {TEMPRANA_H} h, la menos contaminada '
                  'por la extinción)', 'modelo_temp', 'circulo_temp')
    
    print('\n── lectura ──')
    if todo:
        if todo['modelo'] < 0.55:
            print('  El modelo apenas ordena mejor que el azar: la propagación que')
            print('  simula NO reproduce la secuencia real. Eso ya es una respuesta.')
        elif todo['margen'] < 0.02:
            print('  El modelo ordena bien, pero el círculo también: casi todo el')
            print('  acierto viene de "arde antes lo cercano al foco", no del viento.')
        else:
            print('  El modelo ordena mejor que el círculo: aporta algo más que la')
            print('  distancia al foco. Ésta es la primera señal limpia del proyecto.')
    
    json.dump(dict(n=len(filas), completo=todo, temprana=temp, filas=filas),
              open(f'{SCR}/e56_result.json', 'w'), indent=1)
    print(f'\nGuardado en {SCR}/e56_result.json')


if __name__ == '__main__':
    principal(carga())
