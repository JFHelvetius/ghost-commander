"""Streamlit dashboard: map, live metrics, event timeline, replay and comparison.

Run with:  ``ghost-commander-app``  or  ``streamlit run dashboard.py``.

The whole point of this view is the visceral demo: watch 100 agents lose a third
of their resources to a shock wave and reorganize themselves to finish the
mission. Everything is driven off a deterministic ``RunRecording`` so the replay
slider is exact.
"""

from __future__ import annotations

import dataclasses

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ghost_commander.coordination import STRATEGIES
from ghost_commander.sim import PRESETS, Scenario, compare_strategies, run_scenario
from ghost_commander.sim.recorder import RunRecording

_STATUS_COLOR = {
    "idle": "#7f8c9b",
    "moving": "#3aa0ff",
    "working": "#27d17c",
    "failed": "#e0484f",
}
_PRIORITY_SIZE = {1: 9, 2: 12, 3: 15, 4: 19, 5: 24}


def _run(scenario: Scenario, strategy: str) -> RunRecording:
    return run_scenario(scenario, strategy)


def _map_figure(frame: dict, width: float, height: float) -> go.Figure:
    agents = frame["world"]["agents"]
    tasks = frame["world"]["tasks"]
    fig = go.Figure()

    # tasks: size by priority. open = amber square, done = dim outline,
    # failed = red X (a deadline lost — the thing coordination is fighting).
    def _bucket(t: dict) -> str:
        if t["status"] == "done":
            return "done"
        if t["status"] == "failed":
            return "failed"
        return "open"

    task_styles = {
        "open": dict(symbol="square", color="#f4b942", line="#f4b942"),
        "done": dict(symbol="square-open", color="#34406b", line="#34406b"),
        "failed": dict(symbol="x", color="#e0484f", line="#e0484f"),
    }
    for bucket, style in task_styles.items():
        sel = [t for t in tasks if _bucket(t) == bucket]
        if not sel:
            continue
        fig.add_trace(go.Scatter(
            x=[t["x"] for t in sel], y=[t["y"] for t in sel], mode="markers",
            name=f"tasks · {bucket}",
            marker=dict(symbol=style["symbol"],
                        size=[_PRIORITY_SIZE.get(t["priority"], 12) for t in sel],
                        color=style["color"], line=dict(width=1, color=style["line"])),
            text=[f"task {t['id']} · prio {t['priority']} · {t['status']} · "
                  f"{int(t['progress']*100)}%"
                  + (f" · req:{t['required_skill']}" if t.get("required_skill") else "")
                  for t in sel],
            hoverinfo="text",
        ))

    # agents: circles colored by status
    for status, color in _STATUS_COLOR.items():
        xs = [a["x"] for a in agents if a["status"] == status]
        ys = [a["y"] for a in agents if a["status"] == status]
        txt = [f"agent {a['id']} · {a['status']} · res {int(a['resources']*100)}%"
               + (f" · {a['skill']}" if a.get("skill") else "")
               for a in agents if a["status"] == status]
        if xs:
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="markers", name=f"agents · {status}",
                marker=dict(size=7, color=color, line=dict(width=0)),
                text=txt, hoverinfo="text",
            ))

    fig.update_layout(
        height=560, margin=dict(l=10, r=10, t=30, b=10),
        plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
        font=dict(color="#cdd3df"),
        legend=dict(orientation="h", y=1.06, font=dict(size=10)),
        xaxis=dict(range=[0, width], showgrid=False, zeroline=False, visible=False),
        yaxis=dict(range=[0, height], showgrid=False, zeroline=False, visible=False,
                   scaleanchor="x", scaleratio=1),
    )
    return fig


def _sidebar() -> tuple[Scenario, str]:
    st.sidebar.title("👻 Ghost Commander")
    st.sidebar.caption("Coordinación dinámica de agentes autónomos")
    preset_name = st.sidebar.selectbox("Escenario", list(PRESETS), index=0)
    base = PRESETS[preset_name]
    strategy = st.sidebar.selectbox("Estrategia de coordinación", list(STRATEGIES),
                                    index=list(STRATEGIES).index("global"))
    seed = st.sidebar.number_input("Seed", min_value=0, value=int(base.seed), step=1)
    n_agents = st.sidebar.slider("Agentes", 10, 300, int(base.n_agents), step=10)
    n_tasks = st.sidebar.slider("Tareas", 5, 120, int(base.n_tasks), step=5)
    max_ticks = st.sidebar.slider("Máx. ticks", 100, 1000, int(base.max_ticks), step=50)
    scenario = dataclasses.replace(
        base, seed=int(seed), n_agents=int(n_agents), n_tasks=int(n_tasks),
        max_ticks=int(max_ticks),
    )
    return scenario, strategy


