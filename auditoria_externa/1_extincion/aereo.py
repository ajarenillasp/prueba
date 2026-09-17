#!/usr/bin/env python3
"""
aereo.py · LOS MEDIOS AÉREOS, QUE FALTABAN ENTEROS (2026-08-18)

POR QUÉ EXISTE ESTE MÓDULO
El proyecto lleva desde el 7 de agosto dando vueltas al mismo confundido: el
simulador simula fuego libre y se compara con satélite de incendios que tenían
bomberos encima. `motor.py` metió la extinción de TIERRA (ataque directo y línea
indirecta). Pero al mirar el parte del MITECO aparece lo que nadie había mirado:

    NIEBLA (Huelva)   10 medios · 7 AÉREOS · 324 m/h de línea de tierra
    PEÑAS DE RIGLOS   24 medios · 17 AÉREOS · 360 m/h de línea de tierra

**La mayor parte del esfuerzo estatal es aéreo, y el aéreo no estaba modelado en
ninguna parte.** `motor.py` sólo sabe abrir línea. Un avión no abre línea.

QUÉ HACE UN MEDIO AÉREO, Y POR QUÉ ES OTRO MECANISMO
No apaga: moja. Baja la velocidad de avance de la franja que riega durante un
rato, y luego eso se seca. El motor YA tenía la primitiva para esto —`water_mult`
y el argumento `wt` de `dijkstra`— escrita para el bloque C y **jamás usada por
nadie**. Aquí se le da uso: este módulo decide QUIÉN riega, CUÁNDO y DÓNDE, y
deja que el motor haga el resto sin tocarlo.

LA DOCTRINA QUE SE CODIFICA, en una frase
    la tierra ataca por donde el fuego va DESPACIO; el aire ataca por donde va
    DEPRISA.
`motor.directo()` ordena el perímetro de menor a mayor velocidad de borde y sólo
trabaja donde `edge <= DIRECT` (8 m/min, lo que aguanta una autobomba). El aire
hace lo contrario: va a la cabeza, que es justo lo que la tierra no puede tocar.
Y la cabeza es donde `c47`/`c50` midieron que al modelo le sobra área. Las dos
piezas encajan, lo cual es un motivo para desconfiar y medirlo, no para creérselo.

Y NO VUELAN DE NOCHE. Ésa es la propiedad que convierte esto en falsable: la
fatiga del combustible no mira el reloj, los aviones sí.

════════════════════════════════════════════════════════════════════════════
LO QUE ESTE MÓDULO NO PUEDE HACER, DICHO ANTES DE USARLO
  · El parte es DIARIO: sabemos cuántos medios hubo ese día, no a qué hora
    llegó cada uno. `T_LLEGADA` es un supuesto.
  · El parte es sólo de medios ESTATALES. Los autonómicos —el grueso de la
    fuerza de tierra— no están. Todo esto es un SUELO del esfuerzo real.
  · Los tiempos de ciclo (`ciclo_min`) son supuestos de doctrina, no medidas.
    Están en minutos por rotación para que cualquiera pueda discutirlos.
  · No hay coordinación: cada aeronave suelta su carga independientemente.
  · La celda de la rejilla mide ~6.400 m² y una descarga de un anfibio grande
    cubre ~5.500 m². **Una descarga ≈ una celda.** A esta resolución no se puede
    representar la geometría de una pasada; sólo el efecto agregado. Es una
    limitación real y hay que citarla en cualquier conclusión.
════════════════════════════════════════════════════════════════════════════
"""
import os
import math

import validate_block_a as V


