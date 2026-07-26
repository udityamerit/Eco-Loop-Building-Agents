# Eco-Loop Building Agents — Streamlit Cloud Deployment Guide

This guide details how to deploy the **Eco-Loop Digital Twin Command Center** (`dashboard/app.py`) to cloud environments, including **Streamlit Community Cloud**, **Docker**, and **Google Cloud Run / AWS ECS**.

---

## Option 1: Streamlit Community Cloud (Recommended & Instant)

Streamlit Community Cloud provides zero-config continuous deployment directly from your GitHub repository.

### Step-by-Step Instructions:
1. **Push to GitHub**: Ensure all latest code changes (including `.streamlit/config.toml` and `requirements.txt`) are committed and pushed to your GitHub repository.
2. **Log in to Streamlit Cloud**: Go to [share.streamlit.io](https://share.streamlit.io/) and log in with your GitHub account.
3. **Deploy App**:
   - Click **"Create app"** or **"New app"**.
   - Select your **Repository** (`Uditya/Eco-Loop-Building-Agents` or your fork).
   - Select the **Branch** (e.g., `main` or `master`).
   - In **Main file path**, enter:
     ```
     dashboard/app.py
     ```
4. **Advanced Settings (Optional)**:
   - Python Version: Select **Python 3.11** or **3.10**.
   - Environment Variables: If connecting to an external cloud vector database or API, add environment variables under **Secrets**.
5. **Launch**: Click **"Deploy!"**. Streamlit will automatically build the environment from `requirements.txt` and launch your interactive dashboard.

---

## Option 2: Containerized Deployment via Docker

We provide a dedicated Dockerfile optimized for container engines (Docker Desktop, Google Cloud Run, AWS Fargate, Azure App Service).

### 1. Build the Docker Image
From the workspace root directory, run:
```bash
docker build -t ecoloop-dashboard -f deploy/Dockerfile.streamlit .
```

### 2. Run Locally in Container
```bash
docker run -d -p 8501:8501 --name ecoloop ecoloop-dashboard
```
Open your browser and navigate to: [http://localhost:8501](http://localhost:8501)

---

## Option 3: AWS / Cloud VM Manual Deployment

To run the application continuously on an Ubuntu/Debian EC2 instance or virtual machine:

1. **Clone the repository**:
   ```bash
   git clone https://github.com/your-username/Eco-Loop-Building-Agents.git
   cd Eco-Loop-Building-Agents
   ```
2. **Install dependencies**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```
3. **Run using Screen or Systemd**:
   ```bash
   nohup streamlit run dashboard/app.py --server.port=8501 --server.address=0.0.0.0 > streamlit.log 2>&1 &
   ```

---

## Architecture Note: Cloud Physics Fallback

When deployed to Linux serverless containers or Streamlit Community Cloud where local binary installations of EnergyPlus CLI (`eppy`) may be offline or restricted:
- The system automatically engages the **Dual-Mode High-Fidelity Thermal & HVAC Physics simulation engine** defined in `src/energyplus_wrapper.py`.
- All autonomous control loops, thermal comfort verifications, and analytical dashboards operate with 100% mathematical fidelity without requiring binary pre-compilation.
