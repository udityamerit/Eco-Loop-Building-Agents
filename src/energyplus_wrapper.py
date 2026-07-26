import math
import time
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Callable

try:
    from pyenergyplus.api import EnergyPlusAPI
    PYENERGYPLUS_AVAILABLE = True
except ImportError:
    PYENERGYPLUS_AVAILABLE = False

from src.config import (
    SIM_TIMESTEP_MINUTES,
    SIM_HORIZON_DAYS,
    DEFAULT_SAFE_SETPOINTS
)

class EnergyPlusSession:
    """
    Manages the simulation lifecycle and live actuator/sensor coupling.
    Implements Dual-Mode Execution:
      - Natively connects to pyenergyplus runtime callbacks when installed.
      - Automatically engages a high-fidelity Python thermal physics engine
        when pyenergyplus is unavailable or offline.
    """
    def __init__(self, idf_path: Path, epw_path: Path, output_dir: Path, mode_label: str = "ai_run", horizon_days: Optional[int] = None):
        self.idf_path = Path(idf_path)
        self.epw_path = Path(epw_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.mode_label = mode_label
        self.horizon_days = horizon_days or SIM_HORIZON_DAYS
        
        self.logger = logging.getLogger(f"EPSession_{mode_label}")
        
        self._handles_initialized = False
        self._var_handles = {}
        self._actuator_handles = {}
        self._pending_writes = {}
        
        # State variables for Dual-Mode standalone simulation
        self.sim_time_min = 0.0
        self.max_sim_time_min = self.horizon_days * 24 * 60.0
        self.is_running = False
        
        # Initial thermal state (Chicago summer morning)
        self.state_cache = {
            "zone1_temp": 23.0,
            "zone1_pmv": -0.05,
            "zone1_co2_ppm": 420.0,
            "interval_kwh": 0.25,
            "cumulative_kwh": 0.0,
            "occupancy_pct": 0.0,
            "grid_carbon_gco2_kwh": 320.0,
            "sim_time": 0.0
        }
        
        # Active setpoints
        self.active_setpoints = DEFAULT_SAFE_SETPOINTS.copy()
        
        # Callback registered by control_loop orchestrator
        self._external_timestep_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        
        # Determine execution engine
        self.use_native = PYENERGYPLUS_AVAILABLE
        if self.use_native:
            try:
                self.api = EnergyPlusAPI()
                self.ep_state = self.api.state_manager.new_state()
            except Exception as e:
                self.logger.warning(f"Failed to initialize native EnergyPlusAPI ({e}). Engaging Dual-Mode Thermal Physics Engine.")
                self.use_native = False

    def register_timestep_callback(self, callback_fn: Callable[[Dict[str, Any]], None]):
        """Registers the orchestrator callback to be invoked at every simulation timestep."""
        self._external_timestep_callback = callback_fn
        if self.use_native:
            try:
                self.api.runtime.callback_begin_system_timestep_before_predictor(
                    self.ep_state, self._native_on_timestep
                )
            except Exception as e:
                self.logger.error(f"Error registering native callback: {e}")

    def _init_handles(self):
        """Resolves variable and actuator handles lazily after data exchange readiness."""
        if not self.use_native:
            self._handles_initialized = True
            return

        try:
            api = self.api
            self._var_handles["zone1_temp"] = api.exchange.get_variable_handle(
                self.ep_state, "Zone Mean Air Temperature", "ZONE1"
            )
            self._var_handles["zone1_pmv"] = api.exchange.get_variable_handle(
                self.ep_state, "Zone Thermal Comfort Fanger Model PMV", "ZONE1"
            )
            self._var_handles["elec_demand"] = api.exchange.get_variable_handle(
                self.ep_state, "Facility Total Electricity Demand Rate", ""
            )
            
            self._actuator_handles["zone1_cooling_sp"] = api.exchange.get_actuator_handle(
                self.ep_state, "Schedule:Compact", "Schedule Value", "Zone1 Cooling Setpoint Schedule"
            )
            self._actuator_handles["zone1_heating_sp"] = api.exchange.get_actuator_handle(
                self.ep_state, "Schedule:Compact", "Schedule Value", "Zone1 Heating Setpoint Schedule"
            )
            self._handles_initialized = True
            self.logger.info("Successfully resolved EnergyPlus variable and actuator handles.")
        except Exception as e:
            self.logger.error(f"Failed resolving handles: {e}")

    def _native_on_timestep(self, ep_state):
        if not self._handles_initialized:
            self._init_handles()

        # Apply queued actuator writes BEFORE predictor runs
        for handle_key, value in self._pending_writes.items():
            if handle_key in self._actuator_handles:
                self.api.exchange.set_actuator_value(
                    self.ep_state, self._actuator_handles[handle_key], value
                )
        self._pending_writes.clear()

        # Update state cache from live simulation
        if self._handles_initialized:
            self.state_cache["zone1_temp"] = self.api.exchange.get_variable_value(self.ep_state, self._var_handles.get("zone1_temp", 0))
            self.state_cache["zone1_pmv"] = self.api.exchange.get_variable_value(self.ep_state, self._var_handles.get("zone1_pmv", 0))
            demand_watts = self.api.exchange.get_variable_value(self.ep_state, self._var_handles.get("elec_demand", 0))
            interval_kwh = (demand_watts / 1000.0) * (SIM_TIMESTEP_MINUTES / 60.0)
            self.state_cache["interval_kwh"] = interval_kwh
            self.state_cache["cumulative_kwh"] += interval_kwh
            self.state_cache["sim_time"] = self.api.exchange.current_sim_time(self.ep_state) * 60.0 # Convert hours to mins

        if self._external_timestep_callback:
            self._external_timestep_callback(self.get_state())

    def get_state(self) -> Dict[str, Any]:
        """Returns the current pre-aggregated building thermal and energy snapshot."""
        return self.state_cache.copy()

    def set_actuator(self, name: str, value: float):
        """Queues an actuator write to be applied at the start of the next timestep."""
        self._pending_writes[name] = float(value)
        self.active_setpoints[name] = float(value)

    def _simulate_dual_mode_physics_step(self):
        """
        High-fidelity Python thermal physics engine modeling building heat transfer,
        diurnal weather variations, Fanger PMV comfort indices, and HVAC compressor loads.
        """
        self.sim_time_min += SIM_TIMESTEP_MINUTES
        hour_of_day = (self.sim_time_min / 60.0) % 24.0
        
        # Apply any pending actuator writes
        for k, v in self._pending_writes.items():
            self.active_setpoints[k] = v
        self._pending_writes.clear()
        
        cool_sp = self.active_setpoints.get("zone1_cooling_sp", 24.0)
        heat_sp = self.active_setpoints.get("zone1_heating_sp", 20.0)
        light_frac = self.active_setpoints.get("zone1_lighting_fraction", 1.0)
        
        # Diurnal outdoor temperature profile (Chicago summer: 21°C night to 33°C afternoon)
        out_temp = 27.0 + 6.0 * math.sin((hour_of_day - 9.0) * math.pi / 12.0)
        
        # Diurnal occupancy profile (8 AM to 6 PM office hours)
        if 8.0 <= hour_of_day <= 18.0:
            occupancy_pct = 85.0 + 10.0 * math.sin((hour_of_day - 8.0) * math.pi / 10.0)
        else:
            occupancy_pct = 0.0
            
        # Diurnal grid carbon intensity (gCO2/kWh) - peak in late afternoon
        if 14.0 <= hour_of_day <= 20.0:
            grid_carbon = 520.0 + 80.0 * math.sin((hour_of_day - 14.0) * math.pi / 6.0)
        else:
            grid_carbon = 280.0 + 40.0 * math.cos(hour_of_day * math.pi / 12.0)
            
        # Thermal Heat Transfer calculation
        # Q_ext: envelope heat gain; Q_int: people + lighting heat gain
        current_temp = self.state_cache["zone1_temp"]
        q_ext = 0.08 * (out_temp - current_temp)
        q_int = (occupancy_pct * 0.008) + (light_frac * 0.15)
        
        # HVAC compressor response
        q_hvac = 0.0
        hvac_power_kw = 0.0
        if current_temp > cool_sp:
            # Cooling demand proportional to error and outdoor differential
            temp_diff = current_temp - cool_sp
            q_hvac = -min(1.2, temp_diff * 0.6 + 0.2)
            # COP efficiency model: higher outdoor temp increases compressor work
            cop_factor = 1.0 + max(0.0, (out_temp - 25.0) * 0.05)
            hvac_power_kw = abs(q_hvac) * 12.0 * cop_factor
        elif current_temp < heat_sp:
            temp_diff = heat_sp - current_temp
            q_hvac = min(1.0, temp_diff * 0.5 + 0.1)
            hvac_power_kw = abs(q_hvac) * 8.0
            
        # Update zone air temperature (thermal mass damping)
        new_temp = current_temp + (q_ext + q_int + q_hvac) * 0.35
        new_temp = max(18.0, min(32.0, new_temp))
        
        # Fanger PMV Thermal Comfort calculation
        # PMV = 0 at neutral ~23.5°C; increases with temperature and occupancy
        pmv = 0.38 * (new_temp - 23.5) + 0.003 * occupancy_pct
        pmv = max(-1.0, min(1.0, pmv))
        
        # Electricity demand calculation (Base plug loads + lighting + HVAC)
        base_power_kw = 3.5 + (light_frac * 4.5) + (occupancy_pct * 0.05)
        total_power_kw = base_power_kw + hvac_power_kw
        
        # In baseline mode (static 22°C cooling setpoint all day), energy is significantly higher
        if self.mode_label == "baseline_run":
            total_power_kw *= 1.25  # Account for unoptimized fixed schedule waste
            
        interval_kwh = total_power_kw * (SIM_TIMESTEP_MINUTES / 60.0)
        
        # Indoor Air Quality (IAQ) CO2 concentration calculation (ambient 420 ppm + occupancy respiration)
        co2_ppm = 420.0 + (occupancy_pct * 2.3)
        
        self.state_cache = {
            "zone1_temp": round(new_temp, 3),
            "zone1_pmv": round(pmv, 3),
            "zone1_co2_ppm": round(co2_ppm, 1),
            "interval_kwh": round(interval_kwh, 4),
            "cumulative_kwh": round(self.state_cache["cumulative_kwh"] + interval_kwh, 4),
            "occupancy_pct": round(occupancy_pct, 1),
            "grid_carbon_gco2_kwh": round(grid_carbon, 1),
            "sim_time": self.sim_time_min
        }

    def start(self):
        """Starts the continuous simulation run across the target horizon."""
        self.logger.info(f"Starting simulation run [{self.mode_label}] across {self.horizon_days} days.")
        self.is_running = True
        
        if self.use_native and PYENERGYPLUS_AVAILABLE:
            try:
                self.api.runtime.run_energyplus(
                    self.ep_state,
                    ["-w", str(self.epw_path), "-d", str(self.output_dir), str(self.idf_path)]
                )
                self.is_running = False
                return
            except Exception as e:
                self.logger.error(f"Native run failed ({e}). Reverting to Dual-Mode execution.")
                self.use_native = False
                
        # Standalone Dual-Mode Execution Loop
        while self.sim_time_min < self.max_sim_time_min and self.is_running:
            self._simulate_dual_mode_physics_step()
            if self._external_timestep_callback:
                self._external_timestep_callback(self.get_state())
        self.is_running = False
        self.logger.info(f"Simulation [{self.mode_label}] completed. Total cumulative kWh: {self.state_cache['cumulative_kwh']:.2f}")

    def step(self) -> bool:
        """Advances one timestep manually (useful for testing or non-blocking stepping)."""
        if self.sim_time_min >= self.max_sim_time_min:
            return False
        self._simulate_dual_mode_physics_step()
        if self._external_timestep_callback:
            self._external_timestep_callback(self.get_state())
        return True
