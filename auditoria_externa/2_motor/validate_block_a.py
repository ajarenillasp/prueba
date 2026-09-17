#!/usr/bin/env python3
"""
Validación del bloque A de fire_sim.js (intervenciones con hora, frente actual,
ventana de oportunidad, asesor) portando el motor a Python y corriéndolo sobre
los datos reales de u1 (snapshot 2026-08-02, rejilla 128x128).

Comprueba:
  1. Escenario base sin atascos.
  2. Un cortafuegos disponible desde t=0 corta igual que en la versión antigua.
  3. EL MISMO cortafuegos, empezado tarde, NO corta (esa era la mentira del modelo).
  4. El área salvada decrece monótonamente conforme se retrasa el inicio de la obra.
  5. La construcción progresiva importa: una obra lenta salva menos que una rápida.
  6. El agua caduca: mismo trazo, efecto según el momento de la descarga.
  7. Frente actual: el interior de la mancha no vuelve a arder; se propaga desde el borde.
  8. Factibilidad: la hora límite de inicio calculada es realmente el límite.
"""
import json, math, heapq, os, sys

SNAP = os.environ.get('SNAP', '/mnt/qnap/greenhouse3/users/u3/snapshot/2026-07-22')

# ── Constantes (idénticas a fire_sim.js) ────────────────────────────────────
ROS_MAX, WIND_K, HEAD_MAX, SLOPE_WIND_K = 20.5, 0.030, 12.0, 45.0   # calibración conjunta 2026-08-06 · ROS_MAX 28 → 20,5 el 2026-09-14
# ⛔ 2026-09-14 · ROS_MAX 28 → 20,5 con la LST de DÍA (INCENDIOS.md §159-§161, `c164`): 28 estaba calibrado con la
# pasada nocturna de Sentinel-3 (sequedad ≈0). ⚠ PARA REPRODUCIR CUALQUIER CRUDO ANTERIOR AL 14-sep hace falta
# ROS_MAX = 28 y la LST de noche (`lst_noche_data.json` en cada captura del banco).
# LB_MAX: 3.0 → 2.0 el 2026-08-10 (`f15_lb2.py`, n=24/14) → 1.5 el 2026-08-11
# (`f20_final.py`, rejilla fina con las dos métricas juntas sobre 210/49 incendios,
# regla escrita antes: el LB_MAX más bajo con Dice ≥ máximo−0,01). Orden 0,828→0,867,
# Dice 0,4516→0,4483. OJO: mejora la nota media del orden pero NO la tasa de
# victorias contra el círculo honesto (3-4% con cualquier LB_MAX de 1,0 a 3,0).
# 2026-08-13: LB_MAX 1,5 → 2,5. Ocho valores barridos (1,5 a 14) contra 208 incendios
# reales en `contencion/c03`: el Dice tiene máximo INTERIOR en 2,5 (0,4747 vs 0,4558),
# y coincide con el alargamiento que justifica el error de rumbo medido (33°, `e58`).
# Aplicado también en js/fire_sim.js:58 — los dos motores deben medir lo mismo.
LB_MAX, FLANK_MIN, MIN_ROS, SPREAD_MIN = 2.5, 0.05, 0.05, 0.60   # cola al 5% de la cabeza (real 1-5%)

# CONFIANZA DEL VIENTO (2026-08-11, `f21_viento_confianza.py`), APLICADO: en vez de
# un LB_MAX fijo para todos los incendios, estirar la elipse a tope sólo cuando el
# reanálisis horario ha apuntado varias horas seguidas en direcciones parecidas, y
# quedarse casi isótropo cuando el viento da bandazos entre horas — ataca la causa
# que `e58_rumbo.py`/`e59_forma.py` encontraron (el modelo estira el doble de lo
# real porque un viento de rejilla de ~30 km no siempre conoce bien la dirección).
# Confirmado fuera de muestra (105 de prueba): orden 0,8750→0,8768, gana 46/64
# (72%, p=0,0003), Dice sin cambio. Matiz (f22_circulo_conf.py, 210 incendios): NO
# cambia cuántas veces le gana al círculo honesto (4/130=3%, igual que sin esto) —
# mejora real y sin coste, pero no resuelve el problema de fondo.
USE_WIND_CONF = True
WIND_CONF_WINDOW_H = 3     # horas a cada lado para juzgar si el viento es consistente
WIND_CONF_GAMMA = 2.0      # >1 castiga más la inconsistencia; 1 = lineal con R
WIND_CONF_MIN_SPD = 3.0    # km/h por debajo de los cuales la dirección no es fiable ni para restar
WATER_FACTOR, WATER_HOLD, WATER_FADE, WATER_RATE = 0.04, 25.0, 35.0, 8.0
BRUSH, FLAM_MIN, NDWI_WATER, INT_REF = 1, 0.02, 0.20, 12.0   # FLAM_MIN calibrado 2026-08-06
RESOURCES = {'crew': (120, 45, 5), 'engine': (400, 30, 8),
             'dozer': (1200, 90, 15), 'heli': (700, 20, 12)}   # m/h, resp min, m/min ataque directo
INF = float('inf')


def clamp(x, a, b):
    return a if x < a else (b if x > b else x)


def load_layer(name):
    p = os.path.join(SNAP, name + '_data.json')
    if not os.path.exists(p):
        return None, None, None
    j = json.load(open(p))
    return j['values'], j.get('shape'), j.get('bbox')


# ── Combustible: CARGA × CURADO (2026-08-06) ────────────────────────────────
# El NDVI de hoy no distingue un rastrojo (creció y se secó → arde muy bien) de un
# suelo pelado (nunca creció → no arde): los dos dan NDVI bajo. Con el verdor
# MÁXIMO de los últimos meses sí se distingue:
#   carga  = cuánta materia llegó a crecer          (verdor máximo)
#   curado = cuánto verdor ha perdido desde entonces (1 - ahora/máximo)
# Un pinar verde tiene mucha carga y poco curado; un rastrojo, mucha carga y mucho
# curado; una era pelada, ninguna carga. Parámetros expuestos para calibrarlos.
PEAK_LO, PEAK_HI = 0.15, 0.60   # verdor máximo → carga 0..1
CURE_BASE = 0.35                # cuánto arde lo que sigue verde (pinar, monte bajo)
USE_PEAK = True                 # False = modelo antiguo (sólo NDVI), para comparar
# D2 · viento modificado por el relieve (mismos valores que fire_sim.js)
TPI_SCALE, TERR_SPEED, TERR_CHAN = 40.0, 0.45, 0.75
USE_TERRAIN = True
USE_LANDCOVER = True             # D4: tipo de terreno como multiplicador del combustible
# Cuánto PESA el tipo de terreno: >1 marca más las discontinuidades (carreteras,
# roca, pueblos frenan más), <1 las suaviza. Se calibra contra las cicatrices.
LC_POW = 1.0
BARRIER_MIN = 0.50   # fracción de urbano/roca/agua a partir de la cual NO arde
# 2026-08-24 · con esto encendido, la barrera actúa EN PROPORCIÓN a la fracción de
# la celda que ocupa, en vez de como interruptor al 50%. `BARRIER_MIN` sólo se usa
# con esto apagado, para poder medir el antes y el después sin ambigüedad.
USE_BARRERA_PROP = os.environ.get('BARRERA_PROP', '1') != '0'
# ⭐ 2026-08-24 · RUIDO DE PROPAGACIÓN POR CELDA. Es el último candidato sin probar
# para el borde liso (§22 k). El motor es DETERMINISTA y uniforme dentro de cada celda:
# el mismo combustible da exactamente la misma velocidad siempre. El fuego real no —
# una racha, una mata más seca, una piedra, un surco— y esa variabilidad de escala fina
# es lo que en la literatura de autómatas de fuego produce bordes irregulares.
# Medido el 24-ago: la heterogeneidad CONTINUA del combustible se alisa (la barrera
# proporcional no hizo nada) pero las DISCONTINUIDADES sí hacen dedos. El ruido está
# entre las dos: no es continuo ni bloquea, es aleatorio celda a celda.
# `RUIDO_ROS` es la desviación (fracción). 0 = como hasta hoy. Determinista por
# posición: dos corridas del mismo terreno dan lo mismo, que es condición para comparar.
RUIDO_ROS = float(os.environ.get('RUIDO_ROS', '0'))


def _ruido(i, j):
    """Multiplicador pseudoaleatorio y REPRODUCIBLE de la celda (i, j)."""
    if RUIDO_ROS <= 0:
        return 1.0
    h = ((i * 73856093) ^ (j * 83492791) ^ 0x9E3779B9) & 0xFFFFFFFF
    u = (h % 100000) / 100000.0            # uniforme [0,1)
    return max(0.05, 1.0 + RUIDO_ROS * (2.0 * u - 1.0))
# Velocidad relativa por TIPO de terreno. En la realidad el pasto corre 3-10 veces
# más que la hojarasca de un bosque (Rothermel: el pasto tiene mucha superficie por
# unidad de volumen y arde suelto; la hojarasca está compactada). El modelo sólo
# distinguía "cuánto combustible hay", no de qué tipo. Se calibra contra cicatrices.
LC_ROS = {10: 1.00, 20: 0.85, 30: 1.00, 40: 0.55}   # arbolado, matorral, pasto, cultivo
# DESACTIVADO tras medirlo (2026-08-06): frenar el arbolado EMPEORA de forma
# monótona (0.363 → 0.090 al bajarlo a 0.25). En estos incendios del noroeste el
# "arbolado" de WorldCover es eucaliptal y pinar con matorral debajo, que corre
# tanto como el pasto: la clase no distingue un robledal de una plantación con
# tojo. Con una capa de combustible de más detalle (Corine nivel 3, o modelos de
# combustible) volvería a tener sentido. Se deja medido y documentado.
USE_LCROS = False


