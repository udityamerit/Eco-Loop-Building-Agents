import logging
from typing import List, Dict, Any, Tuple
from src.config import (
    PMV_LOWER_BOUND,
    PMV_UPPER_BOUND,
    TEMP_MIN_CELSIUS,
    TEMP_MAX_CELSIUS,
    COOLING_SETPOINT_MIN,
    COOLING_SETPOINT_MAX,
    HEATING_SETPOINT_MIN,
    HEATING_SETPOINT_MAX,
    DEFAULT_SAFE_SETPOINTS
)

class AgentDecisionError(Exception):
    """Raised when an agent tool call is malformed or violates hard physical comfort boundaries."""
    pass

class ECMLogic:
    """
    Validation and translation boundary for Energy Conservation Measures (ECMs) and actuator writes.
    Enforces hard occupant thermal comfort limits and provides watchdog failover protection.
    """
    def __init__(self):
        self.logger = logging.getLogger("ECMLogic")
        self.last_safe_setpoints = DEFAULT_SAFE_SETPOINTS.copy()

    def get_comfort_bounds(self) -> Dict[str, Any]:
        """Returns static physical and thermal comfort boundaries mandated for the agent."""
        return {
            "pmv_lower_bound": PMV_LOWER_BOUND,
            "pmv_upper_bound": PMV_UPPER_BOUND,
            "temp_min_celsius": TEMP_MIN_CELSIUS,
            "temp_max_celsius": TEMP_MAX_CELSIUS,
            "cooling_sp_range": [COOLING_SETPOINT_MIN, COOLING_SETPOINT_MAX],
            "heating_sp_range": [HEATING_SETPOINT_MIN, HEATING_SETPOINT_MAX]
        }

    def validate_tool_call(self, tool_call: Dict[str, Any], current_state: Dict[str, Any]) -> Tuple[bool, str, Dict[str, float]]:
        """
        Validates a single tool call against hard comfort and physical actuator limits.
        Returns (is_valid, reason_or_error, actuator_updates_dict).
        """
        tool_name = tool_call.get("name") or tool_call.get("tool_called")
        params = tool_call.get("params") or tool_call.get("arguments") or {}
        
        if not tool_name or not isinstance(params, dict):
            return False, "Malformed tool call structure: missing 'name' or 'params'", {}

        updates = {}

        if tool_name == "set_zone_setpoint":
            zone_id = params.get("zone_id", "ZONE1")
            sp_type = params.get("setpoint_type", "").lower()
            try:
                val = float(params.get("value", 0.0))
            except (ValueError, TypeError):
                return False, f"Invalid numeric setpoint value: {params.get('value')}", {}

            if sp_type == "cooling":
                if val < COOLING_SETPOINT_MIN or val > COOLING_SETPOINT_MAX:
                    return False, f"Cooling setpoint {val}°C outside allowed bounds [{COOLING_SETPOINT_MIN}, {COOLING_SETPOINT_MAX}]°C", {}
                # Prevent cooling setpoint from dropping too low if PMV is already negative
                if current_state.get("zone1_pmv", 0.0) <= PMV_LOWER_BOUND and val < 24.0:
                    return False, f"Cannot lower cooling setpoint to {val}°C when PMV is already at lower bound ({current_state.get('zone1_pmv')})", {}
                updates["zone1_cooling_sp"] = val

            elif sp_type == "heating":
                if val < HEATING_SETPOINT_MIN or val > HEATING_SETPOINT_MAX:
                    return False, f"Heating setpoint {val}°C outside allowed bounds [{HEATING_SETPOINT_MIN}, {HEATING_SETPOINT_MAX}]°C", {}
                updates["zone1_heating_sp"] = val

            elif sp_type == "supply_air_temp":
                if val < 12.0 or val > 20.0:
                    return False, f"Supply air temperature {val}°C out of valid bounds [12.0, 20.0]°C", {}
                updates["supply_air_sp"] = val

            else:
                return False, f"Unknown setpoint_type: {sp_type}. Must be in {{'heating', 'cooling', 'supply_air_temp'}}", {}

        elif tool_name == "apply_ecm":
            ecm_name = params.get("ecm_name") or params.get("name", "")
            if ecm_name == "reduce_lighting_load":
                try:
                    reduction_pct = float(params.get("reduction_pct", 50.0))
                except (ValueError, TypeError):
                    return False, "Invalid numeric reduction_pct", {}
                
                # Check occupancy: do not slash lighting if zone is heavily occupied
                occ = current_state.get("occupancy_pct", 0.0)
                if occ > 20.0 and reduction_pct > 30.0:
                    return False, f"Cannot reduce lighting by {reduction_pct}% when zone is occupied ({occ}%)", {}
                
                new_frac = max(0.1, 1.0 - (reduction_pct / 100.0))
                updates["zone1_lighting_fraction"] = round(new_frac, 2)

            elif ecm_name == "pre_cool_flush":
                # Pre-cool during low carbon intensity by lowering cooling setpoint slightly within safe bounds
                updates["zone1_cooling_sp"] = max(COOLING_SETPOINT_MIN, 22.5)
            else:
                return False, f"Unsupported ECM strategy: {ecm_name}", {}

        elif tool_name in ["get_building_state", "get_comfort_bounds"]:
            # Read-only tools require no actuator changes
            return True, "Read-only tool call accepted", {}

        else:
            return False, f"Unrecognized tool function: {tool_name}", {}

        return True, "Validated successfully against hard boundaries", updates

    def validate_and_apply(self, tool_calls: List[Dict[str, Any]], ep_session, current_state: Dict[str, Any]) -> Dict[str, float]:
        """
        Validates a list of tool calls. If all are valid, applies them to the EnergyPlus session.
        If any validation fails, raises AgentDecisionError to trigger self-correction retry or watchdog.
        Returns the dictionary of applied actuator setpoints.
        """
        if not tool_calls:
            raise AgentDecisionError("Agent returned no tool calls to apply.")

        combined_updates = {}
        for tc in tool_calls:
            is_valid, reason, updates = self.validate_tool_call(tc, current_state)
            if not is_valid:
                self.logger.warning(f"Validation rejection: {reason} | ToolCall: {tc}")
                raise AgentDecisionError(f"Tool validation failed: {reason}")
            combined_updates.update(updates)

        # Apply to live simulation session
        for actuator_key, val in combined_updates.items():
            ep_session.set_actuator(actuator_key, val)

        if combined_updates:
            self.last_safe_setpoints.update(combined_updates)
            
        return self.last_safe_setpoints.copy()

    def apply_raw(self, setpoints_dict: Dict[str, float], ep_session):
        """
        Directly applies a dictionary of known-safe setpoints (used by watchdog failover).
        """
        if not setpoints_dict:
            setpoints_dict = self.last_safe_setpoints.copy()
        self.logger.warning(f"[WATCHDOG FAILOVER] Restoring safe actuator setpoints: {setpoints_dict}")
        for k, v in setpoints_dict.items():
            ep_session.set_actuator(k, v)
        self.last_safe_setpoints.update(setpoints_dict)
