# """
# SmartShotApp - Desktop
# (CustomTkinter UI with Scores + Preview + Location Open + Share
# + Advanced Filters + Recent Searches with Result Cache + Tags System
# + Duplicate Finder + Login/Register + Profile Corner)
# """

import os
import json
import threading
import re
import traceback
import time
import subprocess

import customtkinter as ctk
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import messagebox

from ocr_engine import extract_text_from_folder
from nlp_engine import apply_feedback, clean_text
from ml_engine import TFIDFEngine
from storage_engine import save_data_json, load_data_json

# ------------------ Fuzzy helper (rapidfuzz or difflib) ------------------
try:
    from rapidfuzz import fuzz

    def FUZZ_RATIO(a, b):
        try:
            return fuzz.partial_ratio(a, b)
        except Exception:
            return 0
except Exception:
    import difflib

    def FUZZ_RATIO(a, b):
        return int(difflib.SequenceMatcher(None, a, b).ratio() * 100)


# ------------------ Constants & Globals ------------------
DATA = []
filtered_data = []

DATA_FOLDER = "data_storage"
LAST_USED_FILE = os.path.join(DATA_FOLDER, "last_used_folder.json")
USED_FOLDERS_FILE = os.path.join(DATA_FOLDER, "used_folders.json")
RECENT_SEARCHES_FILE = os.path.join(DATA_FOLDER, "recent_searches.json")
USERS_FILE = os.path.join(DATA_FOLDER, "users.json")  # for login/register

EXT_OPTIONS = ["All", "Images", ".pdf", ".docx", ".txt"]
DATE_FILTER_OPTIONS = [
    "Any time",
    "Last 24 hours",
    "Last 7 days",
    "Last 30 days",
    "Older than 30 days",
]
SIZE_FILTER_OPTIONS = [
    "Any size",
    "< 1 MB",
    "1–10 MB",
    "> 10 MB",
]

tfidf_engine = TFIDFEngine()

root = None
folder_entry = None
search_entry = None
result_frame = None
folder_dropdown = None
ext_dropdown = None
date_filter_dropdown = None
size_filter_dropdown = None
recent_dropdown = None
tag_filter_dropdown = None

progress_label = None
progress_var = None
progress_bar = None

# logged-in user
CURRENT_USER = None


# ------------------ Helper UI class ------------------
class AutocompleteCombobox(ctk.CTkComboBox):
    def set_completion_list(self, completion_list):
        self._completion_list = sorted(completion_list, key=str.lower)
        self.configure(values=self._completion_list)


# ------------------ User storage helpers (Login / Register) ------------------
def load_users():
    """JSON se users load: {username: {password, question, answer}} ya purana format."""
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}

    users = {}
    if isinstance(raw, dict):
        for uname, val in raw.items():
            if isinstance(val, str):
                # old: "username": "password"
                users[uname] = {
                    "password": val,
                    "question": None,
                    "answer": None,
                }
            elif isinstance(val, dict):
                users[uname] = {
                    "password": val.get("password", ""),
                    "question": val.get("question"),
                    "answer": val.get("answer"),
                }
    return users


