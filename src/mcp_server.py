import logging
from typing import Dict, Any, List, Optional
from src.ecm_logic import ECMLogic

try:
    from src.ml_forecaster import MLForecaster
except ImportError:
    MLForecaster = None

class MCPServer:
    """
    Model Context Protocol (MCP) Server exposing typed, validated tools to the LLM agent.
    Provides schema definitions for LLM tool calling and routes executions through ECMLogic.
    Insects Hybrid Predictive ML forecasts into building state payloads for executive LLM orchestration.
    """
    def __init__(self, ep_session, ecm_logic: ECMLogic):
        self.ep_session = ep_session
        self.ecm_logic = ecm_logic
        self.logger = logging.getLogger("MCPServer")
        self.ml_forecaster = MLForecaster() if MLForecaster else None

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Returns standard OpenAI/MCP-compatible JSON schema definitions for available tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_building_state",
                    "description": "Returns current zone air temperatures, PMV comfort indices, energy demand, grid carbon intensity, and Hybrid Predictive ML forecasts (RandomForest/SVM/LogisticRegression) for upcoming timesteps.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_comfort_bounds",
                    "description": "Returns static physical thermal comfort boundaries (PMV in [-0.5, 0.5]) and allowed setpoint ranges that must be respected.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "set_zone_setpoint",
                    "description": "Sets heating, cooling, or supply air temperature setpoint for a specific building zone.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "zone_id": {"type": "string", "description": "Target zone identifier, e.g. 'ZONE1'"},
                            "setpoint_type": {"type": "string", "enum": ["heating", "cooling", "supply_air_temp"], "description": "Type of setpoint to adjust"},
                            "value": {"type": "number", "description": "New temperature setpoint in Celsius"}
                        },
                        "required": ["zone_id", "setpoint_type", "value"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "apply_ecm",
                    "description": "Applies a higher-level Energy Conservation Measure (ECM) strategy such as unoccupied lighting shedding.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ecm_name": {"type": "string", "enum": ["reduce_lighting_load", "pre_cool_flush"], "description": "Name of the ECM strategy to execute"},
                            "params": {
                                "type": "object",
                                "description": "Strategy parameters, e.g. {'zone_id': 'ZONE1', 'reduction_pct': 50}",
                                "additionalProperties": True
                            }
                        },
                        "required": ["ecm_name", "params"]
                    }
                }
            }
        ]

    def get_tools_definition(self) -> List[Dict[str, Any]]:
        """Legacy helper returning schemas in MCP internal format."""
        schemas = self.get_tool_schemas()
        return [
            {
                "name": s["function"]["name"],
                "description": s["function"]["description"],
                "inputSchema": s["function"]["parameters"]
            }
            for s in schemas
        ]

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Executes a tool invocation requested by the reasoning agent."""
        self.logger.debug(f"Executing MCP Tool: {tool_name} | Args: {arguments}")
        
        if tool_name == "get_building_state":
            state = self.ep_session.get_state() if self.ep_session else {}
            if self.ml_forecaster and state:
                try:
                    forecast = self.ml_forecaster.predict_next(state)
                    state["ml_predictive_forecast"] = forecast
                except Exception as e:
                    self.logger.debug(f"ML forecast injection skipped: {e}")
            return {"status": "success", "data": state}
            
        elif tool_name == "get_comfort_bounds":
            bounds = self.ecm_logic.get_comfort_bounds() if self.ecm_logic else {}
            return {"status": "success", "data": bounds}
            
        elif tool_name in ["set_zone_setpoint", "apply_ecm"]:
            # Validate against ECMLogic boundary
            tool_call_payload = {"name": tool_name, "params": arguments}
            current_state = self.ep_session.get_state() if self.ep_session else {}
            is_valid, reason, updates = self.ecm_logic.validate_tool_call(tool_call_payload, current_state)
            if not is_valid:
                return {"status": "error", "error": f"Validation failed: {reason}", "accepted": False}
            
            # Queue valid updates in session
            if self.ep_session:
                for k, v in updates.items():
                    self.ep_session.set_actuator(k, v)
                
            return {"status": "success", "accepted": True, "reason": reason, "actuator_updates": updates}
            
        else:
            return {"status": "error", "error": f"Unknown tool: {tool_name}", "accepted": False}
