# Eco-Loop Building Agents — Part 1: Architecture & Foundations

**A Closed-Loop Physical AI System for Autonomous Building Energy Optimization**

This is Part 1 of a 3-part roadmap. It covers *what* you're building and *why*, in enough depth that every later implementation decision traces back to a requirement here.

- Part 1 (this file): Problem, architecture, tech stack, repo structure, deliverables/evaluation mapping
- Part 2: Full implementation guide (EnergyPlus integration → LLM/MCP agent → closed-loop orchestration)
- Part 3: Dashboard, architecture documentation, demo video, presentation, risk mitigation

---

## 1. The Problem, In Depth

Buildings consume roughly 40% of global energy and are a primary driver of carbon emissions. The core failure of traditional Building Management Systems (BMS) is that they are **schedule-driven, not state-driven** — a BMS runs "cooling on 9am–6pm, setpoint 22°C" regardless of whether the building is actually occupied, whether it's a mild day outside, or whether the grid is under peak carbon load at that exact hour. This mismatch between fixed schedule and real-world state is where the wasted energy lives.

The proposed fix has three ingredients, and it's worth understanding why each is necessary rather than optional:

1. **A physics-based simulation engine (EnergyPlus)** — because you need a faithful digital twin of thermal dynamics (heat transfer, HVAC response, occupancy loads) to test control strategies safely and quantify savings. You cannot prove a % kWh reduction without a physically accurate baseline to compare against.
2. **An open-source LLM as the reasoning layer** — because the mapping from "current state + goals" to "optimal setpoint" is not a simple lookup table; it requires reasoning over multiple competing objectives (comfort, energy, carbon intensity) that shift with context. A fixed rule-based controller can't generalize the way a reasoning model can, and the hackathon explicitly wants LLM-driven reasoning, not hardcoded heuristics.
3. **MCP as the connective tissue** — because the LLM needs a *structured, safe* way to read simulation state and issue control actions. Free-text parsing of LLM output into building actuator writes is fragile and dangerous (a malformed setpoint could be catastrophic in a real building). MCP tool-calling gives you validated, typed, auditable read/write operations.

### 1.1 What "closed-loop" actually means here
A one-shot LLM call that looks at a building's state once and prints a recommendation is **not** a closed loop — it's a report generator. A closed loop requires:
- The LLM's decisions to feed back into the *same running simulation*, changing its future physics.
- The simulation's *new* resulting state (after the LLM's last action took effect) to be the input to the LLM's *next* decision.
- This cycle to repeat continuously across the simulated time horizon, with the system able to recover from bad decisions (self-correction), not just execute a fixed plan.

This is the single most technically demanding part of the project, and it's worth internalizing before writing any code: **you are not running EnergyPlus once and then doing analysis. You are running EnergyPlus once, continuously, and reaching into it mid-run.**

---

## 2. System Architecture

### 2.1 The Loop, Stage by Stage

```
 ┌───────────────────────────────────────────────────────────────────┐
 │                                                                     │
 │   ┌─────────────────┐   (1) FEEDBACK    ┌─────────────────────┐   │
 │   │   EnergyPlus     │ ────────────────▶ │     MCP Server       │   │
 │   │   Simulation     │  zone temps,      │  (tool bridge layer) │   │
 │   │  (digital twin)  │  air quality,     │                      │   │
 │   │                  │  energy meters,   │  exposes:            │   │
 │   │                  │  PMV comfort      │  - get_building_     │   │
 │   │                  │                   │    state()           │   │
 │   │                  │                   │  - set_zone_         │   │
 │   │                  │                   │    setpoint()        │   │
 │   │                  │                   │  - apply_ecm()       │   │
 │   │                  │                   │  - get_comfort_      │   │
 │   │                  │                   │    bounds()          │   │
 │   └────────▲─────────┘                   └──────────┬───────────┘   │
 │            │                                          │             │
 │   (4) FORWARD INJECTION                        (2) TOOLS EXPOSED    │
 │   new setpoints written                        TO AGENT             │
 │   into live actuators                                   │           │
 │            │                                            ▼           │
 │            │                                 ┌──────────────────┐  │
 │            └─────────(3) CONTROL ACTIONS──── │  Open-Source LLM  │  │
 │                       via validated tool      │  (reasoning agent)│  │
 │                       calls                   │                    │  │
 │                                                │  evaluates state   │  │
 │                                                │  against comfort/  │  │
 │                                                │  energy/carbon      │  │
 │                                                │  targets, calls     │  │
 │                                                │  tools to act        │  │
 │                                                └──────────────────┘  │
 │                                                                     │
 └───────────────────────────────────────────────────────────────────┘
```

### 2.2 Stage Detail

**(1) Feedback — EnergyPlus → MCP Server**
Every control interval, the running simulation must surface a compact snapshot: zone air temperature(s), indoor air quality proxy (e.g. CO₂ if modeled), HVAC/lighting energy meters (kWh since last interval and cumulative), and Predicted Mean Vote (PMV) thermal comfort index per zone. This is *not* the raw EnergyPlus output file — it's a small, structured, pre-aggregated payload built specifically for LLM consumption.

