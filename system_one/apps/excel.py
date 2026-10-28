#!/usr/bin/env python3
"""
System 1 Native Automation for Microsoft Excel (macOS)
Direct AppleScript dictionary integration without GUI scripting.
Provides safe workbook creation, tabular data/headers insertion,
cell formatting (bold, currency), pre-flight snapshot, and surgical rollback.
"""

import os
from typing import List, Optional, Tuple
from ..executor import run_applescript

APP_NAME = "Microsoft Excel"


def _escape_as_string(text: str) -> str:
    """Escapes string and converts newlines to AppleScript string constants."""
    if not text:
        return '""'
    escaped = text.replace('\\', '\\\\').replace('"', '\\"')
    parts = escaped.split('\n')
    if len(parts) == 1:
        return f'"{parts[0]}"'
    joined = ' & return & '.join(f'"{p}"' for p in parts)
    return joined


def col_letter(col_idx: int) -> str:
    """Converts 1-based column index to Excel column letters (1->A, 2->B, 27->AA)."""
    res = ""
    while col_idx > 0:
        col_idx, rem = divmod(col_idx - 1, 26)
        res = chr(65 + rem) + res
    return res or "A"


def get_active_workbook_info() -> Tuple[bool, str, str]:
    """
    Returns pre-flight snapshot: (has_wb: bool, wb_name: str, sheet_name: str).
    """
    script = '''
    tell application "Microsoft Excel"
        if not (exists active workbook) then
            return "NO_WORKBOOK"
        end if
        set wbName to name of active workbook
        set sName to name of active sheet
        return wbName & "|" & sName
    end tell
    '''
    ok, out, _ = run_applescript(script, timeout=3.0, target_app=APP_NAME)
    if ok and out and out != "NO_WORKBOOK" and "|" in out:
        parts = out.split("|", 1)
        return True, parts[0].strip(), parts[1].strip()
    return False, "", ""


def create_workbook(title: str = "", headers: Optional[List[str]] = None) -> Tuple[bool, str]:
    """
    Creates a new blank Excel workbook, optionally adds a formatted title and/or table headers.
    Returns (success: bool, wb_name_or_err: str). Captures wb_name for surgical rollback.
    """
    esc_title = _escape_as_string(title)
    hdrs = [h for h in (headers or []) if h]

    # Build script lines
    lines = [
        'tell application "Microsoft Excel"',
        '    activate',
        '    set newBook to make new workbook',
        '    set wbName to name of newBook',
        '    set theSheet to active sheet of newBook'
    ]

    start_row = 1
    if title:
        lines.append(f'    set value of cell 1 of row 1 of theSheet to {esc_title}')
        lines.append('    set font size of font object of range "A1" of theSheet to 16')
        lines.append('    set bold of font object of range "A1" of theSheet to true')
        start_row = 3  # Leave blank row after title for table

    if hdrs:
        for idx, h in enumerate(hdrs, 1):
            esc_h = _escape_as_string(h)
            lines.append(f'    set value of cell {idx} of row {start_row} of theSheet to {esc_h}')
        end_col = col_letter(len(hdrs))
        hdr_range = f"A{start_row}:{end_col}{start_row}"
        lines.append(f'    set bold of font object of range "{hdr_range}" of theSheet to true')

    lines.append('    return wbName')
    lines.append('end tell')

    script = "\n".join(lines)
    ok, out, _ = run_applescript(script, timeout=8.0, target_app=APP_NAME)
    if ok:
        wb_name = out.strip() or "Cartella"
        return True, wb_name
    return False, out


def insert_table(headers: Optional[List[str]] = None, start_row: Optional[int] = None) -> Tuple[bool, str]:
    """
    Inserts tabular headers in the active Excel worksheet.
    Finds next available row automatically if start_row is None.
    """
    hdrs = [h for h in (headers or []) if h]
    if not hdrs:
        return False, "Nessuna colonna specificata per la tabella"

    lines = [
        'tell application "Microsoft Excel"',
        '    activate',
        '    if not (exists active workbook) then',
        '        make new workbook',
        '    end if',
        '    set theSheet to active sheet'
    ]

    if start_row is not None and start_row > 0:
        lines.append(f'    set targetRow to {int(start_row)}')
    else:
        lines.append('    set targetRow to 1')
        lines.append('    if (value of cell 1 of row 1 of theSheet) is not "" then')
        lines.append('        set uRange to used range of theSheet')
        lines.append('        set targetRow to (first row index of uRange) + (count rows of uRange) + 1')
        lines.append('    end if')

    for idx, h in enumerate(hdrs, 1):
        esc_h = _escape_as_string(h)
        lines.append(f'    set value of cell {idx} of row targetRow of theSheet to {esc_h}')

    end_col = col_letter(len(hdrs))
    lines.append(f'    set startCell to cell 1 of row targetRow of theSheet')
    lines.append(f'    set endCell to cell {len(hdrs)} of row targetRow of theSheet')
    lines.append(f'    set bold of font object of (get range startCell to endCell) to true')
    lines.append('    return "OK"')
    lines.append('end tell')

    script = "\n".join(lines)
    ok, out, _ = run_applescript(script, timeout=6.0, target_app=APP_NAME)
    return ok, out


def format_cells(range_ref: str = "selection", bold: bool = True, currency: bool = False) -> Tuple[bool, str]:
    """
    Formats the given cell range or selection in the active sheet.
    Supports bold styling and currency formatting.
    """
    r_clean = (range_ref or "selection").strip()
    bold_str = "true" if bold else "false"

    lines = [
        'tell application "Microsoft Excel"',
        '    activate',
        '    if not (exists active workbook) then return "NO_WORKBOOK"'
    ]

    if r_clean.lower() in ("selection", "selected", "selezionate", "selezione", ""):
        lines.append('    set targetRange to selection')
    else:
        esc_r = _escape_as_string(r_clean)
        lines.append(f'    set targetRange to range {esc_r} of active sheet')

    if bold:
        lines.append(f'    set bold of font object of targetRange to {bold_str}')

    if currency:
        lines.append('    set number format of targetRange to "€ #,##0.00"')

    lines.append('    return "OK"')
    lines.append('end tell')

    script = "\n".join(lines)
    ok, out, _ = run_applescript(script, timeout=6.0, target_app=APP_NAME)
    return ok, out


def close_workbook(wb_name: Optional[str] = None, saving: bool = False) -> Tuple[bool, str]:
    """
    Closes the specified workbook (by name) or the active workbook.
    Used for surgical verified rollback (close_created_workbook_verified).
    """
    save_str = "yes" if saving else "no"
    if wb_name:
        esc_name = _escape_as_string(wb_name)
        script = f'''
        tell application "Microsoft Excel"
            if exists workbook {esc_name} then
                close workbook {esc_name} saving {save_str}
                return "CLOSED"
            end if
            return "NOT_FOUND"
        end tell
        '''
    else:
        script = f'''
        tell application "Microsoft Excel"
            if exists active workbook then
                close active workbook saving {save_str}
                return "CLOSED"
            end if
            return "NO_WORKBOOK"
        end tell
        '''
    ok, out, _ = run_applescript(script, timeout=4.0, target_app=APP_NAME)
    return ok, out


def undo_last() -> Tuple[bool, str]:
    """
    Triggers native Excel undo.
    Used for rollback strategy excel_undo.
    """
    script = '''
    tell application "Microsoft Excel"
        undo
        return "OK"
    end tell
    '''
    ok, out, _ = run_applescript(script, timeout=3.0, target_app=APP_NAME)
    return ok, out
