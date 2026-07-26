"""
Firebase Real-Time State Synchronization Client for Eco-Loop Building Agents.
Handles live streaming of simulation metrics (kWh, PMV, zone temperatures) and decision audit logs.
Includes automatic local fallback persistence when offline or running in standalone verification mode.
"""
import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

try:
    import firebase_admin
    from firebase_admin import credentials, db
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False

logger = logging.getLogger("FirebaseRealtimeClient")
logger.setLevel(logging.INFO)

class FirebaseClient:
    """
    Client for syncing real-time building state and agent decision logs to Firebase Realtime Database.
    Gracefully falls back to local JSON/CSV persistence when offline.
    """
    def __init__(self, db_url: Optional[str] = None, cred_path: Optional[str] = None):
        self.db_url = db_url or os.getenv("FIREBASE_DATABASE_URL")
        self.cred_path = cred_path or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        self.is_cloud_active = False
        self.local_fallback_dir = Path(__file__).resolve().parent.parent / "logs" / "firebase_fallback"
        self.local_fallback_dir.mkdir(parents=True, exist_ok=True)
        self.local_metrics_file = self.local_fallback_dir / "live_metrics.json"
        self.local_decisions_file = self.local_fallback_dir / "live_decisions.json"
        
        self._init_firebase()

    def _init_firebase(self):
        """Initializes Firebase Admin SDK if available and configured with real credentials."""
        is_mock_url = self.db_url and any(k in str(self.db_url).lower() for k in ["mock", "unconfigured", "test", "example"])
        
        if FIREBASE_AVAILABLE and self.db_url and not is_mock_url:
            try:
                has_valid_creds = False
                if self.cred_path and os.path.exists(self.cred_path):
                    has_valid_creds = True
                elif os.getenv("GOOGLE_APPLICATION_CREDENTIALS") and os.path.exists(os.getenv("GOOGLE_APPLICATION_CREDENTIALS")):
                    has_valid_creds = True
                    
                if has_valid_creds:
                    if not firebase_admin._apps:
                        if self.cred_path and os.path.exists(self.cred_path):
                            cred = credentials.Certificate(self.cred_path)
                            firebase_admin.initialize_app(cred, {"databaseURL": self.db_url})
                        else:
                            firebase_admin.initialize_app(options={"databaseURL": self.db_url})
                    self.is_cloud_active = True
                    logger.info(f"Connected to live cloud Firebase Realtime Database at {self.db_url}")
                else:
                    logger.info("No valid Google/Firebase service account credentials found. Using local real-time persistence emulation.")
                    self.is_cloud_active = False
            except Exception as e:
                logger.warning(f"Could not initialize cloud Firebase ({e}). Engaging offline fallback persistence.")
                self.is_cloud_active = False
        else:
            logger.info("Firebase Admin SDK or DB URL unconfigured (or mock URL). Using local real-time persistence emulation.")
            self.is_cloud_active = False

    def push_metric(self, sim_time_min: float, timestamp_str: str, interval_kwh: float, cum_kwh: float, zone1_temp: float, zone1_pmv: float, grid_carbon: float, occupancy: float):
        """Pushes an interval simulation metric payload to real-time storage."""
        payload = {
            "sim_time_min": sim_time_min,
            "timestamp": timestamp_str,
            "interval_kwh": interval_kwh,
            "cumulative_kwh": cum_kwh,
            "zone1_temp": zone1_temp,
            "zone1_pmv": zone1_pmv,
            "grid_carbon_gco2_kwh": grid_carbon,
            "occupancy_pct": occupancy,
            "updated_at": datetime.utcnow().isoformat()
        }
        
        if self.is_cloud_active:
            try:
                ref = db.reference("ecoloop_realtime/metrics")
                ref.push(payload)
                return True
            except Exception as e:
                logger.warning(f"Cloud push failed ({e}). Saving metric locally.")
                
        # Local fallback persistence
        self._append_local_json(self.local_metrics_file, payload)
        return True

    def push_decision(self, sim_time_min: float, timestamp_str: str, tool_called: str, params: Dict[str, Any], rationale: str, status: str):
        """Pushes an auditable MCP tool decision log to real-time storage."""
        payload = {
            "sim_time_min": sim_time_min,
            "timestamp": timestamp_str,
            "tool_called": tool_called,
            "params": params if isinstance(params, dict) else str(params),
            "rationale": rationale,
            "status": status,
            "updated_at": datetime.utcnow().isoformat()
        }
        
        if self.is_cloud_active:
            try:
                ref = db.reference("ecoloop_realtime/decisions")
                ref.push(payload)
                return True
            except Exception as e:
                logger.warning(f"Cloud decision push failed ({e}). Saving decision locally.")
                
        self._append_local_json(self.local_decisions_file, payload)
        return True

    def fetch_recent_metrics(self, limit: int = 144) -> List[Dict[str, Any]]:
        """Retrieves recent real-time simulation metrics for dashboard streaming."""
        if self.is_cloud_active:
            try:
                ref = db.reference("ecoloop_realtime/metrics")
                snapshot = ref.order_by_child("sim_time_min").limit_to_last(limit).get()
                if snapshot:
                    return list(snapshot.values()) if isinstance(snapshot, dict) else snapshot
            except Exception as e:
                logger.warning(f"Cloud fetch failed ({e}). Reading local persistence.")
                
        return self._read_local_json(self.local_metrics_file, limit)

    def fetch_recent_decisions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves recent auditable MCP decision logs for dashboard streaming."""
        if self.is_cloud_active:
            try:
                ref = db.reference("ecoloop_realtime/decisions")
                snapshot = ref.order_by_child("sim_time_min").limit_to_last(limit).get()
                if snapshot:
                    return list(snapshot.values()) if isinstance(snapshot, dict) else snapshot
            except Exception as e:
                logger.warning(f"Cloud decision fetch failed ({e}). Reading local persistence.")
                
        return self._read_local_json(self.local_decisions_file, limit)

    def _append_local_json(self, file_path: Path, item: Dict[str, Any]):
        """Appends an item to a local fallback JSON file."""
        data = self._read_local_json(file_path, limit=10000)
        data.append(item)
        with open(file_path, mode="w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _read_local_json(self, file_path: Path, limit: int = 100) -> List[Dict[str, Any]]:
        """Reads recent items from local fallback JSON file."""
        if not file_path.exists():
            return []
        try:
            with open(file_path, mode="r", encoding="utf-8") as f:
                data = json.load(f)
                return data[-limit:] if isinstance(data, list) else []
        except Exception:
            return []
