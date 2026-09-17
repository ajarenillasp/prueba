  // La velocidad de fuego libre se estimará con los incendios REMOTOS, donde casi
  // no hubo medios (e49_supresion.py). Hasta entonces se queda el valor anterior.
  // ⛔ 2026-09-14 · 28 → 20,5 · RECALIBRADO CON LA TEMPERATURA DEL SUELO DE DÍA (INCENDIOS.md §159-§161).
  // La capa `lst` era la pasada NOCTURNA de Sentinel-3 (sequedad ≈0); con la de día la facilidad de ignición
  // sube ~37% y el fuego salía ~19% mayor. 28 estaba calibrado CON el dato malo: 20,5 (≈ 28/1,37) devuelve el
  // tamaño validado de las 3 primeras horas (0,983× en mitad ciega, misma forma, `c164`). Va a la vez que
  // `validate_block_a.py:22` y `e56_orden.aplica()` (paridad, §93.1) y que `extract_snapshot.py` pidiendo
  // sólo la órbita de día. ⚠ Con una captura VIEJA (LST de noche) este valor quema ~27% menos: se recapturan.
  const ROS_MAX     = 20.5;   // m/min de avance base en condiciones extremas
  const WIND_K      = 0.030;  // (sin uso desde 2026-08-06: sustituido por la ley de potencia)
  const WIND_A      = 0.60;   // cabeza = 1 + A·(U/10)^B  — forma de Rothermel
  const WIND_B      = 1.5;    // calibrado contra 11 cicatrices reales
  const HEAD_MAX    = 12.0;   // multiplicador máximo de la cabeza del fuego
  const SLOPE_WIND_K = 45.0;  // pendiente (rise/run) → viento equivalente (km/h). 30% ≈ 13 km/h
  const LB_MAX      = 2.5;    // largo/ancho de la elipse. 2026-08-13 (antes 1,5;
                              // y 2,0 y 3,0 y 5,0 antes que eso).
                              // ESTE VALOR NO SALE DE OPTIMIZAR UNA MÉTRICA INTERNA,
                              // que es lo que hizo bailar el parámetro cuatro veces.
                              // Sale de dos medidas independientes que coinciden:
                              //  1 · `c03` barrió OCHO valores (1,5 a 14) contra los
                              //    208 incendios reales: el Dice —cuánto de lo que
                              //    ardió de verdad acierta— tiene un máximo INTERIOR
                              //    en 2,5 (0,4747 frente a 0,4558 de 1,5). No es un
                              //    borde de rejilla: sube hasta 2,5 y baja después,
                              //    hasta hundirse en 0,3547 con LB=14.
                              //  2 · `e58` mide que el rumbo del modelo falla 33° en
                              //    los incendios alargados (72° en todos). Con esa
                              //    incertidumbre de dirección, 2,5 es más o menos el
                              //    alargamiento que se puede justificar: estirar más
                              //    es meter el fuego con fuerza donde no va.
                              // Coste conocido y aceptado: la métrica del ORDEN baja
                              // (0,713 → 0,663). Esa métrica guió las tres bajadas
                              // anteriores de LB_MAX y las tres empeoraron la forma
                              // real, así que aquí NO decide.
                              // Lo que este cambio NO arregla: la forma sigue en 1,28
                              // frente a 1,62 observado, y el ancho en 1,91x. El techo
                              // de lo alcanzable tocando LB_MAX es 1,48 (medido), y no
                              // se llega porque el modelo no sabe la dirección.
                              // Ver contencion/PROYECTO.md y c03_result_lb_extendido.json.
  // CONFIANZA DEL VIENTO (2026-08-11, `f21_viento_confianza.py`). Idea del usuario:
  // en vez de estirar la elipse igual siempre, estirarla a tope sólo cuando el
  // reanálisis horario ha apuntado varias horas seguidas en direcciones parecidas,
  // y quedarse casi isótropo cuando da bandazos entre horas — ataca la causa que
  // e58_rumbo.py/e59_forma.py encontraron (el modelo estira el doble de lo real
  // porque un viento de ~30 km no siempre conoce bien la dirección).
  // Confirmado fuera de muestra (105 incendios de prueba): orden 0,8750→0,8768,
  // gana en 46/64 (72%, p=0,0003), Dice sin cambio (0,4735→0,4741).
  // OJO, matiz honesto (medido con f22_circulo_conf.py sobre 210 incendios): mejora
  // sobre el LB_MAX fijo pero NO cambia cuántas veces le gana al círculo honesto
  // (se queda en 4/130 = 3%, igual que sin esto). Es una mejora real y sin coste,
  // pero pequeña frente al problema de fondo — no lo resuelve.
  const USE_WIND_CONF = true;
  const WIND_CONF_WINDOW_H = 3;   // horas a cada lado para juzgar consistencia
  const WIND_CONF_GAMMA = 2.0;    // >1 castiga más la inconsistencia
  const WIND_CONF_MIN_SPD = 3.0;  // km/h por debajo de los cuales la dirección no es fiable
  function windConfidenceSeries(prof) {
    // Por hora, R∈[0,1]: consistencia circular del viento en una ventana de horas
    // alrededor (mismo cálculo que wind_confidence_series() en validate_block_a.py).
    const n = prof.length, conf = new Array(n).fill(1);
    for (let h = 0; h < n; h++) {
      const lo = Math.max(0, h - WIND_CONF_WINDOW_H), hi = Math.min(n - 1, h + WIND_CONF_WINDOW_H);
      let vx = 0, vy = 0, cnt = 0;
      for (let k = lo; k <= hi; k++) {
        const ws = prof[k][0], wd = prof[k][1];
        if (ws < WIND_CONF_MIN_SPD) continue;
        const a = wd * Math.PI / 180;
        vx += Math.sin(a); vy += Math.cos(a); cnt++;
      }
      conf[h] = cnt >= 2 ? Math.hypot(vx, vy) / cnt : 1;
    }
    return conf;
  }
  const FLANK_MIN   = 0.05;   // suelo de propagación lateral. La cola avanza al 5% de
                              // la cabeza, que es lo que hace un incendio de viento real
                              // (sin esto, los lados casi se extinguen y tardan días en rellenar)
  /* ── CRONOLOGÍA REAL DE LA RESPUESTA ───────────────────────────────────────
     Contada por el usuario el 2026-08-12, y corrige de raíz lo que había:
       t=0      arranca el fuego; alguien lo ve y llama al 112
       1-2 h    llegan los primeros bomberos y atacan el PERÍMETRO como pueden
       2-4 h    si es grande se escala: grupo de extinción, más coches y personal
       4-6 h    si NO se controla se piden refuerzos, y entonces entran los
                medios aéreos — no antes
     Lo que había suponía bomberos a los 45 min y helicóptero a los 20, como si
     estuviera esperando en pista. Con eso el asesor planificaba una respuesta que
     no existe, y además medía el agua desde puntos a 10-24 km del fuego. */
  const T_GROUND_1 = 90;        // min · primer ataque de tierra (1-2 h)
  const T_GROUND_2 = 210;       // min · refuerzo terrestre tras escalar
  const T_AIR      = 300;       // min · llegan los medios aéreos (4-6 h)
  // Más allá de esto ya no es esta intervención, es la guardia siguiente: una
  // medida cuyo fuego llega después NO es un plan, es un dibujo. Es lo que metía
  // cortafuegos a 24 km donde el fuego llegaba en la hora 104.
  const OPS_WINDOW = 12 * 60;   // min

  const MIN_ROS     = 0.05;   // combustible por debajo → no hay nada que arda
  const SPREAD_MIN  = 0.60;   // m/min mínimos para que el fuego PRENDA en la celda
                              // (si viento/pendiente/humedad lo dejan más lento → se apaga)
  /* ── QUÉ HACE EL AGUA (rehecho el 2026-08-12) ──────────────────────────────
     Antes el agua SÓLO multiplicaba la velocidad por 0,04 mientras duraba el
     mojado, y `waterMult()` nunca devolvía 0: toda celda mojada acababa ardiendo.
     No existía el estado "apagado". Medido: mojar 41 celdas (26 ha) por delante
     de la cabeza salvaba 0,0 ha y retrasaba el frente 0,02 min.
     Lo que ocurre de verdad depende de la INTENSIDAD del tramo:
       · borde de baja intensidad → la manguera o la autobomba APAGAN, y con la
         liquidación queda apagado. Así se apagan los incendios.
       · cabeza en carrera → la descarga aérea NO la apaga; baja la intensidad
         para que la gente de tierra pueda entrar. */
  // ── Intensidad lineal del frente (Andrews & Rothermel 1982, INT-GTR-131) ────
  // Portado de `validate_block_a.py:324-345` el 2026-08-20. La doctrina de
  // extinción no decide por VELOCIDAD sino por INTENSIDAD, y la traducción entre
  // las dos depende del combustible: los mismos 9 m/min son 1.265 kW/m en
  // combustible pleno (donde no se sostiene nada) y 46 m/min de margen en una
  // celda casi pelada. Con el umbral único de velocidad, medido en `a32` sobre
  // 71.531 celdas de perímetro, en 11 de los 13 modelos de combustible se mandaba
  // gente a fuego que no puede atacar Y se le negaba al avión el 100% de la banda
  // donde la doctrina dice que sirve (346-1.731 kW/m, el 19-38% del perímetro).
  const CHAIN_M = 20.1168;    // 1 chain, en metros
  const BTU_KW  = 3.4614;     // 1 Btu/ft/s = 3,4614 kW/m
  const HPUA_MAX = 750;       // Btu/ft2 con combustible = 1 (modelo 3, pasto alto)
  const HPUA_MIN = 40;        // suelo, para que una celda casi pelada no dé 0
  const I_MANUAL = 346;       // <=346 kW/m · la herramienta manual sostiene el frente
  const I_MAQUINA = 1731;     // 346-1731 · manual NO en cabeza; maquinaria y AVIONES sí
  function hpua(f) { return Math.max(HPUA_MIN, HPUA_MAX * Math.max(0, f)); }
  function intensidad(rosMMin, f) {
    if (!(rosMMin > 0)) return 0;
    return hpua(f) * (rosMMin * 60 / CHAIN_M) / 55 * BTU_KW;
  }

  const WATER_KILL_ROS = 9;   // m/min · umbral VIEJO, sólo para el aviso de la ficha
  const WATER_ASSIST   = 26;  // m/min · hasta aquí el agua sirve de apoyo
  const WATER_FACTOR = 0.04;  // el agua reduce muchísimo la velocidad… mientras está mojado
  const WATER_HOLD  = 25;     // min que aguanta mojada una descarga aérea
  const WATER_FADE  = 35;     // min más hasta secarse del todo (el efecto se pierde gradualmente)

  // ── Medios de agua (bloque C) ───────────────────────────────────────────────
  // Aéreos: cada pasada moja una mancha pequeña y hay que volver a por agua. El
  // ciclo se calcula con la distancia real al punto de agua más cercano.
  // `resp`  = minutos hasta que el aparato está sobre el incendio. NO es el del
  //           equipo de tierra: un helicóptero no espera a la cuadrilla, y usar
  //           el `resp` de tierra era la causa nº1 del "no da tiempo" del asesor.
  // `nowater`= km de trayecto que se suponen si NDWI no ve agua en la zona. El
  //           helicóptero carga de balsas, piscinas y pozas que a 100 m de
  //           resolución no se ven, así que penalizarlo igual que al avión era
  //           descartarlo por un límite del satélite, no por la realidad. El
  //           avión sí necesita una lámina de agua grande o una pista.
  const AIRCRAFT = {
    // kmh: 120 era la velocidad de un helicóptero pesado cargado, no la de crucero.
    // Un medio de extinción medio va a 200-250, y con el 120 el ciclo de recarga
    // salía casi el doble de lo real, lo que hacía descartar el agua aérea por
    // "no da tiempo" cuando sí daba.
    heli:  { icon: '🚁', wm: 30, lm: 90,  kmh: 220, turn: 2.5, vol: 1500, resp: T_AIR,     nowater: 4 },
    plane: { icon: '✈️', wm: 45, lm: 220, kmh: 270, turn: 4.0, vol: 5000, resp: T_AIR + 30, nowater: 12 }
  };
  // La huella se deriva de la COBERTURA, no al revés. El heli mojaba 90 × 30 m
  // con 1500 L = 0,56 L/m², y el avión 0,51: por debajo del mínimo eficaz hasta
  // en pasto (~1 L/m²; matorral y arbolado piden 2-4). Se repartía la misma agua
  // sobre 2-3 veces más terreno del que puede mojar, así que ninguna descarga
  // mojaba de verdad. Ahora área = volumen / cobertura, con proporción 3:1.
  /* ⭐ 2026-08-25 · LA COBERTURA DEPENDE DEL COMBUSTIBLE, y un solo número era falso
     en los dos extremos. Fuente leída de primera mano: Plucinski et al. 2007 (Bushfire
     CRC), p.18, citando a Loane & Gould 1986 y George et al. 1990:
       · «<0,5 L/m² para pasto, >1,5 L/m² para bosque de eucalipto»
       · George et al. 1990 (estudio operativo en EEUU): media eficaz 0,5 L/m²
         (rango 0,3-0,8) para llamas ≤2 m, ~2.000 kW/m — que es EXACTAMENTE el régimen
         donde este modelo deja atacar con agua aérea (`I_AGUA_AEREA` = 1.731 kW/m).
     Tener 1,5 FIJO era poner el valor del arbolado denso también sobre el pasto, y como
     la huella sale de `área = volumen / cobertura`, eso ENCOGÍA el avión justo donde más
     suelo debería mojar. Idéntico a `aereo.cobertura_de()`; lo vigila `paridad_reglas`.
     ⚠ La fuente dice además que la cobertura necesaria SUBE con la intensidad del
     fuego; aquí sólo depende del combustible. Simplificación DECLARADA. */
  // Una por línea: `paridad.py` sólo reconoce `const NOMBRE = número;` y con las dos
  // juntas no las veía — o sea que la guarda existía y estaba ciega.
  const COBERTURA_PASTO = 0.3;   // L/m² · pasto, mínimo eficaz (George et al. 1990)
  const COBERTURA_ARBOL = 1.5;   // L/m² · eucalipto/arbolado (Loane & Gould 1986)
  const COBERTURA_REF_F = 0.5;   // combustible de referencia para la GEOMETRÍA del avión
  function coberturaDe(f) {
    const x = (f == null) ? 0 : (f < 0 ? 0 : (f > 1 ? 1 : f));
    return COBERTURA_PASTO + (COBERTURA_ARBOL - COBERTURA_PASTO) * x;
  }
  // La huella del aparato es GEOMETRÍA y se calcula una vez, antes de que exista
  // rejilla: se usa el combustible de referencia. El efecto por descarga sí va con el
  // combustible de la celda donde cae (más abajo, `a.cpd`).
  const WATER_COVERAGE = coberturaDe(COBERTURA_REF_F);
  for (const A of Object.values(AIRCRAFT)) {
    A.wm = Math.round(Math.sqrt((A.vol / WATER_COVERAGE) / 3));
    A.lm = Math.round(3 * A.wm);
  }
  const AIR_DAY = [7, 21];    // los medios aéreos no vuelan de noche
  // Combustible: carga (verdor máximo) × curado (verdor perdido desde entonces)
  const PEAK_LO = 0.15, PEAK_HI = 0.60;   // verdor máximo → carga 0..1
  const CURE_BASE = 0.35;                 // cuánto arde lo que sigue verde
  const AIR_APPROACH = 6;     // min que se ve al aparato llegando antes de soltar
  const AIR_LEAVE = 4;        // min que sigue a la vista después de soltar
  // Manguera: llega hasta donde da el tendido desde un punto accesible, avanza
  // despacio y mantiene mojado mientras el equipo sigue allí.
  const HOSE = { icon: '🚒', reach: 250, rate: 2.5, soak: 90 };   // m de alcance, m/min, min mojando

  // ── D1 · Pavesas (focos secundarios por brasas) ────────────────────────────
  const SPOT_MIN_SPD  = 6;      // m/min de avance mínimos para que salten brasas
  const SPOT_MIN_WIND = 15;     // km/h equivalentes mínimos (viento + pendiente)
  const SPOT_DIST_K   = 14;     // m de salto por km/h de viento (30 km/h ≈ 420 m)
  const SPOT_DIST_MIN = 60;     // por debajo de esto no es un salto, es avance normal
  const SPOT_SPREAD   = 0.35;   // dispersión lateral del abanico de pavesas
  const SPOT_DELAY    = 2;      // min entre que sale la brasa y prende el foco
  const SPOT_TRIES    = 3;      // intentos de salto por celda del frente
  const SPOT_MAX      = 400;    // tope de focos secundarios (evita explosión)
  const SPOT_LEVEL    = { low: 0.006, med: 0.02, high: 0.06 };   // propensión
  const BRUSH       = 1;      // radio del "pincel" al pintar (1 = 3×3)
  // Calibrado el 2026-08-06 contra 14 incendios reales (mitad de ajuste / mitad de
  // prueba). El 0.20 anterior estaba atado a la escala del combustible ANTIGUO:
  // con carga×curado dejaba el 98% del monte sin arder.
  const FLAM_MIN    = 0.02;   // inflamabilidad (combustible·sequedad) mínima para arder
                              // → zonas ralas/verdes quedan como islas sin quemar
  const NDWI_WATER  = 0.20;   // NDWI por encima → agua (barrera natural)
  // Si más de esta fracción de la celda es urbano, roca o agua, no arde: es barrera.
  // Con 0.5 una carretera estrecha sólo frena (multiplicador), pero un pueblo o un
  // roquedo cortan de verdad, que es lo que hacen en la realidad.
  const BARRIER_MIN = 0.50;
  // 2026-08-24 · con esto la barrera actúa por PROBABILIDAD en vez de por umbral
  // al 50%. `BARRIER_MIN` sólo se usa con esto apagado. Ver `buildGrid()`.
  const BARRERA_PROB = true;
  // HORIZONTE de la simulación = hasta donde llegan los datos, no un tope arbitrario.
  // El fuego simulado no se paraba nunca y acababa comiéndose el AOI entero. Se buscó
  // la causa FÍSICA (humedad de extinción: de madrugada el combustible fino pasa del
  // 25% de humedad y deja de propagar) y se midió: hace que el fuego se pare, sí,
  // pero EMPEORA el parecido con las cicatrices reales por debajo de un círculo. Y el
  // dato que lo refuta: el 40% de las detecciones de fuego activo de 14 incendios
  // reales son de MADRUGADA. Ardían de noche. Lo que paró esos incendios fue la
  // extinción humana, y eso no se modela.
  // Por eso el horizonte no es "el fuego se apaga", es "hasta aquí sabemos": tenemos
  // meteorología horaria para 48 h y no modelamos la intervención de los bomberos.
  // Más allá, la simulación sería inventar.
  // 2026-08-21 · EL HORIZONTE DEJA DE SER UNA CONSTANTE.
  // Era `48 * 60` porque la captura pedía a ERA5 la fecha objetivo y un día más.
  // Comprobado contra la API el 21-ago: es el ARCHIVO de ERA5, y devuelve tantos
  // días como se le pidan mientras `end_date` no pase de HOY (mañana da HTTP 400).
  // Así que la duración la elige el usuario y el horizonte sale de DOS cosas:
  //   1) lo que el usuario pidió  ·  2) las horas de viento que trajo la captura.
  // Manda el menor de los dos, y la pestaña dice cuál mandó — si pides 30 días y
  // la captura sólo trajo 3, no se simulan 30 y se calla.
  // ⚠ LÍMITE QUE NO SE ARREGLA CON DATOS, y va escrito aquí para que no se olvide:
  // el modelo sólo está validado entre 0 y 36 h (`c43`, n=208). Más allá es
  // extrapolación pura, y como apenas decelera con la edad (-15% frente al -88%
  // real) las superficies a varios días son físicamente imposibles. La duración
  // larga es un instrumento para VER ese defecto, no una predicción.
  const SIM_HORAS_DEF = 48;               // por defecto, lo de siempre
  const SIM_HORAS_MAX = 31 * 24;          // tope duro (el de `DIAS_METEO`)
  let   simHoras = SIM_HORAS_DEF;         // lo que el usuario pide, en horas

  /* La duración se lee AQUÍ y sólo aquí, en días. Es una función y no una línea
     suelta porque `calcular()` la vuelve a leer antes de decidir nada: si el
     usuario escribe «4» y pulsa el botón sin salir del campo, el evento `change`
     puede no haber llegado todavía y se calcularía con la duración anterior. */
  /* ⛔ 2026-08-24 · «pongo 14 días y sólo hace 3». No era el selector: es el ARCHIVO.
     `extract_snapshot.py` pide el reanálisis con `end_date = min(fecha + dias, HOY)`
     —medido contra la API el 21-ago: un `end_date` futuro devuelve HTTP 400 y se lleva
     por delante la serie entera—, así que un incendio del 21-ago sólo puede tener
     3 días de viento por detrás. No es un tope de 3: depende de la fecha.
       incendio del 21-ago → 3 días · del 10-ago → 14 · del 1-jul → 54
     Antes esto se descubría DESPUÉS de gastar la captura, y el aviso salía —si salía—
     contra las horas de la captura vieja. Ahora se sabe antes de pulsar. */
  let diasRecortados = 0;   // lo que el usuario pidió cuando la fecha no da para tanto
  function fechaSim() {
    return $('simGenDate')?.value || $('simDateSel')?.value || genDate || '';
  }
  function diasMaxPorFecha() {
    const f = fechaSim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(f)) return 31;
    const hoy = new Date(); hoy.setHours(0, 0, 0, 0);
    const d = (hoy - Date.parse(f + 'T00:00:00')) / 864e5;
    return Math.max(1, Math.min(31, Math.floor(d)));
  }
  // El campo no ofrece lo que la fecha no puede dar: `max` se mueve con la fecha.
  function ajustaMaxDuracion() {
    const el = $('simDurDias'); if (!el) return;
    el.max = String(diasMaxPorFecha());
    leeDuracion();
    avisoDuracion();
  }

  function leeDuracion() {
    const el = $('simDurDias'); if (!el) return simHoras;
    // `+el.value || 2` estaba mal: «0» es un número válido y falsy a la vez, así
    // que escribir 0 daba 2 días en vez de recortarse a 1. Se comprueba que sea
    // número antes de recurrir al valor por defecto.
    const n = Number(el.value);
    const tope = diasMaxPorFecha();
    // El tope de 31 sigue siendo el duro (`DIAS_METEO`); el de la fecha manda si es menor.
    const dias = Number.isFinite(n) && el.value !== ''
               ? Math.max(1, Math.min(31, tope, Math.round(n)))
               : Math.min(2, tope);
    diasRecortados = (Number.isFinite(n) && el.value !== '' && Math.round(n) > tope) ? Math.round(n) : 0;
    if (String(dias) !== el.value) el.value = String(dias);   // se enseña lo que se va a usar
    simHoras = Math.min(SIM_HORAS_MAX, dias * 24);
    return simHoras;
  }

  // Horas de viento que trae de verdad la captura, desde la hora de arranque.
  function horasDisponibles() {
    const w = D && D.wind_hourly;
    if (!w || !Array.isArray(w.wspd) || !w.wspd.length) return SIM_HORAS_DEF;
    let i0 = Array.isArray(w.hours) ? w.hours.indexOf(String(startHour()).padStart(2, '0')) : -1;
    if (i0 < 0) i0 = 0;
    return Math.max(1, w.wspd.length - i0);
  }
  // Horizonte efectivo, en MINUTOS. Es el que usa todo el resto del fichero.
  function simHorizon() {
    return Math.max(60, Math.min(simHoras, horasDisponibles(), SIM_HORAS_MAX) * 60);
  }
  /* ── FRENO POR EDAD (2026-08-21) · puerto literal de `validate_block_a.py` ──
     Por qué existe: medido en 208 incendios con el control diurno puesto, la
     realidad pierde el 88% de su velocidad entre las 0-6 h y las 24-36 h; el
     modelo pierde el 15%. Arranca bordando y NO SABE PARAR. Y al quitarle la
     pared del lienzo (`a59`, 21-ago) se ve entero: con cuatro veces más terreno
     quema un 44% más, y seguiría.
     Qué es, dicho sin adornos: un freno FENOMENOLÓGICO. Reproduce la curva
     observada, no identifica la causa — detrás hay al menos extinción acumulada,
     combustible agotado y frentes que mueren sin reencenderse, y este factor los
     mete a los tres en el mismo saco. `AGE_TAU_H` NO es «lo que tardan los
     bomberos».
     ⚠ POR QUÉ VIENE APAGADO, y no es timidez: medido contra cicatriz con la
     extinción dentro (`a28`) y en muestra ciega (`a30`), SE PASA DE FRENADA —
     apaga incendios que en la realidad siguieron, y ese error va del lado
     inseguro: te diría que el fuego no llega a un sitio al que sí llega.
     Hasta que eso se resuelva, aquí sólo EXISTE. No actúa.
     Se porta ahora porque hasta hoy el JS no tenía ni una constante `AGE_*`
     (comprobado con grep el 19-ago) y los dos motores diferían en el mando, no
     sólo en el valor — que es la familia de fallo que más veces ha mordido. */
  /* 2026-08-22 · Deja de ser una constante para ser un INTERRUPTOR VISIBLE, y el
     motivo lo dio el usuario al ver que el fuego llena cualquier lienzo que se le
     dé: «que no para nunca, pero esa cosa hay que arreglarla porque en un incendio
     real sí para». Tiene razón, y es el §16quater entero.
     ⚠ Lo que NO cambia: sigue viniendo APAGADO, y producción sigue siendo lo de
     siempre. Encenderlo es un CAMBIO DE MODELO y va medido con su mitad ciega, no
     colado por la puerta de atrás — sobre todo éste, que está medido (`a28`, `a30`)
     y SE PASA DE FRENADA: apaga incendios que en la realidad siguieron, y ese error
     cae del lado inseguro. El interruptor existe para VERLO, no para creérselo.
     El motor de validación tiene el mismo mando y el mismo valor por defecto
     (`validate_block_a.py:260`), así que la paridad se mantiene. */
  /* ⭐⭐⭐ 2026-08-25 · ARDE O NO ARDE, POR PARCHES. Portado de
     `validate_block_a.py:prende()` (§24, §25). ENCENDIDO: producción CAMBIA hoy, y es
     la primera vez en el proyecto que un mecanismo del motor entra en la app.

     QUÉ HACE. Hasta hoy, si el frente llegaba a una celda con combustible, ardía. La
     realidad no es así: hay roquedos, vaguadas verdes y parcelas que no prenden aunque
     les llegue el fuego, y son manchas de cientos de metros, no celdas sueltas. Ahora
     una celda prende con probabilidad `combustible^POW`, y el dado se tira UNA VEZ POR
     PARCHE, no por celda. Una celda que no prende TAMPOCO PROPAGA.

     POR QUÉ SE ENCIENDE, y qué lo separa del freno por edad de abajo:
       · Baja el área quemada **sin acortar el recorrido** — los cuatro mecanismos
         anteriores (`a61`-`a64`) pagaban siempre en alcance, y éste no: razón pareada
         de alcance **1,000** sobre 40 incendios.
       · Mueve el borde y las islas hacia la realidad: forma 3,39 → 4,9 (real 8,11),
         islas 1,9% → 3,1% (real 7,0%).
       · **Se repite en una captura INDEPENDIENTE de los mismos 40 incendios** (`a74`),
         y sus efectos son 3-5× su suelo de ruido (`a75`). El freno por edad no tiene
         nada de esto: se pasa de frenada y apaga incendios que en la realidad siguieron.

     ⚠ LA ESCALA VA EN METROS Y NO EN CELDAS, y esto es la lección de `a67`: el arnés lo
     tenía en celdas, la celda de allí va de 54,7 a 129,2 m y la de la app es 80 m fijos.
     Portar «32 celdas» habrían sido 2,56 km, donde el mecanismo está MUERTO (baja el
     área un 0,1%). Son `round(1750/80) = 22` celdas.

     ⚠ EL SORTEO TIENE QUE DAR LO MISMO QUE EN PYTHON o los motores divergen en
     silencio: mismos primos, misma aritmética, y `prueba10.js` lo comprueba celda a
     celda. Primos DISTINTOS a los de la barrera y a los de la textura, o las decisiones
     saldrían correlacionadas. Máximo con rejilla 512: (512/22)*(25703+60077) = 2,0M,
     muy por debajo de 2^53, así que es exacto en JS.

     ⛔ EL ARNÉS SIGUE APAGADO A PROPÓSITO. No es un descuido: sus controles C0 comparan
     contra la MISMA producción de `a63`, y encenderlo allí rompería la comparabilidad de
     todo §24. Para medir un brazo nuevo hay que encenderlo a mano. La divergencia está
     DECLARADA en `paridad_reglas.py` (N5) y sale en cada corrida. */
  // ⭐⭐⭐ 2026-08-26 · LA TEXTURA ENTRA · §35. Y NO es «lo de ayer + textura»: el brazo
  // validado cambia TAMBIÉN el parche grueso (0,15/1750 -> 0,25/1800). Son tres valores.
  // Por qué, en una frase: la irregularidad de la mancha (`forma`) es ADIMENSIONAL, así
  // que un zoom NO la mueve — y §34 midió que TODOS los demás mandos del motor son un
  // zoom. Esto la mueve 5,0x el suelo de ruido (3,39 -> 6,92; real 8,11) con las islas
  // en 8,4% (real 7,0%), y reproduce en LAS DOS MITADES del banco.
  // Se descartó el 25-ago (`a78`) por una puerta de UN SOLO LADO sobre el alcance;
  // midiendo el ERROR de alcance, la textura lo ACERCA a la realidad sumando las dos
  // mitades (ajuste 0,41 -> 0,17 · ciega 0,00 -> 0,06), porque el motor SE PASA de
  // alcance en la mitad de ajuste (1,41).
  // ⚠ Lo que NO hace: el Dice pasa de 0,310 a 0,321 = 0,6x el ruido, o sea nada. El Dice
  // lo manda la DIRECCIÓN (27°), no el relleno (§24.6). Esto entra por forma y área.
  // ⚠ Es ESTOCÁSTICO: la peor de las ocho realizaciones deja el alcance ciego en 0,86.
  // ⛔⛔ 26-ago 13:1x · REVERTIDO A `parche` TRAS VERIFICAR EN PANTALLA. El mecanismo
  // es estadísticamente correcto (§35) pero VISUALMENTE NO: el hash del sorteo es LINEAL
  // —`(I*pa + J*pb) % 100003`— y los conjuntos de nivel de una función lineal módulo m son
  // RETÍCULAS (Marsaglia 1968). Medido: el 82% de las separaciones entre huecos de una
  // fila son EXACTAMENTE 5 bloques. Con el parche grueso (22-23 celdas) el periodo es
  // ~9 km y no se ve; con la textura fina (3 celdas) cae en ~1,2 km y la mancha sale como
  // una MOSQUITERA, no como un mosaico de incendio.
  // No se revierte el diagnóstico de §35 —la forma y las islas mejoran de verdad—: se
  // revierte hasta arreglar el hash y RE-MEDIR, porque `a78` midió CON la retícula dentro.
  // Volver a poner 'parche+textura' / 0,25 / 1800 sólo cuando eso esté hecho.
  /* ⛔⛔⛔ 30-ago · APAGADO. Y no es sólo el punto 6 de §1quater-F: al auditarlo hoy
     apareció que **el motor que se mide y el motor que corre no eran el mismo**.
     `scripts/validacion/validate_block_a.py:376` tiene `USE_P_IGN = False` desde
     que §42.1 lo condenó el 27-ago; aquí seguía en `'parche'`. Así que TODAS las
     garantías que la app enseña —el falso seguro de 0,5% (§83), la probabilidad de
     12 h, el reloj de §88.2 y las bandas de §92.1— están medidas sobre un motor
     SIN sorteo y las estaba produciendo un motor CON sorteo.

     Y el error caía del lado inseguro: el sorteo borra celdas, así que el modelo
     quema menos, declara «seguro» MÁS terreno del que se midió, y el falso seguro
     real de la pantalla era PEOR que el 0,5% prometido.

     Lo que midió §42.1 sobre `a90_mediana.json`, y por qué no se echa de menos:
       · sin sorteo ............ cobertura 96,1%
       · `bloque`  0,15/1750 ... 89,4%
       · `organico` 0,15/1750 .. 78,1%   ← lo que había puesto aquí
     El sorteo **pinta islas sin quemar encima de sitios que se quemaron**: no es un
     adorno discutible, destruye 18 puntos de acierto sobre la única vara que
     sostiene lo que la app promete.

     ⚠ Lo que se pierde y va declarado: §35 midió que la textura mejora la forma y
     las islas. Es cierto y no se discute — pero se paga en cobertura, y con el
     objetivo delante (decidir por dónde escapar y por dónde atacar) la cobertura
     manda. Volver a encenderlo exige arreglar antes el hash de retícula (§35bis) Y
     re-medirlo, y aun así tendría que ganar en cobertura para entrar. */
  let P_IGN_MODO = 'no';         // 'no' | 'parche' | 'parche+textura'
  const P_IGN_POW      = 0.15;   // p = combustible ^ POW
  const P_IGN_M        = 1750;   // lado del parche, en METROS (§25 · `a67`)
  const P_IGN_FINO_M   = 220;    // textura fina de `a68`: sólo en 'parche+textura'
  const P_IGN_FINO_POW = 0.05;
  const P_IGN_PA = 25703, P_IGN_PB = 60077;     // primos del parche
  const P_IGN_FPA = 46589, P_IGN_FPB = 83987;   // primos de la textura
  /* ⛔⛔ 2026-08-26 · EL FOCO NO PUEDE CAER EN UN PARCHE APAGADO · el fallo que el
     usuario vio en pantalla: «dice hecho y no se ve nada».
     MEDIDO sobre 300 focos aleatorios: con `parche` 0,15/1750 —lo que hay EN PRODUCCIÓN
     desde el 25-ago— el **7,7%** de los focos queda ENCERRADO y el incendio no sale del
     punto; con 0,25/1800 sube al 11% y con textura al 12,7%. El sorteo apaga bloques
     ENTEROS de 22x22 celdas (1,75 km): si el foco cae en el centro de uno, no hay por
     dónde escapar y la app termina sin pintar nada.
     Y es una CONTRADICCIÓN, no una mala suerte: el sorteo representa parcelas de las que
     no sabemos si arden, pero **el foco es un dato que pone el usuario** — ahí hay fuego.
     Ese parche no puede ser de los que no arden. Se exime el bloque (grueso y fino) que
     contiene cada foco. Comprobado: 0/300 atascados en las tres configuraciones.
     Espejo exacto de `SEMILLA_BLOQUES` / `_bloques_de()` en `validate_block_a.py`. */
  let SEMILLA_BLOQUES = null;     // Set de claves 'g:I:J' / 'f:I:J', por corrida
  function bloquesDeFoco(k, nc, b, bf) {
    const i = (k / nc) | 0, j = k % nc, out = ['g:' + ((i / b) | 0) + ':' + ((j / b) | 0)];
    if (bf > 1) out.push('f:' + ((i / bf) | 0) + ':' + ((j / bf) | 0));
    return out;
  }
  /* ⛔⛔⛔ 2026-08-26 · LOS CUADRADOS · el fallo que el usuario persiguió toda la tarde.
     Lo que veía como «una línea recta» en cada simulación eran los PARCHES del sorteo:
     el dado se tiraba por bloque de `P_IGN_M/celda` = 1750/80 = **22 celdas**, alineado a
     la rejilla, así que un parche que no prende es un CUADRADO PERFECTO de 1,76 km con
     lados rectos horizontales y verticales. Localizados en el campo: filas 154..175 y
     110..131 — 22 filas exactas, arrancando en múltiplos de 22 (22×7, 22×5).
     Y es físicamente falso: lo que no arde en un incendio real son roquedos, vaguadas
     verdes y parcelas — manchas IRREGULARES, nunca cuadrados alineados a una rejilla.

     Dos arreglos, y son la misma familia de error:
     1 · `mezcla32` sustituye al hash LINEAL. `(i*pa + j*pb) % m` tiene sus conjuntos de
         nivel en RETÍCULAS (Marsaglia 1968): medido, el 82% de las separaciones entre
         parches apagados eran exactamente 5 bloques. Un hash con avalancha no.
     2 · `deforma()` tuerce las coordenadas del bloque con ondas suaves antes de dividir,
         así que la frontera entre parches deja de ser recta. **La probabilidad de cada
         celda NO cambia** —sigue siendo `combustible^POW`—, sólo cambia la FORMA.

     ⚠ Esto cambia el sorteo, así que las cifras de `a66`-`a78` (medidas con cuadrados)
     hay que RE-MEDIRLAS. `P_IGN_FORMA='bloque'` reproduce el comportamiento viejo para
     que los experimentos antiguos sigan siendo reproducibles. */
  let P_IGN_FORMA = 'organico';   // 'bloque' = cuadrados (histórico) · 'organico' = manchas
  function mezcla32(a) {
    a = (a ^ 61) ^ (a >>> 16);
    a = (a + (a << 3)) | 0;
    a = a ^ (a >>> 4);
    a = Math.imul(a, 0x27d4eb2d);
    a = a ^ (a >>> 15);
    return a >>> 0;
  }
  function deforma(i, j, b) {
    // ondas suaves de amplitud ~1/3 de bloque: rompen el borde recto sin mover el centro
    const A = b / 3;
    const wi = i + A * (Math.sin(j * 0.21) * 0.6 + Math.sin(j * 0.073 + 1.7) * 0.4);
    const wj = j + A * (Math.sin(i * 0.19) * 0.6 + Math.sin(i * 0.061 + 0.9) * 0.4);
    return [Math.floor(wi), Math.floor(wj)];
  }
  function tiraIgn(i, j, b, pa, pb, p) {
    if (b > 1) {
      if (P_IGN_FORMA === 'organico') { const w = deforma(i, j, b); i = w[0]; j = w[1]; }
      i = Math.floor(i / b); j = Math.floor(j / b);
    }
    if (P_IGN_FORMA === 'organico') {
      return mezcla32(Math.imul(i, pa) ^ Math.imul(j, pb)) % 10000 < Math.floor(p * 10000);
    }
    return (i * pa + j * pb) % 100003 % 10000 < Math.floor(p * 10000);
  }
  /* ¿Prende la celda `k` al llegarle el frente? Determinista, dirigido por el dato.
     Determinista por dos motivos que no son negociables: Dijkstra visita una celda
     varias veces y un dado distinto en cada visita daría un resultado dependiente del
     orden de la cola; y el arnés tiene que poder dar EXACTAMENTE lo mismo. */
  function prende(k) {
    if (P_IGN_MODO === 'no') return true;
    let f = grid.fuel[k];
    f = (f == null) ? 0 : (f < 0 ? 0 : (f > 1 ? 1 : f));
    const nc = grid.nc, i = (k / nc) | 0, j = k % nc;
    const p = Math.pow(f, P_IGN_POW);
    if (p <= 0) return false;
    const b = Math.max(1, Math.round(P_IGN_M / CELDA_OBJETIVO));
    const exG = SEMILLA_BLOQUES && SEMILLA_BLOQUES.has('g:' + ((i / b) | 0) + ':' + ((j / b) | 0));
    if (!exG && p < 1 && !tiraIgn(i, j, b, P_IGN_PA, P_IGN_PB, p)) return false;
    if (P_IGN_MODO === 'parche+textura') {
      const pf = Math.pow(f, P_IGN_FINO_POW);
      if (pf <= 0) return false;
      const bf = Math.max(2, Math.round(P_IGN_FINO_M / CELDA_OBJETIVO));
      const exF = SEMILLA_BLOQUES && SEMILLA_BLOQUES.has('f:' + ((i / bf) | 0) + ':' + ((j / bf) | 0));
      if (!exF && pf < 1 && !tiraIgn(i, j, bf, P_IGN_FPA, P_IGN_FPB, pf)) return false;
    }
    return true;
  }
  let useAgeBrake = false;       // apagado: producción NO cambia
  const AGE_T0_H      = 6.0;     // horas de gracia antes de empezar a frenar
  const AGE_TAU_H     = 12.0;    // constante de tiempo del decaimiento, en horas
  const AGE_FLOOR     = 0.05;    // multiplicador mínimo
  function ageBrake(ct) {        // `ct` en minutos, como en Python
    if (!useAgeBrake) return 1.0;
    const th = ct / 60.0;
    if (th <= AGE_T0_H) return 1.0;
    return AGE_FLOOR + (1.0 - AGE_FLOOR) * Math.exp(-(th - AGE_T0_H) / AGE_TAU_H);
  }

  const INT_REF     = 12.0;   // m/min que se pinta como intensidad máxima (amarillo)
  const FRONT_FRAC  = 0.05;   // ancho del frente activo (fracción del tiempo total)

  const SPEED_SECS  = { slow: 55, med: 28, fast: 12 };  // duración de la animación

  // ── Medios de extinción (A1/A2) ─────────────────────────────────────────────
  // rate = metros de línea de defensa por hora (orientativo, terreno medio).
  // resp = minutos hasta que el medio está trabajando en el monte (llegada).
  // Los rendimientos reales varían mucho con pendiente, matorral y accesos.
  // resp = minutos hasta que el medio está TRABAJANDO en el monte, según la
  // cronología de arriba. Antes eran 20-90 min para todo, que es el plazo de una
  // dotación urbana, no el de un incendio forestal.
  const RESOURCES = {
    crew:   { icon: '👷', rate: 120,  resp: T_GROUND_1, direct: 5 },   // cuadrilla manual
    engine: { icon: '🚒', rate: 400,  resp: T_GROUND_1, direct: 8 },   // autobomba / tractor
    dozer:  { icon: '🚜', rate: 1200, resp: T_GROUND_2, direct: 15 },  // maquinaria: llega al escalar
    heli:   { icon: '🚁', rate: 700,  resp: T_AIR,      direct: 12 }   // helicóptero (línea húmeda)
  };
  // Intensidad máxima que aguanta cada medio, por su producción de línea. Es la
  // regla de `contencion/motor.py::umbral_intensidad()`: por debajo de 500 m/h se
  // trabaja con herramienta manual y motosierra (banda <=346 kW/m); por encima es
  // maquinaria pesada, que la Tabla 1 sitúa —junto con los AVIONES— hasta los
  // 1.731 kW/m. Es un supuesto de correspondencia, explícito para poder discutirlo.
  for (const R of Object.values(RESOURCES)) {
    R.imax = R.rate <= 500 ? I_MANUAL : I_MAQUINA;
  }
  /* ── ⭐ LA REGLA DE DESPLIEGUE · §97.1 · `c118`, n=207, 31-ago ───────────────
     La primera cifra del proyecto que contesta una decisión que un jefe de
     guardia toma todos los días: **no elige entre llegar ya o tarde, elige entre
     mandar lo que tiene cerca ahora o esperar a lo que viene de lejos**.

     Rejilla completa 4 fuerzas × 5 retrasos sobre 207 incendios, con el ancla
     emparejada por incendio contra `c91` en +0,00 pts. La fila de 8 cuadrillas
     coincide CIFRA POR CIFRA con `c113` (§96.3), que es otro experimento con
     otro eje: dos vías independientes, mismo número.

     `gana` = cuántos minutos de espera compensa DOBLAR la fuerza, partiendo de
     llegar a `t`. `tope` = el valor toca el borde del eje (la rejilla se acaba
     en 120 min), así que ahí es COTA INFERIOR y se dice «al menos».

     ⚠ Es un SUELO, no una cifra operativa: este motor apaga hasta el 46,4%
     donde la realidad (INFOCA) llega al 67%. El sentido es fiable; la ventaja de
     concentrar medios es al menos ésta, probablemente más.
     ⚠ Y el eje llega a 32 cuadrillas (~640 personas sobre un incendio): la parte
     alta de la rejilla es extrapolación operativa, no doctrina. */
  const C118_FRONTERA = [
    { t: 15, gana: 75, tope: false },
    { t: 30, gana: 60, tope: false },
    { t: 60, gana: 60, tope: true  },
    { t: 90, gana: 30, tope: true  }
  ];
  const C118_TOPE_EJE = 120;          // el retraso mayor que se midió
  // El contraste que hace la regla operativa, de la misma rejilla:
  // 2026-09-17 · RE-MEDIDO CON LA CUADRILLA DE ESTA APP (INCENDIOS.md §169.10).
  // Los valores anteriores (15,1% y 4,1%) salían de la rejilla con cuadrillas de
  // 324 m/h, que es la del banco; `RESOURCES.crew.rate` aquí es 120 m/h y cada
  // cuadrilla del banco vale por 2,7 de éstas. Con 120 m/h la misma rejilla da
  // 5,5% (32 cuadrillas a 120 min) y 2,2% (4 cuadrillas a 15 min): el SENTIDO de
  // la regla no cambia —concentrar medios gana con holgura— pero las cifras que
  // se enseñaban eran de otra cuadrilla. ⚠ Sin ancla contra crudo viejo: no
  // existe un `c126` a 120 m/h (§169.10).
  const C118_CONTRASTE = { fuerte: 5.5, fuerteN: 32, fuerteT: 120,
                           flojo: 2.2,  flojoN: 4,   flojoT: 15 };

  // Devuelve la fila medida aplicable a una llegada de `t` min, o null si `t`
  // se sale de lo medido. No interpola: §85 dejó dicho que no se declara un
  // número fuera de donde se midió, y aquí la alternativa (decir «no aplica»)
  // no cae a ninguna rampa vieja, así que null es seguro.
  function reglaDespliegue(t) {
    if (!isFinite(t) || t > C118_TOPE_EJE) return null;
    let fila = C118_FRONTERA[0];
    for (const f of C118_FRONTERA) if (t >= f.t) fila = f;
    return fila;
  }

  const SEG_USEFUL = 300;     // m de línea que consideramos "un tramo útil" (A2)
  const DIRECT_HARD = 15;     // m/min de avance por encima del cual NO cabe ataque directo
  const ASSET_MAX = 5;        // puntos 🏠 que se pueden marcar a la vez: coste lineal
                              // por punto (arco + feasibility), acotado a propósito
  // ── Reparto de medios (2026-08-12) ──────────────────────────────────────────
  // En un incendio real no trabaja un solo equipo: llegan varios y se reparten el
  // perímetro. El asesor puede colocar hasta TEAMS_MAX medidas de tierra, cada una
  // con SU equipo, y por eso las horas de dos medidas simultáneas se sostienen.
  const TEAMS_MAX  = 3;
  // Un cortafuegos tiene una extensión LÓGICA: la que un equipo abre en su relevo.
  // Sin este tope la longitud la mandaba la anchura de la huella del incendio a
  // 48 h y salían líneas de 6-11 km — 50-90 horas de obra para una cuadrilla, de
  // ahí que el asesor sólo supiera decir "no da tiempo".
  const SHIFT_MIN  = 12 * 60;
  const RUN_MIN    = 3;       // celdas mínimas para que un tramo de perímetro valga

  let map = null, overlay = null, igMks = [], meMk = null, escLine = null;
  let actLayer = null, actSig = '';        // dibujo vectorial de las intervenciones
  let D = null, grid = null, arrival = null, spd = null;
  // A1/A3/C: campos temporales por celda. El agua es un INTERVALO [wTime, wEnd]
  // de mojado pleno: la manguera lo mantiene mientras el equipo trabaja allí,
  // la descarga aérea sólo un rato.
  let bTime = null, wTime = null, wEnd = null, burnt = null;
  let accessCell = null, accessMk = null;         // C3: hasta dónde llega el vehículo
  let actions = [], actionSeq = 0;                // A1: línea de tiempo de intervenciones
  let baseArrival = null, baseSpd = null;         // escenario SIN intervenir (referencia)
  let baseEdge = null;                            // m/min a los que AVANZA el borde
  let oppSlack = null;                            // A2: margen de trabajo por celda
  let ens = null, ensRunning = false;             // B: abanico de escenarios
  let lastSpots = 0;                              // D1: focos secundarios de la última pasada
  let tMax = 0, igCells = [], meCell = null;
  let assetCells = [], assetMks = [], firmsMks = [];   // puntos a proteger (hasta ASSET_MAX) · focos reales FIRMS
  let lastPlan = null;                            // propuesta del asesor pendiente de aplicar
  let contain = null;                             // resultado de la contención del plan aplicado
  let tool = 'ignition';
  let anim = null, animT = 0, animDur = SPEED_SECS.med;
  let zoneClicks = [], zoneRect = null, genTask = null, genTimer = null, genDate = null;

  const clamp = (x, a, b) => x < a ? a : (x > b ? b : x);
  function setStatus(m, err) {
    const el = $('simStatus'); if (!el) return;
    el.textContent = m || ''; el.className = 'sim-status' + (err ? ' err' : '');
  }
  const resource = () => RESOURCES[$('simRes')?.value] || RESOURCES.crew;
  const respMin  = () => +($('simResp')?.value ?? resource().resp);
  const startHour = () => +($('simStartHour')?.value ?? 14);

  /* ── Entrada al abrir la pestaña ─────────────────────────────────────────── */
  window.updateFireSimTab = function () {
    if (!map) initMap(); else map.invalidateSize();
    if (!D) loadData();
  };

  function initMap() {
    map = L.map('simMap').setView([40, 0], 5);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }).addTo(map);
    map.on('click', onMapClick);
    actLayer = L.layerGroup().addTo(map);
