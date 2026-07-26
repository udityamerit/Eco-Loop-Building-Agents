# Eco-Loop Building Agents: Autonomous Agent Upgradation Directives

**Target System:** `eco-loop-building-agents`
**Objective:** Refactor the existing local-execution architecture into a highly scalable, cloud-native, hybrid-AI physical control system. 

The following directives outline the exact technical specifications and architectural constraints for the system upgrade. Execute these phases sequentially.

---

## Phase 1: Cloud-Native Infrastructure & Real-Time Sync
**Goal:** Decouple physics simulation from cognitive reasoning to eliminate latency and prevent crashes over extended simulation horizons.

1.  **AWS Infrastructure Migration:**
    *   Containerize the EnergyPlus simulation environment (`src/energyplus_wrapper.py`) and deploy it to a dedicated **AWS EC2** instance to handle continuous computational workloads.
    *   Refactor the LLM orchestration layer (`src/mcp_client_agent.py` and `src/control_loop.py`) into serverless **AWS Lambda** functions. 
    *   Configure **VPC** and **IAM** roles to securely manage communication between the EC2 simulation instance and the Lambda orchestration layer.
2.  **Firebase Real-Time State Management:**
    *   Deprecate local CSV logging for active state synchronization.
    *   Integrate **Firebase** to stream real-time simulation metrics (kWh, PMV, zone temperatures) directly from the EC2 instance.
    *   Update `src/metrics_logger.py` to push decision logs and metric payloads to the Firebase database.
3.  **UI Interface Constraints (`dashboard/app.py`):**
    *   Refactor the Streamlit dashboard to pull live data streams directly from Firebase rather than parsing local CSV files.
    *   **Strict UI Directive:** The dashboard must be strictly analytical and enterprise-ready. You must scrub and remove any specific developer names or personal branding from all Streamlit UI interface components.

---

## Phase 2: Semantic Memory Context Engine
**Goal:** Provide the LLM reasoning agent with historical context to prevent repetitive sub-optimal decisions and learn from past successful Energy Conservation Measures (ECMs).

1.  **Vector Database Integration:**
    *   Implement **ChromaDB** to store historical building states mapped to successful MCP tool calls and ECMs.
2.  **State Embedding:**
    *   Utilize **Sentence Transformers** (specifically the `all-MiniLM-L6-v2` model) to generate embeddings of the current real-time building state (temperature, occupancy, grid carbon intensity).
3.  **Diverse Retrieval Strategy:**
    *   Implement **Maximal Marginal Relevance (MMR)** during the semantic search process within ChromaDB. This ensures the retrieved historical context injected into the LLM's prompt is highly relevant but also diverse, stabilizing the control policy.

---

## Phase 3: Hybrid Predictive ML Fusion
**Goal:** Prevent LLM hallucinations on strict numerical set-points by fusing classical machine learning predictions into the Model Context Protocol (MCP) payload.

1.  **Multi-Model Forecasting Package:**
    *   Develop a predictive module utilizing a multi-model approach (comparing **Logistic Regression, SVM, and Random Forest** implementations).
    *   Train these models on historical weather and building load data to forecast baseline zone temperatures and expected grid intensity for upcoming timesteps.
2.  **Hyperparameter Optimization:**
    *   Implement **GridSearch** across the classical models to determine the optimal parameters before deploying the forecasting pipeline.
3.  **Executive LLM Orchestration:**
    *   Modify `src/mcp_server.py` to inject the classical ML predictions into the `get_building_state` payload.
    *   Instruct the LLM to act as the executive orchestrator—evaluating the classical ML predictions against thermal comfort boundaries to issue the final `set_zone_setpoint` or `apply_ecm` tool calls.

---

## Phase 4: Delivery & Documentation
1.  **Repository Configuration:** Ensure GitHub repository visibility is configured to Public.
2.  **Architecture Sync:** Update `ARCHITECTURE.md` to reflect the new AWS/Firebase/ChromaDB integrations. 
