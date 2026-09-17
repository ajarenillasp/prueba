#!/usr/bin/env python3
"""
mixto.py · AIRE Y TIERRA EN EL MISMO BUCLE (2026-08-19)

EL FALLO QUE ARREGLA, y es de ORDEN, no de física
Hasta hoy los dos módulos corrían enteros y por separado. En `a12_llegada.py:90`:

    _, bt = M.directo(c, 324.0, libre, edge0, [V.INF] * N)   # la tierra, ENTERA
    arr, _ = A.con_aire(c, flota, HOR, lat, doy, bt=bt)      # el aire, DESPUÉS

Dos consecuencias, las dos medidas:
  1. **El avión no podía habilitar nada**, porque cuando riega la tierra ya ha
     terminado de trabajar. El orden real es el contrario: el aire baja la
     intensidad y ENTONCES entra la gente.
  2. `edge0` se calcula UNA vez con el fuego LIBRE y no se refresca nunca. O sea
     que la tierra decide dónde puede trabajar mirando una foto de antes de que
     nadie hiciera nada.

Resultado: una brigada cavando salvaba el 99,9% de un conato y la flota aérea
entera el 15,3% (`a15`). El usuario lo señaló como imposible antes de que nadie
lo mirara, y tenía razón.

LO QUE **NO** HAY QUE INVENTAR PARA ARREGLARLO
Nada de reglas nuevas. `M.edge_ros()` mide la velocidad del borde a partir del
GRADIENTE de los tiempos de llegada; si el agua está aplicada, el tramo mojado
tarda más en cruzarse y su borde ya sale lento. La regla que ya existe
—`edge <= DIRECT`, lo que aguanta una autobomba— lo vería sola. Sólo hacía falta
(a) intercalar los dos en un único bucle temporal, con el aire ANTES, y
(b) refrescar `edge` en cada paso.

LA DOCTRINA QUE QUEDA CODIFICADA, en una frase
    el aire no apaga la cabeza: la enfría el tiempo justo para que la tierra
    pueda cortar ahí, y ese corte sí es permanente.
Una descarga sola se seca en `WATER_HOLD + WATER_FADE` (25+35 min) y el fuego
vuelve a pasar. Una descarga que la tierra aprovecha se convierte en línea, y la
línea no se seca. Eso es lo que hace que sumar aire y tierra valga MÁS que las dos
por separado, y es exactamente lo que el modelo no podía representar.

CÓMO SE DECIDE SI UN TRAMO ES ATACABLE, y por qué es la versión CONSERVADORA
`edge_efectivo()` multiplica la velocidad del borde por el mojado del PEOR de sus
vecinos sin quemar (`max` de `water_mult`, no `min`): si al tramo le queda un solo
vecino seco por donde escapar, NO cuenta como atacable aunque el resto esté
empapado. Es la elección conservadora a propósito — la generosa (basta un vecino
mojado) haría atacable casi todo el perímetro en cuanto pasara un avión, y este
proyecto ya tiene documentado cuatro veces lo que pasa cuando un mecanismo nuevo
sale demasiado bien. Y encaja con `_franja()`, que precisamente riega bandas
CONTIGUAS porque el fuego rodea una celda mojada aislada.

LO QUE SIGUE SIENDO SUPUESTO, dicho antes de usarlo
  · Que la tierra puede trabajar un tramo recién mojado DENTRO de la ventana de
    mojado. En la realidad hay que llegar hasta allí; aquí se supone que sí.
  · `T_LLEGADA` del aire y `T0` de la tierra son supuestos (el parte del MITECO
    es diario, no trae horas).
  · Una descarga ≈ una celda a esta resolución. No se representa la geometría de
    una pasada, sólo el efecto agregado.
  · Los aviones NO vuelan de noche, y eso es lo que hace esto falsable: de noche
    el acoplamiento tiene que dar EXACTAMENTE lo mismo que la tierra sola.
"""
import aereo as A
import motor as M
import validate_block_a as V

PASO = 30.0          # min por ciclo de decisión conjunto (el aire decidía cada 15)

