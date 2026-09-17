#!/usr/bin/env python3
"""
c183 · 👷🇪🇸 EL RENDIMIENTO DE LÍNEA MEDIDO EN ESPAÑA (Ortega 2023) CONTRA LAS TABLAS AMERICANAS · PRE-REGISTRO §177

DE DÓNDE SALE. `c182` (§176) metió el rendimiento por combustible con las tablas **NWCG/Broyles**, que son de EE.UU.
El usuario trajo el 17-sep el artículo que faltaba: **Ortega, Rodríguez y Silva & Molina (2023), IJWF 32:1503-1514**,
204 actuaciones medidas **con GPS en incendios activos del sur de España** (2014-2019). Su Tabla 10 dice, con esas
palabras, que las tasas españolas son **casi tres veces** las americanas en todos los combustibles.

LA VARA DE ORTEGA (y hay que respetarla): metros de línea / **tiempo efectivo de trabajo** —incluye descansos,
EXCLUYE desplazamientos— y **por bombero**.

TABLA 3, ataque INDIRECTO (que es el que abre este simulador), m/min por bombero:
    pasto 0,40 (n=10) · chaparral 0,31 (n=16) · matorral 0,31 (agrupado con chaparral en el texto) ·
    arbolado con sotobosque 0,16 (n=10)
⇒ para una cuadrilla de 20 bomberos: **pasto 480 · matorral 372 · arbolado 192 m/h**
⇒ para una cuadrilla de 9 (la norma española, y el corte donde Ortega mide que cae el rendimiento por persona):
   **pasto 216 · matorral 167 · arbolado 86 m/h**

⭐⭐ Y ESTO DA LA VUELTA AL ORDEN de `c182`: con NWCG el lento era el MATORRAL (99 m/h) y con Ortega el lento es el
ARBOLADO (192 con 20 bomberos). Como el eje de nuestra línea va por **76,5% de matorral** (§176.2), el signo del
resultado puede cambiar.

LOS BRAZOS (mismo mapeo de combustible que `c182`, para comparar igual con igual: fuel<0,30 pasto · 0,30-0,60
matorral · >=0,60 arbolado; línea indirecta a la fracción desplegada 0,45; llegada 60 min; 24 h; 8 y 32 cuadrillas):
    `plano126`     · control · 126 m/h planos (`c168`)                     ⚓ ANCLA: idéntico a `c182`, fila a fila
    `nwcg`         · lo de `c182` · pasto 191 · matorral 99 · arbolado 139
    `ort20`        · Ortega con cuadrilla de **20** bomberos (comparable con NWCG, que se normaliza a 20)
    `ort9`         · Ortega con cuadrilla de **9** · ⚠ es OTRA FUERZA: informa, no compara
    `ort20_fatiga` · `ort20` × la ley de fatiga de Ortega (Tabla 6): c1 = −0,21·ln(t) + 1,45.
                     ⚠ **NORMALIZADA a t = 120 min** (centro de la categoría media del estudio) porque las medias de
                     la Tabla 3 YA promedian trabajos de 20 a 605 min: aplicarla cruda contaría la fatiga dos veces.
                     ⛔⛔ **CORREGIDO EN LA PRUEBA DE HUMO, y se declara**: la primera versión metía `c1` como ritmo
                     INSTANTÁNEO (celda a celda con el reloj de la obra) y eso convierte una ley de reducción en un
                     PREMIO —a los pocos minutos de obra el factor vale 3,26×— porque `c1` está ajustada a
                     **operaciones enteras** indexadas por su tiempo TOTAL, no a una curva instantánea. Uso fiel y
                     definitivo: **un solo factor por operación en DOS PASADAS** — se abre la línea con `ort20`, se
                     mide el tiempo total de obra T, y se reabre con `c1(T)/c1(120)` constante. Ninguna cifra del humo
                     se cita.
    `ort20_aire`   · `ort20` × el acoplamiento aéreo de Ortega (Tabla 6): c2 = −0,20·ln(y) + 1,45, y = minutos entre
                     descargas. La flota estándar del banco (ALFA 1, BRIF-A 2, BRIF-B 1, FOCA 4, KILO 1, MIKE 1) da
                     una descarga cada **1,57 min**, por debajo del rango medido (3-30), así que se recorta a y=3 y
                     sale un **×1,23 plano**. ⚠ Es el TAMAÑO del acoplamiento, no un mecanismo: aire y tierra siguen
                     sin hablarse en el motor.

LAS SALIDAS, ESCRITAS ANTES DE CORRER (y con mi apuesta dicha antes, §177):
 A · ⭐ **ORTEGA DA LA VUELTA** si `ort20` salva MÁS que `plano126` con el IC 95% del pareado sin cruzar 0
     (es lo que predije: el matorral pasa de 99 a 372 m/h y la línea va por ahí).
 B · ⚠ **MISMA DIRECCIÓN QUE NWCG** si `ort20` salva menos que `plano126` con IC limpio.
 C · ⛔ **NO SE DISTINGUE** si el IC cruza 0.
 D · informa: el tamaño de la fatiga (`ort20_fatiga` − `ort20`) y del acoplamiento aéreo (`ort20_aire` − `ort20`).
 E · informa: `ort9`, que es otra fuerza y no se compara de tú a tú.
 ⚠ NO CONCLUYE si n < 25.

    HUMO=1 NMAX=3 WORKERS=3 python3 c183_ortega.py
    WORKERS=13 python3 c183_ortega.py
"""
import json, math, os, sys, time

