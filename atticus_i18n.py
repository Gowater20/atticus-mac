#!/usr/bin/env python3
"""
Atticus i18n & Italian Language Support Module
Provides seamless Italian NLU, command mapping, voice/speech localization,
STT number normalization and UI helpers.
Modular design to ensure upstream git pull compatibility.
"""

import os
import re
import subprocess

def is_italian_system():
    """Detect if macOS is set to Italian."""
    lang = os.environ.get('LC_ALL') or os.environ.get('LC_MESSAGES') or os.environ.get('LANG', '')
    if 'it' in lang.lower():
        return True
    try:
        r = subprocess.run(['defaults', 'read', '-g', 'AppleLanguages'], capture_output=True, text=True, timeout=1)
        if r.returncode == 0 and ('it' in r.stdout.lower() or 'it-IT' in r.stdout):
            return True
    except Exception:
        pass
    return False

# Italian system app aliases mapping common Italian names to macOS bundle names
APP_ALIASES_IT = {
    'word': 'Microsoft Word',
    'microsoft word': 'Microsoft Word',
    'excel': 'Microsoft Excel',
    'microsoft excel': 'Microsoft Excel',
    'powerpoint': 'Microsoft PowerPoint',
    'terminale': 'Terminal',
    'impostazioni': 'System Settings',
    'preferenze': 'System Settings',
    'preferenze di sistema': 'System Settings',
    'promemoria': 'Reminders',
    'calcolatrice': 'Calculator',
    'posta': 'Mail',
    'messaggi': 'Messages',
    'anteprima': 'Preview',
    'mappe': 'Maps',
    'orologio': 'Clock',
    'foto': 'Photos',
    'contatti': 'Contacts',
    'calendario': 'Calendar',
    'bussola': 'Compass',
    'note': 'Notes',
    'musica': 'Music',
    'libri': 'Books',
    'podcast': 'Podcasts',
    'borsa': 'Stocks',
    'meteo': 'Weather',
    'memo vocali': 'Voice Memos',
    'monitoraggio attività': 'Activity Monitor',
    'monitoraggio attivita': 'Activity Monitor',
    'disco': 'Disk Utility',
    'utilità disco': 'Disk Utility',
    'utilita disco': 'Disk Utility',
    'testo': 'TextEdit',
    'safari': 'Safari',
    'chrome': 'Google Chrome',
    'finder': 'Finder'
}

IT_NUMBERS = {
    'zero': '0', 'un': '1', 'uno': '1', 'una': '1',
    'due': '2', 'tre': '3', 'quattro': '4', 'cinque': '5',
    'sei': '6', 'sette': '7', 'otto': '8', 'nove': '9',
    'dieci': '10', 'undici': '11', 'dodici': '12', 'tredici': '13',
    'quattordici': '14', 'quindici': '15', 'sedici': '16', 'diciassette': '17',
    'diciotto': '18', 'diciannove': '19', 'venti': '20', 'trenta': '30'
}

def normalize_italian_numbers(text):
    """
    Converts Italian spelled-out numbers into digits.
    Especially useful for speech-to-text inputs (e.g. 'tre righe' -> '3 righe').
    """
    if not text:
        return text
    
    words = text.split()
    out = []
    for w in words:
        clean = re.sub(r'[^\w]', '', w.lower())
        if clean in IT_NUMBERS:
            # preserve punctuation around word
            digit = IT_NUMBERS[clean]
            replaced = w.lower().replace(clean, digit)
            out.append(replaced)
        else:
            out.append(w)
    return " ".join(out)

def resolve_app_alias(target):
    """Maps an Italian app name to its macOS English name if available."""
    if not target:
        return target
    t = target.strip().lower()
    return APP_ALIASES_IT.get(t, target)

FRONT_VERBS_IT = re.compile(
    r'\b(apri|aprimi|lancia|avvia|mostra|mostrami|porta in primo piano|porta avanti|'
    r'in primo piano|visualizza|passa a|vai a|vai su|schermo intero|tutto schermo|massimizza)\b',
    re.IGNORECASE
)

NEGATION_IT = re.compile(
    r'\b(non|senza|evita|dietro|in background|background|secondo piano|in secondo piano)\b',
    re.IGNORECASE
)

