"""
AWS EC2 Continuous Simulation Worker Service for Eco-Loop Building Agents.
Provides a REST API for serverless AWS Lambda orchestration functions to poll state and apply actuator tool calls.
"""
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from src.config import IDF_PATH, EPW_PATH, AI_LOGS_DIR
from src.energyplus_wrapper import EnergyPlusSession
from src.ecm_logic import ECMLogic

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    # Fallback dummy for environments where FastAPI is not installed
    class FastAPI:
        def __init__(self, *args, **kwargs): pass
        def get(self, *args, **kwargs): return lambda f: f
        def post(self, *args, **kwargs): return lambda f: f
    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str):
            super().__init__(detail)
            self.status_code = status_code
    class JSONResponse:
        def __init__(self, content: Any, status_code: int = 200):
            self.content = content
            self.status_code = status_code

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("EC2SimulationWorker")

app = FastAPI(title="Eco-Loop EC2 Simulation Worker API", version="2.0.0")

# Global session management
_sim_session: Optional[EnergyPlusSession] = None
_ecm_logic: Optional[ECMLogic] = None

def get_session() -> EnergyPlusSession:
    global _sim_session, _ecm_logic
    if _sim_session is None:
        logger.info("Initializing EC2 EnergyPlus simulation session...")
        _sim_session = EnergyPlusSession(IDF_PATH, EPW_PATH, AI_LOGS_DIR, mode_label="ec2_worker")
        _ecm_logic = ECMLogic()
    return _sim_session

def get_ecm() -> ECMLogic:
    global _ecm_logic
    if _ecm_logic is None:
        get_session()
    return _ecm_logic

class ToolCallRequest(BaseModel):
    name: str
    params: Dict[str, Any]
    rationale: Optional[str] = "Lambda Cloud Orchestration"

class StepRequest(BaseModel):
    tool_calls: List[ToolCallRequest] = []

@app.get("/health")
def health_check():
    """Health check endpoint for Docker and AWS ALB target group verification."""
    session = get_session()
    state = session.get_state()
    return {
        "status": "healthy",
        "sim_time": state.get("sim_time", 0.0),
        "zone1_temp": state.get("zone1_temp", 23.0),
        "engine": "EnergyPlus Continuous Worker"
    }

@app.get("/state")
def fetch_state():
    """Returns the current real-time building simulation state."""
    session = get_session()
    return session.get_state()

@app.post("/step")
def step_simulation(payload: StepRequest):
    """
    Applies validated tool calls requested by AWS Lambda and advances the simulation by one interval.
    """
    session = get_session()
    ecm = get_ecm()
    state = session.get_state()
    
    # Convert request models to dictionary tool calls
    raw_calls = [
        {"name": tc.name, "params": tc.params, "rationale": tc.rationale}
        for tc in payload.tool_calls
    ]
    
    if raw_calls:
        logger.info(f"Applying {len(raw_calls)} tool calls from AWS Lambda orchestration...")
        ecm.validate_and_apply(raw_calls, session, state)
        
    session.step()
    new_state = session.get_state()
    return {
        "status": "advanced",
        "previous_time": state.get("sim_time"),
        "new_time": new_state.get("sim_time"),
        "current_state": new_state
    }

@app.post("/reset")
def reset_simulation():
    """Resets the simulation session back to timestep 0."""
    global _sim_session
    logger.info("Resetting EC2 simulation environment...")
    _sim_session = None
    return {"status": "reset", "message": "Simulation session re-initialized."}
