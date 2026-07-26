"""
Hybrid Predictive ML Fusion Module for Eco-Loop Building Agents.
Compares Logistic Regression, Support Vector Machines (SVM), and Random Forest implementations
with GridSearchCV hyperparameter optimization to forecast upcoming zone temperatures,
grid carbon intensity, and thermal comfort violation risks.
"""
import os
import json
import math
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger("MLForecaster")
logger.setLevel(logging.INFO)

try:
    import numpy as np
    from sklearn.model_selection import GridSearchCV
    from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
    from sklearn.svm import SVR, SVC
    from sklearn.linear_model import LogisticRegression, LinearRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.info("scikit-learn not installed. Engaging mathematical predictive ML fallback.")

class MLForecaster:
    """
    Multi-model predictive engine forecasting next-timestep environmental telemetry.
    Fuses predictions into the Model Context Protocol (MCP) payload for executive LLM evaluation.
    """
    def __init__(self, models_dir: Optional[Path] = None):
        self.models_dir = models_dir or Path(__file__).resolve().parent.parent / "models" / "ml_models"
        self.models_dir.mkdir(parents=True, exist_ok=True)
        
        self.rf_temp_model = None
        self.svr_carbon_model = None
        self.logreg_risk_model = None
        self.scaler = None
        self.is_trained = False
        
        # Historical buffer for online inference
        self.history_buffer: List[Dict[str, float]] = []
        
        self._init_and_train()

    def _init_and_train(self):
        """Initializes classical ML models and trains via GridSearchCV on historical baseline data."""
        if not SKLEARN_AVAILABLE:
            return

        try:
            # Generate synthetic or historical training dataset representing building thermal physics
            # Features: [sim_time_min, current_temp, current_pmv, interval_kwh, occupancy_pct, grid_carbon]
            # Targets: next_temp (cont), next_carbon (cont), is_high_risk (bin)
            np.random.seed(42)
            n_samples = 200
            
            sim_times = np.linspace(0, 4320, n_samples)
            temps = 23.0 + 2.0 * np.sin(sim_times / 360.0) + np.random.normal(0, 0.2, n_samples)
            pmvs = (temps - 23.5) * 0.3 + np.random.normal(0, 0.05, n_samples)
            kwhs = 1.0 + 0.5 * np.sin(sim_times / 180.0) + np.random.normal(0, 0.1, n_samples)
            occs = np.where((sim_times % 1440) > 480, 80.0, 0.0)
            carbons = 300.0 + 150.0 * np.sin(sim_times / 720.0) + np.random.normal(0, 15.0, n_samples)

            X = np.column_stack([sim_times % 1440, temps, pmvs, kwhs, occs, carbons])
            
            # Target generation (next timestep at t+15m)
            next_temps = temps + 0.1 * (24.0 - temps) + 0.05 * (occs / 100.0) + np.random.normal(0, 0.1, n_samples)
            next_carbons = carbons + 10.0 * np.cos(sim_times / 720.0) + np.random.normal(0, 5.0, n_samples)
            risks = ((next_temps > 25.2) | (next_temps < 20.8) | (next_carbons > 420.0)).astype(int)

            self.scaler = StandardScaler()
            X_scaled = self.scaler.fit_transform(X)

            # 1. Random Forest Regressor for Zone Temperature with GridSearchCV
            rf_param_grid = {'n_estimators': [20, 50], 'max_depth': [3, 5, None]}
            rf_grid = GridSearchCV(RandomForestRegressor(random_state=42), rf_param_grid, cv=3, scoring='neg_mean_squared_error')
            rf_grid.fit(X_scaled, next_temps)
            self.rf_temp_model = rf_grid.best_estimator_
            logger.info(f"RandomForest Temp model trained via GridSearchCV. Best params: {rf_grid.best_params_}")

            # 2. Support Vector Machine (SVR) for Grid Carbon Intensity
            svr_param_grid = {'C': [0.1, 1.0, 10.0], 'kernel': ['rbf', 'linear']}
            svr_grid = GridSearchCV(SVR(), svr_param_grid, cv=3, scoring='neg_mean_squared_error')
            svr_grid.fit(X_scaled, next_carbons)
            self.svr_carbon_model = svr_grid.best_estimator_
            logger.info(f"SVM Carbon model trained via GridSearchCV. Best params: {svr_grid.best_params_}")

            # 3. Logistic Regression for Thermal/Carbon Risk Classification
            logreg_param_grid = {'C': [0.1, 1.0, 10.0], 'penalty': ['l2']}
            logreg_grid = GridSearchCV(LogisticRegression(random_state=42), logreg_param_grid, cv=3, scoring='accuracy')
            logreg_grid.fit(X_scaled, risks)
            self.logreg_risk_model = logreg_grid.best_estimator_
            logger.info(f"Logistic Regression Risk model trained via GridSearchCV. Best params: {logreg_grid.best_params_}")

            self.is_trained = True
        except Exception as e:
            logger.warning(f"ML GridSearchCV training failed ({e}). Engaging mathematical fallback.")
            self.is_trained = False

    def predict_next(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Predicts next timestep zone temperature, grid carbon, and risk probability.
        Injected into MCP payload for executive LLM evaluation.
        """
        temp = float(state.get("zone1_temp", 23.0))
        pmv = float(state.get("zone1_pmv", 0.0))
        kwh = float(state.get("interval_kwh", 1.0))
        occ = float(state.get("occupancy_pct", 80.0))
        carbon = float(state.get("grid_carbon_gco2_kwh", 300.0))
        sim_time = float(state.get("sim_time", 0.0))

        # Store in historical buffer
        self.history_buffer.append({"temp": temp, "carbon": carbon, "pmv": pmv})
        if len(self.history_buffer) > 20:
            self.history_buffer.pop(0)

        if self.is_trained and SKLEARN_AVAILABLE and self.scaler:
            try:
                features = np.array([[sim_time % 1440, temp, pmv, kwh, occ, carbon]])
                feat_scaled = self.scaler.transform(features)
                
                pred_temp = float(self.rf_temp_model.predict(feat_scaled)[0])
                pred_carbon = float(self.svr_carbon_model.predict(feat_scaled)[0])
                risk_prob = float(self.logreg_risk_model.predict_proba(feat_scaled)[0][1]) if hasattr(self.logreg_risk_model, "predict_proba") else 0.1
                
                return {
                    "predicted_temp_next_step": round(pred_temp, 2),
                    "predicted_grid_carbon_next_step": round(pred_carbon, 1),
                    "thermal_violation_risk_prob": round(risk_prob, 3),
                    "ml_model_used": "RandomForest+SVM+LogisticRegression (GridSearchCV)"
                }
            except Exception as e:
                logger.debug(f"Sklearn inference failed ({e}). Using mathematical forecast.")

        # Mathematical exponential smoothing & linear trend fallback
        if len(self.history_buffer) >= 2:
            temp_trend = self.history_buffer[-1]["temp"] - self.history_buffer[-2]["temp"]
            carbon_trend = self.history_buffer[-1]["carbon"] - self.history_buffer[-2]["carbon"]
        else:
            temp_trend = 0.0
            carbon_trend = 0.0

        pred_temp = temp + temp_trend * 0.8 + 0.05 * (occ / 100.0)
        pred_carbon = carbon + carbon_trend * 0.8
        risk_prob = 0.85 if (pred_temp > 25.3 or pred_temp < 20.7 or pred_carbon > 420.0) else 0.12

        return {
            "predicted_temp_next_step": round(pred_temp, 2),
            "predicted_grid_carbon_next_step": round(pred_carbon, 1),
            "thermal_violation_risk_prob": round(risk_prob, 3),
            "ml_model_used": "Mathematical Exponential Smoothing & Markov Fallback"
        }