def asks_front_it(task):
    """Returns True if the task uses Italian verbs/phrases requesting the window/app in front."""
    if not task:
        return False
    t = task.strip().lower()
    if NEGATION_IT.search(t):
        return False
    return bool(FRONT_VERBS_IT.search(t))

def translate_fast_command(text):
    """
    Translates common Italian voice/text commands into the syntax expected by atticus.fast().
    Returns translated_text (or original text if no translation applied).
    """
    if not text:
        return text
    t = text.strip()
    low = t.lower()

    # Simple conversational words
    if low in ('ciao', 'buongiorno', 'buonasera', 'salve', 'ehi'):
        return 'hello'
    if low in ('chiudi tutto', 'chiudi tutte le app', 'chiudi finestre'):
        return 'close all'
    if low in ('grazie', 'molte grazie', 'ti ringrazio'):
        return 'thanks'

    # Window management translations
    m = re.match(r'^(?:sposta\s+|metti\s+)?(.+?)\s+(?:a|in|su)\s+(sinistra|destra|tutto schermo|schermo intero|centro)(?:\s+sul?\s+(monitor|display|schermo(?:\s+esterno)?|laptop|portatile))?$', low)
    if m:
        app = resolve_app_alias(m.group(1).strip())
        where = m.group(2)
        screen = m.group(3)
        where_en = {
            'sinistra': 'left',
            'destra': 'right',
            'tutto schermo': 'full',
            'schermo intero': 'full',
            'centro': 'center'
        }.get(where, 'left')
        screen_en = 'monitor' if screen and any(k in screen for k in ('monitor', 'display', 'esterno')) else ('laptop' if screen else 'current')
        return f"{app} {where_en} {screen_en}"

    return t

def localize_reply(reply, orig_query=""):
    """Translates common fast command English responses into natural Italian."""
    if not reply or not is_italian_system():
        return reply

    m = re.match(r'^Opened (.+)\.$', reply)
    if m:
        return f"Aperto {m.group(1)}."

    m = re.match(r'^Closed (.+)\.$', reply)
    if m:
        return f"Chiuso {m.group(1)}."

    m = re.match(r'^Searched (.+?)(?: on (.+?))?\.$', reply)
    if m:
        q = m.group(1)
        s = m.group(2)
        return f"Cercato {q} su {s}." if s else f"Cercato {q}."

    m = re.match(r'^Playing (.+)\.$', reply)
    if m:
        return f"Riproduzione di {m.group(1)}."

    m = re.match(r'^Added (.+?) to queue\.$', reply)
    if m:
        return f"Aggiunto {m.group(1)} alla coda."

    m = re.match(r'^(.+?): (left|right|full screen|center)(?: on (monitor|laptop))?\.$', reply)
    if m:
        app = m.group(1)
        where = m.group(2)
        sc = m.group(3)
        where_it = {
            'left': 'a sinistra',
            'right': 'a destra',
            'full screen': 'a tutto schermo',
            'center': 'al centro'
        }.get(where, where)
        sc_it = f" sul {'monitor esterno' if sc == 'monitor' else 'display del Mac'}" if sc else ""
        return f"{app}: {where_it}{sc_it}."

    if reply == "Okay.":
        return "Va bene."
    if "Review your feedback before opening GitHub." in reply:
        return "Controlla il tuo feedback prima di aprire GitHub."
    if "I have saved the procedure for next time." in reply:
        return "Ho salvato la procedura per la prossima volta."

    return reply

def system_prompt_addon():
    """System prompt instruction to be added to LLM calls."""
    return (
        "\n\n[LINGUA E LOCALIZZAZIONE IT]\n"
        "Se l'utente scrive o parla in italiano, rispondi sempre in italiano in modo chiaro, naturale e conciso. "
        "Mantieni i nomi propri originali delle applicazioni di sistema e terze parti macOS "
        "(es. 'Microsoft Word', 'Safari', 'Finder', 'Terminale', 'Preferenze di Sistema', 'Impostazioni'). "
        "Quando esegui comandi shell per aprire o mostrare applicazioni richieste dall'utente, portale sempre in primo piano."
    )
