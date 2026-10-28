#!/usr/bin/env python3
"""
System 1 Safe AppleScript Executor
Handles cold-launches, TCC permissions (-1743), parameter passing,
timeout management, DRY_RUN testing mode, and execution/rollback strategy routing
for applications including Microsoft Word, Microsoft Excel, Finder, and Window Management.
"""

import os
import sys
import time
import subprocess
import shlex
from typing import Tuple, Dict, Any, Optional

ERR_TCC_PERMISSION = -1743
ERR_ACCESSIBILITY = -25211

APP_CANONICAL_NAMES = {
    "word": "Microsoft Word",
    "excel": "Microsoft Excel",
    "finder": "Finder",
    "safari": "Safari",
    "system events": "System Events",
    "com.microsoft.word": "Microsoft Word",
    "com.microsoft.excel": "Microsoft Excel",
    "com.apple.finder": "Finder"
}


def resolve_app_name(app_key: str) -> str:
    """Resolves short app key or bundle identifier to canonical macOS application name."""
    if not app_key:
        return ""
    k = app_key.strip().lower()
    return APP_CANONICAL_NAMES.get(k, app_key)


def is_dry_run() -> bool:
    return os.environ.get("ATTICUS_DRY_RUN") == "1"


def is_app_running(app_name: str) -> bool:
    """Checks if an application process is running."""
    if is_dry_run():
        return True
    canonical = resolve_app_name(app_name)
    try:
        script = f'tell application "System Events" to return (exists (first application process whose name is "{canonical}"))'
        res = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=2)
        return res.stdout.strip().lower() == 'true'
    except Exception:
        return False


def ensure_app_ready(app_name: str, max_wait: float = 8.0) -> bool:
    """
    Ensures the target application is launched and ready for AppleEvents.
    Prevents timeout -1712 during cold launch.
    """
    if is_dry_run():
        return True
    canonical = resolve_app_name(app_name)
    if is_app_running(canonical):
        return True

    try:
        subprocess.run(['open', '-a', canonical], capture_output=True, text=True, timeout=3)
    except Exception:
        pass

    start = time.time()
    while time.time() - start < max_wait:
        if is_app_running(canonical):
            # Give the event loop a brief moment to stabilize
            time.sleep(0.4)
            return True
        time.sleep(0.3)
    return False


def run_applescript(script_str: str, args: Optional[list] = None, timeout: float = 6.0, target_app: Optional[str] = None) -> Tuple[bool, str, int]:
    """
    Executes AppleScript with robust error trapping.
    If target_app is provided, checks for cold launch.
    Supports DRY_RUN mode for test suites.
    Returns (success: bool, output: str, err_code: int).
    """
    if is_dry_run():
        # Simulate success for test suites in DRY_RUN mode
        return True, "DRY_RUN_OK", 0

    canonical_target = resolve_app_name(target_app) if target_app else None
    if canonical_target:
        ensure_app_ready(canonical_target)

    cmd = ['osascript']
    # If script contains 'on run argv', pass args via CLI
    cmd.extend(['-e', script_str])
    if args:
        cmd.extend([str(a) for a in args])

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (res.stdout or res.stderr or "").strip()
        code = res.returncode
        if code == 0:
            return True, out, 0

        # Check for TCC permission errors
        if "-1743" in out or "errAEEventNotPermitted" in out:
            app_label = canonical_target if canonical_target else "l'applicazione"
            msg = f"Permesso macOS mancante per controllare '{app_label}'. Abilitalo in Impostazioni di Sistema -> Privacy e Sicurezza -> Automazione."
            return False, msg, ERR_TCC_PERMISSION

        return False, out, code
    except subprocess.TimeoutExpired:
        return False, f"Timeout ({timeout}s) durante l'esecuzione di AppleScript", -1712
    except Exception as e:
        return False, str(e), -1


def execute_rollback_strategy(strategy: str, metadata: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    """
    Routes and executes surgical rollback strategies across System 1 applications:
    - 'close_created_workbook_verified': Closes created Excel workbook if name matches
    - 'excel_undo': Triggers native Microsoft Excel undo
    - 'close_created_doc_verified': Closes created Word document if name matches
    - 'word_undo': Triggers native Microsoft Word undo
    - 'restore_window_bounds': Restores previous exact window bounds
    - 'delete_if_empty': Deletes created folder if empty
    """
    metadata = metadata or {}
    strat = (strategy or "").strip().lower()

    if strat in ("close_created_workbook_verified", "excel_close_verified"):
        wb_name = metadata.get("wb_name")
        from .apps import excel
        ok, out = excel.close_workbook(wb_name=wb_name, saving=False)
        return ok, f"Chiusa cartella di lavoro '{wb_name}'." if ok else f"Errore rollback Excel: {out}"

    elif strat in ("excel_undo", "undo_excel"):
        from .apps import excel
        ok, out = excel.undo_last()
        return ok, "Annullata ultima modifica su Excel." if ok else f"Errore undo Excel: {out}"

    elif strat in ("close_created_doc_verified", "word_close_verified"):
        doc_name = metadata.get("doc_name")
        from .apps import word
        ok, out = word.close_active_document(doc_name=doc_name, saving=False)
        return ok, f"Chiuso documento '{doc_name}'." if ok else f"Errore rollback Word: {out}"

    elif strat in ("word_undo", "undo_word"):
        from .apps import word
        ok, out = word.undo_last()
        return ok, "Annullata ultima modifica su Word." if ok else f"Errore undo Word: {out}"

    elif strat == "restore_window_bounds":
        proc = metadata.get("app")
        bounds = metadata.get("bounds")
        if proc and bounds:
            from .apps import window
            ok, out = window.restore_window_bounds(proc, bounds)
            return ok, f"Ripristinata posizione finestra di {proc}." if ok else f"Errore rollback finestra: {out}"
        return False, "Metadati finestra mancanti"

    elif strat == "delete_if_empty":
        folder_path = metadata.get("path")
        if folder_path:
            from .apps import finder
            ok, out = finder.rollback_create_folder(folder_path)
            return ok, "Rimossa cartella creata." if ok else f"Errore rollback cartella: {out}"
        return False, "Percorso cartella mancante"

    return False, f"Strategia di rollback '{strategy}' non riconosciuta"
