#!/usr/bin/env python3
"""
System 1 Finder Automation Module
Handles safe folder creation and file revealing.
"""

import os
from ..executor import run_applescript

APP_NAME = "Finder"


def create_folder(folder_name="Nuova Cartella", base_path="~/Desktop"):
    """
    Creates a new folder safely via Finder.
    Returns (success: bool, created_path: str).
    """
    full_base = os.path.expanduser(base_path)
    target_path = os.path.join(full_base, folder_name)

    if os.path.exists(target_path):
        return False, f"La cartella '{folder_name}' esiste già."

    esc_name = folder_name.replace('"', '\\"')
    esc_base = full_base.replace('"', '\\"')

    script = f'''
    tell application "Finder"
        set baseFolder to POSIX file "{esc_base}" as alias
        make new folder at baseFolder with properties {{name:"{esc_name}"}}
        return "OK"
    end tell
    '''
    ok, out, _ = run_applescript(script, timeout=4.0, target_app=APP_NAME)
    if ok:
        return True, target_path
    return False, out


def rollback_create_folder(folder_path):
    """
    Deletes the created folder ONLY if it is still empty.
    Moves to Trash instead of permanent deletion.
    """
    full_path = os.path.expanduser(folder_path)
    if not os.path.exists(full_path):
        return True, "Già rimossa"

    # Verify folder is empty
    try:
        if os.listdir(full_path):
            return False, "La cartella contiene file, rollback annullato per sicurezza."
    except Exception as e:
        return False, str(e)

    esc_path = full_path.replace('"', '\\"')
    script = f'''
    tell application "Finder"
        set targetItem to POSIX file "{esc_path}" as alias
        delete targetItem
        return "OK"
    end tell
    '''
    ok, out, _ = run_applescript(script, timeout=3.0, target_app=APP_NAME)
    return ok, out


def reveal_item(item_path):
    """Reveals a file or directory in Finder."""
    full_path = os.path.expanduser(item_path)
    esc_path = full_path.replace('"', '\\"')
    script = f'''
    tell application "Finder"
        activate
        reveal POSIX file "{esc_path}"
        return "OK"
    end tell
    '''
    ok, out, _ = run_applescript(script, timeout=3.0, target_app=APP_NAME)
    return ok, out
