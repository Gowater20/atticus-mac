#!/usr/bin/env python3
"""
Atticus Feedback & Rollback Manager (Continuous Learning / Negative Feedback)
Tracks recent actions within a Grace Period (default 6 seconds).
Allows the user to say "annulla", "no", "sbagliato" or press Esc to undo the action,
remove faulty learned skills from skills.json, and trigger disambiguation.
"""

import os
import sys
import time
import json
import re
import subprocess

CONFIG_DIR = os.path.expanduser("~/.config/atticus")
LAST_ACTION_PATH = os.path.join(CONFIG_DIR, "last_action.json")
SKILLS_PATH = os.path.join(CONFIG_DIR, "skills.json")
DEFAULT_GRACE_PERIOD = 7.0  # seconds

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
        print(f"[Feedback] Errore nel salvataggio di last_action: {e}", file=sys.stderr)


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


def invalidate_skill(skill_key):
    """Removes a skill from skills.json when flagged as a false positive."""
    if not skill_key or not os.path.exists(SKILLS_PATH):
        return False
    try:
        with open(SKILLS_PATH, "r", encoding="utf-8") as f:
            skills = json.load(f)
        removed = False
        k_clean = skill_key.strip().lower()
        keys_to_del = [k for k in skills if k.strip().lower() == k_clean]
        for k in keys_to_del:
            del skills[k]
            removed = True
        if removed:
            tmp = SKILLS_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(skills, f, indent=1)
            os.replace(tmp, SKILLS_PATH)
            print(f"[Feedback] Skill '{skill_key}' invalidata e rimossa da skills.json", file=sys.stderr)
        return removed
    except Exception as e:
        print(f"[Feedback] Errore nell'invalidazione della skill: {e}", file=sys.stderr)
        return False


def handle_annulla():
    """
    Executes rollback if an action is within the grace period.
    Returns (True, message) or (False, None).
    """
    last = get_last_action()
    if not last:
        return False, None

    prompt = last.get("prompt", "")
    rollback_cmd = last.get("rollback_cmd", "")
    skill_key = last.get("skill_key") or prompt

    # 1. Invalidate learned shortcut
    invalidate_skill(skill_key)

    # 2. Execute rollback command if provided
    rollback_executed = False
    if rollback_cmd:
        try:
            print(f"[Feedback] Esecuzione rollback: {rollback_cmd}", file=sys.stderr)
            subprocess.run(rollback_cmd, shell=isinstance(rollback_cmd, str), timeout=6)
            rollback_executed = True
        except Exception as e:
            print(f"[Feedback] Errore esecuzione rollback: {e}", file=sys.stderr)

    # 3. Clear last action to prevent double rollback
    clear_last_action()

    msg = "Azione annullata. Cosa volevi fare?"
    return True, msg

