# Eco-Loop Building Agents — Part 2: Implementation Guide

This is Part 2 of a 3-part roadmap: the full technical build sequence. It assumes you've read Part 1 (architecture, stack, repo structure). Everything here is organized by *system*, not by day — build in this order because each stage's tests depend on the previous stage working.

- Part 1: Architecture & Foundations
- Part 2 (this file): Implementation — EnergyPlus integration, LLM/MCP agent, closed-loop orchestration
- Part 3: Dashboard, documentation, demo video, presentation, risk mitigation

---

## 1. Simulation Engine Integration

### 1.1 Get a Baseline Building Model
Don't author an `.idf` from scratch — start from a well-documented EnergyPlus example file and adapt it. `RefBldgMediumOfficeNew2004_Chicago.idf` (from the EnergyPlus ExampleFiles or DOE Reference Building set) is a common, well-tested starting point: multi-zone, realistic HVAC, standard schedules. Pair it with a `.epw` weather file for whichever city you're targeting.

Steps:
1. Install EnergyPlus (23.x or 24.x) and confirm the CLI runs: `energyplus --version`.
2. Locate an example medium-office or small-office `.idf` and its matching `.epw`.
3. Run it once, completely untouched, in batch mode:
   ```
   energyplus -w baseline_weather.epw -r baseline_building.idf
   ```
4. Inspect the output (`eplusout.csv`, `eplusout.err`) to confirm it ran cleanly with no severe errors.
5. **Save this exact output as your baseline dataset.** This is the fixed comparison point for every savings calculation in Part 3 — do not regenerate or tweak it later, or your % reduction number becomes invalid.

### 1.2 Declare What You'll Need Before the Run Starts
EnergyPlus needs certain objects declared *in the IDF itself* before a simulation starts — you can't add sensors or actuators mid-run, only read/write the ones already declared. Use **eppy** to edit the IDF programmatically (repeatable, versionable) rather than a GUI.

Add via eppy:

- **`Output:Variable` objects** for everything your agent needs to read:
  - `Zone Mean Air Temperature`
  - `Zone Air CO2 Concentration` (if CO₂/air-quality is modeled in your building)
  - `Zone Thermal Comfort Fanger Model PMV` (requires `ZoneControl:Thermostat:ThermalComfort` or equivalent comfort model setup — verify this populates before Phase 2 depends on it, per Part 1 §6 risk list)
  - Facility/zone-level electricity and HVAC energy meters (`Facility Total Electricity Demand Rate`, or per-meter `Output:Meter` objects)
- **`EnergyManagementSystem:Actuator` objects** for every control point the LLM will be allowed to move — e.g.:
  - Zone heating/cooling setpoint actuators (via `EnergyManagementSystem:Actuator` bound to `Zone Temperature Control` on your thermostat schedule objects)
  - Supply air temperature setpoint, if you're controlling at the air-handler level
  - Lighting fraction/power actuators, if lighting ECMs are part of your ECM set
