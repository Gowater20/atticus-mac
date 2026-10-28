#!/usr/bin/env python3
"""
Atticus Feedback & Rollback Manager (Continuous Learning / Negative Feedback)
Tracks recent actions with indefinite undo persistence until superseded or cleared.
Handles surgical, non-destructive rollbacks, confidence decay and reinforcement in skills.json,
IPC state management for pending disambiguation choices (pending_choice.json),
and fast-path user corrections (user_corrections.json / corrections_dataset.jsonl).
"""

import os
import sys
import time
import json
import re
import subprocess

CONFIG_DIR = os.environ.get("ATTICUS_DIR") or os.path.expanduser("~/.config/atticus")
LAST_ACTION_PATH = os.path.join(CONFIG_DIR, "last_action.json")
PENDING_CHOICE_PATH = os.path.join(CONFIG_DIR, "pending_choice.json")
SKILLS_PATH = os.path.join(CONFIG_DIR, "skills.json")
USER_CORRECTIONS_FILE = os.path.join(CONFIG_DIR, "user_corrections.json")
CORRECTIONS_DATASET_FILE = os.path.join(CONFIG_DIR, "corrections_dataset.jsonl")

DEFAULT_GRACE_PERIOD = 5.0  # seconds (legacy fallback)
DEFAULT_PENDING_TTL = 25.0  # seconds

NEGATIVE_TRIGGERS = {
    'annulla', 'annullalo', 'annulla tutto', 'annulla azione',
    'no', 'no no', 'no sbagliato', 'sbagliato', 'non questo',
    'fermati', 'torna indietro', 'cancella', 'cancella azione',
    'undo', 'cancel', 'stop', 'wrong', 'nevermind', 'never mind'
}

# --- Cache and Path Resolution Helpers ---

_USER_CORRECTIONS_CACHE = {}
_CACHE_LOADED = False
_CACHE_DIR = None
_CACHE_MTIME = 0.0


def _get_cfg_dir():
    return getattr(sys.modules[__name__], "CONFIG_DIR", CONFIG_DIR)


def _get_user_corrections_path():
    cfg = _get_cfg_dir()
    return os.path.join(cfg, "user_corrections.json")


def _get_corrections_dataset_path():
    cfg = _get_cfg_dir()
    return os.path.join(cfg, "corrections_dataset.jsonl")


def _get_skills_path():
    cfg = _get_cfg_dir()
    s_path = getattr(sys.modules[__name__], "SKILLS_PATH", None)
    if not s_path or (cfg != CONFIG_DIR and os.path.dirname(s_path) != cfg):
        s_path = os.path.join(cfg, "skills.json")
    return s_path


def _get_last_action_path():
    cfg = _get_cfg_dir()
    last_path = getattr(sys.modules[__name__], "LAST_ACTION_PATH", None)
    if not last_path or (cfg != CONFIG_DIR and os.path.dirname(last_path) != cfg):
        last_path = os.path.join(cfg, "last_action.json")
    return last_path


def _get_pending_choice_path():
    cfg = _get_cfg_dir()
    p_path = getattr(sys.modules[__name__], "PENDING_CHOICE_PATH", None)
    if not p_path or (cfg != CONFIG_DIR and os.path.dirname(p_path) != cfg):
        p_path = os.path.join(cfg, "pending_choice.json")
    return p_path


def _normalize_prompt(prompt):
    """Normalizes prompt: spoken numbers to digits, lowercase, trimmed punctuation and whitespaces."""
    if not prompt:
        return ""
    try:
        import atticus_i18n
        p = atticus_i18n.normalize_italian_numbers(str(prompt))
    except Exception:
        p = str(prompt)
    p = p.strip().lower()
    p = re.sub(r'^[,\.\s!?]+|[,\.\s!?]+$', '', p)
    p = re.sub(r'\s+', ' ', p)
    return p


def _ensure_cache_loaded():
    global _USER_CORRECTIONS_CACHE, _CACHE_LOADED, _CACHE_DIR, _CACHE_MTIME
    cfg = _get_cfg_dir()
    path = _get_user_corrections_path()

    if not _CACHE_LOADED or _CACHE_DIR != cfg:
        _USER_CORRECTIONS_CACHE = {}
        _CACHE_DIR = cfg
        _CACHE_LOADED = True
        _CACHE_MTIME = 0.0

    if os.path.exists(path):
        try:
            mtime = os.path.getmtime(path)
            if mtime != _CACHE_MTIME:
                with open(path, "r", encoding="utf-8") as f:
                    _USER_CORRECTIONS_CACHE = json.load(f)
                _CACHE_MTIME = mtime
        except Exception:
            _USER_CORRECTIONS_CACHE = {}
    else:
        _USER_CORRECTIONS_CACHE = {}
        _CACHE_MTIME = 0.0


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
    cfg = _get_cfg_dir()
    os.makedirs(cfg, exist_ok=True)
    payload = {
        "created_at": time.time(),
        "ttl_seconds": ttl,
        "original_query": original_query,
        "front_app": front_app,
        "options": options or []
    }
    p_path = _get_pending_choice_path()
    tmp_path = p_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_path, p_path)
    except Exception as e:
        print(f"[Feedback] Errore salvataggio pending_choice: {e}", file=sys.stderr)


