#!/usr/bin/env python3
"""
motor.py · LAS PIEZAS DE CONTENCIÓN, EN UN SOLO SITIO (2026-08-13)

Extraído de `c07_indirecta.py` cuando hizo falta reutilizarlo en `c09`. Se saca a
módulo a propósito: en este proyecto ya han mordido cuatro veces las copias que
se quedan viejas (constantes atadas a una escala anterior). Una sola definición.

Todo esto es un PUERTO de `js/fire_sim.js`: `fireGeometry`, `candidateAxis`,
`clipToShift`, `buildEdgeRos` y `containment`. Si se toca aquí, hay que tocarlo
allí, o la validación y la app dejan de medir lo mismo.
"""
import math
import os
import sys

sys.path.insert(0, '/mnt/qnap/greenhouse3/scripts/validacion')
import validate_block_a as V   # noqa: E402

# Parámetros del operativo. El que llama puede pisarlos antes de usar el módulo.
T0 = 60.0          # min hasta que llegan los medios
PASO = 90.0        # min por paso de contención
DIRECT = 8.0       # m/min de avance de borde que se puede atacar de frente
HOR = 48 * 60.0    # horizonte
OPS_WINDOW = 12 * 60
# ── 31-ago · QUÉ ELIGE EL ORÁCULO, sin tocar la firma (§99) ─────────────────
# `c114` midió que `mejor_extincion` salva el 69,5% donde la doctrina fija salva el
# 32,5% (§98.2): un factor 2,1 que vive entero en DÓNDE se pone la línea. Para saber
# si ese hueco es un mal valor por defecto —arreglable— o pura ventaja de saber ya
# por dónde irá el fuego —no desplegable— hace falta ver qué candidata gana y cuánto
# salva CADA UNA, no sólo la mejor.
#
# ⚠ La firma NO cambia: la llaman `c11`, `c16`, `c31`, `c33` y `a28`, y todas tienen
# que seguir reproduciendo. Se expone con el mismo patrón que `AMP_DIURNA` (§95-C) y
# `NOCHE_K` (§97): un interruptor apagado por defecto, así que quien no lo toque
# obtiene exactamente lo de ayer. Con `fork` cada trabajador tiene su copia, que es
# lo que hace seguro el global.
REGISTRA_CANDIDATAS = False
ULTIMA_TABLA = None        # {'directo': quemado, '0.30_0': quemado, ...} tras la llamada
# ═══════════════════════════════════════════════════════════════════════════════
# 4-sep (tarde) · ⚠⚠ EL DEFECTO HA CAMBIADO. LEER ESTO ANTES DE REPRODUCIR NADA.
# ═══════════════════════════════════════════════════════════════════════════════
# Estas eran las candidatas de colocación de la línea indirecta, y eran las dos
# cosas mal (§105): las tres fracciones dejaban el óptimo EN EL BORDE de la rejilla
# y las rotaciones no pagan en ciego. `c123` abrió el barrido a nueve fracciones
# sin rotar sobre 208 incendios y 10 celdas, y el óptimo salió INTERIOR, en 0,45.
#
# El 4-sep por la tarde eso entró en la app (`js/fire_sim.js:4480`,
# `?v=20260904a`), así que el defecto de aquí **tiene que ser el mismo** o la
# validación y la app dejan de medir lo mismo — que es el aviso del encabezado de
# este fichero y ya ha mordido cuatro veces.
#
# ⛔⛔ CONSECUENCIA, Y NO ES MENOR: `c120` y `c121` (§100, §103) se corrieron con
#     la rejilla VIEJA. Para reproducirlos bit a bit **hay que pedirla**:
#
#         FRACS=0.3,0.5,0.7 ROTS=0,-30,30 python3 c121_techo_colocacion.py
#
#     Sin eso NO reproducen, y el ancla de 12,58% lo cazará. `c123` se corrió con
#     la rejilla nueva, que ahora es el defecto, así que reproduce sin poner nada.
FRACS = [float(x) for x in os.environ.get(
    'FRACS', '0.15,0.25,0.35,0.45,0.55,0.65,0.75,0.85,0.95').split(',')]
ROTS = [int(x) for x in os.environ.get('ROTS', '0').split(',')]


