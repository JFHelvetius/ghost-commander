# 👻 Ghost Commander

**Un sistema capaz de coordinar cientos de agentes autónomos en entornos
cambiantes, maximizando el éxito de la misión mediante reasignación dinámica de
recursos.**

Ghost Commander no es un observador ni un paper: es un **comandante digital**.
Asigna tareas, detecta fallos y reorganiza la flota en tiempo real para que la
misión se complete a pesar de las pérdidas.

> El resultado que persigue no es *"qué arquitectura tan interesante"*, sino:
> **"Acabo de ver 100 agentes perder un tercio de sus recursos a una onda de
> choque y reorganizarse solos para completar la misión."**

---

## Demo en 30 segundos

```bash
# headless: una misión + comparación de las 3 estrategias
python examples/run_demo.py

# dashboard interactivo (mapa 2D, métricas, timeline, replay, comparación)
ghost-commander-app
```

Salida típica del demo (escenario por defecto, 100 agentes, onda de choque en el
tick 18 que tumba ~35% de la flota):

```
=== single run (global strategy) ===
  mission completion : 100.0%
  tasks done         : 55/55
  agents lost        : 40
  reassignments      : 18
  determinism digest : bbd2c0926212c315

=== strategy comparison (same scenario + seed) ===
  1. global   mission=100.0%  done=55/55  ticks=60   lost=40  reassign=18
  2. auction  mission=100.0%  done=55/55  ticks=64   lost=40  reassign=18
  3. greedy   mission=100.0%  done=55/55  ticks=111  lost=40  reassign=24
```

La flota pierde 40 de 100 agentes a mitad de misión y aun así la termina. El
comandante reasigna 18 veces las tareas que quedaron huérfanas. Las tres
estrategias completan, pero `greedy` tarda casi el doble y necesita más
reasignaciones: la comparación hace visible *por qué* la coordinación importa.

---

## Instalación

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows
pip install -e ".[app,dev]"     # app = dashboard, dev = tests
```

Requiere Python ≥ 3.11. El núcleo solo depende de `numpy`; el dashboard añade
`streamlit`, `plotly` y `pandas`.

---

## Uso (CLI)

```bash
ghost-commander presets                              # escenarios y estrategias
ghost-commander run --strategy global --seed 7       # una misión
ghost-commander run --preset swarm --save run.json   # 200 agentes, guarda replay
ghost-commander compare --preset scarce              # ranking de estrategias
```

Escenarios incluidos: `default`, `swarm` (200 agentes), `scarce` (recursos
escasos), `calm` (sin fallos), `contested` (con deadlines, la misión se puede
*perder*), `rush` (plazos muy ajustados, escaparate del triage). Estrategias:
`greedy`, `auction`, `global`, `triage` (deadline-aware).

### Cuándo la coordinación *gana o pierde* la misión

En `default` sobran agentes incluso tras el shock, así que las tres estrategias
completan (la diferencia es de **velocidad**). El escenario `contested` añade
**deadlines de tarea**: una tarea que no se completa a tiempo **fracasa** — una
pérdida de misión. Con una flota más justa bajo desgaste continuo, la calidad de
la coordinación se vuelve **éxito**, no solo velocidad:

```
ghost-commander compare --preset contested
rank strategy  mission   done     failed  ticks   lost   reassign
------------------------------------------------------------------
1    auction   98.5%     58/60    2       95      35     32
2    global    96.3%     56/60    4       136     39     35
3    greedy    88.8%     53/60    7       131     37     33
```

`greedy` pierde 7 tareas (es local y por orden de llegada: se amontona y
reorganiza tarde); las estrategias que resuelven la contención globalmente
(`auction`, `global`) salvan bastante más. **El hallazgo robusto across seeds es
que `greedy` sacrifica más tareas bajo presión de deadline**; quién gana entre
`auction` y `global` cambia según la misión. La métrica de misión está
**ponderada por prioridad**, así que perder una tarea VITAL pesa más que perder
una LOW.

### Cuando los plazos aprietan: triage deadline-aware

Las cuatro estrategias anteriores pesan prioridad contra distancia pero **ignoran
el tiempo**. La estrategia `triage` estima si un agente *aún llega* a una tarea
antes de su deadline (`tiempo_viaje + tiempo_trabajo` vs `slack`): descarta las
causas perdidas y se lanza a las tareas salvables y urgentes, las críticas
primero. Con plazos holgados se comporta como `global`; cuando aprietan, gana:

```
ghost-commander compare --preset rush
rank strategy  mission   done     failed  ticks   lost   reassign
------------------------------------------------------------------
1    triage    88.3%     48/60    12      80      28     23
2    global    84.1%     44/60    16      80      28     23
3    auction   79.3%     43/60    17      80      28     24
4    greedy    69.0%     37/60    23      80      28     28
```

`triage` salva **11 tareas más que `greedy`** en la misma misión. Across seeds es
el ganador medio cuando los deadlines son ajustados; con deadlines desactivados
produce exactamente la misma misión que `global` (mismo digest determinista).

---

## Qué hay dentro

```
src/ghost_commander/
  core/          # infraestructura reutilizada de Project Ghost (ver abajo)
    rng.py       #   RandomSource jerárquico determinista (fallos reproducibles)
    events.py    #   EventBus tipado + catálogo de eventos (timeline)
    clock.py     #   reloj de paso fijo determinista
  domain/        # modelo: Agent, Task, World
  coordination/  # estrategias intercambiables: greedy, auction, global, triage
  sim/           # motor, modelo de fallos, métricas, grabador, comparador
  app/           # dashboard Streamlit
  cli.py         # entrada de línea de comandos
