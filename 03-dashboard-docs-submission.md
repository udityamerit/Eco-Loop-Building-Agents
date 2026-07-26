# Eco-Loop Building Agents — Part 3: Dashboard, Documentation & Submission

This is Part 3 of a 3-part roadmap, covering everything needed to turn a working closed-loop agent (Part 2) into a graded, submitted deliverable.

- Part 1: Architecture & Foundations
- Part 2: Implementation Guide
- Part 3 (this file): Dashboard, documentation, demo video, presentation, risk mitigation

---

## 1. Quantitative Savings Dashboard

### 1.1 Methodology — Get This Right Before Building Any Charts
The entire "Energy Efficiency Realized" score (25%) depends on a defensible, apples-to-apples comparison. The methodology matters more than the visualization:

1. **Same building, same weather file, same time horizon, for both runs.** Any difference between the baseline and AI runs other than the control strategy itself invalidates the comparison.
2. **Baseline run**: the original, untouched rule-based/static schedule from your source `.idf` (Part 1, §1.1 baseline model) — run once, saved once, never regenerated.
3. **AI-driven run**: the exact same building and weather file, but with your closed-loop agent (Part 2) controlling setpoints for the full horizon.
4. Log both runs at the same granularity (ideally matching your control interval, at minimum matching your simulation timestep) into `/logs/baseline_run/` and `/logs/ai_run/`: timestamp, per-zone temperature, per-zone PMV, interval kWh, cumulative kWh.
5. Compute: `% reduction = (baseline_cumulative_kWh - ai_cumulative_kWh) / baseline_cumulative_kWh * 100`. This single number is what "explicitly prove percentage reductions in total kWh consumed" is asking for — make sure it appears prominently, not buried in a table.
6. **Comfort must be reported alongside energy, not separately.** For every kWh saved, show the corresponding PMV/comfort trace for the AI run against the stated comfort bounds. A dashboard that shows only the energy number invites the exact failure mode the "Thermal Comfort & Constraints" criterion (20%) is designed to catch — savings achieved by silently letting comfort drift out of bounds.

### 1.2 Build the Dashboard (`dashboard/app.py`)
Streamlit is the fastest path from logged CSV/Parquet data to an interactive comparison view:

```python
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

baseline = pd.read_csv("logs/baseline_run/metrics.csv")
ai_run = pd.read_csv("logs/ai_run/metrics.csv")

st.title("Eco-Loop Building Agents — Savings Dashboard")

baseline_total = baseline["interval_kwh"].sum()
ai_total = ai_run["interval_kwh"].sum()
pct_reduction = (baseline_total - ai_total) / baseline_total * 100

col1, col2, col3 = st.columns(3)
col1.metric("Baseline kWh", f"{baseline_total:,.0f}")
col2.metric("AI-Driven kWh", f"{ai_total:,.0f}")
col3.metric("Reduction", f"{pct_reduction:.1f}%")

# Cumulative energy comparison
fig_energy = go.Figure()
fig_energy.add_trace(go.Scatter(x=baseline["timestamp"], y=baseline["interval_kwh"].cumsum(),
                                 name="Baseline (cumulative)"))
fig_energy.add_trace(go.Scatter(x=ai_run["timestamp"], y=ai_run["interval_kwh"].cumsum(),
                                 name="AI-Driven (cumulative)"))
fig_energy.update_layout(title="Cumulative Energy Consumption", yaxis_title="kWh")
st.plotly_chart(fig_energy)

# Comfort trace against bounds
fig_comfort = go.Figure()
fig_comfort.add_trace(go.Scatter(x=ai_run["timestamp"], y=ai_run["zone1_pmv"], name="Zone 1 PMV (AI run)"))
fig_comfort.add_hline(y=0.5, line_dash="dash", annotation_text="Upper comfort bound")
fig_comfort.add_hline(y=-0.5, line_dash="dash", annotation_text="Lower comfort bound")
fig_comfort.update_layout(title="Thermal Comfort (PMV) vs Bounds — AI-Driven Run")
st.plotly_chart(fig_comfort)

# Decision log with LLM rationale
st.subheader("Agent Decision Log")
decisions = pd.read_csv("logs/ai_run/decisions.csv")
st.dataframe(decisions[["timestamp", "tool_called", "params", "rationale"]])
```

