from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from nlp_engine import clean_text, get_embeddings

class TFIDFEngine:
    def __init__(self):
        self.vectorizer = None
        self.doc_vectors = None
        self.documents = []

    def fit(self, data):
        """
        data: list of {"filename","path","text"}
        """
        texts = [clean_text(item.get("text","")) for item in data]
        self.documents = data
        if not texts or all(t=="" for t in texts):
            self.vectorizer = None
            self.doc_vectors = None
            return
        self.vectorizer = TfidfVectorizer().fit(texts)
        self.doc_vectors = self.vectorizer.transform(texts)

    def query(self, query_text, top_k=10):
        if self.vectorizer is None or self.doc_vectors is None:
            return []

        q = clean_text(query_text)
        q_vec = self.vectorizer.transform([q])
        sims = cosine_similarity(q_vec, self.doc_vectors)[0]

        idx_sorted = np.argsort(sims)[::-1][:top_k]
        results = []
        for i in idx_sorted:
            if sims[i]>0:
                results.append({
                    "filename": self.documents[i]["filename"],
                    "path": self.documents[i]["path"],
                    "score": float(sims[i]),
                    "text": self.documents[i]["text"]
                })
        return results

# Optional: Embedding search helper
def search_embeddings_engine(query, data, top_k=10, threshold=0.6):
    embeddings = get_embeddings([item["text"] for item in data])
    query_emb = get_embeddings([query])
    sims = cosine_similarity(query_emb, embeddings)[0]
    results = []
    for i, s in enumerate(sims):
        if s >= threshold:
            results.append({**data[i], "similarity": float(s)})
    results.sort(key=lambda x:x.get("similarity",0), reverse=True)
    return results[:top_k]
