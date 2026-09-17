#!/usr/bin/env python3
"""
c184 · 🪓 EL ATAQUE DIRECTO CON EL RENDIMIENTO ESPAÑOL · cuadrilla = 9 bomberos · PRE-REGISTRO §179

DE DÓNDE SALE. `c183` (§177) metió las tasas de Ortega (2023) en la línea INDIRECTA y el salvado subió. Pero
`motor.directo()` —el ataque directo sobre el borde— **se quedó a tasa plana**, y Ortega publica el directo, que es
**2-3× el indirecto**. Es lo único de la matriz externa (§178) que puede mover el número HACIA ARRIBA.

DECISIÓN DEL USUARIO (17-sep): **una cuadrilla son 9 bomberos.** Todo lo de aquí usa eso.

TASAS (Ortega 2023, Tabla 3, m/min por bombero × 9 bomberos × 60):
                    indirecto            directo
    pasto           0,40 →  216 m/h      0,87 →  470 m/h
    matorral        0,31 →  167 m/h      0,67 →  362 m/h
    arbolado        0,16 →   86 m/h      0,44 →  238 m/h
Mapeo de combustible: el MISMO de `c182`/`c183` (fuel<0,30 pasto · 0,30-0,60 matorral · >=0,60 arbolado).

BRAZOS · 8 y 32 cuadrillas (72 y 288 bomberos) · llegada 60 min · 24 h · tierra sola:
    `plano_d`   · control · ataque directo a 126 m/h planos (lo que hay hoy)
    `ort9_d`    · ataque directo con las tasas DIRECTAS de Ortega
    `ort9_i`    · sólo línea indirecta con las INDIRECTAS (= `ort9` de `c183`)   ⚓ ANCLA: fila a fila contra `c183`
    `ort9_di`   · las dos tácticas juntas, como hace `mejor_extincion`: primero la línea, luego el directo encima
⚓ Y un guardián: `plano_d` tiene que salir DISTINTO de `ort9_d` (si no, el mando no se aplicó).

SALIDAS, ESCRITAS ANTES DE CORRER:
 A · ⭐ **EL DIRECTO PAGA** si `ort9_d` salva más que `plano_d` con el IC 95% del pareado sin cruzar 0 en las dos fuerzas.
 B · ⚠ **A MEDIAS** si sólo en una fuerza.
 C · ⛔ **NO PAGA** si el IC cruza 0 en las dos.
 D · informa: `ort9_di` contra el mejor de los dos por separado — ¿suman las dos tácticas o se estorban?
 ⚠ NO CONCLUYE si n < 25.

    HUMO=1 NMAX=3 WORKERS=3 python3 c184_directo_ortega.py
    WORKERS=13 python3 c184_directo_ortega.py
"""
import json, os, sys, time

ROOT = '/mnt/qnap/greenhouse3'
SCR, VAL = f'{ROOT}/contencion', f'{ROOT}/scripts/validacion'
sys.path.insert(0, SCR); sys.path.insert(0, VAL)
import e56_orden as O          # noqa: E402
import validate_block_a as V   # noqa: E402
import motor as M_             # noqa: E402

GAP, FRAC_FIJA, T_LLEGA = 30.0, 0.45, 60.0
HORA = float(os.environ.get('HORA', '24'))
FUERZAS = [int(x) for x in os.environ.get('FUERZAS', '8,32').split(',')]
BOMBEROS = 9                     # ⭐ decisión del usuario, 17-sep
E_PLANO = 126.0
IND = {k: v * BOMBEROS * 60 for k, v in (('pasto', 0.40), ('matorral', 0.31), ('arbolado', 0.16))}
DIR = {k: v * BOMBEROS * 60 for k, v in (('pasto', 0.87), ('matorral', 0.67), ('arbolado', 0.44))}
HUMO = bool(int(os.environ.get('HUMO', '0')))
SUF = os.environ.get('SUF', '') + ('_humo' if HUMO else '')
JSONL = f'{SCR}/c184_directo_ortega{SUF}.jsonl'
clase = lambda f: 'pasto' if f < 0.30 else ('matorral' if f < 0.60 else 'arbolado')


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
    N = G.nr * G.nc
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
        fila['eje'] = {'n': len(eje), **{cl: round(cls.count(cl) / len(cls), 3) for cl in IND}}
        edge = M_.edge_ros(lr, G)

        def quema(a):
            return sum(1 for x in a if x != V.INF and x <= hm)

        def linea(tab, fuerza):
            M_.RATE_CELDA = (lambda k, _T=tab, _f=fuerza: _T[clase(G.fuel[k])] * _f / 60.0)
            cel = M_.tiempos_desde_el_medio(G, eje, T_LLEGA, 0.0, tmed - T_LLEGA)
            M_.RATE_CELDA = None
            return (V.field_from(G, cel), len(cel)) if len(cel) >= 2 else (None, 0)

        for fuerza in FUERZAS:
            E_nom = E_PLANO * fuerza          # sólo para el umbral de trabajabilidad, igual en todos los brazos
            # 1 · directo plano (control)
            M_.RATE_CELDA = None
            a, _ = M_.directo(cc, E_nom, lr, edge, [V.INF] * N)
            fila['brazos'][f'plano_d_{fuerza}'] = {'salvado': round(100.0 * (qh - quema(a)) / qh, 3)}
            # 2 · directo con tasas españolas
            M_.RATE_CELDA = (lambda k, _f=fuerza: DIR[clase(G.fuel[k])] * _f / 60.0)
            a, _ = M_.directo(cc, E_nom, lr, edge, [V.INF] * N)
            M_.RATE_CELDA = None
            fila['brazos'][f'ort9_d_{fuerza}'] = {'salvado': round(100.0 * (qh - quema(a)) / qh, 3)}
            # 3 · sólo línea indirecta (ancla contra c183)
            bt, nc_ = linea(IND, fuerza)
            if bt is None:
                fila['brazos'][f'ort9_i_{fuerza}'] = None
                fila['brazos'][f'ort9_di_{fuerza}'] = None
                continue
            a_i = M_.sim(cc, bt)
            fila['brazos'][f'ort9_i_{fuerza}'] = {'salvado': round(100.0 * (qh - quema(a_i)) / qh, 3),
                                                  'celdas_linea': nc_}
            # 4 · las dos juntas: la línea y, encima, el directo (como `mejor_extincion`)
            M_.RATE_CELDA = (lambda k, _f=fuerza: DIR[clase(G.fuel[k])] * _f / 60.0)
            a_di, _ = M_.directo(cc, E_nom, a_i, M_.edge_ros(a_i, G), list(bt))
            M_.RATE_CELDA = None
            fila['brazos'][f'ort9_di_{fuerza}'] = {'salvado': round(100.0 * (qh - quema(a_di)) / qh, 3)}
    except Exception as e:
        fila['error'] = f'{type(e).__name__}: {e}'
    finally:
        M_.RATE_CELDA = None
    with open(JSONL, 'a') as fh:
        fh.write(json.dumps(fila) + '\n')
    return fila


if __name__ == '__main__':
    C = O.carga()
    if HUMO:
        C = C[:int(os.environ.get('NMAX', '3'))]
    elif int(os.environ.get('NMAX', '0')):
        C = C[:int(os.environ['NMAX'])]
    print(f'c184 · {len(C)} incendios · cuadrilla {BOMBEROS} bomberos · indirecto {IND} · directo {DIR}', flush=True)
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