### 1.3 What to Include, Specifically
- **Headline metrics**: baseline kWh, AI-driven kWh, and the % reduction, displayed prominently (not just computable from a chart — state it as a number).
- **Cumulative energy comparison chart**, both runs on one axis, so the divergence is visually obvious.
- **Comfort trace vs. bounds**, at minimum for the AI-driven run, ideally for both runs — this is your visual evidence for the 20%-weighted comfort criterion.
- **Agent decision log with rationale.** Surface *why* the LLM made each control decision, not just the resulting numbers — this directly supports the "Agentic Autonomy" criterion by making the reasoning visible and auditable, not just the outcome.
- **Static export.** In addition to the live Streamlit app, export a summary chart/table as an image or PDF — some graders will only look at a screenshot or a static export, not run your app locally.

---

## 2. System Architecture Document (`ARCHITECTURE.md`)

This is a required, separately-graded deliverable — treat it as a technical writeup, not a README duplicate. It must explicitly cover four things:

### 2.1 Tool-Calling Architecture
- Diagram the loop (reuse and adapt the Part 1, §2.1 diagram to your actual implementation).
- List every MCP tool (`get_building_state`, `set_zone_setpoint`, `apply_ecm`, `get_comfort_bounds`), what each does, and *why* the tool surface is scoped the way it is (small, typed, validated — Part 2 §2.2).
- Explain the validation boundary: where hard constraints are enforced in code (`ecm_logic.py`), independent of what the LLM was told in its prompt.

### 2.2 Prompt Engineering Strategies
- Reproduce (or closely summarize) your system prompt structure and explain the reasoning behind its priority ordering (comfort constraint first, then energy/carbon minimization, then action-smoothness preference — Part 2 §2.3).
- Document any few-shot examples you added and what inconsistency they were added to fix.
- Note any iteration history worth mentioning — e.g., "the initial prompt allowed setpoint swings of several degrees per cycle; we added an explicit smoothness preference after observing oscillation in early test runs."

### 2.3 Prompt / Latency Management
- Explain the control-interval decoupling from simulation timestep (Part 2 §3.2) and why it's necessary for both performance and decision granularity.
- Explain any prompt-prefix caching or reuse strategy (Part 2 §2.4, point 4).
- If you measured actual latency per control cycle, include the number — a concrete measurement is more convincing than a general claim.

### 2.4 Handling Lengthy Simulation Logs
- Explain the aggregation step between raw EnergyPlus output and what reaches the LLM (Part 2 §2.4, point 1) — what gets summarized, what gets dropped, and why that doesn't lose decision-relevant information.
- If you log more than you show the LLM (e.g., full timestep-level EnergyPlus output kept in `/logs/` for your own dashboard/debugging, but only a coarser snapshot given to the model), say so explicitly — it shows a deliberate design choice rather than an oversight.

### 2.5 Honest Scoping
Close with a short "known limitations / what we'd improve with more time" section. Graders reading dozens of submissions respond well to honest scoping — it reads as engineering maturity, not weakness. Good candidates: single-building-type validation only, comfort model simplifications, LLM model size/latency tradeoffs, lack of live grid carbon-intensity data (if you mocked or omitted it).

---

## 3. PoC Demonstration Video (≤ 3 minutes)

### 3.1 What Must Be Visible
The brief is specific: the video must highlight **data transferring live from EnergyPlus to the LLM** and **the subsequent control actions updating the model parameters automatically**. Both halves are required — a video that only shows the dashboard afterward does not satisfy this.