**(2) Tool Exposure — MCP Server → LLM**
The MCP server does not hand the LLM raw simulation internals. It exposes a small, fixed set of typed tools. This is a deliberate constraint: fewer, well-documented tools produce far more reliable agent behavior than a large, loosely-specified toolset.

**(3) Reasoning & Control Actions — LLM → MCP Server**
The LLM receives the state snapshot plus its operating goals (minimize energy and carbon while respecting comfort bounds) and responds with one or more tool calls — never free text that requires parsing. Every tool call is validated against hard-coded safety bounds before it's allowed to reach the simulation (see Part 2, §4.3).

**(4) Forward Injection — MCP Server → EnergyPlus**
Validated tool calls translate into EnergyPlus EMS actuator writes, applied at the *next* timestep boundary the simulation processes. The simulation then advances, and the cycle restarts from stage 1 with the new physics in effect.

### 2.3 Why This Differs From a Naive Implementation
A common shortcut that will cost you on "System Integration" and "Agentic Autonomy" scoring: running EnergyPlus once per candidate setpoint set (batch mode), having the LLM look at output files after each run, and picking the best one. This is optimization-by-brute-force-search, not a closed-loop agent, and it does not scale to continuous real-time control. The evaluation criteria specifically reward a pipeline that runs *without crashing over an extended simulation time horizon* — that phrasing assumes one continuous simulation instance being steered live, not many short batch runs.

---

## 3. Technology Stack — Detailed Rationale

| Layer | Tool | Why this one | Alternatives considered |
|---|---|---|---|
| Simulation engine | **EnergyPlus** (v23.x or 24.x) | Required by the brief; the industry-standard open-source building energy simulator with EMS scripting and a real-time Python API | (None — mandated) |
| Live mid-run coupling | **EnergyPlus Python API** (`pyenergyplus.api`) | Provides `callback_*` hooks that fire during a *running* simulation, and a Data Transfer (actuator/sensor) interface — this is the only realistic way to satisfy "forward injection" into a live run | BCVTB/FMU co-simulation is more powerful for multi-tool coupling but has a much steeper setup cost; only worth it if you later co-simulate grid/weather models separately |
| IDF editing between runs | **eppy** | Best-in-class Python library for parsing/editing `.idf` text objects (zones, schedules, EMS actuator declarations) — you'll use this to *author* the actuator/output-variable declarations before the run starts, while the Python API handles *during*-run control | Manual regex editing of IDF text (fragile, avoid) |
| LLM | **Llama 3.1/3.2**, **Mistral**, or **Qwen2.5**, served locally | Open-source (required), and all three have usable function/tool-calling support as of recent releases | Larger local models if hardware allows; avoid anything without native tool-calling — you'd have to hand-roll JSON parsing, which is a reliability risk |
| Local LLM server | **Ollama** (fastest to stand up) or **vLLM** (better throughput if you have a GPU and need speed) | Ollama gives you an OpenAI-compatible endpoint in minutes; vLLM is worth the extra setup only if control-loop latency becomes a bottleneck | Cloud-hosted open-weight APIs — acceptable if "self-hosted API" per the brief's wording, but local is safer for demo reliability |
| Agent protocol | **MCP (Model Context Protocol)**, Python SDK | Explicitly required; standardizes tool exposure and keeps LLM actions auditable and typed | Custom function-calling glue (works, but loses the "MCP" architecture requirement) |
| Orchestration | Plain Python control loop | The loop logic here is simple enough (poll → decide → validate → apply) that a heavyweight framework adds complexity without benefit; graders reward clarity (part of the 15% Agentic Autonomy & Code Elegance score) | LangGraph/LangChain — fine if you're already fluent in them, but don't adopt them just for the label |
| Dashboard | **Streamlit** | Fastest path from a pandas DataFrame to an interactive comparison dashboard; strong default charting story with Plotly under the hood | Plotly Dash (more control, more boilerplate); a static matplotlib export is an acceptable fallback if time is short |
| Metrics storage | SQLite or Parquet/CSV | Simulation ticks can be sub-hourly; append-only flat files are simplest and sufficient at hackathon scale | A full time-series DB is overkill here |

---

## 4. Repository Structure

Set this up before writing any implementation logic — it forces early interface thinking and gives graders an immediate impression of organization (part of the 10% Presentation & Documentation score).

