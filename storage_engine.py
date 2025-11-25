import json
from pathlib import Path

def save_data_json(data, filepath):
    """
    data: list of dicts (filename, path, text)
    """
    p = Path(filepath)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_data_json(filepath):
    p = Path(filepath)
    if not p.exists():
        return []
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)