# ── LA FLOTA ────────────────────────────────────────────────────────────────
# (litros por descarga, minutos por rotación).
# Los LITROS salen del propio parte del MITECO (la descripción de cada medio los
# lleva escritos), así que no son un supuesto: son el dato.
# Los MINUTOS son doctrina y sí son supuesto: dependen de la distancia al agua,
# que no está en el parte. Se listan aparte para poder barrerlos.
FLOTA = {
    'FOCA':   (5500.0, 20.0),   # avión anfibio tipo 1
    'ALFA':   (3100.0, 18.0),   # avión anfibio tipo 2
    'TANGO':  (3100.0, 40.0),   # avión de carga EN TIERRA: recarga en aeródromo
    'KILO':   (4500.0, 12.0),   # helicóptero bombardero tipo 1
    'MIKE':   (2500.0, 10.0),   # helicóptero bombardero tipo 2
    'LIMA':   (1000.0,  8.0),   # helicóptero bombardero tipo 3
    'BRIF-A': (2400.0, 15.0),   # 2 helicópteros de 1.200 l
    'BRIF-B': (1200.0, 15.0),   # 1 helicóptero de 1.200 l
}
# Sin capacidad de descarga: coordinación, mando, brigada en disponibilidad.
SIN_AGUA = ('ACO', 'UMAP', 'BRIF DISPONIBILIDAD')

# Litros útiles por m² de huella. La escala de "coverage level" del ataque aéreo
# va de 1 a 8 gal/100 ft²; 1 gal/100 ft² ≈ 0,41 l/m². El nivel 2-3 es el habitual
# en matorral y pasto, o sea ~0,8-1,2 l/m². Se toma 1,0 y se puede barrer.
COBERTURA_L_M2 = 1.5   # UNIFICADO con WATER_COVERAGE de la app (era 1.0 aquí)

# ⭐ 2026-08-24 · LA COBERTURA DEPENDE DEL COMBUSTIBLE, y un solo número es falso en
# los dos extremos.
# La fuente verificada (§17 · Plucinski et al., Bushfire CRC 2007) no dice «0,5»: dice
# **<0,5 L/m² en pasto** y **>1,5 L/m² en eucalipto**, con media eficaz 0,5 (0,3-0,8).
# Tener 1,5 fijo es poner el valor del arbolado denso en TODAS partes, y como la huella
# sale de `área = volumen / cobertura`, eso **encoge el avión** justo donde más suelo
# debería mojar.
# Medido el 24-ago sobre 20 incendios (§23 e61): con 1,5 se salva 1,50% y con 0,5 el
# 3,82% — ×2,55. Pero cambiar 1,5 por 0,5 sería el mismo error al revés: pasto en todas
# partes. Lo real es interpolar con el combustible de la celda, que ya lo tenemos.
# ⚠ El índice de combustible NO es densidad de biomasa: es carga × curado (§3). Se usa
# como PROXY de «cuánta vegetación hay que mojar», y eso es un supuesto declarado.
# ⭐ 2026-08-25 · VALOR DECIDIDO, con la fuente leída de primera mano.
# Plucinski et al. 2007 (Bushfire CRC), «The Effectiveness and Efficiency of Aerial
# Firefighting in Australia», p.18, citando a Loane & Gould 1986 y George et al. 1990:
#   · «Effective retardant coverage levels range from <0,5 L/m² for grass fires to
#      >1,5 L/m² for eucalypt forest (providing a holding time up to 2h)».
#   · George et al. 1990, estudio OPERATIVO extenso en EEUU: «an average coverage level
#      of 0,5 L/m² (range 0,3-0,8) was effective on fires with flame lengths up to 2m
#      (intensity approximately 2000 kW/m) in a wide range of fuel types».
#   · Teórico para combustibles pesados hasta 4,0 L/m², «but in practice the effective
#      coverage levels are considerably lower». Bajo dosel rara vez pasa de 2,5.
# POR QUÉ 0,3 EN EL EXTREMO DE PASTO Y NO 0,5: nuestro modelo sólo deja atacar con agua
# aérea por debajo de `I_AGUA_AEREA` = 1.731 kW/m, que es EXACTAMENTE el régimen que
# describe George et al. (llamas ≤2 m, ~2.000 kW/m) y donde la cobertura eficaz medida
# es 0,5 de media con mínimo 0,3. El extremo de pasto de nuestra interpolación tiene que
# ser ese mínimo, no la media.
# ⚠ LO QUE LA FUENTE DICE Y ESTE MODELO NO HACE: la cobertura necesaria SUBE con la
# intensidad del fuego (Loane & Gould, figura 2). Aquí sólo depende del combustible.
# Es una simplificación DECLARADA, no un descuido.
COBERTURA_PASTO = 0.3    # pasto · mínimo eficaz medido (George et al. 1990)
COBERTURA_ARBOL = 1.5    # eucalipto/arbolado denso (Loane & Gould 1986)
USE_COBERTURA_COMB = os.environ.get('COB_COMB', '1') != '0'


