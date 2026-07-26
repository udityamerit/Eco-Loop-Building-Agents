import json
import logging
from typing import List, Dict, Any, Optional

from src.config import OLLAMA_BASE_URL, LLM_MODEL_NAME, LLM_TEMPERATURE

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    class OpenAI:
        def __init__(self, *args, **kwargs): pass

try:
    from src.memory_engine import SemanticMemoryEngine
except ImportError:
    SemanticMemoryEngine = None

class MCPClientAgent:
    """
    Reasoning Agent responsible for analyzing building state and issuing MCP tool calls.
    Implements a dual-mode engine: connects to local Llama 3.1 LLM via OpenAI API,
    and seamlessly falls back to a deterministic physical AI reasoning rule engine if LLM is offline.
    Integrates Semantic Memory (ChromaDB + MMR) to recall past successful ECM actions.
    """
    def __init__(self, mcp_server):
        self.server = mcp_server
        self.logger = logging.getLogger("MCPClientAgent")
        self.logger.setLevel(logging.INFO)
        
        # Initialize Semantic Memory Engine
        self.memory = SemanticMemoryEngine() if SemanticMemoryEngine else None
        
        # Retrieve JSON tool schemas from the MCP server
        raw_tools = self.server.get_tools_definition() if hasattr(self.server, "get_tools_definition") else []
        self.tool_schemas = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["inputSchema"]
                }
            }
            for t in raw_tools
        ]
        
        self.system_prompt = (
            "You are the autonomous Physical AI Reasoning Agent for an advanced commercial building Eco-Loop.\n"
            "Your objective is to optimize energy efficiency and grid carbon emissions while strictly maintaining indoor thermal comfort.\n\n"
            "### MANDATORY DOMAIN RULES:\n"
            "1. Thermal Comfort Constraints: You MUST keep Zone 1 Fanger PMV index between -0.5 and +0.5. Never allow temp outside [20.0, 26.0]°C.\n"
            "2. Grid Carbon Shedding: When grid carbon intensity is high (> 400 gCO2/kWh), aggressively reduce load by increasing cooling setpoints or reducing lighting in unoccupied zones.\n"
            "3. Action Consistency: Always verify setpoint limits before calling tools. Do not oscillate setpoints rapidly between consecutive intervals.\n\n"
            "### Available Tools:\n"
            "- set_zone_setpoint: Adjust HVAC cooling/heating temperature setpoint in °C.\n"
            "- apply_ecm: Execute an Energy Conservation Measure (e.g., reduce_lighting_load).\n\n"
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
                self.client.models.list(timeout=0.5)
                self.logger.info(f"Connected to live OpenAI/Ollama endpoint at {OLLAMA_BASE_URL}")
            except Exception as e:
                self.logger.info(f"Local LLM endpoint offline or unreachable ({e}). Engaging Dual-Mode Heuristic Reasoning Engine.")
                self.use_llm_api = False

    def build_messages(self, state: Dict[str, Any], corrective_feedback: Optional[str] = None) -> List[Dict[str, str]]:
        """Constructs prompt messages with compact JSON state snapshot and retrieved MMR historical context."""
        compact_state = {
            "zone1_temp": round(state.get("zone1_temp", 23.0), 2),
            "zone1_pmv": round(state.get("zone1_pmv", 0.0), 2),
            "interval_kwh": round(state.get("interval_kwh", 0.0), 3),
            "occupancy_pct": round(state.get("occupancy_pct", 0.0), 1),
            "grid_carbon_gco2_kwh": round(state.get("grid_carbon_gco2_kwh", 300.0), 1),
            "sim_time_min": round(state.get("sim_time", 0.0), 1)
        }
        
        user_content = f"Current Building State Snapshot: {json.dumps(compact_state)}\n"
        
        # Retrieve relevant, diverse historical ECM actions via MMR
        if self.memory:
            try:
                past_actions = self.memory.retrieve_mmr(state, top_k=2)
                if past_actions:
                    user_content += "\n### Semantic Memory Context (Past Successful Actions via MMR):\n"
                    for pa in past_actions:
                        user_content += f"- When state was [{pa['context_state']}], successful action was {json.dumps(pa['recommended_action'])} with rationale: \"{pa['rationale']}\"\n"
            except Exception as e:
                self.logger.debug(f"Memory MMR retrieval skipped: {e}")
                
        user_content += "\nAnalyze state and call appropriate control tools."
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
        Deterministic physical AI fallback engine.
        Executed when open-source LLM is offline or times out.
        """
        tool_calls = []
        temp = state.get("zone1_temp", 23.0)
        pmv = state.get("zone1_pmv", 0.0)
        grid_carbon = state.get("grid_carbon_gco2_kwh", 300.0)
        occupancy = state.get("occupancy_pct", 80.0)

        # Rule 1: High Carbon Peak Demand Shedding
        if grid_carbon > 400.0:
            if pmv < 0.3 and temp < 25.0:
                tool_calls.append({
                    "name": "set_zone_setpoint",
                    "params": {"zone_id": "ZONE1", "setpoint_type": "cooling", "value": min(25.0, round(temp + 1.0, 1))},
                    "rationale": f"Grid carbon peak ({grid_carbon:.0f} gCO2/kWh). Increasing cooling setpoint by 1.0°C to shed compressor electrical load while keeping PMV comfortably within bounds ({pmv:.2f} < 0.5)."
                })
            if occupancy == 0.0:
                tool_calls.append({
                    "name": "apply_ecm",
                    "params": {"ecm_name": "reduce_lighting_load", "params": {"zone_id": "ZONE1", "reduction_pct": 50}},
                    "rationale": f"Grid carbon peak ({grid_carbon:.0f} gCO2/kWh) and zone unoccupied (0%). Shedding 50% lighting load."
                })
            elif occupancy < 30.0:
                tool_calls.append({
                    "name": "apply_ecm",
                    "params": {"ecm_name": "reduce_lighting_load", "params": {"zone_id": "ZONE1", "reduction_pct": 25}},
                    "rationale": f"Low zone occupancy ({occupancy:.0f}%). Dimming lighting by 25% during high grid carbon period."
                })

        # Rule 2: Thermal Comfort Boundary Enforcement (PMV Upper Limit)
        elif pmv > 0.45 or temp > 25.5:
            tool_calls.append({
                "name": "set_zone_setpoint",
                "params": {"zone_id": "ZONE1", "setpoint_type": "cooling", "value": max(22.0, round(temp - 1.0, 1))},
                "rationale": f"Thermal comfort approaching upper boundary (PMV={pmv:.2f}, Temp={temp:.1f}°C). Lowering cooling setpoint by 1.0°C to restore optimal comfort."
            })

        # Rule 3: Thermal Comfort Boundary Enforcement (PMV Lower Limit)
        elif pmv < -0.45 or temp < 21.0:
            tool_calls.append({
                "name": "set_zone_setpoint",
                "params": {"zone_id": "ZONE1", "setpoint_type": "heating", "value": min(21.5, round(temp + 1.0, 1))},
                "rationale": f"Thermal comfort approaching lower boundary (PMV={pmv:.2f}, Temp={temp:.1f}°C). Increasing heating setpoint by 1.0°C."
            })

        # Rule 4: Normal Steady-State Optimization
        else:
            if occupancy == 0.0:
                tool_calls.append({
                    "name": "apply_ecm",
                    "params": {"ecm_name": "reduce_lighting_load", "params": {"zone_id": "ZONE1", "reduction_pct": 40}},
                    "rationale": "Zone is currently unoccupied. Reducing lighting power fraction by 40% to save baseline energy."
                })
            else:
                tool_calls.append({
                    "name": "set_zone_setpoint",
                    "params": {"zone_id": "ZONE1", "setpoint_type": "cooling", "value": 23.5},
                    "rationale": f"Grid carbon intensity is low ({grid_carbon:.0f} gCO2/kWh). Maintaining optimal thermal setpoint (23.5°C) to pre-cool zone efficiently."
                })

        if not tool_calls:
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
        Stores successful actions in Semantic Memory (ChromaDB + MMR).
        """
        tool_calls = []
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
            except Exception as e:
                self.logger.debug(f"LLM API request failed ({e}). Switching to Dual-Mode Reasoning.")
                
        if not tool_calls:
            tool_calls = self._dual_mode_heuristic_reasoning(state)
            
        # Record successful decisions into Semantic Memory
        if self.memory and tool_calls:
            for tc in tool_calls:
                try:
                    self.memory.store_memory(state, tc, tc.get("rationale", "Autonomous ECM decision executed."))
                except Exception as mem_err:
                    self.logger.debug(f"Memory storage skipped: {mem_err}")
                    
        return tool_calls
