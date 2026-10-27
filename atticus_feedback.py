#!/usr/bin/env python3
"""
Atticus Feedback & Rollback Manager (Continuous Learning / Negative Feedback)
Tracks recent actions within a Grace Period (5.0 seconds).
Handles surgical, non-destructive rollbacks, confidence decay in skills.json,
and IPC state management for pending disambiguation choices (pending_choice.json).
"""

import os
import sys
import time
import json
import re
import subprocess

CONFIG_DIR = os.path.expanduser("~/.config/atticus")
LAST_ACTION_PATH = os.path.join(CONFIG_DIR, "last_action.json")
PENDING_CHOICE_PATH = os.path.join(CONFIG_DIR, "pending_choice.json")
SKILLS_PATH = os.path.join(CONFIG_DIR, "skills.json")
DEFAULT_GRACE_PERIOD = 5.0  # seconds
DEFAULT_PENDING_TTL = 25.0  # seconds

NEGATIVE_TRIGGERS = {
    'annulla', 'annullalo', 'annulla tutto', 'annulla azione',
    'no', 'no no', 'no sbagliato', 'sbagliato', 'non questo',
    'fermati', 'torna indietro', 'cancella', 'cancella azione',
    'undo', 'cancel', 'stop', 'wrong', 'nevermind', 'never mind'
}


def is_negative_trigger(text):
    """Checks if the user input expresses regret or a request to undo."""
    if not text:
        return False
    t = text.strip().lower()
    t = re.sub(r'^[,\.\s!]+|[,\.\s!]+$', '', t)
    if t in NEGATIVE_TRIGGERS:
        return True
    return bool(re.match(r'^(?:no|annulla|cancella|stop)(?:\s+(?:tutto|questo|quello|l\'azione|l\'app))?$', t))


# --- 1. Pending Choice (Disambiguation IPC) Management ---

def save_pending_choice(original_query, options, front_app="", ttl=DEFAULT_PENDING_TTL):
    """Saves pending disambiguation card choices with a TTL."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    payload = {
        "created_at": time.time(),
        "ttl_seconds": ttl,
        "original_query": original_query,
        "front_app": front_app,
        "options": options or []
    }
    tmp_path = PENDING_CHOICE_PATH + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_path, PENDING_CHOICE_PATH)
    except Exception as e:
        print(f"[Feedback] Errore salvataggio pending_choice: {e}", file=sys.stderr)


def get_pending_choice(max_age=DEFAULT_PENDING_TTL):
    """Retrieves pending choice if within its TTL."""
    if not os.path.exists(PENDING_CHOICE_PATH):
        return None
    try:
        with open(PENDING_CHOICE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        elapsed = time.time() - data.get("created_at", 0)
        ttl = data.get("ttl_seconds", max_age)
        if elapsed <= ttl:
            data["_elapsed"] = elapsed
            return data
    except Exception:
        pass
    return None


def clear_pending_choice():
    """Removes pending choice file."""
    try:
        if os.path.exists(PENDING_CHOICE_PATH):
            os.remove(PENDING_CHOICE_PATH)
    except Exception:
        pass


def resolve_pending_choice(text):
    """
    Checks if text is a selection for an active pending choice:
    e.g. 'uno', '1', 'prima', 'due', '2', 'seconda', 'tre', '3', 'terza', 'gemini'.
    Returns (resolved: bool, choice_dict_or_action: dict or None).
    """
    pending = get_pending_choice()
    if not pending:
        return False, None

    t = text.strip().lower()
    options = pending.get("options", [])
    if not options:
        clear_pending_choice()
        return False, None

    choice_idx = None
    if t in ("1", "uno", "la prima", "opzione uno", "prima"):
        choice_idx = 0
    elif t in ("2", "due", "la seconda", "opzione due", "seconda"):
        choice_idx = 1
    elif t in ("3", "tre", "la terza", "opzione tre", "terza", "chiedi a gemini", "gemini"):
        choice_idx = 2

    if choice_idx is not None and choice_idx < len(options):
        selected = options[choice_idx]
        clear_pending_choice()
        return True, selected

    return False, None


# --- 2. Grace Period & Last Action Tracking ---

def record_action(prompt, action_type, executed_cmds=None, rollback_cmd=None, skill_key=None, metadata=None):
    """Saves the last executed action to disk for grace-period tracking."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    payload = {
        "timestamp": time.time(),
        "prompt": prompt,
        "action_type": action_type,
        "executed_cmds": executed_cmds or [],
        "rollback_cmd": rollback_cmd or "",
        "skill_key": skill_key or "",
        "metadata": metadata or {}
    }
    tmp_path = LAST_ACTION_PATH + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_path, LAST_ACTION_PATH)
    except Exception as e:
        print(f"[Feedback] Errore salvataggio last_action: {e}", file=sys.stderr)