def cobertura_de(f):
    """L/m² que hace falta en una celda con índice de combustible `f`."""
    if not USE_COBERTURA_COMB:
        return COBERTURA_L_M2
    x = 0.0 if f is None else (0.0 if f < 0 else (1.0 if f > 1 else f))
    return COBERTURA_PASTO + (COBERTURA_ARBOL - COBERTURA_PASTO) * x

# EL AGUA TIENE QUE PODER APAGAR (portado de `fire_sim.js:150,979`, 2026-08-18).
# La app ya lo tenía desde el 12-ago y el motor de validación NO: aquí el agua
# sólo bajaba la velocidad un rato y luego se secaba, así que NINGUNA celda
# mojada quedaba nunca apagada. Consecuencia medida hoy (`a14`): una brigada
# cavando salvaba el 99,9% de un conato y un Canadair el 2,6%, que es al revés
# de lo que pasa en la realidad — el usuario lo dijo antes de que yo lo mirara.
# La regla es la de la app, y depende de la INTENSIDAD del tramo:
#   · borde lento (<= WATER_KILL_ROS) -> el agua APAGA, y queda apagado.
#   · cabeza en carrera               -> el agua NO apaga; sólo baja la
#                                        intensidad para que entre la tierra.
WATER_KILL_ROS = 9.0    # m/min de avance de borde

T_LLEGADA = 90.0      # min desde la ignición hasta la primera descarga (supuesto)
PASO = 15.0           # min por ciclo de decisión del aire
MARGEN_SOL = 30.0     # min de margen sobre el orto y el ocaso (no se vuela al filo)

# Mojado: se reutilizan las constantes del motor para no abrir una segunda
# definición (en este proyecto ya han mordido cuatro veces las copias viejas).
#   V.WATER_FACTOR = 0.04  · velocidad mientras está mojado
#   V.WATER_HOLD   = 25 min · mojado pleno
#   V.WATER_FADE   = 35 min · secado lineal


def sol(lat_deg, doy):
    """Orto y ocaso en horas locales solares. Devuelve (amanecer, ocaso).

    El `acos` va CLAMPEADO a propósito: sin eso, en latitud alta y cerca del
    solsticio el argumento se sale de [-1, 1] y revienta. Ya pasó una vez en
    este proyecto (crash del meteo por sol de medianoche, jun-2026).
    """
    lat = math.radians(lat_deg)
    dec = math.radians(23.44) * math.sin(2 * math.pi * (doy - 81) / 365.0)
    x = -math.tan(lat) * math.tan(dec)
    if x <= -1.0:
        return 0.0, 24.0          # día polar: se vuela todo el día
    if x >= 1.0:
        return 12.0, 12.0         # noche polar: no se vuela
    h = math.degrees(math.acos(x)) / 15.0
    return 12.0 - h, 12.0 + h


def es_de_dia(t_min, start_h, amanecer, ocaso):
    """¿Se puede volar en el minuto `t_min` desde la ignición?"""
    h = (start_h + t_min / 60.0) % 24.0
    return (amanecer + MARGEN_SOL / 60.0) <= h <= (ocaso - MARGEN_SOL / 60.0)


def flota_de_parte(medios):
    """Convierte la lista `medios` de un parte en [(tipo, n)] sólo con los que
    descargan agua. Devuelve también los litros/hora nominales, que es el número
    que un jefe de extinción puede juzgar de un vistazo."""
    flota, l_h = [], 0.0
    for m in medios:
        tipo, n = m.get('tipo', ''), float(m.get('n') or 0)
        if tipo in SIN_AGUA or n <= 0:
            continue
        if tipo not in FLOTA:
            continue
        lit, ciclo = FLOTA[tipo]
        flota.append((tipo, n))
        l_h += n * lit * (60.0 / ciclo)
    return flota, l_h


