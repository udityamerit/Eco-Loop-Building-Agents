"""
Eco-Loop Building Agents — Digital Twin Command Center
Main Entrypoint Script for executing the 3-Day Baseline & AI-Driven Simulation Pipeline.
"""
import sys
import logging
from pathlib import Path

# Add workspace root to Python path
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.control_loop import run_evaluation_pipeline

if __name__ == "__main__":
    print("=====================================================================")
    print(" Eco-Loop Building Agents -- Autonomous Simulation Pipeline ")
    print("=====================================================================")
    print("Executing 3-Day Baseline and Cloud-Native AI-Driven Closed-Loop Control...")
    
    results = run_evaluation_pipeline()
    
    print("\n[SUCCESS] Simulation Pipeline Execution Complete!")
    print(f"   Baseline Demand : {results.get('baseline_kwh', 0):,.2f} kWh")
    print(f"   AI Control Demand: {results.get('ai_kwh', 0):,.2f} kWh")
    print(f"   Energy Reduction : {results.get('pct_reduction', 0):.2f}%\n")
    print("-> To view the interactive dashboard, run: streamlit run dashboard/app.py")