def get_last_action(max_age=DEFAULT_GRACE_PERIOD):
    """Retrieves the last action if within the grace period."""
    if not os.path.exists(LAST_ACTION_PATH):
        return None
    try:
        with open(LAST_ACTION_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        elapsed = time.time() - data.get("timestamp", 0)
        if elapsed <= max_age:
            data["elapsed"] = elapsed
            return data
    except Exception:
        pass
    return None


def clear_last_action():
    """Clears the last action file."""
    try:
        if os.path.exists(LAST_ACTION_PATH):
            os.remove(LAST_ACTION_PATH)
    except Exception:
        pass


# --- 3. Continuous Learning: Confidence Decay vs Reinforcement ---

def decay_skill(skill_key, factor=0.65):
    """
    Applies exponential decay to a skill instead of hard deletion.
    If confidence < 0.35, sets status to 'quarantined'.
    """
    if not skill_key or not os.path.exists(SKILLS_PATH):
        return False
    try:
        with open(SKILLS_PATH, "r", encoding="utf-8") as f:
            skills = json.load(f)

        k_clean = skill_key.strip().lower()
        modified = False

        for k, v in list(skills.items()):
            if k.strip().lower() == k_clean:
                if isinstance(v, dict):
                    old_c = v.get("confidence", 0.85)
                    new_c = round(old_c * factor, 3)
                    v["confidence"] = new_c
                    v["undo_count"] = v.get("undo_count", 0) + 1
                    if new_c < 0.35 or v["undo_count"] >= 2:
                        v["status"] = "quarantined"
                    v["last_modified"] = time.time()
                else:
                    # Legacy string shortcut: remove or convert
                    del skills[k]
                modified = True

        if modified:
            tmp = SKILLS_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(skills, f, indent=2)
            os.replace(tmp, SKILLS_PATH)
            print(f"[Feedback] Skill '{skill_key}' penalizzata con decay ({factor}) in skills.json", file=sys.stderr)
        return modified
    except Exception as e:
        print(f"[Feedback] Errore nel decay della skill: {e}", file=sys.stderr)
        return False


def reinforce_skill(skill_key):
    """Increases confidence of a successfully executed skill."""
    if not skill_key or not os.path.exists(SKILLS_PATH):
        return False
    try:
        with open(SKILLS_PATH, "r", encoding="utf-8") as f:
            skills = json.load(f)

        k_clean = skill_key.strip().lower()
        modified = False

        for k, v in list(skills.items()):
            if k.strip().lower() == k_clean and isinstance(v, dict):
                old_c = v.get("confidence", 0.80)
                new_c = min(0.98, round(old_c + 0.04 * (1.0 - old_c), 3))
                v["confidence"] = new_c
                v["success_count"] = v.get("success_count", 0) + 1
                v["status"] = "active"
                v["last_used"] = time.time()
                modified = True

        if modified:
            tmp = SKILLS_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(skills, f, indent=2)
            os.replace(tmp, SKILLS_PATH)
        return modified
    except Exception:
        return False


# --- 4. Rollback Execution (Surgical & Non-Destructive) ---

def handle_annulla():
    """
    Executes a surgical rollback if an action is within the grace period.
    Returns (True, message) or (False, None).
    """
    last = get_last_action()
    if not last:
        return False, None

    prompt = last.get("prompt", "")
    action_type = last.get("action_type", "")
    metadata = last.get("metadata", {}) or {}
    skill_key = last.get("skill_key") or prompt

    # 1. Apply confidence decay to the skill
    decay_skill(skill_key)

    # 2. Domain-specific surgical rollback
    rollback_ok = False
    details = ""

    if action_type == "word_create":
        # Safe document close: only close document if name matches
        doc_name = metadata.get("doc_name")
        if doc_name:
            from system_one.apps import word
            word.close_active_document(doc_name=doc_name, saving=False)
            rollback_ok = True
            details = f"Chiuso documento '{doc_name}'."

    elif action_type == "window_place":
        # Geometric restore: restore previous exact bounds
        proc = metadata.get("app")
        bounds = metadata.get("bounds")
        if proc and bounds:
            from system_one.apps import window
            ok, _ = window.restore_window_bounds(proc, bounds)
            if ok:
                rollback_ok = True
                details = f"Ripristinata posizione finestra di {proc}."

    elif action_type == "create_folder":
        # Safe delete: delete folder only if empty
        folder_path = metadata.get("path")
        if folder_path:
            from system_one.apps import finder
            ok, _ = finder.rollback_create_folder(folder_path)
            if ok:
                rollback_ok = True
                details = f"Rimossa cartella creata."

    # 3. Fallback to generic rollback command if specific handler did not apply
    if not rollback_ok:
        rollback_cmd = last.get("rollback_cmd", "")
        if rollback_cmd:
            try:
                print(f"[Feedback] Esecuzione rollback generico: {rollback_cmd}", file=sys.stderr)
                subprocess.run(rollback_cmd, shell=isinstance(rollback_cmd, str), timeout=5)
                rollback_ok = True
            except Exception as e:
                print(f"[Feedback] Errore esecuzione rollback: {e}", file=sys.stderr)

    # 4. Clear last action to avoid double rollback
    clear_last_action()

    msg = f"Azione annullata. {details}".strip()
    return True, msg
