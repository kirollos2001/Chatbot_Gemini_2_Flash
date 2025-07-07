import os
import json

SESSION_FILE = "client_sessions.json"

def load_all_sessions():
    if not os.path.exists(SESSION_FILE):
        return {}
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_all_sessions(sessions):
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, indent=2, ensure_ascii=False)

def save_session(thread_id, client_info):
    sessions = load_all_sessions()
    sessions[thread_id] = client_info
    save_all_sessions(sessions)

def get_session(thread_id):
    sessions = load_all_sessions()
    return sessions.get(thread_id)
