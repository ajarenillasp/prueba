# PROMPT · TODAS LAS VARIABLES DEL SIMULADOR, DEL APAGADO Y DE LOS MEDIOS

> **Qué es este fichero.** Un prompt listo para pegar en otra IA (o para leerlo a mano) con **todas** las
> variables que gobiernan el simulador de incendios: propagación, extinción y medios. Generado el
> **2026-09-17 leyendo el código**, no de memoria. Cada fila dice **valor · unidad · qué hace · de dónde sale**
> y, lo más importante, **si es un número MEDIDO o un SUPUESTO**.
>
> Ficheros de verdad (si algún valor de aquí no cuadra, manda el código):
> · motor de validación: `scripts/validacion/validate_block_a.py` · configuración de producción:
> `scripts/validacion/e56_orden.py::aplica()` · contención/línea: `contencion/motor.py` · aire:
> `contencion/aereo.py` · la app: `/mnt/qnap_web/greenhouse_3/js/fire_sim.js`.

---

## 0 · CONTEXTO PARA QUIEN LO ANALICE (pegar tal cual)

Estoy construyendo una herramienta **operativa para bomberos forestales**: simula un incendio real sobre datos
de satélite (NDVI/NDMI/LST/DEM/landcover, ERA5 horario) y **simula también la extinción** (líneas de defensa,
autobombas, maquinaria, helicópteros y aviones) para responder a decisiones de mando: a quién esperar, dónde
abrir la línea, qué se salva.

**Estado validado, con números propios (208 incendios reales del Mediterráneo, 2016-2025):**
- De **0 a 3 h el motor acierta**: área simulada/observada **0,96-1,02×**, rumbo con **5°** de error, solape
  de forma 0,471 (un círculo del mismo área da 0,400: toda la física vale +0,07).
- **A partir de ahí se pasa**: **2,1×** la cicatriz a 24 h y **4,8×** a 36 h.
- **La causa está medida y no es la propagación: es la extinción que falta.** La cicatriz de satélite es de
  un fuego **apagado por bomberos**, y el modelo simula fuego **libre**. La extinción explica el **89%** del exceso.
- **Lo que salvan los medios simulados es la mitad de lo real**: el simulador salva **32-44%** del área que
  ardería sin nadie; en España (INFOCA, 39 incendios >100 ha con partes reales) el valor medido es **67%**
  (sd 0,23, rango 0,20-0,99), con la **misma definición** (`1 − área_real/área_potencial_sin_extinción`).

**Lo que quiero de ti:** mirar las variables de abajo —sobre todo las de **extinción y medios**— y decirme
**qué está mal planteado, qué valor no se sostiene contra la literatura, y qué cambio concreto cerraría el
hueco del 32-44% al 67%**, sabiendo que el hueco NO está en la propagación.

**Reglas que te pido:**
1. **Cita la fuente primaria** (autor, año, publicación) de cada número que propongas. Si no la tienes, di
   «no lo sé». Un resumen no vale como fuente: ya nos coló una fórmula inventada una vez.
2. **No propongas nada que ya esté en la lista de §5 («lo que ya se probó y NO funciona»).**
3. Distingue siempre **lo que es física** de **lo que es doctrina operativa** (cómo se despliega la gente).
4. Si un valor te parece razonable, dilo también: saber qué NO tocar vale tanto como lo otro.

---

## 1 · EL MOTOR DE PROPAGACIÓN · qué gobierna la velocidad y la forma del fuego

Modelo: propagación tipo Huygens/Dijkstra sobre rejilla, celda **80 m** (validado 38-162 m), vecindad de 16,
elipse con cabeza/flancos/cola. Paso de tiempo implícito (tiempo de llegada por celda). Horizonte típico 48 h.