ROOT = '/mnt/qnap/greenhouse3'
SCR, VAL = f'{ROOT}/contencion', f'{ROOT}/scripts/validacion'
sys.path.insert(0, SCR); sys.path.insert(0, VAL)
import e56_orden as O          # noqa: E402
import validate_block_a as V   # noqa: E402
import motor as M_             # noqa: E402

GAP = 30.0
FRAC_FIJA = 0.45
T_LLEGA = 60.0
HORA = float(os.environ.get('HORA', '24'))
FUERZAS = [int(x) for x in os.environ.get('FUERZAS', '8,32').split(',')]
E_PLANO = 126.0
NWCG = {'pasto': 191.0, 'matorral': 99.0, 'arbolado': 139.0}            # `c182` · Tipo I, indirecto, 20 bomberos
ORT_MIN = {'pasto': 0.40, 'matorral': 0.31, 'arbolado': 0.16}          # Ortega Tabla 3, indirecto, m/min/bombero
ORT20 = {k: v * 20 * 60 for k, v in ORT_MIN.items()}                   # 480 · 372 · 192 m/h
ORT9 = {k: v * 9 * 60 for k, v in ORT_MIN.items()}                     # 216 · 167 · 86 m/h
C1_REF = -0.21 * math.log(120.0) + 1.45                                # normalización de la fatiga (t = 120 min)
C2_AIRE = -0.20 * math.log(3.0) + 1.45                                 # 1,230 · flota estándar, recortada al rango
HUMO = bool(int(os.environ.get('HUMO', '0')))
SUF = os.environ.get('SUF', '') + ('_humo' if HUMO else '')
JSONL = f'{SCR}/c183_ortega{SUF}.jsonl'


def clase(f):
    return 'pasto' if f < 0.30 else ('matorral' if f < 0.60 else 'arbolado')


def fatiga(t_min):
    """Factor de fatiga de Ortega normalizado a 120 min. t en minutos ya trabajados."""
    return max(0.05, (-0.21 * math.log(max(t_min, 1.0)) + 1.45) / C1_REF)


