"""Streamlit dashboard: map, live metrics, event timeline, replay and comparison.

Run with:  ``ghost-commander-app``  or  ``streamlit run streamlit_app.py``.

The whole point of this view is the visceral demo: watch a fleet lose a third of
its agents to a shock wave and reorganize itself to finish the mission.
Everything is driven off a deterministic ``RunRecording`` so the replay slider is
exact and the strategy comparison is fair.
"""

from __future__ import annotations

import dataclasses

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ghost_commander.coordination import STRATEGIES
from ghost_commander.sim import PRESETS, Scenario, StrategyResult, run_scenario
from ghost_commander.sim.recorder import RunRecording

_BG = "#0e1117"
_FG = "#cdd3df"


def _logo(size: int = 44) -> str:
    """Inline SVG mark: a command hub reassigning agent nodes (hub-and-spoke).

    Bespoke identity for Ghost Commander — a central commander (green core)
    directing peripheral agents (blue nodes) over live links. Deliberately not
    an emoji.
    """
    return f"""
<svg width="{size}" height="{size}" viewBox="0 0 100 100" fill="none"
     xmlns="http://www.w3.org/2000/svg" style="vertical-align:middle">
  <circle cx="50" cy="50" r="46" fill="#0e1117" stroke="#27d17c" stroke-width="3"/>
  <g stroke="#3aa0ff" stroke-width="2.4" opacity="0.75" stroke-linecap="round">
    <line x1="50" y1="50" x2="26" y2="28"/>
    <line x1="50" y1="50" x2="76" y2="32"/>
    <line x1="50" y1="50" x2="28" y2="74"/>
    <line x1="50" y1="50" x2="74" y2="72"/>
  </g>
  <g fill="#3aa0ff">
    <circle cx="26" cy="28" r="6.5"/>
    <circle cx="76" cy="32" r="6.5"/>
    <circle cx="28" cy="74" r="6.5"/>
    <circle cx="74" cy="72" r="6.5"/>
  </g>
  <circle cx="50" cy="50" r="12" fill="#27d17c"/>
  <circle cx="50" cy="50" r="12" fill="none" stroke="#0e1117" stroke-width="2.5"/>
</svg>
"""

_STATUS_COLOR = {
    "idle": "#7f8c9b",
    "moving": "#3aa0ff",
    "working": "#27d17c",
    "recharging": "#b06cff",
    "failed": "#e0484f",
}
_PRIORITY_SIZE = {1: 9, 2: 12, 3: 15, 4: 19, 5: 24}

# Rank colors for the strategy comparison (winner -> worst).
_RANK_COLORS = ["#27d17c", "#5cc887", "#9fc56f", "#f4b942", "#e07a3a", "#e0484f"]


