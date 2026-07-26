"""
Semantic Memory Context Engine for Eco-Loop Building Agents.
Integrates ChromaDB and Sentence Transformers ('all-MiniLM-L6-v2') to store historical building states
and retrieve relevant, diverse successful control actions using Maximal Marginal Relevance (MMR).
Includes a lightweight mathematical vector fallback when heavy ML packages are offline.
"""
import os
import json
import math
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("SemanticMemoryEngine")
logger.setLevel(logging.INFO)

try:
    import chromadb
    from chromadb.config import Settings
    from sentence_transformers import SentenceTransformer
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    logger.info("ChromaDB or sentence-transformers not installed. Engaging lightweight mathematical vector memory fallback.")

class SemanticMemoryEngine:
    """
    Stores historical building states and successful ECM tool calls.
    Uses Maximal Marginal Relevance (MMR) to retrieve diverse, relevant past context for the LLM.
    """
    def __init__(self, db_path: Optional[str] = None, collection_name: str = "ecoloop_ecm_memory"):
        self.collection_name = collection_name
        self.db_path = db_path or os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "chroma_db")
        self.model = None
        self.client = None
        self.collection = None
        self.fallback_memory: List[Dict[str, Any]] = []
        
        self._init_engine()
        self._seed_default_memories()

    def _init_engine(self):
        if CHROMADB_AVAILABLE:
            try:
                os.makedirs(self.db_path, exist_ok=True)
                self.model = SentenceTransformer("all-MiniLM-L6-v2")
                self.client = chromadb.PersistentClient(path=self.db_path)
                self.collection = self.client.get_or_create_collection(name=self.collection_name)
                logger.info("ChromaDB and SentenceTransformer initialized successfully.")
            except Exception as e:
                logger.warning(f"Failed to initialize ChromaDB ({e}). Falling back to in-memory vector storage.")
                self.collection = None
        else:
            self.collection = None

    def _state_to_text(self, state: Dict[str, Any]) -> str:
        """Converts structured building state into semantic text for embedding."""
        temp = round(state.get("zone1_temp", 23.0), 1)
        pmv = round(state.get("zone1_pmv", 0.0), 2)
        carbon = round(state.get("grid_carbon_gco2_kwh", 300.0), 0)
        occ = round(state.get("occupancy_pct", 80.0), 0)
        return f"Zone temperature is {temp}C with Fanger PMV index of {pmv}. Grid carbon intensity is {carbon} gCO2/kWh and zone occupancy is {occ}%."

    def _embed_text(self, text: str) -> List[float]:
        """Generates embedding vector for text using sentence-transformer or fallback hash embedding."""
        if self.model and self.collection:
            try:
                return self.model.encode(text).tolist()
            except Exception:
                pass
        # Lightweight deterministic 32-dim semantic feature vector fallback
        words = text.lower().split()
        vec = [0.0] * 32
        for i, word in enumerate(words):
            idx = sum(ord(c) for c in word) % 32
            vec[idx] += 1.0 / (i + 1)
        # Normalize vector
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def store_memory(self, state: Dict[str, Any], action: Dict[str, Any], rationale: str):
        """Stores a successful control decision in the semantic memory database."""
        text = self._state_to_text(state)
        embedding = self._embed_text(text)
        metadata = {
            "action_json": json.dumps(action),
            "rationale": rationale,
            "temp": state.get("zone1_temp", 23.0),
            "pmv": state.get("zone1_pmv", 0.0)
        }
        doc_id = f"mem_{len(self.fallback_memory) + 1}_{int(state.get('sim_time', 0))}"
        
        if self.collection:
            try:
                self.collection.add(
                    ids=[doc_id],
                    embeddings=[embedding],
                    documents=[text],
                    metadatas=[metadata]
                )
            except Exception as e:
                logger.debug(f"ChromaDB store skipped: {e}")
                
        self.fallback_memory.append({
            "id": doc_id,
            "text": text,
            "embedding": embedding,
            "metadata": metadata,
            "action": action,
            "rationale": rationale
        })

    def retrieve_mmr(self, query_state: Dict[str, Any], top_k: int = 2, lambda_param: float = 0.65) -> List[Dict[str, Any]]:
        """
        Retrieves historical successful ECM actions using Maximal Marginal Relevance (MMR)
        to balance semantic relevance with policy diversity.
        """
        query_text = self._state_to_text(query_state)
        query_emb = self._embed_text(query_text)
        
        candidates = []
        if self.collection and self.collection.count() > 0:
            try:
                res = self.collection.query(query_embeddings=[query_emb], n_results=min(10, self.collection.count()))
                for i in range(len(res["ids"][0])):
                    candidates.append({
                        "id": res["ids"][0][i],
                        "text": res["documents"][0][i],
                        "metadata": res["metadatas"][0][i],
                        "embedding": res["embeddings"][0][i] if "embeddings" in res and res["embeddings"] else self._embed_text(res["documents"][0][i])
                    })
            except Exception:
                candidates = self.fallback_memory
        else:
            candidates = self.fallback_memory
            
        if not candidates:
            return []
            
        # Compute cosine similarity between query and candidate embeddings
        def cosine_sim(vec1: List[float], vec2: List[float]) -> float:
            dot = sum(a * b for a, b in zip(vec1, vec2))
            norm1 = math.sqrt(sum(a * a for a in vec1)) or 1e-9
            norm2 = math.sqrt(sum(b * b for b in vec2)) or 1e-9
            return dot / (norm1 * norm2)
            
        selected: List[Dict[str, Any]] = []
        unselected = list(candidates)
        
        while len(selected) < min(top_k, len(candidates)):
            best_score = -float("inf")
            best_idx = -1
            
            for idx, cand in enumerate(unselected):
                sim_to_query = cosine_sim(query_emb, cand["embedding"])
                
                if not selected:
                    max_sim_to_selected = 0.0
                else:
                    max_sim_to_selected = max(cosine_sim(cand["embedding"], s["embedding"]) for s in selected)
                    
                mmr_score = lambda_param * sim_to_query - (1.0 - lambda_param) * max_sim_to_selected
                
                if mmr_score > best_score:
                    best_score = mmr_score
                    best_idx = idx
                    
            if best_idx >= 0:
                item = unselected.pop(best_idx)
                selected.append(item)
            else:
                break
                
        # Format results
        results = []
        for item in selected:
            meta = item.get("metadata", {})
            action_data = meta.get("action_json")
            action_obj = json.loads(action_data) if action_data else item.get("action", {})
            results.append({
                "context_state": item.get("text"),
                "recommended_action": action_obj,
                "rationale": meta.get("rationale", item.get("rationale", ""))
            })
        return results

    def _seed_default_memories(self):
        """Seeds memory with foundational high-efficiency physical domain rules."""
        if len(self.fallback_memory) == 0:
            self.store_memory(
                {"zone1_temp": 22.5, "zone1_pmv": -0.1, "grid_carbon_gco2_kwh": 460.0, "occupancy_pct": 80.0},
                {"name": "set_zone_setpoint", "params": {"zone_id": "ZONE1", "setpoint_type": "cooling", "value": 23.5}},
                "Increasing cooling setpoint by 1.0C sheds compressor load during high carbon intensity while keeping PMV optimal (-0.1 -> +0.2)."
            )
            self.store_memory(
                {"zone1_temp": 23.0, "zone1_pmv": 0.0, "grid_carbon_gco2_kwh": 310.0, "occupancy_pct": 0.0},
                {"name": "apply_ecm", "params": {"ecm_name": "reduce_lighting_load", "params": {"zone_id": "ZONE1", "reduction_pct": 50}}},
                "Zone unoccupied; dimming lighting by 50% reduces baseline electrical demand without impacting thermal comfort."
            )