# ── LA REGLA DE PRIORIDAD DE LA TIERRA, y por qué es un parámetro y no una
#    decisión escondida (añadido el 2026-08-19 DESPUÉS de ver `a24`) ──────────
# `a24` midió la primera versión de este módulo con prioridad 'agua': el perímetro
# se ordenaba por velocidad de borde YA CORREGIDA por el mojado. Consecuencia
# medida: los tramos de cabeza recién mojados salen con `edge*0,04` ≈ 1 m/min, o
# sea MÁS LENTOS que un flanco seco de 3 m/min, así que la tierra gastaba TODO su
# cupo persiguiendo descargas en la cabeza y ABANDONABA los flancos, donde su
# línea sí servía. Resultado: 1,3-1,9% salvado contra el 5,4-6,0% de correr los
# dos por separado. Acoplar EMPEORABA.
#
# 'ancla' es la doctrina que `motor.directo()` ya declara en su docstring —
# «anclando en lo ya quemado y progresando hacia la cabeza»—: primero el perímetro
# que se puede trabajar EN SECO, y sólo con el cupo que sobre se extiende la línea
# por los tramos que el agua acaba de abaratar. El argumento NO depende del
# resultado: un corte en seco es permanente con certeza, y un tramo mojado hay que
# cortarlo ANTES DE QUE SE SEQUE (25+35 min). Ante la misma inversión, se prefiere
# lo seguro.
#
# Se deja como parámetro y se miden LAS DOS a la vez, a propósito: el cambio de
# regla se hizo después de ver los números y eso en este proyecto es exactamente
# el patrón que ha mordido cuatro veces. Que se vea en la tabla, no en un commit.



def _toca(k, S, nc):
    """¿La celda `k` toca (8-vecindad) alguna del conjunto `S`?"""
    if not S:
        return False
    i, j = divmod(k, nc)
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            if not di and not dj:
                continue
            if (i + di) * nc + (j + dj) in S:
                return True
    return False


def _linea_de_tierra(per, cortadas, G, n_celdas, orden_key):
    """`n_celdas` de perímetro trabajable, CONTIGUAS y ancladas en lo ya cortado.

    ⭐ EL ARREGLO DE DOCTRINA QUE LA TIERRA NUNCA RECIBIÓ (26-ago).
    Es literalmente el mismo que `aereo._franja` lleva desde el 18-ago (tender una
    franja en vez de salpicar, «el fuego rodea una celda mojada aislada») más el del
    24-ago (anclar en lo anterior y extender, «el fuego rodea cada trozo»). El aire lo
    tiene tres veces y la tierra CERO: `motor.directo()` y el bloque de tierra de
    `con_aire_y_tierra()` ordenan el perímetro entero por intensidad y cortan las N
    celdas más baratas ESTÉN DONDE ESTÉN. Eso no es una línea, y `a80`/`a81` lo miden:
    32 celdas repartidas en 19 trozos con el contiguo más largo en 8.

    El argumento NO depende del resultado, que es lo que exige este proyecto: una
    cuadrilla real no se teletransporta al siguiente tramo barato del perímetro, ancla
    —en un camino, en lo ya quemado, en la línea de ayer— y progresa. Si al medirlo
    sale que da igual, el veredicto es que la contigüidad no manda, no que el
    mecanismo estuviera mal planteado.

    Anclaje, en orden: (1) pegado a la línea YA cortada en pasos anteriores; (2)
    pegado a lo seleccionado en este paso; (3) si no hay nada que tocar, la celda más
    barata que quede, y eso cuenta como SALTO —la línea se rompe y se dice.
    El crecimiento va por adyacencia dentro del perímetro trabajable, desempatando por
    el mismo criterio que usa la prioridad 'ancla', así que **lo único que cambia
    respecto de 'ancla' es la contigüidad**.
    """
    if not per or n_celdas <= 0:
        return [], 0
    nc = G.nc
    S = set(per)
    orden = sorted(per, key=orden_key)
    sel, vistos, saltos = [], set(), 0
    while len(sel) < n_celdas:
        inicio = None
        for k in orden:                      # (1) y (2): algo que tocar
            if k in vistos:
                continue
            if _toca(k, cortadas, nc) or _toca(k, vistos, nc):
                inicio = k
                break
        if inicio is None:                   # (3) arranque nuevo = la línea se rompe
            for k in orden:
                if k not in vistos:
                    inicio = k
                    break
            if inicio is None:
                break
            if sel or cortadas:
                saltos += 1
        vistos.add(inicio)
        sel.append(inicio)
        frente = [inicio]
        while frente and len(sel) < n_celdas:
            nuevo = []
            for x in frente:
                i, j = divmod(x, nc)
                vec = [(i + di) * nc + (j + dj)
                       for di in (-1, 0, 1) for dj in (-1, 0, 1)
                       if (di or dj)]
                for nb in sorted((v for v in vec if v in S and v not in vistos),
                                 key=orden_key):
                    if len(sel) >= n_celdas:
                        break
                    vistos.add(nb)
                    sel.append(nb)
                    nuevo.append(nb)
            frente = nuevo
    return sel, saltos


