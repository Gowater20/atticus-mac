#!/usr/bin/env python3
"""
System 1 Native Automation for Microsoft Word (macOS)
Direct AppleScript dictionary integration without GUI scripting.
Provides safe document creation, formatting, keyword styling, saving, and targeted rollback.
"""

import os
import subprocess
from ..executor import run_applescript

APP_NAME = "Microsoft Word"


def _escape_as_string(text):
    """Escapes string and converts newlines to AppleScript string constants."""
    if not text:
        return '""'
    escaped = text.replace('\\', '\\\\').replace('"', '\\"')
    parts = escaped.split('\n')
    if len(parts) == 1:
        return f'"{parts[0]}"'
    joined = ' & return & '.join(f'"{p}"' for p in parts)
    return joined


def get_active_doc_info():
    """
    Returns pre-flight snapshot: (has_doc: bool, doc_name: str, char_count: int).
    """
    script = '''
    tell application "Microsoft Word"
        if not (exists active document) then
            return "NO_DOC"
        end if
        set dName to name of active document
        set cCount to count characters of text object of active document
        return dName & "|" & (cCount as text)
    end tell
    '''
    ok, out, _ = run_applescript(script, timeout=3.0, target_app=APP_NAME)
    if ok and out and out != "NO_DOC" and "|" in out:
        parts = out.split("|", 1)
        try:
            return True, parts[0].strip(), int(parts[1].strip())
        except Exception:
            return True, parts[0].strip(), 0
    return False, "", 0


def create_and_populate(doc_title="", body_text="", title_size=20, title_bold=True, body_size=12):
    """
    Creates a new blank Word document and writes formatted title and body.
    Returns (success: bool, doc_name_or_err: str).
    """
    esc_title = _escape_as_string(doc_title)
    esc_body = _escape_as_string(body_text)
    bold_str = "true" if title_bold else "false"

    script = f'''
    tell application "Microsoft Word"
        activate
        set newDoc to make new document
        set dName to name of newDoc
        set myRange to text object of newDoc
        
        -- 1. Titolo
        if {esc_title} is not "" then
            set content of myRange to ({esc_title} & return)
            set font size of font object of myRange to {int(title_size)}
            set bold of font object of myRange to {bold_str}
            set myRange to collapse range myRange direction collapse end
        end if
        
        -- 2. Corpo
        if {esc_body} is not "" then
            set content of myRange to {esc_body}
            set font size of font object of myRange to {int(body_size)}
            set bold of font object of myRange to false
        end if
        
        return dName
    end tell
    '''
    ok, out, _ = run_applescript(script, timeout=8.0, target_app=APP_NAME)
    if ok:
        doc_name = out.strip() or "Documento"
        return True, doc_name
    return False, out


def insert_title(doc_title="", title_size=20, title_bold=True):
    """Inserts a formatted title in the active Word document."""
    esc_title = _escape_as_string(doc_title)
    bold_str = "true" if title_bold else "false"
    script = f'''
    tell application "Microsoft Word"
        activate
        if not (exists active document) then
            make new document
        end if
        set myRange to text object of active document
        set startRange to create range active document start 0 end 0
        set content of startRange to ({esc_title} & return)
        set font size of font object of startRange to {int(title_size)}
        set bold of font object of startRange to {bold_str}
        return name of active document
    end tell
    '''
    ok, out, _ = run_applescript(script, timeout=5.0, target_app=APP_NAME)
    return ok, out


def format_keyword(keyword, make_bold=False, highlight_color="yellow"):
    """
    Finds and formats a keyword in the active document.
    Uses Word's find and replace object cleanly without infinite repeat-loops.
    """
    if not keyword:
        return False, "Nessuna parola specificata"

    esc_kw = _escape_as_string(keyword)
    bold_str = "true" if make_bold else "false"

    # Map color names
    hl_str = "yellow"
    if highlight_color in ("none", "no", ""):
        hl_str = "no highlight"
    elif highlight_color in ("green", "bright green"):
        hl_str = "bright green"

    script = f'''
    tell application "Microsoft Word"
        activate
        if not (exists active document) then return "NO_DOC"
        
        set myFind to find object of text object of active document
        clear formatting myFind
        set forward of myFind to true
        set content of myFind to {esc_kw}
        
        -- Configura la formattazione di sostituzione
        set repObj to replacement of myFind
        clear formatting repObj
        set content of repObj to "^&"
        if {bold_str} then
            set bold of font object of repObj to true
        end if
        if "{hl_str}" is not "no highlight" then
            set highlight color index of repObj to {hl_str}
        end if
        
        execute find myFind replace replace all
        return "OK"
    end tell
    '''
    ok, out, _ = run_applescript(script, timeout=6.0, target_app=APP_NAME)
    return ok, out


def save_and_close(file_path="~/Desktop/documento.docx", as_pdf=False):
    """Saves the active document safely, escaping paths correctly."""
    full_path = os.path.expanduser(file_path)
    esc_path = _escape_as_string(full_path)

    if as_pdf:
        script = f'''
        tell application "Microsoft Word"
            activate
            if not (exists active document) then return "NO_DOC"
            set myDoc to active document
            save as myDoc file name {esc_path} file format format PDF
            return "OK"
        end tell
        '''
    else:
        script = f'''
        tell application "Microsoft Word"
            activate
            if not (exists active document) then return "NO_DOC"
            set myDoc to active document
            save as myDoc file name {esc_path} file format format document
            return "OK"
        end tell
        '''
    ok, out, _ = run_applescript(script, timeout=6.0, target_app=APP_NAME)
    return ok, out


def close_active_document(doc_name=None, saving=False):
    """
    Closes the active document or a specific document name if provided.
    """
    save_str = "yes" if saving else "no"
    if doc_name:
        esc_name = _escape_as_string(doc_name)
        script = f'''
        tell application "Microsoft Word"
            if exists document {esc_name} then
                close document {esc_name} saving {save_str}
                return "CLOSED"
            end if
            return "NOT_FOUND"
        end tell
        '''
    else:
        script = f'''
        tell application "Microsoft Word"
            if exists active document then
                close active document saving {save_str}
                return "CLOSED"
            end if
            return "NO_DOC"
        end tell
        '''
    ok, out, _ = run_applescript(script, timeout=4.0, target_app=APP_NAME)
    return ok, out


def undo_last():
    """Triggers native Word undo."""
    script = '''
    tell application "Microsoft Word"
        if exists active document then
            tell active document to undo
            return "OK"
        end if
        return "NO_DOC"
    end tell
    '''
    ok, out, _ = run_applescript(script, timeout=3.0, target_app=APP_NAME)
    return ok, out