def descargas(flota, t_ini, t_fin, start_h, amanecer, ocaso):
    """Calendario de descargas: [(minuto, litros)] ordenado.

    Cada aeronave rota con su propio periodo. Se desfasan entre sí para que no
    suelten todas a la vez, que es lo que haría un despliegue coordinado.
    """
    ev = []
    for tipo, n in flota:
        lit, ciclo = FLOTA[tipo]
        for u in range(int(round(n))):
            fase = ciclo * (u / max(1.0, n))       # desfase entre unidades del mismo tipo
            t = t_ini + fase
            while t <= t_fin:
                if es_de_dia(t, start_h, amanecer, ocaso):
                    ev.append((t, lit))
                t += ciclo
    ev.sort()
    return ev


def _delante_del_frente(arr, edge, G, t, ws_f, we_f, ahora):
    """Celdas SIN QUEMAR que el fuego tiene delante en el instante `t`,
    ordenadas por la velocidad con la que se les viene encima.

    ⚠ ESTO ES LO QUE SE RIEGA, y la primera versión lo tenía mal: regaba el
    perímetro YA QUEMADO. Regar donde el fuego ya pasó no hace absolutamente
    nada —`water_mult` multiplica la velocidad de ENTRADA a una celda— y por eso
    el humo daba 339 celdas regadas y el área quemada idéntica a la del fuego
    libre. Además es lo que hacen los medios de verdad: sueltan por DELANTE de
    la cabeza para que el fuego tenga que cruzar la franja mojada, no sobre lo
    que ya está negro.

    Criterio del aire, inverso exacto al de la tierra: `motor.directo()` ordena
    de MENOR a mayor velocidad de borde y sólo trabaja por debajo de `DIRECT`;
    aquí se ordena de MAYOR a menor y sin tope. La tierra va a donde puede, el
    aire va a donde hace falta.
    """
    nr, nc = G.nr, G.nc
    N = nr * nc
    cand = {}
    for k in range(N):
        a = arr[k]
        if a == V.INF or a > t:          # sólo miramos lo ya quemado a tiempo t
            continue
        i, j = divmod(k, nc)
        v = edge[k] if edge[k] != V.INF else 0.0
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if not di and not dj:
                    continue
                ni, nj = i + di, j + dj
                if not (0 <= ni < nr and 0 <= nj < nc):
                    continue
                nb = ni * nc + nj
                b = arr[nb]
                if b != V.INF and b <= t:        # ya quemada: no se riega
                    continue
                if G.fuel[nb] <= 0:              # no arde: no se malgasta carga
                    continue
                if ws_f[nb] != V.INF and we_f[nb] > ahora:   # ya mojada y húmeda
                    continue
                if V.USE_INTENSIDAD:
                    # Tabla 1 de Andrews & Rothermel: los medios aéreos figuran
                    # como efectivos en la banda 346-1.731 kW/m. Por encima de
                    # 1.731 «los esfuerzos de control en la cabeza serán
                    # probablemente inefectivos», y por encima de 3.461 son
                    # «inefectivos». Sin este filtro el módulo tira toda la carga
                    # en la parte más caliente del frente —que es lo que ordena
                    # `_franja`— o sea justo donde la doctrina dice que no sirve.
                    if V.intensidad(v, G.fuel[nb]) > V.I_MAQUINA:
                        continue
                if v > cand.get(nb, -1.0):
                    cand[nb] = v
    return cand


