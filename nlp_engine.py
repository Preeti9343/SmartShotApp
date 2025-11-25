import string
from nltk.corpus import stopwords
from rapidfuzz import fuzz
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

STOPWORDS = set(stopwords.words('english'))
sbert_model = SentenceTransformer('all-MiniLM-L6-v2')
feedback_scores = {}  # user feedback

def clean_text(text):
    """
    Lowercase, remove punctuation, stopwords.
    """
    if not text or not isinstance(text, str):
        return ""
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    tokens = [t for t in text.split() if t and t not in STOPWORDS]
    return " ".join(tokens)

# --------- Fuzzy Search ----------
def fuzzy_score(query, text):
    if not text:
        return 0
    return fuzz.partial_ratio(query, text)

def search_fuzzy(query, data, top_k=5, threshold=60):
    query_c = clean_text(query)
    results = []
    for item in data:
        txt = clean_text(item.get("text",""))
        score = fuzzy_score(query_c, txt)
        if score >= threshold:
            results.append({**item, "fuzzy_score": score})
    results.sort(key=lambda x: x["fuzzy_score"], reverse=True)
    return results[:top_k]

# --------- Embedding Search ----------
def get_embeddings(text_list):
    return sbert_model.encode(text_list)

def search_embeddings(query, data, top_k=5, threshold=0.6):
    texts = [item["text"] for item in data]
    embeddings = get_embeddings(texts)
    query_emb = get_embeddings([query])
    sims = cosine_similarity(query_emb, embeddings)[0]

    results = []
    for i, item in enumerate(data):
        if sims[i] >= threshold:
            results.append({**item, "similarity": float(sims[i])})
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:top_k]

# --------- Merge Scores ----------
def merge_scores(fuzzy_list, tfidf_list, embed_list, data, weights=(0.3,0.3,0.4), top_k=10):
    w_f, w_t, w_e = weights
    fuzzy_map = {it['filename']: it.get('fuzzy_score',0) for it in (fuzzy_list or [])}
    tfidf_map = {data[it['index']]['filename']: it['score'] for it in (tfidf_list or [])}
    embed_map = {data[it['index']]['filename']: it['score'] for it in (embed_list or [])}

    filenames = set(list(fuzzy_map.keys()) + list(tfidf_map.keys()) + list(embed_map.keys()))
    results = []
    for fn in filenames:
        fsc = fuzzy_map.get(fn, 0)
        tsc = tfidf_map.get(fn, 0)
        esc = embed_map.get(fn, 0)
        score = w_f*(fsc/100) + w_t*tsc + w_e*esc
        item = next((d for d in data if d['filename']==fn), None)
        if item:
            results.append({
                "filename": fn,
                "path": item['path'],
                "text": item['text'],
                "score": float(score),
                "components": {"fuzzy": fsc, "tfidf": tsc, "embed": esc}
            })
    results.sort(key=lambda x:x['score'], reverse=True)
    return results[:top_k]

# --------- Feedback System ----------
def record_feedback(filename, relevance):
    """relevance: +1 (good), -1 (bad)"""
    feedback_scores[filename] = feedback_scores.get(filename,0) + relevance

def apply_feedback(results):
    """Adjust ranking based on feedback"""
    for r in results:
        r["score"] += feedback_scores.get(r["filename"],0)*0.1
    results.sort(key=lambda x:x["score"], reverse=True)
    return results