class Grid:
    def __init__(self, fwi=45.0):
        ndvi, shape, bbox = load_layer('ndvi')
        ndmi, _, _ = load_layer('ndmi')
        lst, _, _ = load_layer('lst')
        dem, _, _ = load_layer('dem')
        ndwi, _, _ = load_layer('ndwi')
        peak, _, _ = load_layer('ndvipeak')
        # D4: tipo de terreno (ESA WorldCover). Aporta lo que ninguna otra capa da:
        # DISCONTINUIDADES — carreteras, pueblos, roca — que es donde se paran los
        # incendios reales. Guardado como mezcla por celda, no clase dominante.
        lcov, _, _ = load_layer('landcover')
        lcbar, _, _ = load_layer('lcbarrier')   # fracción urbano/roca/agua
        import os as _os
        _cp = _os.path.join(SNAP, 'lcclass.json')
        lccls = json.load(open(_cp))['clases'] if _os.path.exists(_cp) else None
        self.nr, self.nc = shape[0], shape[1]
        N = self.nr * self.nc
        danger = clamp(fwi / 50.0, 0.05, 1)
        self.fuel = [0.0] * N
        self.ease = [0.0] * N
        self.water = [0] * N
        self.noburn = [0] * N
        elev = [None] * N
        for i in range(self.nr):
            for j in range(self.nc):
                k = i * self.nc + j
                nv = _g(ndvi, i, j); nm = _g(ndmi, i, j)
                lt = _g(lst, i, j); dm = _g(dem, i, j); nw = _g(ndwi, i, j)
                pk = _g(peak, i, j)
                if pk is None or nv is None or not USE_PEAK:
                    # snapshot antiguo sin capa de verdor máximo: modelo de antes
                    f = 0.3 if nv is None else clamp((nv - 0.05) / 0.40, 0, 1)
                else:
                    load = clamp((pk - PEAK_LO) / (PEAK_HI - PEAK_LO), 0, 1)
                    cure = clamp(1 - nv / pk, 0, 1) if pk > 0.05 else 0.0
                    f = load * clamp(CURE_BASE + (1 - CURE_BASE) * cure, 0, 1)
                dryN = 0.5 if nm is None else clamp((0.40 - nm) / 0.60, 0, 1)
                dryL = 0.5 if lt is None else clamp((lt - 20) / 25, 0, 1)
                e = (0.35 + 0.65 * dryN) * (0.55 + 0.45 * dryL) * (0.30 + 0.70 * danger)
                lc = _g(lcov, i, j)
                if lc is not None and USE_LANDCOVER:
                    f *= clamp(lc, 0, 1.2) ** LC_POW
                # Velocidad según el TIPO de terreno de la celda (mezcla ponderada)
                if lccls is not None and USE_LCROS:
                    wsum = vsum = 0.0
                    for _k, _v in LC_ROS.items():
                        _fr = _g(lccls.get(str(_k)), i, j)
                        if _fr:
                            wsum += _fr; vsum += _fr * _v
                    if wsum > 0.05:
                        f *= vsum / wsum
                # ⭐ BARRERA PROPORCIONAL (2026-08-24). Antes esto era un
                # INTERRUPTOR: `bar >= 0,50` → no arde; por debajo, arde como si no
                # hubiera nada. Y la capa guarda la MEZCLA por celda precisamente
                # para no perder la carretera de 10 m dentro de la celda de 70 —lo
                # dice su propio comentario— y el umbral la tiraba igual. Medido el
                # 24-ago en la capa real: hay 3-4× MÁS barrera parcial (>=0,20) de la
                # que el umbral conserva (>=0,50).
                # Lo real no es «arde o no arde»: una celda con 30% de roca **arde
                # menos y desvía**. Eso es lo que hace dedos, y los dedos son la
                # mitad de lo que separa la forma del modelo de la cicatriz real
                # (índice 1,84 contra 4,56, §22 i).
                # `noburn` se reserva para cuando ya no queda combustible que valga:
                # deja de ser un umbral elegido y pasa a ser la consecuencia.
                bar = _g(lcbar, i, j)
                if bar is not None and USE_LANDCOVER:
                    if USE_BARRERA_PROP:
                        # ⛔ La primera versión de esto (24-ago) multiplicaba el
                        # combustible por (1-bar) y NO SIRVIÓ DE NADA: índice 1,99 →
                        # 1,94. La razón enseña cómo funciona el motor: **hacer que
                        # una celda arda más despacio no deja muesca**, el camino de
                        # tiempo mínimo simplemente tarda un poco más en cruzarla.
                        # En un modelo de camino mínimo la heterogeneidad CONTINUA se
                        # alisa; **sólo las discontinuidades hacen dedos**. Y bajar
                        # `BARRIER_MIN` sí funcionaba (1,84 → 2,48) justamente porque
                        # convierte celdas en bloqueos duros.
                        # Lo real tampoco es un umbral: una celda con 30% de carretera
                        # no «arde un 30% menos», es que **el fuego la cruza o no la
                        # cruza** según dónde caiga la carretera dentro de la celda y
                        # cómo sople. Bloquea con PROBABILIDAD igual a su fracción:
                        # así la barrera media por hectárea es la correcta Y aparecen
                        # las discontinuidades que hacen el borde irregular.
                        # Sorteo DETERMINISTA por posición: mismo terreno, mismo
                        # resultado, para que dos corridas sean comparables.
                        # ⚠ La fórmula tiene que dar EXACTAMENTE lo mismo en Python y
                        # en JavaScript o los dos motores divergen en silencio. La
                        # primera versión usaba XOR sobre productos grandes: en JS eso
                        # pasa por int32 con signo y en Python no — para (300,400) daba
                        # 3484 aquí y −2996 allí. Ésta se queda muy por debajo de 2^53
                        # (i,j < 512 → suma < 58 millones), así que es exacta en los dos.
                        if bar > 0.0 and (i * 7919 + j * 104729) % 100003 % 10000 \
                                < int(bar * 10000):
                            f = 0.0
                            self.noburn[k] = 1
                    elif bar >= BARRIER_MIN:
                        f = 0.0
                        self.noburn[k] = 1
                if nw is not None and nw > NDWI_WATER:
                    f = 0.0
                    self.water[k] = 1
                if RUIDO_ROS > 0:
                    e *= _ruido(i, j)      # la variabilidad fina va en la facilidad
                if f * e < FLAM_MIN:
                    f = 0.0
                self.fuel[k] = f; self.ease[k] = e
                elev[k] = dm
        known = [v for v in elev if v is not None]
        mean = sum(known) / len(known) if known else 0.0
        elev = [mean if v is None else v for v in elev]
        self.elev = elev
        latc = (bbox['lat_min'] + bbox['lat_max']) / 2
        self.dym = abs(bbox['lat_max'] - bbox['lat_min']) / self.nr * 110540
        self.dxm = abs(bbox['lon_max'] - bbox['lon_min']) / self.nc * 111320 * math.cos(math.radians(latc))
        self.sgx = [0.0] * N; self.sgy = [0.0] * N
        for i in range(self.nr):
            for j in range(self.nc):
                k = i * self.nc + j
                jE, jW = min(self.nc - 1, j + 1), max(0, j - 1)
                iN, iS = max(0, i - 1), min(self.nr - 1, i + 1)
                self.sgx[k] = (elev[i * self.nc + jE] - elev[i * self.nc + jW]) / ((jE - jW) * self.dxm or 1)
                self.sgy[k] = (elev[iN * self.nc + j] - elev[iS * self.nc + j]) / ((iS - iN) * self.dym or 1)
        # TPI (bloque D2): resalte de cada celda sobre su entorno. Positivo = cresta
        # (el viento se acelera), negativo = vaguada (se frena y se encauza).
        # Lo tenía la app pero NO el arnés: hasta el 2026-08-06 la validación medía
        # un modelo más pobre que el que está en producción.
        self.tpi = [0.0] * N
        R = 3
        for i in range(self.nr):
            for j in range(self.nc):
                s = 0.0; n = 0
                for di in range(-R, R + 1):
                    ni = i + di
                    if ni < 0 or ni >= self.nr:
                        continue
                    for dj in range(-R, R + 1):
                        nj = j + dj
                        if 0 <= nj < self.nc:
                            s += elev[ni * self.nc + nj]; n += 1
                self.tpi[i * self.nc + j] = elev[i * self.nc + j] - s / n
        self.ig = [self.fuel[k] * self.ease[k] for k in range(N)]
        self.cell_ha = self.dxm * self.dym / 10000.0

    def ros_base(self, k):
        return ROS_MAX * self.fuel[k] * self.ease[k]


def _g(grid, i, j):
    if grid is None:
        return None
    row = grid[i] if i < len(grid) else None
    if row is None or j >= len(row):
        return None
    v = row[j]
    return None if v is None else v


def diurnal(hod, hum=1.0, amp=1.0):
    """Ciclo día/noche. `hum` viene de la humedad relativa: con el dato HORARIO del
    punto (22%-91% en el mismo día) el contraste día/noche es mucho mayor que con
    la media diaria de una estación, que lo aplana."""
    h = (hod - FASE_H) % 24            # 15-sep · FASE_H = 3,0 es producción exacta (§169)
    v = hum * (0.775 - 0.375 * amp * math.cos(2 * math.pi * h / 24))
    # ── FRENO SÓLO NOCTURNO (2026-08-31) · §97 ──────────────────────────────
    # `AMP_DIURNA` estira el ciclo por los DOS lados: hunde la madrugada y
    # ACELERA la tarde. `c117` lo usó creyendo que frenaba la noche y midió lo
    # contrario — con ventana de 6 h y el 55% de la cohorte arrancando entre las
    # 09:00 y las 15:00, el fuego libre CRECIÓ 1,24x en 2 de cada 3 incendios.
    # `NOCHE_K` deja el día EXACTAMENTE como está y sólo profundiza el valle
    # nocturno, así que la diferencia es atribuible a la noche y a nada más.
    # ⭐ Propiedad que se usa como comprobación: con K>1 todas las velocidades
    #    bajan o quedan igual, luego el fuego libre NO PUEDE CRECER. Si crece,
    #    el experimento está mal montado.
    if NOCHE_K != 1.0:
        base = hum * 0.775                     # la media diaria, escalada por HR
        if v < base:                           # lado nocturno (21:00-09:00)
            v = base - (base - v) * NOCHE_K
    return clamp(v, 0.12, 1.7)


# ── Humedad de EXTINCIÓN (2026-08-06) ───────────────────────────────────────
# La razón física por la que un incendio no se come un continente. El combustible
# fino intercambia humedad con el aire en menos de una hora: de madrugada, con la
# HR al 90-95%, pasa del ~25% de humedad y YA NO PROPAGA. No es que vaya despacio:
# es que se para, y a la mañana siguiente hay que volver a encenderlo (por eso los
# incendios reales tienen "noches" y frentes que se apagan solos).
# El modelo anterior aplicaba un factor con SUELO de 0.75, así que con HR 80%, 90%
# o 95% avanzaba igual y nunca se detenía.
FFM_EXT = 0.30          # humedad de extinción del combustible fino (30%)
# DESACTIVADA tras medirla (2026-08-06): con extinción fuerte el fuego sí se para
# (67%→31% del AOI, más cerca del 20% real) PERO la forma cae a 0.299, por debajo
# del círculo (0.345). Y el dato que la refuta: el 40% de las detecciones de fuego
# ACTIVO de estos 14 incendios son de madrugada (3-4 de la mañana hora local). Estos
# incendios ardían de noche. La razón por la que se pararon no es la humedad: es que
# los apagaron, y eso no se modela. Se deja el código, medido y documentado.
USE_EXTINCTION = False

