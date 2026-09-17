#!/usr/bin/env python3
"""
JUEZ de la cola del 17-sep · `c184` (ataque directo) · `c185` (perímetro al primer trabajo) · `c186` (despliegue).
Las reglas son las de INCENDIOS.md §179, escritas ANTES de correr. Aquí NO se tocan.

    python3 auditoria_cola17.py
"""
import json, math, os
import numpy as np

SCR = '/mnt/qnap/greenhouse3/contencion'
rng = np.random.default_rng(2026)
B = 2000
OUT = {}


def ic(v):
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    if not len(v):
        return [float('nan')] * 2
    b = v[rng.integers(0, len(v), (B, len(v)))].mean(axis=1)
    return [float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))]


def sv(r, k):
    x = r['brazos'].get(k)
    return x['salvado'] if x else None


# ══════════════════ c184 · EL ATAQUE DIRECTO ══════════════════
print('=' * 104 + '\n🪓 c184 · ATAQUE DIRECTO CON TASAS ESPAÑOLAS · cuadrilla de 9 bomberos\n' + '=' * 104)
R4 = [r for r in map(json.loads, open(f'{SCR}/c184_directo_ortega.jsonl')) if 'error' not in r and r.get('brazos')]
print(f'{len(R4)} incendios')
# ⚓ ANCLA · `ort9_i` tiene que reproducir el brazo `ort9` de `c183`, fila a fila
R3 = {r['uid']: r for r in map(json.loads, open(f'{SCR}/c183_ortega.jsonl')) if 'error' not in r and r.get('brazos')}
pares = dist = 0
for r in R4:
    o = R3.get(r['uid'])
    if not o:
        continue
    for f in (8, 32):
        a, b = sv(r, f'ort9_i_{f}'), (o['brazos'].get(f'ort9_{f}') or {}).get('salvado')
        if a is not None and b is not None:
            pares += 1
            dist += abs(a - b) > 1e-9
ANC = pares > 0 and dist == 0
print(f'⚓ ANCLA · `ort9_i` = `c183.ort9`: {pares} pares · {dist} distintos → {"✔" if ANC else "⛔"}')
guard = sum(1 for r in R4 if sv(r, 'plano_d_8') == sv(r, 'ort9_d_8'))
print(f'⚓ GUARDIÁN · incendios con el directo español idéntico al plano: {guard} de {len(R4)} '
      f'→ {"✔" if guard < len(R4) * 0.1 else "⛔"}')

res4 = {}
print(f'\n{"comparación":<28}{"fuerza":>7}{"n":>5}{"ref":>9}{"brazo":>9}{"Δ pareado":>11}{"IC 95%":>21}{"mej/emp":>12}')
for f in (8, 32):
    for nom, a, b in (('ort9_d contra plano_d', 'ort9_d', 'plano_d'),
                      ('ort9_di contra ort9_i', 'ort9_di', 'ort9_i'),
                      ('ort9_di contra ort9_d', 'ort9_di', 'ort9_d')):
        p = [(sv(r, f'{a}_{f}'), sv(r, f'{b}_{f}')) for r in R4]
        p = [(x, y) for x, y in p if x is not None and y is not None]
        d = np.array([x - y for x, y in p])
        i = ic(d)
        res4[(nom, f)] = (len(d), float(d.mean()), i)
        print(f'{nom:<28}{f:>7}{len(d):>5}{np.mean([y for _, y in p]):>8.2f}%{np.mean([x for x, _ in p]):>8.2f}%'
              f'{d.mean():>+10.2f}  [{i[0]:>+6.2f}, {i[1]:>+6.2f}]{int((d>0).sum()):>6}/{int((d<0).sum()):<6}')
n4 = min(v[0] for v in res4.values())
limpio = lambda k: res4[k][2][0] > 0
if n4 < 25:
    s4 = f'⚠ NO CONCLUYE (n={n4})'
elif not ANC:
    s4 = '⛔ ANCLA FALLIDA · no se lee'
elif all(limpio(('ort9_d contra plano_d', f)) for f in (8, 32)):
    s4 = '⭐ A · EL DIRECTO PAGA · sube con IC limpio en las dos fuerzas'
elif any(limpio(('ort9_d contra plano_d', f)) for f in (8, 32)):
    s4 = '⚠ B · A MEDIAS · sólo en una fuerza'
else:
    s4 = '⛔ C · NO PAGA'
print(f'\n  ⇒ c184 · {s4}')
OUT['c184'] = {'salida': s4, 'ancla': {'pares': pares, 'distintos': dist},
               'res': {f'{k[0]}_{k[1]}': {'n': v[0], 'dif': v[1], 'ic': v[2]} for k, v in res4.items()}}

# ══════════════════ c185 · EL PERÍMETRO AL PRIMER TRABAJO ══════════════════
print('\n' + '=' * 104 + '\n📏 c185 · PERÍMETRO AL PRIMER TRABAJO ÷ PRODUCCIÓN = «la carrera», en horas\n' + '=' * 104)
R5 = {r['uid']: r for r in map(json.loads, open(f'{SCR}/c185_perimetro.jsonl'))}
print(f'{len(R5)} incendios · perímetro mediano a los 60 min: '
      f'{np.median([r["perim_m"] for r in R5.values()]):.0f} m')


