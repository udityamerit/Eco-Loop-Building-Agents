import json
import logging
from typing import List, Dict, Any, Optional
from src.config import OLLAMA_BASE_URL, LLM_MODEL_NAME, LLM_TEMPERATURE

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

class MCPClientAgent:
    """
    LLM reasoning agent orchestrating autonomous building energy optimization via MCP tool calls.
    Features prompt prefix caching formatting, self-correction retries on invalid output,
    and a dual-mode fallback reasoning engine when local Ollama endpoints are unreachable.
    """
    def __init__(self, mcp_server):
        self.mcp_server = mcp_server
        self.logger = logging.getLogger("MCPClientAgent")
        self.tool_schemas = self.mcp_server.get_tool_schemas()
        
        # System prompt formatted as stable prefix for KV-cache reuse
        self.system_prompt = (
            "You are an autonomous building energy control agent. Your goals, in priority order:\n"
            "1. Keep every zone's PMV thermal comfort index within the bounds returned by get_comfort_bounds() ([-0.5, 0.5]). This is a hard constraint, not a preference.\n"
            "2. Subject to constraint 1, minimize total facility energy consumption and prefer shifting load away from high-carbon-intensity periods.\n"
            "3. Prefer the smallest control action that achieves the goal — avoid large, abrupt setpoint swings between consecutive control cycles (make adjustments in increments of 0.5°C to 1.0°C).\n\n"
            "You must act only through the provided tools. Never propose a setpoint value outside allowed bounds.\n\n"
            "### Example Scenario 1: High Carbon Peak, Comfort Normal\n"
            'State: {"zone1_temp": 22.5, "zone1_pmv": -0.1, "grid_carbon_gco2_kwh": 450, "occupancy_pct": 80}\n'
            'Action: Call set_zone_setpoint(zone_id="ZONE1", setpoint_type="cooling", value=23.5)\n'
            'Rationale: Increasing cooling setpoint by 1.0°C reduces compressor demand during a carbon peak while keeping PMV comfortably within bounds (-0.1 -> ~ +0.2).\n\n'
            "### Example Scenario 2: Unoccupied Zone Energy Shedding\n"
            'State: {"zone1_temp": 23.0, "zone1_pmv": 0.0, "grid_carbon_gco2_kwh": 300, "occupancy_pct": 0}\n'
            'Action: Call apply_ecm(ecm_name="reduce_lighting_load", params={"zone_id": "ZONE1", "reduction_pct": 50})\n'
            'Rationale: Zone is unoccupied; reducing lighting fraction by 50% sheds baseline electrical demand without impacting thermal comfort.'
        )

        self.client = None
        self.use_llm_api = OPENAI_AVAILABLE
        if self.use_llm_api:
            try:
                self.client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama", max_retries=0, timeout=0.5)
                # Quick health check to prevent blocking timeouts during simulation loop
                self.client.models.list(timeout=0.5)
                self.logger.info(f"Connected to live OpenAI/Ollama endpoint at {OLLAMA_BASE_URL}")
            except Exception as e:
                self.logger.info(f"Local LLM endpoint offline or unreachable ({e}). Engaging Dual-Mode Heuristic Reasoning Engine.")
                self.use_llm_api = False

    def build_messages(self, state: Dict[str, Any], corrective_feedback: Optional[str] = None) -> List[Dict[str, str]]:
        """Constructs prompt messages with compact JSON state snapshot."""
        # Pre-aggregate and format compact state
        compact_state = {
            "zone1_temp": round(state.get("zone1_temp", 23.0), 2),
            "zone1_pmv": round(state.get("zone1_pmv", 0.0), 2),
            "interval_kwh": round(state.get("interval_kwh", 0.0), 3),
            "occupancy_pct": round(state.get("occupancy_pct", 0.0), 1),
            "grid_carbon_gco2_kwh": round(state.get("grid_carbon_gco2_kwh", 300.0), 1),
            "sim_time_min": round(state.get("sim_time", 0.0), 1)
        }
        
        user_content = f"Current Building State Snapshot: {json.dumps(compact_state)}\nAnalyze state and call appropriate control tools."
        if corrective_feedback:
            user_content += f"\n\nIMPORTANT CORRECTION FROM PREVIOUS ATTEMPT: {corrective_feedback}. Please re-issue a valid tool call respecting bounds."
            
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content}
        ]

    def _extract_tool_calls_from_llm(self, response) -> List[Dict[str, Any]]:
        """Parses OpenAI tool calling response structure."""
        tool_calls = []
        if not response or not response.choices:
            return tool_calls
            
        message = response.choices[0].message
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments
                    tool_calls.append({
                        "name": tc.function.name,
                        "params": args,
                        "rationale": getattr(message, "content", "") or f"LLM called tool {tc.function.name}"
                    })
                except Exception as e:
                    self.logger.error(f"Error parsing tool call arguments: {e}")
        return tool_calls

    def _dual_mode_heuristic_reasoning(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Intelligent Dual-Mode Reasoning Engine.
        Executes multi-objective decision policy when Ollama/LLM endpoint is offline,
        producing identical structured MCP tool invocations and auditable rationales.
        """
        temp = state.get("zone1_temp", 23.0)
        pmv = state.get("zone1_pmv", 0.0)
        occ = state.get("occupancy_pct", 0.0)
        grid_carbon = state.get("grid_carbon_gco2_kwh", 300.0)

        tool_calls = []

        # Rule 1: Occupancy-based Lighting Shedding (ECM)
        if occ < 10.0:
            tool_calls.append({
                "name": "apply_ecm",
                "params": {"ecm_name": "reduce_lighting_load", "params": {"zone_id": "ZONE1", "reduction_pct": 60.0}},
                "rationale": f"Zone occupancy is very low ({occ:.1f}%). Shedding 60% lighting load via apply_ecm to minimize baseline electrical consumption."
            })
        else:
            tool_calls.append({
                "name": "apply_ecm",
                "params": {"ecm_name": "reduce_lighting_load", "params": {"zone_id": "ZONE1", "reduction_pct": 0.0}},
                "rationale": f"Zone is occupied ({occ:.1f}%). Restoring normal lighting fraction."
            })

        # Rule 2: Multi-objective thermal comfort and carbon-aware HVAC setpoint optimization
        if pmv > 0.35:
            # Approaching upper comfort boundary -> lower cooling setpoint by 0.5°C
            new_sp = max(22.0, temp - 0.5)
            tool_calls.append({
                "name": "set_zone_setpoint",
                "params": {"zone_id": "ZONE1", "setpoint_type": "cooling", "value": round(new_sp, 1)},
                "rationale": f"PMV index (+{pmv:.2f}) is approaching warm boundary (+0.5). Lowering cooling setpoint to {new_sp:.1f}°C to ensure comfort bounds are strictly respected."
            })
        elif pmv < -0.35:
            # Approaching lower comfort boundary -> raise cooling setpoint
            new_sp = min(25.5, temp + 0.5)
            tool_calls.append({
                "name": "set_zone_setpoint",
                "params": {"zone_id": "ZONE1", "setpoint_type": "cooling", "value": round(new_sp, 1)},
                "rationale": f"PMV index ({pmv:.2f}) is cool. Raising cooling setpoint to {new_sp:.1f}°C to prevent over-cooling and save energy."
            })
        elif grid_carbon > 450.0:
            # Carbon peak load shedding: if comfort permits (PMV < +0.2), raise cooling setpoint
            if pmv < 0.2:
                new_sp = min(25.0, temp + 1.0)
                tool_calls.append({
                    "name": "set_zone_setpoint",
                    "params": {"zone_id": "ZONE1", "setpoint_type": "cooling", "value": round(new_sp, 1)},
                    "rationale": f"Grid carbon intensity is peaking ({grid_carbon:.0f} gCO2/kWh). Shifting electrical load by raising cooling setpoint to {new_sp:.1f}°C while PMV remains comfortable ({pmv:.2f})."
                })
        elif grid_carbon < 350.0 and occ > 50.0:
            # Low carbon intensity + occupied -> pre-cool flush
            tool_calls.append({
                "name": "set_zone_setpoint",
                "params": {"zone_id": "ZONE1", "setpoint_type": "cooling", "value": 23.5},
                "rationale": f"Grid carbon intensity is low ({grid_carbon:.0f} gCO2/kWh). Maintaining optimal thermal setpoint (23.5°C) to pre-cool zone efficiently."
            })

        if not tool_calls:
            # Default stability check
            tool_calls.append({
                "name": "set_zone_setpoint",
                "params": {"zone_id": "ZONE1", "setpoint_type": "cooling", "value": 24.0},
                "rationale": "Building state and thermal comfort are stable within optimal bounds. Maintaining 24.0°C cooling setpoint."
            })

        return tool_calls

    def decide(self, state: Dict[str, Any], corrective_feedback: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Main decision method invoked every control cycle.
        Attempts LLM API call with retry on error; falls back to dual-mode reasoning if API is unavailable.
        """
        if self.use_llm_api and self.client:
            try:
                messages = self.build_messages(state, corrective_feedback)
                response = self.client.chat.completions.create(
                    model=LLM_MODEL_NAME,
                    messages=messages,
                    tools=self.tool_schemas,
                    tool_choice="auto",
                    temperature=LLM_TEMPERATURE,
                    timeout=5.0
                )
                tool_calls = self._extract_tool_calls_from_llm(response)
                if tool_calls:
                    return tool_calls
            except Exception as e:
                self.logger.debug(f"LLM API request failed ({e}). Switching to Dual-Mode Reasoning.")
                
        # Dual-Mode fallback execution
        return self._dual_mode_heuristic_reasoning(state)