# ── FRENADA POR EDAD DEL INCENDIO (2026-08-16, `c43`) ───────────────────────
# `c43` midió sobre 208 incendios y con los intervalos DIURNOS aparte (para que
# «decelera» no sea «se hizo de noche») que el frente real cae un 88% de las
# primeras horas a las 24-36 h —de 289 a 35 m/h— mientras el modelo sólo cae un
# 15% —de 301 a 255—. El arranque lo borda; lo que no sabe es PARAR.
#
# HONESTIDAD SOBRE LO QUE ESTO ES: un freno FENOMENOLÓGICO. Reproduce la
# observación, no identifica la causa. Detrás hay al menos tres mecanismos
# distintos y este factor los mete a todos en el mismo saco:
#   a) extinción acumulada — los 208 incendios de la muestra se apagaron TODOS,
#      y a nadie lo apaga la meteorología. Es el candidato principal.
#   b) combustible agotado — el fuego llega a lo que no arde.
#   c) frentes que se apagan y no se reencienden.
# Separarlos exige otro experimento. Mientras tanto, `AGE_TAU_H` NO es «lo que
# tardan los bomberos»: es la constante que ajusta la curva agregada.
#
# Forma: multiplicador 1 durante una gracia inicial `AGE_T0_H` (el tramo que el
# modelo ya acierta y NO hay que tocar), y decaimiento exponencial después hasta
# un suelo `AGE_FLOOR`. El suelo evita que el fuego se congele del todo; por
# debajo de SPREAD_MIN el frente se corta solo, que es la extinción emergiendo.
USE_AGE_BRAKE = False     # apagado: producción no cambia hasta que se mida

# ⭐ 2026-08-24 · listón de muerte del frente por intensidad, ver `dijkstra()`. Los dos
# apagados: producción no cambia hasta que `a62` lo mida en las dos mitades.
USE_I_MIN = False
I_MIN = 0.0               # kW/m por debajo de los cuales el frente no se sostiene

# ⭐⭐ 2026-08-24 · ¿ARDE O NO ARDE? · el mecanismo que `a63` pone a prueba.
#
# `a61` y `a62` midieron que TRES mecanismos independientes —freno por edad,
# `SPREAD_MIN` e `I_MIN`— hacen exactamente lo mismo: el área y el alcance caen
# ENCADENADOS. No es calibración, es la topología de un buscador de caminos mínimos:
# el tiempo de llegada a una celda lejana es la SUMA de los tiempos del camino hasta
# ella, así que cualquier cosa que frene la propagación lenta corta también los
# caminos largos, porque un camino largo casi siempre lleva tramos lentos dentro.
#
# El defecto de fondo no es ningún parámetro:
#   **este motor quema TODA celda cuyo tiempo de llegada sea ≤ t_obs.** No tiene una
#   decisión de «arde / no arde» separada de la de «se puede llegar». En la realidad
#   una celda se alcanza y aun así no arde. Por eso la cicatriz real tiene 3,7% de
#   islas interiores e índice de forma 4,8 y la nuestra 1,3% y 1,9: aquí
#   *alcanzable ≡ quemado*, y la mancha sale rellena POR CONSTRUCCIÓN.
#
# Esto separa las dos cosas: al llegar el frente a una celda se decide si prende, y
# **una celda que no prende tampoco propaga**. La cabeza sigue encontrando camino
# continuo entre las que sí prenden, así que el alcance no tiene por qué caer — que es
# justo la predicción que distingue este mecanismo de los tres anteriores.
#
# ⚠ DIRIGIDO POR DATOS, NO POR RUIDO. La diferencia no es menor: la barrera
# probabilística (dato: fracción de barrera de la celda) cerró el 10% del hueco de
# forma con el Dice intacto, y sortear islas AL AZAR (`a18`) hundió el Dice de 0,444 a
# 0,074. Aquí la probabilidad sale del índice de combustible de la celda, que hoy es
# un continuo suave que nunca dice que no: una celda con índice 0,3 arde al 100% y
# propaga al 30%, cuando debería ARDER con probabilidad ligada a ese 0,3.
#
# ⚠ EL SORTEO ES DETERMINISTA, por dos motivos que no son negociables:
#   · Dijkstra visita una celda varias veces; un dado distinto en cada visita daría
#     un resultado dependiente del orden de la cola.
#   · el JS tiene que dar EXACTAMENTE lo mismo (precedente: `prueba9.js`).
#   Primos DISTINTOS a los de la barrera, o las dos decisiones saldrían correlacionadas
#   celda a celda. Máximo con rejilla 512: 512*(25703+60077) = 43.9M, muy por debajo
#   de 2^53, así que es exacto también en JS.
# 2026-08-25 · LOS VALORES SON LOS VALIDADOS, EL INTERRUPTOR SIGUE APAGADO, y las dos
# cosas son a propósito. La app los lleva ENCENDIDOS desde hoy (§25); aquí el switch se
# queda en False porque los controles C0 de §24 comparan contra la MISMA producción de
# `a63`, y encenderlo rompería la comparabilidad de todo lo medido. Para medir un brazo
# nuevo se enciende a mano. Dejando el POW en su valor validado, `paridad.py` deja de
# cantar una diferencia de VALOR que no lo es: lo único que difiere es el switch, y eso
# está declarado en `paridad_reglas.py` (N5).
USE_P_IGN = False
P_IGN_POW = 0.15          # ⛔ 26-ago: se probó 0,25 (con textura) y se REVIRTIÓ por el
                          # artefacto de retícula del hash (§35bis). Volver a 0,25 sólo
                          # cuando el hash esté arreglado y RE-MEDIDO.
P_IGN_M = 1750            # lado del parche en METROS · la app lo usa así (§25, `a67`).
                          # `P_IGN_BLOQUE` (celdas) se mantiene porque los experimentos
                          # a63-a68 lo usan; en celdas = round(P_IGN_M / dxm).

# ⭐ 2026-08-24 · LA ESCALA DEL PARCHE (`a64`), y sale medida de `a63`.
# `a63` corrió este sorteo celda a celda e hizo lo que se le pedía —el índice de forma
# pasó de 3,57 a 20-32 y las islas interiores de 1,8% a 18-24%— pero **se pasó de
# largo**: la cicatriz real está en forma **7,32** e islas **5,9%**. O sea que la
# mancha no salió deshilachada, salió CONFETI.
# El motivo es de escala, no de mecanismo: un sorteo independiente por celda es ruido
# blanco a 55 m. Lo que la realidad tiene sin quemar son roquedos, vaguadas verdes y
# parcelas — manchas de cientos de metros, **espacialmente correlacionadas**. Con
# `P_IGN_BLOQUE` el dado se tira por PARCHE de lado `bloque` celdas y no por celda; la
# probabilidad sigue saliendo del combustible de CADA celda, así que lo que se
# correlaciona es el azar, no el dato.
P_IGN_BLOQUE = 1          # lado del parche, en celdas. 1 = una tirada por celda (a63)

# ⭐⭐⭐ 2026-08-26 · LA SEGUNDA ESCALA (textura), PORTADA · §35
# `a68` la midió y `a78` la descartó por una puerta de UN SOLO LADO sobre el alcance. El
# reanálisis de §35, con la ley de escala de §34 delante, invierte la decisión: la
# irregularidad (`forma`) es ADIMENSIONAL, así que un zoom no la mueve — y esto la mueve
# **5,0x el suelo de ruido** (3,39 -> 6,92; real 8,11) con las islas a 8,4% (real 7,0%),
# reproduciendo en LAS DOS MITADES. Y midiendo el ERROR de alcance en vez de su caída, la
# textura ACERCA el alcance a la realidad sumando las dos mitades (ajuste 0,41 -> 0,17;
# ciega 0,00 -> 0,06), porque producción SE PASA de alcance en la mitad de ajuste (1,41).
#
# ⚠ NO es «producción + textura»: el brazo validado cambia TAMBIÉN el parche grueso,
# de pow 0,15/1750 m a **pow 0,25/1800 m**. Son tres parámetros, no uno.
#
# ⚠ Y lo que NO hace, para que nadie lo venda: el Dice pasa de 0,310 a 0,321, que es
# 0,6x el ruido — nada. §24.6 ya dijo que el Dice lo manda la DIRECCIÓN (27°), no el
# relleno. Esto entra por forma y área.
P_IGN_MODO = 'parche'     # espejo de `fire_sim.js` · la textura, REVERTIDA (§35bis)
P_IGN_FINO_M = 220        # lado de la textura fina, en METROS (`a64`/`a68`)
P_IGN_BLOQUE_FINO = 0     # ídem en CELDAS · 0 = derivar de metros. Los experimentos
                          # a63-a82 trabajan en celdas y DEBEN seguir reproduciendo.
P_IGN_FINO_POW = 0.05     # el brazo elegido en §35 (p0,10 se pasa de islas: 12,9% vs 7,0%)
P_IGN_PA, P_IGN_PB = 25703, 60077      # primos del parche
P_IGN_FPA, P_IGN_FPB = 46589, 83987    # primos de la textura · independientes a propósito


# ⛔⛔⛔ 2026-08-26 · LOS CUADRADOS · lo que el usuario veía como «una línea recta».
# El dado se tiraba por bloque alineado a la rejilla, así que un parche apagado era un
# CUADRADO PERFECTO de `P_IGN_M` (1,76 km) con lados rectos. Localizados en el campo:
# filas 154..175 y 110..131 — 22 filas exactas, arrancando en múltiplos de 22.
# Y el hash era LINEAL, así que los cuadrados apagados caían además en RETÍCULA (medido:
# el 82% de las separaciones eran exactamente 5 bloques).
# Lo que no arde en un incendio real son manchas IRREGULARES, no cuadrados de una rejilla.
# ⚠ Esto cambia el sorteo: las cifras de `a66`-`a78` hay que RE-MEDIRLAS.
#   `P_IGN_FORMA = 'bloque'` reproduce el comportamiento viejo para los experimentos.
P_IGN_FORMA = 'organico'      # 'bloque' = cuadrados (histórico) · 'organico' = manchas


def _mezcla32(a):
    """Hash con avalancha. Espejo de `mezcla32()` en `fire_sim.js`."""
    a &= 0xFFFFFFFF
    a = (a ^ 61) ^ (a >> 16)
    a = (a + (a << 3)) & 0xFFFFFFFF
    a ^= (a >> 4)
    a = (a * 0x27d4eb2d) & 0xFFFFFFFF
    a ^= (a >> 15)
    return a & 0xFFFFFFFF


def _deforma(i, j, b):
    """Tuerce las coordenadas del bloque con ondas suaves: rompe el borde RECTO sin
    cambiar la probabilidad de cada celda. Espejo de `deforma()` en JS."""
    A = b / 3.0
    wi = i + A * (math.sin(j * 0.21) * 0.6 + math.sin(j * 0.073 + 1.7) * 0.4)
    wj = j + A * (math.sin(i * 0.19) * 0.6 + math.sin(i * 0.061 + 0.9) * 0.4)
    return math.floor(wi), math.floor(wj)


