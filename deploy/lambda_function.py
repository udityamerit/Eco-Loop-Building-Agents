"""
AWS Lambda Serverless Orchestration Handler for Eco-Loop Building Agents.
Decouples cognitive LLM reasoning from EC2 continuous physics simulation.
Triggered periodically via AWS EventBridge (every 15 simulated minutes / cron).
"""
import os
import sys
import json
import logging
from typing import Dict, Any

# Ensure parent library is in path when running in Lambda bundle
sys.path.append("/opt/python")
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import CONTROL_INTERVAL_MINUTES
from src.mcp_client_agent import MCPClientAgent

try:
    import urllib.request
    import urllib.error
except ImportError:
    pass

logger = logging.getLogger("AWSLambdaOrchestrator")
logger.setLevel(logging.INFO)

# Configuration from Lambda environment variables
EC2_WORKER_URL = os.getenv("EC2_WORKER_URL", "http://localhost:8000")
USE_LOCAL_FALLBACK = os.getenv("USE_LOCAL_FALLBACK", "true").lower() == "true"

def _fetch_state_from_ec2() -> Dict[str, Any]:
    """Fetches real-time building state from EC2 continuous simulation worker."""
    url = f"{EC2_WORKER_URL}/state"
    req = urllib.request.Request(url, headers={"User-Agent": "AWS-Lambda-Orchestrator"})
    with urllib.request.urlopen(req, timeout=3.0) as response:
        return json.loads(response.read().decode("utf-8"))

def _send_tool_calls_to_ec2(tool_calls: list) -> Dict[str, Any]:
    """Sends validated reasoning decisions back to EC2 simulation engine."""
    url = f"{EC2_WORKER_URL}/step"
    payload = json.dumps({"tool_calls": tool_calls}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "AWS-Lambda-Orchestrator"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=5.0) as response:
        return json.loads(response.read().decode("utf-8"))

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda entrypoint.
    1. Polls EC2 simulation worker for building state.
    2. Invokes MCPClientAgent (Llama 3.1 / Heuristic fallback / Semantic Memory).
    3. Emits structured tool calls back to EC2 simulation worker.
    """
    logger.info(f"Lambda orchestration cycle triggered. Event: {event}")
    
    try:
        # Step 1: Fetch building state
        try:
            state = _fetch_state_from_ec2()
            logger.info(f"Fetched state from EC2 worker: sim_time={state.get('sim_time')}m, temp={state.get('zone1_temp')}C")
        except Exception as ec2_err:
            if not USE_LOCAL_FALLBACK:
                raise ec2_err
            logger.warning(f"EC2 worker unreachable ({ec2_err}). Using local hybrid state emulation...")
            state = {
                "sim_time": event.get("sim_time", 15.0),
                "zone1_temp": event.get("zone1_temp", 23.5),
                "zone1_pmv": event.get("zone1_pmv", 0.1),
                "interval_kwh": event.get("interval_kwh", 1.2),
                "grid_carbon_gco2_kwh": event.get("grid_carbon_gco2_kwh", 320.0),
                "occupancy_pct": event.get("occupancy_pct", 80.0)
            }
            
        # Step 2: Cognitive Reasoning Cycle
        # Create a mock server interface for MCPClientAgent if needed
        class DummyServer:
            def get_tools_definition(self):
                from src.mcp_server import MCPServer
                return MCPServer(None, None).get_tools_definition()
                
        agent = MCPClientAgent(DummyServer())
        tool_calls = agent.decide(state)
        logger.info(f"Agent generated {len(tool_calls)} control decisions: {[tc.get('name') for tc in tool_calls]}")
        
        # Step 3: Send decisions back to EC2
        try:
            step_resp = _send_tool_calls_to_ec2(tool_calls)
            status = step_resp.get("status", "success")
        except Exception as post_err:
            logger.warning(f"Failed to post step back to EC2 ({post_err}). Local emulation mode completed.")
            status = "local_emulated"
            
        return {
            "statusCode": 200,
            "body": json.dumps({
                "status": status,
                "sim_time": state.get("sim_time"),
                "decisions": tool_calls,
                "engine": "AWS Lambda Serverless Orchestrator"
            })
        }
    except Exception as e:
        logger.error(f"Lambda orchestration failed: {str(e)}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e), "message": "AWS Lambda Orchestration Failure"})
        }

if __name__ == "__main__":
    # Test local execution
    print(lambda_handler({"sim_time": 30.0, "zone1_temp": 24.2, "zone1_pmv": 0.3}, None))