def main() -> None:
    st.set_page_config(page_title="Ghost Commander", page_icon="👻", layout="wide")
    scenario, strategy = _sidebar()

    if st.sidebar.button("▶ Ejecutar misión", type="primary", use_container_width=True):
        with st.spinner("Simulando…"):
            st.session_state["rec"] = _run(scenario, strategy)
            st.session_state["rec_label"] = f"{scenario.name} · {strategy} · seed {scenario.seed}"

    tab_mission, tab_compare = st.tabs(["🛰  Misión", "📊  Comparar estrategias"])

    with tab_mission:
        rec: RunRecording | None = st.session_state.get("rec")
        if rec is None:
            st.info("Configura el escenario en la barra lateral y pulsa **Ejecutar misión**.")
        else:
            _render_mission(rec)

    with tab_compare:
        _render_compare(scenario)


def _render_mission(rec: RunRecording) -> None:
    st.caption(st.session_state.get("rec_label", ""))
    n_frames = len(rec.frames)
    tick = st.slider("Replay (tick)", 0, n_frames - 1, n_frames - 1)
    frame = rec.frames[tick]
    m = frame["metrics"]

    failed = int(m.get("tasks_failed", 0))
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Misión (ponderada)", f"{m['mission_completion'] * 100:.0f}%")
    c2.metric("Tareas hechas", f"{m['tasks_done']}/{m['tasks_total']}")
    c3.metric("Tareas falladas", failed, delta=None if failed == 0 else f"-{failed}",
              delta_color="inverse")
    c4.metric("Agentes vivos", f"{m['agents_alive']}/{m['agents_total']}",
              delta=f"-{m['agents_total'] - m['agents_alive']}")
    c5.metric("Reasignaciones", int(m["reassignments"]))
    c6.metric("Recursos medios", f"{m['mean_resources'] * 100:.0f}%")

    left, right = st.columns([3, 2])
    with left:
        st.plotly_chart(
            _map_figure(frame, _world_w(rec), _world_h(rec)),
            use_container_width=True,
        )
    with right:
        hist = pd.DataFrame(rec.metrics_history[: tick + 1])
        st.markdown("**Progreso de misión**")
        st.line_chart(hist.set_index("tick")[["mission_completion"]], height=180)
        st.markdown("**Agentes vivos**")
        st.line_chart(hist.set_index("tick")[["agents_alive"]], height=180)

    st.markdown("**Timeline de eventos** (hasta el tick seleccionado)")
    ev = pd.DataFrame([e for e in rec.events if e["tick"] <= tick])
    if not ev.empty:
        notable = ev[ev["severity"].isin(["WARN", "ERROR", "CRITICAL", "INFO"])]
        st.dataframe(notable.tail(200), use_container_width=True, height=240)


def _render_compare(scenario: Scenario) -> None:
    st.markdown(f"Mismo escenario y seed (**{scenario.name}**, seed {scenario.seed}), "
                "solo cambia el algoritmo. Determinista ⇒ comparación justa.")
    if st.button("Comparar las 3 estrategias", use_container_width=True):
        with st.spinner("Corriendo greedy / auction / global…"):
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
            marker_color="#27d17c", text=[f"{r.completion*100:.0f}%" for r in results],
            textposition="outside",
        ))
        fig.update_layout(
            title="Éxito de misión por estrategia", height=360,
            plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font=dict(color="#cdd3df"),
            yaxis=dict(range=[0, 105], title="misión ponderada %"),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.success(f"🏆 Ganador: **{results[0].strategy}**")


def _world_w(rec: RunRecording) -> float:
    xs = [t["x"] for t in rec.frames[0]["world"]["tasks"]] + \
         [a["x"] for a in rec.frames[0]["world"]["agents"]]
    return max(xs, default=200.0) * 1.05


def _world_h(rec: RunRecording) -> float:
    ys = [t["y"] for t in rec.frames[0]["world"]["tasks"]] + \
         [a["y"] for a in rec.frames[0]["world"]["agents"]]
    return max(ys, default=200.0) * 1.05


if __name__ == "__main__":
    main()