| variable | valor | unidad | qué hace | origen |
|---|---|---|---|---|
| `ROS_MAX` | **20,5** | m/min | velocidad base en condiciones extremas; escala todo | **CALIBRADO** (28 → 20,5 el 14-sep al corregir la temperatura de suelo a la de día) |
| `MIN_ROS` | 0,05 | m/min | por debajo, no hay nada que arda | calibrado |
| `SPREAD_MIN` | 0,60 | m/min | mínimo para que la celda PRENDA | supuesto |
| `WIND_A` / `WIND_B` | 0,60 / 1,5 | — | cabeza = 1 + A·(U/10)^B (forma de Rothermel) | **CALIBRADO** contra 11 cicatrices reales |
| `HEAD_MAX` | 12,0 | × | tope del multiplicador de cabeza | supuesto |
| `LB_MAX` | 2,5 | — | largo/ancho máximo de la elipse | calibrado (1,5 → 2,5 el 13-ago) |
| `FLANK_MIN` | 0,05 | fracción | suelo de propagación lateral (la cola avanza al 5% de la cabeza) | supuesto |
| `SLOPE_WIND_K` | 45,0 | km/h por (rise/run) | convierte pendiente en viento equivalente (30% ≈ 13 km/h) | supuesto con forma física |
| `SLOPE_QUAD` | True | — | efecto cuadrático de la pendiente | — |
| `USE_WIND_CONF` · `WIND_CONF_WINDOW_H` · `WIND_CONF_GAMMA` · `WIND_CONF_MIN_SPD` | True · 3 · 2,0 · 3,0 | — · h · — · km/h | descuenta el viento cuando la serie horaria es inconsistente | propio |
| `TPI_SCALE` · `TERR_SPEED` · `TERR_CHAN` | 40 · 0,45 · 0,75 | m · fracción · fracción | el relieve acelera en cresta, frena en vaguada y encauza el viento | supuesto (sólo en la app) |
| `CURE_BASE` | 0,35 | — | cuánto arde lo que sigue verde | calibrado |
| `PEAK_LO` / `PEAK_HI` | 0,15 / 0,60 | NDVI | verdor máximo anual → carga de combustible 0..1 | supuesto |
| `FLAM_MIN` | 0,02 | — | inflamabilidad mínima (combustible × sequedad) para arder | calibrado 6-ago |
| `LC_ROS` | arbolado 1,00 · matorral 0,85 · pasto 1,00 · cultivo 0,55 | × | tipo de terreno → velocidad (**APAGADO**: `USE_LCROS=False`) | supuesto |
| `LC_POW` · `USE_LANDCOVER` | 1,0 · True | — | el tipo de terreno multiplica el combustible | — |
| `BARRIER_MIN` | 0,50 | fracción | urbano/roca/agua por encima de esto → NO arde | supuesto |
| `NDWI_WATER` | 0,20 | NDWI | por encima, agua (barrera natural) | supuesto |
| `USE_INTENSIDAD` · `HPUA_MAX` · `HPUA_MIN` | True · 750 · 40 | — · Btu/ft² · Btu/ft² | calor por unidad de área con combustible = 1 (modelo 3, pasto alto) → intensidad de Byram | **literatura** (Anderson/Rothermel) |
| `CHAIN_M` · `BTU_KW` | 20,1168 · 3,4614 | m · kW/m por Btu/ft/s | conversiones | exacto |
| ciclo día/noche `AMP_DIURNA` · `HUM_S` · `FASE_H` · `NOCHE_K` | 1,0 · 1,0 · 3,0 · 1,0 | × · × · h · × | coseno diurno (mínimo a las 3 h) + humedad relativa horaria | **supuesto, y es el punto débil conocido** |
| ciclo alternativo `CICLO_HUM` · `HUM_MX` · `HUM_K` · `HUM_TAU_H` | **0 (apagado)** · 0,30 · 1,0 · 1,0 | — | ciclo desde la humedad del combustible fino (ηM de Rothermel) en vez del coseno | probado 15-17 sep y **DESCARTADO** (ver §5) |
| `FFM_EXT` | 0,30 | fracción | humedad de extinción del combustible fino | literatura |
| freno por edad `USE_AGE_BRAKE` · `AGE_T0_H` · `AGE_TAU_H` · `AGE_FLOOR` | **False** · 6,0 · 12,0 · 0,05 | — · h · h · × | el fuego se frena con la edad | probado y **descartado** |
| pavesas `USE_SPOTTING` · `SPOT_*` | **False** · dist 400 m a 20 km/h · cono 10° · retardo 2 min · p 0,006/0,02/0,06 · máx 400 focos | — | saltos de fuego | probado y **no aporta** |
| sorteo de ignición `USE_P_IGN` · `P_IGN_POW` · `P_IGN_M` · `P_IGN_FORMA` | **False** · 0,15 · 1750 m · 'organico' | — | textura/parcheado de lo quemado (islas) | en la app sí, `P_IGN_MODO='no'` por defecto |
| ensemble `ENS_SEED` · `ENS_DRY` · `ENS_ROS` · `ENS_PLAN` | 20260805 · 0,28 · 2,3 · 6 | — · 1σ · × / ÷ · miembros | abanico de escenarios (incertidumbre de sequedad y velocidad) | supuesto |
| rejilla `CELDA_OBJETIVO` · `CELDA_MIN`-`CELDA_MAX` · `GRID_MAX` | 80 · 38-162 · 512 | m · m · celdas | resolución | validado |
| `SIM_HORAS_DEF` · `HOR` (banco) | 48 · 48 | h | horizonte de simulación | — |