def get_pending_choice(max_age=DEFAULT_PENDING_TTL):
    """Retrieves pending choice if within its TTL."""
    p_path = _get_pending_choice_path()
    if not os.path.exists(p_path):
        return None
    try:
        with open(p_path, "r", encoding="utf-8") as f:
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
        p_path = _get_pending_choice_path()
        if os.path.exists(p_path):
            os.remove(p_path)
    except Exception:
        pass


def resolve_pending_choice(text):
    """
    Checks if text is a selection for an active pending choice:
    e.g. 'uno', '1', 'prima', 'due', '2', 'seconda', 'tre', '3', 'terza', 'gemini'.
    Returns (resolved: bool, choice_dict_or_action: dict or None).
    Saves user correction on selection to user_corrections.json and corrections_dataset.jsonl.
    """
    pending = get_pending_choice()
    if not pending:
        return False, None

    t = re.sub(r'^[,\.\s!?\'"]+|[\,\.\s!?\'"]+$', '', str(text or "")).strip().lower()
    t = re.sub(r'\s+', ' ', t)
    options = pending.get("options", [])
    if not options:
        clear_pending_choice()
        return False, None

    choice_idx = None
    if t in ("1", "uno", "la prima", "opzione uno", "prima"):
        choice_idx = 0
    elif t in ("2", "due", "la seconda", "opzione due", "seconda"):
        choice_idx = 1
    elif t in ("3", "tre", "la terza", "opzione tre", "terza"):
        choice_idx = 2
    elif t in ("chiedi a gemini", "gemini", "usa gemini", "system 2", "system2"):
        for i, opt in enumerate(options):
            act_id = opt.get("action_id", "").lower()
            lbl = opt.get("label", "").lower()
            if act_id in ("ask_gemini", "system2.gemini", "system2_ask_gemini") or "gemini" in lbl:
                choice_idx = i
                break

    if choice_idx is not None and choice_idx < len(options):
        selected = dict(options[choice_idx])
        original_query = pending.get("original_query", "")
        selected["original_query"] = original_query

        extracted_params = dict(selected.get("extracted_params") or {})
        if original_query:
            extracted_params["query"] = original_query
        selected["extracted_params"] = extracted_params

        chosen_intent = selected.get("action_id", "")
        if original_query and chosen_intent:
            save_user_correction(
                prompt=original_query,
                intent=chosen_intent,
                source="disambiguation_card",
                rejected_intent=None,
                params=extracted_params
            )

        clear_pending_choice()
        return True, selected

    return False, None


# --- 2. Action Tracking (Indefinite Undo Persistence) ---

def record_action(prompt, action_type, executed_cmds=None, rollback_cmd=None, skill_key=None, metadata=None, rollback_strategy=None):
    """
    Saves the last executed action to disk.
    If there was a previous action, consolidates (reinforces) the previous skill
    before overwriting. Action remains undoable until superseded or cleared.
    """
    cfg = _get_cfg_dir()
    os.makedirs(cfg, exist_ok=True)

    # 1. Consolidate previous action if present
    prev = get_last_action()
    if prev:
        prev_skill = prev.get("skill_key") or prev.get("prompt")
        if prev_skill:
            reinforce_skill(prev_skill)

    payload = {
        "timestamp": time.time(),
        "prompt": prompt,
        "action_type": action_type,
        "executed_cmds": executed_cmds or [],
        "rollback_cmd": rollback_cmd or "",
        "skill_key": skill_key or "",
        "rollback_strategy": rollback_strategy or "",
        "metadata": metadata or {}
    }
    last_path = _get_last_action_path()
    tmp_path = last_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_path, last_path)
    except Exception as e:
        print(f"[Feedback] Errore salvataggio last_action: {e}", file=sys.stderr)


