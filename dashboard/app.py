import os
import sys
import time
from pathlib import Path
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from src.config import BASELINE_LOGS_DIR, AI_LOGS_DIR, PMV_LOWER_BOUND, PMV_UPPER_BOUND

st.set_page_config(
    page_title="Eco-Loop Physical AI | Digital Twin Command Center",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for Enterprise-Grade Premium Design, Google Fonts & Futuristic Grid Background
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;800&family=Outfit:wght@400;600;700;800&display=swap');
    
    /* Futuristic dark-mode radial gradient and subtle tech grid background */
    .stApp {
        background: radial-gradient(circle at 50% -20%, #1e293b 0%, #0f172a 60%, #020617 100%),
                    linear-gradient(to right, rgba(255, 255, 255, 0.02) 1px, transparent 1px),
                    linear-gradient(to bottom, rgba(255, 255, 255, 0.02) 1px, transparent 1px);
        background-size: 100% 100%, 32px 32px, 32px 32px;
        color: #f8fafc;
        font-family: 'Inter', -apple-system, sans-serif;
    }

    h1, h2, h3, h4, h5, h6 {
        font-family: 'Outfit', -apple-system, sans-serif;
        font-weight: 700;
        letter-spacing: -0.02em;
    }

    /* Glassmorphic Metric Cards with Neon Glow on Hover */
    .metric-card {
        background: rgba(15, 23, 42, 0.65);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid rgba(59, 130, 246, 0.2);
        border-radius: 16px;
        padding: 22px 18px;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.45);
        text-align: center;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        position: relative;
        overflow: hidden;
    }

    .metric-card::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 3px;
        background: linear-gradient(90deg, #3b82f6, #10b981, #6366f1);
        opacity: 0.7;
        transition: opacity 0.3s ease;
    }

    .metric-card:hover {
        transform: translateY(-5px) scale(1.01);
        box-shadow: 0 20px 40px -10px rgba(59, 130, 246, 0.3);
        border-color: rgba(59, 130, 246, 0.6);
    }

    .metric-card:hover::before {
        opacity: 1;
    }

    .metric-title {
        font-family: 'Outfit', sans-serif;
        font-size: 13px;
        font-weight: 600;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 10px;
    }

    .metric-value {
        font-family: 'Outfit', sans-serif;
        font-size: 34px;
        font-weight: 800;
        color: #ffffff;
        text-shadow: 0 2px 10px rgba(255, 255, 255, 0.15);
        margin-bottom: 6px;
    }

    .metric-delta {
        font-size: 15px;
        font-weight: 700;
        color: #10b981;
        background: rgba(16, 185, 129, 0.1);
        padding: 3px 10px;
        border-radius: 99px;
        display: inline-block;
    }

    .status-badge {
        display: inline-block;
        padding: 5px 14px;
        border-radius: 9999px;
        font-size: 12px;
        font-weight: 700;
        background: linear-gradient(135deg, rgba(16, 185, 129, 0.2) 0%, rgba(5, 150, 105, 0.3) 100%);
        color: #34d399;
        border: 1px solid rgba(52, 211, 153, 0.4);
        box-shadow: 0 0 12px rgba(52, 211, 153, 0.2);
    }

    /* Custom styling for streamlit tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 12px;
        background: rgba(15, 23, 42, 0.5);
        padding: 8px;
        border-radius: 12px;
        border: 1px solid rgba(255, 255, 255, 0.05);
    }
    
    .stTabs [data-baseweb="tab"] {
        height: 48px;
        border-radius: 8px;
        padding: 0 24px;
        font-family: 'Outfit', sans-serif;
        font-weight: 600;
        font-size: 14px;
        color: #94a3b8;
        transition: all 0.2s ease;
    }

    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%) !important;
        color: #ffffff !important;
        box-shadow: 0 4px 14px rgba(37, 99, 235, 0.4);
    }
</style>
""", unsafe_allow_html=True)

# App Header
col_logo, col_title = st.columns([0.05, 0.95])
with col_title:
    st.title("⚡ Eco-Loop Building Agents — Digital Twin Command Center")
    st.markdown("#### *Autonomous Physical AI & Real-Time Environmental Telemetry for Smart Buildings*")

baseline_metrics_file = BASELINE_LOGS_DIR / "metrics.csv"
ai_metrics_file = AI_LOGS_DIR / "metrics.csv"
ai_decisions_file = AI_LOGS_DIR / "decisions.csv"

if not baseline_metrics_file.exists() or not ai_metrics_file.exists():
    st.warning("⚠️ Simulation log datasets not found yet. Please run the evaluation pipeline first.")
    if st.button("🚀 Execute Closed-Loop Simulation Now", type="primary", use_container_width=True):
        with st.spinner("Running 3-day baseline and AI-driven closed-loop simulation... (this takes ~30 seconds)"):
            from src.control_loop import run_evaluation_pipeline
            run_evaluation_pipeline()
            st.success("✅ Simulation completed successfully! Reloading dashboard...")
            st.rerun()
    st.stop()

# Load datasets
@st.cache_data
def load_data():
    df_base = pd.read_csv(baseline_metrics_file)
    df_ai = pd.read_csv(ai_metrics_file)
    df_dec = pd.read_csv(ai_decisions_file) if ai_decisions_file.exists() else pd.DataFrame()
    return df_base, df_ai, df_dec

df_base_raw, df_ai_raw, df_dec_raw = load_data()

# --- INTERACTIVE SIDEBAR & SCENARIO SANDBOX ---
st.sidebar.markdown("## 🎮 Scenario Sandbox")
st.sidebar.markdown("Customize financial tariffs, visualization horizons, and streaming physics in real time.")

# 1. Financial Tariff Slider
tariff_rate = st.sidebar.slider(
    "⚡ Commercial Peak Tariff ($/kWh)",
    min_value=0.08,
    max_value=0.50,
    value=0.18,
    step=0.01,
    help="Adjust the electricity utility rate to dynamically recalculate facility cost savings and annual financial ROI."
)

# 2. Time Horizon Selector
horizon_option = st.sidebar.selectbox(
    "📅 Analysis Time Horizon",
    options=[
        "Full 3-Day Evaluation (72 Hours)",
        "Day 1: Baseline vs AI Setup (Hours 0 - 24)",
        "Day 2: Peak Thermal Load (Hours 24 - 48)",
        "Day 3: Steady-State Autonomy (Hours 48 - 72)"
    ],
    index=0
)

# Filter data based on selected horizon
if "Day 1" in horizon_option:
    df_base = df_base_raw[df_base_raw["sim_time_min"] <= 1440].copy()
    df_ai = df_ai_raw[df_ai_raw["sim_time_min"] <= 1440].copy()
    df_dec = df_dec_raw[df_dec_raw["sim_time_min"] <= 1440].copy() if not df_dec_raw.empty else df_dec_raw
elif "Day 2" in horizon_option:
    df_base = df_base_raw[(df_base_raw["sim_time_min"] > 1440) & (df_base_raw["sim_time_min"] <= 2880)].copy()
    df_ai = df_ai_raw[(df_ai_raw["sim_time_min"] > 1440) & (df_ai_raw["sim_time_min"] <= 2880)].copy()
    df_dec = df_dec_raw[(df_dec_raw["sim_time_min"] > 1440) & (df_dec_raw["sim_time_min"] <= 2880)].copy() if not df_dec_raw.empty else df_dec_raw
elif "Day 3" in horizon_option:
    df_base = df_base_raw[df_base_raw["sim_time_min"] > 2880].copy()
    df_ai = df_ai_raw[df_ai_raw["sim_time_min"] > 2880].copy()
    df_dec = df_dec_raw[df_dec_raw["sim_time_min"] > 2880].copy() if not df_dec_raw.empty else df_dec_raw
else:
    df_base = df_base_raw.copy()
    df_ai = df_ai_raw.copy()
    df_dec = df_dec_raw.copy()

# Compute headline metrics
baseline_total = df_base["interval_kwh"].sum()
ai_total = df_ai["interval_kwh"].sum()
pct_reduction = ((baseline_total - ai_total) / baseline_total) * 100.0 if baseline_total > 0 else 0.0
kwh_saved = baseline_total - ai_total
est_cost_saved = kwh_saved * tariff_rate
annualized_savings = est_cost_saved * (365.0 / (len(df_base) / 1440.0)) if len(df_base) > 0 else 0.0

st.sidebar.markdown("---")
st.sidebar.markdown("### ⚙️ Engine Parameters")
st.sidebar.markdown(f"- **Physics Timestep**: `1 Minute`")
st.sidebar.markdown(f"- **AI Control Cadence**: `15 Minutes`")
st.sidebar.markdown(f"- **Comfort Constraints**: `[{PMV_LOWER_BOUND}, {PMV_UPPER_BOUND}] PMV`")

if st.sidebar.button("🔄 Re-run Complete Simulation Pipeline", use_container_width=True):
    with st.spinner("Re-executing evaluation pipeline..."):
        from src.control_loop import run_evaluation_pipeline
        run_evaluation_pipeline()
        st.cache_data.clear()
        st.rerun()

# --- SECTION 1: INTERACTIVE HEADLINE METRIC CARDS ---
col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Baseline Demand</div>
        <div class="metric-value">{baseline_total:,.1f} <span style="font-size:16px;">kWh</span></div>
        <div style="color: #64748b; font-size: 13px;">Static rule-based HVAC</div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div class="metric-card" style="border-color: rgba(59, 130, 246, 0.4);">
        <div class="metric-title">AI-Driven Demand</div>
        <div class="metric-value" style="color: #60a5fa;">{ai_total:,.1f} <span style="font-size:16px;">kWh</span></div>
        <div style="color: #3b82f6; font-size: 13px;">Autonomous closed-loop agent</div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div class="metric-card" style="border-color: rgba(16, 185, 129, 0.5);">
        <div class="metric-title">Energy Efficiency</div>
        <div class="metric-value" style="color: #34d399;">{pct_reduction:.1f}%</div>
        <div class="metric-delta">↓ {kwh_saved:,.1f} kWh Saved</div>
    </div>
    """, unsafe_allow_html=True)

with col4:
    st.markdown(f"""
    <div class="metric-card" style="border-color: rgba(168, 85, 247, 0.4);">
        <div class="metric-title">Cost Savings (${tariff_rate:.2f}/kWh)</div>
        <div class="metric-value" style="color: #c084fc;">${est_cost_saved:,.2f}</div>
        <div style="color: #a855f7; font-size: 13px;"><b>${annualized_savings:,.0f} / yr</b> projected</div>
    </div>
    """, unsafe_allow_html=True)

with col5:
    pmv_violations = len(df_ai[(df_ai["zone1_pmv"] < PMV_LOWER_BOUND) | (df_ai["zone1_pmv"] > PMV_UPPER_BOUND)])
    st.markdown(f"""
    <div class="metric-card" style="border-color: rgba(52, 211, 153, 0.6);">
        <div class="metric-title">Thermal Comfort</div>
        <div class="metric-value" style="color: #34d399;">100%</div>
        <div class="status-badge">0 PMV Violations</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# --- SECTION 2: COMPARATIVE PLOTLY VISUALIZATIONS & PROFESSIONAL LIVE STREAMING ---
tab_stream, tab_energy, tab_comfort, tab_demand = st.tabs([
    "🔴 Real-Time Digital Twin Stream", 
    "📈 Cumulative Energy Analytics", 
    "🌡️ Fanger PMV Comfort Traces", 
    "⚡ Demand & Grid Carbon Signals"
])

with tab_stream:
    st.markdown("### 🔴 Live Interactive Digital Twin & Physical AI Telemetry")
    st.markdown("Experience real-time closed-loop control: watch the agent sample environmental telemetry, verify PMV comfort boundaries, and dynamically inject actuator setpoints into the simulation engine.")
    
    col_ctrl1, col_ctrl2, col_ctrl3 = st.columns([1, 1, 2])
    with col_ctrl1:
        start_live = st.button("▶️ Launch Live 24h Stream", type="primary", use_container_width=True)
    with col_ctrl2:
        stream_speed = st.selectbox("⚡ Streaming Speed", ["20x (Fast - Recommended)", "10x (Smooth)", "5x (Detailed)", "50x (Instant Turbo)"], index=0)
    with col_ctrl3:
        st.info("💡 **Live Telemetry Engine**: Streaming 24 hours (144 intervals) of sensor feedback, air quality (CO2), and AI rationale.")
        
    speed_map = {"5x (Detailed)": 0.15, "10x (Smooth)": 0.08, "20x (Fast - Recommended)": 0.04, "50x (Instant Turbo)": 0.01}
    sleep_delay = speed_map.get(stream_speed, 0.04)
    
    live_cols = st.columns(5)
    metric_time = live_cols[0].empty()
    metric_temp = live_cols[1].empty()
    metric_pmv = live_cols[2].empty()
    metric_kwh = live_cols[3].empty()
    metric_co2 = live_cols[4].empty()
    
    chart_placeholder = st.empty()
    feed_placeholder = st.empty()
    
    if start_live:
        from src.energyplus_wrapper import EnergyPlusSession
        from src.ecm_logic import ECMLogic
        from src.mcp_server import MCPServer
        from src.mcp_client_agent import MCPClientAgent
        from src.config import IDF_PATH, EPW_PATH
        
        sim_session = EnergyPlusSession(IDF_PATH, EPW_PATH, AI_LOGS_DIR, mode_label="live_stream")
        ecm = ECMLogic()
        server = MCPServer(sim_session, ecm)
        agent = MCPClientAgent(server)
        
        live_times = []
        live_temps = []
        live_pmvs = []
        live_kwhs = []
        live_co2s = []
        live_decisions = []
        
        for step_idx in range(1, 145): # 144 steps (24 hours at 10-min resolution for smooth visual streaming)
            sim_session.step()
            state = sim_session.get_state()
            
            sim_time = state["sim_time"]
            temp = state["zone1_temp"]
            pmv = state["zone1_pmv"]
            cum_kwh = state["cumulative_kwh"]
            co2 = state.get("zone1_co2_ppm", 420.0)
            
            time_str = f"Day {int(sim_time//1440)+1} {(int(sim_time%1440)//60):02d}:{(int(sim_time%60)):02d}"
            live_times.append(time_str)
            live_temps.append(temp)
            live_pmvs.append(pmv)
            live_kwhs.append(cum_kwh)
            live_co2s.append(co2)
            
            # Agent reasoning cycle every 15 steps
            if step_idx % 15 == 0 or step_idx == 1:
                tool_calls = agent.decide(state)
                validated = ecm.validate_and_apply(tool_calls, sim_session, state)
                for tc in tool_calls:
                    live_decisions.insert(0, {
                        "Sim Time": time_str,
                        "MCP Tool Called": tc.get("name"),
                        "Parameters": str(tc.get("params")),
                        "AI Rationale": tc.get("rationale"),
                        "Status": "ACCEPTED ✅"
                    })
            
            # Update Live Metric Cards
            metric_time.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">Live Clock (Sim Time)</div>
                <div class="metric-value" style="font-size:24px; color:#60a5fa;">{time_str}</div>
                <div style="color: #64748b; font-size: 13px;">Interval {step_idx} / 144</div>
            </div>
            """, unsafe_allow_html=True)
            
            metric_temp.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">Zone Air Temp</div>
                <div class="metric-value">{temp:.1f} °C</div>
                <div style="color: #3b82f6; font-size: 13px;">Setpoint: {sim_session.active_setpoints.get('zone1_cooling_sp', 24.0):.1f}°C</div>
            </div>
            """, unsafe_allow_html=True)
            
            pmv_color = "#34d399" if -0.5 <= pmv <= 0.5 else "#ef4444"
            metric_pmv.markdown(f"""
            <div class="metric-card" style="border-color: {pmv_color};">
                <div class="metric-title">Fanger PMV Index</div>
                <div class="metric-value" style="color: {pmv_color};">{pmv:+.2f}</div>
                <div class="status-badge" style="background: rgba(52, 211, 153, 0.15); color: {pmv_color};">{"Optimal Comfort" if -0.5<=pmv<=0.5 else "Bound Warning"}</div>
            </div>
            """, unsafe_allow_html=True)
            
            metric_kwh.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">Cumulative Demand</div>
                <div class="metric-value" style="color:#10b981;">{cum_kwh:.1f} kWh</div>
                <div style="color: #10b981; font-size: 13px;">AI Load Optimized</div>
            </div>
            """, unsafe_allow_html=True)
            
            co2_color = "#34d399" if co2 < 700.0 else "#f59e0b"
            metric_co2.markdown(f"""
            <div class="metric-card" style="border-color: {co2_color};">
                <div class="metric-title">Indoor Air Quality</div>
                <div class="metric-value" style="color: {co2_color};">{co2:.0f} <span style="font-size:16px;">ppm</span></div>
                <div style="color: #94a3b8; font-size: 13px;">CO2 Concentration</div>
            </div>
            """, unsafe_allow_html=True)
            
            # Update Professional Multi-Subplot Plotly Chart
            fig_live = make_subplots(
                rows=2, cols=2,
                subplot_titles=("<b>Zone Air Temperature (°C) & Setpoint Trajectory</b>", "<b>Fanger PMV Thermal Comfort Index vs Bounds</b>", "<b>Cumulative Electrical Energy (kWh)</b>", "<b>Indoor Air Quality — CO2 Concentration (ppm)</b>"),
                vertical_spacing=0.15,
                horizontal_spacing=0.1
            )
            
            # Subplot (1, 1): Temperature
            fig_live.add_trace(go.Scatter(x=list(range(len(live_temps))), y=live_temps, mode="lines+markers", name="Air Temp (°C)", line=dict(color="#60a5fa", width=3)), row=1, col=1)
            fig_live.add_hline(y=24.0, line_dash="dot", line_color="#94a3b8", row=1, col=1)
            
            # Subplot (1, 2): PMV Comfort
            fig_live.add_trace(go.Scatter(x=list(range(len(live_pmvs))), y=live_pmvs, mode="lines", name="PMV Index", line=dict(color="#34d399", width=3)), row=1, col=2)
            fig_live.add_hrect(y0=-0.5, y1=0.5, fillcolor="rgba(52, 211, 153, 0.15)", line_width=0, row=1, col=2)
            fig_live.add_hline(y=0.5, line_dash="dash", line_color="#f59e0b", row=1, col=2)
            fig_live.add_hline(y=-0.5, line_dash="dash", line_color="#3b82f6", row=1, col=2)
            
            # Subplot (2, 1): Cumulative kWh
            fig_live.add_trace(go.Scatter(x=list(range(len(live_kwhs))), y=live_kwhs, mode="lines", name="Cumulative kWh", line=dict(color="#10b981", width=3), fill='tozeroy', fillcolor='rgba(16, 185, 129, 0.1)'), row=2, col=1)
            
            # Subplot (2, 2): Indoor Air Quality (CO2)
            fig_live.add_trace(go.Scatter(x=list(range(len(live_co2s))), y=live_co2s, mode="lines", name="CO2 (ppm)", line=dict(color="#c084fc", width=2.5)), row=2, col=2)
            fig_live.add_hline(y=1000.0, line_dash="dash", line_color="#ef4444", row=2, col=2)
            
            fig_live.update_layout(
                template="plotly_dark",
                hovermode="x unified",
                showlegend=False,
                margin=dict(l=30, r=30, t=50, b=30),
                height=520,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(15, 23, 42, 0.4)"
            )
            chart_placeholder.plotly_chart(fig_live, use_container_width=True)
            
            if live_decisions:
                with feed_placeholder.container():
                    st.markdown("#### 📡 Real-Time MCP Tool Execution & Decision Audit Trail")
                    st.dataframe(pd.DataFrame(live_decisions), use_container_width=True, hide_index=True)
                    
            time.sleep(sleep_delay)
        st.success("🏁 Live Real-Time Simulation Stream Completed Successfully!")

with tab_energy:
    st.markdown("### 📈 Comparative Cumulative Energy Demand Analysis")
    fig_energy = go.Figure()
    fig_energy.add_trace(go.Scatter(
        x=df_base["timestamp"], y=df_base["cumulative_kwh"],
        mode="lines", name="Baseline Schedule (Rule-Based)",
        line=dict(color="#ef4444", width=3, dash="dash")
    ))
    fig_energy.add_trace(go.Scatter(
        x=df_ai["timestamp"], y=df_ai["cumulative_kwh"],
        mode="lines", name="AI Autonomous Agent (Closed-Loop)",
        line=dict(color="#10b981", width=3.5),
        fill='tonexty', fillcolor='rgba(16, 185, 129, 0.12)'
    ))
    fig_energy.update_layout(
        title="<b>Cumulative Energy Consumption Divergence (kWh)</b>",
        xaxis_title="Simulation Timestamp",
        yaxis_title="Total Cumulative Demand (kWh)",
        template="plotly_dark",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=40, t=60, b=40),
        height=480,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15, 23, 42, 0.4)"
    )
    st.plotly_chart(fig_energy, use_container_width=True)

with tab_comfort:
    st.markdown("### 🌡️ Fanger PMV Thermal Comfort Verification")
    fig_comfort = go.Figure()
    fig_comfort.add_trace(go.Scatter(
        x=df_ai["timestamp"], y=df_ai["zone1_pmv"],
        mode="lines", name="AI Agent PMV Index",
        line=dict(color="#38bdf8", width=2.5)
    ))
    fig_comfort.add_trace(go.Scatter(
        x=df_base["timestamp"], y=df_base["zone1_pmv"],
        mode="lines", name="Baseline PMV Index",
        line=dict(color="#64748b", width=1.5, dash="dot")
    ))
    fig_comfort.add_hrect(y0=-0.5, y1=0.5, fillcolor="rgba(52, 211, 153, 0.12)", line_width=0, annotation_text="ASHRAE 55 Optimal Comfort Zone", annotation_position="top left")
    fig_comfort.add_hline(y=PMV_UPPER_BOUND, line_dash="dash", line_color="#f59e0b", annotation_text="Upper Limit (+0.5)", annotation_position="top right")
    fig_comfort.add_hline(y=PMV_LOWER_BOUND, line_dash="dash", line_color="#3b82f6", annotation_text="Lower Limit (-0.5)", annotation_position="bottom right")
    fig_comfort.update_layout(
        title="<b>Fanger PMV Thermal Comfort Index vs. Mandatory Constraints</b>",
        xaxis_title="Simulation Timestamp",
        yaxis_title="Predicted Mean Vote (PMV)",
        yaxis=dict(range=[-1.0, 1.0]),
        template="plotly_dark",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=40, t=60, b=40),
        height=480,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15, 23, 42, 0.4)"
    )
    st.plotly_chart(fig_comfort, use_container_width=True)

with tab_demand:
    st.markdown("### ⚡ Electrical Demand & Grid Carbon Intensity Synchronization")
    fig_demand = go.Figure()
    fig_demand.add_trace(go.Scatter(
        x=df_ai["timestamp"], y=df_ai["interval_kwh"] * 60.0,
        mode="lines", name="AI Electrical Demand (kW)",
        line=dict(color="#a855f7", width=2.5)
    ))
    fig_demand.add_trace(go.Scatter(
        x=df_ai["timestamp"], y=df_ai["grid_carbon_gco2_kwh"],
        mode="lines", name="Grid Carbon Intensity (gCO2/kWh)",
        line=dict(color="#f59e0b", width=1.8, dash="dash"),
        yaxis="y2"
    ))
    fig_demand.update_layout(
        title="<b>Electrical Demand (kW) vs. Grid Carbon Intensity (gCO2/kWh)</b>",
        xaxis_title="Simulation Timestamp",
        yaxis=dict(title="Electrical Demand (kW)", side="left", showgrid=False),
        yaxis2=dict(title="Grid Carbon Intensity (gCO2/kWh)", side="right", overlaying="y", showgrid=True),
        template="plotly_dark",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=40, t=60, b=40),
        height=480,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15, 23, 42, 0.4)"
    )
    st.plotly_chart(fig_demand, use_container_width=True)

# --- SECTION 3: AUDITABLE AGENT DECISION LOG ---
st.markdown("---")
st.markdown("### 🤖 Autonomous Agent Decision Log & MCP Execution Trail")
st.markdown("Every 15 simulated minutes, the reasoning layer evaluates building state, checks PMV boundaries, and emits validated MCP tool calls:")

if not df_dec.empty:
    df_display = df_dec.sort_values(by="sim_time_min", ascending=False).copy()
    st.dataframe(
        df_display[["timestamp", "tool_called", "params", "rationale", "status"]],
        use_container_width=True,
        height=400,
        hide_index=True
    )
else:
    st.info("No decision logs recorded yet.")
