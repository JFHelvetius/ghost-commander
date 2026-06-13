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
from ghost_commander.sim import PRESETS, Scenario, compare_strategies, run_scenario
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
_RANK_COLORS = ["#27d17c", "#7fcf7a", "#f4b942", "#e0484f"]

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
}


# --------------------------------------------------------------------------- map
# Fixed trace order so Plotly can animate frame-to-frame (trace count is constant).
_AGENT_ORDER = ["idle", "moving", "working", "recharging"]


def _frame_scatters(frame: dict) -> list[go.Scatter]:
    """Build the fixed list of traces for one tick (links, bases, tasks, agents)."""
    world = frame["world"]
    agents = world["agents"]
    tasks = world["tasks"]
    bases = world.get("bases", [])
    tpos = {t["id"]: (t["x"], t["y"]) for t in tasks}

    # assignment links: see the commander wiring agents to tasks (and rewiring it).
    lx: list[float | None] = []
    ly: list[float | None] = []
    for a in agents:
        if a["status"] in ("moving", "working") and a.get("task_id") in tpos:
            tx, ty = tpos[a["task_id"]]
            lx += [a["x"], tx, None]
            ly += [a["y"], ty, None]
    traces: list[go.Scatter] = [go.Scatter(
        x=lx, y=ly, mode="lines", name="asignaciones",
        line=dict(color="rgba(58,160,255,0.22)", width=1), hoverinfo="skip",
        showlegend=False,
    )]

    traces.append(go.Scatter(
        x=[b[0] for b in bases], y=[b[1] for b in bases], mode="markers", name="bases",
        marker=dict(symbol="diamond", size=15, color="#19c3d6",
                    line=dict(width=1, color="#bdf3fa")),
        text=[f"base {i}" for i in range(len(bases))], hoverinfo="text",
    ))

    def _bucket(t: dict) -> str:
        return t["status"] if t["status"] in ("done", "failed") else "open"

    task_styles = {
        "open": ("square", "#f4b942", "#f4b942"),
        "done": ("square-open", "#33406b", "#33406b"),
        "failed": ("x", "#e0484f", "#e0484f"),
    }
    for bucket, (symbol, color, line) in task_styles.items():
        sel = [t for t in tasks if _bucket(t) == bucket]
        traces.append(go.Scatter(
            x=[t["x"] for t in sel], y=[t["y"] for t in sel], mode="markers",
            name=f"tarea · {bucket}",
            marker=dict(symbol=symbol, size=[_PRIORITY_SIZE.get(t["priority"], 12) for t in sel],
                        color=color, line=dict(width=1, color=line)),
            text=[f"tarea {t['id']} · prio {t['priority']} · {int(t['progress']*100)}%"
                  + (f" · skill:{t['required_skill']}" if t.get("required_skill") else "")
                  + (f" · equipo:{t['required_agents']}" if t.get("required_agents", 1) > 1 else "")
                  for t in sel],
            hoverinfo="text",
        ))

    for status in _AGENT_ORDER:
        sel = [a for a in agents if a["status"] == status]
        traces.append(go.Scatter(
            x=[a["x"] for a in sel], y=[a["y"] for a in sel], mode="markers",
            name=f"agente · {status}",
            marker=dict(size=9 if status == "working" else 8, color=_STATUS_COLOR[status],
                        line=dict(width=1, color="rgba(255,255,255,0.18)")),
            text=[f"agente {a['id']} · {a['status']} · recursos {int(a['resources']*100)}%"
                  + (f" · {a['skill']}" if a.get("skill") else "") for a in sel],
            hoverinfo="text",
        ))
    return traces


