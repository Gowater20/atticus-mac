#!/usr/bin/env python3
"""
System 1 Context & Short-Term Memory Manager
Tracks frontmost application (ATTICUS_FRONT) and multi-turn session state.
Enables anaphora resolution ("mettilo in grassetto", "salvalo in pdf").
"""

import os
import sys
import time
import json
import subprocess

CONFIG_DIR = os.path.expanduser("~/.config/atticus")
SESSION_CONTEXT_PATH = os.path.join(CONFIG_DIR, "session_context.json")
DEFAULT_SESSION_TTL = 120.0  # seconds


def get_frontmost_app():
    """
    Returns the name of the currently active/frontmost application.
    Prioritizes ATTICUS_FRONT environment variable set by Swift host.
    """
    env_front = os.environ.get("ATTICUS_FRONT")
    if env_front and env_front.strip():
        return env_front.strip()

    if os.environ.get("ATTICUS_DRY_RUN") == "1":
        return os.environ.get("ATTICUS_MOCK_FRONT", "Microsoft Word")

    try:
        cmd = ['osascript', '-e', 'tell application "System Events" to get name of first application process whose frontmost is true']
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=1.5)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return ""


def get_session_context(max_age=DEFAULT_SESSION_TTL):
    """Retrieves session context if updated within max_age seconds."""
    if not os.path.exists(SESSION_CONTEXT_PATH):
        return {}
    try:
        with open(SESSION_CONTEXT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        elapsed = time.time() - data.get("updated_at", 0)
        if elapsed <= max_age:
            data["_elapsed"] = elapsed
            return data
    except Exception:
        pass
    return {}


def update_session_context(app="", action_id="", target_text="", document_id="", file_path="", extra=None):
    """Updates session context atomically for multi-turn references."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    current = get_session_context(max_age=DEFAULT_SESSION_TTL) or {}
    
    payload = {
        "updated_at": time.time(),
        "last_app": app or current.get("last_app", ""),
        "last_action_id": action_id or current.get("last_action_id", ""),
        "last_target_text": target_text if target_text is not None else current.get("last_target_text", ""),
        "last_document_id": document_id if document_id is not None else current.get("last_document_id", ""),
        "last_file_path": file_path if file_path is not None else current.get("last_file_path", ""),
        "extra": extra or current.get("extra", {})
    }
    tmp_path = SESSION_CONTEXT_PATH + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_path, SESSION_CONTEXT_PATH)
    except Exception as e:
        print(f"[Context] Errore salvataggio session_context: {e}", file=sys.stderr)


def clear_session_context():
    """Clears the session context file."""
    try:
        if os.path.exists(SESSION_CONTEXT_PATH):
            os.remove(SESSION_CONTEXT_PATH)
    except Exception:
        pass