def _lerp_color(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> str:
    t = max(0.0, min(1.0, t))
    return "rgb({},{},{})".format(*(int(c1[j] + (c2[j] - c1[j]) * t) for j in range(3)))


def _hud_annotations(m: dict, shock: bool) -> list[dict]:
    """A heads-up display baked into each animation frame (updates as it plays)."""
    txt = (f"tick <b>{int(m['tick'])}</b>   ·   misión <b>{m['mission_completion']*100:.0f}%</b>"
           f"   ·   agentes <b>{int(m['agents_alive'])}/{int(m['agents_total'])}</b>"
           f"   ·   tareas <b>{int(m['tasks_done'])}/{int(m['tasks_total'])}</b>")
    anns = [dict(x=0.012, y=0.985, xref="paper", yref="paper", xanchor="left", yanchor="top",
                 text=txt, showarrow=False, align="left",
                 font=dict(color="#e6ebf3", size=14),
                 bgcolor="rgba(12,15,22,0.78)", bordercolor="#27d17c", borderwidth=1,
                 borderpad=7)]
    if shock:
        anns.append(dict(x=0.5, y=0.55, xref="paper", yref="paper", xanchor="center",
                         yanchor="middle", text="⚡ ONDA DE CHOQUE", showarrow=False,
                         font=dict(color="#ff5a60", size=34), opacity=0.9))
    return anns

# One-line "what makes this one different" for the comparison table.
_SCENARIO_DIFF = {
    "default": "Lo básico: una **onda de choque** tumba un tercio de la flota a mitad "
               "de misión. Todas completan; ves la reorganización.",
    "swarm": "**Escala**: 200 agentes y 80 tareas a la vez.",
    "scarce": "**Recursos justos**: la flota se desgasta; hay que cuidarla.",
    "calm": "**Sin sorpresas** (ni fallos ni shock): coordinación 'en limpio', de referencia.",
    "contested": "**Plazos**: las tareas *fallan* si no se hacen a tiempo → la misión se puede **perder**.",
    "rush": "**Plazos muy apretados**: solo gana quien hace *triage* (prioriza lo salvable).",
    "streaming": "**El mundo cambia**: empieza con pocas tareas y llegan más en oleadas.",
    "specialist": "**Flota mixta**: cada tarea pide un *tipo* de agente, y uno escasea.",
    "endurance": "**Desgaste largo + bases de recarga**: sin recargar, la flota se extingue.",
    "joint": "**Tareas en equipo**: hacen falta 2 agentes a la vez → hay que sincronizar.",
    "recon": "**ISR / reconocimiento** (coordinación, no targeting): cubrir puntos "
             "antes de que caduque su ventana, con interferencias (EW) y desgaste.",
    "resupply": "**Logística en disputa**: reparto bajo desgaste sostenido por bases "
                "(FOB) — sin ellas, la flota se agota antes de servir el campo.",
    "sar": "**Búsqueda y rescate**: llegar a supervivientes antes de que cierre su "
           "ventana (plazos), extracciones que exigen equipo de 2, y una réplica.",
    "patrol": "**Vigilancia persistente**: eventos que aparecen sin parar en un área "
              "grande y hay que atender a tiempo, con flota modesta. Cobertura sostenida.",
    "escalating": "**Prioridades dinámicas**: una tarea que espera se vuelve más "
                  "urgente; hay que re-priorizar la flota sin parar.",
    "taskforce": "**Mix de especialistas**: ~40% de tareas necesitan 1 de cada tipo a "
                 "la vez (p. ej. recon + médico) — la combinación correcta, no solo cuerpos.",
    "mixedfleet": "**Flota heterogénea**: unidades rápidas/lentas y ligeras/pesadas; "
                  "importa *qué* unidad encaja, no solo cuál está cerca.",
}

# How each strategy decides + when it shines (for the comparison table).
_STRATEGY_GUIDE = {
    "greedy": ("Cada unidad va a la mejor tarea **más cercana** (decisión local, rápida).",
               "Casi nunca destaca; suele ser la **peor** bajo presión."),
    "auction": ("Las tareas se **subastan** y van al mejor postor (mira tarea por tarea).",
                "Cuando varias unidades se pelean por las mismas tareas."),
    "global": ("Empareja **toda la flota con todas las tareas a la vez** (visión global).",
               "En general: equilibrada y sólida."),
    "triage": ("Como *global* pero mirando los **plazos**: descarta lo perdido y corre "
               "a lo urgente salvable.",
               "Cuando los **deadlines aprietan** (rush, contested)."),
    "optimal": ("Asignación **óptima exacta** por tick (algoritmo húngaro) del mismo "
                "objetivo que persiguen las heurísticas.",
                "Es el **techo** de ese objetivo; pero al ser *miope* (no mira "
                "plazos), triage puede ganarle bajo presión."),
}

_SCENARIO_DESC = {
    "default": "Flota amplia, onda de choque a mitad de misión. Las 3 estrategias "
               "completan; la diferencia es de velocidad.",
    "swarm": "200 agentes, 80 tareas. Coordinación a gran escala.",
    "scarce": "Pocos agentes y recursos: el desgaste aprieta.",
    "calm": "Sin fallos ni shock — línea base de coordinación pura.",
    "contested": "Deadlines activos: la misión se puede *perder*. La coordinación "
                 "determina cuántas tareas se salvan.",
    "rush": "Plazos muy ajustados. Escaparate del triage deadline-aware: "
            "descarta causas perdidas y salva lo urgente.",
    "streaming": "Entorno cambiante: arranca con pocas tareas y llegan más en "
                 "oleadas. Hay que reorganizarse de forma continua.",
    "specialist": "Flota heterogénea con un especialista escaso (repair, 20%). "
                  "Hay que enrutar el *tipo* correcto, no solo el más cercano.",
    "endurance": "Misión larga de desgaste con bases de recarga. Sin bases la "
                 "flota se extingue; con ellas se sostiene.",
    "joint": "~40% de tareas exigen un equipo de 2 a la vez. Coordinación "
             "*entre* agentes: hay que sincronizar llegadas.",
    "recon": "**ISR / reconocimiento** (coordinación, no targeting): drones cubren "
             "puntos de interés antes de que caduque su ventana de inteligencia, "
             "bajo interferencias (EW) y desgaste.",
    "resupply": "**Logística en disputa**: reparto autónomo a posiciones avanzadas "
                "bajo fuerte desgaste, sostenido por bases (FOB) de recarga. Sin "
                "bases la flota se agota antes de servir el campo.",
    "sar": "**Búsqueda y rescate**: alcanzar supervivientes antes de que cierre su "
           "ventana de supervivencia (plazos ajustados); ~30% de extracciones "
           "necesitan un equipo de 2; una réplica adelgaza la flota.",
    "patrol": "**Vigilancia persistente / cobertura**: eventos a inspeccionar que "
              "aparecen sin parar en un área grande y deben atenderse a tiempo, con "
              "una flota modesta. El reto es la cobertura sostenida.",
    "escalating": "**Prioridades dinámicas**: cada tarea que espera sube de prioridad "
                  "con el tiempo, así que el comandante debe re-rankear la flota "
                  "continuamente, bajo onda de choque y plazos.",
    "taskforce": "**Equipo conjunto (mix de especialistas)**: ~40% de tareas requieren "
                 "un agente de *cada tipo* a la vez (p. ej. recon + médico). Hay que "
                 "enviar la combinación correcta, no solo cuerpos suficientes.",
    "mixedfleet": "**Flota heterogénea**: cada unidad tiene velocidad y capacidad de "
                  "trabajo distintas (exploradores rápidos vs. unidades pesadas). Bajo "
                  "plazos premia a quien razona el tiempo real de cada unidad (triage).",
}


# --------------------------------------------------------------------------- map
# Fixed trace order so Plotly can animate frame-to-frame (trace count is constant):
#   0 links · 1 bases · 2 tasks-open · 3 tasks-done · 4 tasks-failed · 5 halo · 6 core
import math as _math

# CRITICAL for animation: every trace must keep a CONSTANT number of points,
# matched by index, across all frames. If a trace's length changes between frames
# Plotly re-indexes and flings points across the map during the transition (the
# "going crazy" bug). So tasks and links use fixed slots (absent => None/hidden),
# exactly like the id-stable agents trace.


def _frame_scatters(
    frame: dict,
    prev_pos: dict[int, tuple[float, float]],
    agent_ids: list[int],
    task_ids: list[int],
) -> list[go.Scattergl]:
    world = frame["world"]
    amap = {a["id"]: a for a in world["agents"]}
    tmap = {t["id"]: t for t in world["tasks"]}
    bases = world.get("bases", [])
    tpos = {t["id"]: (t["x"], t["y"]) for t in world["tasks"]}

    # --- links: one fixed 3-slot segment per agent (agent->task, then a break);
    # None slots when the agent isn't en route. Constant length = 3 * n_agents.
    lx: list[float | None] = []
    ly: list[float | None] = []
    for aid in agent_ids:
        a = amap.get(aid)
        if a and a["status"] == "moving" and a.get("task_id") in tpos:
            tx, ty = tpos[a["task_id"]]
            lx += [a["x"], tx, None]
            ly += [a["y"], ty, None]
        else:
            lx += [None, None, None]
            ly += [None, None, None]
    traces: list[go.Scattergl] = [go.Scattergl(
        x=lx, y=ly, mode="lines", name="asignaciones",
        line=dict(color="rgba(58,160,255,0.12)", width=1), hoverinfo="skip",
        showlegend=False,
    )]

    traces.append(go.Scattergl(
        x=[b[0] for b in bases], y=[b[1] for b in bases], mode="markers", name="bases",
        marker=dict(symbol="diamond-wide", size=16, color="#19c3d6",
                    line=dict(width=1, color="#bdf3fa")),
        text=[f"base {i}" for i in range(len(bases))], hoverinfo="text", showlegend=False,
    ))

    # --- tasks: ONE constant-length trace over every task id that ever exists.
    # Tasks never move, so positions are constant -> nothing glides; only colour
    # and symbol change (snap, which is correct). Not-yet-arrived tasks are None.
    tx_, ty_, tsym, tcol, tsize, topac, ttxt = [], [], [], [], [], [], []
    for tid in task_ids:
        t = tmap.get(tid)
        if t is None:
            tx_.append(None); ty_.append(None); tsym.append("square")
            tcol.append("#f4b942"); tsize.append(8); topac.append(0); ttxt.append("")
            continue
        status = t["status"]
        prog = float(t.get("progress", 0.0))
        tx_.append(t["x"]); ty_.append(t["y"])
        if status == "done":
            tsym.append("square"); tcol.append("#2a6b48"); topac.append(0.85)
        elif status == "failed":
            tsym.append("x-thin"); tcol.append("#e0484f"); topac.append(1.0)
        else:
            # being worked: amber -> green as it fills, brightening with progress
            tsym.append("square")
            tcol.append(_lerp_color((244, 185, 66), (39, 209, 124), prog))
            topac.append(0.5 + 0.5 * prog)
        tsize.append(_PRIORITY_SIZE.get(t["priority"], 12))
        ttxt.append(f"tarea {t['id']} · prio {t['priority']} · {int(t['progress']*100)}%"
                    + (f" · skill:{t['required_skill']}" if t.get("required_skill") else "")
                    + (f" · mix:{'+'.join(t['required_skills'])}" if t.get("required_skills") else "")
                    + (f" · equipo:{t['required_agents']}"
                       if t.get("required_agents", 1) > 1 and not t.get("required_skills") else ""))
    traces.append(go.Scattergl(
        x=tx_, y=ty_, mode="markers", name="tareas", showlegend=False,
        marker=dict(symbol=tsym, size=tsize, color=tcol, opacity=topac,
                    line=dict(width=1, color=tcol)),
        text=ttxt, hoverinfo="text",
    ))

    # --- agents: id-stable index so each one interpolates smoothly between ticks.
    ax: list[float | None] = []
    ay: list[float | None] = []
    core_c, halo_c, core_s, halo_s, syms, angs, htxt = [], [], [], [], [], [], []
    for aid in agent_ids:
        a = amap.get(aid)
        st_ = a["status"] if a else "failed"
        if a is None or st_ == "failed":
            ax.append(None); ay.append(None)
            core_c.append("#000"); halo_c.append("#000"); core_s.append(8); halo_s.append(16)
            syms.append("circle"); angs.append(0); htxt.append("")
            continue
        ax.append(a["x"]); ay.append(a["y"])
        col = _STATUS_COLOR.get(st_, "#cccccc")
        core_c.append(col); halo_c.append(col)
        base_s = 11.0 + 4.0 * float(a["resources"])  # bigger, clearer drones
        if st_ == "moving" and aid in prev_pos:
            px, py = prev_pos[aid]
            dx, dy = a["x"] - px, a["y"] - py
            if dx * dx + dy * dy > 1e-6:
                syms.append("triangle-up"); angs.append(_math.degrees(_math.atan2(dx, dy)))
            else:
                syms.append("diamond"); angs.append(0)
        elif st_ in ("working", "recharging"):
            syms.append("diamond"); angs.append(0)
        else:
            syms.append("circle"); angs.append(0)
        core_s.append(base_s); halo_s.append(base_s + 15)
        htxt.append(f"agente {a['id']} · {st_} · recursos {int(a['resources']*100)}%"
                    + (f" · {a['skill']}" if a.get("skill") else ""))
    traces.append(go.Scattergl(  # soft glow underneath
        x=ax, y=ay, mode="markers", name="halo", showlegend=False, hoverinfo="skip",
        marker=dict(size=halo_s, color=halo_c, opacity=0.15, line=dict(width=0)),
    ))
    traces.append(go.Scattergl(  # crisp shaped core on top
        x=ax, y=ay, mode="markers", name="agentes", showlegend=False,
        marker=dict(size=core_s, color=core_c, symbol=syms, angle=angs,
                    line=dict(width=0.7, color="rgba(255,255,255,0.4)")),
        text=htxt, hoverinfo="text",
    ))
    return traces


def _animated_map_figure(rec: RunRecording, width: float, height: float,
                         frame_ms: int = 130, shock_tick: int | None = None) -> go.Figure:
    """A play-able, scrubbable map: watch the fleet glide, fail and reorganize."""
    n = len(rec.frames)
    step = max(1, -(-n // 240))  # ceil division -> <= 240 frames
    idxs = list(range(0, n, step))
    if idxs[-1] != n - 1:
        idxs.append(n - 1)

    # Stable, complete id lists so every frame's traces have identical length.
    agent_ids = sorted(a["id"] for a in rec.frames[0]["world"]["agents"])
    task_ids = sorted(t["id"] for t in rec.frames[-1]["world"]["tasks"])

    def _pos(i: int) -> dict[int, tuple[float, float]]:
        return {a["id"]: (a["x"], a["y"]) for a in rec.frames[i]["world"]["agents"]}

    def _is_shock(i: int) -> bool:
        return shock_tick is not None and shock_tick <= i <= shock_tick + 1

    prev: dict[int, tuple[float, float]] = {}
    base = _frame_scatters(rec.frames[idxs[0]], prev, agent_ids, task_ids)
    frames = []
    for i in idxs:
        frames.append(go.Frame(
            data=_frame_scatters(rec.frames[i], prev, agent_ids, task_ids), name=str(i),
            layout=go.Layout(annotations=_hud_annotations(rec.frames[i]["metrics"], _is_shock(i))),
        ))
        prev = _pos(i)

    # WebGL (Scattergl) renders fast and uniformly, so frame == transition gives
    # constant-velocity gliding (no speed-up once the fleet thins after the shock).
    play = dict(label="▶ Reproducir", method="animate",
                args=[None, {"frame": {"duration": frame_ms, "redraw": True},
                             "fromcurrent": True,
                             "transition": {"duration": frame_ms, "easing": "linear"}}])
    pause = dict(label="⏸ Pausa", method="animate",
                 args=[[None], {"frame": {"duration": 0, "redraw": False},
                                "mode": "immediate"}])

    fig = go.Figure(data=base, frames=frames)
    fig.update_layout(
        height=720, margin=dict(l=8, r=8, t=8, b=8),
        plot_bgcolor="#0b0e14", paper_bgcolor=_BG, font=dict(color=_FG),
        showlegend=False,
        annotations=_hud_annotations(rec.frames[idxs[0]]["metrics"], _is_shock(idxs[0])),
        xaxis=dict(range=[0, width], showgrid=True, gridcolor="rgba(80,110,150,0.07)",
                   zeroline=False, showticklabels=False, ticks="", dtick=width / 12),
        yaxis=dict(range=[0, height], showgrid=True, gridcolor="rgba(80,110,150,0.07)",
                   zeroline=False, showticklabels=False, ticks="", dtick=height / 12,
                   scaleanchor="x", scaleratio=1),
        updatemenus=[dict(
            type="buttons", direction="left", x=0.0, y=1.09, xanchor="left",
            showactive=False, bgcolor="#161b25", bordercolor="#27d17c",
            font=dict(color="#e6ebf3"), buttons=[play, pause],
        )],
        sliders=[dict(
            active=0, x=0.0, len=1.0, y=-0.02, pad=dict(t=6),
            currentvalue=dict(prefix="paso ", font=dict(color=_FG, size=12)),
            font=dict(size=9, color="#9aa6b8"),
            transition={"duration": 0},
            steps=[dict(method="animate", label=str(i),
                        args=[[str(i)], {"frame": {"duration": 0, "redraw": True},
                                         "mode": "immediate"}]) for i in idxs],
        )],
    )
    return fig


def _progress_figure(rec: RunRecording, tick: int, shock_tick: int | None) -> go.Figure:
    hist = pd.DataFrame(rec.metrics_history)
    total_agents = hist["agents_total"].iloc[0] if len(hist) else 1
    fig = go.Figure()
    fig.add_trace(go.Scattergl(
        x=hist["tick"], y=hist["mission_completion"] * 100, name="misión %",
        line=dict(color="#27d17c", width=2),
    ))
    fig.add_trace(go.Scattergl(
        x=hist["tick"], y=hist["agents_alive"] / max(total_agents, 1) * 100,
        name="flota viva %", line=dict(color="#3aa0ff", width=2),
    ))
    if "tasks_failed" in hist and hist["tasks_failed"].max() > 0:
        fig.add_trace(go.Scattergl(
            x=hist["tick"], y=hist["tasks_failed"], name="tareas falladas",
            line=dict(color="#e0484f", width=1.5, dash="dot"), yaxis="y2",
        ))
    if shock_tick is not None and shock_tick <= hist["tick"].max():
        fig.add_vline(x=shock_tick, line=dict(color="#e0484f", width=1, dash="dash"),
                      annotation_text="shock", annotation_font_color="#e0484f")
    fig.add_vline(x=tick, line=dict(color="#cdd3df", width=1))
    fig.update_layout(
        height=300, margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor=_BG, paper_bgcolor=_BG, font=dict(color=_FG),
        legend=dict(orientation="h", y=1.12, font=dict(size=10)),
        xaxis=dict(title="tick", gridcolor="#1c2230"),
        yaxis=dict(title="%", range=[0, 105], gridcolor="#1c2230"),
        yaxis2=dict(overlaying="y", side="right", showgrid=False, title="falladas"),
    )
    return fig


_CSS = """
<style>
:root { --gc-green:#27d17c; --gc-blue:#3aa0ff; }
.gc-hero {
  display:flex; align-items:center; gap:16px;
  padding:14px 20px; margin:-8px 0 6px 0; border-radius:14px;
  background:linear-gradient(100deg,#11161f 0%,#0e1117 60%);
  border:1px solid #1d2533;
}
.gc-hero h1 {
  margin:0; font-size:1.55rem; font-weight:800; letter-spacing:.06em;
  background:linear-gradient(90deg,#27d17c,#3aa0ff);
  -webkit-background-clip:text; -webkit-text-fill-color:transparent;
}
.gc-hero p { margin:2px 0 0 0; color:#9aa6b8; font-size:.9rem; }
.gc-side-logo { display:flex; align-items:center; gap:10px; margin-bottom:2px; }
.gc-side-logo span { font-weight:800; letter-spacing:.04em; font-size:1.05rem; color:#e6ebf3; }
.gc-chip {
  display:inline-block; padding:2px 9px; margin:2px 4px 2px 0; border-radius:20px;
  background:#161b25; border:1px solid #232c3b; font-size:.72rem; color:#9aa6b8;
}
[data-testid="stMetricValue"] { font-size:1.5rem; }
</style>
"""


# ----------------------------------------------------------------------- sidebar
_DUR = {"Normal": 1, "Largo (2×)": 2, "Épico (3×)": 3}


def _sidebar() -> tuple[Scenario, str, bool]:
    qp = st.query_params  # shareable URL: defaults come from ?preset=&strategy=&...
    st.sidebar.markdown(
        f'<div class="gc-side-logo">{_logo(34)}<span>GHOST COMMANDER</span></div>',
        unsafe_allow_html=True,
    )
    st.sidebar.caption("Configura la misión aquí y pulsa **Ejecutar misión**.")

    with st.sidebar.expander("ℹ️ Guía rápida de los controles"):
        st.markdown(
            "- **Escenario** = la *situación* a la que se enfrenta la flota. Cada "
            "uno mete un reto distinto. Lee la descripción que sale al elegirlo.\n"
            "- **Estrategia** = el *cerebro* del comandante. Compáralas en 📊.\n"
            "- **Seed** = la semilla del azar. **Misma seed = misma misión**, bit a "
            "bit. Cámbiala para ver *otra* partida del mismo escenario.\n"
            "- **Re-planificación** = el comandante re-evalúa la flota cada tick y "
            "redirige agentes en ruta para rescatar tareas a punto de expirar.\n"
            "- **Duración** = estira la misión en el tiempo. **Velocidad** = solo lo "
            "rápido que se reproduce.\n"
            "- **Ajustes finos** = flota, tareas y límite de tiempo."
        )

    presets = list(PRESETS)
    pidx = presets.index(qp["preset"]) if qp.get("preset") in PRESETS else 0
    preset_name = st.sidebar.selectbox(
        "Escenario (la situación)", presets, index=pidx,
        help="Cada escenario plantea un reto distinto. Elige uno y lee su "
             "descripción justo debajo.")
    base = PRESETS[preset_name]
    st.sidebar.info(_SCENARIO_DESC.get(preset_name, ""))

    strats = list(STRATEGIES)
    sidx = strats.index(qp["strategy"]) if qp.get("strategy") in STRATEGIES \
        else strats.index("global")
    strategy = st.sidebar.selectbox(
        "Estrategia (el cerebro del comandante)", strats, index=sidx,
        help="greedy: lo más cercano (local) · auction/global: miran toda la flota "
             "· triage: tiene en cuenta los plazos · optimal: óptimo exacto por "
             "tick (baseline). Compáralas en 📊.")
    try:
        seed_default = int(qp.get("seed", base.seed))
    except (TypeError, ValueError):
        seed_default = int(base.seed)
    seed = st.sidebar.number_input(
        "Seed (semilla del azar)", min_value=0, value=seed_default, step=1,
        help="Fija el azar de la misión. Misma seed = misma partida idéntica.")

    replan = st.sidebar.checkbox(
        "Re-planificación continua", value=(qp.get("replan") == "1"),
        help="Preempción de rescate: cada tick el comandante puede redirigir a un "
             "agente en ruta para salvar una tarea a punto de expirar. Ayuda bajo "
             "plazos (rush, specialist); mira la diferencia en la pestaña 📊.")

    dur_value = qp["dur"] if qp.get("dur") in _DUR else "Normal"
    dur_label = st.sidebar.select_slider(
        "Duración de la misión", options=list(_DUR), value=dur_value,
        help="Estira la misión en el tiempo (más pasos). El resultado es "
             "prácticamente el mismo; solo cambia cuánto tarda en verse.")
    time_scale = _DUR[dur_label]

    play_label = st.sidebar.select_slider(
        "Velocidad de reproducción", options=["Lento", "Normal", "Rápido"],
        value="Normal", help="Solo cambia lo rápido que va la animación.")
    st.session_state["play_ms"] = {"Lento": 220, "Normal": 130, "Rápido": 70}[play_label]

    with st.sidebar.expander("Ajustes finos (opcional)"):
        st.caption("Cambia el reparto base del escenario. Si no sabes qué tocar, "
                   "déjalo como está.")
        n_agents = st.slider("Agentes (tamaño de la flota)", 10, 300,
                             int(base.n_agents), step=10,
                             help="Cuántas unidades autónomas salen a la misión.")
        n_tasks = st.slider("Tareas iniciales (trabajos a hacer)", 5, 120,
                            int(base.n_tasks), step=5,
                            help="Cuántas tareas hay al empezar (algunos escenarios "
                                 "añaden más sobre la marcha).")
        max_ticks = st.slider("Límite de tiempo (máx. pasos)", 100, 2000,
                              int(base.max_ticks), step=50,
                              help="Si la misión no termina antes, se corta aquí.")

    # reflect the current config in the URL so a run can be shared by link
    st.query_params.update({
        "preset": preset_name, "strategy": strategy, "seed": str(int(seed)),
        "replan": "1" if replan else "0", "dur": dur_label,
    })

    scenario = dataclasses.replace(
        base, seed=int(seed), n_agents=int(n_agents), n_tasks=int(n_tasks),
        max_ticks=int(max_ticks),
    )
    return _time_dilate(scenario, time_scale), strategy, replan


def _time_dilate(sc: Scenario, k: int) -> Scenario:
    """Stretch a scenario over k× more ticks with the same character (same spatial
    paths, same expected losses), so the situation plays out over more time."""
    if k <= 1:
        return sc
    return dataclasses.replace(
        sc,
        agent_speed=sc.agent_speed / k,
        agent_capacity=sc.agent_capacity / k,
        resource_drain_working=sc.resource_drain_working / k,
        resource_drain_moving=sc.resource_drain_moving / k,
        random_failure_rate=sc.random_failure_rate / k,
        shock_tick=None if sc.shock_tick is None else int(sc.shock_tick * k),
        recharge_rate=sc.recharge_rate / k,
        deadline_slack_base=int(sc.deadline_slack_base * k),
        deadline_slack_factor=sc.deadline_slack_factor * k,
        arrival_start_tick=int(sc.arrival_start_tick * k),
        arrival_end_tick=int(sc.arrival_end_tick * k),
        max_ticks=int(sc.max_ticks * k),
    )


def main() -> None:
    st.set_page_config(page_title="Ghost Commander", page_icon="🧭", layout="wide")
    st.markdown(_CSS, unsafe_allow_html=True)
    scenario, strategy, replan = _sidebar()

    run_clicked = st.sidebar.button("▶ Ejecutar misión", type="primary",
                                    use_container_width=True)
    # Auto-run on first load so a freshly deployed app shows something immediately.
    if run_clicked or "rec" not in st.session_state:
        with st.spinner("Simulando…"):
            st.session_state["rec"] = run_scenario(scenario, strategy, replan=replan)
            st.session_state["scenario"] = scenario
            st.session_state["replan"] = replan
            st.session_state["rec_label"] = (
                f"{scenario.name} · {strategy} · seed {scenario.seed} · "
                f"{scenario.n_agents} agentes"
                + (" · re-planificación" if replan else "")
            )

    st.sidebar.markdown(
        "<small>Determinista: misma seed + escenario + estrategia ⇒ misma misión, "
        "bit a bit.<br>[Código en GitHub](https://github.com/JFHelvetius/ghost-commander)"
        "</small>", unsafe_allow_html=True,
    )

    st.markdown(
        f'<div class="gc-hero">{_logo(46)}<div>'
        f'<h1>GHOST COMMANDER</h1>'
        f'<p>Un comandante digital que coordina cientos de agentes autónomos en '
        f'entornos cambiantes, maximizando el éxito de la misión mediante '
        f'reasignación dinámica de recursos.</p></div></div>',
        unsafe_allow_html=True,
    )
    _intro()

    tab_mission, tab_compare, tab_custom, tab_guide = st.tabs(
        ["🛰  Misión", "📊  Comparar estrategias", "✏️  Tu caso", "📖  Guía"])
    with tab_mission:
        _render_mission(st.session_state["rec"], st.session_state.get("scenario", scenario))
    with tab_compare:
        _render_compare(st.session_state.get("scenario", scenario),
                        st.session_state.get("replan", replan))
    with tab_custom:
        _render_custom()
    with tab_guide:
        _render_guide()


def _parse_nl(text: str) -> dict:
    """Tiny local heuristic parser (no API): map a one-liner to scenario settings."""
    import re

    low = text.lower()
    unit = (r"(dron|drone|drones|unidad|unidades|agente|agentes|robot|robots|veh[ií]culo|"
            r"veh[ií]culos|equipo|equipos|convoy|convoyes|rescatador|rescatadores)")
    job = (r"(hospital|hospitales|punto|puntos|entrega|entregas|cliente|clientes|tarea|"
           r"tareas|destino|destinos|parada|paradas|pedido|pedidos|incidencia|incidencias|"
           r"objetivo|objetivos|sector|sectores|posici[oó]n|posiciones|zona|zonas|"
           r"superviviente|supervivientes|v[ií]ctima|v[ií]ctimas|herido|heridos|"
           r"persona|personas|evento|eventos)")
    d: dict = {}
    m1 = re.search(r"(\d+)\s*" + unit, low)
    m2 = re.search(r"(\d+)\s*" + job, low)
    nums = [int(x) for x in re.findall(r"\d+", low)]
    if m1:
        d["agents"] = int(m1.group(1))
    elif nums:
        d["agents"] = nums[0]
    if m2:
        d["tasks"] = int(m2.group(1))
    elif len(nums) >= 2:
        d["tasks"] = nums[1]
    d["deadlines"] = any(w in low for w in
                         ["urgent", "plazo", "deadline", "sangre", "emergencia", "rápid",
                          "rapid", "a tiempo", "antes de", "contra reloj", "rescate",
                          "superviviente", "víctima", "victima", "herido"])
    d["shock"] = any(w in low for w in
                     ["ataque", "tormenta", "choque", "jamming", "interferencia",
                      "guerra electrónica", "guerra electronica", "ew ",
                      "apagón", "apagon", "caída masiva", "caida masiva", "emboscada"])
    d["failures"] = d["shock"] or any(w in low for w in
                                      ["fallo", "fallan", "pierden", "caen", "averí",
                                       "averi", "se rompen", "bajas"])
    d["arrivals"] = any(w in low for w in
                        ["llegan", "nuevas", "nuevos", "sobre la marcha", "dinámic",
                         "dinamic", "continu", "van surgiendo", "aparecen"])
    return d


def _build_custom_scenario(agents: int, tasks: int, area: int, seed: int, deadlines: bool,
                           failures: bool, shock: bool, arrivals: bool) -> Scenario:
    max_ticks = min(2000, max(300, tasks * 10))
    initial = max(1, tasks // 2) if arrivals else tasks
    return Scenario(
        name="custom", seed=int(seed), width=float(area), height=float(area),
        n_agents=int(agents), n_tasks=int(initial), max_ticks=max_ticks,
        random_failure_rate=0.004 if failures else 0.0,
        shock_tick=int(max_ticks * 0.08) if shock else None, shock_failure_rate=0.3,
        deadline_slack_factor=3.0 if deadlines else 0.0, deadline_slack_base=14,
        dynamic_tasks=(tasks - initial) if arrivals else 0,
        arrival_start_tick=5, arrival_end_tick=max(20, max_ticks // 3),
    )


_CC_EXAMPLES = [
    ("🚁 Drones → hospitales", "6 drones que entregan a 30 hospitales, urgente y con fallos"),
    ("📦 Repartidores → pedidos", "20 repartidores y 80 pedidos que van surgiendo"),
    ("🚒 Equipos → incidencias", "15 equipos atienden 50 incidencias tras un ataque"),
    ("🛰 ISR / reconocimiento", "12 drones cubren 40 objetivos con interferencias, urgente"),
    ("🚑 Búsqueda y rescate", "10 equipos de rescate y 40 supervivientes, contra reloj"),
]


def _cc_apply(phrase: str) -> None:
    d = _parse_nl(phrase)
    if "agents" in d:
        st.session_state.cc_agents = min(300, max(1, d["agents"]))
    if "tasks" in d:
        st.session_state.cc_tasks = min(200, max(1, d["tasks"]))
    st.session_state.cc_deadlines = d["deadlines"]
    st.session_state.cc_failures = d["failures"]
    st.session_state.cc_shock = d["shock"]
    st.session_state.cc_arrivals = d["arrivals"]


def _cc_summary() -> str:
    s = st.session_state
    challenges = []
    if s.cc_deadlines:
        challenges.append("plazos")
    if s.cc_failures:
        challenges.append("fallos")
    if s.cc_shock:
        challenges.append("una onda de choque")
    if s.cc_arrivals:
        challenges.append("tareas que van llegando")
    txt = f"**{s.cc_agents} unidades** atendiendo **{s.cc_tasks} puntos**"
    if challenges:
        txt += ", con " + ", ".join(challenges)
    txt += f" · estrategia **{s.cc_strategy}**" + (" + re-planificación" if s.cc_replan else "")
    return txt + "."


def _render_custom() -> None:
    st.markdown("### ✏️ Monta tu propio caso")
    st.markdown(
        "Es un **coordinador genérico** (no usa datos reales): cualquier situación de "
        "*N unidades que atienden M puntos* encaja — drones↔hospitales, "
        "repartidores↔pedidos, bomberos↔incendios… Móntalo y mira cómo se comporta."
    )
    defaults = dict(cc_text="", cc_agents=20, cc_tasks=40, cc_area=200, cc_seed=42,
                    cc_deadlines=False, cc_failures=True, cc_shock=False,
                    cc_arrivals=False, cc_strategy="triage", cc_replan=False)
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)

    st.markdown("**1 · Empieza por un ejemplo** (un clic lo rellena), o escribe tu frase:")
    for row_start in range(0, len(_CC_EXAMPLES), 2):
        pair = _CC_EXAMPLES[row_start:row_start + 2]
        for col, (lab, phrase) in zip(st.columns(2), pair):
            if col.button(lab, use_container_width=True, key=f"ex_{row_start}_{lab}"):
                st.session_state.cc_text = phrase
                _cc_apply(phrase)
                st.rerun()
    st.text_input("Descríbelo en una frase", key="cc_text",
                  placeholder="p. ej.: 6 drones que entregan a 30 hospitales, urgente")
    if st.button("✨ Interpretar la frase"):
        _cc_apply(st.session_state.cc_text)
        st.rerun()

    st.markdown("**2 · Ajusta los detalles** (la flota y los objetivos):")
    c1, c2, c3 = st.columns(3)
    c1.number_input("🚁 Unidades", 1, 300, key="cc_agents")
    c2.number_input("🎯 Puntos / tareas", 1, 200, key="cc_tasks")
    c3.number_input("🗺️ Tamaño del área", 50, 500, step=10, key="cc_area")
    c4, c5 = st.columns(2)
    c4.selectbox("🧠 Estrategia (cómo coordina)", list(STRATEGIES), key="cc_strategy")
    c5.number_input("🎲 Seed (el azar)", 0, key="cc_seed")

    st.markdown("**¿Qué puede salir mal?**")
    cc = st.columns(2)
    cc[0].checkbox("⏱️ Plazos / urgencias (las tareas pueden fallar)", key="cc_deadlines")
    cc[0].checkbox("⚠️ Fallos / pérdidas de unidades", key="cc_failures")
    cc[1].checkbox("💥 Una onda de choque tumba a muchas de golpe", key="cc_shock")
    cc[1].checkbox("📥 Llegan tareas nuevas durante la misión", key="cc_arrivals")
    st.checkbox("🔁 Re-planificación continua (redirige unidades para rescatar tareas)",
                key="cc_replan")

    st.info("Vas a simular: " + _cc_summary())

    st.markdown("**3 · Lánzalo** 👇")
    if st.button("▶ Ejecutar mi caso", type="primary", use_container_width=True):
        sc = _build_custom_scenario(
            st.session_state.cc_agents, st.session_state.cc_tasks, st.session_state.cc_area,
            st.session_state.cc_seed, st.session_state.cc_deadlines,
            st.session_state.cc_failures, st.session_state.cc_shock,
            st.session_state.cc_arrivals)
        st.session_state["rec"] = run_scenario(sc, st.session_state.cc_strategy,
                                               replan=st.session_state.cc_replan)
        st.session_state["scenario"] = sc
        st.session_state["replan"] = st.session_state.cc_replan
        st.session_state["rec_label"] = (
            f"tu caso · {st.session_state.cc_strategy} · {st.session_state.cc_agents} "
            f"unidades / {st.session_state.cc_tasks} puntos")
        st.rerun()

    # show the result right here so a first-timer doesn't have to switch tabs
    sc = st.session_state.get("scenario")
    if sc is not None and getattr(sc, "name", "") == "custom" and "rec" in st.session_state:
        rec = st.session_state["rec"]
        st.divider()
        st.markdown("#### 🛰 Resultado de tu caso")
        _render_mission(rec, sc, key_prefix="cc_")
        comp = rec.final_metrics["mission_completion"]
        if comp >= 0.999:
            st.caption("💡 Salió redondo. Sube las **tareas** o baja las **unidades** "
                       "para encontrar el punto de ruptura.")
        elif comp < 0.8:
            st.caption("💡 Se perdió bastante misión. Prueba con **más unidades**, la "
                       "estrategia **triage**, o activa **re-planificación** y vuelve a lanzar.")
        else:
            st.caption("💡 Prueba a cambiar la **estrategia** o a comparar las 5 en la "
                       "pestaña 📊 con este mismo caso.")


def _render_guide() -> None:
    """Side-by-side reference so the user sees the *differences*, not one at a time."""
    st.markdown("#### Los escenarios — *en qué se diferencian*")
    st.caption("Cada escenario plantea un reto distinto del problema de coordinación. "
               "Pruébalos y mira cómo cambia la misión.")
    st.markdown(
        "| Escenario | El reto que añade |\n|---|---|\n"
        + "\n".join(f"| **{name}** | {_SCENARIO_DIFF.get(name, '')} |" for name in PRESETS)
    )

    st.markdown("#### Las estrategias — *cómo piensa cada comandante*")
    st.caption("Mismo escenario y seed, solo cambia esto. La diferencia que ves es "
               "pura coordinación. Compáralas en la pestaña 📊.")
    st.markdown(
        "| Estrategia | Cómo decide | Brilla cuando… |\n|---|---|---|\n"
        + "\n".join(f"| **{name}** | {how} | {when} |"
                    for name, (how, when) in _STRATEGY_GUIDE.items())
    )

    st.markdown("#### Cómo leer el mapa")
    st.markdown(
        "- **Drones** = puntos con halo. *Color* = qué hacen (🟩 trabajando · 🟦 en "
        "ruta · ⬜ libre · 🟪 recargando); *forma* = ▲ en ruta / ◆ en una tarea / ● "
        "libre; *tamaño* = recursos que le quedan. Si cae, desaparece.\n"
        "- **Tareas** = cuadrados (tamaño = prioridad) que pasan de 🟧 ámbar a 🟩 "
        "verde según se completan · ✖️ roja = fallada (no llegó a tiempo) · 🔷 = base.\n"
        "- **Líneas azules** = las asignaciones del comandante (qué dron va a qué "
        "tarea); míralas reorganizarse tras la onda de choque.\n"
        "- El **HUD** de arriba del mapa y el **gráfico de progreso** se actualizan "
        "en vivo durante la reproducción."
    )
    st.info("Todo es **determinista**: misma seed + escenario + estrategia ⇒ misma "
            "misión, bit a bit. Por eso el replay es exacto y la comparación es justa.")


def _intro() -> None:
    """Explain what the demo is and how to read it — for first-time visitors."""
    with st.expander("👋 ¿Qué es esto y cómo se usa? (léelo si es tu primera vez)",
                     expanded=True):
        st.markdown(
            """
**El problema.** Cientos de agentes autónomos (drones, vehículos, robots) deben
completar un campo de tareas repartidas en un mapa. Pero el mundo cambia: los
agentes **fallan**, una **onda de choque** tumba a un tercio de la flota de
golpe, llegan **tareas nuevas** a mitad de misión, algunas exigen un **tipo**
concreto de agente o un **equipo** completo, y los recursos **se agotan**. El
comandante digital reasigna la flota en tiempo real para salvar la misión.

**Cómo leer el mapa.**

- **Agentes** = los puntos con halo. El **color** dice qué hacen: 🟩 verde
  trabajando · 🟦 azul yendo a una tarea · ⬜ gris libre · 🟪 morado recargando.
  La **forma** también: ▲ nave (se mueve, apunta a su destino) · ◆ rombo (en una
  tarea o base) · ● círculo (libre). Más grande = más recursos. Si un agente
  cae, **desaparece** del mapa.
- **Tareas** = cuadrados, tamaño según prioridad: 🟧 ámbar pendiente · ▫️
  atenuado hecha · ✖️ roja **fallada** (no llegó a tiempo). 🔷 rombo cian = base
  de recarga.
- **Líneas azules tenues** = las asignaciones del comandante (qué agente va a qué
  tarea). Míralas **reorganizarse** tras la onda de choque.

**Cómo se usa.** Pulsa **▶ Reproducir** sobre el mapa para ver la misión en
movimiento (o arrastra el control de **pasos** para ir tú mismo). En la barra
lateral cambias el **escenario** y la **estrategia** y pulsas **Ejecutar misión**
— cada control tiene una **ℹ️** que lo explica, y arriba del todo hay una *guía
rápida*. En la pestaña 📊 comparas estrategias: mismo escenario y seed, *solo
cambia el algoritmo*, así que la diferencia es pura coordinación.

> El proyecto modela 8 dimensiones del problema real (fallos, deadlines,
> entornos cambiantes, especialización, recuperación, cooperación…), todas
> deterministas y reproducibles. El dashboard es solo la ventana; el motor está
> en [GitHub](https://github.com/JFHelvetius/ghost-commander).
"""
        )


def _shock_kills(rec: RunRecording, shock_tick: int) -> int:
    hist = {int(h["tick"]): int(h["agents_alive"]) for h in rec.metrics_history}
    if not hist:
        return 0
    before = hist.get(shock_tick - 1, hist.get(shock_tick, 0))
    after = hist.get(shock_tick + 2, hist.get(shock_tick + 1, before))
    return max(0, before - after)


def _narrative(rec: RunRecording, scenario: Scenario) -> tuple[str, str]:
    """Plain-language story of what happened this mission — returns (level, text)."""
    init = rec.frames[0]["metrics"]
    m = rec.final_metrics
    n_agents = int(m["agents_total"])
    init_tasks, final_tasks = int(init["tasks_total"]), int(m["tasks_total"])
    done, failed = int(m["tasks_done"]), int(m.get("tasks_failed", 0))
    pct = m["mission_completion"] * 100
    lost = n_agents - int(m["agents_alive"])

    p = [f"Una flota de **{n_agents} agentes** (unidades autónomas) salió a completar "
         f"**{init_tasks} tareas** repartidas por el mapa."]
    if final_tasks > init_tasks:
        p.append(f"Sobre la marcha llegaron **{final_tasks - init_tasks} tareas nuevas** "
                 f"(el entorno cambia), hasta **{final_tasks}** en total.")
    if scenario.shock_tick is not None and (k := _shock_kills(rec, scenario.shock_tick)) > 0:
        p.append(f"En el **tick {scenario.shock_tick}** una **onda de choque** destruyó "
                 f"**{k} agentes** de golpe.")
    if lost > 0:
        p.append(f"En total se perdieron **{lost} de {n_agents} agentes** "
                 f"(**{lost / n_agents * 100:.0f}%** de la flota).")
    if int(m.get("recharges", 0)) > 0:
        p.append(f"Las bases de recarga permitieron **{int(m['recharges'])} repostajes** "
                 f"para sostener la flota.")
    if failed == 0 and done == final_tasks:
        if lost > 0 or final_tasks > init_tasks:
            p.append(f"Aun así, el comandante reasignó las tareas huérfanas a las "
                     f"supervivientes y la flota **completó las {done} tareas (100%)**. "
                     f"Eso es coordinación.")
        else:
            p.append(f"El comandante coordinó la flota sin incidencias y **completó las "
                     f"{done} tareas (100%)**.")
        return "success", " ".join(p)
    p.append(f"El comandante salvó **{done} de {final_tasks} tareas** "
             f"(**{pct:.0f}%**, ponderado por prioridad)"
             + (f"; **{failed} no llegaron a tiempo**." if failed else "."))
    return "warning", " ".join(p)


def _event_feed(rec: RunRecording, scenario: Scenario) -> str:
    """A readable, aggregated 'what happened' feed instead of raw event rows."""
    from collections import defaultdict

    shock: dict[int, int] = defaultdict(int)
    losses: dict[int, int] = defaultdict(int)
    task_fail: dict[int, int] = defaultdict(int)
    arrivals: dict[int, int] = defaultdict(int)
    end: tuple[int, str] | None = None
    for e in rec.events:
        t, tick = e["type"], e["tick"]
        if t == "agent.failed":
            (shock if e.get("p_kind") == "shock" else losses)[tick] += 1
        elif t == "task.failed":
            task_fail[tick] += 1
        elif t == "task.created":
            arrivals[tick] += 1
        elif t == "mission.complete":
            end = (tick, "🏁 **Misión completada**: todas las tareas hechas.")
        elif t == "mission.degraded":
            end = (tick, "🏳️ **Misión degradada**: se agotó el tiempo con tareas sin "
                   "completar.")

    rows: list[tuple[int, str]] = []
    for tk, n in shock.items():
        rows.append((tk, f"💥 **{n} agentes** caídos por la onda de choque"))
    for tk, n in losses.items():
        if n >= 3:  # only notable loss spikes, to avoid one-liner spam
            rows.append((tk, f"⚠️ {n} agentes perdidos"))
    for tk, n in task_fail.items():
        rows.append((tk, f"⏱️ {n} tarea(s) **fallada(s)** (deadline perdido)"))
    if arrivals:
        a0, a1 = min(arrivals), max(arrivals)
        total = sum(arrivals.values())
        rows.append((a0, f"📥 empiezan a llegar tareas nuevas (**{total}** entre los "
                     f"ticks {a0}–{a1})"))
    if end:
        rows.append(end)

    rows.sort(key=lambda r: r[0])
    if not rows:
        return "_Misión tranquila: sin incidencias destacables._"
    return "\n".join(f"- **tick {tk}** · {txt}" for tk, txt in rows[:30])


def _render_mission(rec: RunRecording, scenario: Scenario, key_prefix: str = "") -> None:
    # key_prefix namespaces the chart/table ids so this view can render in two
    # tabs at once (Misión + the inline result in "Tu caso") without id clashes.
    st.caption("Resultado de: " + st.session_state.get("rec_label", ""))

    level, story = _narrative(rec, scenario)
    (st.success if level == "success" else st.warning)("🛰 " + story)

    m = rec.final_metrics  # the cards summarize the *outcome* of the mission
    failed = int(m.get("tasks_failed", 0))
    cols = st.columns(5)
    cols[0].metric("Misión completada", f"{m['mission_completion'] * 100:.0f}%",
                   help="Porcentaje de tareas completadas, ponderado por prioridad "
                        "(las urgentes pesan más).")
    cols[1].metric("Tareas hechas", f"{m['tasks_done']}/{m['tasks_total']}",
                   help="Tareas completadas sobre el total de la misión.")
    cols[2].metric("Tareas falladas", failed,
                   delta=None if failed == 0 else f"-{failed}", delta_color="inverse",
                   help="Tareas que no se completaron a tiempo (deadline perdido).")
    cols[3].metric("Agentes perdidos", f"{m['agents_total'] - m['agents_alive']}/{m['agents_total']}",
                   help="Unidades que se perdieron durante la misión.")
    cols[4].metric("Reasignaciones", int(m["reassignments"]),
                   help="Veces que el comandante movió una tarea a otra unidad tras "
                        "perder a la asignada. Es la 'reorganización' en acción.")

    st.markdown("##### ▶ Pulsa **Reproducir** sobre el mapa para ver la misión en vivo "
                "(el HUD de arriba se actualiza solo)")
    # Map full width so each drone is clearly visible.
    st.plotly_chart(
        _animated_map_figure(rec, _world_w(rec), _world_h(rec),
                             frame_ms=int(st.session_state.get("play_ms", 130)),
                             shock_tick=scenario.shock_tick),
        use_container_width=True, key=f"{key_prefix}map",
    )
    st.caption("**Drones** (color = qué hacen, forma = ▲ en ruta / ◆ en una tarea / "
               "● libre, tamaño = recursos): 🟩 trabajando · 🟦 yendo · ⬜ libre · "
               "🟪 recargando. **Tareas**: cuadrados que pasan de 🟧 ámbar a 🟩 verde "
               "según se completan · ✖️ roja = fallada · 🔷 = base. Las líneas azules "
               "son las asignaciones del comandante.")

    left, right = st.columns([3, 2])
    with left:
        st.markdown("**Progreso a lo largo del tiempo**")
        st.plotly_chart(
            _progress_figure(rec, len(rec.frames) - 1, scenario.shock_tick),
            use_container_width=True, key=f"{key_prefix}prog",
        )
        st.caption("Verde = % de misión · azul = flota viva · raya roja = onda de choque.")
    with right:
        st.markdown("**Qué pasó, en orden**")
        st.markdown(_event_feed(rec, scenario))
        with st.expander("Registro técnico completo"):
            ev = pd.DataFrame(rec.events)
            if not ev.empty:
                st.dataframe(ev.tail(300), use_container_width=True, height=240,
                             hide_index=True, key=f"{key_prefix}evt")


_STRAT_COLOR = {
    "greedy": "#e0484f", "auction": "#f4b942", "global": "#3aa0ff",
    "triage": "#27d17c", "optimal": "#b06cff",
}


def _render_compare(scenario: Scenario, replan: bool = False) -> None:
    st.markdown("### ¿Qué forma de coordinar salva más misión?")
    st.markdown(
        f"Corremos la **misma misión exacta** — mismo mapa, mismos fallos, misma onda "
        f"de choque, misma seed (escenario **{scenario.name}**, {scenario.n_agents} "
        f"agentes{', re-planificación ON' if replan else ''}) — y **solo cambiamos el "
        "cerebro del comandante** (la estrategia). Como es 100% determinista, la única "
        "diferencia en el resultado es el algoritmo: la comparación es **justa**."
    )
    st.info(
        "**Lo que se mide → «misión completada (%)»**: el porcentaje de tareas "
        "resueltas, *ponderado por prioridad* (perder una tarea VITAL pesa mucho más "
        "que una LOW). Más alto = mejor coordinación. La pregunta no es académica: "
        "es *cuántos objetivos salva cada forma de mandar a la flota*."
    )
    with st.expander("¿Qué hace cada estrategia?"):
        st.markdown(
            "- **greedy** — cada unidad va a la mejor tarea más cercana (decisión local).\n"
            "- **auction / global** — reparten mirando a toda la flota a la vez.\n"
            "- **triage** — como global, pero además tiene en cuenta los *plazos*.\n"
            "- **optimal** — el óptimo exacto por tick (algoritmo húngaro): el **techo** "
            "de referencia para ese objetivo."
        )

    if not st.button(f"▶ Comparar las {len(STRATEGIES)} estrategias en este escenario",
                     type="primary", use_container_width=True):
        return
    with st.spinner("Corriendo " + " / ".join(STRATEGIES) + "…"):
        recs = {name: run_scenario(scenario, name, replan=replan) for name in STRATEGIES}
    results = sorted(
        (StrategyResult.from_recording(recs[n]) for n in STRATEGIES),
        key=lambda r: (-r.completion, r.ticks_to_finish or 10**9, r.reassignments),
    )
    opt = recs["optimal"].final_metrics["mission_completion"] or 1e-9

    st.success("🏆 " + _interpret_compare(results, opt))

    bar = go.Figure(go.Bar(
        x=[r.strategy for r in results], y=[r.completion * 100 for r in results],
        marker_color=_RANK_COLORS[: len(results)],
        text=[f"{r.completion*100:.0f}%<br><span style='font-size:10px'>"
              f"{r.tasks_failed} falladas</span>" for r in results],
        textposition="outside",
    ))
    bar.update_layout(
        title="Misión completada por estrategia (más alto = mejor)", height=340,
        plot_bgcolor=_BG, paper_bgcolor=_BG, font=dict(color=_FG),
        yaxis=dict(range=[0, 112], title="misión %  (ponderado por prioridad)",
                   gridcolor="#1c2230"),
    )
    st.plotly_chart(bar, use_container_width=True)
    st.caption("Altura de la barra = % de la misión que esa estrategia logró salvar.")

    # how each strategy progresses over time — not just the endpoint
    lines = go.Figure()
    for name in STRATEGIES:
        h = pd.DataFrame(recs[name].metrics_history)
        lines.add_trace(go.Scatter(
            x=h["tick"], y=h["mission_completion"] * 100, name=name,
            line=dict(color=_STRAT_COLOR.get(name, "#cccccc"), width=2)))
    if scenario.shock_tick is not None:
        lines.add_vline(x=scenario.shock_tick, line=dict(color="#e0484f", width=1, dash="dash"),
                        annotation_text="shock", annotation_font_color="#e0484f")
    lines.update_layout(
        title="Progreso en el tiempo: cómo llega cada una al resultado", height=320,
        plot_bgcolor=_BG, paper_bgcolor=_BG, font=dict(color=_FG),
        legend=dict(orientation="h", y=1.12, font=dict(size=10)),
        xaxis=dict(title="tick (paso de tiempo)", gridcolor="#1c2230"),
        yaxis=dict(title="misión %", range=[0, 105], gridcolor="#1c2230"))
    st.plotly_chart(lines, use_container_width=True)
    st.caption("Cada línea es una estrategia. Fíjate en la **raya roja** (la onda de "
               "choque): ahí todas caen o se estancan, y se ve **quién se reorganiza "
               "antes y llega más alto**.")

    st.markdown("**Detalle por estrategia** (ordenado de mejor a peor):")
    df = pd.DataFrame([
        {
            "estrategia": r.strategy,
            "misión %": round(r.completion * 100, 1),
            "% del óptimo": round(r.completion / opt * 100),
            "tareas hechas": f"{r.tasks_done}/{r.tasks_total}",
            "falladas": r.tasks_failed,
            "ticks": r.ticks_to_finish if r.ticks_to_finish is not None else "—",
            "agentes perdidos": r.agents_lost,
            "reasignaciones": r.reassignments,
        }
        for r in results
    ])
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption("**misión %** = cuánto salvó · **% del óptimo** = respecto al máximo "
               "posible por tick (>100% significa que batió al óptimo *miope* mirando "
               "plazos) · **falladas** = tareas perdidas por deadline · **ticks** = en "
               "cuántos pasos cerró · **reasignaciones** = veces que reorganizó la flota.")

    st.markdown(
        "> **El sentido de todo esto:** no hay un ganador universal. La mejor forma de "
        "coordinar **depende de la situación** — `greedy` se hunde bajo presión, "
        "`triage` brilla cuando los plazos aprietan, `optimal` marca el techo por tick "
        "pero es miope. Cambia de **escenario** en la barra lateral y vuelve a comparar: "
        "ese es justo el problema que resuelve un comandante de verdad."
    )


def _interpret_compare(results: list, opt: float) -> str:
    """One-sentence plain-language read of the comparison."""
    win, worst = results[0], results[-1]
    by = {r.strategy: r for r in results}
    parts = [f"Ganó **{win.strategy}** ({win.completion*100:.0f}%)."]
    if "greedy" in by and by["greedy"].strategy != win.strategy:
        g = by["greedy"]
        parts.append(f"**greedy** es de las peores ({g.completion*100:.0f}%"
                     + (f", {g.tasks_failed} tareas perdidas" if g.tasks_failed else "") + ").")
    heur = [r for r in results if r.strategy != "optimal"]
    if heur and opt > 0:
        lo = min(r.completion / opt * 100 for r in heur)
        hi = max(r.completion / opt * 100 for r in heur)
        parts.append(f"Las heurísticas alcanzan **{lo:.0f}–{hi:.0f}%** del óptimo-por-tick.")
        if hi > 100.5:
            parts.append("Alguna *supera* al óptimo-por-tick: es **miope** (no mira "
                         "plazos), y triage sí.")
    return " ".join(parts)


def _world_w(rec: RunRecording) -> float:
    return rec.frames[0]["world"].get("width") or 200.0  # type: ignore[return-value]


def _world_h(rec: RunRecording) -> float:
    return rec.frames[0]["world"].get("height") or 200.0  # type: ignore[return-value]


if __name__ == "__main__":
    main()