def procesa(c):
    obs_t = c['obs_t']
    if len(obs_t) < 40:
        return None
    G = c['G']
    ts = sorted(set(obs_t.values()))
    pas = [[ts[0]]]
    for t in ts[1:]:
        (pas.append([t]) if t - pas[-1][-1] > GAP else pas[-1].append(t))
    if len(pas) < 3:
        return None
    V.SNAP = c['snap']; O.aplica()
    huella = [k for k, t in obs_t.items() if t <= pas[0][-1] and G.fuel[k]]
    if not huella:
        return None
    cc = dict(G=G, seeds=huella, met=c['met'], start_h=c['start_h'], ws=c.get('ws'), rh=c.get('rh'))
    libre, _ = V.dijkstra(G, huella, wspd=c['met']['wspd'], wdir=c['met']['wdir'],
                          start_h=c['start_h'], wind_series=c.get('ws'), rh_series=c.get('rh'))
    hm = HORA * 60
    M_.HOR = hm
    lr = [x if (x != V.INF and x <= hm) else V.INF for x in libre]
    qh = sum(1 for a in lr if a != V.INF)
    if qh < 60:
        return None
    fila = {'uid': c['uid'], 'celda_ha': G.dxm * G.dym / 10000.0, 'libre': qh, 'huella': len(huella), 'brazos': {}}
    try:
        geo = M_.geometria(lr, G, huella)
        if not geo:
            return None
        eje = M_.eje_candidato(G, geo, FRAC_FIJA, 0, lr)
        if len(eje) < 4:
            return None
        lleg = sorted(lr[k] for k in eje if lr[k] != V.INF)
        if not lleg:
            return None
        tmed = lleg[len(lleg) // 2]
        if tmed <= T_LLEGA:
            return None
        cls = [clase(G.fuel[k]) for k in eje]
        fila['eje'] = {'n': len(eje), **{cl: round(cls.count(cl) / len(cls), 3) for cl in NWCG}}

        for fuerza in FUERZAS:
            for brazo in ('plano126', 'nwcg', 'ort20', 'ort9', 'ort20_fatiga', 'ort20_aire'):
                rate_min = 0.0
                if brazo == 'plano126':
                    M_.RATE_CELDA = None
                    rate_min = E_PLANO * fuerza / 60.0
                else:
                    TAB = {'nwcg': NWCG, 'ort20': ORT20, 'ort9': ORT9,
                           'ort20_fatiga': ORT20, 'ort20_aire': ORT20}[brazo]
                    esc = C2_AIRE if brazo == 'ort20_aire' else 1.0
                    M_.RATE_CELDA_T = False
                    if brazo == 'ort20_fatiga':
                        # PASADA 1 · con `ort20` a secas, para saber cuánto dura la obra
                        M_.RATE_CELDA = (lambda k, _T=TAB, _f=fuerza: _T[clase(G.fuel[k])] * _f / 60.0)
                        c0 = M_.tiempos_desde_el_medio(G, eje, T_LLEGA, 0.0, tmed - T_LLEGA)
                        # t = (tiempo de la última celda − t0) / 2 · el motor escribe t0 + acct*2
                        T_obra = max(((max(t for _, t in c0) - T_LLEGA) / 2.0) if len(c0) > 1 else 1.0, 1.0)
                        esc = fatiga(T_obra)
                        fila['brazos'].setdefault('_fatiga', {})[str(fuerza)] = \
                            {'T_obra_min': round(T_obra, 1), 'factor': round(esc, 3)}
                    M_.RATE_CELDA = (lambda k, _T=TAB, _e=esc, _f=fuerza:
                                     _T[clase(G.fuel[k])] * _e * _f / 60.0)
                cel = M_.tiempos_desde_el_medio(G, eje, T_LLEGA, rate_min, tmed - T_LLEGA)
                M_.RATE_CELDA = None; M_.RATE_CELDA_T = False
                if len(cel) < 2:
                    fila['brazos'][f'{brazo}_{fuerza}'] = None
                    continue
                bt = V.field_from(G, cel)
                a = M_.sim(cc, bt)
                q = sum(1 for x in a if x != V.INF and x <= hm)
                fila['brazos'][f'{brazo}_{fuerza}'] = {'quemado': q, 'celdas_linea': len(cel),
                                                       'salvado': round(100.0 * (qh - q) / qh, 3)}
    except Exception as e:
        fila['error'] = f'{type(e).__name__}: {e}'
    finally:
        M_.RATE_CELDA = None; M_.RATE_CELDA_T = False
    with open(JSONL, 'a') as fh:
        fh.write(json.dumps(fila) + '\n')
    return fila


if __name__ == '__main__':
    C = O.carga()
    if HUMO:
        C = C[:int(os.environ.get('NMAX', '3'))]
    elif int(os.environ.get('NMAX', '0')):
        C = C[:int(os.environ['NMAX'])]
    print(f'c183 · {len(C)} incendios · ort20 {ORT20} · ort9 {ORT9} · c2 aire {C2_AIRE:.3f}', flush=True)
    import multiprocessing as mp
    hechos = set()
    if os.path.exists(JSONL):
        for ln in open(JSONL):
            try:
                hechos.add(json.loads(ln)['uid'])
            except Exception:
                pass
    pend = [c for c in C if c['uid'] not in hechos]
    print(f'{len(pend)} pendientes · {len(hechos)} hechos', flush=True)
    t0 = time.time(); ok = 0
    with mp.get_context('fork').Pool(int(os.environ.get('WORKERS', '6'))) as pool:
        for i, r in enumerate(pool.imap_unordered(procesa, pend), 1):
            ok += bool(r)
            if i % 40 == 0 or i == len(pend):
                print(f'  [{i}/{len(pend)}] · {ok} ok · {(time.time()-t0)/60:.1f} min', flush=True)
    print(f'LISTA · {ok} incendios en {(time.time()-t0)/60:.1f} min · {JSONL}', flush=True)
