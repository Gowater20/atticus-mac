#!/usr/bin/env python3
"""
Atticus i18n & Italian Language Support Module
Provides seamless Italian NLU, command mapping, voice/speech localization and UI helpers.
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
    'testo': 'TextEdit'
}

def resolve_app_alias(target):
    """Maps an Italian app name to its macOS English name if available."""
    if not target:
        return target
    t = target.strip().lower()
    return APP_ALIASES_IT.get(t, target)

# Italian verbs indicating the user wants the window/app in front
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
    conversational = {
        'grazie': 'thank you',
        'grazie mille': 'thank you',
        'annulla': 'cancel',
        'niente': 'nothing',
        'lascia stare': 'cancel',
        'si': 'yes',
        'sì': 'yes',
        'certo': 'yes',
        'va bene': 'okay',
        'ok': 'okay'
    }
    if low in conversational:
        return conversational[low]

    # Open / Launch: "apri word", "lancia safari", "avvia terminale", "apri l'app note"
    m = re.match(r'^(?:apri(?:mi)?|lancia|avvia)(?:\s+(?:l[\'\’]|il |la |lo |gli |le |i |un |una |l\'app |l\'applicazione ))?\s*(.+)$', t, re.I)
    if m:
        target = m.group(1).strip()
        # Check window positioning suffix: es. "apri word a sinistra", "apri safari a tutto schermo"
        m_pos = re.search(r'\s+(?:a|in|su)\s+(sinistra|destra|tutto schermo|schermo intero|centro)$', target, re.I)
        if m_pos:
            pos_raw = m_pos.group(1).lower()
            app_raw = target[:m_pos.start()].strip()
            app_resolved = resolve_app_alias(app_raw)
            pos_map = {
                'sinistra': 'left',
                'destra': 'right',
                'tutto schermo': 'full screen',
                'schermo intero': 'full screen',
                'centro': 'center'
            }
            return f"open {app_resolved} on {pos_map.get(pos_raw, 'current')}"
        app_resolved = resolve_app_alias(target)
        return f"open {app_resolved}"

    # Close / Quit: "chiudi word", "esci da safari", "termina chrome"
    m = re.match(r'^(?:chiudi|esci da|termina)(?:\s+(?:l[\'\’]|il |la |lo |gli |le |i |l\'app |l\'applicazione ))?\s*(.+)$', t, re.I)
    if m:
        app_resolved = resolve_app_alias(m.group(1).strip())
        return f"close {app_resolved}"

    # Search: "cerca ricetta tiramisu", "cerca su google meteo roma"
    m = re.match(r'^(?:cerca(?:mi)?|trova)(?:\s+(?:su google|su internet|in rete|sul web))?(?:\s+(?:per|di))?\s+(.+)$', t, re.I)
    if m:
        return f"search for {m.group(1).strip()}"

    # Window placement: "word a sinistra", "safari a destra", "massimizza terminale", "chrome a tutto schermo"
    m = re.match(r'^(?:massimizza|ingrandisci)\s+(.+)$', t, re.I)
    if m:
        app_resolved = resolve_app_alias(m.group(1).strip())
        return f"full screen {app_resolved}"

    m = re.match(r'^(.+?)\s+(?:a|in|su)\s+(sinistra|destra|tutto schermo|schermo intero|centro)$', t, re.I)
    if m:
        app_raw = m.group(1).strip()
        pos_raw = m.group(2).lower()
        app_resolved = resolve_app_alias(app_raw)
        pos_map = {
            'sinistra': 'left',
            'destra': 'right',
            'tutto schermo': 'full screen',
            'schermo intero': 'full screen',
            'centro': 'center'
        }
        return f"{app_resolved} {pos_map.get(pos_raw, 'current')}"

    # Music / Spotify: "riproduci i coldplay", "metti musica jazz"
    m = re.match(r'^(?:riproduci|metti|suona|ascolta)\s+(?:la canzone |il brano |la musica |il pezzo )?(.+)$', t, re.I)
    if m:
        return f"play {m.group(1).strip()}"

    # Learn / Remember: "ricorda come fare una riunione zoom"
    m = re.match(r'^ricorda(?:ti)?\s+come\s+(.+)$', t, re.I)
    if m:
        return f"remember how to {m.group(1).strip()}"

    return text

def localize_reply(reply, original_text=""):
    """Translates common standard English replies to natural Italian if user spoke Italian."""
    if not reply or not isinstance(reply, str):
        return reply

    was_italian = asks_front_it(original_text) or any(
        w in original_text.lower().split()
        for w in ('apri', 'chiudi', 'cerca', 'metti', 'riproduci', 'grazie', 'ciao', 'sì', 'si', 'va', 'bene', 'terminale')
    )
    if not was_italian and not is_italian_system():
        return reply

    # Direct replacements for fast replies
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