def spearman(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    rx = np.argsort(np.argsort(x)); ry = np.argsort(np.argsort(y))
    return float(np.corrcoef(rx, ry)[0, 1])


res5 = {}
for f in (8, 32):
    xs, ys, ps = [], [], []
    for r in R4:
        q = R5.get(r['uid'])
        s = sv(r, f'ort9_di_{f}')
        if not q or s is None or not q['carrera_h'].get(str(f)):
            continue
        xs.append(q['carrera_h'][str(f)]); ys.append(s); ps.append(q['perim_m'])
    rho_c, rho_p = spearman(xs, ys), spearman(ps, ys)
    res5[f] = dict(n=len(xs), rho_carrera=rho_c, rho_perimetro=rho_p,
                   carrera_mediana=float(np.median(xs)))
    print(f'  {f:>2} cuadrillas · n={len(xs):>3} · carrera mediana {np.median(xs):>5.2f} h · '
          f'Spearman(carrera, salvado) = {rho_c:+.3f} · Spearman(perímetro, salvado) = {rho_p:+.3f}')
m = max(abs(res5[f]['rho_carrera']) for f in (8, 32))
mn = min(abs(res5[f]['rho_carrera']) for f in (8, 32))
s5 = ('⭐ A · LA CARRERA MANDA' if mn >= 0.50 else
      '⚠ B · APORTA' if mn >= 0.30 else '⛔ C · NO MANDA')
mejor = all(abs(res5[f]['rho_carrera']) > abs(res5[f]['rho_perimetro']) for f in (8, 32))
print(f'\n  ⇒ c185 · {s5} · |ρ| entre {mn:.2f} y {m:.2f}'
      f'  ·  D: la carrera {"SÍ" if mejor else "NO"} predice mejor que el perímetro a secas')
OUT['c185'] = {'salida': s5, 'res': res5, 'carrera_mejor_que_perimetro': bool(mejor)}

# ══════════════════ c186 · LA REGLA DE DESPLIEGUE ══════════════════
print('\n' + '=' * 104 + '\n🚒⏱ c186 · LA REGLA DE DESPLIEGUE CON LA CUADRILLA DECIDIDA\n' + '=' * 104)
try:
    R6 = [r for r in map(json.loads, open(f'{SCR}/c186_despliegue_ortega.jsonl')) if 'error' not in r and r.get('brazos')]
except FileNotFoundError:
    R6 = []
if not R6:
    print('  (sin crudo todavía)')
else:
    FUERZAS, RETRASOS = [4, 8, 16, 32], [15, 30, 60, 90, 120]
    print(f'{len(R6)} incendios')
    M = {}
    for brazo in ('plano', 'ort9'):
        for f in FUERZAS:
            for t in RETRASOS:
                v = [sv(r, f'{brazo}_{f}_{t}') for r in R6]
                v = [x for x in v if x is not None]
                M[(brazo, f, t)] = float(np.mean(v)) if v else None
        print(f'\n  {brazo} · % salvado (media)')
        print('    ' + 'cuadrillas'.ljust(12) + ''.join(f'{t} min'.rjust(10) for t in RETRASOS))
        for f in FUERZAS:
            print(f'    {f:<12}' + ''.join((f'{M[(brazo,f,t)]:>9.2f}%' if M[(brazo, f, t)] is not None else '        —')
                                           for t in RETRASOS))
    fronteras = {}
    print(f'\n  frontera de indiferencia · minutos de espera que compensa DOBLAR la fuerza')
    print('    ' + 'transición'.ljust(14) + ''.join(f'desde {t}'.rjust(11) for t in RETRASOS[:-1]))
    for brazo in ('plano', 'ort9'):
        fila = []
        for i_, f in enumerate(FUERZAS[:-1]):
            f2 = FUERZAS[i_ + 1]
            for t1 in RETRASOS[:-1]:
                base = M[(brazo, f, t1)]
                gana = [t2 for t2 in RETRASOS if t2 > t1 and (M[(brazo, f2, t2)] or -1) >= (base or 1e9)]
                fronteras[(brazo, f, t1)] = (max(gana) - t1) if gana else 0
        for i_, f in enumerate(FUERZAS[:-1]):
            f2 = FUERZAS[i_ + 1]
            print(f'    {brazo} {f}→{f2}'.ljust(18) + ''.join(
                f'{fronteras[(brazo,f,t1)]:>10.0f}' for t1 in RETRASOS[:-1]))
    difs = [abs(fronteras[('ort9', f, t1)] - fronteras[('plano', f, t1)])
            for f in FUERZAS[:-1] for t1 in RETRASOS[:-1]]
    peor = max(difs)
    s6 = ('⭐ A · LA REGLA AGUANTA' if peor < 15 else
          '⚠ B · SE MUEVE' if peor <= 45 else '⛔ C · NO VALE · hay que reescribir el texto')
    print(f'\n  ⇒ c186 · {s6} · el mayor cambio de frontera es {peor:.0f} min')
    OUT['c186'] = {'salida': s6, 'peor_cambio_min': peor,
                   'malla': {f'{k[0]}_{k[1]}_{k[2]}': v for k, v in M.items()},
                   'fronteras': {f'{k[0]}_{k[1]}_{k[2]}': v for k, v in fronteras.items()}}

json.dump(OUT, open(f'{SCR}/auditoria_cola17.json', 'w'), indent=1, ensure_ascii=False, default=float)
print(f'\n→ {SCR}/auditoria_cola17.json')
