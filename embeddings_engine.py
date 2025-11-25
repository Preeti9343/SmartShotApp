import numpy as np
import logging


try:
    from sentence_transformers import SentenceTransformer
    _HAS_SBERT = True
except Exception:
    _HAS_SBERT = False

try:
    import spacy
    _HAS_SPACY = True
except Exception:
    _HAS_SPACY = False

class EmbeddingsEngine:
    def __init__(self, model_name="all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.model = None
        self.doc_embeddings = None
        self.paths = []
        self.fallback_to_spacy = False

    def load_model(self):
        if _HAS_SBERT:
            try:
                self.model = SentenceTransformer(self.model_name)
                return
            except Exception as e:
                logging.warning("SentenceTransformer load failed: %s", e)
        
        if _HAS_SPACY:
            try:
                self.model = spacy.load("en_core_web_md")
                self.fallback_to_spacy = True
                return
            except Exception as e:
                logging.warning("spaCy load failed: %s", e)
        raise RuntimeError("No embeddings model available. Install 'sentence-transformers' or spaCy 'en_core_web_md'.")

    def fit(self, data):
        """
        data: list of {"filename","path","text"}
        """
        texts = [item.get("text","") or "" for item in data]
        self.paths = [item.get("path") for item in data]
        if not texts:
            self.doc_embeddings = None
            return
        if self.model is None:
            self.load_model()
        if self.fallback_to_spacy:
            
            self.doc_embeddings = np.array([self.model(text).vector for text in texts])
        else:
            self.doc_embeddings = np.array(self.model.encode(texts, show_progress_bar=False))
        
        norms = np.linalg.norm(self.doc_embeddings, axis=1, keepdims=True)
        norms[norms==0] = 1.0
        self.doc_embeddings = self.doc_embeddings / norms

    def query(self, query_text, top_k=10):
        if self.doc_embeddings is None:
            return []
        if self.model is None:
            self.load_model()
        if self.fallback_to_spacy:
            q_emb = self.model(query_text).vector
        else:
            q_emb = self.model.encode([query_text], show_progress_bar=False)[0]
        q_emb = q_emb / (np.linalg.norm(q_emb) or 1.0)
        sims = (self.doc_embeddings @ q_emb)
        idx_sorted = np.argsort(sims)[::-1][:top_k]
        results = [{"index": int(i), "score": float(sims[i])} for i in idx_sorted if sims[i] > 0]
        return results
