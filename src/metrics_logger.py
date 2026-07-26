import csv
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    from src.firebase_client import FirebaseClient
except ImportError:
    FirebaseClient = None

class MetricsLogger:
    """
    Handles logging of timestep simulation metrics and agent decision audit trails.
    Writes structured CSV datasets and synchronizes in real time with Firebase Cloud/Local storage.
    """
    def __init__(self, output_dir: Path, start_datetime: Optional[datetime] = None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.metrics_file = self.output_dir / "metrics.csv"
        self.decisions_file = self.output_dir / "decisions.csv"
        self.error_file = self.output_dir / "errors.log"
        
        self.start_datetime = start_datetime or datetime(2026, 7, 15, 0, 0, 0)
        
        self._init_files()
        self.logger = logging.getLogger(f"MetricsLogger_{output_dir.name}")
        if not self.logger.handlers:
            handler = logging.FileHandler(self.error_file)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
            
        # Initialize real-time Firebase sync client
        self.firebase = FirebaseClient() if FirebaseClient else None

    def _init_files(self):
        # Initialize metrics CSV with headers
        with open(self.metrics_file, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp",
                "sim_time_min",
                "zone1_temp",
                "zone1_pmv",
                "interval_kwh",
                "cumulative_kwh",
                "occupancy_pct",
                "grid_carbon_gco2_kwh"
            ])
            
        # Initialize decisions CSV with headers
        with open(self.decisions_file, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp",
                "sim_time_min",
                "tool_called",
                "params",
                "rationale",
                "status"
            ])

    def _sim_time_to_dt(self, sim_time_min: float) -> str:
        current_dt = self.start_datetime + timedelta(minutes=float(sim_time_min))
        return current_dt.strftime("%Y-%m-%d %H:%M:%S")

    def log_metric(self, sim_time_min: float, state: Dict[str, Any]):
        """Logs a single timestep building state reading into metrics.csv and Firebase storage."""
        timestamp = self._sim_time_to_dt(sim_time_min)
        z_temp = round(state.get("zone1_temp", 0.0), 3)
        z_pmv = round(state.get("zone1_pmv", 0.0), 3)
        i_kwh = round(state.get("interval_kwh", 0.0), 4)
        c_kwh = round(state.get("cumulative_kwh", 0.0), 4)
        occ = round(state.get("occupancy_pct", 0.0), 1)
        carb = round(state.get("grid_carbon_gco2_kwh", 0.0), 1)
        
        with open(self.metrics_file, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                timestamp,
                round(sim_time_min, 2),
                z_temp,
                z_pmv,
                i_kwh,
                c_kwh,
                occ,
                carb
            ])
            
        if self.firebase:
            try:
                self.firebase.push_metric(sim_time_min, timestamp, i_kwh, c_kwh, z_temp, z_pmv, carb, occ)
            except Exception as e:
                self.logger.debug(f"Firebase metric sync skipped: {e}")

    def log_decision(
        self,
        sim_time_min: float,
        tool_called: str,
        params: Dict[str, Any],
        rationale: str,
        status: str = "ACCEPTED"
    ):
        """Logs an agent tool invocation and its rationale into decisions.csv and Firebase storage."""
        timestamp = self._sim_time_to_dt(sim_time_min)
        params_str = json.dumps(params)
        with open(self.decisions_file, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                timestamp,
                round(sim_time_min, 2),
                tool_called,
                params_str,
                rationale,
                status
            ])
            
        if self.firebase:
            try:
                self.firebase.push_decision(sim_time_min, timestamp, tool_called, params, rationale, status)
            except Exception as e:
                self.logger.debug(f"Firebase decision sync skipped: {e}")

    def log_error(self, sim_time_min: float, error_msg: str):
        """Logs exceptions and validation failures."""
        timestamp = self._sim_time_to_dt(sim_time_min)
        self.logger.error(f"[SimTime: {sim_time_min:.1f}m | {timestamp}] {error_msg}")
