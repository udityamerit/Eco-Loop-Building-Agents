import unittest
import shutil
from pathlib import Path
from src.config import BASE_DIR, DEFAULT_SAFE_SETPOINTS, MAX_CONSECUTIVE_FAILURES
from src.ecm_logic import ECMLogic, AgentDecisionError
from src.energyplus_wrapper import EnergyPlusSession
from src.mcp_server import MCPServer
from src.mcp_client_agent import MCPClientAgent
from src.metrics_logger import MetricsLogger
from src.control_loop import ControlLoop

class TestControlLoopAndValidation(unittest.TestCase):
    """
    Unit test suite for Eco-Loop Building Agents.
    Verifies constraint boundary enforcement, actuator validation,
    malformed response handling, watchdog failover, and simulation stepping.
    """
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.test_dir = Path(tempfile.mkdtemp())
        cls.idf_path = BASE_DIR / "models" / "baseline_building.idf"
        cls.epw_path = BASE_DIR / "models" / "baseline_weather.epw"

    @classmethod
    def tearDownClass(cls):
        if cls.test_dir.exists():
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        self.ecm_logic = ECMLogic()
        self.session = EnergyPlusSession(self.idf_path, self.epw_path, self.test_dir / "sim_out", mode_label="test_run")
        self.logger = MetricsLogger(self.test_dir / "logs")
        self.server = MCPServer(self.session, self.ecm_logic)
        self.agent = MCPClientAgent(self.server)

    def test_01_actuator_write_validation(self):
        """Verifies that out-of-bounds temperature requests are strictly rejected."""
        state = self.session.get_state()
        
        # 1. Valid cooling setpoint request (23.5°C)
        valid_call = {"name": "set_zone_setpoint", "params": {"zone_id": "ZONE1", "setpoint_type": "cooling", "value": 23.5}}
        is_valid, reason, updates = self.ecm_logic.validate_tool_call(valid_call, state)
        self.assertTrue(is_valid, f"Expected valid call to pass, got: {reason}")
        self.assertEqual(updates.get("zone1_cooling_sp"), 23.5)

        # 2. Out-of-bounds low cooling setpoint (17.0°C - violates comfort bounds)
        invalid_low = {"name": "set_zone_setpoint", "params": {"zone_id": "ZONE1", "setpoint_type": "cooling", "value": 17.0}}
        is_valid, reason, _ = self.ecm_logic.validate_tool_call(invalid_low, state)
        self.assertFalse(is_valid, "Expected out-of-bounds 17.0°C to be rejected!")
        self.assertIn("outside allowed bounds", reason)

        # 3. Out-of-bounds high cooling setpoint (30.0°C)
        invalid_high = {"name": "set_zone_setpoint", "params": {"zone_id": "ZONE1", "setpoint_type": "cooling", "value": 30.0}}
        is_valid, reason, _ = self.ecm_logic.validate_tool_call(invalid_high, state)
        self.assertFalse(is_valid, "Expected out-of-bounds 30.0°C to be rejected!")

    def test_02_malformed_tool_call_handling(self):
        """Verifies that malformed or incomplete JSON structures raise AgentDecisionError."""
        state = self.session.get_state()
        
        # 1. Missing numeric value
        malformed = [{"name": "set_zone_setpoint", "params": {"zone_id": "ZONE1", "setpoint_type": "cooling", "value": "INVALID_STR"}}]
        with self.assertRaises(AgentDecisionError):
            self.ecm_logic.validate_and_apply(malformed, self.session, state)
            
        # 2. Unknown tool name
        unknown_tool = [{"name": "hack_the_building", "params": {}}]
        with self.assertRaises(AgentDecisionError):
            self.ecm_logic.validate_and_apply(unknown_tool, self.session, state)

    def test_03_watchdog_failover_mechanism(self):
        """Verifies that 3 consecutive control cycle errors trigger watchdog failover to safe setpoints."""
        loop = ControlLoop(self.session, self.agent, self.ecm_logic, self.logger, control_interval_min=15, is_ai_run=True)
        
        # Set a temporary unsafe actuator value in session
        self.session.set_actuator("zone1_cooling_sp", 29.0)
        
        # Simulate 3 consecutive validation failures by throwing AgentDecisionError inside on_timestep
        # We mock agent.decide to return an out-of-bounds request continuously
        def mock_bad_decide(*args, **kwargs):
            return [{"name": "set_zone_setpoint", "params": {"zone_id": "ZONE1", "setpoint_type": "cooling", "value": 10.0}}]
        
        self.agent.decide = mock_bad_decide
        
        state = self.session.get_state()
        # Step 1: First failure (triggers retry, fails retry -> consecutive_failures = 2)
        state["sim_time"] = 15.0
        loop.on_timestep(state)
        self.assertEqual(loop._consecutive_failures, 2)
        
        # Step 2: Next control cycle failure -> consecutive_failures = 3 -> WATCHDOG TRIPS!
        state["sim_time"] = 30.0
        loop.on_timestep(state)
        self.assertGreaterEqual(loop._consecutive_failures, MAX_CONSECUTIVE_FAILURES)
        
        # Verify watchdog restored known safe setpoints in session active setpoints
        self.assertEqual(self.session.active_setpoints["zone1_cooling_sp"], DEFAULT_SAFE_SETPOINTS["zone1_cooling_sp"])

    def test_04_dual_mode_simulation_stepping(self):
        """Verifies that the dual-mode simulation engine advances time and updates cumulative kWh cleanly."""
        start_time = self.session.sim_time_min
        start_kwh = self.session.state_cache["cumulative_kwh"]
        
        success = self.session.step()
        self.assertTrue(success, "Simulation step should succeed")
        self.assertGreater(self.session.sim_time_min, start_time)
        self.assertGreaterEqual(self.session.state_cache["cumulative_kwh"], start_kwh)

if __name__ == "__main__":
    unittest.main()