def get_last_action(max_age=None):
    """
    Retrieves the last action. Action remains cancelable indefinitely
    until clear_last_action() / handle_annulla() is called, or until a new
    action is recorded with record_action() (which consolidates and overwrites it).
    """
    last_path = _get_last_action_path()
    if not os.path.exists(last_path):
        return None
    try:
        with open(last_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        elapsed = time.time() - data.get("timestamp", 0)
        data["elapsed"] = elapsed
        if max_age is not None and elapsed > max_age:
            return None
        return data
    except Exception:
        pass
    return None


def clear_last_action():
    """Clears the last action file."""
    try:
        last_path = _get_last_action_path()
        if os.path.exists(last_path):
            os.remove(last_path)
    except Exception:
        pass


# --- 3. Fast-Path User Corrections (0ms Cache & Dataset Append) ---

def get_user_correction(prompt):
    """
    Retrieves user correction for prompt with 0ms in-memory cache lookup.
    Returns dict with correction details (intent, params, etc.) or None.
    """
    if not prompt:
        return None
    norm = _normalize_prompt(prompt)
    if not norm:
        return None
    _ensure_cache_loaded()
    return _USER_CORRECTIONS_CACHE.get(norm)


def save_user_correction(prompt, intent, source="disambiguation_card", rejected_intent=None, params=None):
    """
    Saves a user correction with atomic write (.tmp + os.replace) to user_corrections.json
    and append to corrections_dataset.jsonl. Updates in-memory cache.
    """
    if not prompt or not intent:
        return False

    norm = _normalize_prompt(prompt)
    if not norm:
        return False

    cfg = _get_cfg_dir()
    os.makedirs(cfg, exist_ok=True)

    now = time.time()
    entry = {
        "intent": intent,
        "params": params or {},
        "source": source,
        "rejected_intent": rejected_intent,
        "timestamp": now,
        "raw_prompt": prompt
    }

    _ensure_cache_loaded()
    _USER_CORRECTIONS_CACHE[norm] = entry

    # 1. Atomic write to user_corrections.json
    corr_path = _get_user_corrections_path()
    tmp_path = corr_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(_USER_CORRECTIONS_CACHE, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, corr_path)
        global _CACHE_MTIME
        _CACHE_MTIME = os.path.getmtime(corr_path)
    except Exception as e:
        print(f"[Feedback] Errore salvataggio user_corrections: {e}", file=sys.stderr)
        return False

    # 2. Append to corrections_dataset.jsonl
    dataset_path = _get_corrections_dataset_path()
    dataset_entry = {
        "prompt": prompt,
        "normalized_prompt": norm,
        "intent": intent,
        "params": params or {},
        "source": source,
        "rejected_intent": rejected_intent,
        "timestamp": now
    }
    try:
        with open(dataset_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(dataset_entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[Feedback] Errore append corrections_dataset: {e}", file=sys.stderr)

    return True


# --- 4. Continuous Learning: Confidence Decay vs Reinforcement ---

def decay_skill(skill_key, factor=0.65):
    """
    Applies exponential decay to a skill instead of hard deletion.
    If confidence < 0.35, sets status to 'quarantined'.
    """
    skills_path = _get_skills_path()
    if not skill_key or not os.path.exists(skills_path):
        return False
    try:
        with open(skills_path, "r", encoding="utf-8") as f:
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
                    del skills[k]
                modified = True

        if modified:
            tmp = skills_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(skills, f, indent=2)
            os.replace(tmp, skills_path)
            print(f"[Feedback] Skill '{skill_key}' penalizzata con decay ({factor}) in skills.json", file=sys.stderr)
        return modified
    except Exception as e:
        print(f"[Feedback] Errore nel decay della skill: {e}", file=sys.stderr)
        return False


def reinforce_skill(skill_key):
    """Increases confidence of a successfully executed skill."""
    skills_path = _get_skills_path()
    if not skill_key or not os.path.exists(skills_path):
        return False
    try:
        with open(skills_path, "r", encoding="utf-8") as f:
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
            tmp = skills_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(skills, f, indent=2)
            os.replace(tmp, skills_path)
        return modified
    except Exception:
        return False


# --- 5. Rollback Execution (Surgical & Non-Destructive) ---

def handle_annulla():
    """
    Executes a surgical rollback of the last action.
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

    # Check explicit rollback_strategy or action_type
    strat = last.get("rollback_strategy")
    if strat in ("close_created_workbook_verified", "excel_undo", "close_created_doc_verified", "word_undo", "restore_window_bounds", "delete_if_empty"):
        try:
            from system_one.executor import execute_rollback_strategy
            ok, msg = execute_rollback_strategy(strat, metadata)
            if ok:
                rollback_ok = True
                details = msg
        except Exception:
            pass

    if not rollback_ok and action_type in ("excel_create", "close_created_workbook_verified"):
        wb_name = metadata.get("wb_name")
        if wb_name:
            from system_one.apps import excel
            excel.close_workbook(wb_name=wb_name, saving=False)
            rollback_ok = True
            details = f"Chiusa cartella di lavoro '{wb_name}'."

    elif not rollback_ok and action_type in ("excel_undo", "format_cells", "insert_table"):
        from system_one.apps import excel
        ok, out = excel.undo_last()
        if ok:
            rollback_ok = True
            details = "Annullata ultima modifica su Excel."

    elif not rollback_ok and action_type == "word_create":
        # Safe document close: only close document if name matches
        doc_name = metadata.get("doc_name")
        if doc_name:
            from system_one.apps import word
            word.close_active_document(doc_name=doc_name, saving=False)
            rollback_ok = True
            details = f"Chiuso documento '{doc_name}'."

    elif not rollback_ok and action_type == "window_place":
        # Geometric restore: restore previous exact bounds
        proc = metadata.get("app")
        bounds = metadata.get("bounds")
        if proc and bounds:
            from system_one.apps import window
            ok, _ = window.restore_window_bounds(proc, bounds)
            if ok:
                rollback_ok = True
                details = f"Ripristinata posizione finestra di {proc}."

    elif not rollback_ok and action_type == "create_folder":
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