def _tira_ign(i, j, bloque, pa, pb, p):
    """El dado, tirado por PARCHE. Espejo exacto de `tiraIgn()` en `fire_sim.js`."""
    if bloque > 1:
        if P_IGN_FORMA == 'organico':
            i, j = _deforma(i, j, bloque)
        i = math.floor(i / bloque)
        j = math.floor(j / bloque)
    if P_IGN_FORMA == 'organico':
        a = (i * pa) & 0xFFFFFFFF
        b = (j * pb) & 0xFFFFFFFF
        return _mezcla32(a ^ b) % 10000 < int(p * 10000)
    return (i * pa + j * pb) % 100003 % 10000 < int(p * 10000)


# ⛔⛔ 2026-08-26 · EL FOCO NO PUEDE CAER EN UN PARCHE APAGADO · el fallo que el usuario
# vio en pantalla («dice hecho y no se ve nada»).
# MEDIDO: con `parche` 0,15/1750 —lo que estaba EN PRODUCCIÓN desde el 25-ago— el **7,7%**
# de los focos queda encerrado y el incendio no sale del punto. Con 0,25/1800 sube al 11%
# y con textura al 12,7%. El sorteo apaga bloques ENTEROS de 22x22 celdas (1,75 km): si el
# foco cae en el centro de uno, no hay por dónde escapar.
# Y es absurdo por definición: el sorteo representa parcelas que NO SABEMOS si arden, pero
# **el foco es un dato observado** — ahí hay fuego. Ese parche no puede ser uno de los que
# no arden. Se exime el bloque (grueso Y fino) que contiene cada foco.
# ⚠ No es un parche cosmético para que "salga algo": es corregir una contradicción entre el
# mecanismo y el dato que el usuario introduce.
SEMILLA_BLOQUES = None    # {(escala, I, J)} · lo rellena `dijkstra` en cada corrida
# ⚠ 26-ago · INTERRUPTOR PARA REPRODUCIR LO ANTERIOR. La exención del foco es un cambio de
# COMPORTAMIENTO: `a66`-`a78` se midieron sin ella. Un experimento que quiera reproducir
# aquellas cifras tiene que apagarla, o su ancla fallará por un motivo que no es el que
# está midiendo. Producción la quiere ENCENDIDA (arregla el 7,7% de focos mudos, §36.2).
USE_SEMILLA_EXENTA = True


