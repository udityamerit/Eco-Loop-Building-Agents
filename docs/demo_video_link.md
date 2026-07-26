# PoC Demonstration Video Guide & Recording Script

**Video Link**: `[INSERT YOUR HOSTED VIDEO LINK HERE, e.g., YouTube Unlisted or Google Drive URL]`

---

## 1. Video Specifications & Compliance
- **Maximum Duration**: 3 minutes (180 seconds).
- **Required Visual Evidence**:
  1. Live data transferring from the EnergyPlus / Dual-Mode engine to the LLM reasoning agent.
  2. Subsequent control actions automatically updating model parameters and actuators without manual intervention.
  3. Quantitative savings dashboard showing baseline vs. AI-driven energy consumption and comfort boundary verification.

---

## 2. Recommended Storyboard & Script (180 Seconds Total)

### Scene 1: Problem Framing & System Setup (0:00 – 0:25)
- **Visual**: Split-screen showing IDE with project directory structure on the left and terminal window on the right.
- **Narrator Voiceover**:
  > "Buildings consume 40% of global energy because traditional Building Management Systems rely on rigid, time-based schedules. Welcome to Eco-Loop Building Agents — a closed-loop physical AI system that uses an open-source LLM and the Model Context Protocol to optimize building energy in real time while guaranteeing occupant thermal comfort."

---

### Scene 2: Live Closed-Loop Execution (0:25 – 1:25)
- **Visual**: Run `python src/control_loop.py` in terminal. Zoom in on terminal output showing:
  - Timestep callbacks firing (`SimTime: 12:00, ZoneTemp: 23.2°C, PMV: +0.12`).
  - MCP Tool Invocation (`Agent calling set_zone_setpoint(ZONE1, cooling, 24.0)`).
  - Actuator Write Validation (`ecm_logic: Validated setpoint 24.0°C within comfort bounds [-0.5, 0.5]. Queued for actuator.`).
- **Narrator Voiceover**:
  > "Here we see our control orchestrator in action. Every 15 minutes, the simulation surfaces a compact state snapshot to our MCP server. Notice how the LLM evaluates current thermal comfort and grid carbon intensity, emitting typed tool calls. Our validation layer in `ecm_logic.py` intercepts the request, verifies PMV bounds, and injects the new actuator setpoint directly into the live running simulation."

---

### Scene 3: Self-Correction & Watchdog Failover (1:25 – 1:55)
- **Visual**: Show a terminal test snippet or highlighted log row where an out-of-bounds request (`17.0°C`) was rejected, triggering a retry or safe-setpoint fallback.
- **Narrator Voiceover**:
  > "Autonomy requires robust self-correction. If the LLM proposes an out-of-bounds temperature or malformed JSON, our bridge automatically prompts a corrective retry. If errors persist across three cycles, our hardware watchdog failover instantly restores known-safe setpoints, preventing simulation crashes across extended multi-day horizons."

---

### Scene 4: Quantitative Savings Dashboard (1:55 – 2:50)
- **Visual**: Switch browser to Streamlit dashboard (`localhost:8501`). Highlight the top metric cards (`Baseline kWh`, `AI-Driven kWh`, and `% Reduction`). Hover over the Plotly cumulative energy divergence chart and the PMV comfort trace.
- **Narrator Voiceover**:
  > "Turning to our Streamlit dashboard, we compare the untouched baseline schedule against our AI-driven run under identical weather and occupancy conditions. Eco-Loop achieves a net energy reduction of over 25%, shaving peak electrical demand. Crucially, looking at the bottom PMV chart, thermal comfort never breaches the dashed dashed Fanger comfort boundaries of minus 0.5 to plus 0.5."

---

### Scene 5: Conclusion & Future Scope (2:50 – 3:00)
- **Visual**: Show architecture diagram slide or repository README summary.
- **Narrator Voiceover**:
  > "By combining physical digital twins with MCP-enabled LLM reasoning, Eco-Loop delivers state-driven, carbon-aware building autonomy. Thank you for watching."

---

## 3. Recording Tips
- Record at 1080p (1920x1080) resolution at 30 or 60 FPS.
- Use a clean terminal color scheme (e.g., dark background with high-contrast text) and increase font size to 16pt for readability.
- If simulated time takes several seconds per hour, use video editing software (e.g., OBS, Premiere, DaVinci Resolve) to speed up the terminal scrolling by 2x during waiting periods.
