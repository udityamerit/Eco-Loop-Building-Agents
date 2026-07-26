"""
Unit Tests for Upgraded Cloud-Native, Semantic Memory, and Hybrid ML Forecasting components.
Verifies Firebase offline persistence, ChromaDB/MMR memory retrieval, and classical ML GridSearch forecasting.
"""
import unittest
import shutil
import tempfile
from pathlib import Path
from src.firebase_client import FirebaseClient
from src.memory_engine import SemanticMemoryEngine
from src.ml_forecaster import MLForecaster
from src.mcp_server import MCPServer
from src.ecm_logic import ECMLogic

class TestUpgradedEngine(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        
    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_firebase_client_fallback_persistence(self):
        """Verifies Firebase client falls back to local JSON persistence cleanly when offline."""
        fb = FirebaseClient(db_url="https://mock-unconfigured-db.firebaseio.com")
        self.assertFalse(fb.is_cloud_active)
        
        # Override fallback file paths to temporary directory
        fb.local_metrics_file = self.test_dir / "test_fb_metrics.json"
        fb.local_decisions_file = self.test_dir / "test_fb_decisions.json"
        
        fb.push_metric(15.0, "2026-07-15 00:15:00", 1.2, 1.2, 23.5, 0.1, 310.0, 80.0)
        fb.push_decision(15.0, "2026-07-15 00:15:00", "set_zone_setpoint", {"zone_id": "ZONE1", "value": 23.5}, "High carbon peak.", "ACCEPTED")
        
        recent_metrics = fb.fetch_recent_metrics(limit=10)
        recent_decisions = fb.fetch_recent_decisions(limit=10)
        
        self.assertEqual(len(recent_metrics), 1)
        self.assertEqual(recent_metrics[0]["zone1_temp"], 23.5)
        self.assertEqual(len(recent_decisions), 1)
        self.assertEqual(recent_decisions[0]["tool_called"], "set_zone_setpoint")

    def test_02_semantic_memory_mmr_retrieval(self):
        """Verifies SemanticMemoryEngine stores experiences and retrieves via Maximal Marginal Relevance (MMR)."""
        db_path = str(self.test_dir / "chroma_test")
        mem = SemanticMemoryEngine(db_path=db_path, collection_name="test_memory")
        
        # Store custom test memory
        mem.store_memory(
            {"zone1_temp": 24.8, "zone1_pmv": 0.4, "grid_carbon_gco2_kwh": 480.0, "occupancy_pct": 50.0},
            {"name": "set_zone_setpoint", "params": {"zone_id": "ZONE1", "setpoint_type": "cooling", "value": 23.5}},
            "Shedding peak carbon load while managing upper comfort boundary."
        )
        
        # Query memory using MMR
        results = mem.retrieve_mmr(
            {"zone1_temp": 24.7, "zone1_pmv": 0.38, "grid_carbon_gco2_kwh": 475.0, "occupancy_pct": 50.0},
            top_k=2,
            lambda_param=0.65
        )
        
        self.assertGreaterEqual(len(results), 1)
        self.assertIn("recommended_action", results[0])
        self.assertIn("rationale", results[0])

    def test_03_ml_forecaster_predictions(self):
        """Verifies MLForecaster initializes, evaluates models, and generates next-step forecasts."""
        forecaster = MLForecaster(models_dir=self.test_dir / "ml_models")
        
        state = {
            "sim_time": 60.0,
            "zone1_temp": 24.1,
            "zone1_pmv": 0.25,
            "interval_kwh": 1.5,
            "occupancy_pct": 80.0,
            "grid_carbon_gco2_kwh": 350.0
        }
        
        forecast = forecaster.predict_next(state)
        self.assertIn("predicted_temp_next_step", forecast)
        self.assertIn("predicted_grid_carbon_next_step", forecast)
        self.assertIn("thermal_violation_risk_prob", forecast)
        self.assertIn("ml_model_used", forecast)
        self.assertIsInstance(forecast["predicted_temp_next_step"], float)

    def test_04_mcp_server_ml_injection(self):
        """Verifies MCPServer injects ML predictions into get_building_state payload."""
        class MockSession:
            def get_state(self):
                return {"sim_time": 15.0, "zone1_temp": 23.0, "zone1_pmv": 0.0, "grid_carbon_gco2_kwh": 300.0}
                
        ecm = ECMLogic()
        server = MCPServer(MockSession(), ecm)
        
        res = server.execute_tool("get_building_state", {})
        self.assertEqual(res["status"], "success")
        self.assertIn("data", res)
        self.assertIn("ml_predictive_forecast", res["data"])
        self.assertIn("predicted_temp_next_step", res["data"]["ml_predictive_forecast"])

if __name__ == "__main__":
    unittest.main()