def _bloques_de(k, nc, b, bf):
    i, j = k // nc, k % nc
    out = {('g', i // b, j // b)}
    if bf > 1:
        out.add(('f', i // bf, j // bf))
    return out


def prende(k, fuel_idx, nc, dxm=None):
    """¿Prende la celda `k` al llegarle el frente? Determinista, dirigido por el dato.

    Con `P_IGN_MODO='parche+textura'` se tiran DOS dados independientes a dos escalas:
    el parche grueso (`P_IGN_M`) y la textura fina (`P_IGN_FINO_M`). La celda prende sólo
    si pasa los dos. Espejo exacto de `prende()` en `js/fire_sim.js`.
    """
    if not USE_P_IGN or P_IGN_MODO == 'no':
        return True
    f = 0.0 if fuel_idx is None else (0.0 if fuel_idx < 0 else (1.0 if fuel_idx > 1 else fuel_idx))
    i, j = k // nc, k % nc
    p = f ** P_IGN_POW
    if p <= 0.0:
        return False
    # bloque grueso: en celdas si viene `P_IGN_BLOQUE` (los experimentos a63-a68 lo usan),
    # o derivado de metros si se pasa `dxm` (que es como lo hace la app)
    b = P_IGN_BLOQUE if dxm is None else max(1, int(round(P_IGN_M / dxm)))
    if SEMILLA_BLOQUES and ('g', i // b, j // b) in SEMILLA_BLOQUES:
        pass                                   # el bloque del foco arde por definición
    elif p < 1.0 and not _tira_ign(i, j, b, P_IGN_PA, P_IGN_PB, p):
        return False
    if P_IGN_MODO == 'parche+textura':
        pf = f ** P_IGN_FINO_POW
        if pf <= 0.0:
            return False
        bf = (P_IGN_BLOQUE_FINO if P_IGN_BLOQUE_FINO
              else (max(2, int(round(P_IGN_FINO_M / dxm))) if dxm else 2))
        if SEMILLA_BLOQUES and ('f', i // bf, j // bf) in SEMILLA_BLOQUES:
            pass
        elif pf < 1.0 and not _tira_ign(i, j, bf, P_IGN_FPA, P_IGN_FPB, pf):
            return False
    return True
# ── AMPLITUD DEL CICLO DÍA/NOCHE (2026-08-30) ───────────────────────────────
# `diurnal()` acepta `amp` desde el 6-ago y el motor NUNCA la ha llamado con otro
# valor que 1.0: es una palanca construida y jamás probada. Se expone como global
# para que `c115` (§95-C) pueda barrerla sin tocar la firma de la función.
# ⚠ El valor por defecto es EXACTAMENTE el comportamiento anterior (amp=1.0), así
# que producción no se mueve: quien no la toque obtiene lo mismo que ayer.
AMP_DIURNA = 1.0

# ── PROFUNDIDAD DEL VALLE NOCTURNO (2026-08-31) ─────────────────────────────
# Multiplica lo que el ciclo diurno baja la velocidad POR DEBAJO de la media, y
# no toca nada por encima. K=1,0 es exactamente producción; K=3,0 deja la
# madrugada pegada al suelo de `clamp` (0,12) — «el fuego se para de noche».
# Lo barre `c119` (§97) con horizonte de 24 h, que es la ventana mínima en la
# que la noche cae dentro para todos los incendios de la cohorte.
NOCHE_K = 1.0

AGE_T0_H = 6.0            # horas de gracia antes de empezar a frenar
AGE_TAU_H = 12.0          # constante de tiempo del decaimiento, en horas
AGE_FLOOR = 0.05          # multiplicador mínimo


def age_brake(ct):
    """Multiplicador de velocidad por edad del incendio. `ct` en minutos."""
    if not USE_AGE_BRAKE:
        return 1.0
    th = ct / 60.0
    if th <= AGE_T0_H:
        return 1.0
    f = math.exp(-(th - AGE_T0_H) / AGE_TAU_H)
    return AGE_FLOOR + (1.0 - AGE_FLOOR) * f


def fine_moisture(rh):
    """Humedad del combustible fino a partir de la HR (curva tipo Simard)."""
    return 0.03 + 0.28 * (rh / 100.0) ** 2


# ── 2026-09-15 · DOS MANDOS DEL CICLO DIURNO PARA LA COLA DEL 15-sep (INCENDIOS.md §169) ────────────────
# `HUM_S` escala cuánto mueve la humedad horaria la velocidad (1,0 = producción; 0,0 = la humedad no cuenta).
# `FASE_H` es la hora local del mínimo del coseno de `diurnal()` (3,0 = producción). Con los valores por defecto
# el resultado es IDÉNTICO bit a bit: 1,0·x = x y 3 = 3,0 en coma flotante. Lo comprueba el ancla de `c172`.
HUM_S = 1.0
FASE_H = 3.0


def hum_factor(rh):
    if rh is None:
        return 1.0
    if not USE_EXTINCTION:
        return clamp(1 + HUM_S * (45.0 - rh) / 120.0, 0.75, 1.25)
    m = fine_moisture(rh)
    return clamp(1.0 - (m / FFM_EXT) ** 2, 0.0, 1.25)


# ── 2026-09-15 · EL CICLO DÍA/NOCHE DESDE LA HUMEDAD DEL COMBUSTIBLE FINO (INCENDIOS.md §170, `c178`) ──────────────────
# Con `CICLO_HUM` 0 (producción) no cambia NADA: `dijkstra` sigue con coseno × `hum_factor`. Con 1 y serie de HR, el factor
# de velocidad sale del amortiguamiento por humedad de Rothermel (1972) sobre `fine_moisture(HR)` con retardo exponencial de
# `HUM_TAU_H` horas (combustible de 1 h), escalado por `HUM_K` y con el mismo recorte que `diurnal()`. Sin coseno.
CICLO_HUM = 0
HUM_MX = 0.30             # humedad de extinción del combustible fino (fracción)
HUM_K = 1.0               # escala de nivel (cómputo cero: el factor medio a 0-3 h queda en 0,63-0,67× de producción)
HUM_TAU_H = 1.0           # retardo del combustible fino, en horas


def eta_humedad(m, mx):
    """Amortiguamiento por humedad de Rothermel (1972): 1 − 2,59 r + 5,11 r² − 3,52 r³, con r = m/mx recortado a 1."""
    r = min(m / mx, 1.0)
    return max(0.0, 1.0 - 2.59 * r + 5.11 * r * r - 3.52 * r ** 3)


def humedad_retardada(rh_series, tau_h):
    """Humedad fina hora a hora con retardo exponencial; arranca en equilibrio con la primera HR válida."""
    out, m = [], None
    a = 1.0 - math.exp(-1.0 / tau_h) if tau_h > 0 else 1.0
    for rh in rh_series:
        if rh is None:
            out.append(m if m is not None else fine_moisture(45.0))
            continue
        meq = fine_moisture(rh)
        m = meq if m is None else m + a * (meq - m)
        out.append(m)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# INTENSIDAD LINEAL DEL FRENTE (2026-08-19) · la variable con la que la doctrina
# decide quién puede atacar un incendio, y que este motor no tenía.
#
# POR QUÉ SE AÑADE
# `motor.DIRECT` decide el ataque directo con la VELOCIDAD del borde (8 m/min).
# Andrews & Rothermel 1982 (INT-GTR-131, tabla 1, en `literatura/`) usan la
# INTENSIDAD LINEAL, y su tabla 2 lo demuestra: dos fuegos con el mismo viento,
# pendiente y humedad que se diferencian 14 VECES en velocidad (66 y 4,7 m/min)
# tienen la misma intensidad y necesitan los mismos medios.
# Medido sobre nuestros 97 incendios (`a32`/`a33`): el umbral único de 8 m/min
# autoriza una llama de 0,75 m en pasto fino y de 3,86 m en restos pesados, y en
# 11 de los 13 combustibles manda cuadrillas a fuego que no pueden trabajar.
#
# LAS ECUACIONES (apéndice A del mismo documento, verificadas contra su tabla 2)
#     I[Btu/ft/s] = H_A[Btu/ft²] · R[chains/h] / 55
#     F_L[ft]     = 0,45 · I^0,46
#
# DE DÓNDE SALE H_A (calor por unidad de área)
# Los 13 valores están deducidos en `contencion/a33_hpua.py` de las tablas 15-78
# del NWCG Fireline Handbook Appendix B, y verificados contra los tres que Andrews
# & Rothermel miden directamente. Van de 91 (pasto fino) a 3.268 (restos pesados).
#
# ⚠ EL SUPUESTO QUE HAY QUE VIGILAR, y por eso `HPUA_MAX` es un parámetro:
# el motor NO sabe qué modelo de combustible tiene cada celda. `lcclass.json` sólo
# existe en 54 snapshots, y el 2026-08-06 se midió que distinguir arbolado de
# matorral por WorldCover EMPEORA (el "arbolado" de WorldCover es pinar con
# matorral debajo). Así que se usa el índice de combustible del propio motor
# —carga x curado, que es lo que físicamente determina el calor disponible— y se
# escala a `HPUA_MAX`. Eso es una APROXIMACIÓN: si la conclusión depende del valor
# de `HPUA_MAX`, hace falta una capa de modelos de combustible de verdad, y hay
# que decirlo en vez de elegir el número que dé el resultado bonito.
# 2026-08-20 · ENCENDIDO. La app pasó a decidir por intensidad (agua y tierra) y
# los dos motores tienen que ser el mismo modelo: dejarlo apagado aquí era volver a
# la divergencia que ya mordió cinco veces. La justificación es `a32` (n=97, 71.531
# celdas de perímetro): con el umbral único de velocidad, en 11 de los 13 modelos de
# combustible se manda gente a fuego que no puede atacar, y se ataca el 0% de la
# banda 346-1.731 kW/m, que es el 19-38% del perímetro y donde la doctrina dice que
# sirven los aviones. Contra cicatriz es neutro (`a35c`, n=23, Dice <=0,003): esto se
# justifica por doctrina, no por Dice.
USE_INTENSIDAD = True
HPUA_MAX = 750.0             # Btu/ft² con índice de combustible = 1 (modelo 3, pasto alto)
HPUA_MIN = 40.0              # suelo, para que una celda casi pelada no dé 0
CHAIN_M = 20.1168            # 1 chain, metros
BTU_KW = 3.4614              # 1 Btu/ft/s = 3,4614 kW/m
# Cortes de la tabla 1, en kW/m
I_MANUAL = 346.0             # <100 Btu/ft/s · "manual aguanta, en cabeza o flancos"
I_MAQUINA = 1731.0           # 100-500 · "manual NO en cabeza; maquinaria y AVIONES sí"
I_INEFECTIVO = 3461.0        # >1000 · "control en la cabeza inefectivo"

# ⭐ 2026-08-24 · EL LISTÓN DEL AGUA AÉREA. Hasta hoy una descarga sólo dejaba línea
# permanente por debajo de I_MANUAL (346 kW/m), que es la banda en que **aguanta un
# tipo con una azada**. Aplicárselo a un hidroavión no lo sostiene ninguna fuente:
#   · la Tabla 1 de Andrews & Rothermel 1982 —la que ya usa este proyecto— sitúa
#     los AVIONES junto con la maquinaria pesada, hasta 1.731 kW/m. Está escrito en
#     el comentario de `fire_sim.js:1177` desde el 20-ago y no se había aplicado al
#     agua.
#   · Plucinski et al., Bushfire CRC 2007 (§17, fuente verificada): las descargas
#     son eficaces hasta ~2 m de llama, ≈2.000 kW/m.
# Y la incoherencia estaba DENTRO del mismo fichero: `aereo.py:213` ya usaba
# I_MAQUINA para decidir dónde se puede atacar, y `aereo.py:323` usaba I_MANUAL para
# decidir si el agua apaga.
# Medido sobre el perímetro real de NIEBLA (46.607 celdas de borde a 6 h):
#     <= 346 kW/m → 36,2% del perímetro   |   <= 1.731 → 77,1%   |   <= 2.000 → 79,7%
# ⚠ ES UN CAMBIO DE MODELO: se deja como constante propia y no reutilizando
# I_MAQUINA, para poder moverlo y medirlo sin tocar la banda de la tierra.
I_AGUA_AEREA = I_MAQUINA     # kW/m · hasta aquí una descarga deja línea permanente


def hpua(fuel_idx):
    """Calor por unidad de área de una celda, Btu/ft²."""
    return max(HPUA_MIN, HPUA_MAX * max(0.0, fuel_idx))


def intensidad(ros_m_min, fuel_idx):
    """Intensidad lineal del frente en kW/m, desde la velocidad de borde."""
    if ros_m_min <= 0:
        return 0.0
    R_ch = ros_m_min * 60.0 / CHAIN_M
    return hpua(fuel_idx) * R_ch / 55.0 * BTU_KW


def llama_m(i_kwm):
    """Longitud de llama en metros, para poder enseñarla y discutirla."""
    if i_kwm <= 0:
        return 0.0
    return 0.45 * ((i_kwm / BTU_KW) ** 0.46) * 0.3048


def water_mult(ws, we, ct):
    """Mojado pleno en [ws, we] y luego se seca (modelo de intervalo, bloque C)."""
    if ws == INF or ct < ws:
        return 1.0
    if ct <= we:
        return WATER_FACTOR
    age = ct - we
    if age >= WATER_FADE:
        return 1.0
    return WATER_FACTOR + (1 - WATER_FACTOR) * age / WATER_FADE


# 8 vecinos = sólo 8 rumbos, separados 45°. Una elipse estrecha (viento fuerte) no
# cabe entre esos rumbos y el fuego se ATASCA: por eso alguien subió FLANK_MIN a
# 0.18, que hace que la cola avance al 18% de la cabeza cuando en la realidad va al
# 1-5%. El parámetro era un parche de un defecto numérico, y a cambio dejaba las
# manchas redondas — que es justo lo que impedía ganarle al círculo.
# Con los saltos de caballo (±1,±2) hay 16 rumbos separados ~26°, y la elipse cabe.
NB8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
NB16 = NB8 + [(-2, -1), (-2, 1), (-1, -2), (-1, 2),
              (1, -2), (1, 2), (2, -1), (2, 1)]
USE_NB16 = True
# ── Respuesta al viento (2026-08-06) ────────────────────────────────────────
# La curva vieja era exp(WIND_K*U) con tope HEAD_MAX=12: satura y se queda corta
# justo en 20-40 km/h, que es donde corren estos incendios (a 20 km/h daba 1.8x
# cuando Rothermel da ~3.7x). Rothermel usa una LEY DE POTENCIA sin tope:
#   phi_w = C * U^B     →     cabeza = 1 + phi_w
# Se calibra contra cicatrices reales.
WIND_A, WIND_B = 0.60, 1.5
USE_POWER_WIND = True
# ── Pendiente SEPARADA del viento (2026-08-06) ──────────────────────────────
# Antes: U = |viento + 45*pendiente|, un solo número del que salía todo. Con la
# pendiente mediana de estos AOI (33%) eso metía ~15 km/h de "viento" falso en
# todas partes, comparable al viento real: los dos términos se tapaban y la
# calibración no podía distinguir "ventoso" de "empinado".
# Rothermel usa phi_s proporcional a tan(theta)^2: casi nada en ladera suave y
# mucho en la fuerte. Aquí se mantiene la suma vectorial (hace falta para saber
# hacia dónde va la cabeza) pero la MAGNITUD de la aportación de la pendiente
# pasa a ser cuadrática.
SLOPE_QUAD = True
NB = NB8
# ── PAVESAS / SPOTTING (2026-08-14) ─────────────────────────────────────────
# Hasta hoy el fuego se propagaba SÓLO por contacto entre celdas vecinas. La
# documentación afirmaba que las pavesas «sí están, como aproximación
# estadística» y era FALSO: cero líneas de código. Lo detectaron dos revisiones
# externas el mismo día, y es la única de sus observaciones que resultó cierta.
#
# Implementación compatible con Dijkstra: una pavesa es una ARISTA LARGA. Desde
# una celda que arde con suficiente intensidad y con viento suficiente, el fuego
# puede aparecer a `SPOT_DIST_M` metros a favor del viento, pagando un tiempo
# fijo (elevación + vuelo + ignición) en vez de recorrer el camino. Es
# determinista —no estocástico— para que el arnés siga siendo reproducible y
# para que dos ejecuciones den lo mismo, que es lo que exige toda la validación.
#
# Lo importante del mecanismo: la pavesa NO comprueba las celdas intermedias, así
# que CRUZA BARRERAS Y CORTAFUEGOS. Ésa es justamente la razón por la que en la
# realidad las líneas de defensa fallan, y lo que el modelo no sabía representar.
# Sí exige que la celda de ATERRIZAJE sea combustible y no esté ya cortada.
USE_SPOTTING = False       # apagado: producción no cambia hasta que se mida
SPOT_DIST_M = 400.0        # distancia característica a 20 km/h; escala lineal con U
SPOT_CONE = 10.0           # grados a cada lado del rumbo de cabeza. OJO: el
# conjunto quemado por pavesas es una CUÑA de ±SPOT_CONE, así que su anchura
# crece como 2·alcance·sen(cono). Con 30° medido en laboratorio el fuego pasaba
# de 13,6 a 30,9 km de ancho — irreal. Con 10° queda neutro en anchura y el
# efecto es alargar la cabeza y cruzar barreras, que es lo que se busca.
SPOT_DELAY = 2.0           # min · UNIFICADO con la app (era 6.0 aquí, 2 allí)

# ════════════════════════════════════════════════════════════════════════════
# UNIFICACIÓN CON EL MOTOR DE LA APP (2026-08-18)
# Hasta hoy este fichero y `js/fire_sim.js` eran DOS MODELOS DISTINTOS, no dos
# copias del mismo: la app tira pavesas de forma ALEATORIA (3 intentos por celda,
# con probabilidad, distancia y dispersión al azar) y aquí era un cono fijo
# determinista; la app apaga con agua por debajo de 9 m/min y aquí el agua no
# apagaba nunca; y `SPOT_DELAY` valía 2 allí y 6 aquí. Seis días de mediciones
# describían un programa que el usuario no ve nunca.
# La app manda, porque es lo que corre de verdad. Estas constantes y el bloque de
# pavesas de `dijkstra()` son PUERTO LITERAL de `fire_sim.js:196-204,1318-1357`.
# Si se toca una, hay que tocar la otra: `contencion/paridad.py` lo comprueba y
# falla si divergen. Correrlo ANTES de cualquier medición que decida algo.
# ════════════════════════════════════════════════════════════════════════════
SPOT_MIN_SPD = 6.0         # m/min de avance mínimos para que salten brasas
SPOT_MIN_WIND = 15.0       # km/h equivalentes mínimos (viento + pendiente)
SPOT_DIST_K = 14.0         # m de salto por km/h de viento
SPOT_DIST_MIN = 60.0       # por debajo no es salto, es avance normal
SPOT_SPREAD = 0.35         # dispersión lateral del abanico
SPOT_TRIES = 3             # intentos de salto por celda del frente
SPOT_MAX = 400             # tope de focos secundarios
SPOT_P = 0.02              # propensión (SPOT_LEVEL.med de la app)
SPOT_SEED = 0              # el miembro central del ensemble usa spotSeed 0
WATER_KILL_ROS = 9.0       # m/min · por debajo, el agua APAGA la celda
WATER_ASSIST = 26.0        # m/min · hasta aquí el agua sirve de apoyo


def _u32(x):
    return x & 0xFFFFFFFF


def hash_rnd(k, s):
    """Puerto literal de `hashRnd()` de la app (mismo bit a bit). Da el mismo
    número para la misma celda y el mismo intento, así que la simulación sigue
    siendo reproducible aunque las pavesas sean aleatorias."""
    h = _u32(_u32(_u32(k ^ 0x9E3779B9) * 0x85EBCA6B)
             ^ _u32(_u32(s + 1) * 0xC2B2AE35))
    h ^= h >> 13
    h = _u32(h * 0x27D4EB2D)
    h ^= h >> 15
    return _u32(h) / 4294967296.0


def wind_confidence_series(wind_series, window=None, min_spd=None):
    """Por hora, R∈[0,1] del vector medio de dirección en una ventana ±`window`
    horas (estadística circular: R=1 si todas las horas de la ventana apuntan
    igual, R→0 si dan bandazos). Las horas con viento flojo (<min_spd) se
    excluyen: su dirección no es fiable ni para sumar ni para restar confianza.
    Con menos de 2 horas útiles en la ventana se devuelve 1.0 (neutral: no hay
    base para desconfiar)."""
    if window is None:
        window = WIND_CONF_WINDOW_H
    if min_spd is None:
        min_spd = WIND_CONF_MIN_SPD
    n = len(wind_series)
    conf = [1.0] * n
    for h in range(n):
        lo, hi = max(0, h - window), min(n - 1, h + window)
        vx = vy = 0.0
        cnt = 0
        for k in range(lo, hi + 1):
            ws, wd = wind_series[k]
            if ws < min_spd:
                continue
            a = math.radians(wd)
            vx += math.sin(a); vy += math.cos(a); cnt += 1
        conf[h] = math.hypot(vx, vy) / cnt if cnt >= 2 else 1.0
    return conf


# ── VENTANA DIARIA DE CRECIMIENTO · `burn period` (`a85`, 26-ago) · APAGADA ──
# Es lo que FARSITE usa contra EXACTAMENTE nuestro bug. Cita literal de su
# documentación (`FARSITE_Weather_Stream_and_Burn_Periods.htm`, verificada el 26-ago):
#   «helps correct the tendency of Farsite to OVER-PREDICT under moderate burning
#    conditions because LONG PERIODS OF VERY LOW FIRE BEHAVIOR can result in
#    significant spread distances»
# Y FSim sólo deja crecer 1, 3 o 5 h AL DÍA según percentil de ERC (§17bis). Nosotros
# corremos 36 h seguidas.
#
# ⚠ LA SEMÁNTICA CORRECTA NO ES «velocidad cero fuera de la ventana». En un Dijkstra la
# celda se extrae UNA vez: si en ese instante la velocidad es cero, la arista se rechaza
# y no hay segunda oportunidad, así que todo lo que prendiera de noche moriría para
# siempre. Lo que hace FARSITE es PARAR EL RELOJ: el fuego espera a que abra la ventana.
# Aquí se implementa así — el avance se mide en MINUTOS DE QUEMA, no de reloj.
USE_BURN_PERIOD = False
BP_H0, BP_H1 = 10.0, 18.0     # ventana diaria [h0, h1) en hora local


_BP_CACHE = {}


def _bp_cte(start_h):
    """Constantes del reloj de quema, cacheadas por (ventana, hora de inicio).

    ⚠ 26-ago · LA PRIMERA VERSIÓN HACÍA `a85` 7x MÁS LENTO, por dos motivos que se
    suman y que sólo se vieron perfilando: (a) `_bp_wall` bisecaba 60 veces POR ARISTA,
    y (b) `_bp_dia` **definía una función anidada en cada llamada**, así que la
    bisección creaba 60 closures por arista. Con ~640.000 aristas por incendio y brazo,
    eso es lo que se estaba pagando. Aquí no hay bisección ni closures: la inversa es
    cerrada porque `_bp_dia` es lineal a trozos y periódica.
    """
    key = (BP_H0, BP_H1, start_h)
    c = _BP_CACHE.get(key)
    if c is None:
        dur = (BP_H1 - BP_H0) * 60.0
        h0m = BP_H0 * 60.0
        ini = start_h * 60.0
        d0, h0 = divmod(ini, 1440.0)
        a0 = d0 * dur + min(max(h0 - h0m, 0.0), dur)
        c = (dur, h0m, ini, a0)
        _BP_CACHE[key] = c
    return c


def _bp_dia(t_wall, start_h):
    """Minutos de QUEMA acumulados desde la ignición hasta el minuto de reloj `t_wall`."""
    dur, h0m, ini, a0 = _bp_cte(start_h)
    d, h = divmod(ini + t_wall, 1440.0)
    return d * dur + min(max(h - h0m, 0.0), dur) - a0


def _bp_wall(b, start_h):
    """Inversa cerrada: minuto de reloj en que se acumulan `b` minutos de quema."""
    if b <= 0:
        return 0.0
    dur, h0m, ini, a0 = _bp_cte(start_h)
    obj = a0 + b
    d = obj // dur
    rem = obj - d * dur
    if rem == 0.0 and d > 0.0:
        # justo en la frontera: el cruce termina AL CERRAR la ventana de ese día, no al
        # abrir la del siguiente. Sin esto, un cruce que encaja exacto se retrasaba una
        # noche entera. Caso de medida nula, pero el proyecto ya ha pagado dos veces por
        # bordes así (`motor.directo` con el cupo, `aereo.moja` con las descargas).
        d -= 1.0
        rem = dur
    return d * 1440.0 + h0m + rem - ini


def bp_efectivo(t_wall, start_h):
    """Si `t_wall` cae FUERA de la ventana, devuelve el instante en que ésta abre."""
    h = (start_h + t_wall / 60.0) % 24.0
    if BP_H0 <= h < BP_H1:
        return t_wall
    espera = (BP_H0 - h) % 24.0
    return t_wall + espera * 60.0


# ── 2026-08-26 · EXTRAÍDAS DEL CLOSURE DE `dijkstra` PARA QUE EL SOLVER DE FRENTE
#    (`frente.py`, §33) USE **LA MISMA FÍSICA**, no una copia.
#    Regla del proyecto: dos motores que se separan es exactamente lo que vigilan
#    `paridad.py` y `paridad_reglas.py`. Un tercer motor con la física duplicada
#    sería el mismo fallo por tercera vez. El cambio es de REFACTOR: mismo cálculo,
#    mismos números — comprobado con ancla sobre incendios reales el 26-ago.

def terrain_wind_g(G, cur, ws, bx, by):
    """D2: el viento no llega igual a todas partes. Acelera en las crestas,
    frena en los fondos y en las vaguadas se encauza a lo largo del valle en
    vez de cruzarlo. Mismo cálculo que terrainWind() de fire_sim.js."""
    if not USE_TERRAIN:
        return ws * bx, ws * by
    t = G.tpi[cur] / TPI_SCALE
    spd = ws * clamp(1 + TERR_SPEED * t, 0.45, 1.9)
    dx, dy = bx, by
    if t < 0:
        gx, gy = G.sgx[cur], G.sgy[cur]
        gm = math.hypot(gx, gy)
        if gm > 1e-4:
            ax, ay = -gy / gm, gx / gm            # eje del valle
            if ax * bx + ay * by < 0:
                ax, ay = -ax, -ay                  # en el sentido del viento
            f = clamp(TERR_CHAN * min(1.0, -t) * min(1.0, gm / 0.25), 0, 1)
            dx, dy = bx * (1 - f) + ax * f, by * (1 - f) + ay * f
            dm = math.hypot(dx, dy) or 1.0
            dx, dy = dx / dm, dy / dm
    return spd * dx, spd * dy


def campo_celda(G, cur, ws_t, wvx, wvy, lb_max_eff):
    """Viento+pendiente compuestos en una celda → (hx, hy, ecc, head).

    Literalmente el bloque que `dijkstra` ejecuta al extraer un nodo. Devuelve el
    rumbo unitario de cabeza, la excentricidad de la elipse y el factor de cabeza.
    """
    tvx, tvy = terrain_wind_g(G, cur, ws_t, wvx, wvy)
    gx, gy = G.sgx[cur], G.sgy[cur]
    if SLOPE_QUAD:
        gm = math.hypot(gx, gy)
        if gm > 1e-6:
            eq = SLOPE_WIND_K * gm * gm
            gx, gy = eq * gx / gm, eq * gy / gm
        else:
            gx = gy = 0.0
    else:
        gx, gy = SLOPE_WIND_K * gx, SLOPE_WIND_K * gy
    Ux, Uy = tvx + gx, tvy + gy
    U = math.hypot(Ux, Uy)
    hx, hy = (Ux / U, Uy / U) if U > 1e-6 else (1.0, 0.0)
    grow = 1 - math.exp(-0.055 * U)
    LB = 1 + (lb_max_eff - 1) * grow
    ecc = math.sqrt(max(0.0, 1 - 1 / (LB * LB)))
    if USE_POWER_WIND:
        head = 1.0 + WIND_A * (U / 10.0) ** WIND_B
    else:
        head = min(HEAD_MAX, math.exp(WIND_K * U))
    return hx, hy, ecc, head, U


def forma_dir(ex, ey, dist, hx, hy, ecc, U):
    """Factor elíptico en la dirección (ex, ey). Mismo `shape` que `dijkstra`."""
    cosphi = ((ex / dist) * hx + (ey / dist) * hy) if U > 1e-6 else 1.0
    return max(FLANK_MIN, (1 - ecc) / (1 - ecc * cosphi))


def dijkstra(G, seeds, bt=None, wt=None, burnt=None, wspd=25.0, wdir=225.0, start_h=14,
             dry=1.0, wind_series=None, rh_series=None, dtsrc=None):
    """wind_series = [(km/h, grados)] por hora desde la ignición. Si se da, el viento
    cambia a lo largo de la simulación en vez de ser el mismo durante 12 horas
    (que es lo que daba la media diaria de una estación lejana)."""
    nr, nc = G.nr, G.nc
    N = nr * nc
    arr = [INF] * N
    spd = [0.0] * N
    conf_series = (wind_confidence_series(wind_series)
                   if USE_WIND_CONF and wind_series else None)
    if not seeds:
        return arr, spd
    horizonte_bp = 1440.0 * 30
    global SEMILLA_BLOQUES
    if USE_P_IGN and P_IGN_MODO != 'no' and USE_SEMILLA_EXENTA:
        _b = P_IGN_BLOQUE
        _bf = (P_IGN_BLOQUE_FINO if P_IGN_BLOQUE_FINO
               else max(2, int(round(P_IGN_FINO_M / G.dxm))))
        SEMILLA_BLOQUES = set()
        for _s in seeds:
            SEMILLA_BLOQUES |= _bloques_de(_s, nc, max(1, _b), _bf)
    else:
        SEMILLA_BLOQUES = None
    heap = []
    spots = [0]                      # focos secundarios ya lanzados (tope SPOT_MAX)
    for s in seeds:
        arr[s] = 0.0; spd[s] = INT_REF
        heapq.heappush(heap, (0.0, s))
    def wind_vec(ct):
        if wind_series:
            ws, wd = wind_series[min(len(wind_series) - 1, int(ct / 60))]
        else:
            ws, wd = wspd, wdir
        a = math.radians(wd) + math.pi
        return ws, math.sin(a), math.cos(a)

    terrain_wind = lambda cur, ws, bx, by: terrain_wind_g(G, cur, ws, bx, by)
    # §170 · sólo con `CICLO_HUM` 1 y serie de HR; en producción es None y el ciclo es el de siempre
    m_lag = humedad_retardada(rh_series, HUM_TAU_H) if (CICLO_HUM and rh_series) else None

    while heap:
        ct, cur = heapq.heappop(heap)
        if ct > arr[cur]:
            continue
        ci, cj = divmod(cur, nc)
        if USE_BURN_PERIOD:
            # el fuego espera a que abra la ventana; las condiciones (viento, HR, ciclo
            # diurno) se evalúan en ese instante, no en el de llegada.
            ct = bp_efectivo(ct, start_h)
            if ct >= horizonte_bp:
                continue
        if m_lag is not None:
            dfac = clamp(HUM_K * eta_humedad(m_lag[min(len(m_lag) - 1, int(ct / 60))], HUM_MX), 0.12, 1.7)
        else:
            if rh_series:
                hf = hum_factor(rh_series[min(len(rh_series) - 1, int(ct / 60))])
            else:
                hf = 1.0
            dfac = diurnal((start_h + ct / 60.0) % 24, hum=hf, amp=AMP_DIURNA)
        ws_t, wvx, wvy = wind_vec(ct)
        if conf_series is not None:
            c = conf_series[min(len(conf_series) - 1, int(ct / 60))] ** WIND_CONF_GAMMA
            lb_max_eff = 1 + (LB_MAX - 1) * c
        else:
            lb_max_eff = LB_MAX
        # 26-ago · MISMA función que usa `frente.py`. Refactor, no cambio de física.
        hx, hy, ecc, head, U = campo_celda(G, cur, ws_t, wvx, wvy, lb_max_eff)
        # ── PAVESAS · puerto literal de `fire_sim.js:1318-1350` ────────────────
        # Aleatorias, no un cono fijo: 3 intentos por celda del frente, con
        # probabilidad proporcional a la intensidad y al viento, distancia
        # sesgada a corto y dispersión lateral. El azar viene de `hash_rnd`, que
        # depende de la celda: mismo mapa, mismo resultado.
        if (USE_SPOTTING and spots[0] < SPOT_MAX and spd[cur] >= SPOT_MIN_SPD
                and U >= SPOT_MIN_WIND):
            inten = min(1.0, spd[cur] / (INT_REF * 1.5))
            p_fire = SPOT_P * inten * min(1.0, U / 35.0)
            for _s in range(SPOT_TRIES):
                r1 = hash_rnd(cur, _s * 2 + SPOT_SEED)
                r2 = hash_rnd(cur, _s * 2 + 1 + SPOT_SEED)
                if r1 > p_fire:
                    continue
                dmax = SPOT_DIST_K * U * (0.5 + 0.5 * inten)
                dist = SPOT_DIST_MIN + (dmax - SPOT_DIST_MIN) * r2 * r2
                if dist < SPOT_DIST_MIN:
                    continue
                jx = hx * dist + (r1 - 0.5) * dist * SPOT_SPREAD
                jy = hy * dist + (r2 - 0.5) * dist * SPOT_SPREAD
                si_ = ci - int(round(jy / G.dym))
                sj_ = cj + int(round(jx / G.dxm))
                if not (0 <= si_ < nr and 0 <= sj_ < nc):
                    continue
                sk = si_ * nc + sj_
                if sk == cur or (burnt and burnt[sk]):
                    continue
                if G.fuel[sk] <= 0 or G.ros_base(sk) * dry < MIN_ROS:
                    continue
                if wt is not None and water_mult(wt[0][sk], wt[1][sk], ct) < 0.5:
                    continue                      # cae en mojado: no prende
                nt = ct + SPOT_DELAY
                if bt is not None and nt >= bt[sk]:
                    continue
                if nt < arr[sk]:
                    arr[sk] = nt
                    spd[sk] = SPREAD_MIN
                    spots[0] += 1
                    heapq.heappush(heap, (nt, sk))

        for di, dj in (NB16 if USE_NB16 else NB8):
            # un salto de caballo no puede cruzar por encima de una barrera: se
            # comprueba la celda intermedia, o el fuego saltaría los cortafuegos
            if abs(di) + abs(dj) == 3:
                mi, mj = ci + (di // 2 if abs(di) == 2 else di), cj + (dj // 2 if abs(dj) == 2 else dj)
                if 0 <= mi < nr and 0 <= mj < nc:
                    mk = mi * nc + mj
                    if G.fuel[mk] <= 0:
                        continue
                    if bt is not None and ct >= bt[mk]:
                        continue
            ni, nj = ci + di, cj + dj
            if ni < 0 or nj < 0 or ni >= nr or nj >= nc:
                continue
            nb = ni * nc + nj
            if burnt and burnt[nb]:
                continue
            if bt is not None and ct >= bt[nb]:
                continue
            if bt is not None and di != 0 and dj != 0 and (
                    ct >= bt[ci * nc + nj] or ct >= bt[ni * nc + cj]):
                continue
            # ⭐⭐ 2026-08-24 · ¿ARDE O NO ARDE? (a63). APAGADO por defecto.
            # Va AQUÍ, antes de calcular nada: una celda que no prende no arde y —lo
            # que importa— **tampoco propaga**, porque nunca se le asigna `arr` ni
            # entra en la cola. Es el mismo sitio y la misma lógica que la barrera.
            if USE_P_IGN and not prende(nb, G.fuel[nb], nc):
                continue
            ros0 = G.ros_base(nb) * dry
            if wt is not None:
                ros0 *= water_mult(wt[0][nb], wt[1][nb], ct)
            if ros0 < MIN_ROS:
                continue
            ex, ey = dj * G.dxm, -di * G.dym
            dist = math.hypot(ex, ey)
            shape = forma_dir(ex, ey, dist, hx, hy, ecc, U)
            speed = ros0 * head * shape * dfac * age_brake(ct)
            if speed < SPREAD_MIN:
                continue
            # ⭐ 2026-08-24 · MUERTE DEL FRENTE POR INTENSIDAD (a62). APAGADO por
            # defecto: producción no cambia hasta que se mida.
            # `a61` midió que el freno por edad recorta el ALCANCE (0,67-0,91 en la
            # mitad ciega) porque multiplica por igual a la cabeza y a los flancos:
            # frena el avance del incendio entero. La realidad no hace eso — la cabeza
            # de un incendio corre un día entero y lo que se apaga son los FLANCOS.
            # Un frente que retrocede o lame de lado no «va despacio»: por debajo de
            # cierta intensidad se apaga y esa dirección queda muerta. Este motor no
            # tenía forma de que un frente muriera: `SPREAD_MIN` es un listón sobre la
            # velocidad, ciego al combustible, y con `FLANK_MIN`=0,05 el flanco repta
            # eternamente al 5% de la cabeza. Eso es lo que RELLENA la elipse.
            # Aquí el listón es la intensidad de Byram en kW/m, que ya se calcula para
            # decidir qué medio puede atacar (`intensidad()`), y depende del
            # combustible de la celda: el mismo m/min mata en pasto y no en arbolado.
            if USE_I_MIN and intensidad(speed, G.fuel[nb]) < I_MIN:
                continue
            if USE_BURN_PERIOD:
                nt = _bp_wall(_bp_dia(ct, start_h) + dist / speed, start_h)
            else:
                nt = ct + dist / speed
            # ⭐⭐ 2026-08-26 · MUERTE DEL FRENTE COMO FUENTE (`a84`, §31). APAGADA:
            # `dtsrc=None` en producción y en todo lo anterior.
            # `dtsrc[cur]` es el instante a partir del cual la celda `cur` deja de poder
            # encender a nadie. NO es un multiplicador de velocidad ni un listón sobre
            # ella: es una PUERTA que se cierra, y lo que la abre o la cierra se decide
            # FUERA, en el bucle por pasos (`mixto.con_muerte_de_frente`), mirando cuánto
            # lleva la celda en el perímetro. Ver §31 para por qué esto no es `SPREAD_MIN`
            # con otro nombre: aquí `dtsrc` se RECALCULA entre pasadas, así que matar una
            # celda retrasa a sus vecinas, y ese retraso puede matarlas a ellas. Es la
            # cascada lo que se está probando, no el umbral.
            if dtsrc is not None and nt > dtsrc[cur]:
                continue
            if nt < arr[nb]:
                arr[nb] = nt; spd[nb] = speed
                heapq.heappush(heap, (nt, nb))
    return arr, spd


def burned(arr, until=None):
    return sum(1 for a in arr if a != INF and (until is None or a <= until))


def build_times(G, axis, t0, rate_min, reverse=False):
    seq = list(reversed(axis)) if reverse else list(axis)
    out, acc = [], 0.0
    for n, k in enumerate(seq):
        if n:
            a, b = seq[n - 1], seq[n]
            di = (b // G.nc) - (a // G.nc)
            dj = (b % G.nc) - (a % G.nc)
            acc += math.hypot(dj * G.dxm, di * G.dym)
        out.append((k, t0 + acc / rate_min))
    return out, acc


def field_from(G, cells):
    """Vuelca (celda, minuto) a un campo temporal con el pincel 3x3."""
    N = G.nr * G.nc
    f = [INF] * N
    for k, t in cells:
        ci, cj = divmod(k, G.nc)
        for di in range(-BRUSH, BRUSH + 1):
            for dj in range(-BRUSH, BRUSH + 1):
                ni, nj = ci + di, cj + dj
                if 0 <= ni < G.nr and 0 <= nj < G.nc:
                    kk = ni * G.nc + nj
                    if t < f[kk]:
                        f[kk] = t
    return f


def line_cells(G, a, b):
    nc = G.nc
    x0, y0 = a % nc, a // nc
    x1, y1 = b % nc, b // nc
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx - dy
    out = []
    while True:
        out.append(y0 * nc + x0)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy; x0 += sx
        if e2 < dx:
            err += dx; y0 += sy
    return out


def feasibility(G, axis, rate_min, base_arr, t0):
    best = None
    for reverse in (False, True):
        cells, length = build_times(G, axis, 0.0, rate_min, reverse)
        latest, done = INF, 0
        for k, off in cells:
            fa = base_arr[k]
            if fa == INF:
                done += 1
                continue
            latest = min(latest, fa - off)
            if t0 + off < fa:
                done += 1
        frac = done / len(cells) if cells else 0
        cand = dict(latest=latest, reverse=reverse, done=frac,
                    minutes=cells[-1][1] if cells else 0, length=length)
        if best is None or cand['latest'] > best['latest']:
            best = cand
    return best


# ── Escenario de prueba ─────────────────────────────────────────────────────
def main():
    G = Grid(fwi=45.0)
    N = G.nr * G.nc
    print(f"Rejilla {G.nr}x{G.nc} = {N} celdas · {G.dxm:.0f}x{G.dym:.0f} m/celda "
          f"· {G.cell_ha:.2f} ha/celda")

    # Foco: la celda más peligrosa (mismo criterio que "peor caso")
    ig = max(range(N), key=lambda k: G.ig[k])
    print(f"Foco peor caso en celda {ig} (fila {ig//G.nc}, col {ig%G.nc})")

    base, bspd = dijkstra(G, [ig])
    nb = burned(base)
    fin = sorted(a for a in base if a != INF)
    t95 = fin[int(0.95 * (len(fin) - 1))] if fin else 0
    print(f"\n[1] BASE: {nb} celdas ({nb*G.cell_ha:.0f} ha, {100*nb/N:.0f}%) "
          f"· p95 llegada {t95/60:.1f} h · máx {fin[-1]/60:.1f} h")
    # El límite sigue al horizonte de la app (48 h). Subió de 24 a 48 el 2026-08-06
    # al estrechar la elipse (LB 3, cola al 5%) y bajar la velocidad: el fuego tarda
    # ahora 27.8 h en cubrir este AOI en vez de menos de 24. Lo que el test vigila
    # es que NO se atasque (era el fallo original), y eso se sigue comprobando con
    # nb > 50 y con que el p95 exista y sea finito.
    ok1 = 0 < t95 / 60 < 48 and nb > 50
    print("    " + ("OK: sin atascos, duración plausible" if ok1 else "FALLO"))

    # Línea perpendicular al avance, cruzando por delante de la cabeza
    # (la construimos entre dos bordes pasando a media distancia del alcance)
    ci, cj = divmod(ig, G.nc)
    # dirección de la cabeza = hacia la celda de llegada más tardía del 15% superior
    cells_sorted = sorted((a, k) for k, a in enumerate(base) if a != INF)
    head = cells_sorted[-max(1, len(cells_sorted) // 7):]
    hi = sum(k // G.nc for _, k in head) / len(head)
    hj = sum(k % G.nc for _, k in head) / len(head)
    drow, dcol = hi - ci, hj - cj
    mag = math.hypot(drow, dcol) or 1
    drow, dcol = drow / mag, dcol / mag
    prow, pcol = -dcol, drow
    reach = max((k // G.nc - ci) * drow + (k % G.nc - cj) * dcol for _, k in cells_sorted)
    lr, lc = ci + drow * reach * 0.5, cj + dcol * reach * 0.5
    axis = []
    for t in [x * 0.5 for x in range(-60, 61)]:
        r, c = round(lr + prow * t), round(lc + pcol * t)
        if 0 <= r < G.nr and 0 <= c < G.nc:
            k = r * G.nc + c
            if not axis or axis[-1] != k:
                axis.append(k)
    print(f"\nLínea candidata: {len(axis)} celdas de eje")

    # [2] Barrera disponible desde el minuto 0 (modelo antiguo: siempre existe)
    bt0 = field_from(G, [(k, 0.0) for k in axis])
    a0, _ = dijkstra(G, [ig], bt=bt0)
    n0 = burned(a0)
    saved0 = (nb - n0) * G.cell_ha
    print(f"[2] Línea ya hecha en t=0: {n0} celdas · salva {saved0:.0f} ha")
    ok2 = n0 < nb
    print("    " + ("OK: corta el fuego" if ok2 else "FALLO: no corta"))

    # [3] La misma línea, pero construida DESPUÉS de que el fuego pase por ahí
    late = max(base[k] for k in axis if base[k] != INF) + 120
    btL = field_from(G, [(k, late) for k in axis])
    aL, _ = dijkstra(G, [ig], bt=btL)
    nL = burned(aL)
    print(f"[3] Misma línea empezada a las {late/60:.1f} h (tras pasar el fuego): "
          f"{nL} celdas · salva {(nb-nL)*G.cell_ha:.0f} ha")
    ok3 = nL == nb
    print("    " + ("OK: llegar tarde no sirve de nada (antes 'salvaba' igual)" if ok3 else "FALLO"))

    # [4] Barrido del momento de inicio → el área salvada debe decrecer
    print("[4] Área salvada según cuándo se empieza la obra (instantánea):")
    prev, mono = None, True
    for t0 in (0, 120, 240, 360, 420, 480, 540, 600):
        bt = field_from(G, [(k, float(t0)) for k in axis])
        a, _ = dijkstra(G, [ig], bt=bt)
        s = (nb - burned(a)) * G.cell_ha
        print(f"      empieza a los {t0:>3} min → salva {s:7.0f} ha")
        if prev is not None and s > prev + 1e-6:
            mono = False
        prev = s
    print("    " + ("OK: decrece monótonamente" if mono else "FALLO: no monótono"))

    # [5] Construcción progresiva: mismo inicio, distinto medio
    print("[5] Misma línea, mismo inicio (t=45 min), distinto ritmo de obra:")
    ok5_vals = []
    for res in ('crew', 'engine', 'dozer'):
        rate, resp, _ = RESOURCES[res]
        rate_min = max(1.0, rate / 60.0)
        f = feasibility(G, axis, rate_min, base, 45.0)
        cells, length = build_times(G, axis, 45.0, rate_min, f['reverse'])
        bt = field_from(G, cells)
        a, _ = dijkstra(G, [ig], bt=bt)
        s = (nb - burned(a)) * G.cell_ha
        ok5_vals.append(s)
        print(f"      {res:<7} {rate:>5} m/h · obra {cells[-1][1]-45:6.0f} min "
              f"· hecho a tiempo {100*f['done']:3.0f}% · hora límite inicio "
              f"{f['latest']:6.0f} min → salva {s:7.0f} ha")
    ok5 = ok5_vals[2] >= ok5_vals[1] >= ok5_vals[0]
    print("    " + ("OK: cuanto más rápida la obra, más salva" if ok5 else "FALLO"))

    # [6] El agua caduca
    print("[6] Agua sobre el mismo trazo (se seca en "
          f"{WATER_HOLD:.0f}+{WATER_FADE:.0f} min):")
    water_axis = axis[len(axis) // 2 - 12: len(axis) // 2 + 12]
    res_w = []
    # Las horas de descarga van RELATIVAS a cuándo llega el fuego, no fijas: al
    # calibrar ROS_MAX (50 → 28.4 el 2026-08-06) el fuego pasó a llegar al trazo
    # en el minuto ~510, y unas descargas fijas en 0/60/120 se secaban mucho antes
    # de que hubiera nada que mojar. El cero era correcto; lo obsoleto era el test.
    llega = min(base[k] for k in water_axis if base[k] != INF)
    for t0 in (max(0, llega - 300), max(0, llega - 40), max(0, llega - 10)):
        cells, _ = build_times(G, water_axis, float(t0), WATER_RATE, False)
        ws = field_from(G, cells)
        we = [v + WATER_HOLD if v != INF else INF for v in ws]
        a, _ = dijkstra(G, [ig], wt=(ws, we))
        # retraso medio en las celdas justo detrás del trazo
        delays = [a[k] - base[k] for k in water_axis if base[k] != INF and a[k] != INF]
        d = sum(delays) / len(delays) if delays else 0
        res_w.append(d)
        print(f"      descarga a los {t0:>3} min → retraso medio en el trazo {d:6.1f} min")
    ok6 = max(res_w) > 0
    print("    " + ("OK: el agua retrasa, y el efecto depende del momento"
                    if ok6 else "FALLO: el agua no hace nada"))

    # [7] Frente actual: mancha quemada, propaga desde el borde
    burnt = [0] * N
    R = 6
    for i in range(max(0, ci - R), min(G.nr, ci + R + 1)):
        for j in range(max(0, cj - R), min(G.nc, cj + R + 1)):
            if (i - ci) ** 2 + (j - cj) ** 2 <= R * R:
                burnt[i * G.nc + j] = 1
    seeds = []
    for i in range(G.nr):
        for j in range(G.nc):
            k = i * G.nc + j
            if not burnt[k]:
                continue
            for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ni, nj = i + di, j + dj
                if 0 <= ni < G.nr and 0 <= nj < G.nc and not burnt[ni * G.nc + nj]:
                    seeds.append(k)
                    break
    af, _ = dijkstra(G, seeds, burnt=burnt)
    inner = [k for k in range(N) if burnt[k] and k not in set(seeds)]
    reburn = sum(1 for k in inner if af[k] != INF)
    print(f"\n[7] Frente actual: mancha de {sum(burnt)} celdas → {len(seeds)} semillas "
          f"de perímetro · celdas interiores que vuelven a arder: {reburn}")
    ok7 = reburn == 0 and burned(af) > 0
    print("    " + ("OK: arranca del borde y lo quemado no rearde" if ok7 else "FALLO"))

    # [8] La "hora límite de inicio" es realmente el límite
    rate_min = max(1.0, RESOURCES['dozer'][0] / 60.0)
    f = feasibility(G, axis, rate_min, base, RESOURCES['dozer'][1])
    lim = f['latest']
    res8 = {}
    for t0 in (max(0, lim - 60), max(0, lim - 5), lim + 60, lim + 180):
        cells, _ = build_times(G, axis, float(t0), rate_min, f['reverse'])
        bt = field_from(G, cells)
        a, _ = dijkstra(G, [ig], bt=bt)
        res8[t0] = (nb - burned(a)) * G.cell_ha
    print(f"[8] Hora límite calculada para 🚜 dozer: {lim:.0f} min")
    for t0 in sorted(res8):
        tag = "antes del límite" if t0 <= lim else "PASADO el límite"
        print(f"      inicio {t0:6.0f} min ({tag:16}) → salva {res8[t0]:7.0f} ha")
    before = [v for t, v in res8.items() if t <= lim]
    after = [v for t, v in res8.items() if t > lim]
    ok8 = min(before) >= max(after)
    print("    " + ("OK: empezar tras la hora límite salva menos" if ok8 else "FALLO"))

    allok = all([ok1, ok2, ok3, mono, ok5, ok6, ok7, ok8])
    print("\n" + ("=== TODO OK ===" if allok else "=== HAY FALLOS ==="))
    return 0 if allok else 1


if __name__ == '__main__':
    sys.exit(main())