---

## 2 · EL APAGADO · cómo se construye y qué detiene al fuego

Dos vías: **ataque directo** (se ataca el borde si avanza despacio) y **línea indirecta** (se abre una línea
por delante, anclada, y el fuego se detiene al llegar). Más agua (terrestre y aérea).

| variable | valor | unidad | qué hace | origen |
|---|---|---|---|---|
| `T0` | **60** | min | tiempo hasta que los medios están trabajando (banco de validación) | supuesto |
| `PASO` | 90 | min | duración de un paso de contención | supuesto |
| `HOR` | 48 × 60 | min | horizonte del ejercicio de extinción | — |
| `OPS_WINDOW` | 12 × 60 | min | ventana operativa (un relevo) | doctrina |
| `DIRECT` (banco) / `DIRECT_HARD` (app) | **8** / **15** | m/min | avance de borde por encima del cual **no cabe ataque directo** | doctrina · ⚠ **los dos números no son el mismo** |
| `FRACS` | 0,15 · 0,25 · 0,35 · **0,45** · 0,55 · 0,65 · 0,75 · 0,85 · 0,95 | fracción | dónde se pone la línea indirecta entre el fuego y el borde del alcance previsto. **0,45 es la doctrina fija desplegada** | **MEDIDO** (óptimo interior sobre 208 incendios; y elegirla con previsión real NO mejora a la fija) |
| `ROTS` | 0 | grados | rotación del eje de la línea | medido: rotar no paga |
| `SEG_USEFUL` | 300 | m | longitud mínima para que un tramo de línea cuente | supuesto |
| `RUN_MIN` | 3 | celdas | tramo mínimo de perímetro que cuenta | supuesto |
| `TEAMS_MAX` | 3 | equipos | medidas de tierra simultáneas en la app | límite de interfaz |
| `SHIFT_MIN` | 12 × 60 | min | relevo | doctrina |
| **umbrales de intensidad** `I_MANUAL` · `I_MAQUINA` · `I_INEFECTIVO` | **346** · **1.731** · **3.461** | kW/m | qué medio puede atacar: manual hasta 346; maquinaria **y aviones** hasta 1.731; por encima de 3.461 el control en cabeza es inefectivo | **literatura** (bandas de Byram/NWCG). ⚠ La correspondencia medio↔banda es **supuesto declarado** |
| `I_AGUA_AEREA` | = `I_MAQUINA` (1.731) | kW/m | hasta aquí una descarga deja línea permanente | supuesto |
| agua `WATER_KILL_ROS` · `WATER_ASSIST` | **9** · **26** | m/min | ⛔⛔ **CORREGIDO 17-sep: son CÓDIGO MUERTO en producción.** Con `USE_INTENSIDAD = True` (que es producción) el agua aérea decide por **intensidad de Byram ≤ `I_AGUA_AEREA` = 1.731 kW/m**, no por velocidad de avance. En el JS el propio comentario dice «umbral VIEJO, sólo para el aviso de la ficha». ⇒ **la pregunta 3 de §6 ya está contestada dentro del modelo** | supuesto muerto |
| `WATER_FACTOR` · `WATER_HOLD` · `WATER_FADE` | 0,04 · 25 · 35 | × · min · min | mientras está mojado la velocidad cae al 4%; aguanta 25 min y se seca en 35 más | supuesto |
| manguera `HOSE` | alcance 250 · 2,5 m/min · 90 min | m · m/min · min | tendido desde punto accesible | supuesto |
| `USE_EXTINCTION` (en el motor de propagación) | **False** | — | el motor **no se autoapaga**: toda la extinción es explícita | decisión de diseño |

