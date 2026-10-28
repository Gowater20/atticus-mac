#!/usr/bin/env python3
"""
System 1 Decision Engine with JEV Architecture (Judge - Evaluator - Verifier)
Calculates Joint Expected Value: JEV(a) = P(a)*U_fast - (1-P(a))*C_risk(a).
Provides context-aware semantic parsing, multi-turn state, safe execution,
and continuous learning feedback loop.
Supports both neural probability scoring via Rizzo Flow and heuristic rule-based JEV.
"""

import os
import re
import sys
import json
import time
from .apps import word, window, finder, excel
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

    def _load_settings(self):
        """Loads settings from config directory with test isolation support."""
        cfg_dir = getattr(atticus_feedback, "CONFIG_DIR", None)
        std_dir = os.path.expanduser("~/.config/atticus")
        if cfg_dir and os.path.abspath(cfg_dir) != os.path.abspath(std_dir):
            test_settings = os.path.join(cfg_dir, "settings.json")
            if os.path.exists(test_settings):
                try:
                    with open(test_settings, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
            return {}
        settings_path = os.path.join(std_dir, "settings.json")
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _map_action_to_intent_and_risk(self, act_key: str):
        k = act_key.lower().replace(".", "_")
        if "create_workbook" in k or "excel_create" in k:
            return "excel_create_workbook", "low"
        if "insert_table" in k:
            return "excel_insert_table", "medium"
        if "format_cells" in k:
            return "excel_format_cells", "medium"

        if "create_document" in k or "create_and_format" in k or k == "word_create":
            return "word_create_and_format", "low"
        if "append_text" in k or "word_append" in k or "word_edit" in k or "edit_document" in k:
            return "word_append_text", "low"
        if "insert_title" in k:
            return "word_create_and_format", "medium"
        if "format_keyword" in k:
            return "word_format_keyword", "medium"
        if "save" in k:
            return "word_save", "high"
        if "close" in k:
            return "word_close", "high"

        if "snap_left" in k:
            return "window_place", "low"
        if "snap_right" in k:
            return "window_place", "low"
        if "maximize" in k:
            return "window_place", "low"
        if "center" in k:
            return "window_place", "low"
        if "window_place" in k:
            return "window_place", "low"
        if "split" in k:
            return "window_split", "low"

        if "create_folder" in k:
            return "finder_create_folder", "medium"
        if "reveal" in k:
            return "finder_reveal_item", "low"

        if "ask_gemini" in k or "system2" in k:
            return "ask_gemini", "low"

        return k, "medium"

    def _extract_params_for_intent(self, intent, norm_text, action_key=None, frontmost_app=None):
        t = norm_text.lower()

        if intent == "word_create_and_format":
            title = ""
            body = ""
            keyword = ""
            kw_bold = False
            kw_hl = "none"

            m_title = re.search(
                r'titolo\s+(?:con\s+|di\s+|[\'"]?)([^\,\;\n]+?)(?:[\'"]|\s+in grassetto|\s+grassetto|\,\s*scrivi|\s+scrivi|\,\s*con|$)',
                norm_text,
                re.IGNORECASE
            )
            if m_title:
                title = m_title.group(1).strip().strip('\'"')

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

            m_kw = re.search(r'(?:evidenzia|metti in grassetto|grassetto su)(?:\s+(?:in grassetto|la parola|il termine|la|il|lo|gli|le))*\s+[\'\"“]?([a-zA-Z0-9_\-]+)', norm_text, re.IGNORECASE)
            if m_kw:
                keyword = m_kw.group(1).strip().strip('\'"“')
                kw_bold = "grassetto" in t[m_kw.start():] or "evidenzia in grassetto" in t
                kw_hl = "yellow" if "evidenzia" in t else "none"

            return {
                "title": title or "Documento",
                "title_bold": True,
                "title_size": 20,
                "body": body,
                "body_size": 12,
                "keyword": keyword,
                "kw_bold": kw_bold,
                "kw_hl": kw_hl
            }

        elif intent == "word_append_text":
            body = ""
            if "lorem ipsum" in t:
                m_lines = re.search(r'(\d+)\s*(?:righe|righi|paragrafi|frasi)', t)
                body = LOREM_IPSUM_1 if (m_lines and int(m_lines.group(1)) <= 1) else LOREM_IPSUM_3
            else:
                m_text = re.search(
                    r'(?:scrivendo|scrivi(?:\s+nel\s+documento)?|aggiungi(?:\s+testo|\s+al\s+documento)?|inserisci(?:\s+testo)?|con\s+testo|testo)\s*:?\s*[\'\"“]?([^\;\n]+)',
                    norm_text,
                    re.IGNORECASE
                )
                if m_text:
                    body = m_text.group(1).strip().strip('\'"“”')
                else:
                    cleaned = re.sub(
                        r'^(?:modifica|aggiorna)\s+(?:il\s+)?(?:documento|file)(?:\s+word)?\s*',
                        '',
                        norm_text,
                        flags=re.IGNORECASE
                    ).strip().strip('\'"“”')
                    body = cleaned or norm_text.strip()
            return {"text": body}

        elif intent == "word_format_keyword":
            m_format_only = re.search(r'(?:metti in grassetto|evidenzia|grassetto su)(?:\s+(?:la parola|il termine|la|il|lo|gli|le))*\s+[\'\"“]?([a-zA-Z0-9_\-]+)', norm_text, re.IGNORECASE)
            kw = m_format_only.group(1).strip().strip('\'"“') if m_format_only else ""
            return {"keyword": kw, "bold": "grassetto" in t, "highlight": "yellow" if "evidenzia" in t else "none"}

        elif intent == "word_save":
            as_pdf = "pdf" in t
            file_name = "documento.pdf" if as_pdf else "documento.docx"
            return {"path": f"~/Desktop/{file_name}", "as_pdf": as_pdf}

        elif intent == "word_close":
            saving = "salvando" in t and "senza" not in t
            return {"saving": saving}

        elif intent == "window_place":
            where = "left"
            if action_key:
                ak = action_key.lower()
                if "left" in ak or "sinistra" in ak:
                    where = "left"
                elif "right" in ak or "destra" in ak:
                    where = "right"
                elif "maximize" in ak or "tutto" in ak or "full" in ak:
                    where = "full"
                elif "center" in ak or "centro" in ak:
                    where = "center"
            else:
                if "destra" in t:
                    where = "right"
                elif "sinistra" in t:
                    where = "left"
                elif "tutto schermo" in t or "massimizza" in t or "schermo intero" in t:
                    where = "full"
                elif "centro" in t:
                    where = "center"

            m_win = re.match(r'^(?:sposta\s+|metti\s+)?(.+?)\s+(?:a|in|su)\s+(sinistra|destra|tutto schermo|schermo intero|centro)$', t)
            app = m_win.group(1).strip() if m_win else (frontmost_app or "current")
            return {"app": app, "where": where}

        elif intent == "window_split":
            return {"left": "Microsoft Word", "right": "Safari"}

        elif intent == "finder_create_folder":
            m_folder = re.search(
                r'\b(?:crea|fai|nuova)\s+cartella(?:\s+(?:chiamata|di nome|intitolata|[\'"]))?\s*([a-zA-Z0-9_\-\s]+)?',
                norm_text,
                re.IGNORECASE
            )
            f_name = (m_folder.group(1) or "Nuova Cartella").strip().strip('\'"') if m_folder else "Nuova Cartella"
            return {"name": f_name or "Nuova Cartella", "path": "~/Desktop"}

        elif intent == "excel_create_workbook":
            title = ""
            m_title = re.search(
                r'(?:titolo\s+(?:con\s+|di\s+|[\'"]?)|chiamat[oa]\s+[\'"]?|intitolat[oa]\s+[\'"]?)([^\,\;\n]+?)(?:[\'"]|\s+(?:e|con)\s+(?:colonne|tabella)|\,\s*con|$)',
                norm_text,
                re.IGNORECASE
            )
            if m_title:
                title = m_title.group(1).strip().strip('\'"')

            headers = []
            m_hdrs = re.search(r'(?:colonne|intestazioni|campi)\s*:?\s*([^\;\n]+)', norm_text, re.IGNORECASE)
            if m_hdrs:
                raw_hdrs = m_hdrs.group(1).strip()
                headers = [h.strip().strip('\'"') for h in re.split(r',\s*|\s+e\s+', raw_hdrs) if h.strip()]

            return {
                "title": title,
                "headers": headers
            }

        elif intent == "excel_insert_table":
            headers = []
            m_hdrs = re.search(r'(?:colonne|intestazioni|con\s+colonne|campi)\s*:?\s*([^\;\n]+)', norm_text, re.IGNORECASE)
            if m_hdrs:
                raw_hdrs = m_hdrs.group(1).strip()
                headers = [h.strip().strip('\'"') for h in re.split(r',\s*|\s+e\s+', raw_hdrs) if h.strip()]
            if not headers:
                headers = ["Colonna 1", "Colonna 2"]
            return {"headers": headers}

        elif intent == "excel_format_cells":
            m_range = re.search(r'(?:intervallo|intervalli|celle?)\s+([a-zA-Z0-9\:]+)', norm_text, re.IGNORECASE)
            range_ref = m_range.group(1).strip() if m_range else "selection"
            bold = ("grassetto" in t) or ("formatta" in t and "valuta" not in t)
            currency = any(w in t for w in ["valuta", "euro", "prezzo", "prezzi", "importo", "importi", "€", "$"])
            return {
                "range": range_ref,
                "bold": bold,
                "currency": currency
            }

        return {}

    def _get_action_label(self, intent, params):
        if intent == "excel_create_workbook":
            title = params.get("title", "")
            return f"Crea nuova cartella Excel{f' ({title})' if title else ''}"
        if intent == "excel_insert_table":
            return "Inserisci tabella nel foglio Excel attivo"
        if intent == "excel_format_cells":
            r = params.get("range", "selezione")
            return f"Formatta celle ({r}) in Excel"
        if intent == "window_split":
            return "Affianca finestre (Word a sinistra, Safari a destra)"
        if intent == "window_place":
            where = params.get("where", "sinistra")
            app = params.get("app", "finestra")
            where_it = {"left": "a sinistra", "right": "a destra", "full": "a tutto schermo", "center": "al centro"}.get(where, where)
            return f"Sposta {app} ({where_it})"
        if intent == "word_create_and_format":
            title = params.get("title", "")
            return f"Crea nuovo documento vuoto su Word{f' ({title})' if title else ''}"
        if intent == "word_save":
            as_pdf = params.get("as_pdf", False)
            return f"Salva documento Word {'in PDF' if as_pdf else ''}".strip()
        if intent == "finder_create_folder":
            name = params.get("name", "cartella")
            return f"Crea cartella '{name}' sul Desktop"
        if intent == "word_append_text":
            txt = params.get("text", "")
            preview = (txt[:25] + "...") if len(txt) > 25 else txt
            return f"Aggiungi testo al documento Word attivo{f' (\"{preview}\")' if preview else ''}"
        if intent in ("ask_gemini", "system2.gemini", "system2_ask_gemini"):
            return "Chiedi a Gemini (analisi avanzata)"
        return intent

    def _build_alternatives_from_candidates(self, candidates, norm_text, frontmost_app=None):
        alts = []
        seen_intents = set()
        seen_labels = set()

        for c in candidates:
            intent = c["intent"]
            if intent in ("ask_gemini", "system2.gemini", "system2_ask_gemini"):
                intent = "system2.gemini"
                params = {"query": norm_text}
            else:
                params = self._extract_params_for_intent(intent, norm_text, action_key=c["action_key"], frontmost_app=frontmost_app)

            label = self._get_action_label(intent, params)
            norm_intent = "ask_gemini" if intent in ("ask_gemini", "system2.gemini") else intent

            if norm_intent in seen_intents or label in seen_labels:
                continue

            seen_intents.add(norm_intent)
            seen_labels.add(label)

            alts.append({
                "choice_id": len(alts) + 1,
                "action_id": intent,
                "label": label,
                "extracted_params": params,
                "jev_score": c["jev_score"]
            })
            if len(alts) >= 3:
                break

        if len(alts) < 3 and "ask_gemini" not in seen_intents:
            alts.append({
                "choice_id": len(alts) + 1,
                "action_id": "system2.gemini",
                "label": "Chiedi a Gemini (analisi avanzata)",
                "extracted_params": {"query": norm_text},
                "jev_score": 1.0
            })
        return alts

    def analyze(self, text, frontmost_app=None):
        """
        JEV Pipeline:
        1. Checks for active pending_choice resolution (1, 2, 3 / uno, due, tre).
        2. Fast-Path: checks learned user_corrections (0ms).
        3. If useRizzoFlow is True: queries Rizzo Flow server (POST /v1/systemone, 250ms timeout)
           and calculates JEV based on neural probabilities.
           If server is offline/times out: returns confidence 1.0, intent="error_rizzo_offline".
        4. If useRizzoFlow is False: evaluates rule-based Judge and JEV.
        """
        if not text:
            return 0.0, "none", {}, []

        norm_text = atticus_i18n.normalize_italian_numbers(text.strip())
        t = norm_text.lower()

        # Step 0: Check if input resolves an active pending choice card
        resolved, choice = atticus_feedback.resolve_pending_choice(norm_text)
        if resolved and choice:
            action_id = choice.get("action_id", "")
            if action_id in ("system2.gemini", "ask_gemini", "system2_ask_gemini"):
                orig_q = (
                    choice.get("original_query")
                    or choice.get("extracted_params", {}).get("query")
                    or text
                )
                return 0.20, "ask_gemini", {"query": orig_q}, []
            return 0.99, action_id, choice.get("extracted_params", {}), []

        # Step 0.5: Fast-Path on user_corrections via get_user_correction(norm_text)
        corr = atticus_feedback.get_user_correction(norm_text)
        if corr:
            raw_intent = corr.get("intent") if isinstance(corr, dict) else corr
            params = corr.get("params", {}) if isinstance(corr, dict) else {}
            canonical_intent, _ = self._map_action_to_intent_and_risk(raw_intent)
            if not params:
                params = self._extract_params_for_intent(canonical_intent, norm_text, frontmost_app=frontmost_app)
            return 1.0, canonical_intent, params, []

        # Context detection
        explicit_front_passed = frontmost_app is not None
        if not frontmost_app:
            frontmost_app = get_frontmost_app()
        session_ctx = get_session_context()

        # Step 1: Check Settings for useRizzoFlow
        settings = self._load_settings()
        use_rizzo = settings.get("useRizzoFlow", False)

        if use_rizzo:
            from .rizzo_client import query_rizzo_intent, RIZZO_TIMEOUT
            endpoint = settings.get("rizzoFlowUrl", "http://127.0.0.1:8017").rstrip("/") + "/v1/systemone"
            timeout = float(settings.get("rizzoTimeout", RIZZO_TIMEOUT))
            try:
                probs = query_rizzo_intent(
                    prompt=norm_text,
                    catalog=self.catalog,
                    context={"frontmost_app": frontmost_app},
                    endpoint=endpoint,
                    timeout=timeout
                )
                if not probs or not isinstance(probs, dict):
                    raise RuntimeError("Rizzo Flow returned invalid probabilities")
            except Exception:
                return 1.0, "error_rizzo_offline", {
                    "message": "Rizzo Flow non è attivo sulla porta 8017. Avvia il server per eseguire i comandi"
                }, []

            # Rizzo Flow Neural JEV scoring: JEV(a) = P(a)*1.0 - (1 - P(a))*C_risk
            candidates = []
            for act_key, p_score in probs.items():
                if p_score <= 0.0:
                    continue
                canonical_intent, risk_level = self._map_action_to_intent_and_risk(act_key)
                jev = self._calc_jev(p_score, risk_level)
                candidates.append({
                    "action_key": act_key,
                    "intent": canonical_intent,
                    "p_score": p_score,
                    "risk_level": risk_level,
                    "jev_score": jev
                })

            if not candidates:
                return 0.20, "ask_gemini", {"query": text}, []

            candidates.sort(key=lambda x: x["jev_score"], reverse=True)
            top = candidates[0]
            top_intent = top["intent"]
            top_jev = top["jev_score"]
            top_risk = top["risk_level"]

            threshold = EXEC_THRESHOLDS.get(top_risk, 0.80)
            if top_jev >= threshold:
                params = self._extract_params_for_intent(top_intent, norm_text, action_key=top["action_key"], frontmost_app=frontmost_app)
                return top_jev, top_intent, params, []
            elif top_jev >= DISAMB_THRESHOLDS.get(top_risk, 0.40):
                alts = self._build_alternatives_from_candidates(candidates[:3], norm_text, frontmost_app=frontmost_app)
                atticus_feedback.save_pending_choice(text, alts, front_app=frontmost_app)
                return top_jev, "disambiguation", {}, alts
            else:
                return 0.20, "ask_gemini", {"query": text}, []

        # Step 2: Rule-Based Judge & JEV Evaluator (when useRizzoFlow is False)
        front_is_word = "word" in (frontmost_app or "").lower()
        is_word_explicit = bool(re.search(r'\b(word|documento word|file word|word vuoto)\b', t))
        session_is_word = (not explicit_front_passed) and (session_ctx.get("last_app") == "Microsoft Word")
        is_word = front_is_word or is_word_explicit

        front_is_excel = "excel" in (frontmost_app or "").lower()
        is_excel_explicit = bool(re.search(r'\b(excel|foglio excel|file excel|cartella excel)\b', t))
        session_is_excel = (not explicit_front_passed) and (session_ctx.get("last_app") == "Microsoft Excel")
        is_excel = front_is_excel or is_excel_explicit

        # -------------------------------------------------------------
        # 0. Excel: Create Workbook
        # -------------------------------------------------------------
        is_excel_create = bool(re.search(r'\b(nuovo foglio excel|crea file excel|apri excel vuoto|apri excel|nuova cartella excel|crea tabella excel|foglio excel vuoto|nuovo file excel)\b', t))
        if is_excel_create or (is_excel and re.search(r'\b(apri|crea|nuov[oa])\s+(?:file|foglio|cartella)?\b', t) and not re.search(r'\b(word|documento)\b', t)):
            params = self._extract_params_for_intent("excel_create_workbook", norm_text)
            p_score = 0.96 if is_excel_explicit else 0.88
            jev = self._calc_jev(p_score, "low")
            if jev >= 0.77:
                return p_score, "excel_create_workbook", params, []

        # -------------------------------------------------------------
        # Excel: Insert Table
        # -------------------------------------------------------------
        if (is_excel or session_is_excel) and re.search(r'\b(inserisci tabella|crea tabella|aggiungi tabella|inserisci colonne)\b', t) and not is_excel_create:
            params = self._extract_params_for_intent("excel_insert_table", norm_text)
            p_score = 0.92 if (is_excel_explicit or front_is_excel) else 0.86
            jev = self._calc_jev(p_score, "medium")
            if jev >= 0.75:
                return p_score, "excel_insert_table", params, []

        # -------------------------------------------------------------
        # Excel: Format Cells
        # -------------------------------------------------------------
        if (is_excel or session_is_excel) and re.search(r'\b(grassetto su celle|metti in valuta|formatta celle|celle in valuta|celle in grassetto)\b', t):
            params = self._extract_params_for_intent("excel_format_cells", norm_text)
            p_score = 0.92 if (is_excel_explicit or front_is_excel) else 0.86
            jev = self._calc_jev(p_score, "medium")
            if jev >= 0.75:
                return p_score, "excel_format_cells", params, []

        # -------------------------------------------------------------
        # Word: Append / Edit active document
        # -------------------------------------------------------------
        is_edit_word = bool(re.search(r'\b(modifica\s+(?:il\s+)?(?:documento|file)|aggiungi\s+(?:testo|al\s+documento)|scrivi\s+nel\s+documento|inserisci\s+testo|continua\s+a\s+scrivere)\b', t))
        if (is_word or session_is_word) and is_edit_word:
            params = self._extract_params_for_intent("word_append_text", norm_text)
            p_score = 0.94 if (is_word_explicit or front_is_word) else 0.88
            jev = self._calc_jev(p_score, "low")
            if jev >= 0.77:
                return p_score, "word_append_text", params, []

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

        elif intent == "word_append_text":
            text_to_add = params.get("text", "")
            ok, doc_name_or_err = word.append_text(text=text_to_add)
            if ok:
                update_session_context(
                    app="Microsoft Word",
                    action_id="word_append_text",
                    target_text=text_to_add[:30],
                    document_id=doc_name_or_err
                )
                atticus_feedback.record_action(
                    prompt=prompt,
                    action_type="word_undo",
                    rollback_strategy="word_undo",
                    rollback_cmd=['osascript', '-e', 'tell application "Microsoft Word" to tell active document to undo'],
                    metadata={"doc_name": doc_name_or_err, "text": text_to_add}
                )
                return True, f"Testo aggiunto al documento Word '{doc_name_or_err}'."
            return False, f"Impossibile aggiungere testo in Word: {doc_name_or_err}"

        elif intent == "word_format_keyword":
            kw = params.get("keyword")
            bold = params.get("bold", False)
            hl = params.get("highlight", "none")
            ok, out = word.format_keyword(kw, make_bold=bold, highlight_color=hl)
            if ok:
                update_session_context(app="Microsoft Word", action_id="word_format_keyword", target_text=kw)
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

        elif intent == "excel_create_workbook":
            title = params.get("title", "")
            headers = params.get("headers", [])
            ok, wb_name = excel.create_workbook(title=title, headers=headers)
            if not ok:
                return False, f"Errore Excel: {wb_name}"

            update_session_context(
                app="Microsoft Excel",
                action_id="excel_create_workbook",
                target_text=title or "Cartella",
                document_id=wb_name
            )

            atticus_feedback.record_action(
                prompt=prompt,
                action_type="excel_create",
                rollback_strategy="close_created_workbook_verified",
                metadata={"wb_name": wb_name, "title": title}
            )
            rep_title = f" con titolo '{title}'" if title else ""
            rep_hdrs = f" e tabella ({', '.join(headers)})" if headers else ""
            return True, f"Creata nuova cartella di lavoro Excel '{wb_name}'{rep_title}{rep_hdrs}."

        elif intent == "excel_insert_table":
            headers = params.get("headers", [])
            ok, out = excel.insert_table(headers=headers)
            if ok:
                update_session_context(app="Microsoft Excel", action_id="excel_insert_table")
                atticus_feedback.record_action(
                    prompt=prompt,
                    action_type="excel_undo",
                    rollback_strategy="excel_undo",
                    metadata={"headers": headers}
                )
                return True, "Tabella con intestazioni inserita nel foglio Excel attivo."
            return False, f"Impossibile inserire la tabella in Excel: {out}"

        elif intent == "excel_format_cells":
            r_ref = params.get("range", "selection")
            bold = params.get("bold", True)
            curr = params.get("currency", False)
            ok, out = excel.format_cells(range_ref=r_ref, bold=bold, currency=curr)
            if ok:
                update_session_context(app="Microsoft Excel", action_id="excel_format_cells")
                atticus_feedback.record_action(
                    prompt=prompt,
                    action_type="excel_undo",
                    rollback_strategy="excel_undo",
                    metadata={"range": r_ref, "bold": bold, "currency": curr}
                )
                fmt_desc = "valuta" if curr and not bold else ("grassetto" if bold and not curr else "grassetto e valuta")
                return True, f"Celle ({r_ref}) formattate in {fmt_desc} in Excel."
            return False, f"Impossibile formattare le celle in Excel: {out}"

        return False, "Azione non gestita da System 1"