def _animated_map_figure(rec: RunRecording, width: float, height: float) -> go.Figure:
    """A play-able, scrubbable map: watch the fleet move, fail and reorganize."""
    n = len(rec.frames)
    step = max(1, n // 90)  # cap frames so the payload stays light
    idxs = list(range(0, n, step))
    if idxs[-1] != n - 1:
        idxs.append(n - 1)

    base = _frame_scatters(rec.frames[idxs[0]])
    frames = [go.Frame(data=_frame_scatters(rec.frames[i]), name=str(i)) for i in idxs]

    def _btn(label: str, dur: int | None) -> dict:
        args = [None, {"frame": {"duration": dur, "redraw": True},
                       "fromcurrent": True, "transition": {"duration": 0}}] if dur \
            else [[None], {"frame": {"duration": 0, "redraw": False}, "mode": "immediate"}]
        return dict(label=label, method="animate", args=args)

    fig = go.Figure(data=base, frames=frames)
    fig.update_layout(
        height=600, margin=dict(l=8, r=8, t=8, b=8),
        plot_bgcolor=_BG, paper_bgcolor=_BG, font=dict(color=_FG),
        legend=dict(orientation="h", y=1.03, font=dict(size=9), bgcolor="rgba(0,0,0,0)"),
        xaxis=dict(range=[0, width], showgrid=False, zeroline=False, visible=False),
        yaxis=dict(range=[0, height], showgrid=False, zeroline=False, visible=False,
                   scaleanchor="x", scaleratio=1),
        updatemenus=[dict(
            type="buttons", direction="left", x=0.0, y=1.10, xanchor="left",
            showactive=False, bgcolor="#161b25", bordercolor="#27d17c",
            font=dict(color="#e6ebf3"),
            buttons=[_btn("▶ Reproducir", 110), _btn("⏸ Pausa", None)],
        )],
        sliders=[dict(
            active=len(idxs) - 1, x=0.0, len=1.0, y=-0.02, pad=dict(t=6),
            currentvalue=dict(prefix="paso ", font=dict(color=_FG, size=12)),
            font=dict(size=9, color="#9aa6b8"),
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
    fig.add_trace(go.Scatter(
        x=hist["tick"], y=hist["mission_completion"] * 100, name="misión %",
        line=dict(color="#27d17c", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=hist["tick"], y=hist["agents_alive"] / max(total_agents, 1) * 100,
        name="flota viva %", line=dict(color="#3aa0ff", width=2),
    ))
    if "tasks_failed" in hist and hist["tasks_failed"].max() > 0:
        fig.add_trace(go.Scatter(
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
def _sidebar() -> tuple[Scenario, str]:
    st.sidebar.markdown(
        f'<div class="gc-side-logo">{_logo(34)}<span>GHOST COMMANDER</span></div>',
        unsafe_allow_html=True,
    )
    st.sidebar.caption("Coordinación dinámica de cientos de agentes autónomos")

    preset_name = st.sidebar.selectbox("Escenario", list(PRESETS), index=0)
    base = PRESETS[preset_name]
    st.sidebar.info(_SCENARIO_DESC.get(preset_name, ""))

    strategy = st.sidebar.selectbox(
        "Estrategia de coordinación", list(STRATEGIES),
        index=list(STRATEGIES).index("global"),
        help="greedy: local · auction: por tarea · global: óptimo aprox. · "
             "triage: consciente de deadlines",
    )
    seed = st.sidebar.number_input("Seed", min_value=0, value=int(base.seed), step=1)

    with st.sidebar.expander("Ajustes finos"):
        n_agents = st.slider("Agentes", 10, 300, int(base.n_agents), step=10)
        n_tasks = st.slider("Tareas (iniciales)", 5, 120, int(base.n_tasks), step=5)
        max_ticks = st.slider("Máx. ticks", 100, 1000, int(base.max_ticks), step=50)

    scenario = dataclasses.replace(
        base, seed=int(seed), n_agents=int(n_agents), n_tasks=int(n_tasks),
        max_ticks=int(max_ticks),
    )
    return scenario, strategy


def main() -> None:
    st.set_page_config(page_title="Ghost Commander", page_icon="🧭", layout="wide")
    st.markdown(_CSS, unsafe_allow_html=True)
    scenario, strategy = _sidebar()

    run_clicked = st.sidebar.button("▶ Ejecutar misión", type="primary",
                                    use_container_width=True)
    # Auto-run on first load so a freshly deployed app shows something immediately.
    if run_clicked or "rec" not in st.session_state:
        with st.spinner("Simulando…"):
            st.session_state["rec"] = run_scenario(scenario, strategy)
            st.session_state["scenario"] = scenario
            st.session_state["rec_label"] = (
                f"{scenario.name} · {strategy} · seed {scenario.seed} · "
                f"{scenario.n_agents} agentes"
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

    tab_mission, tab_compare = st.tabs(["🛰  Misión", "📊  Comparar estrategias"])
    with tab_mission:
        _render_mission(st.session_state["rec"], st.session_state.get("scenario", scenario))
    with tab_compare:
        _render_compare(scenario)


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

- 🟩 **verde** trabajando · 🟦 **azul** en ruta · ⬜ **gris** libre · 🟪 **morado** recargando · 🟥 caído
- ⬛ **cuadrados** = tareas (tamaño = prioridad) · ▢ atenuado = hecha · ✕ roja = **fallada** (deadline perdido) · ◆ = base de recarga
- Arrastra el **replay** para rebobinar la misión tick a tick. La línea roja
  punteada del gráfico marca la onda de choque.

**Pruébalo.** Cambia el **escenario** (barra lateral) y compara estrategias en
la pestaña 📊: con el mismo escenario y seed, *solo cambia el algoritmo*, así que
la diferencia que ves es pura coordinación.

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


def _render_mission(rec: RunRecording, scenario: Scenario) -> None:
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

    st.markdown("##### ▶ Pulsa **Reproducir** para ver la misión en movimiento")
    left, right = st.columns([3, 2])
    with left:
        st.plotly_chart(
            _animated_map_figure(rec, _world_w(rec), _world_h(rec)),
            use_container_width=True,
        )
        st.caption("🟩 trabajando · 🟦 en ruta · ⬜ libre · 🟪 recargando — "
                   "🟧 tarea pendiente · ▫️ tarea hecha · ✖️ tarea fallada · 🔷 base. "
                   "Las líneas azules tenues son las asignaciones del comandante: "
                   "míralas **recablearse** tras la onda de choque.")
    with right:
        st.markdown("**Progreso a lo largo del tiempo**")
        st.plotly_chart(
            _progress_figure(rec, len(rec.frames) - 1, scenario.shock_tick),
            use_container_width=True,
        )
        st.caption("Verde = % de misión · azul = flota viva · raya roja = onda de choque.")
        with st.expander("Ver registro de eventos"):
            ev = pd.DataFrame(rec.events)
            if not ev.empty:
                notable = ev[ev["severity"].isin(["WARN", "ERROR", "CRITICAL", "INFO"])]
                st.dataframe(notable.tail(200), use_container_width=True, height=240)


def _render_compare(scenario: Scenario) -> None:
    st.markdown(
        "**¿La forma de repartir el trabajo cambia el resultado?** Aquí corremos la "
        f"**misma misión** (escenario **{scenario.name}**, {scenario.n_agents} agentes) "
        "con cada una de las 4 estrategias de coordinación y comparamos cuánto salva "
        "cada una. Como todo es determinista, lo único que cambia es el algoritmo — "
        "así que la diferencia es justa.\n\n"
        "- **greedy**: cada unidad va a la tarea buena más cercana (decisión local).\n"
        "- **auction / global**: reparten mirando a toda la flota a la vez.\n"
        "- **triage**: además mira los *plazos* y no malgasta unidades en tareas que "
        "ya no llegan a tiempo."
    )
    if not st.button(f"▶ Comparar las {len(STRATEGIES)} estrategias",
                     type="primary", use_container_width=True):
        return
    with st.spinner("Corriendo " + " / ".join(STRATEGIES) + "…"):
        results = compare_strategies(scenario)

    df = pd.DataFrame([
        {
            "estrategia": r.strategy,
            "misión %": round(r.completion * 100, 1),
            "tareas": f"{r.tasks_done}/{r.tasks_total}",
            "falladas": r.tasks_failed,
            "ticks": r.ticks_to_finish if r.ticks_to_finish is not None else "—",
            "agentes perdidos": r.agents_lost,
            "reasignaciones": r.reassignments,
        }
        for r in results
    ])
    st.dataframe(df, use_container_width=True, hide_index=True)

    fig = go.Figure(go.Bar(
        x=[r.strategy for r in results],
        y=[r.completion * 100 for r in results],
        marker_color=_RANK_COLORS[: len(results)],
        text=[f"{r.completion*100:.0f}%<br><span style='font-size:10px'>"
              f"{r.tasks_failed} falladas</span>" for r in results],
        textposition="outside",
    ))
    fig.update_layout(
        title="Éxito de misión por estrategia (ponderado por prioridad)", height=380,
        plot_bgcolor=_BG, paper_bgcolor=_BG, font=dict(color=_FG),
        yaxis=dict(range=[0, 112], title="misión ponderada %", gridcolor="#1c2230"),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.success(f"🏆 Ganador en este escenario: **{results[0].strategy}** "
               f"({results[0].completion*100:.0f}%)")
    st.caption("El ganador cambia según la misión: greedy suele ser el peor bajo "
               "presión; triage destaca cuando los deadlines aprietan.")


def _world_w(rec: RunRecording) -> float:
    return rec.frames[0]["world"].get("width") or 200.0  # type: ignore[return-value]


def _world_h(rec: RunRecording) -> float:
    return rec.frames[0]["world"].get("height") or 200.0  # type: ignore[return-value]


if __name__ == "__main__":
    main()