### 3.2 Suggested Structure (fits comfortably in 3 minutes)
1. **0:00–0:20** — One-sentence problem framing, cut straight to the running system (don't spend time on title slides in a 3-minute video).
2. **0:20–1:30** — Split-screen or quick cuts: terminal/logs showing a state snapshot being pulled from EnergyPlus → the LLM's tool call appearing → the actuator write confirmed → simulation advancing. Narrate briefly over this; don't just show silent logs scrolling.
3. **1:30–2:20** — Cut to the dashboard: baseline vs. AI-driven cumulative energy, the % reduction number, and the comfort trace staying within bounds.
4. **2:20–3:00** — One or two sentences on what's autonomous/self-correcting about it (reference the retry/watchdog logic briefly), and close.

### 3.3 Practical Recording Notes
- Screen-record terminal and dashboard together (split-screen or picture-in-picture) rather than switching windows abruptly — reviewers watching once need to follow the causal chain without replaying.
- If your control interval is long in simulated time, consider speeding up playback of the "waiting" portions or pre-selecting a window with several control decisions close together, so the video doesn't spend real time waiting on simulated time to pass.

---

## 4. Presentation (Provided Template)

Fill in the required template with:
- **Problem framing** — the 40%-of-global-energy / rigid-BMS framing from Part 1 §1, condensed to a slide's worth.
- **Architecture diagram** — reuse the Part 1 §2.1 diagram, adapted to your actual implementation specifics.
- **Results, front and center** — the % kWh reduction number should be the single most visually prominent figure in the deck, not buried in a details slide.
- **Comfort-vs-savings chart** — one slide making explicit that savings didn't come at comfort's expense (directly answering the 20%-weighted criterion).
- **Brief architecture/tooling summary** — condensed version of the ARCHITECTURE.md content; the deck doesn't need to repeat it in full, but should show you can summarize it concisely.

Export all deliverables (architecture doc, presentation, any static dashboard exports) to PDF, or a ZIP of the repo if that's accepted — the submission portal only accepts PDF or ZIP; convert/print anything else before uploading.

---

## 5. Risk Mitigation — What to De-Risk Early, and Why

These are the points most likely to derail a submission if discovered late. Validate each one *in isolation*, before it's load-bearing for something else.

| Risk | Why it's high-risk | How to de-risk it early |
|---|---|---|
| **Mid-simulation actuator control** | The hardest technical piece in the whole project (Part 2, §1.3). Batch-mode IDF editing between runs is much easier but does not satisfy "continuous, real-time optimization" — a grader will notice the difference between true live control and repeated batch runs. | Validate the EnergyPlus Python API callback + actuator approach with a hardcoded dummy rule (Part 2, §1.4) *before* building the LLM layer on top of it. If this doesn't work reliably, nothing downstream will either. |
| **LLM tool-calling reliability** | Varies significantly by model and quantization level; some smaller/quantized open models produce malformed or inconsistent tool calls under load. | Test tool-calling specifically (not just chat quality) with your chosen local model *before* committing to it for the full build (Part 2, §2.1). |
| **PMV computation not populating** | Requires specific `Output:Variable` requests and comfort-model setup in the IDF (Part 2, §1.2) — if this is misconfigured, your comfort criterion (20% of the grade) has no data to show. | Confirm `Zone Thermal Comfort Fanger Model PMV` is populating in a short test run before Phase 2 (agent logic) depends on it being available. |
| **Extended-horizon stability** | System Integration is the single highest-weighted criterion (30%); a pipeline that only survives a short demo run under-delivers on the criterion that matters most. | Budget real wall-clock time for at least one long, unattended run (Part 2, §3.4) — not just a short slice used for the demo video. |
| **Baseline/AI run comparability** | If the two runs differ in anything besides control strategy (different weather file version, different horizon length, a stale baseline regenerated after edits), the headline % reduction number becomes indefensible under scrutiny. | Fix and freeze the baseline run (§1.1) the moment it's generated; never regenerate it casually while iterating on the AI-driven side. |