---

## 3 · LOS MEDIOS · lo que más me interesa que mires

### 3.1 · Tierra

| medio | producción de línea | llegada | ataque directo hasta | dónde |
|---|---|---|---|---|
| cuadrilla manual 👷 | **120 m/h** (app) · **324 m/h** (banco de validación) | **90 min** (app) · 45 min (tabla del banco) · **60 min** (`T0`, que es lo que usan los experimentos) | 5 m/min | `RESOURCES` |
| autobomba / tractor 🚒 | 400 m/h | 90 min (app) · 30 min (tabla) | 8 m/min | `RESOURCES` |
| maquinaria pesada 🚜 | 1.200 m/h | 210 min (app) · 90 min (tabla) | 15 m/min | `RESOURCES` |
| helicóptero (línea húmeda) 🚁 | 700 m/h | 300 min (app) · 20 min (tabla) | 12 m/min | `RESOURCES` |

⚠⚠ **Tres avisos que hay que leer juntos:**
1. **La producción de línea NO depende de nada**: ni del modelo de combustible, ni de la pendiente, ni de si
   la línea es directa o indirecta. Es un número plano por medio. La pendiente y el combustible **ya están en
   cada celda del mapa**, así que no es falta de dato.
2. Contra la referencia publicada (**NWCG Fireline Production Rate Tables, 2021**): una cuadrilla Tipo I de 20
   personas hace **342 m/h en pasto corto** pero **133 m/h en chaparral**; un bulldozer hace 1.106-1.811 m/h
   en pendiente suave y **0-161 m/h con pendiente 56-74%**. O sea: nuestros números son **de pasto y llano**.
3. **El banco y la app no usan la misma cuadrilla** (324 vs 120 m/h) ni la misma llegada. Todo lo medido con
   324 hay que releerlo antes de enseñarlo en pantalla.

### 3.2 · Aire

| aparato | litros por descarga | ciclo (min) | notas |
|---|---|---|---|
| FOCA (anfibio tipo 1) | 5.500 | 20 | los **litros salen del parte real del MITECO**: son dato |
| ALFA (anfibio tipo 2) | 3.100 | 18 | |
| TANGO (carga en tierra) | 3.100 | 40 | recarga en aeródromo |
| KILO (helicóptero tipo 1) | 4.500 | 12 | |
| MIKE (helicóptero tipo 2) | 2.500 | 10 | |
| LIMA (helicóptero tipo 3) | 1.000 | 8 | |
| BRIF-A / BRIF-B | 2.400 / 1.200 | 15 | brigadas helitransportadas |
| sin capacidad de descarga | — | — | ACO, UMAP, BRIF en disponibilidad |

En la app el catálogo es más simple: `heli` 1.500 L a 220 km/h, giro 2,5 min · `plane` 5.000 L a 270 km/h,
giro 4,0 min. La **huella** de cada descarga se deriva de `área = volumen / cobertura`, no al revés.

| variable | valor | unidad | qué hace | origen |
|---|---|---|---|---|
| `COBERTURA_PASTO` | **0,3** | L/m² | cobertura eficaz en pasto | **literatura leída en primaria**: George et al. 1990 (media 0,5, rango 0,3-0,8, llamas ≤2 m ≈ 2.000 kW/m) |
| `COBERTURA_ARBOL` | **1,5** | L/m² | cobertura eficaz en arbolado denso | Loane & Gould 1986, vía Plucinski et al. 2007 (Bushfire CRC), p.18 |
| `COBERTURA_REF_F` | 0,5 | índice | combustible de referencia para la GEOMETRÍA del aparato | supuesto |
| interpolación | lineal con el índice de combustible de la celda | — | ⚠ **la fuente dice que la cobertura necesaria sube también con la INTENSIDAD del fuego; aquí sólo depende del combustible. Simplificación declarada** | |
| `T_LLEGADA` (aire, banco) · `T_AIR` (app) | 90 · **300** | min | primera descarga | supuesto · ⚠ tampoco coinciden |
| `PASO` (aire) | 15 | min | ciclo de decisión del aire | supuesto |
| `AIR_DAY` · `MARGEN_SOL` | 7-21 h · 30 min | — | no se vuela de noche, ni al filo del orto/ocaso | doctrina |
| `DOCTRINAS_AEREAS` · `PRIORIDAD` | cabeza · flancos · apoyo · linea → **'cabeza'** | — | dónde suelta el aire | medido: **da igual dónde suelte** |
| mandos de usuario en la app | recurso · respuesta 0-240 min (def. 90) · respuesta aérea 15-360 min (def. 300) · nº aeronaves 1-8 · ciclo 4-90 min · doctrina · vuelo nocturno | — | lo que el bombero puede cambiar en pantalla | — |

