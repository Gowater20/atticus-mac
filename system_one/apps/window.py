#!/usr/bin/env python3
"""
System 1 Native Window Management (macOS)
Wraps window placement operations: left, right, full screen, center.
"""

import sys
import subprocess

def _get_atticus():
    return sys.modules.get('atticus') or sys.modules.get('__main__')

def place_window(app_name, where="left", screen="current"):
    """
    Places app_name in specified position (left, right, full, center).
    Returns (success: bool, description: str).
    """
    att = _get_atticus()
    if att and hasattr(att, 'place') and hasattr(att, 'proc_of'):
        proc = att.proc_of(app_name) or app_name
        res = att.place(proc, where, screen)
        if att.place_failed(res):
            return False, res
        return True, res

    # Standalone fallback via AppleScript
    script = f'''
    tell application "System Events"
        if exists process "{app_name}" then
            tell process "{app_name}"
                set frontmost to true
                try
                    tell window 1
                        -- Simple placement
                        if "{where}" is "left" then
                            set position to {{0, 25}}
                            set size to {{960, 1055}}
                        else if "{where}" is "right" then
                            set position to {{960, 25}}
                            set size to {{960, 1055}}
                        else if "{where}" is "full" then
                            set position to {{0, 25}}
                            set size to {{1920, 1055}}
                        else if "{where}" is "center" then
                            set position to {{480, 200}}
                            set size to {{1200, 800}}
                        end if
                    end tell
                    return "SUCCESS"
                on error
                    return "WINDOW_ERROR"
                end try
            end tell
        end if
        return "NO_PROCESS"
    end tell
    '''
    try:
        r = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=3)
        return r.returncode == 0, r.stdout.strip()
    except Exception as e:
        return False, str(e)

