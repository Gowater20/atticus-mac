#!/usr/bin/env python3
"""
System 1 Decision Engine & Intent Router
Fast semantic parsing, confidence estimation, parameter extraction, and execution.
Integrates with continuous learning (feedback/rollback) and human-in-the-loop disambiguation.
"""

import os
import re
import sys
import json
from .apps import word, window

LOREM_IPSUM_3 = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.\n"
    "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.\n"
    "Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur."
)

LOREM_IPSUM_1 = "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua."


class SystemOneEngine:
    def __init__(self):
        self.catalog_path = os.path.join(os.path.dirname(__file__), "apple_catalog.json")
        self.catalog = self._load_catalog()

    def _load_catalog(self):
        try:
            with open(self.catalog_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def analyze(self, text):
        """
        Analyzes the prompt and returns:
        (confidence_score: float, intent: str, params: dict, alternatives: list)
        """
        if not text:
            return 0.0, "none", {}, []

        t = text.strip().lower()

        # 1. Check Microsoft Word advanced multi-step document creation
        # e.g.: "apri file vuoto su word, titolo test in grassetto, scrivi un lorem ipsum di 3 righi..."
        is_word = bool(re.search(r'\b(word|documento word|file word|word vuoto)\b', t))
        is_create = bool(re.search(r'\b(apri|crea|scrivi|nuovo|file vuoto|documento)\b', t))

        if is_word and is_create:
            # High confidence Word document creation
            title = ""
            title_bold = True
            body = ""
            keyword = ""
            kw_bold = False
            kw_hl = "none"

            # Extract Title
            m_title = re.search(r'titolo\s+(?:con\s+|di\s+|[\'"]?)([^\,\;\n]+?)(?:[\'"]|\s+in grassetto|\s+grassetto|\,\s*scrivi|\,\s*con|$)', t)
            if m_title:
                title = m_title.group(1).strip().strip('\'"')

            # Extract Lorem Ipsum / Body
            if "lorem ipsum" in t:
                m_lines = re.search(r'(\d+)\s*(?:righe|righi|paragrafi|frasi)', t)
                if m_lines and int(m_lines.group(1)) <= 1:
                    body = LOREM_IPSUM_1
                else:
                    body = LOREM_IPSUM_3
            else:
                m_body = re.search(r'scrivi\s+(?:il\s+testo\s+|un\s+testo\s+|[\'"]?)([^\,\;]+)', t)
                if m_body:
                    body = m_body.group(1).strip().strip('\'"')

            # Extract Keyword formatting (bold / highlight)
            m_kw = re.search(r'(?:evidenzia|metti in grassetto|grassetto su)(?:\s+(?:in grassetto|la parola|il termine|la|il|lo|gli|le))*\s+[\'\"“]?([a-zA-Z0-9_\-]+)', t)
            if m_kw:
                keyword = m_kw.group(1).strip().strip('\'"“')
                kw_bold = "grassetto" in t[m_kw.start():] or "evidenzia in grassetto" in t
                kw_hl = "yellow" if "evidenzia" in t else "none"

            params = {
                "title": title or "Documento",
                "title_bold": title_bold,
                "title_size": 20,
                "body": body,
                "body_size": 12,
                "keyword": keyword,
                "kw_bold": kw_bold,
                "kw_hl": kw_hl
            }
            return 0.95, "word_create_and_format", params, []

        # 2. Check Word Save / Close
        if is_word and re.search(r'\b(salva|esporta in pdf)\b', t):
            as_pdf = "pdf" in t
            return 0.92, "word_save", {"as_pdf": as_pdf}, []

        if is_word and re.search(r'\b(chiudi documento|annulla documento)\b', t):
            return 0.90, "word_close", {"saving": False}, []

        # 3. Check Window Management
        # e.g.: "word a sinistra", "massimizza terminale", "safari a destra"
        m_win = re.match(r'^(?:sposta\s+|metti\s+)?(.+?)\s+(?:a|in|su)\s+(sinistra|destra|tutto schermo|schermo intero|centro)$', t)
        if m_win:
            app_raw = m_win.group(1).strip()
            pos_raw = m_win.group(2).lower()
            pos_map = {
                'sinistra': 'left',
                'destra': 'right',
                'tutto schermo': 'full',
                'schermo intero': 'full',
                'centro': 'center'
            }
            return 0.95, "window_place", {"app": app_raw, "where": pos_map.get(pos_raw, "left")}, []

        # 4. Moderate ambiguity / Disambiguation cases (0.40 <= confidence < 0.85)
        # e.g. "organizza documenti", "nuovo foglio", "chiudi tutto"
        if re.search(r'\b(organizza|sistema|prepara)\s+(?:i\s+)?(?:documenti|word|finestre)\b', t):
            alternatives = [
                {"label": "Affianca finestre Word a sinistra e destra", "intent": "window_split", "params": {"app": "Microsoft Word"}},
                {"label": "Crea nuovo documento vuoto su Word", "intent": "word_create_and_format", "params": {"title": "Appunti", "body": ""}},
                {"label": "Chiedi a Gemini (analisi avanzata)", "intent": "ask_gemini", "params": {"query": text}}
            ]
            return 0.65, "disambiguation", {}, alternatives

        # 5. Low confidence -> delegate to System 2 (Gemini)
        return 0.20, "ask_gemini", {"query": text}, []

    def execute(self, intent, params, prompt=""):
        """
        Executes a resolved System 1 intent.
        Registers action with atticus_feedback for grace-period rollback.
        Returns (success: bool, reply_message: str).
        """
        import atticus_feedback

        if intent == "word_create_and_format":
            title = params.get("title", "")
            body = params.get("body", "")
            ok, out = word.create_and_populate(
                doc_title=title,
                body_text=body,
                title_size=params.get("title_size", 20),
                title_bold=params.get("title_bold", True),
                body_size=params.get("body_size", 12)
            )
            if not ok:
                return False, f"Errore Word: {out}"

            # Format keyword if requested
            kw = params.get("keyword")
            if kw:
                word.format_keyword(kw, make_bold=params.get("kw_bold", False), highlight_color=params.get("kw_hl", "none"))

            # Register for rollback (closing without saving)
            atticus_feedback.record_action(
                prompt=prompt,
                action_type="word_create",
                rollback_cmd=['osascript', '-e', 'tell application "Microsoft Word" to if exists active document then close active document saving no'],
                metadata={"title": title}
            )
            rep_title = f" con titolo '{title}'" if title else ""
            rep_kw = f" e formattato '{kw}'" if kw else ""
            return True, f"Creato nuovo documento Word{rep_title}{rep_kw}."

        elif intent == "word_save":
            as_pdf = params.get("as_pdf", False)
            ext = "pdf" if as_pdf else "docx"
            path = f"~/Desktop/documento.{ext}"
            ok, out = word.save_and_close(path, as_pdf=as_pdf)
            if ok:
                return True, f"Documento Word salvato su {path}."
            return False, f"Impossibile salvare il documento: {out}"

        elif intent == "word_close":
            word.close_active_document(saving=params.get("saving", False))
            return True, "Chiuso documento Word."

        elif intent == "window_place":
            raw_app = params.get("app", "")
            try:
                import atticus_i18n
                app = atticus_i18n.resolve_app_alias(raw_app)
            except Exception:
                app = raw_app
            try:
                import atticus
                proc = atticus.proc_of(app) or atticus.app_named(app) or app
            except Exception:
                proc = app
            where = params.get("where", "left")
            ok, out = window.place_window(proc, where=where)
            if ok:
                where_it = {"left": "a sinistra", "right": "a destra", "full": "a tutto schermo", "center": "al centro"}.get(where, where)
                # Register rollback: center window or bring back via atticus helper
                att_bin = sys.argv[0] if sys.argv and os.path.exists(sys.argv[0]) else '/Users/fabio/Applications/Atticus.app/Contents/Resources/atticus.py'
                atticus_feedback.record_action(
                    prompt=prompt,
                    action_type="window_place",
                    rollback_cmd=[sys.executable, att_bin, '--place', proc, 'center', 'current'],
                    metadata={"app": proc, "where": where}
                )
                return True, f"{proc}: posizionato {where_it}."
            return False, f"Errore posizionamento {proc}."

        return False, "Azione non gestita da System 1"