```
eco-loop-building-agents/
├── README.md                        # project overview, setup instructions, how to run
├── ARCHITECTURE.md                  # the required System Architecture Document (see Part 3)
├── requirements.txt
│
├── /models/
│   ├── baseline_building.idf        # authored/adapted baseline building model
│   ├── baseline_weather.epw         # weather file for the target location
│   └── /runtime_generated/          # auto-saved actuator-state snapshots per control cycle
│
├── /src/
│   ├── energyplus_wrapper.py        # EnergyPlus Python API wrapper — start/get_state/set_actuator/step
│   ├── mcp_server.py                # MCP server exposing simulation tools to the LLM
│   ├── mcp_client_agent.py          # LLM agent — system prompt, tool-calling loop, decision logging
│   ├── control_loop.py              # the closed-loop orchestrator — main entry point
│   ├── ecm_logic.py                 # translates high-level LLM decisions into actuator values
│   ├── metrics_logger.py            # per-timestep logging: kWh, PMV, temps, decisions
│   └── config.py                    # comfort bounds, control interval, model paths, LLM endpoint
│
├── /dashboard/
│   └── app.py                       # Streamlit savings dashboard (baseline vs AI-driven)
│
├── /logs/
│   ├── baseline_run/                # full baseline simulation output (untouched schedule)
│   └── ai_run/                      # full AI-driven closed-loop run output
│
├── /docs/
│   ├── prompt_engineering.md        # system prompt design + iteration notes
│   └── demo_video_link.md
│
└── /tests/
    └── test_control_loop.py         # at minimum: actuator-write validation, malformed-response handling
```

**Interface contracts to lock in now** (define these signatures before implementation, even as stubs — Part 2 builds directly against them):

```python
# energyplus_wrapper.py
class EnergyPlusSession:
    def start(self, idf_path: str, epw_path: str) -> None: ...
    def get_state(self) -> dict: ...        # zone temps, PMV, energy meters, timestamp
    def set_actuator(self, name: str, value: float) -> None: ...
    def step(self) -> bool: ...              # advances one timestep; returns False when sim ends

# mcp_server.py — tool signatures the LLM will call
def get_building_state() -> dict: ...
def set_zone_setpoint(zone_id: str, setpoint_type: str, value: float) -> dict: ...
def apply_ecm(ecm_name: str, params: dict) -> dict: ...
def get_comfort_bounds() -> dict: ...
```

---

## 5. Deliverables — Full Checklist

Submit a GitHub repository URL containing:

1. **Fully functional source code** — unified Python codebase covering the EnergyPlus API wrapper, LLM agent orchestration, and the communication bus (MCP layer).
2. **Building models (`.idf` files)** — the baseline file *and* the modified versions generated during runtime evaluation (save every actuator-state snapshot the agent produces).
3. **Quantitative savings dashboard** — visual dashboard or final data export comparing baseline operation against the AI-driven closed-loop strategy, with explicit % reduction in total kWh consumed *while maintaining thermal comfort boundaries* (both halves of this sentence are graded — see §6).
4. **System Architecture Document** — short Markdown report explaining: tool-calling architecture, prompt engineering strategies, prompt/latency management, and the technical approach to handling lengthy simulation logs.
5. **PoC demonstration video** — maximum 3 minutes, showing the loop in action: live data transfer from EnergyPlus to the LLM, and the subsequent control actions updating model parameters automatically.
6. **Presentation** — using the provided template, filled in with your solution's specifics.

All files must be submitted as PDF or ZIP only (convert/print to PDF if ZIP upload fails).

---

## 6. Evaluation Criteria — What Each One Actually Rewards

| Criterion | Weight | What's actually being measured | Where it's built in this roadmap |
|---|---|---|---|
| **System Integration** | 30% | Does the closed-loop pipeline run robustly and reliably, without crashing, over an *extended* simulation time horizon? Not "does it run once for a demo." | Part 2, §3 (closed-loop orchestration + self-correction/watchdog logic) |
| **Energy Efficiency Realized** | 25% | The net % reduction in energy use the autonomous agent achieves vs. a standard baseline schedule — a real, computed number from two comparable runs. | Part 3, §1 (baseline vs AI-driven comparison methodology) |
| **Thermal Comfort & Constraints** | 20% | Did the AI save energy *at the expense* of occupant comfort, or did it intelligently balance both? Savings without comfort bounds respected will actively lose points here, not just fail to gain them. | Part 2, §2.4 (comfort bounds as hard constraints); Part 3, §1 (comfort shown alongside savings) |
| **Agentic Autonomy & Code Elegance** | 15% | Effective, creative use of open-source LLM tool-calling, MCP protocol usage, and self-correction loops — not hardcoded rules dressed up as "AI." | Part 2, §2 (MCP tool design) and §3.3 (self-correction) |
| **Presentation & Documentation** | 10% | Clarity of system architecture design, data visualizations, and project delivery. | Part 3, §2–4 |

**The practical implication:** System Integration + Energy Efficiency + Thermal Comfort together are 75% of the grade. Prioritize loop reliability and a real, honestly-measured savings number over dashboard polish or presentation aesthetics — those matter, but only for the remaining 25%.

---

*Continue to Part 2: Implementation Guide for the full build sequence — EnergyPlus integration, the MCP/LLM agent, and closed-loop orchestration.*