```

### El motor por tick

1. **Reasigna** los agentes libres a las tareas que necesitan dotación, usando
   la estrategia activa.
2. **Mueve** cada agente hacia su tarea y la **trabaja** cuando llega.
3. **Aplica fallos**: desgaste de recursos, pérdidas aleatorias y ondas de
   choque coordinadas.
4. **Desvincula** a los agentes perdidos → sus tareas vuelven al pool y se
   re-dotan en el siguiente tick (el "reorganizarse solo" que se ve en pantalla).
5. **Registra** métricas y un frame para el replay.

### Determinismo y replay

Mismo escenario + misma seed + misma estrategia ⇒ **misión idéntica, bit a
bit** (verificado por `RunRecording.digest()`). Por eso la barra de replay del
dashboard es exacta y la comparación de estrategias es justa: lo único que
cambia es el algoritmo.

---

## Reutilización de Project Ghost

Ghost Commander es un proyecto **nuevo e independiente**. No modifica ni depende
del Project Ghost original, pero **reutiliza tres de sus piezas mejor diseñadas**
adaptándolas (Apache-2.0):

| Pieza de Ghost | Para qué se reutiliza aquí |
|---|---|
| `core.clock.RandomSource` (derivación jerárquica SHA-256) | Fallos **reproducibles**: el stream de fallos es un hijo del seed raíz, independiente del layout |
| `events.EventBus` + eventos tipados | **Timeline de eventos** del dashboard (sequence monotónico, dispatch síncrono, aislamiento de subscribers) |
| Patrón `SimClockImpl` (tiempo entero, sin float, avanzado solo por código) | Reloj de paso fijo determinista del motor |

El resto —dominio de agentes/tareas, estrategias de coordinación, modelo de
fallos, motor, métricas y dashboard— es nuevo.

---

## Tests

```bash
pytest -q     # 19 tests: determinismo, validez de asignaciones, integración del motor
```

## Estado

MVP v0.1.0 — ejecutable y demostrable hoy. Incluye **deadlines de tarea** (las
misiones se pueden *perder*) y una estrategia **deadline-aware (`triage`)** que
gana cuando los plazos aprietan (preset `rush`). Roadmap inmediato: capacidades
heterogéneas de agentes, tareas que llegan durante la misión (no solo al inicio),
y animación continua en el dashboard.

## Licencia

Apache-2.0.