def geometria(arr, G, seeds):
    """Puerto de fireGeometry(): centro, rumbo de cabeza, alcance y semianchura
    DENTRO de la ventana operativa."""
    nr, nc, N = G.nr, G.nc, G.nr * G.nc
    ci = sum(k // nc for k in seeds) / len(seeds)
    cj = sum(k % nc for k in seeds) / len(seeds)
    cel = [(k, arr[k]) for k in range(N) if arr[k] != V.INF]
    if len(cel) < 8:
        return None
    cel.sort(key=lambda x: -x[1])
    cab = cel[:max(1, int(len(cel) * 0.15))]
    hi = sum(k // nc for k, _ in cab) / len(cab)
    hj = sum(k % nc for k, _ in cab) / len(cab)
    drow, dcol = hi - ci, hj - cj
    mag = math.hypot(drow, dcol) or 1.0
    drow /= mag; dcol /= mag
    reach = halfw = 0.0
    for k, a in cel:
        if a > OPS_WINDOW:
            continue
        di, dj = k // nc - ci, k % nc - cj
        reach = max(reach, di * drow + dj * dcol)
        halfw = max(halfw, abs(di * (-dcol) + dj * drow))
    return dict(ci=ci, cj=cj, drow=drow, dcol=dcol,
                reach=max(reach, 2.0), halfw=max(halfw, 2.0))


def eje_candidato(G, geo, frac, rot_deg, arr):
    """Puerto de candidateAxis(): línea perpendicular a la cabeza, anclada donde
    deja de haber combustible o donde el fuego ya no llega."""
    nr, nc = G.nr, G.nc
    rot = math.radians(rot_deg); cs, sn = math.cos(rot), math.sin(rot)
    drow = geo['drow'] * cs - geo['dcol'] * sn
    dcol = geo['drow'] * sn + geo['dcol'] * cs
    prow, pcol = -dcol, drow
    lr = geo['ci'] + drow * geo['reach'] * frac
    lc = geo['cj'] + dcol * geo['reach'] * frac
    maxT = geo['halfw'] + 6
    izq, der = [], []
    for dirn, dest in ((1, der), (-1, izq)):
        anclado = 0
        t = 0.0 if dirn == 1 else 1.0
        while t <= maxT:
            row = int(round(lr + prow * t * dirn)); col = int(round(lc + pcol * t * dirn))
            if not (0 <= row < nr and 0 <= col < nc):
                break
            k = row * nc + col
            if dest and dest[-1] == k:
                t += 0.5; continue
            if V.ROS_MAX * G.fuel[k] * G.ease[k] < V.MIN_ROS or arr[k] == V.INF:
                anclado += 1
                if anclado >= 2:
                    break
            else:
                anclado = 0
            dest.append(k)
            t += 0.5
    izq.reverse()
    return izq + der


# ── 2026-09-17 · RENDIMIENTO DE LÍNEA POR CELDA (§176) · APAGADO POR DEFECTO ──
# Hasta hoy la línea se abre al MISMO ritmo en todas partes: `rate_min` es un
# número plano. Las tablas NWCG 2021 (`literatura/NWCG_2021_FireLineProductionRates.pdf`,
# bajadas hoy de frames.gov) publican el rendimiento SOSTENIDO de una cuadrilla de 20
# por modelo de combustible y por directo/indirecto, y la diferencia no es pequeña:
# en línea INDIRECTA —que es la que abre este simulador— una cuadrilla Tipo I hace
# 9,5 ch/h en pasto (191 m/h), 6,9 en hojarasca de arbolado (139) y 4,9 en matorral
# (99). El plano de 126 m/h de `c168` (dato MITECO/BRIF) es una BUENA MEDIA de esos
# tres, así que lo que esto añade no es nivel: es el PATRÓN espacial.
# `RATE_CELDA` es una función k -> m/min para la celda k. Con `None` (defecto) el
# camino es el de siempre, línea a línea: el ancla de cualquier corrida anterior
# tiene que salir exacta.
RATE_CELDA = None
# Si `RATE_CELDA_T` está puesto, la función se llama `RATE_CELDA(k, t)` con `t` = MINUTOS YA
# TRABAJADOS en esta línea, que es lo que pide la ley de fatiga de Ortega (2023). Bandera
# explícita y no introspección de la firma: las lambdas con argumentos por defecto engañan a
# `co_argcount` y eso habría sido un fallo de arnés silencioso.
RATE_CELDA_T = False


def tiempos_desde_el_medio(G, eje, t0, rate_min, minutos):
    """La línea se abre desde el centro hacia los dos lados y sólo hasta donde da
    el turno (clipToShift(mid=true) + buildTimes, con dos frentes de obra).

    Con `RATE_CELDA` puesto, el ritmo lo pone cada celda y el turno se gasta en
    TIEMPO en vez de en metros. Es algebraicamente lo mismo cuando el ritmo es
    constante (t = acc/rate y el tope acc<=rate*minutos <=> tiempo<=minutos), pero
    el camino viejo se deja intacto para no tocar ninguna corrida anterior."""
    if len(eje) < 2:
        return []
    if RATE_CELDA is not None:
        return _tiempos_por_celda(G, eje, t0, minutos)
    nc = G.nc
    mid = len(eje) // 2
    Lmax = rate_min * min(max(minutos, 30.0), 12 * 60)
    fuera = [(eje[mid], t0)]
    lo = hi = mid
    acc = 0.0

    def d(a, b):
        return math.hypot((b % nc - a % nc) * G.dxm, (b // nc - a // nc) * G.dym)

    while lo > 0 or hi < len(eje) - 1:
        dlo = d(eje[lo - 1], eje[lo]) if lo > 0 else float('inf')
        dhi = d(eje[hi], eje[hi + 1]) if hi < len(eje) - 1 else float('inf')
        usa_lo = dlo <= dhi
        paso = dlo if usa_lo else dhi
        if acc + paso > Lmax:
            break
        acc += paso
        if usa_lo:
            lo -= 1; fuera.append((eje[lo], t0 + acc / max(rate_min, 1e-6) * 2))
        else:
            hi += 1; fuera.append((eje[hi], t0 + acc / max(rate_min, 1e-6) * 2))
    return fuera


def _tiempos_por_celda(G, eje, t0, minutos):
    """Igual que `tiempos_desde_el_medio` pero el ritmo lo pone `RATE_CELDA(k)`."""
    nc = G.nc
    mid = len(eje) // 2
    Tdisp = min(max(minutos, 30.0), 12 * 60)
    fuera = [(eje[mid], t0)]
    lo = hi = mid
    acct = 0.0

    def d(a, b):
        return math.hypot((b % nc - a % nc) * G.dxm, (b // nc - a // nc) * G.dym)

    def r(a, b, t):
        # el tramo entre dos celdas cuesta lo que cuesta la media de las dos
        ra, rb = (RATE_CELDA(a, t), RATE_CELDA(b, t)) if RATE_CELDA_T else (RATE_CELDA(a), RATE_CELDA(b))
        return max((ra + rb) / 2.0, 1e-6)

    while lo > 0 or hi < len(eje) - 1:
        dlo = d(eje[lo - 1], eje[lo]) if lo > 0 else float('inf')
        dhi = d(eje[hi], eje[hi + 1]) if hi < len(eje) - 1 else float('inf')
        usa_lo = dlo <= dhi
        paso = dlo if usa_lo else dhi
        k_a, k_b = (eje[lo - 1], eje[lo]) if usa_lo else (eje[hi], eje[hi + 1])
        dt = paso / r(k_a, k_b, acct)
        if acct + dt > Tdisp:
            break
        acct += dt
        if usa_lo:
            lo -= 1; fuera.append((eje[lo], t0 + acct * 2))
        else:
            hi += 1; fuera.append((eje[hi], t0 + acct * 2))
    return fuera


def edge_ros(arr, G):
    """Velocidad de avance del BORDE (m/min). Puerto de buildEdgeRos()."""
    nr, nc, N = G.nr, G.nc, G.nr * G.nc
    out = [V.INF] * N
    for k in range(N):
        a = arr[k]
        if a == V.INF:
            continue
        i, j = divmod(k, nc)
        best = 0.0
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if not di and not dj:
                    continue
                ni, nj = i + di, j + dj
                if not (0 <= ni < nr and 0 <= nj < nc):
                    continue
                b = arr[ni * nc + nj]
                if b == V.INF or b <= a or b - a <= 1e-6:
                    continue
                v = math.hypot(dj * G.dxm, di * G.dym) / (b - a)
                if v > best:
                    best = v
        if best > 0:
            out[k] = best
    return out


def sim(c, bt):
    return V.dijkstra(c['G'], c['seeds'], bt=bt, wspd=c['met']['wspd'],
                      wdir=c['met']['wdir'], start_h=c['start_h'],
                      wind_series=c['ws'], rh_series=c['rh'])[0]


def quemado(arr):
    return sum(1 for a in arr if a != V.INF and a <= HOR)


def umbral_intensidad(E):
    """Qué intensidad aguanta un medio que produce `E` m/h de línea.

    Tabla 1 de Andrews & Rothermel 1982: por debajo de 346 kW/m la herramienta
    manual aguanta el fuego en cabeza o flancos; entre 346 y 1.731 la manual ya no
    puede en la cabeza pero la MAQUINARIA y los AVIONES sí; por encima de 1.731 el
    control en la cabeza es inefectivo.

    El corte por producción de línea (500 m/h) separa cuadrillas y brigadas —que
    trabajan con herramienta manual y motosierra— de la maquinaria pesada. Es un
    supuesto de correspondencia, no un dato: se deja explícito para poder discutirlo.
    """
    return V.I_MANUAL if E <= 500.0 else V.I_MAQUINA


def directo(c, E, arr, edge, bt0, i_max=None):
    """Ataque directo sobre el perímetro trabajable, lo más lento primero.
    Puerto de containment().

    Con `V.USE_INTENSIDAD` la condición de trabajabilidad deja de ser la VELOCIDAD
    del borde y pasa a ser la INTENSIDAD LINEAL, que es lo que usa la doctrina.
    Medido en `a32`: con el umbral de velocidad, en 11 de los 13 combustibles se
    manda gente a fuego que no puede trabajar, y se le niega al avión toda la banda
    donde sí sirve.
    """
    G = c['G']; nr, nc = G.nr, G.nc; N = nr * nc
    if i_max is None:
        i_max = umbral_intensidad(E)
    bt = list(bt0)
    held = bytearray(N)
    resto = 0.0
    for t in range(int(T0), int(HOR) + 1, int(PASO)):
        per = []
        for k in range(N):
            a = arr[k]
            if a == V.INF or a > t or held[k]:
                continue
            if V.USE_INTENSIDAD:
                if V.intensidad(edge[k] if edge[k] != V.INF else 0.0,
                                G.fuel[k]) > i_max:
                    continue
            elif edge[k] > DIRECT:
                continue
            i, j = divmod(k, nc)
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    if not di and not dj:
                        continue
                    ni, nj = i + di, j + dj
                    if not (0 <= ni < nr and 0 <= nj < nc):
                        continue
                    b = arr[ni * nc + nj]
                    if b == V.INF or b > t:
                        per.append(k); break
                else:
                    continue
                break
        if not per:
            continue
        if V.USE_INTENSIDAD:
            per.sort(key=lambda k: V.intensidad(
                edge[k] if edge[k] != V.INF else 0.0, G.fuel[k]))
        else:
            per.sort(key=lambda k: edge[k])
        # El cupo SOBRANTE se arrastra al paso siguiente. Sin esto, cada paso de
        # 90 min tiraba a la basura lo que no llegaba a completar una celda: con
        # 324 m/h son 486 m de cupo contra celdas de 71 m -> 6 celdas y 60 m
        # perdidos, un 12% del esfuerzo, EN CADA PASO. Es el mismo fallo que ya
        # mordió en `aereo.moja()` con las descargas parciales (2026-08-18), y lo
        # detectó el usuario razonando sobre la granularidad de la rejilla.
        # 2026-09-17 · con `RATE_CELDA` el cupo del paso se gasta en TIEMPO y no en
        # metros: cada celda cuesta lo que cuesta cortarla EN ESE COMBUSTIBLE
        # (§179). Con ritmo constante es lo mismo —`PASO` minutos a `E`/60 m/min son
        # `E·PASO/60` metros— así que el camino viejo no se toca.
        por_tiempo = RATE_CELDA is not None
        cupo = (PASO + resto) if por_tiempo else (E * PASO / 60.0 + resto)
        tocado = False
        for k in per:
            # Hay que PODER PAGAR la celda entera antes de cortarla. Antes la
            # comprobación iba antes de descontar (`if cupo <= 0`), así que
            # siempre caía una celda gratis por paso: una cuadrilla de 60 m/h
            # con 15 m de cupo cortaba una celda de 71 m igual. Efecto medido
            # (`a12`/`a13`, 2026-08-18): 60, 120 y 324 m/h daban EXACTAMENTE el
            # mismo resultado en todas las tablas del día, porque a ninguna le
            # mandaba su cupo real. Con el resto arrastrándose (ver arriba), una
            # cuadrilla pequeña ahora ACUMULA varios pasos hasta pagarse una
            # celda, que es lo que hace de verdad.
            coste = (G.dxm / max(RATE_CELDA(k), 1e-6)) if por_tiempo else G.dxm
            if cupo < coste:
                break
            cupo -= coste; held[k] = 1; tocado = True
            i, j = divmod(k, nc)
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    ni, nj = i + di, j + dj
                    if 0 <= ni < nr and 0 <= nj < nc and t < bt[ni * nc + nj]:
                        bt[ni * nc + nj] = t
        resto = max(0.0, cupo)      # lo que no dio para otra celda, al siguiente
        if tocado:
            arr = sim(c, bt)
        if all(a == V.INF or a <= t for a in arr):
            break
    return arr, bt


def mejor_extincion(c, E, arr0, geo, edge):
    """La MEJOR extinción posible con esfuerzo E, según la premisa del usuario de
    suponer que los bomberos actúan bien: se prueban ataque directo, línea
    indirecta (9 trazados) y las dos juntas, y se devuelve el mejor resultado.
    Es una COTA SUPERIOR de lo que la extinción puede lograr — que es justo lo
    que hay que comparar con una cicatriz, que también lleva bomberos dentro."""
    G = c['G']; N = G.nr * G.nc
    rate_min = E / 60.0
    global ULTIMA_TABLA
    tabla = {} if REGISTRA_CANDIDATAS else None
    arr_d, _ = directo(c, E, arr0, edge, [V.INF] * N)
    mejor_arr, mejor_q = arr_d, quemado(arr_d)
    if tabla is not None:
        tabla['directo'] = mejor_q
    mejor_bt = None
    for frac in FRACS:
        for rot in ROTS:
            eje = eje_candidato(G, geo, frac, rot, arr0)
            if len(eje) < 4:
                continue
            lleg = sorted(arr0[k] for k in eje if arr0[k] != V.INF)
            if not lleg:
                continue
            tmed = lleg[len(lleg) // 2]
            if tmed <= T0:
                continue
            cel = tiempos_desde_el_medio(G, eje, T0, rate_min, tmed - T0)
            if len(cel) < 2:
                continue
            bt = V.field_from(G, cel)
            a = sim(c, bt)
            q = quemado(a)
            if tabla is not None:
                tabla[f'{frac:.2f}_{rot}'] = q
            if q < mejor_q:
                mejor_arr, mejor_q, mejor_bt = a, q, bt
    if mejor_bt is not None:
        a2, _ = directo(c, E, mejor_arr, edge_ros(mejor_arr, G), list(mejor_bt))
        if quemado(a2) < mejor_q:
            mejor_arr, mejor_q = a2, quemado(a2)
    if tabla is not None:
        # ⛔⛔ 31-ago · LO CAZÓ `paridad_oraculo.py` Y ERA UNA SUPOSICIÓN FALSA MÍA.
        #    El resultado que esta función DEVUELVE no es ninguna de las 10 candidatas:
        #    tras elegir la mejor línea indirecta le echa encima un ataque DIRECTO, y esa
        #    COMBINACIÓN suele ganar a cualquiera de las dos por separado. Así que
        #    `min(tabla.values()) != mejor_q`, y `c120` (§99), que definía el oráculo como
        #    «la mejor de las 10», habría medido un techo MÁS BAJO que el 69,5% de §98.2 y
        #    comparado contra otra cosa sin enterarse.
        #    Se guarda aparte para que el que lee la tabla vea las dos cosas: lo que da
        #    cada colocación sola, y lo que da la combinación que la función devuelve.
        tabla['_oraculo'] = mejor_q
        ULTIMA_TABLA = tabla
    return mejor_arr, mejor_q


# ─────────────────────────────────────────────────────────────────────────────
# MANGUERA · puerto de `fire_sim.js` (2026-08-24)
#
# POR QUÉ EXISTE ESTO
# La app tiene manguera desde el 12-ago (`fire_sim.js:1004`) y **ningún motor de
# Python la tenía**: un `grep` de `HOSE|manguera` sobre todo `scripts/validacion/`
# y `contencion/` no devolvía nada. O sea que al medir un ataque de tierra el arnés
# medía SÓLO obra de línea, y la pantalla hacía obra de línea Y mojado. §14 punto 9
# lo enunciaba al revés («darle manguera a los bomberos»), como si faltara en los
# dos sitios.
# Es una divergencia que `paridad.py` no puede ver: no es una constante con otro
# valor, es un mecanismo que en un lado no existe. Por eso, junto con este puerto,
# `paridad_reglas.py` gana un nivel que compara MECANISMOS.
#
# QUÉ ES TRADUCCIÓN LITERAL Y QUÉ ES AÑADIDO — la distinción importa
#   · LITERAL (de `addAction`, `buildTimes` y `rebuildFields` de la app):
#       - el tendido avanza a HOSE_RATE m/min desde el punto de acceso
#       - cada celda se moja a su hora t = t0 + metros/ritmo
#       - mojado: ws = min(ws, t) · we = max(we, t + HOSE_SOAK); re-mojar ALARGA
#       - donde la intensidad del borde es <= I_MANUAL, el agua APAGA y queda
#         apagado (bt[k] = t), igual que un tramo de línea terminado
#       - el alcance del tendido es HOSE_REACH m desde el acceso
#   · AÑADIDO, y hay que decirlo: en la app el usuario PINTA el trazo con el ratón.
#     Aquí no hay usuario, así que el trazo se elige por una regla —perímetro
#     trabajable dentro del alcance, de más cerca a más lejos del acceso—. Esa regla
#     NO está en la app y no se puede llamar paridad: es una decisión de este arnés,
#     escrita aquí para poder discutirla.
# ─────────────────────────────────────────────────────────────────────────────
HOSE_REACH = 250.0    # m de tendido desde el punto de acceso   (fire_sim.js:1004)
HOSE_RATE  = 2.5      # m/min que avanza el tendido             (fire_sim.js:1004)
HOSE_SOAK  = 90.0     # min que mantiene mojado                 (fire_sim.js:1004)


def _perimetro_en_t(arr, G, t, held=None):
    """Celdas ya alcanzadas por el fuego en `t` que tocan algo aún sin arder.
    Es el mismo criterio de borde que usa `directo()`, extraído para compartirlo."""
    nr, nc = G.nr, G.nc
    out = []
    for k in range(nr * nc):
        a = arr[k]
        if a == V.INF or a > t or (held is not None and held[k]):
            continue
        i, j = divmod(k, nc)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if not di and not dj:
                    continue
                ni, nj = i + di, j + dj
                if not (0 <= ni < nr and 0 <= nj < nc):
                    continue
                b = arr[ni * nc + nj]
                if b == V.INF or b > t:
                    out.append(k)
                    break
            else:
                continue
            break
    return out


def manguera(c, arr, edge, bt0, ws, we, acceso, t0,
             alcance=HOSE_REACH, ritmo=HOSE_RATE, soak=HOSE_SOAK):
    """Tiende manguera desde `acceso` sobre el perímetro que tenga a tiro.

    Modifica `ws`/`we` IN SITU (igual que `aereo.moja()`) y devuelve
    `(bt, n_celdas, n_apagadas)`. `bt0` no se toca: se devuelve una copia.

    `acceso` es el índice de celda donde está la autobomba. `t0`, el minuto en que
    empieza a tender.
    """
    G = c['G']; nr, nc = G.nr, G.nc
    bt = list(bt0)
    ai, aj = divmod(acceso, nc)

    # El trazo: perímetro trabajable dentro del alcance, de más cerca a más lejos.
    # ⚠ Esta ordenación es del arnés, no de la app (ver la cabecera del bloque).
    def dist(k):
        i, j = divmod(k, nc)
        return math.hypot((j - aj) * G.dxm, (i - ai) * G.dym)

    eje = [k for k in _perimetro_en_t(arr, G, t0) if dist(k) <= alcance]
    if not eje:
        return bt, 0, 0
    eje.sort(key=dist)

    # Los tiempos, como `buildTimes()`: la celda n queda mojada cuando el tendido
    # ha recorrido los metros que la separan de la anterior, a `ritmo` m/min.
    n_apagadas = 0
    rec = 0.0
    ant = None
    for k in eje:
        if ant is not None:
            i0, j0 = divmod(ant, nc)
            i1, j1 = divmod(k, nc)
            rec += math.hypot((j1 - j0) * G.dxm, (i1 - i0) * G.dym)
        ant = k
        t = t0 + rec / ritmo
        # mojado: re-mojar ALARGA la ventana, no la reinicia (igual que la app)
        if t < ws[k]:
            ws[k] = t
        fin = t + soak
        if we[k] == V.INF or fin > we[k]:
            we[k] = fin
        # y donde el fuego es débil, el agua deja el tramo hecho
        inten = V.intensidad(edge[k] if edge[k] != V.INF else 0.0, G.fuel[k])
        if inten <= V.I_MANUAL and t < bt[k]:
            bt[k] = t
            n_apagadas += 1
    return bt, len(eje), n_apagadas
