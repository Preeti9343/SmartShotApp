from PIL import Image, ImageTk
import os

def get_thumbnail_image(path, size=(200, 150)):
    try:
        img = Image.open(path)
        img.thumbnail(size)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None

def merge_scores(fuzzy_list, tfidf_list, embed_list, data, weights=(0.3,0.3,0.4), top_k=10):
    """
    fuzzy_list: list of dicts with 'filename' and 'fuzzy_score' OR dict mapping filename->score
    tfidf_list: list of {"index","score"} referencing data indices
    embed_list: list of {"index","score"}
    data: original data list
    weights: (w_fuzzy, w_tfidf, w_embed)
    Returns top_k merged results with fields:
    {"filename","path","text","score","components":{...}}
    """
    w_f, w_t, w_e = weights
   
    fuzzy_map = {}
    if isinstance(fuzzy_list, list):
        for it in fuzzy_list:
            fuzzy_map[it['filename']] = it.get('fuzzy_score', 0)
    else:
        fuzzy_map = fuzzy_list or {}

    tfidf_map = {}
    if tfidf_list:
        for it in tfidf_list:
            idx = it['index']; sc = it['score']; tfidf_map[data[idx]['filename']] = sc

    embed_map = {}
    if embed_list:
        for it in embed_list:
            idx = it['index']; sc = it['score']; embed_map[data[idx]['filename']] = sc

    
    filenames = set(list(fuzzy_map.keys()) + list(tfidf_map.keys()) + list(embed_map.keys()))
    results = []
    for fn in filenames:
        fsc = fuzzy_map.get(fn, 0)
        tsc = tfidf_map.get(fn, 0)
        esc = embed_map.get(fn, 0)
        score = w_f * (fsc/100.0) + w_t * (tsc) + w_e * (esc)  
        
        item = next((d for d in data if d['filename'] == fn), None)
        if item:
            results.append({
                "filename": fn,
                "path": item['path'],
                "text": item['text'],
                "score": float(score),
                "components": {"fuzzy": fsc, "tfidf": tsc, "embed": esc}
            })
    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:top_k]