---

## 4 · REGLAS OPERATIVAS YA MEDIDAS (no son variables: son salidas)

- **Esperar al doble de fuerza compensa** hasta ~60 min de retraso (frontera 75 · 60 · 60 · 30 min para
  llegadas de 15 · 30 · 60 · 90 min), medido en 207 incendios.
- **La línea se pone a 0,45** del recorrido previsto; buscarla incendio a incendio con la previsión real no
  compra nada (y a veces cuesta). El margen que existe **vive de conocer el futuro**.
- **Con la cuadrilla de la app (120 m/h) más fuerza sigue comprando**: salvado 1,5 · 7,4 · 19,4 · 37,6 · 41,1%
  con 4 · 8 · 16 · 32 · 64 cuadrillas. Con cuadrillas de 324 m/h saturaba en 32.
- **El aire aporta ~+30-38 ha de media** sobre la tierra, y **el orden por aportación es el orden por litros**:
  es el agua, no el aparato. Volar de noche valdría +0,4-0,6 puntos.
- **Una línea permeable (que sólo frene) pierde siempre** frente a una línea que corta.

---

## 5 · LO QUE YA SE PROBÓ Y **NO** FUNCIONA (no lo propongas)

Sobre el «que el fuego se pare solo»: frenar la velocidad · buscarlo en la meteorología · frenar tarde ·
lienzo mayor · subincendios (`burn periods`, 3 veces) · barrera fina · anclar la línea en carreteras · parada
en escalones de vegetación · suelo de NDVI · invertir el signo del combustible · 50 formas del combustible ·
apagar trozos del borde con cinco criterios físicos (ninguno le gana a apagar un tramo al azar) · corregir la
temperatura de suelo · el ciclo día/noche desde la humedad del combustible (`c178`: arreglaba la madrugada a
0-3 h pero a 7-12 h empeoraba, 3,16× → 3,93×, en incendios nuevos).

Sobre los medios: alargar la línea (+0,00) · anclarla en vías (+0,00) · línea permeable (pierde siempre) ·
elegir la fracción con previsión (no retiene nada) · cambiar dónde suelta el aire (da igual).

---

## 6 · LAS PREGUNTAS, EN ORDEN DE LO QUE ME IMPORTA

1. **¿Qué le falta a este modelo de extinción para pasar de salvar el 32-44% a algo cercano al 67% real?**
   Lo que sabemos: no es la colocación de la línea (medido), no es la cantidad de medios (satura o casi), no
   es dónde suelta el aire. ¿Qué queda?
2. **La producción de línea plana (120/400/1.200/700 m/h) contra las tablas NWCG por combustible y pendiente:
   ¿cuál es la forma funcional correcta?** Dame la tabla o la ecuación con su fuente. La pendiente y el
   combustible ya están en cada celda.
3. **¿Está bien la regla «el agua apaga por debajo de 9 m/min de avance y sólo ayuda hasta 26»?** ¿Hay
   literatura que ligue eficacia del agua con intensidad de Byram en vez de con velocidad de avance?
4. **La cobertura eficaz debería subir con la intensidad** (lo dice nuestra propia fuente) y aquí sólo sube
   con el combustible. ¿Con qué ley?
5. **Los tiempos**: ¿son razonables 60-90 min hasta que la tierra trabaja y 300 min para el aire, para España?
   ¿Hay estadística publicada de tiempos de respuesta por tipo de medio?
6. **¿Qué variable de esta lista sobra**, o es tan inestable que no debería existir como mando?

**Formato de respuesta que quiero:** una tabla `variable → qué está mal → valor o ley propuesta → fuente
primaria → cómo lo comprobarías con 208 incendios y cicatrices de satélite`. Sin rodeos y sin relleno.
