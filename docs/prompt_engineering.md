# Prompt Engineering Strategies & Iteration Notes

This document records the design, evolution, and empirical iteration of the LLM system prompt used in the **Eco-Loop Building Agents** reasoning layer.

---

## 1. System Prompt Evolution

### 1.1 Version 1.0 (Naive Zero-Shot)
Our initial prompt instructed the model to simply lower energy consumption while keeping the building comfortable:
```text
You are a building energy controller. Look at the temperature and energy use, and change the HVAC setpoint to reduce kWh without making people uncomfortable. Use the set_zone_setpoint tool.
```

**Observed Failure Modes**:
- **Aggressive Setpoint Swings**: The model frequently requested cooling setpoints of 26°C or higher immediately upon seeing high energy demand, causing PMV to spike above +0.8 (warm discomfort).
- **Tool Hallucination**: Without explicit tool parameter schemas in the prompt instructions, smaller quantized models (e.g., Llama-3-8B-Instruct) occasionally emitted raw text explanations rather than structured tool calls.

---

### 1.2 Version 2.0 (Strict Hierarchy & Constraint Enforcement)
We revised the prompt to establish an inviolable priority hierarchy and referenced the `get_comfort_bounds()` tool:
```text
You are an autonomous building energy control agent. Your goals, in priority order:
1. Keep every zone's PMV thermal comfort index within the bounds returned by get_comfort_bounds(). This is a hard constraint, not a preference.
2. Subject to constraint 1, minimize total facility energy consumption.
3. Never propose a setpoint value outside the bounds returned by get_comfort_bounds().
```

**Observed Improvements & Residual Issues**:
- Compliance with PMV bounds (`[-0.5, 0.5]`) improved significantly.
- However, when zone PMV drifted close to a boundary (e.g., +0.45), the model sometimes over-corrected by dropping setpoints by 3°C at once, causing oscillation in subsequent 15-minute control cycles.

---

### 1.3 Version 3.0 (Production Prompt with Action Smoothness & Few-Shot Exemplars)
To eliminate oscillation and incorporate grid carbon intensity, we added an explicit priority for **action smoothness** along with brief few-shot demonstrations:

```text
You are an autonomous building energy control agent. Your goals, in priority order:
1. Keep every zone's PMV thermal comfort index within the bounds returned by get_comfort_bounds() ([-0.5, 0.5]). This is a hard constraint, not a preference.
2. Subject to constraint 1, minimize total facility energy consumption and prefer shifting load away from high-carbon-intensity periods.
3. Prefer the smallest control action that achieves the goal — avoid large, abrupt setpoint swings between consecutive control cycles (make adjustments in increments of 0.5°C to 1.0°C).

You must act only through the provided tools. If you are uncertain, call get_building_state() again rather than guessing.

### Example Scenario 1: High Carbon Peak, Comfort Normal
State: {"zone1_temp": 22.5, "zone1_pmv": -0.1, "grid_carbon_gco2_kwh": 450, "occupancy_pct": 80}
Action: Call set_zone_setpoint(zone_id="ZONE1", setpoint_type="cooling", value=23.5)
Rationale: Increasing cooling setpoint by 1.0°C reduces compressor demand during a carbon peak while keeping PMV comfortably within bounds (-0.1 -> ~ +0.2).

### Example Scenario 2: Unoccupied Zone Energy Shedding
State: {"zone1_temp": 23.0, "zone1_pmv": 0.0, "grid_carbon_gco2_kwh": 300, "occupancy_pct": 0}
Action: Call apply_ecm(ecm_name="reduce_lighting_load", params={"zone_id": "ZONE1", "reduction_pct": 50})
Rationale: Zone is unoccupied; reducing lighting fraction by 50% sheds baseline electrical demand without impacting thermal comfort.
```

---

## 2. Key Takeaways for Physical AI Systems

1. **Quantify Increments**: Telling an LLM to make "small adjustments" is ambiguous; explicitly specifying `increments of 0.5°C to 1.0°C` eliminates erratic setpoint jumps.
2. **Pre-Compute Complex Physics**: Rather than asking the LLM to calculate PMV from raw dry-bulb temperature, air velocity, and relative humidity, surfacing the pre-computed Fanger PMV index allows the model to focus purely on policy reasoning.
3. **Double-Guarding is Essential**: Even with Version 3.0, code-level validation in `src/ecm_logic.py` remains indispensable to guarantee physical safety in edge cases.
