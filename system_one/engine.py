#!/usr/bin/env python3
"""
System 1 Decision Engine with JEV Architecture (Judge - Evaluator - Verifier)
Calculates Joint Expected Value: JEV(a) = P(a)*U_fast - (1-P(a))*C_risk(a).
Provides context-aware semantic parsing, multi-turn state, safe execution,
and continuous learning feedback loop.
"""

import os
import re
import sys
import json
import time
from .apps import word, window, finder
from .context import get_frontmost_app, get_session_context, update_session_context
import atticus_feedback
import atticus_i18n

RISK_PENALTIES = {
    "low": 0.15,
    "medium": 0.45,
    "high": 1.10
}

EXEC_THRESHOLDS = {
    "low": 0.80,
    "medium": 0.86,
    "high": 0.93
}

DISAMB_THRESHOLDS = {
    "low": 0.40,
    "medium": 0.45,
    "high": 0.50
}

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

    def analyze(self, text, frontmost_app=None):
        """
        JEV Pipeline:
        1. Checks for active pending_choice resolution (1, 2, 3 / uno, due, tre).
        2. Stage 1: JUDGE - Token matching, slot filling, context boost.
        3. Stage 2: EVALUATOR - JEV formula & risk weighting.
        4. Returns (confidence: float, intent: str, params: dict, alternatives: list)
        """
        if not text:
            return 0.0, "none", {}, []

        norm_text = atticus_i18n.normalize_italian_numbers(text.strip())
        t = norm_text.lower()

        # Step 0: Check if input resolves an active pending choice card
        resolved, choice = atticus_feedback.resolve_pending_choice(norm_text)
        if resolved and choice:
            action_id = choice.get("action_id", "")
            if action_id == "system2.gemini":
                return 0.20, "ask_gemini", {"query": choice.get("extracted_params", {}).get("query", text)}, []
            return 0.99, action_id, choice.get("extracted_params", {}), []

        # Context detection
        explicit_front_passed = frontmost_app is not None
        if not frontmost_app:
            frontmost_app = get_frontmost_app()
        session_ctx = get_session_context()

        front_is_word = "word" in (frontmost_app or "").lower()
        is_word_explicit = bool(re.search(r'\b(word|documento word|file word|word vuoto)\b', t))
        session_is_word = (not explicit_front_passed) and (session_ctx.get("last_app") == "Microsoft Word")
        is_word = front_is_word or is_word_explicit

        # -------------------------------------------------------------
        # 1. Word: Create and Format Document (multi-step or standalone)
        # -------------------------------------------------------------
        is_create = bool(re.search(r'\b(apri|crea|scrivi|nuovo|file vuoto|documento vuoto|bozza)\b', t))
        if is_word and is_create and not re.search(r'\b(cartella|finestra)\b', t):
            title = ""
            body = ""
            keyword = ""
            kw_bold = False
            kw_hl = "none"

            # Title extraction - preserve original casing with re.IGNORECASE on norm_text
            m_title = re.search(
                r'titolo\s+(?:con\s+|di\s+|[\'"]?)([^\,\;\n]+?)(?:[\'"]|\s+in grassetto|\s+grassetto|\,\s*scrivi|\s+scrivi|\,\s*con|$)',
                norm_text,
                re.IGNORECASE
            )
            if m_title:
                title = m_title.group(1).strip().strip('\'"')

            # Body / Lorem Ipsum extraction
            if "lorem ipsum" in t:
                m_lines = re.search(r'(\d+)\s*(?:righe|righi|paragrafi|frasi)', t)
                if m_lines and int(m_lines.group(1)) <= 1:
                    body = LOREM_IPSUM_1
                else:
                    body = LOREM_IPSUM_3
            else:
                m_body = re.search(r'scrivi\s+(?:il\s+testo\s+|un\s+testo\s+|[\'"]?)([^\,\;]+)', norm_text, re.IGNORECASE)
                if m_body:
                    body = m_body.group(1).strip().strip('\'"')

            # Keyword formatting extraction
            m_kw = re.search(r'(?:evidenzia|metti in grassetto|grassetto su)(?:\s+(?:in grassetto|la parola|il termine|la|il|lo|gli|le))*\s+[\'\"“]?([a-zA-Z0-9_\-]+)', norm_text, re.IGNORECASE)
            if m_kw:
                keyword = m_kw.group(1).strip().strip('\'"“')
                kw_bold = "grassetto" in t[m_kw.start():] or "evidenzia in grassetto" in t
                kw_hl = "yellow" if "evidenzia" in t else "none"

            params = {
                "title": title or "Documento",
                "title_bold": True,
                "title_size": 20,
                "body": body,
                "body_size": 12,
                "keyword": keyword,
                "kw_bold": kw_bold,
                "kw_hl": kw_hl
            }
            risk = "low" if not body and not title else "medium"
            p_score = 0.96 if is_word_explicit else 0.88
            jev = self._calc_jev(p_score, risk)
            if jev >= 0.77:
                return p_score, "word_create_and_format", params, []

        # -------------------------------------------------------------
        # 2. Word: Standalone Format Keyword (e.g. "metti in grassetto la parola X")
        # -------------------------------------------------------------
        m_format_only = re.search(r'(?:metti in grassetto|evidenzia|grassetto su)(?:\s+(?:la parola|il termine|la|il|lo|gli|le))*\s+[\'\"“]?([a-zA-Z0-9_\-]+)', norm_text, re.IGNORECASE)
        if m_format_only and (is_word or session_is_word):
            kw = m_format_only.group(1).strip().strip('\'"“')
            is_bold = "grassetto" in t
            is_hl = "yellow" if "evidenzia" in t else "none"
            params = {"keyword": kw, "bold": is_bold, "highlight": is_hl}
            p_score = 0.90 if (is_word_explicit or front_is_word) else 0.84
            jev = self._calc_jev(p_score, "medium")
            if jev >= 0.75:
                return p_score, "word_format_keyword", params, []

        # -------------------------------------------------------------
        # 3. Word: Save / Export PDF
        # -------------------------------------------------------------
        if (is_word or session_is_word) and re.search(r'\b(salva|salvalo|esporta|esportalo)\b', t):
            as_pdf = "pdf" in t
            file_name = "documento.pdf" if as_pdf else "documento.docx"
            params = {"path": f"~/Desktop/{file_name}", "as_pdf": as_pdf}
            # High risk action: p_score=0.90 yields JEV = 0.90 - (0.10 * 1.10) = 0.79 >= 0.75
            p_score = 0.94 if is_word_explicit else (0.90 if front_is_word else 0.88)
            jev = self._calc_jev(p_score, "high")
            if jev >= 0.75:
                return p_score, "word_save", params, []

        # -------------------------------------------------------------
        # 4. Word: Close Document
        # -------------------------------------------------------------
        if (is_word or front_is_word) and re.search(r'\b(chiudi documento|annulla documento|chiudi word)\b', t):
            saving = "salvando" in t and "senza" not in t
            return 0.92, "word_close", {"saving": saving}, []

        # -------------------------------------------------------------
        # 5. Window Management (Snap Left/Right/Full/Center)
        # -------------------------------------------------------------
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
            p_score = 0.95
            return p_score, "window_place", {"app": app_raw, "where": pos_map.get(pos_raw, "left")}, []

        # Window Split / Side by Side
        if re.search(r'\b(affianca|dividi schermo|split|metti affiancate)\b', t) and "finestr" in t:
            return 0.92, "window_split", {"left": "Microsoft Word", "right": "Safari"}, []

        # -------------------------------------------------------------
        # 6. Finder Operations
        # -------------------------------------------------------------
        m_folder = re.search(
            r'\b(?:crea|fai|nuova)\s+cartella(?:\s+(?:chiamata|di nome|intitolata|[\'"]))?\s*([a-zA-Z0-9_\-\s]+)?',
            norm_text,
            re.IGNORECASE
        )
        if m_folder:
            f_name = (m_folder.group(1) or "Nuova Cartella").strip().strip('\'"')
            return 0.90, "finder_create_folder", {"name": f_name or "Nuova Cartella", "path": "~/Desktop"}, []

        # -------------------------------------------------------------
        # 7. Disambiguation (JEV Ambiguity Margin)
        # -------------------------------------------------------------
        if re.search(r'\b(organizza|sistema|prepara)\s+(?:i\s+)?(?:documenti|word|finestre|lavoro)\b', t):
            alternatives = [
                {
                    "choice_id": 1,
                    "action_id": "window_split",
                    "label": "Affianca finestre (Word a sinistra, Safari a destra)",
                    "extracted_params": {"left": "Microsoft Word", "right": "Safari"},
                    "jev_score": 0.72
                },
                {
                    "choice_id": 2,
                    "action_id": "word_create_and_format",
                    "label": "Crea nuovo documento vuoto su Word",
                    "extracted_params": {"title": "Appunti", "body": ""},
                    "jev_score": 0.68
                },
                {
                    "choice_id": 3,
                    "action_id": "system2.gemini",
                    "label": "Chiedi a Gemini (analisi avanzata)",
                    "extracted_params": {"query": text},
                    "jev_score": 1.0
                }
            ]
            atticus_feedback.save_pending_choice(text, alternatives, front_app=frontmost_app)
            return 0.65, "disambiguation", {}, alternatives
            # Save state in pending_choice.json with 25s TTL
            atticus_feedback.save_pending_choice(text, alternatives, front_app=frontmost_app)
            return 0.65, "disambiguation", {}, alternatives

        # Fallback to System 2 (Gemini)
        return 0.20, "ask_gemini", {"query": text}, []

    def _calc_jev(self, p_score, risk_level):
        """Calculates JEV = P(a)*1.0 - (1-P(a))*C_risk."""
        c_risk = RISK_PENALTIES.get(risk_level, 0.45)
        return round(p_score * 1.0 - (1.0 - p_score) * c_risk, 3)

    def execute(self, intent, params, prompt=""):
        """
        Executes a resolved System 1 intent.
        Performs pre-flight state snapshots and registers actions with atticus_feedback.
        Returns (success: bool, reply_message: str).
        """
        front_app = get_frontmost_app()

        if intent == "word_create_and_format":
            title = params.get("title", "")
            body = params.get("body", "")
            kw = params.get("keyword")

            ok, doc_name = word.create_and_populate(
                doc_title=title,
                body_text=body,
                title_size=params.get("title_size", 20),
                title_bold=params.get("title_bold", True),
                body_size=params.get("body_size", 12)
            )
            if not ok:
                return False, f"Errore Word: {doc_name}"

            if kw:
                word.format_keyword(kw, make_bold=params.get("kw_bold", False), highlight_color=params.get("kw_hl", "none"))

            # Update session context
            update_session_context(
                app="Microsoft Word",
                action_id="word_create_and_format",
                target_text=title or kw or body[:30],
                document_id=doc_name
            )

            # Register surgical rollback targeting ONLY doc_name
            atticus_feedback.record_action(
                prompt=prompt,
                action_type="word_create",
                metadata={"doc_name": doc_name, "title": title}
            )
            rep_title = f" con titolo '{title}'" if title else ""
            rep_kw = f" e formattato '{kw}'" if kw else ""
            return True, f"Creato nuovo documento Word{rep_title}{rep_kw}."

        elif intent == "word_format_keyword":
            kw = params.get("keyword")
            bold = params.get("bold", False)
            hl = params.get("highlight", "none")
            ok, out = word.format_keyword(kw, make_bold=bold, highlight_color=hl)
            if ok:
                update_session_context(app="Microsoft Word", action_id="word_format_keyword", target_text=kw)
                # Rollback via Word undo
                atticus_feedback.record_action(
                    prompt=prompt,
                    action_type="word_undo",
                    rollback_cmd=['osascript', '-e', 'tell application "Microsoft Word" to tell active document to undo'],
                    metadata={"keyword": kw}
                )
                action_desc = "in grassetto" if bold else ("evidenziato" if hl != "none" else "formattato")
                return True, f"Parola '{kw}' impostata {action_desc} in Word."
            return False, f"Impossibile formattare la parola: {out}"

        elif intent == "word_save":
            as_pdf = params.get("as_pdf", False)
            ext = "pdf" if as_pdf else "docx"
            path = params.get("path") or f"~/Desktop/documento.{ext}"
            ok, out = word.save_and_close(path, as_pdf=as_pdf)
            if ok:
                update_session_context(app="Microsoft Word", action_id="word_save", file_path=path)
                return True, f"Documento Word salvato su {path}."
            return False, f"Impossibile salvare il documento: {out}"

        elif intent == "word_close":
            word.close_active_document(saving=params.get("saving", False))
            return True, "Chiuso documento Word."

        elif intent == "window_place":
            raw_app = params.get("app", "")
            app = atticus_i18n.resolve_app_alias(raw_app)
            try:
                import atticus
                proc = atticus.proc_of(app) or atticus.app_named(app) or app
            except Exception:
                proc = app

            where = params.get("where", "left")

            # Pre-flight bounds snapshot for true geometric rollback
            pre_bounds = window.get_window_bounds(proc)

            ok, out = window.place_window(proc, where=where)
            if ok:
                where_it = {"left": "a sinistra", "right": "a destra", "full": "a tutto schermo", "center": "al centro"}.get(where, where)
                update_session_context(app=proc, action_id="window_place")
                atticus_feedback.record_action(
                    prompt=prompt,
                    action_type="window_place",
                    metadata={"app": proc, "where": where, "bounds": pre_bounds}
                )
                return True, f"{proc}: posizionato {where_it}."
            return False, f"Errore posizionamento {proc}."

        elif intent == "window_split":
            left_app = params.get("left", "Microsoft Word")
            right_app = params.get("right", "Safari")
            ok, msg = window.split_windows(left_app, right_app)
            if ok:
                return True, f"Finestre affiancate: {left_app} a sinistra, {right_app} a destra."
            return False, f"Impossibile affiancare le finestre."

        elif intent == "finder_create_folder":
            f_name = params.get("name", "Nuova Cartella")
            f_path = params.get("path", "~/Desktop")
            ok, out = finder.create_folder(folder_name=f_name, base_path=f_path)
            if ok:
                update_session_context(app="Finder", action_id="finder_create_folder", file_path=out)
                atticus_feedback.record_action(
                    prompt=prompt,
                    action_type="create_folder",
                    metadata={"path": out}
                )
                return True, f"Cartella '{f_name}' creata sul Desktop."
            return False, f"Impossibile creare la cartella: {out}"

        return False, "Azione non gestita da System 1"
