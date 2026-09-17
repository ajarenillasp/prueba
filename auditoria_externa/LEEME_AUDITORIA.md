# PAQUETE PARA AUDITORÍA EXTERNA · simulador de incendios + extinción

Generado el **2026-09-17**. Son copias; el original vive en `/mnt/qnap/greenhouse3/` y en
`/mnt/qnap_web/greenhouse_3/`. **No hay credenciales en ningún fichero de esta carpeta** (comprobado).

## QUÉ SE PIDE

Auditar y proponer mejoras **del apagado y los medios de extinción**, que es donde está el problema: el simulador
salva **32-44%** del área que ardería sin nadie y la realidad española salva **67%** (INFOCA, misma definición). La
propagación libre **no** es el problema: de 0 a 3 h acierta (área 0,96-1,02×, rumbo 5° de error).

## POR DÓNDE EMPEZAR · las tres carpetas, en orden

### `1_extincion/` ⭐ **lo imprescindible** · 73 KB · aquí está lo que se audita
| fichero | qué contiene |
|---|---|
| `motor.py` | **la línea de defensa**: geometría del incendio, eje candidato, colocación (`FRACS`, doctrina fija 0,45), construcción de la línea por turnos (`tiempos_desde_el_medio`) y el **ataque directo** (`directo`). Es el puerto a Python de lo que hace la app. |
| `aereo.py` | **el aire**: flota real (litros y ciclo por aparato, del parte del MITECO), cobertura L/m² por combustible, calendario de descargas, mojado y apagado. |
| `mixto.py` | **aire + tierra juntos**: cómo se reparte el perímetro y cómo interactúan. |

Puntos de entrada: `motor.mejor_extincion()` (cota superior de lo que la extinción puede lograr),
`motor.directo()`, `motor.tiempos_desde_el_medio()`, `aereo.moja()`, `mixto.con_aire_y_tierra()`.

### `2_motor/` · el motor de propagación y la configuración · 142 KB
| fichero | qué contiene |
|---|---|
| `validate_block_a.py` | el motor: rejilla y combustible por celda (`Grid`), propagación por camino mínimo (`dijkstra`), intensidad de Byram (`intensidad`), reglas del agua, ciclo día/noche. |
| `e56_orden.py` | ⭐ **`aplica()` es la configuración de PRODUCCIÓN**: el valor real de cada mando. Léase antes que nada. |
| `e8_wind.py` | serie horaria de viento y humedad (ERA5). |
| `fire_sim_EXTRACTO_constantes.js` | **extracto** (líneas 1040-1700) del motor de la app, que es JavaScript: ahí están `RESOURCES`, `AIRCRAFT`, coberturas, umbrales de agua y las reglas de despliegue en pantalla. El fichero completo son 6.708 líneas / 376 KB: se puede pasar aparte si hace falta. |

⚠ **La extinción sólo usa esta API del motor**: `INF`, `intensidad()`, `USE_INTENSIDAD`, `I_MANUAL`/`I_MAQUINA`/
`I_AGUA_AEREA`, `dijkstra()`, `field_from()`, `water_mult()`, `WATER_*`, `ROS_MAX`, `MIN_ROS`. Si el contexto es
corto, con eso y `1_extincion/` se puede auditar el apagado sin leer el motor entero.

### `3_metodo/` · cómo se mide aquí · 27 KB
| fichero | qué contiene |
|---|---|
| `c183_ortega.py` | un experimento completo, con su **pre-registro escrito en la cabecera antes de correr**. |
| `c184_directo_ortega.py` | otro, el del ataque directo. |
| `auditoria_cola17.py` | un **juez**: los listones están escritos antes y no se tocan al ver los datos. |

Toda propuesta debe poder juzgarse así: pre-registro, ancla contra una corrida anterior, mitad ciega o cohorte que
no eligió nada, e IC por remuestreo sobre incendios.

### `PROMPT_VARIABLES.md`
El inventario de **todas** las variables (motor, apagado y medios) con valor, unidad, y si es **medido, calibrado o
supuesto**. Es el mejor mapa del sistema.

## LO QUE NO HAY QUE PROPONER (ya está medido y refutado)

Frenar la velocidad · buscar la parada en la meteorología · subincendios (`burn periods`) · barrera fina · anclar la
línea en carreteras · parada en escalones de vegetación · suelo de NDVI · invertir el signo del combustible · apagar
trozos del borde con criterios físicos · alargar la línea · línea permeable · cambiar dónde suelta el aire · elegir
la fracción de colocación con previsión real. Y el agua **ya decide por intensidad de Byram**, no por velocidad de
avance: `WATER_KILL_ROS` es código muerto.

## LO QUE SÍ FALTA, Y SE SABE

1. La cicatriz de satélite con la que se valida **lleva los bomberos dentro**: no hay registro público de medios por
   incendio, así que «dónde se para» mide «dónde lo pararon».
2. Una celda apagada **nunca reignita** y la línea **nunca falla**: no hay remate ni vigilancia.
3. Aire y tierra **no se hablan**: no hay efecto del apoyo aéreo sobre la producción de la cuadrilla.
4. Cada descarga se da por eficaz: no hay probabilidad de interacción ni de éxito.
