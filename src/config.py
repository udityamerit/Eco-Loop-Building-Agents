import os
from pathlib import Path

# Project base directories
BASE_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = BASE_DIR / "models"
LOGS_DIR = BASE_DIR / "logs"
RUNTIME_DIR = MODELS_DIR / "runtime_generated"
BASELINE_LOGS_DIR = LOGS_DIR / "baseline_run"
AI_LOGS_DIR = LOGS_DIR / "ai_run"

# Ensure log and runtime directories exist
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
BASELINE_LOGS_DIR.mkdir(parents=True, exist_ok=True)
AI_LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Model paths
IDF_PATH = MODELS_DIR / "baseline_building.idf"
EPW_PATH = MODELS_DIR / "baseline_weather.epw"

# Simulation timing parameters
SIM_TIMESTEP_MINUTES = 1         # 1 minute per EnergyPlus step
CONTROL_INTERVAL_MINUTES = 15    # LLM agent polled every 15 simulated minutes
SIM_HORIZON_DAYS = 3             # 3-day multi-day simulation horizon for grading evaluation

# Thermal comfort boundaries (Fanger PMV Model & Temperature limits)
PMV_LOWER_BOUND = -0.5
PMV_UPPER_BOUND = 0.5
TEMP_MIN_CELSIUS = 20.0
TEMP_MAX_CELSIUS = 26.0

# HVAC Actuator bounds and constraints
COOLING_SETPOINT_MIN = 21.0
COOLING_SETPOINT_MAX = 26.0
HEATING_SETPOINT_MIN = 18.0
HEATING_SETPOINT_MAX = 22.0
MAX_SETPOINT_SWING_PER_CYCLE = 1.5

# Watchdog parameters
MAX_CONSECUTIVE_FAILURES = 3

# Default known-safe setpoints (used by watchdog failover)
DEFAULT_SAFE_SETPOINTS = {
    "zone1_cooling_sp": 24.0,
    "zone1_heating_sp": 20.0,
    "zone1_lighting_fraction": 1.0,
}

# LLM Configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "llama3.1")
LLM_TEMPERATURE = 0.1  # Low temperature for deterministic policy behavior