# ── 7-sep · LA DOCTRINA AÉREA DEJA DE SER ÚNICA (§109, `c127`) ───────────────
# Hasta hoy `_franja` tenía UNA sola regla: empezar por la celda más caliente y
# crecer hacia lo más caliente. Nadie ha probado otra nunca, y `c126` acaba de medir
# que cambiar una regla fija por una búsqueda vale 16-31 puntos en el lado de la
# tierra (§108bis.2). Esto expone la regla como parámetro, SIN cambiar el defecto:
# con `PRIORIDAD='cabeza'` el módulo hace exactamente lo de siempre, así que `c126`
# y todo lo anterior siguen reproduciendo bit a bit.
#   'cabeza'  · lo de siempre: a lo que avanza más deprisa (la cabeza del fuego).
#   'flancos' · al revés: a lo que avanza despacio, para ESTRECHAR el incendio en
#               vez de frenarlo de frente. La tierra ya trabaja ahí (`edge<=DIRECT`),
#               así que esto es "los dos al mismo sitio" y puede salir mal — por eso
#               se mide en vez de razonarlo.
#   'apoyo'   · pegado a la línea que está abriendo la tierra (`APOYO`), para
#               comprarle tiempo a las cuadrillas. Si no se pasa `APOYO`, cae a
#               'cabeza' y lo dice el propio brazo.  (alias histórico: 'linea')
#
# ⛔⛔ 8-sep · EL BRAZO `apoyo` DE `c127` NUNCA SE MIDIÓ, Y NADIE SE ENTERÓ.
#    `c127_donde_sueltan.py:224` ponía `A.PRIORIDAD = 'apoyo'` —el nombre del brazo en
#    §109 y en el crudo— y aquí sólo se reconocía `'linea'`. El `if` no casaba, caía al
#    `return` de abajo y el brazo corrió como `cabeza`: **idéntico bit a bit en 205/205
#    incendios**, con `con_eje` = 9/9 diciendo que sí había eje. La noche del 7-sep midió
#    dos doctrinas creyendo que medía tres, y el veredicto ⛔ SALIDA 3 se escribió sobre
#    una comparación que no existía.
#    ⭐ Los dos arreglos, porque el segundo es el que importa:
#      1 · se aceptan los dos nombres, `apoyo` (canónico, el de §109) y `linea`.
#      2 · **una doctrina desconocida ya no cae en silencio a `cabeza`: revienta.** Es lo
#          que `mixto.py:243` lleva haciendo desde siempre con su propia `prioridad` —el
#          módulo hermano tenía la validación y éste no, y ahí se coló el bug.
DOCTRINAS_AEREAS = ('cabeza', 'flancos', 'apoyo', 'linea')
PRIORIDAD = 'cabeza'
APOYO = None          # set de celdas del eje de la línea de tierra, para 'apoyo'