def save_users(users: dict):
    os.makedirs(DATA_FOLDER, exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def register_user(username: str, password: str, question: str, answer: str):
    username = (username or "").strip()
    password = (password or "").strip()
    question = (question or "").strip()
    answer = (answer or "").strip()

    if not username or not password:
        return False, "Username and password are required."

    if len(password) < 4:
        return False, "Password must be at least 4 characters."

    if not question or not answer:
        return False, "Security question and answer are required."

    users = load_users()
    if username in users:
        return False, "This username already exists. Please choose another."

    users[username] = {
        "password": password,
        "question": question,
        "answer": answer.lower(),
    }
    save_users(users)
    return True, "Account created successfully! You can now log in."


def authenticate_user(username: str, password: str) -> bool:
    username = (username or "").strip()
    password = (password or "").strip()
    users = load_users()
    info = users.get(username)
    if info is None:
        return False

    if isinstance(info, str):
        return info == password

    return info.get("password") == password


# ------------------ Folder JSON helpers ------------------
def get_folder_json_path(folder_path):
    folder_name = os.path.basename(os.path.normpath(folder_path)) or "root"
    return os.path.join(DATA_FOLDER, f"{folder_name}.json")


def load_last_used_folder():
    if os.path.exists(LAST_USED_FILE):
        try:
            with open(LAST_USED_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("folder_path", "")
        except Exception as e:
            print("Error reading last_used_folder:", e)
    return ""


def save_last_used_folder(folder_path):
    os.makedirs(DATA_FOLDER, exist_ok=True)
    with open(LAST_USED_FILE, "w", encoding="utf-8") as f:
        json.dump({"folder_path": folder_path}, f, ensure_ascii=False)


def load_used_folders():
    if os.path.exists(USED_FOLDERS_FILE):
        try:
            with open(USED_FOLDERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as e:
            print("Error reading used_folders:", e)
    return []


def save_used_folder(folder_path):
    folders = load_used_folders()
    if folder_path not in folders:
        folders.append(folder_path)
        os.makedirs(DATA_FOLDER, exist_ok=True)
        with open(USED_FOLDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(folders, f, ensure_ascii=False)


# ------------------ Recent searches + cached results ------------------
def _load_recent_data():
    if not os.path.exists(RECENT_SEARCHES_FILE):
        return {"recent": [], "cache": {}}
    try:
        with open(RECENT_SEARCHES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"recent": [], "cache": {}}
        if "recent" not in data:
            data["recent"] = []
        if "cache" not in data:
            data["cache"] = {}
        return data
    except Exception as e:
        print("Error reading recent_searches:", e)
        return {"recent": [], "cache": {}}


def _save_recent_data(data):
    try:
        os.makedirs(DATA_FOLDER, exist_ok=True)
        with open(RECENT_SEARCHES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Error writing recent_searches:", e)


def load_recent_searches():
    data = _load_recent_data()
    recent_list = data.get("recent", [])
    return [r.get("query", "") for r in recent_list if r.get("query")]


def save_recent_search_with_results(
    query, results, max_items=10, max_results_per_query=5
):
    query = (query or "").strip()
    if not query:
        return

    data = _load_recent_data()
    recent_list = data.get("recent", [])
    cache = data.get("cache", {})

    recent_list = [
        r for r in recent_list if r.get("query", "").lower() != query.lower()
    ]
    recent_list.insert(0, {"query": query, "time": time.time()})

    if len(recent_list) > max_items:
        for r in recent_list[max_items:]:
            q = r.get("query")
            if q in cache:
                cache.pop(q, None)
        recent_list = recent_list[:max_items]

    cached_results = []
    for item in (results[:max_results_per_query] if results else []):
        cached_results.append(
            {
                "filename": item.get("filename", ""),
                "path": item.get("path", ""),
                "text": item.get("text", ""),
                "score": float(item.get("score", 0.0)),
                "fuzzy_score": float(item.get("fuzzy_score", 0.0)),
                "tfidf_score": float(item.get("tfidf_score", 0.0)),
                "embed_score": float(item.get("embed_score", 0.0)),
                "match_info": item.get("match_info", "Fuzzy / semantic match"),
                "tags": item.get("tags", []),
            }
        )

    cache[query] = cached_results
    data["recent"] = recent_list
    data["cache"] = cache
    _save_recent_data(data)
    refresh_recent_dropdown()


def load_recent_results_for_query(query):
    query = (query or "").strip()
    if not query:
        return []
    data = _load_recent_data()
    cache = data.get("cache", {})
    results = cache.get(query, []) or []
    for r in results:
        if "tags" not in r or not isinstance(r["tags"], list):
            r["tags"] = []
    return results


def refresh_recent_dropdown():
    global recent_dropdown
    if root is None or recent_dropdown is None:
        return

    def _update():
        try:
            values = load_recent_searches()
            if not values:
                recent_dropdown.configure(values=[""])
                recent_dropdown.set("")
            else:
                recent_dropdown.configure(values=values)
        except Exception:
            pass

    root.after(0, _update)


# ------------------ TF-IDF fit ------------------
def fit_tfidf_engine():
    if not DATA:
        return
    try:
        try:
            tfidf_engine.fit(DATA)
        except Exception:
            tfidf_engine.fit([d.get("text", "") for d in DATA])
        print(f"TF-IDF fitted on {len(DATA)} docs.")
        show_notification("📊 Search index updated (TF-IDF ready)", "lightgreen")
    except Exception as e:
        print("TFIDF fit error:", e)
        show_notification("⚠ TF-IDF index update failed", "orange")


# ------------------ Popup Notifications ------------------
def show_notification(text, color="white"):
    global root
    if root is None:
        return

    def _show():
        notif = ctk.CTkToplevel(root)
        notif.title("Notification")
        notif.geometry("360x130")
        notif.resizable(False, False)
        notif.attributes("-topmost", True)

        try:
            root.update_idletasks()
            x = root.winfo_x() + (root.winfo_width() // 2) - 180
            y = root.winfo_y() + (root.winfo_height() // 2) - 65
            notif.geometry(f"+{x}+{y}")
        except Exception:
            pass

        frame = ctk.CTkFrame(notif, corner_radius=10)
        frame.pack(expand=True, fill="both", padx=10, pady=10)

        label = ctk.CTkLabel(
            frame,
            text=text,
            wraplength=320,
            justify="center",
            font=("Segoe UI", 11),
            text_color=("black", "white"),
        )
        label.pack(expand=True, pady=(10, 5))

        ok_btn = ctk.CTkButton(frame, text="OK", width=60, command=notif.destroy)
        ok_btn.pack(pady=(0, 10))

        notif.after(2500, notif.destroy)

    root.after(0, _show)


# ------------------ File & image helpers ------------------
def get_thumbnail_image(path, size=(220, 150)):
    try:
        img = Image.open(path)
        img.thumbnail(size)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


def open_file(path):
    if path and os.path.exists(path):
        os.startfile(path)
    else:
        show_notification("⚠ File not found on disk", "orange")


def open_location(path):
    if not path or not os.path.exists(path):
        show_notification("⚠ File path not found on disk", "orange")
        return
    try:
        if os.name == "nt":
            subprocess.run(["explorer", "/select,", os.path.normpath(path)])
        else:
            folder = os.path.dirname(path)
            if folder:
                os.startfile(folder)
    except Exception as e:
        print("open_location error:", e)
        try:
            folder = os.path.dirname(path)
            if folder:
                os.startfile(folder)
        except Exception:
            show_notification("❌ Unable to open folder location", "red")


def copy_file_to_clipboard(path):
    if not path or not os.path.exists(path):
        show_notification("⚠ File not found on disk", "orange")
        return
    try:
        if os.name == "nt":
            cmd = f'Set-Clipboard -Path "{path}"'
            subprocess.run(
                ["powershell", "-NoLogo", "-NoProfile", "-Command", cmd],
                check=True,
            )
            show_notification(
                "📋 File copied to clipboard (paste in WhatsApp, etc.)",
                "lightgreen",
            )
        else:
            if root is not None:
                root.clipboard_clear()
                root.clipboard_append(path)
            show_notification(
                "📋 Path copied (file copy only works fully on Windows)", "orange"
            )
    except Exception as e:
        print("copy_file_to_clipboard error:", e)
        show_notification("⚠ Unable to copy file to clipboard", "orange")


# ------------------ TAG helpers ------------------
def ensure_tags_field():
    for d in DATA:
        if "tags" not in d or not isinstance(d["tags"], list):
            d["tags"] = []


def get_all_tags():
    tags = set()
    for d in DATA:
        for t in d.get("tags", []):
            if t:
                tags.add(t.strip())
    return sorted(tags, key=str.lower)


def refresh_tag_filter_dropdown():
    global tag_filter_dropdown
    if root is None or tag_filter_dropdown is None:
        return

    def _update():
        options = ["All tags"]
        options.extend(get_all_tags())
        tag_filter_dropdown.configure(values=options)
        tag_filter_dropdown.set("All tags")

    root.after(0, _update)


def propagate_tags_to_data(path, tags):
    normalized_path = os.path.normpath(path or "")
    for d in DATA:
        p = os.path.normpath(d.get("path", "") or "")
        if p == normalized_path:
            d["tags"] = list(sorted(set(tags)))
    for d in filtered_data:
        p = os.path.normpath(d.get("path", "") or "")
        if p == normalized_path:
            d["tags"] = list(sorted(set(tags)))


def save_tags_to_folder_json(path, tags):
    path = path or ""
    if not path:
        return
    folder = os.path.dirname(path)
    if not folder:
        return

    json_path = get_folder_json_path(folder)
    if not os.path.exists(json_path):
        return

    try:
        data_list = load_data_json(json_path)
    except Exception as e:
        print("Error loading folder json for tags:", e)
        return

    changed = False
    norm_target = os.path.normpath(path)
    for item in data_list:
        p = os.path.normpath(item.get("path", "") or "")
        if p == norm_target:
            item["tags"] = list(sorted(set(tags)))
            changed = True
            break

    if changed:
        try:
            save_data_json(data_list, json_path)
        except Exception as e:
            print("Error saving folder json with tags:", e)


def open_tag_manager(item):
    global root
    if root is None:
        return

    path = item.get("path", "") or ""
    filename = item.get("filename", "") or ""
    current_tags = set([t.strip() for t in item.get("tags", []) if t])

    ensure_tags_field()
    all_tags = get_all_tags()

    win = ctk.CTkToplevel(root)
    win.title(f"Tags - {filename}")
    win.geometry("480x420")
    win.resizable(False, False)
    win.attributes("-topmost", True)

    try:
        root.update_idletasks()
        x = root.winfo_x() + (root.winfo_width() // 2) - 240
        y = root.winfo_y() + (root.winfo_height() // 2) - 210
        win.geometry(f"+{x}+{y}")
    except Exception:
        pass

    win.grid_columnconfigure(0, weight=1)
    win.grid_rowconfigure(2, weight=1)

    header = ctk.CTkFrame(win)
    header.grid(row=0, column=0, padx=10, pady=(10, 0), sticky="ew")

    title_lbl = ctk.CTkLabel(
        header,
        text=f"Manage tags for:\n{filename}",
        font=("Segoe UI Semibold", 13),
        justify="left",
    )
    title_lbl.pack(anchor="w", padx=8, pady=6)

    body = ctk.CTkFrame(win)
    body.grid(row=1, column=0, padx=10, pady=(6, 4), sticky="ew")

    exist_lbl = ctk.CTkLabel(body, text="Existing tags:", font=("Segoe UI", 11))
    exist_lbl.grid(row=0, column=0, padx=8, pady=(6, 2), sticky="w")

    tags_frame = ctk.CTkScrollableFrame(win, corner_radius=8)
    tags_frame.grid(row=2, column=0, padx=10, pady=(0, 6), sticky="nsew")
    tags_frame.grid_columnconfigure(0, weight=1)

    checkbox_vars = {}

    if not all_tags:
        empty_lbl = ctk.CTkLabel(
            tags_frame,
            text="No tags yet. Create a new tag below.",
            font=("Segoe UI", 10),
            text_color="gray70",
        )
        empty_lbl.grid(row=0, column=0, padx=8, pady=8, sticky="w")
    else:
        for i, t in enumerate(all_tags):
            var = tk.BooleanVar(value=(t in current_tags))
            cb = ctk.CTkCheckBox(tags_frame, text=t, variable=var)
            cb.grid(row=i, column=0, padx=8, pady=4, sticky="w")
            checkbox_vars[t] = var

    new_tag_frame = ctk.CTkFrame(win)
    new_tag_frame.grid(row=3, column=0, padx=10, pady=(4, 4), sticky="ew")
    new_tag_frame.grid_columnconfigure(0, weight=1)

    new_tag_label = ctk.CTkLabel(
        new_tag_frame, text="Add new tag:", font=("Segoe UI", 11)
    )
    new_tag_label.grid(row=0, column=0, padx=8, pady=(4, 0), sticky="w")

    new_tag_entry = ctk.CTkEntry(
        new_tag_frame, placeholder_text="Type new tag name..."
    )
    new_tag_entry.grid(row=1, column=0, padx=8, pady=(2, 4), sticky="ew")

    def on_add_tag():
        new_tag = new_tag_entry.get().strip()
        if not new_tag:
            return
        if new_tag not in checkbox_vars:
            row = len(checkbox_vars)
            var = tk.BooleanVar(value=True)
            cb = ctk.CTkCheckBox(tags_frame, text=new_tag, variable=var)
            cb.grid(row=row, column=0, padx=8, pady=4, sticky="w")
            checkbox_vars[new_tag] = var
        else:
            checkbox_vars[new_tag].set(True)
        new_tag_entry.delete(0, ctk.END)

    add_tag_btn = ctk.CTkButton(
        new_tag_frame, text="Add", width=80, command=on_add_tag
    )
    add_tag_btn.grid(row=1, column=1, padx=(4, 8), pady=(2, 4))

    footer = ctk.CTkFrame(win, fg_color="transparent")
    footer.grid(row=4, column=0, padx=10, pady=(4, 10), sticky="ew")
    footer.grid_columnconfigure(0, weight=1)
    footer.grid_columnconfigure(1, weight=0)
    footer.grid_columnconfigure(2, weight=0)

    def on_apply():
        selected = set()
        for t, var in checkbox_vars.items():
            if var.get():
                selected.add(t.strip())

        new_tag_text = new_tag_entry.get().strip()
        if new_tag_text:
            selected.add(new_tag_text)

        selected_list = sorted(set([t for t in selected if t]))

        item["tags"] = selected_list
        propagate_tags_to_data(path, selected_list)
        save_tags_to_folder_json(path, selected_list)

        refresh_tag_filter_dropdown()
        display_results(filtered_data if filtered_data else DATA, search_entry.get())
        show_notification("✅ Tags updated", "lightgreen")
        win.destroy()

    apply_btn = ctk.CTkButton(footer, text="Apply", width=80, command=on_apply)
    apply_btn.grid(row=0, column=1, padx=(0, 8), pady=4, sticky="e")

    cancel_btn = ctk.CTkButton(
        footer,
        text="Cancel",
        width=80,
        fg_color="transparent",
        border_width=1,
        command=win.destroy,
    )
    cancel_btn.grid(row=0, column=2, padx=(0, 8), pady=4, sticky="e")


# ------------------ Filtering (ext + date + size + tags) ------------------
def update_filtered_data():
    global filtered_data

    if not DATA:
        filtered_data = []
        return

    try:
        selected_ext = ext_dropdown.get() if ext_dropdown else "All"
    except Exception:
        selected_ext = "All"

    try:
        selected_date = (
            date_filter_dropdown.get() if date_filter_dropdown else "Any time"
        )
    except Exception:
        selected_date = "Any time"

    try:
        selected_size = (
            size_filter_dropdown.get() if size_filter_dropdown else "Any size"
        )
    except Exception:
        selected_size = "Any size"

    try:
        selected_tag = (
            tag_filter_dropdown.get() if tag_filter_dropdown else "All tags"
        )
    except Exception:
        selected_tag = "All tags"

    if selected_ext == "All":
        temp = list(DATA)
    elif selected_ext == "Images":
        img_exts = (".png", ".jpg", ".jpeg", ".bmp", ".tiff")
        temp = [
            d
            for d in DATA
            if (d.get("filename", "") or "").lower().endswith(img_exts)
        ]
    else:
        ext = selected_ext.lower()
        temp = [
            d
            for d in DATA
            if (d.get("filename", "") or "").lower().endswith(ext)
        ]

    now_ts = time.time()
    filtered_by_date = []

    for d in temp:
        mt = d.get("modified_time") or d.get("created_time")
        if not isinstance(mt, (int, float)):
            filtered_by_date.append(d)
            continue

        age_seconds = now_ts - mt
        day = 24 * 3600
        keep = True

        if selected_date == "Last 24 hours":
            keep = age_seconds <= day
        elif selected_date == "Last 7 days":
            keep = age_seconds <= 7 * day
        elif selected_date == "Last 30 days":
            keep = age_seconds <= 30 * day
        elif selected_date == "Older than 30 days":
            keep = age_seconds > 30 * day

        if keep:
            filtered_by_date.append(d)

    MB = 1024 * 1024
    filtered_by_size = []

    for d in filtered_by_date:
        size = d.get("size_bytes")
        try:
            size = int(size) if size is not None else 0
        except Exception:
            size = 0

        keep = True
        if selected_size == "< 1 MB":
            keep = size < 1 * MB
        elif selected_size == "1–10 MB":
            keep = (size >= 1 * MB) and (size <= 10 * MB)
        elif selected_size == "> 10 MB":
            keep = size > 10 * MB

        if keep:
            filtered_by_size.append(d)

    final_list = []
    st = (selected_tag or "").strip()
    st_lower = st.lower()

    for d in filtered_by_size:
        tags = [t.strip() for t in d.get("tags", []) if t]
        if not st or st == "All tags":
            final_list.append(d)
        else:
            tag_lowers = [t.lower() for t in tags]
            if st_lower in tag_lowers:
                final_list.append(d)

    filtered_data = final_list

    if filtered_data:
        show_notification(f"✅ Filter → {len(filtered_data)} files", "lightgreen")
    else:
        show_notification("⚠ Filter matched no files", "orange")


# ------------------ Normalization & scoring helpers ------------------
def normalize_results(results, data):
    normalized = []
    for r in results:
        try:
            idx = r.get("index")
            text = r.get("text", "")
            filename = r.get("filename", "")
            path = r.get("path", "")
            raw_score = r.get("score", 0)

            try:
                score = float(raw_score) if raw_score is not None else 0.0
            except Exception:
                score = 0.0

            if idx is not None and (not filename or not path):
                if 0 <= idx < len(data):
                    d = data[idx]
                    filename = filename or d.get("filename")
                    path = path or d.get("path")
                    text = text or d.get("text")

            normalized.append(
                {
                    "filename": filename or "",
                    "path": path or "",
                    "text": text or "",
                    "score": score,
                }
            )
        except Exception:
            continue
    return normalized


def normalize_score_list(lst, boost=50):
    if not lst:
        return lst
    for x in lst:
        if "score" not in x or x["score"] is None:
            x["score"] = 0.0
        else:
            try:
                x["score"] = float(x["score"])
            except Exception:
                x["score"] = 0.0
    max_score = max([x.get("score", 0.0) for x in lst])
    if max_score == 0:
        for x in lst:
            x["score"] = x.get("score", 0.0) + boost * 0.5
        return lst
    for x in lst:
        x["score"] = (x.get("score", 0.0) / max_score) * boost
    return lst


def find_exact_matches(data, query):
    query_lower = query.lower().strip()
    if not query_lower:
        return []
    exact = []
    for item in data:
        text_lower = re.sub(r"\s+", " ", (item.get("text") or "").lower())
        try:
            if re.search(r"\b" + re.escape(query_lower) + r"\b", text_lower):
                item_copy = item.copy()
                item_copy["score"] = 100.0
                exact.append(item_copy)
        except re.error:
            if query_lower in text_lower:
                item_copy = item.copy()
                item_copy["score"] = 100.0
                exact.append(item_copy)
    return exact


def merge_results(fuzzy, tfidf, embed, data, query=""):
    WEIGHTS = {"fuzzy": 3.0, "tfidf": 4.0, "embed": 2.0}
    partial_boost = 20.0

    exact = find_exact_matches(data, query)
    fuzzy = normalize_score_list(fuzzy, boost=40)
    tfidf = normalize_score_list(tfidf, boost=50)
    embed = normalize_score_list(embed, boost=50)

    combined = {}

    for item in exact:
        fn = item.get("filename", "")
        if not fn:
            continue
        combined[fn] = {
            "filename": fn,
            "path": item.get("path", ""),
            "text": item.get("text", ""),
            "score": item.get("score", 100.0),
        }

    for lst, key in zip([fuzzy, tfidf, embed], ["fuzzy", "tfidf", "embed"]):
        for item in lst:
            fn = item.get("filename", "")
            if not fn:
                continue
            sc = item.get("score", 0.0) * WEIGHTS.get(key, 1.0)
            if (
                query.strip().lower()
                and query.strip().lower() in (item.get("text", "") or "").lower()
            ):
                sc += partial_boost
            if fn not in combined:
                combined[fn] = {
                    "filename": fn,
                    "path": item.get("path", ""),
                    "text": item.get("text", ""),
                    "score": sc,
                }
            else:
                combined[fn]["score"] += sc

    combined_list = list(combined.values())
    q = (query or "").strip().lower()

    for item in combined_list:
        fn = item.get("filename", "") or ""
        txt = (item.get("text", "") or "")
        fn_lower = fn.lower()
        name_no_ext = os.path.splitext(fn_lower)[0]
        txt_lower = txt.lower()

        boost = 0.0
        match_tags = []

        if q:
            if name_no_ext == q:
                boost += 1000.0
                match_tags.append("Exact filename")
            elif q in name_no_ext:
                boost += 800.0
                match_tags.append("Filename contains")

            if q in txt_lower:
                boost += 400.0
                match_tags.append("Text contains")

        if not match_tags:
            match_tags.append("Fuzzy / semantic match")

        base = float(item.get("score", 0.0))
        item["base_score"] = base
        item["score"] = base + boost
        item["match_info"] = ", ".join(match_tags)

    combined_list.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return combined_list[:5]


# ------------------ Search backends ------------------
def search_fuzzy_backend(query, data, top_n=5):
    res = []
    q = clean_text(query)
    for item in data:
        t = clean_text(item.get("text", ""))
        sc = FUZZ_RATIO(q, t)
        res.append(
            {
                "filename": item.get("filename", ""),
                "path": item.get("path", ""),
                "text": item.get("text", ""),
                "score": sc,
            }
        )
    res = sorted(res, key=lambda x: x["score"], reverse=True)[:top_n]
    return res


def search_tfidf_backend(query, data, top_n=5):
    try:
        raw = tfidf_engine.query(query, top_n)
        return normalize_results(raw, data)
    except Exception as e:
        print("TFIDF backend error:", e)
        return []


def search_embed_backend(query, data, top_n=5):
    q_words = set(clean_text(query).split())
    res = []
    for i, item in enumerate(data):
        words = set(clean_text(item.get("text", "")).split())
        common = len(q_words & words)
        res.append(
            {
                "index": i,
                "filename": item.get("filename", ""),
                "path": item.get("path", ""),
                "text": item.get("text", ""),
                "score": float(common),
            }
        )
    res = sorted(res, key=lambda x: x["score"], reverse=True)[:top_n]
    return normalize_results(res, data)


# ------------------ Share helper ------------------
def share_item_popup(item):
    global root
    if root is None:
        return

    path = item.get("path", "") or ""
    filename = item.get("filename", "") or ""
    text = item.get("text", "") or ""

    win = ctk.CTkToplevel(root)
    win.title(f"Share - {filename}")
    win.geometry("440x260")
    win.resizable(False, False)
    win.attributes("-topmost", True)

    try:
        root.update_idletasks()
        x = root.winfo_x() + (root.winfo_width() // 2) - 220
        y = root.winfo_y() + (root.winfo_height() // 2) - 130
        win.geometry(f"+{x}+{y}")
    except Exception:
        pass

    frame = ctk.CTkFrame(win, corner_radius=10)
    frame.pack(expand=True, fill="both", padx=10, pady=10)

    title_lbl = ctk.CTkLabel(frame, text="Share this result", font=("Segoe UI Semibold", 15))
    title_lbl.pack(pady=(10, 4))

    info_lbl = ctk.CTkLabel(
        frame,
        text="Choose how you want to share:",
        font=("Segoe UI", 11),
        text_color=("gray20", "gray80"),
    )
    info_lbl.pack(pady=(0, 10))

    def copy_text(value, msg):
        try:
            root.clipboard_clear()
            root.clipboard_append(value)
            show_notification(msg, "lightgreen")
        except Exception:
            show_notification("⚠ Unable to copy to clipboard", "orange")

    btn_file = ctk.CTkButton(
        frame,
        text="Copy file (for WhatsApp, Telegram, etc.)",
        width=260,
        command=lambda: copy_file_to_clipboard(path),
    )
    btn_file.pack(pady=4)

    btn1 = ctk.CTkButton(
        frame,
        text="Copy file path",
        width=220,
        command=lambda: copy_text(path, "📋 File path copied"),
    )
    btn1.pack(pady=4)

    btn2 = ctk.CTkButton(
        frame,
        text="Copy filename",
        width=220,
        command=lambda: copy_text(filename, "📋 Filename copied"),
    )
    btn2.pack(pady=4)

    btn3 = ctk.CTkButton(
        frame,
        text="Copy extracted text",
        width=220,
        command=lambda: copy_text(text, "📋 Extracted text copied"),
    )
    btn3.pack(pady=4)

    close_btn = ctk.CTkButton(
        frame,
        text="Close",
        width=100,
        fg_color="transparent",
        border_width=1,
        command=win.destroy,
    )
    close_btn.pack(pady=(10, 8))


# ------------------ Result preview popup ------------------
def show_item_preview(item):
    global root
    if root is None:
        return

    path = item.get("path", "") or ""
    filename = item.get("filename", "") or ""
    ext = os.path.splitext(filename)[1].lower()
    text = item.get("text", "") or ""

    win = ctk.CTkToplevel(root)
    win.title(f"Preview - {filename}")
    win.geometry("900x600")
    win.resizable(True, True)
    win.attributes("-topmost", True)

    try:
        root.update_idletasks()
        x = root.winfo_x() + (root.winfo_width() // 2) - 450
        y = root.winfo_y() + (root.winfo_height() // 2) - 300
        win.geometry(f"+{x}+{y}")
    except Exception:
        pass

    win.grid_columnconfigure(0, weight=1)
    win.grid_rowconfigure(1, weight=1)

    header = ctk.CTkFrame(win)
    header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
    header.grid_columnconfigure(0, weight=1)

    title_lbl = ctk.CTkLabel(header, text=filename, font=("Segoe UI Semibold", 16))
    title_lbl.grid(row=0, column=0, padx=5, pady=(0, 2), sticky="w")

    path_lbl = ctk.CTkLabel(
        header,
        text=path,
        font=("Segoe UI", 10),
        text_color=("gray25", "gray70"),
    )
    path_lbl.grid(row=1, column=0, padx=5, pady=(0, 4), sticky="w")

    score_line = (
        f"Total: {item.get('score', 0.0):.3f} | "
        f"Fuzzy: {item.get('fuzzy_score', 0.0):.1f} • "
        f"TF-IDF: {item.get('tfidf_score', 0.0):.1f} • "
        f"Embed: {item.get('embed_score', 0.0):.1f}"
    )

    info_lbl = ctk.CTkLabel(
        header,
        text=f"{score_line}\nMatch: {item.get('match_info', 'Fuzzy / semantic match')}",
        font=("Segoe UI", 10),
        text_color=("gray25", "gray80"),
        justify="left",
    )
    info_lbl.grid(row=0, column=1, rowspan=2, padx=5, pady=2, sticky="e")

    open_btn = ctk.CTkButton(
        header, text="Open file", width=90, command=lambda p=path: open_file(p)
    )
    open_btn.grid(row=0, column=2, padx=(10, 5), pady=(4, 2), sticky="e")

    open_loc_btn = ctk.CTkButton(
        header,
        text="Open location",
        width=110,
        command=lambda p=path: open_location(p),
    )
    open_loc_btn.grid(row=1, column=2, padx=(10, 5), pady=(0, 4), sticky="e")

    content = ctk.CTkFrame(win)
    content.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
    content.grid_rowconfigure(0, weight=1)
    content.grid_columnconfigure(0, weight=1)

    if ext in [".jpg", ".jpeg", ".png"]:
        try:
            img = Image.open(path)
            max_w, max_h = 820, 460
            img.thumbnail((max_w, max_h))
            img_tk = ImageTk.PhotoImage(img)

            img_label = ctk.CTkLabel(content, image=img_tk, text="")
            img_label.image = img_tk
            img_label.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        except Exception as e:
            err_lbl = ctk.CTkLabel(
                content,
                text=f"Unable to load image preview:\n{e}",
                font=("Segoe UI", 11),
                text_color="red",
            )
            err_lbl.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
    else:
        textbox = ctk.CTkTextbox(content, wrap="word")
        textbox.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        if text:
            textbox.insert("1.0", text)
        else:
            textbox.insert("1.0", "No extracted text available for this file.")
        textbox.configure(state="disabled")


def clear_frame_children(frame):
    for w in frame.winfo_children():
        try:
            w.destroy()
        except Exception:
            pass


def display_results(results, query):
    clear_frame_children(result_frame)

    if not results:
        lbl = ctk.CTkLabel(
            result_frame,
            text="No results found. Try a different keyword.",
            font=("Segoe UI", 12),
            text_color=("gray20", "gray80"),
        )
        lbl.pack(pady=15)
        show_notification("⚠ No results found for this query", "orange")
        return

    q_lower = (query or "").lower().strip()

    for item in results:
        if "tags" not in item or not isinstance(item["tags"], list):
            item["tags"] = []

        card = ctk.CTkFrame(result_frame, corner_radius=12)
        card.pack(padx=12, pady=8, fill="x")

        ext = os.path.splitext(item["filename"])[1].lower()

        left_container = ctk.CTkFrame(card, fg_color="transparent")
        left_container.pack(side="left", padx=10, pady=10)

        right_container = ctk.CTkFrame(card, fg_color="transparent")
        right_container.pack(
            side="left", fill="both", expand=True, padx=(0, 10), pady=10
        )

        if ext in [".jpg", ".jpeg", ".png"]:
            img_thumb = get_thumbnail_image(item["path"])
            if img_thumb:
                img_label = ctk.CTkLabel(
                    left_container, image=img_thumb, text=""
                )
                img_label.image = img_thumb
                img_label.pack()
                img_label.bind(
                    "<Button-1>", lambda e, p=item["path"]: open_file(p)
                )
        else:
            if ext == ".pdf":
                doc_icon = "📄"
            elif ext in [".doc", ".docx", ".txt"]:
                doc_icon = "📝"
            else:
                doc_icon = "📁"

            doc_label = ctk.CTkLabel(
                left_container, text=doc_icon, font=("Segoe UI Emoji", 30)
            )
            doc_label.pack()
            doc_label.bind(
                "<Button-1>", lambda e, p=item["path"]: open_file(p)
            )

        title_label = ctk.CTkLabel(
            right_container,
            text=item["filename"],
            font=("Segoe UI Semibold", 14),
            anchor="w",
        )
        title_label.pack(fill="x")

        total_score = float(item.get("score", 0.0))
        fuzzy_score = float(item.get("fuzzy_score", 0.0))
        tfidf_score = float(item.get("tfidf_score", 0.0))
        embed_score = float(item.get("embed_score", 0.0))

        score_text = (
            f"Total: {total_score:.3f}  |  "
            f"Fuzzy: {fuzzy_score:.1f}  •  "
            f"TF-IDF: {tfidf_score:.1f}  •  "
            f"Embed: {embed_score:.1f}"
        )

        score_label = ctk.CTkLabel(
            right_container,
            text=score_text,
            font=("Segoe UI", 11),
            text_color=("gray25", "gray80"),
        )
        score_label.pack(anchor="w", pady=(2, 2))

        match_info = item.get("match_info", "Fuzzy / semantic match")
        match_label = ctk.CTkLabel(
            right_container,
            text=f"Match: {match_info}",
            font=("Segoe UI", 10),
            text_color=("gray30", "gray70"),
        )
        match_label.pack(anchor="w", pady=(0, 4))

        full_text = item.get("text", "") or ""
        preview = full_text[:320]

        if q_lower and q_lower in preview.lower():
            try:
                lower_preview = preview.lower()
                start = lower_preview.find(q_lower)
                end = start + len(q_lower)
                if start != -1:
                    preview = (
                        preview[:start]
                        + "["
                        + preview[start:end]
                        + "]"
                        + preview[end:]
                    )
            except Exception:
                pass

        body_label = ctk.CTkLabel(
            right_container,
            text="Preview: " + preview + ("..." if preview else ""),
            justify="left",
            wraplength=550,
            font=("Segoe UI", 11),
        )
        body_label.pack(anchor="w")

        location = item.get("path", "") or ""
        location_label = ctk.CTkLabel(
            right_container,
            text=f"Location: {location}",
            font=("Segoe UI", 9),
            text_color=("gray30", "gray60"),
            wraplength=550,
            justify="left",
        )
        location_label.pack(anchor="w", pady=(4, 2))

        tags_text = ", ".join(item.get("tags", [])) if item.get("tags") else "None"
        tags_label = ctk.CTkLabel(
            right_container,
            text=f"Tags: {tags_text}",
            font=("Segoe UI", 9),
            text_color=("gray35", "gray65"),
        )
        tags_label.pack(anchor="w", pady=(0, 2))

        btn_frame = ctk.CTkFrame(right_container, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(4, 0))

        tags_btn = ctk.CTkButton(
            btn_frame,
            text="Tags",
            width=60,
            command=lambda it=item: open_tag_manager(it),
        )
        tags_btn.pack(side="right", padx=(4, 0))

        share_btn = ctk.CTkButton(
            btn_frame,
            text="Share",
            width=80,
            command=lambda it=item: share_item_popup(it),
        )
        share_btn.pack(side="right", padx=(4, 0))

        preview_btn = ctk.CTkButton(
            btn_frame,
            text="Preview",
            width=80,
            command=lambda it=item: show_item_preview(it),
        )
        preview_btn.pack(side="right", padx=(4, 0))

        open_loc_btn = ctk.CTkButton(
            btn_frame,
            text="Open location",
            width=110,
            command=lambda p=item["path"]: open_location(p),
        )
        open_loc_btn.pack(side="right", padx=(4, 0))

        open_file_btn = ctk.CTkButton(
            btn_frame,
            text="Open file",
            width=90,
            command=lambda p=item["path"]: open_file(p),
        )
        open_file_btn.pack(side="right", padx=(4, 0))


# ------------------ Search trigger ------------------
def search_query():
    global filtered_data

    query = search_entry.get().strip()
    if not query:
        show_notification("⚠ Please enter a search query", "orange")
        return

    if not filtered_data:
        update_filtered_data()

    if not filtered_data:
        show_notification("⚠ No data to search! Load a folder first.", "orange")
        return

    if progress_label is not None:

        def _set_search():
            progress_label.configure(text=f"Searching: {query}")

        root.after(0, _set_search)

    show_notification("🔎 Searching in your screenshots & docs...", "lightblue")

    try:
        fuzzy_raw = search_fuzzy_backend(query, filtered_data, 10)
    except Exception:
        fuzzy_raw = []

    try:
        tfidf_raw = search_tfidf_backend(query, filtered_data, 10)
    except Exception:
        tfidf_raw = []

    try:
        embed_raw = search_embed_backend(query, filtered_data, 10)
    except Exception:
        embed_raw = []

    fuzzy_map = {i.get("filename", ""): float(i.get("score", 0.0)) for i in fuzzy_raw}
    tfidf_map = {i.get("filename", ""): float(i.get("score", 0.0)) for i in tfidf_raw}
    embed_map = {i.get("filename", ""): float(i.get("score", 0.0)) for i in embed_raw}

    combined = merge_results(fuzzy_raw, tfidf_raw, embed_raw, filtered_data, query)

    try:
        combined = apply_feedback(combined)
    except Exception:
        pass

    for item in combined:
        fn = item.get("filename", "")
        item["fuzzy_score"] = fuzzy_map.get(fn, 0.0)
        item["tfidf_score"] = tfidf_map.get(fn, 0.0)
        item["embed_score"] = embed_map.get(fn, 0.0)
        if "tags" not in item or not isinstance(item["tags"], list):
            item["tags"] = []

    save_recent_search_with_results(query, combined)

    display_results(combined, query)
    show_notification("✅ Search complete", "lightgreen")

    if progress_label is not None:

        def _done():
            progress_label.configure(text="Search complete")

        root.after(0, _done)

    if progress_bar is not None and progress_var is not None:
        progress_var.set(100)
        progress_bar.set(1.0)


def threaded_search():
    search_query()


def on_recent_search_select(choice):
    if not choice:
        return

    try:
        search_entry.delete(0, ctk.END)
        search_entry.insert(0, choice)
    except Exception:
        pass

    cached = load_recent_results_for_query(choice)
    if cached:
        show_notification(f"📂 Showing recent results for: {choice}", "lightblue")
        display_results(cached, choice)
        if progress_label is not None:
            progress_label.configure(text=f"Showing cached results for: {choice}")
    else:
        threaded_search()


# ------------------ Duplicate Finder Logic ------------------
def compute_duplicate_groups(data_list, sim_threshold=0.95):
    """
    Similar-content based duplicate finder.
    Uses Jaccard similarity on cleaned text.
    sim_threshold ~ 0.95 means 95%+ similar content treated as duplicate.
    """
    n = len(data_list)
    if n < 2:
        return []

    cleaned = []
    for d in data_list:
        txt = clean_text(d.get("text", "") or "")
        words = set(txt.split()) if txt else set()
        size = d.get("size_bytes") or 0
        cleaned.append({"words": words, "size": int(size)})

    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        wi = cleaned[i]["words"]
        if not wi:
            continue
        for j in range(i + 1, n):
            wj = cleaned[j]["words"]
            if not wj:
                continue

            inter = len(wi & wj)
            uni = len(wi | wj)
            if uni == 0:
                sim = 0.0
            else:
                sim = inter / uni

            if sim < 1.0:
                if inter < max(1, int(0.3 * min(len(wi), len(wj)))):
                    continue

            if sim >= sim_threshold:
                union(i, j)

    groups_map = {}
    for i in range(n):
        root_id = find(i)
        groups_map.setdefault(root_id, []).append(i)

    groups = []
    for root_id, idx_list in groups_map.items():
        if len(idx_list) >= 2:
            group_items = [data_list[idx] for idx in idx_list]
            groups.append(group_items)

    return groups


def show_duplicate_window(groups):
    global root
    if root is None:
        return

    if not groups:
        show_notification("✅ No strong duplicates / near-duplicates found", "lightgreen")
        return

    win = ctk.CTkToplevel(root)
    win.title("Duplicate Finder")
    win.geometry("900x600")
    win.resizable(True, True)
    win.attributes("-topmost", True)

    try:
        root.update_idletasks()
        x = root.winfo_x() + (root.winfo_width() // 2) - 450
        y = root.winfo_y() + (root.winfo_height() // 2) - 300
        win.geometry(f"+{x}+{y}")
    except Exception:
        pass

    win.grid_rowconfigure(0, weight=1)
    win.grid_columnconfigure(0, weight=1)

    frame = ctk.CTkScrollableFrame(win, corner_radius=10)
    frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
    frame.grid_columnconfigure(0, weight=1)

    header_lbl = ctk.CTkLabel(
        frame,
        text=f"Found {len(groups)} duplicate groups",
        font=("Segoe UI Semibold", 14),
    )
    header_lbl.grid(row=0, column=0, padx=8, pady=(4, 8), sticky="w")

    row_idx = 1
    for gi, group in enumerate(groups, start=1):
        group_frame = ctk.CTkFrame(frame, corner_radius=10)
        group_frame.grid(row=row_idx, column=0, padx=4, pady=6, sticky="ew")
        group_frame.grid_columnconfigure(0, weight=1)
        row_idx += 1

        title = ctk.CTkLabel(
            group_frame,
            text=f"Group {gi} (duplicates: {len(group)})",
            font=("Segoe UI Semibold", 13),
        )
        title.grid(row=0, column=0, padx=8, pady=(6, 4), sticky="w")

        for fi, item in enumerate(group, start=1):
            row = fi
            filename = item.get("filename", "") or "(no name)"
            path = item.get("path", "") or ""
            size = item.get("size_bytes", 0) or 0

            line = f"{fi}. {filename}  ({size} bytes)\n{path}"

            file_lbl = ctk.CTkLabel(
                group_frame,
                text=line,
                font=("Segoe UI", 10),
                justify="left",
                wraplength=600,
            )
            file_lbl.grid(row=row, column=0, padx=8, pady=(2, 2), sticky="w")

            btn_panel = ctk.CTkFrame(group_frame, fg_color="transparent")
            btn_panel.grid(row=row, column=1, padx=4, pady=(2, 2), sticky="e")

            open_btn = ctk.CTkButton(
                btn_panel,
                text="Open",
                width=70,
                command=lambda p=path: open_file(p),
            )
            open_btn.pack(side="left", padx=(0, 4))

            open_loc_btn = ctk.CTkButton(
                btn_panel,
                text="Location",
                width=80,
                command=lambda p=path: open_location(p),
            )
            open_loc_btn.pack(side="left", padx=(0, 4))

    footer = ctk.CTkLabel(
        frame,
        text=(
            "Note: Duplicates are detected based on high content similarity "
            "(text Jaccard similarity ≥ 95%)."
        ),
        font=("Segoe UI", 9),
        text_color=("gray25", "gray70"),
        wraplength=820,
        justify="left",
    )
    footer.grid(row=row_idx, column=0, padx=8, pady=(8, 6), sticky="w")


def run_duplicate_finder():
    if not DATA:
        show_notification("⚠ Load a folder first before finding duplicates", "orange")
        return

    base_list = filtered_data if filtered_data else DATA

    try:
        q = (search_entry.get() or "").strip().lower()
    except Exception:
        q = ""

    if q:
        narrowed = []
        for d in base_list:
            fn = (d.get("filename", "") or "").lower()
            txt = clean_text(d.get("text", "") or "")
            if q in fn or q in txt:
                narrowed.append(d)
        base_list = narrowed

    if not base_list:
        show_notification(
            "⚠ Current search/filters ke hisaab se koi file nahi mili", "orange"
        )
        return

    show_notification(
        f"🔍 Finding duplicates in {len(base_list)} matching files...", "lightblue"
    )

    def worker():
        try:
            groups = compute_duplicate_groups(base_list, sim_threshold=0.95)
        except Exception as e:
            print("Duplicate finder error:", e)
            traceback.print_exc()

            def _err():
                show_notification(
                    "❌ Error while finding duplicates (see console)", "red"
                )

            root.after(0, _err)
            return

        def _ui():
            if groups:
                show_duplicate_window(groups)
                show_notification(
                    f"✅ Found {len(groups)} duplicate groups", "lightgreen"
                )
            else:
                show_duplicate_window([])

        root.after(0, _ui)

    threading.Thread(target=worker, daemon=True).start()


# ------------------ Folder loading ------------------
def load_folder(folder=None, lang="eng"):
    global DATA

    folder = folder or (folder_entry.get().strip() if folder_entry is not None else "")
    if not folder:
        show_notification("⚠ Please enter a folder path", "orange")
        return
    if not os.path.exists(folder):
        show_notification("❌ Invalid folder path!", "red")
        return

    show_notification(f"⏳ Loading folder: {folder}", "lightblue")

    if progress_label is not None and progress_bar is not None:
        progress_var.set(0)
        progress_bar.set(0.0)

        def _initial():
            progress_label.configure(text="Processing files...")

        root.after(0, _initial)

    def progress_callback(idx, total):
        if progress_var is None or progress_label is None or progress_bar is None:
            return

        def _update():
            try:
                value = int((idx / max(total, 1)) * 100)
                progress_var.set(value)
                progress_bar.set(value / 100.0)
                progress_label.configure(text=f"Processing {idx}/{total} files...")
            except Exception:
                pass

        root.after(0, _update)

    def process_folder():
        json_path = get_folder_json_path(folder)
        new_data = []
        loaded_from_cache = False

        try:
            if os.path.exists(json_path):
                new_data = load_data_json(json_path)
                loaded_from_cache = True
            else:
                try:
                    new_data = extract_text_from_folder(folder, lang, progress_callback)
                except TypeError:
                    new_data = extract_text_from_folder(folder, lang)

                for item in new_data:
                    p = item.get("path", "")
                    if os.path.exists(p):
                        try:
                            item["created_time"] = os.path.getctime(p)
                            item["modified_time"] = os.path.getmtime(p)
                            item["size_bytes"] = os.path.getsize(p)
                        except Exception:
                            item["created_time"] = None
                            item["modified_time"] = None
                            item["size_bytes"] = None
                    else:
                        item["created_time"] = None
                        item["modified_time"] = None
                        item["size_bytes"] = None

                    if "tags" not in item or not isinstance(item["tags"], list):
                        item["tags"] = []

                save_data_json(new_data, json_path)
        except Exception as e:
            print("Error during folder processing:", e)
            traceback.print_exc()
            show_notification("❌ Error processing folder (see console)", "red")
            return

        DATA.clear()
        DATA.extend(new_data)
        ensure_tags_field()
        fit_tfidf_engine()

        def _final_ui():
            if loaded_from_cache:
                msg = f"📂 Loaded cached data ({len(DATA)} files)"
            else:
                msg = f"✅ Folder processed ({len(DATA)} files)"
            show_notification(msg, "lightgreen")

            try:
                folder_entry.delete(0, ctk.END)
                folder_entry.insert(0, folder)
                folder_dropdown.set_completion_list(load_used_folders())
                save_last_used_folder(folder)
                save_used_folder(folder)
            except Exception:
                pass

            update_filtered_data()
            refresh_tag_filter_dropdown()

            if progress_label is not None:
                progress_label.configure(text="Ready")
            if progress_bar is not None and progress_var is not None:
                progress_var.set(100)
                progress_bar.set(1.0)

        root.after(0, _final_ui)

    threading.Thread(target=process_folder, daemon=True).start()


def on_folder_select(choice):
    folder_entry.delete(0, ctk.END)
    folder_entry.insert(0, choice)
    load_folder(choice)


# ------------------ Main App UI (Dashboard after login) ------------------
def open_main_app():
    """
    Existing global `root` window ke andar dashboard UI load karega.
    Login screen ke widgets pehle destroy honge.
    """
    # global (
    #     root,
    #     folder_entry,
    #     search_entry,
    #     result_frame,
    #     folder_dropdown,
    #     progress_var,
    #     progress_label,
    #     progress_bar,
    #     ext_dropdown,
    #     date_filter_dropdown,
    #     size_filter_dropdown,
    #     filtered_data,
    #     recent_dropdown,
    #     tag_filter_dropdown,
    #     CURRENT_USER,
    # )

    # python me above wali line allowed nahi, isliye normal tarike se likhte hain:
    global root, folder_entry, search_entry, result_frame, folder_dropdown
    global progress_var, progress_label, progress_bar
    global ext_dropdown, date_filter_dropdown, size_filter_dropdown
    global filtered_data, recent_dropdown, tag_filter_dropdown
    global CURRENT_USER

    # purana login UI hata do
    for w in root.winfo_children():
        w.destroy()

    root.title("SmartShotApp - Visual Memory Search")
    root.geometry("1250x780")
    root.minsize(1080, 660)

    root.grid_columnconfigure(0, weight=0)
    root.grid_columnconfigure(1, weight=1)
    root.grid_rowconfigure(0, weight=1)

    SIDEBAR_WIDTH = 320

    # ---------- SIDEBAR ----------
    sidebar = ctk.CTkFrame(root, width=SIDEBAR_WIDTH, corner_radius=0)
    sidebar.grid(row=0, column=0, sticky="nsw")

    sidebar_content = ctk.CTkScrollableFrame(
        sidebar,
        corner_radius=0,
        fg_color="transparent",
        width=SIDEBAR_WIDTH,
    )
    sidebar_content.pack(fill="both", expand=True)
    sidebar_content.grid_columnconfigure(0, weight=1)
    sidebar_content.grid_rowconfigure(99, weight=1)

    # Branding
    brand_frame = ctk.CTkFrame(sidebar_content, fg_color="transparent")
    brand_frame.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 6))

    app_icon = ctk.CTkLabel(brand_frame, text="🧠", font=("Segoe UI Emoji", 30))
    app_icon.grid(row=0, column=0, padx=(0, 8))

    app_title = ctk.CTkLabel(
        brand_frame, text="SmartShotApp", font=("Segoe UI Semibold", 20)
    )
    app_title.grid(row=0, column=1, sticky="w")

    app_tagline = ctk.CTkLabel(
        sidebar_content,
        text="Your personal visual memory search engine.",
        font=("Segoe UI", 10),
        text_color=("gray20", "gray70"),
        wraplength=SIDEBAR_WIDTH - 40,
        justify="left",
    )
    app_tagline.grid(row=1, column=0, padx=18, pady=(0, 10), sticky="w")

    # LIBRARY
    sec_lib = ctk.CTkLabel(
        sidebar_content,
        text="LIBRARY",
        font=("Segoe UI Semibold", 11),
        text_color=("gray25", "gray60"),
    )
    sec_lib.grid(row=2, column=0, padx=18, pady=(6, 2), sticky="w")

    folder_card = ctk.CTkFrame(sidebar_content, corner_radius=14)
    folder_card.grid(row=3, column=0, padx=14, pady=(0, 10), sticky="ew")
    folder_card.grid_columnconfigure(0, weight=1)

    folder_entry = ctk.CTkEntry(
        folder_card,
        placeholder_text="Paste / type folder path...",
        height=32,
        width=SIDEBAR_WIDTH - 60,
    )
    folder_entry.grid(row=0, column=0, padx=10, pady=(10, 4), sticky="ew")

    folder_dropdown = AutocompleteCombobox(folder_card, width=SIDEBAR_WIDTH - 60)
    folder_dropdown.grid(row=1, column=0, padx=10, pady=(0, 6), sticky="ew")
    folder_dropdown.set_completion_list(load_used_folders())
    folder_dropdown.configure(command=on_folder_select)

    load_btn = ctk.CTkButton(
        folder_card,
        text="Load Folder",
        height=32,
        width=SIDEBAR_WIDTH - 60,
        command=lambda: load_folder(),
    )
    load_btn.grid(row=2, column=0, padx=10, pady=(4, 10), sticky="ew")

    # SEARCH
    sec_search = ctk.CTkLabel(
        sidebar_content,
        text="SEARCH",
        font=("Segoe UI Semibold", 11),
        text_color=("gray25", "gray60"),
    )
    sec_search.grid(row=4, column=0, padx=18, pady=(4, 2), sticky="w")

    search_card = ctk.CTkFrame(sidebar_content, corner_radius=14)
    search_card.grid(row=5, column=0, padx=14, pady=(0, 10), sticky="ew")
    search_card.grid_columnconfigure(0, weight=1)
    search_card.grid_columnconfigure(1, weight=0)

    search_inner = ctk.CTkFrame(search_card, fg_color="transparent")
    search_inner.grid(
        row=0, column=0, columnspan=2, padx=10, pady=(8, 2), sticky="ew"
    )
    search_inner.grid_columnconfigure(1, weight=1)

    search_icon = ctk.CTkLabel(search_inner, text="🔎", font=("Segoe UI Emoji", 18))
    search_icon.grid(row=0, column=0, padx=(0, 6))

    search_entry = ctk.CTkEntry(
        search_inner,
        placeholder_text="Search screenshots / documents...",
        height=32,
        width=SIDEBAR_WIDTH - 90,
    )
    search_entry.grid(row=0, column=1, sticky="ew")

    filter_row = ctk.CTkFrame(search_card, fg_color="transparent")
    filter_row.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(2, 8))
    filter_row.grid_columnconfigure(0, weight=1)
    filter_row.grid_columnconfigure(1, weight=1)

    ext_dropdown = ctk.CTkComboBox(
        filter_row,
        values=EXT_OPTIONS,
        state="readonly",
        width=110,
        height=30,
    )
    ext_dropdown.set("All")
    ext_dropdown.grid(row=0, column=0, padx=(0, 6), sticky="w")
    ext_dropdown.configure(command=lambda _c: update_filtered_data())

    search_btn = ctk.CTkButton(
        filter_row, text="Search", height=30, width=110, command=threaded_search
    )
    search_btn.grid(row=0, column=1, sticky="e")

    # ADVANCED FILTERS
    sec_filters = ctk.CTkLabel(
        sidebar_content,
        text="ADVANCED FILTERS",
        font=("Segoe UI Semibold", 11),
        text_color=("gray25", "gray60"),
    )
    sec_filters.grid(row=6, column=0, padx=18, pady=(4, 2), sticky="w")

    adv_card = ctk.CTkFrame(sidebar_content, corner_radius=14)
    adv_card.grid(row=7, column=0, padx=14, pady=(0, 8), sticky="ew")
    adv_card.grid_columnconfigure(0, weight=1)
    adv_card.grid_columnconfigure(1, weight=1)

    date_filter_dropdown = ctk.CTkComboBox(
        adv_card,
        values=DATE_FILTER_OPTIONS,
        state="readonly",
        width=130,
        height=30,
    )
    date_filter_dropdown.set("Any time")
    date_filter_dropdown.grid(
        row=0, column=0, padx=(10, 4), pady=(8, 4), sticky="w"
    )
    date_filter_dropdown.configure(command=lambda _c: update_filtered_data())

    size_filter_dropdown = ctk.CTkComboBox(
        adv_card,
        values=SIZE_FILTER_OPTIONS,
        state="readonly",
        width=130,
        height=30,
    )
    size_filter_dropdown.set("Any size")
    size_filter_dropdown.grid(
        row=0, column=1, padx=(4, 10), pady=(8, 4), sticky="e"
    )
    size_filter_dropdown.configure(command=lambda _c: update_filtered_data())

    tag_label = ctk.CTkLabel(
        adv_card,
        text="Tag filter",
        font=("Segoe UI", 10),
        text_color=("gray25", "gray70"),
    )
    tag_label.grid(row=1, column=0, columnspan=2, padx=10, pady=(2, 0), sticky="w")

    tag_filter_dropdown = ctk.CTkComboBox(
        adv_card,
        values=["All tags"],
        state="readonly",
        height=30,
        width=SIDEBAR_WIDTH - 60,
        command=lambda _c: update_filtered_data(),
    )
    tag_filter_dropdown.set("All tags")
    tag_filter_dropdown.grid(
        row=2, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="ew"
    )

    # TOOLS
    tools_label = ctk.CTkLabel(
        sidebar_content,
        text="TOOLS",
        font=("Segoe UI Semibold", 11),
        text_color=("gray25", "gray60"),
    )
    tools_label.grid(row=8, column=0, padx=18, pady=(4, 2), sticky="w")

    tools_card = ctk.CTkFrame(sidebar_content, corner_radius=14)
    tools_card.grid(row=9, column=0, padx=14, pady=(0, 8), sticky="ew")
    tools_card.grid_columnconfigure(0, weight=1)

    dup_btn = ctk.CTkButton(
        tools_card,
        text="🗂  Find duplicates",
        height=30,
        width=SIDEBAR_WIDTH - 60,
        command=run_duplicate_finder,
    )
    dup_btn.grid(row=0, column=0, padx=10, pady=(8, 4), sticky="ew")

    recent_label = ctk.CTkLabel(
        tools_card,
        text="Recent searches",
        font=("Segoe UI", 10),
        text_color=("gray25", "gray70"),
    )
    recent_label.grid(row=1, column=0, padx=10, pady=(6, 0), sticky="w")

    recent_dropdown = ctk.CTkComboBox(
        tools_card,
        values=load_recent_searches(),
        width=SIDEBAR_WIDTH - 60,
        state="readonly",
        height=30,
        command=on_recent_search_select,
    )
    recent_dropdown.set("")
    recent_dropdown.grid(row=2, column=0, padx=10, pady=(0, 8), sticky="ew")

    # APPEARANCE
    appearance_label = ctk.CTkLabel(
        sidebar_content,
        text="APPEARANCE",
        font=("Segoe UI Semibold", 11),
        text_color=("gray25", "gray60"),
    )
    appearance_label.grid(row=10, column=0, padx=18, pady=(4, 2), sticky="w")

    def change_theme(choice):
        ctk.set_appearance_mode(choice)

    theme_switch = ctk.CTkSegmentedButton(
        sidebar_content, values=["Light", "Dark", "System"], command=change_theme
    )
    theme_switch.set("System")
    theme_switch.grid(row=11, column=0, padx=18, pady=(0, 10), sticky="ew")

    exit_btn = ctk.CTkButton(
        sidebar_content,
        text="Quit SmartShotApp",
        fg_color="transparent",
        border_width=1,
        border_color="gray70",
        hover_color="#ff4444",
        text_color=("gray10", "gray90"),
        height=30,
        command=root.destroy,
    )
    exit_btn.grid(row=99, column=0, padx=18, pady=(0, 18), sticky="sew")

    # ---------- MAIN AREA ----------
    main = ctk.CTkFrame(root, corner_radius=0)
    main.grid(row=0, column=1, sticky="nsew")
    main.grid_rowconfigure(2, weight=1)
    main.grid_columnconfigure(0, weight=1)

    header = ctk.CTkFrame(main)
    header.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 10))
    # 0 = title/subtitle, 1 = BETA badge, 2 = profile corner
    header.grid_columnconfigure(0, weight=1)
    header.grid_columnconfigure(1, weight=0)
    header.grid_columnconfigure(2, weight=0)

    title_label = ctk.CTkLabel(
        header,
        text="Screenshot & Document Search",
        font=("Segoe UI Semibold", 22),
    )
    title_label.grid(row=0, column=0, padx=6, pady=(2, 0), sticky="w")

    subtitle_label = ctk.CTkLabel(
        header,
        text=(
            "Search your visual memory using OCR, fuzzy search, "
            "TF-IDF, tags & duplicate detection."
        ),
        font=("Segoe UI", 11),
        text_color=("gray25", "gray70"),
    )
    subtitle_label.grid(row=1, column=0, padx=6, pady=(0, 6), sticky="w")

    badge = ctk.CTkLabel(
        header,
        text="BETA",
        font=("Segoe UI Semibold", 10),
        text_color="white",
        fg_color="#3b82f6",
        corner_radius=999,
        padx=10,
        pady=3,
    )
    badge.grid(row=0, column=1, rowspan=2, padx=(0, 10), pady=4, sticky="e")

    # ---------- PROFILE CORNER ----------
    display_name = CURRENT_USER if CURRENT_USER else "Guest"

    profile_frame = ctk.CTkFrame(
        header,
        corner_radius=20,
        fg_color=("white", "#111827"),
    )
    profile_frame.grid(
        row=0,
        column=2,
        rowspan=2,
        padx=(0, 6),
        pady=4,
        sticky="e",
    )
    profile_frame.grid_columnconfigure(1, weight=1)

    avatar_text = display_name[:1].upper() if display_name else "U"
    avatar = ctk.CTkLabel(
        profile_frame,
        text=avatar_text,
        width=32,
        height=32,
        font=("Segoe UI Semibold", 14),
        text_color="white",
        fg_color="#3b82f6",
        corner_radius=999,
    )
    avatar.grid(row=0, column=0, rowspan=2, padx=(8, 6), pady=6)

    name_label = ctk.CTkLabel(
        profile_frame,
        text=display_name,
        font=("Segoe UI Semibold", 11),
        anchor="w",
    )
    name_label.grid(row=0, column=1, padx=(0, 8), pady=(4, 0), sticky="w")

    sub_label = ctk.CTkLabel(
        profile_frame,
        text="Signed in",
        font=("Segoe UI", 9),
        text_color=("gray40", "gray70"),
        anchor="w",
    )
    sub_label.grid(row=1, column=1, padx=(0, 8), pady=(0, 6), sticky="w")

    def logout():
        ans = messagebox.askyesno(
            "Log out",
            "Do you really want to log out?",
            parent=root,
        )
        if not ans:
            return

        globals()["CURRENT_USER"] = None
        show_login_screen()

    def open_profile_popup():
        popup = ctk.CTkToplevel(root)
        popup.title("Account")
        popup.geometry("220x150")
        popup.resizable(False, False)
        popup.attributes("-topmost", True)

        try:
            root.update_idletasks()
            x = root.winfo_x() + root.winfo_width() - 260
            y = root.winfo_y() + 80
            popup.geometry(f"+{x}+{y}")
        except Exception:
            pass

        popup.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            popup,
            text=f"Hi, {display_name}",
            font=("Segoe UI Semibold", 13),
        )
        title.grid(row=0, column=0, padx=12, pady=(12, 4), sticky="w")

        role_lbl = ctk.CTkLabel(
            popup,
            text="SmartShot user",
            font=("Segoe UI", 10),
            text_color=("gray40", "gray70"),
        )
        role_lbl.grid(row=1, column=0, padx=12, pady=(0, 10), sticky="w")

        logout_btn = ctk.CTkButton(
            popup,
            text="Log out",
            height=30,
            fg_color="#ef4444",
            hover_color="#dc2626",
            command=lambda: (popup.destroy(), logout()),
        )
        logout_btn.grid(row=2, column=0, padx=12, pady=(6, 10), sticky="ew")

        close_btn = ctk.CTkButton(
            popup,
            text="Close",
            height=28,
            fg_color="transparent",
            border_width=1,
            command=popup.destroy,
        )
        close_btn.grid(row=3, column=0, padx=12, pady=(0, 12), sticky="ew")

    profile_btn = ctk.CTkButton(
        profile_frame,
        text="⋮",
        width=26,
        height=26,
        fg_color="transparent",
        border_width=0,
        text_color=("gray40", "gray70"),
        hover_color=("#e5e7eb", "#374151"),
        command=open_profile_popup,
    )
    profile_btn.grid(row=0, column=2, rowspan=2, padx=(0, 8), pady=4, sticky="e")

    # ---------- STATUS + RESULTS ----------
    status_frame = ctk.CTkFrame(main, corner_radius=12)
    status_frame.grid(row=1, column=0, padx=18, pady=(0, 10), sticky="ew")
    status_frame.grid_columnconfigure(0, weight=1)
    status_frame.grid_columnconfigure(1, weight=3)

    progress_label = ctk.CTkLabel(
        status_frame,
        text="No folder loaded yet.",
        font=("Segoe UI", 11),
    )
    progress_label.grid(row=0, column=0, padx=10, pady=8, sticky="w")

    progress_var = tk.IntVar(value=0)
    progress_bar = ctk.CTkProgressBar(status_frame, height=8)
    progress_bar.grid(row=0, column=1, padx=(0, 10), pady=10, sticky="ew")
    progress_bar.set(0.0)

    result_frame_holder = ctk.CTkFrame(main, corner_radius=16)
    result_frame_holder.grid(row=2, column=0, padx=18, pady=(0, 18), sticky="nsew")
    result_frame_holder.grid_rowconfigure(0, weight=1)
    result_frame_holder.grid_columnconfigure(0, weight=1)

    result_frame = ctk.CTkScrollableFrame(
        result_frame_holder,
        corner_radius=14,
        label_text="Results",
        label_font=("Segoe UI Semibold", 12),
    )
    result_frame.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

    # globals update
    globals()["progress_label"] = progress_label
    globals()["progress_var"] = progress_var
    globals()["progress_bar"] = progress_bar
    globals()["result_frame"] = result_frame
    globals()["folder_entry"] = folder_entry
    globals()["folder_dropdown"] = folder_dropdown
    globals()["search_entry"] = search_entry
    globals()["ext_dropdown"] = ext_dropdown
    globals()["date_filter_dropdown"] = date_filter_dropdown
    globals()["size_filter_dropdown"] = size_filter_dropdown
    globals()["tag_filter_dropdown"] = tag_filter_dropdown
    globals()["recent_dropdown"] = recent_dropdown

    filtered_data = []

    show_notification("👋 Welcome to SmartShotApp (Desktop)", "lightgreen")
    refresh_recent_dropdown()
    refresh_tag_filter_dropdown()

    last_folder = load_last_used_folder()
    if last_folder:
        folder_entry.insert(0, last_folder)
        show_notification(f"📂 Last used folder: {last_folder}", "lightblue")


# ================================
#   REGISTER WINDOW (Sign Up)
# ================================
def open_register_window(parent):
    win = ctk.CTkToplevel(parent)
    win.title("Create Account - SmartShotApp")
    win.geometry("480x520")
    win.resizable(False, False)

    win.transient(parent)
    win.grab_set()
    win.focus_force()

    try:
        parent.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - 240
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 260
        win.geometry(f"+{x}+{y}")
    except Exception:
        pass

    win.grid_columnconfigure(0, weight=1)
    win.grid_rowconfigure(2, weight=1)

    title = ctk.CTkLabel(
        win,
        text="Create your SmartShotApp account",
        font=("Segoe UI Semibold", 18),
    )
    title.grid(row=0, column=0, padx=20, pady=(16, 4), sticky="w")

    subtitle = ctk.CTkLabel(
        win,
        text="Set a password and security question.",
        font=("Segoe UI", 11),
        text_color=("gray25", "gray75"),
    )
    subtitle.grid(row=1, column=0, padx=20, pady=(0, 8), sticky="w")

    form = ctk.CTkFrame(win, corner_radius=12)
    form.grid(row=2, column=0, padx=18, pady=(4, 16), sticky="nsew")
    form.grid_columnconfigure(0, weight=1)

    # Username
    user_label = ctk.CTkLabel(form, text="Username", font=("Segoe UI", 11))
    user_label.grid(row=0, column=0, padx=16, pady=(10, 2), sticky="w")

    user_entry = ctk.CTkEntry(form, placeholder_text="Enter a username", height=30)
    user_entry.grid(row=1, column=0, padx=16, pady=(0, 6), sticky="ew")

    # Password
    pass_label = ctk.CTkLabel(form, text="Password", font=("Segoe UI", 11))
    pass_label.grid(row=2, column=0, padx=16, pady=(4, 2), sticky="w")

    pass_entry = ctk.CTkEntry(
        form, placeholder_text="Enter password", show="*", height=30
    )
    pass_entry.grid(row=3, column=0, padx=16, pady=(0, 6), sticky="ew")

    confirm_label = ctk.CTkLabel(
        form, text="Confirm password", font=("Segoe UI", 11)
    )
    confirm_label.grid(row=4, column=0, padx=16, pady=(4, 2), sticky="w")

    confirm_entry = ctk.CTkEntry(
        form, placeholder_text="Re-enter password", show="*", height=30
    )
    confirm_entry.grid(row=5, column=0, padx=16, pady=(0, 6), sticky="ew")

    # Security question
    q_label = ctk.CTkLabel(
        form,
        text="Security question (for password reset)",
        font=("Segoe UI", 11),
    )
    q_label.grid(row=6, column=0, padx=16, pady=(6, 2), sticky="w")

    question_options = [
        "Your favourite place?",
        "Your best friend's name?",
        "Your first school's name?",
        "Your favourite teacher's name?",
        "Your favourite movie?",
    ]

    question_combo = ctk.CTkComboBox(
        form, values=question_options, state="readonly", height=30
    )
    question_combo.set(question_options[0])
    question_combo.grid(row=7, column=0, padx=16, pady=(0, 6), sticky="ew")

    # Security answer
    a_label = ctk.CTkLabel(form, text="Answer", font=("Segoe UI", 11))
    a_label.grid(row=8, column=0, padx=16, pady=(4, 2), sticky="w")

    answer_entry = ctk.CTkEntry(
        form, placeholder_text="Type your answer here", height=30
    )
    answer_entry.grid(row=9, column=0, padx=16, pady=(0, 8), sticky="ew")

    def do_register():
        u = user_entry.get().strip()
        p1 = pass_entry.get().strip()
        p2 = confirm_entry.get().strip()
        q = question_combo.get().strip()
        a = answer_entry.get().strip()

        if p1 != p2:
            messagebox.showerror("Error", "Passwords do not match.", parent=win)
            return

        ok, msg = register_user(u, p1, q, a)
        if ok:
            messagebox.showinfo("Success", msg, parent=win)
            win.destroy()
        else:
            messagebox.showerror("Error", msg, parent=win)

    btn = ctk.CTkButton(form, text="Create account", height=32, command=do_register)
    btn.grid(row=10, column=0, padx=16, pady=(4, 12), sticky="ew")


# ================================
#   RESET PASSWORD WINDOW
# ================================
def open_reset_password_window(parent):
    win = ctk.CTkToplevel(parent)
    win.title("Reset Password")
    win.geometry("440x520")
    win.resizable(False, False)

    win.transient(parent)
    win.grab_set()
    win.focus_force()

    try:
        parent.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - 220
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 260
        win.geometry(f"+{x}+{y}")
    except Exception:
        pass

    win.grid_columnconfigure(0, weight=1)
    win.grid_rowconfigure(2, weight=1)

    title = ctk.CTkLabel(
        win,
        text="Reset your password",
        font=("Segoe UI Semibold", 17),
    )
    title.grid(row=0, column=0, padx=18, pady=(16, 4), sticky="w")

    subtitle = ctk.CTkLabel(
        win,
        text=(
            "Enter username, answer security question and then set a new password."
        ),
        font=("Segoe UI", 10),
        text_color=("gray25", "gray70"),
        wraplength=400,
        justify="left",
    )
    subtitle.grid(row=1, column=0, padx=18, pady=(0, 10), sticky="w")

    frame = ctk.CTkFrame(win, corner_radius=12)
    frame.grid(row=2, column=0, padx=16, pady=(4, 16), sticky="nsew")
    frame.grid_columnconfigure(0, weight=1)

    current_info = {"uname": None, "info": None}
    answer_verified = {"flag": False, "question_exists": False}

    user_label = ctk.CTkLabel(frame, text="Username", font=("Segoe UI", 11))
    user_label.grid(row=0, column=0, padx=14, pady=(12, 2), sticky="w")

    user_entry = ctk.CTkEntry(
        frame, placeholder_text="Enter your username", height=30
    )
    user_entry.grid(row=1, column=0, padx=14, pady=(0, 8), sticky="ew")

    q_label = ctk.CTkLabel(
        frame,
        text="Security question: (enter username and click 'Show question')",
        font=("Segoe UI", 10),
        text_color=("gray25", "gray70"),
        wraplength=380,
        justify="left",
    )
    q_label.grid(row=2, column=0, padx=14, pady=(4, 4), sticky="w")

    def on_show_question():
        uname = user_entry.get().strip()
        if not uname:
            messagebox.showerror("Error", "Please enter username first.", parent=win)
            return

        users = load_users()
        info = users.get(uname)

        if info is None:
            messagebox.showerror("Error", "User not found.", parent=win)
            return

        current_info["uname"] = uname
        current_info["info"] = info
        answer_verified["flag"] = False
        answer_verified["question_exists"] = False

        if isinstance(info, str):
            q_label.configure(
                text=(
                    "No security question set for this user.\n"
                    "You can reset password directly after verifying username."
                )
            )
        else:
            q = info.get("question") or "No security question set."
            q_label.configure(text=f"Security question:\n{q}")
            if info.get("question"):
                answer_verified["question_exists"] = True

    show_q_btn = ctk.CTkButton(
        frame,
        text="Show question",
        width=120,
        height=28,
        command=on_show_question,
    )
    show_q_btn.grid(row=3, column=0, padx=14, pady=(0, 8), sticky="e")

    ans_label = ctk.CTkLabel(frame, text="Answer", font=("Segoe UI", 11))
    ans_label.grid(row=4, column=0, padx=14, pady=(6, 2), sticky="w")

    ans_entry = ctk.CTkEntry(frame, placeholder_text="Type your answer", height=30)
    ans_entry.grid(row=5, column=0, padx=14, pady=(0, 4), sticky="ew")

    def enable_password_fields():
        new_entry.configure(state="normal")
        confirm_entry.configure(state="normal")
        reset_btn.configure(state="normal")

    def on_verify_answer():
        info = current_info["info"]
        uname = current_info["uname"]

        if not uname or info is None:
            messagebox.showerror(
                "Error",
                "Please enter username and click 'Show question' first.",
                parent=win,
            )
            return

        if isinstance(info, str) or not info.get("question"):
            answer_verified["flag"] = True
            answer_verified["question_exists"] = False
            messagebox.showinfo(
                "Info",
                "No security question set for this user.\n"
                "You can set a new password now.",
                parent=win,
            )
            enable_password_fields()
            return

        given = (ans_entry.get() or "").strip().lower()
        stored_answer = (info.get("answer") or "").lower()

        if not given:
            messagebox.showerror("Error", "Please type your answer.", parent=win)
            return

        if given != stored_answer:
            messagebox.showerror(
                "Error", "Security answer does not match.", parent=win
            )
            return

        answer_verified["flag"] = True
        answer_verified["question_exists"] = True
        messagebox.showinfo(
            "Success", "Answer verified. You can set a new password.", parent=win
        )
        enable_password_fields()

    verify_btn = ctk.CTkButton(
        frame,
        text="Verify answer",
        width=120,
        height=28,
        command=on_verify_answer,
    )
    verify_btn.grid(row=6, column=0, padx=14, pady=(0, 8), sticky="e")

    new_label = ctk.CTkLabel(frame, text="New password", font=("Segoe UI", 11))
    new_label.grid(row=7, column=0, padx=14, pady=(6, 2), sticky="w")

    new_entry = ctk.CTkEntry(
        frame,
        placeholder_text="Enter new password",
        show="*",
        height=30,
        state="disabled",
    )
    new_entry.grid(row=8, column=0, padx=14, pady=(0, 6), sticky="ew")

    confirm_label = ctk.CTkLabel(
        frame, text="Confirm new password", font=("Segoe UI", 11)
    )
    confirm_label.grid(row=9, column=0, padx=14, pady=(4, 2), sticky="w")

    confirm_entry = ctk.CTkEntry(
        frame,
        placeholder_text="Re-enter new password",
        show="*",
        height=30,
        state="disabled",
    )
    confirm_entry.grid(row=10, column=0, padx=14, pady=(0, 8), sticky="ew")

    def on_reset():
        if not answer_verified["flag"]:
            messagebox.showerror(
                "Error",
                "Please verify security answer before resetting password.",
                parent=win,
            )
            return

        uname = current_info["uname"]
        info = current_info["info"]

        if not uname or info is None:
            messagebox.showerror("Error", "Username not verified.", parent=win)
            return

        p1 = new_entry.get().strip()
        p2 = confirm_entry.get().strip()

        if not p1 or not p2:
            messagebox.showerror("Error", "Please enter new password.", parent=win)
            return

        if p1 != p2:
            messagebox.showerror("Error", "Passwords do not match.", parent=win)
            return

        if len(p1) < 4:
            messagebox.showerror(
                "Error",
                "Password must be at least 4 characters.",
                parent=win,
            )
            return

        users = load_users()
        info = users.get(uname)

        if info is None:
            messagebox.showerror("Error", "User not found.", parent=win)
            return

        if isinstance(info, str):
            users[uname] = {
                "password": p1,
                "question": None,
                "answer": None,
            }
        else:
            info["password"] = p1
            users[uname] = info

        save_users(users)
        messagebox.showinfo("Success", "Password reset successfully!", parent=win)
        win.destroy()

    reset_btn = ctk.CTkButton(
        frame,
        text="Reset password",
        height=32,
        command=on_reset,
        state="disabled",
    )
    reset_btn.grid(row=11, column=0, padx=14, pady=(6, 12), sticky="ew")


# ================================
#   LOGIN SCREEN (first screen)
# ================================
def show_login_screen():
    global root, CURRENT_USER

    for w in root.winfo_children():
        w.destroy()

    root.title("SmartShotApp - Login")
    root.geometry("1000x650")
    root.minsize(900, 550)

    root.grid_columnconfigure(0, weight=1)
    root.grid_columnconfigure(1, weight=1)
    root.grid_rowconfigure(0, weight=1)

    # LEFT PANEL
    left = ctk.CTkFrame(root, corner_radius=0)
    left.grid(row=0, column=0, sticky="nsew", padx=(40, 20), pady=40)
    left.grid_columnconfigure(0, weight=1)

    logo_frame = ctk.CTkFrame(left, fg_color="transparent")
    logo_frame.grid(row=0, column=0, padx=10, pady=(4, 10), sticky="w")

    logo_icon = ctk.CTkLabel(logo_frame, text="🧠", font=("Segoe UI Emoji", 26))
    logo_icon.grid(row=0, column=0, padx=(0, 6))

    logo_text = ctk.CTkLabel(
        logo_frame, text="SmartShotApp", font=("Segoe UI Semibold", 20)
    )
    logo_text.grid(row=0, column=1)

    heading = ctk.CTkLabel(
        left,
        text="Welcome back!",
        font=("Segoe UI Semibold", 28),
    )
    heading.grid(row=1, column=0, padx=10, pady=(10, 2), sticky="w")

    sub = ctk.CTkLabel(
        left,
        text="Please sign in to search your screenshots & documents.",
        font=("Segoe UI", 11),
        text_color=("gray25", "gray75"),
    )
    sub.grid(row=2, column=0, padx=10, pady=(0, 14), sticky="w")

    form = ctk.CTkFrame(left, corner_radius=14)
    form.grid(row=3, column=0, padx=4, pady=(0, 10), sticky="nsew")
    form.grid_columnconfigure(0, weight=1)

    user_label = ctk.CTkLabel(form, text="Username", font=("Segoe UI", 11))
    user_label.grid(row=0, column=0, padx=18, pady=(14, 2), sticky="w")

    user_entry = ctk.CTkEntry(
        form,
        placeholder_text="Enter your username",
        height=34,
    )
    user_entry.grid(row=1, column=0, padx=18, pady=(0, 8), sticky="ew")

    pass_label = ctk.CTkLabel(form, text="Password", font=("Segoe UI", 11))
    pass_label.grid(row=2, column=0, padx=18, pady=(6, 2), sticky="w")

    pass_entry = ctk.CTkEntry(
        form,
        placeholder_text="Enter your password",
        show="*",
        height=34,
    )
    pass_entry.grid(row=3, column=0, padx=18, pady=(0, 6), sticky="ew")

    forgot = ctk.CTkLabel(
        form,
        text="Forgot password?",
        font=("Segoe UI", 10),
        text_color=("#2563eb", "#93c5fd"),
    )
    forgot.grid(row=4, column=0, padx=18, pady=(0, 10), sticky="e")

    forgot.configure(cursor="hand2")
    forgot.bind("<Button-1>", lambda e: open_reset_password_window(root))

    def do_login():
        global CURRENT_USER

        u = user_entry.get().strip()
        p = pass_entry.get().strip()

        if not u or not p:
            messagebox.showerror(
                "Error",
                "Please enter username and password.",
                parent=root,
            )
            return

        if authenticate_user(u, p):
            CURRENT_USER = u
            open_main_app()
        else:
            messagebox.showerror(
                "Login failed",
                "Invalid username or password.",
                parent=root,
            )

    login_btn = ctk.CTkButton(
        form,
        text="Sign in",
        height=36,
        command=do_login,
    )
    login_btn.grid(row=5, column=0, padx=18, pady=(0, 12), sticky="ew")

    bottom_frame = ctk.CTkFrame(form, fg_color="transparent")
    bottom_frame.grid(row=6, column=0, padx=18, pady=(4, 14), sticky="ew")
    bottom_frame.grid_columnconfigure(0, weight=1)

    info = ctk.CTkLabel(
        bottom_frame,
        text="Don't have an account?",
        font=("Segoe UI", 10),
        text_color=("gray30", "gray70"),
    )
    info.grid(row=0, column=0, sticky="e", padx=(0, 4))

    def open_signup(_event=None):
        open_register_window(root)

    signup = ctk.CTkLabel(
        bottom_frame,
        text="Sign up",
        font=("Segoe UI Semibold", 10),
        text_color=("#2563eb", "#93c5fd"),
        cursor="hand2",
    )
    signup.grid(row=0, column=1, sticky="w")
    signup.bind("<Button-1>", open_signup)

    # RIGHT PANEL
    right = ctk.CTkFrame(root, corner_radius=24)
    right.grid(row=0, column=1, sticky="nsew", padx=(0, 40), pady=40)
    right.grid_columnconfigure(0, weight=1)
    right.grid_rowconfigure(1, weight=1)

    right.configure(fg_color=("#eef2ff", "#1f2937"))

    hero_title = ctk.CTkLabel(
        right,
        text="Visual memory,\nnow searchable.",
        font=("Segoe UI Semibold", 24),
        justify="left",
    )
    hero_title.grid(row=0, column=0, padx=26, pady=(26, 4), sticky="w")

    hero_sub = ctk.CTkLabel(
        right,
        text=(
            "Drop a folder of screenshots and quickly find\n"
            "what you saw yesterday – code, chats, notes\n"
            "and documents – all in one place."
        ),
        font=("Segoe UI", 11),
        text_color=("gray25", "gray70"),
        justify="left",
    )
    hero_sub.grid(row=1, column=0, padx=26, pady=(0, 10), sticky="nw")

    art = ctk.CTkLabel(right, text="📸  ➜  🔍  ➜  💡", font=("Segoe UI Emoji", 40))
    art.grid(row=2, column=0, padx=26, pady=(10, 6), sticky="n")

    caption = ctk.CTkLabel(
        right,
        text=(
            "Capture once, search forever.\n"
            "SmartShotApp keeps your visual memory organized."
        ),
        font=("Segoe UI", 10),
        text_color=("gray30", "gray70"),
        justify="center",
    )
    caption.grid(row=3, column=0, padx=26, pady=(0, 20), sticky="s")


# ================================
#   MAIN ENTRY
# ================================
if __name__ == "__main__":
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    globals()["root"] = root

    show_login_screen()
    root.mainloop()