def edge_efectivo(arr, edge, ws, we, G, t):
    """Velocidad de borde CONTANDO EL AGUA, y qué tramos la deben al aire.

    Para cada celda ya quemada con algún vecino sin quemar que arda, se toma el
    mojado del vecino MENOS mojado (`max` de `water_mult`): si queda una vía seca
    de escape, el tramo no se abarata. Devuelve (ef, por_agua).
    """
    nr, nc = G.nr, G.nc
    N = nr * nc
    ef, por_agua = {}, {}
    for k in range(N):
        a = arr[k]
        if a == V.INF or a > t:
            continue
        i, j = divmod(k, nc)
        peor = None
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if not di and not dj:
                    continue
                ni, nj = i + di, j + dj
                if not (0 <= ni < nr and 0 <= nj < nc):
                    continue
                nb = ni * nc + nj
                b = arr[nb]
                if b != V.INF and b <= t:      # ya quemado: no es frontera
                    continue
                if G.fuel[nb] <= 0:            # no arde: no es frontera
                    continue
                m = V.water_mult(ws[nb], we[nb], t)
                peor = m if peor is None else max(peor, m)
        if peor is None:                       # no tiene frente: no es perímetro
            continue
        e = edge[k] if edge[k] != V.INF else 0.0
        ef[k] = e * peor
        por_agua[k] = peor < 1.0
    return ef, por_agua