- **`EnergyManagementSystem:Sensor` objects** if you want EMS-level access to output variables from within Erl/EMS logic (optional — the Python API can often read output variables directly without a separate EMS sensor declaration, but check your EnergyPlus version's API docs).

Example (eppy) — adding an output variable:
```python
from eppy.modeleditor import IDF

IDF.setiddname("/path/to/Energy+.idd")
idf = IDF("baseline_building.idf")

idf.newidfobject(
    "OUTPUT:VARIABLE",
    Key_Value="*",
    Variable_Name="Zone Mean Air Temperature",
    Reporting_Frequency="Timestep",
)
idf.newidfobject(
    "OUTPUT:VARIABLE",
    Key_Value="*",
    Variable_Name="Zone Thermal Comfort Fanger Model PMV",
    Reporting_Frequency="Timestep",
)
idf.save()
```

Declaring an EMS actuator (conceptually — exact object fields depend on what you're actuating; consult the EnergyPlus Input/Output Reference for `EnergyManagementSystem:Actuator` on your specific thermostat/schedule object):
```python
idf.newidfobject(
    "ENERGYMANAGEMENTSYSTEM:ACTUATOR",
    Name="ZoneCoolingSetpointActuator",
    Actuated_Component_Unique_Name="Zone1 Cooling Setpoint Schedule",
    Actuated_Component_Type="Schedule:Compact",
    Actuated_Component_Control_Type="Schedule Value",
)
idf.save()
```

### 1.3 Wire Up the EnergyPlus Python API
This is the technically critical piece: the **EnergyPlus Python API** (`pyenergyplus.api.EnergyPlusAPI`) lets you register callbacks that fire *during* a running simulation, and read/write actuator and sensor handles live. This is fundamentally different from eppy (which only edits the IDF text before a run starts).

Build `src/energyplus_wrapper.py` around this shape:

```python
from pyenergyplus.api import EnergyPlusAPI

class EnergyPlusSession:
    def __init__(self, idf_path, epw_path, output_dir):
        self.api = EnergyPlusAPI()
        self.idf_path = idf_path
        self.epw_path = epw_path
        self.output_dir = output_dir
        self.state = self.api.state_manager.new_state()
        self._handles_initialized = False
        self._var_handles = {}
        self._actuator_handles = {}
        self._pending_writes = {}

        # Register the callback that fires each system timestep
        self.api.runtime.callback_begin_system_timestep_before_predictor(
            self.state, self._on_timestep
        )

    def _init_handles(self):
        # Called once, on the first callback invocation, after the API
        # confirms variable/actuator handles can be resolved.
        api = self.api
        self._var_handles["zone1_temp"] = api.exchange.get_variable_handle(
            self.state, "Zone Mean Air Temperature", "ZONE1"
        )
        self._var_handles["zone1_pmv"] = api.exchange.get_variable_handle(
            self.state, "Zone Thermal Comfort Fanger Model PMV", "ZONE1"
        )
        self._actuator_handles["zone1_cooling_sp"] = api.exchange.get_actuator_handle(
            self.state, "Schedule:Compact", "Schedule Value",
            "Zone1 Cooling Setpoint Schedule"
        )
        self._handles_initialized = True

    def _on_timestep(self, state):
        if not self._handles_initialized:
            self._init_handles()

        # Apply any actuator values queued by the control loop since the
        # last timestep, BEFORE the predictor runs.
        for handle_key, value in self._pending_writes.items():
            self.api.exchange.set_actuator_value(
                self.state, self._actuator_handles[handle_key], value
            )
        self._pending_writes.clear()

    def get_state(self) -> dict:
        api = self.api
        return {
            "zone1_temp": api.exchange.get_variable_value(
                self.state, self._var_handles["zone1_temp"]
            ),
            "zone1_pmv": api.exchange.get_variable_value(
                self.state, self._var_handles["zone1_pmv"]
            ),
            "sim_time": api.exchange.current_sim_time(self.state),
        }

    def set_actuator(self, handle_key: str, value: float):
        # Queued, applied at the start of the next timestep callback.
        self._pending_writes[handle_key] = value

    def start(self):
        self.api.runtime.run_energyplus(
            self.state,
            ["-w", self.epw_path, "-d", self.output_dir, self.idf_path],
        )
```

Key implementation notes:
- `run_energyplus` is **blocking** — it runs the full simulation, invoking your callback at every timestep along the way. Your control loop logic lives *inside* the callback (or is triggered from it), not in a separate loop that calls "step" repeatedly from outside. Design `control_loop.py` around this fact (see §3).
- Handles (`get_variable_handle`, `get_actuator_handle`) can only be resolved *after* the simulation has started and API data exchange is ready — hence resolving them lazily on first callback, not at construction time.
- Actuator writes should be queued and applied at the *start* of a timestep's callback, before EnergyPlus's predictor step, so the new setpoint is what the physics for that timestep actually uses.

### 1.4 Isolated Validation Before Involving the LLM
Before writing any agent code, hardcode a dummy rule directly in `_on_timestep` (e.g., "if zone1_temp > 24°C, lower cooling setpoint actuator by 1°C") and confirm:
1. The actuator write measurably changes subsequent zone temperature/energy behavior in the output.
2. The simulation runs start-to-finish without errors across a multi-day horizon.

This isolates simulation-layer bugs from agent-layer bugs — if something breaks once the LLM is involved, you'll know it's in the reasoning/tool-calling layer, not the EnergyPlus coupling.

---

## 2. Cognitive Engine: LLM + MCP

### 2.1 Stand Up a Local LLM Server
Fastest path: **Ollama**.
```
ollama pull llama3.1        # or mistral, qwen2.5
ollama serve
```
This exposes an OpenAI-compatible endpoint (typically `http://localhost:11434/v1`). Confirm tool/function calling works with a trivial test before building anything on top of it — send a one-tool request ("what's the weather" → calls a dummy `get_weather` tool) and verify the model returns a structured tool call rather than prose describing what it *would* call.

If throughput becomes a bottleneck once the full loop is running (see §3.2 on latency), **vLLM** is the upgrade path — more setup cost, meaningfully better tokens/sec if you have GPU headroom.

### 2.2 Design the MCP Tool Set
Keep the tool surface small and precisely typed — this is a deliberate design choice that improves both reliability (fewer ways for the LLM to misuse a tool) and your Agentic Autonomy score (a clean, minimal tool contract reads as more deliberate design than a sprawling one).

Build `src/mcp_server.py` exposing:

```python
def get_building_state() -> dict:
    """Returns current zone temps, PMV, cumulative and interval energy
    consumption, and (if modeled) a grid carbon-intensity signal."""

def set_zone_setpoint(zone_id: str, setpoint_type: str, value: float) -> dict:
    """setpoint_type in {'heating', 'cooling', 'supply_air_temp'}.
    Value is validated against hard bounds before being queued for
    the EnergyPlus wrapper. Returns {'accepted': bool, 'reason': str}."""

def apply_ecm(ecm_name: str, params: dict) -> dict:
    """Higher-level actions, e.g. 'reduce_lighting_load' with
    {'zone_id': ..., 'reduction_pct': ...} for unoccupied zones."""

def get_comfort_bounds() -> dict:
    """Static config the LLM must respect, e.g. PMV in [-0.5, 0.5],
    or an occupant-defined temperature range per zone."""
```

Each tool function should call straight into `energyplus_wrapper` for reads, and into `ecm_logic.py` (which validates, then calls `set_actuator`) for writes — the MCP layer itself stays thin; validation and translation logic belongs in `ecm_logic.py` so it's unit-testable independent of the MCP transport (see §4.3 and Part 2 §3.3 for why this separation matters for self-correction).

### 2.3 Build the Agent Loop (`mcp_client_agent.py`)
The agent's job each control cycle: receive a state snapshot, reason against goals and constraints, and emit one or more tool calls.

System prompt structure (this becomes documented content for your Architecture Doc in Part 3):
```
You are an autonomous building energy control agent. Your goals, in priority order:
1. Keep every zone's PMV thermal comfort index within the bounds returned by
   get_comfort_bounds(). This is a hard constraint, not a preference.
2. Subject to constraint 1, minimize total facility energy consumption and,
   where a grid carbon-intensity signal is available, prefer shifting load
   away from high-carbon-intensity periods.
3. Prefer the smallest control action that achieves the goal — avoid large,
   abrupt setpoint swings between consecutive control cycles.

You must act only through the provided tools. Never propose a setpoint value
outside the bounds returned by get_comfort_bounds(). If you are uncertain,
call get_building_state() again rather than guessing.
```

Loop shape:
```python
def decide(state: dict) -> list[dict]:
    messages = build_messages(state)     # compact JSON state, not raw logs
    response = llm_client.chat(
        messages=messages,
        tools=TOOL_SCHEMAS,
        tool_choice="auto",
    )
    tool_calls = extract_tool_calls(response)
    return tool_calls   # control_loop.py applies these via ecm_logic.py
```

### 2.4 Prompt Engineering Priorities
These four points are exactly what your Architecture Document (Part 3) needs to explain, so treat them as design decisions to document as you make them, not afterthoughts:

1. **Compact state payloads.** Never pass raw EnergyPlus verbose output into the prompt. Pre-aggregate `get_building_state()`'s return into a small JSON object (a handful of zones' temps/PMV, one or two energy figures, one timestamp) — this keeps token counts low and keeps the model focused on decision-relevant signal.
2. **Hard constraints stated explicitly, twice.** State comfort bounds in the system prompt *and* enforce them again in code (`ecm_logic.py` validation, §4.3) before any actuator write reaches EnergyPlus. Treat the prompt-level instruction as a first line of defense, not the only one — LLMs occasionally violate stated constraints, and a real building (or a graded simulation of one) can't tolerate that.
3. **Few-shot examples for consistency.** If early testing shows inconsistent decisions (e.g., oscillating setpoints cycle to cycle), add one or two worked examples in the system prompt showing a good decision given a sample state, including brief rationale.
4. **Prompt/context reuse across calls.** The system prompt and tool schemas are static — only the state snapshot changes per control cycle. If your LLM serving setup supports prompt caching (many local servers do via KV-cache reuse for a repeated prefix), structure your messages so the static system prompt is the stable prefix, cutting redundant processing latency significantly across a long simulation run with many control cycles.

---

## 3. Closed-Loop Orchestration

This is the highest-weighted deliverable (System Integration, 30%). Build it deliberately, not as an afterthought once the pieces "mostly work."

### 3.1 The Orchestration Shape
Because `run_energyplus` is blocking and callback-driven (§1.3), your control loop doesn't sit *outside* EnergyPlus calling a `step()` function — it lives *inside* the timestep callback, or is triggered from it at the right cadence. `control_loop.py` should look roughly like:

```python
class ControlLoop:
    def __init__(self, ep_session, agent, ecm_logic, metrics_logger, control_interval_min=15):
        self.ep_session = ep_session
        self.agent = agent
        self.ecm_logic = ecm_logic
        self.metrics_logger = metrics_logger
        self.control_interval_min = control_interval_min
        self._last_control_time = None
        self._consecutive_failures = 0
        self._last_safe_setpoints = {}

    def on_timestep(self, state):
        sim_time = state["sim_time"]
        if not self._due_for_control(sim_time):
            return

        try:
            tool_calls = self.agent.decide(state)
            validated = self.ecm_logic.validate_and_apply(tool_calls, self.ep_session)
            self._last_safe_setpoints = validated
            self._consecutive_failures = 0
        except AgentDecisionError as e:
            self._consecutive_failures += 1
            self.metrics_logger.log_error(sim_time, e)
            if self._consecutive_failures >= 3:
                # Watchdog: fall back to last known-safe setpoints rather
                # than halting the simulation.
                self.ecm_logic.apply_raw(self._last_safe_setpoints, self.ep_session)

        self.metrics_logger.log(sim_time, state, tool_calls)
        self._last_control_time = sim_time
```

### 3.2 Decouple Control Interval From Simulation Timestep
Do **not** call the LLM on every single EnergyPlus timestep (often sub-hourly, potentially 4–12 calls per simulated hour) — this is both slow and unnecessary, since building thermal dynamics don't require decisions that granular. Poll and act on a coarser interval (e.g., every 15–60 simulated minutes), tracked via `_due_for_control()` comparing `sim_time` against `_last_control_time`. Document this decoupling explicitly in your Architecture Doc under "latency management" — it's a direct answer to one of the required documentation sections.

### 3.3 Self-Correction and Validation
Two distinct layers of defense, both required for a genuinely "autonomous, self-correcting" system (not just marketing language for the presentation):

1. **Malformed or invalid tool call → retry with correction.** If the LLM's tool call has a missing/invalid field or an out-of-bounds value, don't crash — send a corrective follow-up message ("your last output was invalid because `<reason>` — respond again with a valid tool call respecting `<bounds>`") and retry once. Only escalate to the watchdog fallback if the retry also fails.
2. **Repeated failure → watchdog fallback.** If N consecutive control cycles fail validation or retry, fall back to the last known-safe setpoints rather than halting the simulation or leaving stale/undefined actuator values in place. This is what "robustly and reliably... without crashing over an extended simulation time horizon" is actually testing.

`ecm_logic.py` should own the validation boundary — every tool call, regardless of source, passes through explicit bound checks (from `get_comfort_bounds()` and any hard-coded safety limits) before it's allowed to reach `energyplus_wrapper.set_actuator`. Keep this logic unit-testable in isolation (`tests/test_control_loop.py`) — feed it deliberately malformed and out-of-bounds inputs and confirm it rejects them correctly, independent of whether the LLM or EnergyPlus is even running.

### 3.4 Scaling From Short Test to Extended Horizon
Validate the full loop first on a short horizon (e.g., one simulated day) to catch integration bugs cheaply, then scale up to the extended horizon the evaluation criteria explicitly call out. Budget real wall-clock time for at least one long, unattended run — this is the test that actually generates the System Integration evidence you need, and it's also the run most likely to surface rare edge cases (a corrective retry loop that never resolves, a handle that goes stale, a state snapshot with an unexpected `None`) that a short demo run won't expose.

### 3.5 Persist Every Runtime Modification
Save every actuator-state snapshot / modified `.idf` representation generated during the run into `/models/runtime_generated/` as you go, not just at the end — this satisfies the "modified versions generated during runtime evaluation" deliverable and gives you an audit trail if you need to debug an unexpected result after the fact.

---

*Continue to Part 3: Dashboard, Documentation, Demo Video, Presentation, and Risk Mitigation.*
