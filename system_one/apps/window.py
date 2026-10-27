#!/usr/bin/env python3
"""
System 1 Window Management Module
Handles window positioning, dynamic multi-monitor geometry,
pre-flight bounds capture, and true geometric rollback.
"""

import os
import sys
import subprocess
from ..executor import run_applescript


def get_screen_bounds():
    """Returns dynamic screen dimensions (width, height) using System Events."""
    if os.environ.get("ATTICUS_DRY_RUN") == "1":
        return 1728, 1117

    script = 'tell application "Finder" to get bounds of window of desktop'
    ok, out, _ = run_applescript(script, timeout=2.0)
    if ok and out:
        try:
            # Output is format: "0, 0, 1728, 1117"
            parts = [int(p.strip()) for p in out.split(",")]
            if len(parts) == 4:
                return parts[2] - parts[0], parts[3] - parts[1]
        except Exception:
            pass
    return 1920, 1080


def get_window_bounds(proc_name):
    """
    Captures pre-flight window bounds: (x, y, width, height).
    Used for surgical geometric rollback.
    """
    if os.environ.get("ATTICUS_DRY_RUN") == "1":
        return {"x": 100, "y": 100, "width": 800, "height": 600}

    script = f'''
    tell application "System Events"
        if not (exists process "{proc_name}") then return "NO_PROC"
        tell process "{proc_name}"
            if not (exists (window 1)) then return "NO_WIN"
            set p to position of window 1
            set s to size of window 1
            return (item 1 of p as text) & "," & (item 2 of p as text) & "," & (item 1 of s as text) & "," & (item 2 of s as text)
        end tell
    end tell
    '''
    ok, out, _ = run_applescript(script, timeout=2.0)
    if ok and out and "," in out:
        try:
            pts = [int(x.strip()) for x in out.split(",")]
            if len(pts) == 4:
                return {"x": pts[0], "y": pts[1], "width": pts[2], "height": pts[3]}
        except Exception:
            pass
    return None


def restore_window_bounds(proc_name, bounds):
    """Restores the exact previous position and size of a window."""
    if not bounds or not isinstance(bounds, dict):
        return False, "Nessun bound precedente"

    x = bounds.get("x", 0)
    y = bounds.get("y", 25)
    w = bounds.get("width", 800)
    h = bounds.get("height", 600)

    script = f'''
    tell application "System Events"
        if exists process "{proc_name}" then
            tell process "{proc_name}"
                if exists (window 1) then
                    set position of window 1 to {{{x}, {y}}}
                    set size of window 1 to {{{w}, {h}}}
                    return "OK"
                end if
            end tell
        end if
        return "NO_PROC"
    end tell
    '''
    ok, out, _ = run_applescript(script, timeout=3.0)
    return ok, out


def place_window(proc_name, where="left"):
    """
    Places a window dynamically using actual desktop dimensions.
    Supported where: left, right, full, center.
    """
    screen_w, screen_h = get_screen_bounds()
    menu_bar_h = 25
    usable_h = screen_h - menu_bar_h

    if where == "left":
        x = 0
        y = menu_bar_h
        w = screen_w // 2
        h = usable_h
    elif where == "right":
        x = screen_w // 2
        y = menu_bar_h
        w = screen_w // 2
        h = usable_h
    elif where in ("full", "fullscreen"):
        x = 0
        y = menu_bar_h
        w = screen_w
        h = usable_h
    elif where == "center":
        w = int(screen_w * 0.7)
        h = int(usable_h * 0.8)
        x = (screen_w - w) // 2
        y = menu_bar_h + (usable_h - h) // 2
    else:
        x = 0
        y = menu_bar_h
        w = screen_w // 2
        h = usable_h

    script = f'''
    tell application "System Events"
        if exists process "{proc_name}" then
            tell process "{proc_name}"
                set frontmost to true
                if exists (window 1) then
                    set position of window 1 to {{{x}, {y}}}
                    set size of window 1 to {{{w}, {h}}}
                    return "OK"
                end if
            end tell
        end if
        return "NO_WIN"
    end tell
    '''
    ok, out, _ = run_applescript(script, timeout=3.0)
    return ok, out


def split_windows(app_left="Microsoft Word", app_right="Safari"):
    """Splits two applications side by side (left and right)."""
    ok_l, _ = place_window(app_left, where="left")
    ok_r, _ = place_window(app_right, where="right")
    return (ok_l or ok_r), f"{app_left} a sinistra, {app_right} a destra"
