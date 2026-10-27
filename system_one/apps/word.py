#!/usr/bin/env python3
"""
System 1 Native Automation for Microsoft Word (macOS)
Direct AppleScript integration without GUI scripting or mouse simulation.
Supports fast document creation, formatting, keyword styling, saving, and rollback.
"""

import os
import subprocess
import shlex

def _escape_as_string(text):
    """Escapes string and converts newlines to AppleScript constants."""
    if not text:
        return '""'
    escaped = text.replace('\\', '\\\\').replace('"', '\\"')
    parts = escaped.split('\n')
    if len(parts) == 1:
        return f'"{parts[0]}"'
    joined = ' & return & '.join(f'"{p}"' for p in parts)
    return joined


def run_applescript(script_str, timeout=5):
    """Runs an AppleScript block and returns (success: bool, output: str)."""
    try:
        r = subprocess.run(['osascript', '-e', script_str],
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout or r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return False, "Timeout execution"
    except Exception as e:
        return False, str(e)


def create_and_populate(doc_title="", body_text="", title_size=20, title_bold=True, body_size=12):
    """
    Creates a new blank Word document and writes formatted title and body.
    Zero-mouse execution via AppleScript dictionary.
    """
    esc_title = _escape_as_string(doc_title)
    esc_body = _escape_as_string(body_text)
    bold_str = "true" if title_bold else "false"

    script = f'''
    tell application "Microsoft Word"
        activate
        set newDoc to make new document
        set myRange to text object of newDoc
        
        -- 1. Inserimento e formattazione Titolo
        if {esc_title} is not "" then
            set content of myRange to ({esc_title} & return)
            set font size of font object of myRange to {int(title_size)}
            set bold of font object of myRange to {bold_str}
            set myRange to collapse range myRange direction collapse end
        end if
        
        -- 2. Inserimento e formattazione Corpo
        if {esc_body} is not "" then
            set content of myRange to ({esc_body} & return)
            set font size of font object of myRange to {int(body_size)}
            set bold of font object of myRange to false
        end if
        return "SUCCESS"
    end tell
    '''
    return run_applescript(script)


def format_keyword(target_word, make_bold=False, highlight_color="none"):
    """
    Finds and formats all occurrences of target_word in the active Word document.
    """
    if not target_word:
        return False, "Target word missing"
    
    esc_word = _escape_as_string(target_word)
    bold_cmd = "set bold of font object to true" if make_bold else ""
    
    hl_snippet = ""
    if highlight_color in ("yellow", "green", "red", "pink", "turquoise"):
        color_map = {
            "yellow": "yellow",
            "green": "bright green",
            "red": "red",
            "pink": "pink",
            "turquoise": "turquoise"
        }
        as_color = color_map.get(highlight_color, "yellow")
        hl_snippet = f'''
        set searchRange to text object of active document
        tell find object of searchRange
            clear formatting
            set content to {esc_word}
            repeat while execute find
                set highlight color index of searchRange to {as_color}
                set searchRange to collapse range searchRange direction collapse end
            end repeat
        end tell
        '''

    script = f'''
    tell application "Microsoft Word"
        if not (exists active document) then return "NO_DOC"
        set findRange to text object of active document
        
        tell find object of findRange
            clear formatting
            set content to {esc_word}
            set match case to false
            set match whole word to true
            
            tell replacement of it
                clear formatting
                set content to {esc_word}
                {bold_cmd}
            end tell
            
            execute find replace replace all
        end tell
        
        {hl_snippet}
        return "SUCCESS"
    end tell
    '''
    return run_applescript(script)


def save_and_close(posix_path="~/Desktop/documento.docx", as_pdf=False, force_rollback=False):
    """
    Saves and closes active document, or forces rollback closing without saving.
    """
    full_path = os.path.expanduser(posix_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    
    fmt = "pdf" if as_pdf else "docx"
    rollback_str = "true" if force_rollback else "false"

    script = f'''
    tell application "Microsoft Word"
        if not (exists active document) then return "NO_DOC"
        set activeDoc to active document
        
        if {rollback_str} then
            close activeDoc saving no
            return "ROLLED_BACK"
        end if
        
        set macPath to (POSIX file "{full_path}") as string
        try
            if "{fmt}" is "pdf" then
                save as activeDoc file name macPath file format format PDF
            else
                save as activeDoc file name macPath file format format document
            end if
            close activeDoc saving no
            return "SUCCESS"
        on error errMsg
            close activeDoc saving no
            return "ERROR_ROLLED_BACK"
        end try
    end tell
    '''
    return run_applescript(script)


def close_active_document(saving=False):
    """Closes the current active document with or without saving."""
    save_str = "yes" if saving else "no"
    script = f'''
    tell application "Microsoft Word"
        if (exists active document) then
            close active document saving {save_str}
            return "CLOSED"
        end if
        return "NO_DOC"
    end tell
    '''
    return run_applescript(script)