def _clave(cand, G):
    """Devuelve la función de orden de la doctrina activa. Menor = se riega antes."""
    if PRIORIDAD not in DOCTRINAS_AEREAS:
        raise ValueError(f'doctrina aérea desconocida: {PRIORIDAD!r} · '
                         f'las que hay son {DOCTRINAS_AEREAS}')
    if PRIORIDAD == 'flancos':
        return lambda k: cand[k]                    # lo más LENTO primero
    if PRIORIDAD in ('apoyo', 'linea') and APOYO:
        nc = G.nc
        def _d(k):
            i, j = divmod(k, nc)
            # distancia de Chebyshev al eje de la línea, en celdas; a igualdad, lo
            # más caliente primero (para no quedarse regando un tramo muerto)
            m = min((max(abs(i - a // nc), abs(j - a % nc)) for a in APOYO), default=9999)
            return (m, -cand[k])
        return _d
    return lambda k: -cand[k]                       # 'cabeza' · lo de siempre


def _franja(cand, G, n, ancla=None):
    """Elige `n` celdas CONTIGUAS entre las candidatas, arrancando por la más
    caliente —o **por donde ya hay línea mojada**, si se pasa `ancla`— y creciendo
    por adyacencia.

    ⭐ TERCER ARREGLO DE DOCTRINA (24-ago): ANCLAR Y EXTENDER.
    El segundo arreglo (18-ago, abajo) consiguió que cada descarga no salpicara. Pero
    **cada paso de 15 min volvía a empezar de cero**, anclándose en la celda más
    caliente de ese instante — que para entonces se ha movido. Medido en NIEBLA a 6 h:
    nueve tendidos de 5-8 celdas que acaban formando **SIETE bandas sueltas** de 10, 9,
    5, 4, 3, 3 y 1 celdas. La mayor mide **700 m**. El fuego rodea cada trozo, igual
    que rodeaba una celda suelta antes del arreglo del 18: es el MISMO fallo un nivel
    más arriba.
    Un medio real no hace eso: **ancla en la descarga anterior y extiende**, y la línea
    crece hora tras hora. Con `ancla` (las celdas ya mojadas) la franja nueva arranca
    pegada a la vieja siempre que alguna candidata la toque; si ninguna la toca —el
    fuego se ha ido a otra parte— se vuelve al criterio de antes y se dice por qué.

    ⚠ SEGUNDO ARREGLO DE DOCTRINA. La versión anterior cogía las `n` celdas más
    calientes sueltas, y el efecto sobre el área quemada era del 0,1-0,7%: nada.
    El motivo es físico y no del código —**el fuego rodea una celda mojada
    aislada**—, y es también lo que separa un modelo de juguete de la doctrina
    real: los medios aéreos no salpican, TIENDEN UNA FRANJA. Cada descarga se
    ancla en la anterior y se construye una banda que el frente tiene que cruzar.
    """
    if not cand:
        return []
    nc = G.nc
    _k = _clave(cand, G)
    orden = sorted(cand, key=_k)
    # ANCLA: si alguna candidata toca la línea ya mojada, se empieza por ahí. Entre
    # las que tocan se elige la más caliente, para que la extensión siga yendo hacia
    # donde el fuego aprieta.
    inicio = None
    if ancla:
        pegadas = []
        for k in orden:
            i, j = divmod(k, nc)
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    if not di and not dj:
                        continue
                    if (i + di) * nc + (j + dj) in ancla:
                        pegadas.append(k)
                        break
                else:
                    continue
                break
        if pegadas:
            inicio = pegadas[0]
    if inicio is None:
        inicio = orden[0]
    sel = [inicio]
    vistos = {inicio}
    frente = [inicio]
    while len(sel) < n and frente:
        nuevo = []
        for k in frente:
            i, j = divmod(k, nc)
            vec = []
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    if not di and not dj:
                        continue
                    nb = (i + di) * nc + (j + dj)
                    if nb in cand and nb not in vistos:
                        vec.append(nb)
            # se crece por el vecino más caliente primero: la franja se alarga
            # a lo ancho de la cabeza, no en cualquier dirección
            for nb in sorted(vec, key=_k):
                if len(sel) >= n:
                    break
                sel.append(nb); vistos.add(nb); nuevo.append(nb)
        if len(sel) >= n:
            break
        if not nuevo:
            # franja agotada: se salta al siguiente foco caliente sin tocar
            for k in orden:
                if k not in vistos:
                    sel.append(k); vistos.add(k); nuevo = [k]
                    break
            if not nuevo:
                break
        frente = nuevo
    return sel[:n]


def moja(c, arr, edge, ev, ws, we, btw=None):
    """Aplica el calendario de descargas sobre la simulación `arr` y actualiza
    los campos de mojado (ws, we) IN SITU.

    Devuelve el número de celdas regadas. Cada descarga cubre
    `litros / COBERTURA_L_M2` metros cuadrados, que a esta rejilla es del orden
    de una celda: por eso se acumulan las descargas del paso y se reparten entre
    las celdas más rápidas del frente.
    """
    G = c['G']
    area_celda = G.dxm * G.dym
    apagadas = [0]
    regadas = 0
    # La línea mojada que ya existe: es el ancla de la franja siguiente (24-ago).
    _mojadas = set()
    resto = 0.0
    i = 0
    t = ev[0][0] if ev else 0.0
    while i < len(ev):
        # todas las descargas de esta ventana de decisión
        litros = 0.0
        t0 = t
        while i < len(ev) and ev[i][0] < t0 + PASO:
            litros += ev[i][1]
            i += 1
        t = t0 + PASO
        if litros <= 0:
            continue
        # El resto se ARRASTRA a la ventana siguiente. Sin esto, cuando la celda
        # es grande frente a la descarga (rejilla gruesa, o flota pequeña) cada
        # ventana tira su fracción por el desagüe y el aire deja de existir sin
        # avisar. Con celdas de 250 m una descarga es 0,07 celdas: el `int()`
        # daba 0 SIEMPRE y el módulo habría dicho "el aire no hace nada" cuando
        # lo que pasaba es que no se estaba aplicando.
        # la cobertura sale del combustible de DONDE se va a soltar, no de una
        # constante global: el mismo avión moja más suelo en pasto que en arbolado
        _cand = _delante_del_frente(arr, edge, G, t0, ws, we, t0)
        _f = (sorted(G.fuel[k] for k in _cand)[len(_cand) // 2] if _cand else 0.5)
        resto += litros / cobertura_de(_f) / area_celda
        n_celdas = int(resto)
        if n_celdas < 1:
            continue
        resto -= n_celdas
        cand = _delante_del_frente(arr, edge, G, t0, ws, we, t0)
        if not cand:
            continue
        for k in _franja(cand, G, n_celdas, ancla=_mojadas):
            # una celda regada dos veces alarga la ventana, no la reinicia
            _mojadas.add(k)
            ws[k] = min(ws[k], t0)
            we[k] = max(we[k] if we[k] != V.INF else 0.0, t0 + V.WATER_HOLD)
            # y si el tramo iba despacio, el agua lo APAGA: barrera permanente,
            # no un retraso de una hora (ver la nota de WATER_KILL_ROS arriba)
            # El agua APAGA de forma permanente donde la línea aguantaría: por
            # debajo de 346 kW/m la Tabla 1 dice que la herramienta manual sostiene
            # el fuego en cabeza o flancos, y una descarga en esa banda deja el
            # tramo hecho. Por encima sólo moja y baja la intensidad, que es lo que
            # permite entrar a la tierra (ver `mixto.py`).
            if V.USE_INTENSIDAD:
                _apaga = V.intensidad(edge[k] if edge[k] != V.INF else 0.0,
                                      G.fuel[k]) <= V.I_AGUA_AEREA
            else:
                _apaga = edge[k] <= WATER_KILL_ROS
            if btw is not None and _apaga and t0 < btw[k]:
                btw[k] = t0
                apagadas[0] += 1
            regadas += 1
    return regadas, apagadas[0]


def sim(c, bt=None, wt=None, dtsrc=None):
    return V.dijkstra(c['G'], c['seeds'], bt=bt, wt=wt, dtsrc=dtsrc,
                      wspd=c['met']['wspd'], wdir=c['met']['wdir'],
                      start_h=c['start_h'], wind_series=c['ws'],
                      rh_series=c['rh'])[0]


def con_aire(c, flota, horizonte_min, lat, doy, iteraciones=3, bt=None):
    """Simula el incendio CON los medios aéreos de `flota` encima.

    Iterativo por necesidad: dónde riegan depende de dónde está el fuego, y
    dónde está el fuego depende de dónde han regado. Converge rápido porque el
    mojado sólo puede frenar, nunca acelerar.

    Devuelve (arr, info).
    """
    import motor as M

    N = c['G'].nr * c['G'].nc
    amanecer, ocaso = sol(lat, doy)
    ev = descargas(flota, T_LLEGADA, horizonte_min, c['start_h'], amanecer, ocaso)
    info = dict(n_descargas=len(ev), amanecer=round(amanecer, 2),
                ocaso=round(ocaso, 2), regadas=0)
    arr = sim(c, bt=bt)
    if not ev:
        return arr, info

    for it in range(iteraciones):
        edge = M.edge_ros(arr, c['G'])
        btw = list(bt) if bt is not None else [V.INF] * N
        # F5 (2026-08-19): el riego se RECALCULA en cada iteración, no se SUMA.
        # `ws`/`we` estaban creados FUERA del bucle y `moja` recorre el calendario
        # ENTERO cada vez haciendo min/max, así que la misma flota soltaba su carga
        # tantas veces como iteraciones. Medido (`a26`): 142 celdas mojadas con una
        # iteración y 402 con tres — 2,83x de agua fantasma. Y no se veía porque
        # `info['regadas']` se sobreescribe y sólo enseña la última pasada.
        # La iteración existe porque dónde riegan depende de dónde está el fuego y
        # al revés; para eso hay que REHACER el reparto sobre el fuego actual, que
        # es lo que hace este reinicio. Invalida `a15`, `a24`, `a25` y la rejilla
        # aire x tierra de la noche del 18: todas sobrevaloran el aire.
        # ⚠️ CORRECCIÓN 2026-09-XX: se conserva el mojado acumulado entre iteraciones
        # para que el agua no desaparezca. Se recalcula DÓNDE se aplica, pero lo ya
        # mojado SIGUE MOJADO. Sin esto, la iteración converge a fuego libre porque
        # el agua se evapora en cada paso.
        if it == 0:
            ws = [V.INF] * N
            we = [V.INF] * N
        info['regadas'], info['apagadas'] = moja(c, arr, edge, ev, ws, we, btw)
        arr = sim(c, bt=btw, wt=(ws, we))
    return arr, info