def con_aire_y_tierra(c, flota, E, horizonte_min, lat, doy,
                      paso=None, t_aire=None, t_tierra=None, prioridad='ancla'):
    """Un solo bucle temporal: en cada paso riega el aire, y ENTONCES trabaja la
    tierra sobre el perímetro que el agua acaba de dejar atacable.

    `E` en m/h de línea de tierra. `flota` como la de `aereo.flota_de_parte`.
    Devuelve (arr, info).
    """
    G = c['G']
    nr, nc = G.nr, G.nc
    N = nr * nc
    paso = PASO if paso is None else paso
    t_aire = A.T_LLEGADA if t_aire is None else t_aire
    t_tierra = M.T0 if t_tierra is None else t_tierra

    amanecer, ocaso = A.sol(lat, doy)
    ev = A.descargas(flota, t_aire, horizonte_min, c['start_h'], amanecer, ocaso) \
        if flota else []

    ws = [V.INF] * N
    we = [V.INF] * N
    mojadas = set()          # la línea de agua ya tendida: ancla de la siguiente (24-ago)
    # 24-ago · DIAGNÓSTICO DE CONTINUIDAD. Un incendio no lo para cortar celdas: lo
    # para una línea que CIERRA. Contar celdas cortadas no distingue 130 celdas
    # seguidas de 130 celdas repartidas por todo el perímetro, y la diferencia entre
    # las dos cosas es que la segunda no para nada. Se apunta el conjunto para poder
    # decirlo en `info`, que es lo que faltaba para diagnosticar.
    cortadas_set = set()
    bt = [V.INF] * N
    held = bytearray(N)
    arr = A.sim(c)

    if prioridad not in ('ancla', 'agua', 'linea'):
        raise ValueError(f'prioridad desconocida: {prioridad}')
    info = dict(n_descargas=len(ev), amanecer=round(amanecer, 2),
                ocaso=round(ocaso, 2), regadas=0, apagadas_aire=0, cortadas=0,
                cortadas_por_agua=0, cortadas_secas=0, pasos=0, paso_min=paso,
                saltos_linea=0, prioridad=prioridad)
    ev_i = 0
    resto_agua = resto_linea = 0.0
    t = min(t_aire, t_tierra)
    while t < horizonte_min:
        info['pasos'] += 1
        edge = M.edge_ros(arr, G)
        cambio = False

        # ── 1 · EL AIRE, PRIMERO ────────────────────────────────────────────
        litros = 0.0
        while ev_i < len(ev) and ev[ev_i][0] < t + paso:
            litros += ev[ev_i][1]
            ev_i += 1
        if litros > 0:
            # el resto se arrastra: a rejilla gruesa una descarga es una fracción
            # de celda y truncarla hacía desaparecer el aire (fallo F1, 18-ago)
            # cobertura según el combustible del frente (24-ago, ver `aereo.py`)
            _c = A._delante_del_frente(arr, edge, G, t, ws, we, t)
            _f = (sorted(G.fuel[k] for k in _c)[len(_c) // 2] if _c else 0.5)
            resto_agua += litros / A.cobertura_de(_f) / (G.dxm * G.dym)
            n_cel = int(resto_agua)
            if n_cel >= 1:
                resto_agua -= n_cel
                cand = A._delante_del_frente(arr, edge, G, t, ws, we, t)
                for k in A._franja(cand, G, n_cel, ancla=mojadas):
                    mojadas.add(k)
                    ws[k] = min(ws[k], t)
                    we[k] = max(we[k] if we[k] != V.INF else 0.0, t + V.WATER_HOLD)
                    info['regadas'] += 1
                    cambio = True
                    # y si ese tramo iba despacio, el agua lo apaga del todo.
                    # 2026-08-20: por INTENSIDAD si está encendida, igual que
                    # `aereo.moja()`. Dejarlo en velocidad aquí era tener dos
                    # criterios distintos para la misma agua.
                    _e = edge[k] if edge[k] != V.INF else 0.0
                    _apaga = (V.intensidad(_e, G.fuel[k]) <= V.I_AGUA_AEREA
                              if V.USE_INTENSIDAD else edge[k] <= A.WATER_KILL_ROS)
                    if _apaga and t < bt[k]:
                        bt[k] = t
                        info['apagadas_aire'] += 1

        # ── 2 · LA TIERRA, VIENDO LO QUE EL AIRE ACABA DE MOJAR ─────────────
        # Aquí está el acoplamiento: `ef` cuenta el agua, así que un tramo de
        # cabeza que la tierra no podía tocar (edge > DIRECT) pasa a ser
        # atacable mientras esté mojado. Y lo que la tierra corta es PERMANENTE.
        if E > 0 and t >= t_tierra:
            ef, por_agua = edge_efectivo(arr, edge, ws, we, G, t)
            # 2026-08-20 · mismo criterio que `motor.directo()`: intensidad si
            # está encendida, con el umbral que corresponde a la producción de
            # línea del medio (<=500 m/h = herramienta manual).
            if V.USE_INTENSIDAD:
                _imax = M.umbral_intensidad(E)
                _ok = lambda k: V.intensidad(ef[k], G.fuel[k]) <= _imax
                _peso = lambda k: V.intensidad(ef[k], G.fuel[k])
            else:
                _ok = lambda k: ef[k] <= M.DIRECT
                _peso = lambda k: ef[k]
            per = [k for k in ef if not held[k] and _ok(k)]
            # primero lo trabajable EN SECO (un corte seguro y permanente), y sólo
            # con el cupo que sobre se extiende por lo que mojó el aire
            _seco = lambda k: (1 if por_agua.get(k) else 0, _peso(k))
            cupo = E * paso / 60.0 + resto_linea
            if prioridad == 'linea':
                # 26-ago · mismo criterio de PREFERENCIA que 'ancla'; lo único que
                # cambia es que la línea se tiende CONTIGUA y anclada (ver
                # `_linea_de_tierra`). El cupo se traduce a celdas antes de elegir,
                # porque la contigüidad hay que planificarla, no descubrirla.
                per, _sal = _linea_de_tierra(per, cortadas_set, G,
                                             int(cupo // G.dxm), _seco)
                info['saltos_linea'] += _sal
            elif prioridad == 'ancla':
                per.sort(key=_seco)
            else:
                per.sort(key=lambda k: _peso(k))
            for k in per:
                if cupo < G.dxm:
                    break
                cupo -= G.dxm
                held[k] = 1
                cortadas_set.add(k)
                cambio = True
                info['cortadas'] += 1
                if por_agua.get(k):
                    info['cortadas_por_agua'] += 1
                else:
                    info['cortadas_secas'] += 1
                i, j = divmod(k, nc)
                for di in (-1, 0, 1):
                    for dj in (-1, 0, 1):
                        ni, nj = i + di, j + dj
                        if 0 <= ni < nr and 0 <= nj < nc and t < bt[ni * nc + nj]:
                            bt[ni * nc + nj] = t
            resto_linea = max(0.0, cupo)

        if cambio:
            arr = A.sim(c, bt=bt, wt=(ws, we))
        
        # CONDICIÓN DE PARADA CORREGIDA (2026-09-17): verificar si hay fuego activo
        # La condición anterior (`all(a == V.INF or a <= t)`) sólo miraba si todas
        # las celdas habían sido alcanzadas por el frente, no si el fuego seguía
        # activo. Esto causaba falsos positivos de extinción cuando el fuego tenía
        # rutas de propagación disponibles pero aún no las había alcanzado.
        # Ahora se verifica que NO queden celdas por quemar (fuego activo).
        hay_fuego_activo = any(a == V.INF or a > t for a in arr)
        if not hay_fuego_activo:
            break
        
        t += paso
    # ── continuidad de la línea de tierra: ¿una línea, o confeti? ──────────
    def _bandas(S):
        vis, out = set(), []
        for k0 in S:
            if k0 in vis:
                continue
            pila, n = [k0], 0
            vis.add(k0)
            while pila:
                x = pila.pop(); n += 1
                i, j = divmod(x, nc)
                for di in (-1, 0, 1):
                    for dj in (-1, 0, 1):
                        nb = (i + di) * nc + (j + dj)
                        if nb in S and nb not in vis:
                            vis.add(nb); pila.append(nb)
            out.append(n)
        return sorted(out, reverse=True)
    bt_tierra = _bandas(cortadas_set)
    bd_agua = _bandas(mojadas)
    info['bandas_tierra'] = bt_tierra[:8]
    info['n_bandas_tierra'] = len(bt_tierra)
    info['banda_tierra_max'] = bt_tierra[0] if bt_tierra else 0
    info['bandas_agua'] = bd_agua[:8]
    info['n_bandas_agua'] = len(bd_agua)
    return arr, info


# ═══════════════════════════════════════════════════════════════════════════
# EL FRENTE CON MEMORIA · `a84`, §31 · 2026-08-26 · APAGADO en producción
# ═══════════════════════════════════════════════════════════════════════════
# QUÉ SE PRUEBA, y qué NO
# Los cuatro mecanismos de parada de §24 fallaron todos igual: bajaban el área Y el
# alcance. La razón es la topología del camino mínimo — el tiempo de llegada a una celda
# lejana es la SUMA de los del camino, así que cualquier penalización se acumula y
# castiga más a los caminos largos, que son el alcance. Lo formaliza también la consulta
# externa del 26-ago: T'(L) ~ L/(R·g).
#
# ⚠ Y LA OBJECIÓN, ESCRITA ANTES DE IMPLEMENTAR (§31): «el vecino tiene que prender
# antes de que se agote la celda» es `dist/speed <= tau`, o sea `speed >= dist/tau`. Eso
# es `SPREAD_MIN` con otro nombre, y `SPREAD_MIN` ya falló. Por eso `modo='umbral'`
# existe: se corre como CONTROL, para poder demostrar que lo que rompe (si rompe) es la
# CASCADA y no el umbral.
#
# LA CASCADA, que es lo único genuinamente nuevo
# Matar una celda retrasa a sus vecinas —tienen que llegar por otro sitio—, y como la
# velocidad se evalúa con la meteo del INSTANTE DE LLEGADA, llegar más tarde puede
# significar llegar de noche, o sea más despacio, o sea más tarde todavía. Eso puede
# matarlas a ellas. Es un bucle de realimentación que una sola pasada NO puede producir,
# y es exactamente la física de «los flancos se apagan por la noche y ya no vuelven».
#
# POR QUÉ PODRÍA ESCAPAR DONDE LOS OTROS CUATRO NO
# De los cinco mecanismos de §24 el único que rompió el acoplamiento fue `P_IGN`, y lo
# que lo distingue es que NO AÑADE COSTE: quita celdas del grafo. Esto también quita
# celdas del grafo, pero por comportamiento medido en vez de por sorteo.


def _sigue_en_frente(k, arr, G, T):
    """¿La celda `k` sigue teniendo por dónde propagar en el instante `T`?

    Sí, si le queda al menos un vecino que ARDE y al que el fuego todavía no ha llegado
    en `T`. Si no le queda ninguno, el frente ya pasó de largo: la celda es interior y
    su muerte no cambia nada.
    """
    nr, nc = G.nr, G.nc
    i, j = divmod(k, nc)
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            if not di and not dj:
                continue
            ni, nj = i + di, j + dj
            if not (0 <= ni < nr and 0 <= nj < nc):
                continue
            nb = ni * nc + nj
            if G.fuel[nb] <= 0:
                continue
            if arr[nb] > T:            # incluye V.INF
                return True
    return False


def con_muerte_de_frente(c, horizonte_min, tau_min, modo='cascada', iteraciones=12):
    """Propagación en la que un trozo de frente puede MORIR, y muerto no enciende.

    `tau_min` · cuánto aguanta una celda en el perímetro antes de apagarse. ⚠ Es un
    parámetro AJUSTADO, no un dato: haría falta carga de combustible en kg/m² y el motor
    usa una escala 0-1 del NDVI (§31, deber nº1 de `literatura/LEEME.md`).

    `modo='umbral'`  · UNA pasada. Control: equivale a un listón de velocidad.
    `modo='cascada'` · se repite hasta punto fijo. Es lo que se prueba.

    Devuelve (arr, info).
    """
    if modo not in ('umbral', 'cascada'):
        raise ValueError(f'modo desconocido: {modo}')
    G = c['G']
    N = G.nr * G.nc
    arr = A.sim(c)
    dtsrc = [V.INF] * N
    muertas = set()
    info = dict(tau_min=tau_min, modo=modo, iteraciones=0, convergido=False,
                muertas=0, muertas_por_iter=[])
    n_it = 1 if modo == 'umbral' else iteraciones
    for it in range(n_it):
        info['iteraciones'] = it + 1
        antes = len(muertas)
        for k in range(N):
            a = arr[k]
            if a == V.INF or a > horizonte_min:
                continue
            T = a + tau_min
            if T >= horizonte_min:      # no le da tiempo a morir dentro del horizonte
                continue
            if k in muertas:
                dtsrc[k] = T            # `arr` puede haber crecido: se refresca
                continue
            if _sigue_en_frente(k, arr, G, T):
                muertas.add(k)
                dtsrc[k] = T
        nuevas = len(muertas) - antes
        info['muertas_por_iter'].append(nuevas)
        if not muertas:
            break
        arr = A.sim(c, dtsrc=dtsrc)
        if nuevas == 0:
            info['convergido'] = True
            break
    info['muertas'] = len(muertas)
    return arr, info
