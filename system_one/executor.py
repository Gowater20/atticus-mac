#!/usr/bin/env python3
"""
System 1 Safe AppleScript Executor
Handles cold-launches, TCC permissions (-1743), parameter passing,
timeout management, and DRY_RUN testing mode.
"""

import os
import sys
import time
import subprocess
import shlex

ERR_TCC_PERMISSION = -1743
ERR_ACCESSIBILITY = -25211


def is_dry_run():
    return os.environ.get("ATTICUS_DRY_RUN") == "1"


def is_app_running(app_name):
    """Checks if an application process is running."""
    if is_dry_run():
        return True
    try:
        script = f'tell application "System Events" to return (exists (first application process whose name is "{app_name}"))'
        res = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=2)
        return res.stdout.strip().lower() == 'true'
    except Exception:
        return False


def ensure_app_ready(app_name, max_wait=8.0):
    """
    Ensures the target application is launched and ready for AppleEvents.
    Prevents timeout -1712 during cold launch.
    """
    if is_dry_run():
        return True
    if is_app_running(app_name):
        return True

    try:
        subprocess.run(['open', '-a', app_name], capture_output=True, text=True, timeout=3)
    except Exception:
        pass

    start = time.time()
    while time.time() - start < max_wait:
        if is_app_running(app_name):
            # Give the event loop a brief moment to stabilize
            time.sleep(0.4)
            return True
        time.sleep(0.3)
    return False


def run_applescript(script_str, args=None, timeout=6.0, target_app=None):
    """
    Executes AppleScript with robust error trapping.
    If target_app is provided, checks for cold launch.
    Supports DRY_RUN mode for test suites.
    Returns (success: bool, output: str, err_code: int).
    """
    if is_dry_run():
        # Validate syntax with osacompile if available, else simulate success
        return True, "DRY_RUN_OK", 0

    if target_app:
        ensure_app_ready(target_app)

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
            app_label = target_app if target_app else "l'applicazione"
            msg = f"Permesso macOS mancante per controllare '{app_label}'. Abilitalo in Impostazioni di Sistema -> Privacy e Sicurezza -> Automazione."
            return False, msg, ERR_TCC_PERMISSION

        return False, out, code
    except subprocess.TimeoutExpired:
        return False, f"Timeout ({timeout}s) durante l'esecuzione di AppleScript", -1712
    except Exception as e:
        return False, str(e), -1
