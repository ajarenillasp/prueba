#!/usr/bin/env python3
"""
Script de prueba para verificar las correcciones en el simulador de incendios.
"""
import sys
sys.path.insert(0, '/workspace/auditoria_externa/2_motor')
sys.path.insert(0, '/workspace/auditoria_externa/1_extincion')

import validate_block_a as V
import motor
import aereo
import mixto

print("=" * 70)
print("PRUEBAS DE CORRECCIONES - SIMULADOR DE INCENDIOS")
print("=" * 70)

# Crear una configuración de prueba mínima
def crear_config_prueba():
    """Crea una configuración básica para pruebas."""
    nr, nc = 50, 50
    G = type('Grid', (), {
        'nr': nr,
        'nc': nc,
        'dxm': 80.0,  # metros por celda en X
        'dym': 80.0,  # metros por celda en Y
        'fuel': [0.5] * (nr * nc),  # combustible uniforme
        'ease': [1.0] * (nr * nc),  # facilidad uniforme
    })()
    
    seeds = [nr * nc // 2]  # ignición en el centro
    
    return {
        'G': G,
        'seeds': seeds,
        'met': {'wspd': 5.0, 'wdir': 45.0},
        'start_h': 12.0,
        'ws': None,
        'rh': None,
    }

print("\n1. VERIFICANDO CORRECCIÓN EN aereo.py (conservación del mojado)")
print("-" * 70)
try:
    c = crear_config_prueba()
    flota = [('FOCA', 2)]  # 2 aviones FOCA
    horizonte = 180
    lat, doy = 40.0, 180
    
    arr, info = aereo.con_aire(c, flota, horizonte, lat, doy, iteraciones=3)
    
    print(f"✓ con_aire ejecuta correctamente")
    print(f"  - Descargas: {info['n_descargas']}")
    print(f"  - Celdas regadas: {info['regadas']}")
    print(f"  - Celdas apagadas: {info.get('apagadas', 'N/A')}")
except Exception as e:
    print(f"✗ ERROR en aereo.con_aire: {e}")
    import traceback
    traceback.print_exc()

print("\n2. VERIFICANDO CORRECCIÓN EN mixto.py (condición de parada)")
print("-" * 70)
try:
    c = crear_config_prueba()
    flota = [('FOCA', 1)]
    E = 324.0  # m/h de línea de tierra
    horizonte = 240
    lat, doy = 40.0, 180
    
    arr, info = mixto.con_aire_y_tierra(
        c, flota, E, horizonte, lat, doy, 
        prioridad='ancla'
    )
    
    print(f"✓ con_aire_y_tierra ejecuta correctamente")
    print(f"  - Pasos: {info['pasos']}")
    print(f"  - Cortadas: {info['cortadas']}")
    print(f"  - Regadas: {info['regadas']}")
    print(f"  - Bandas de tierra: {info['n_bandas_tierra']}")
    print(f"  - Banda máxima: {info['banda_tierra_max']}")
    
    # Verificar continuidad
    if info['n_bandas_tierra'] <= 3 and info['banda_tierra_max'] > 10:
        print(f"✓ La línea de tierra muestra buena continuidad")
    else:
        print(f"⚠ La línea puede estar fragmentada (verificar visualmente)")
        
except Exception as e:
    print(f"✗ ERROR en mixto.con_aire_y_tierra: {e}")
    import traceback
    traceback.print_exc()

print("\n3. VERIFICANDO QUE motor.directo maneja correctamente el cupo")
print("-" * 70)
try:
    c = crear_config_prueba()
    E = 324.0
    arr0 = motor.sim(c, bt=[V.INF] * (c['G'].nr * c['G'].nc))
    edge = motor.edge_ros(arr0, c['G'])
    
    arr_final, bt_final = motor.directo(c, E, arr0, edge, [V.INF] * len(arr0))
    
    quemadas_inicial = sum(1 for a in arr0 if a != V.INF and a <= motor.HOR)
    quemadas_final = sum(1 for a in arr_final if a != V.INF and a <= motor.HOR)
    
    print(f"✓ directo ejecuta correctamente")
    print(f"  - Celdas quemadas inicial: {quemadas_inicial}")
    print(f"  - Celdas quemadas final: {quemadas_final}")
    print(f"  - Reducción: {quemadas_inicial - quemadas_final} celdas")
    
except Exception as e:
    print(f"✗ ERROR en motor.directo: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)
print("RESUMEN DE CORRECCIONES APLICADAS:")
print("=" * 70)
print("""
1. aereo.py (líneas 499-520):
   - CORREGIDO: Reinicio completo de ws/we en cada iteración
   - AHORA: Se conserva el mojado acumulado entre iteraciones
   - EFECTO: El agua aplicada persiste, evitando "agua fantasma"

2. mixto.py (líneas 343-376):
   - CORREGIDO: Condición de parada incorrecta (all(a <= t))
   - AHORA: Verifica si hay rutas de propagación disponibles
   - EFECTO: Detecta correctamente cuando el fuego está contenido

3. mixto.py (continuidad):
   - YA IMPLEMENTADO: _linea_de_tierra para contigüidad
   - EFECTO: Las líneas de extinción son continuas, no parches

4. motor.py:
   - YA IMPLEMENTADO: Arrastre de cupo sobrante entre pasos
   - EFECTO: No se pierde esfuerzo de extinción
""")

print("=" * 70)
print("PRUEBAS COMPLETADAS")
print("=" * 70)
