#!/usr/bin/env python3
"""
Test Suite for System 1 Decision Engine with JEV Architecture
Covers:
- JEV Scoring & Risk Evaluation
- Frontmost App Context-Awareness
- Pending Choice (Disambiguation IPC) resolution
- Safe & Surgical Rollback
- Number normalization (STT resilience)
Runs in DRY_RUN mode to avoid modifying the real desktop GUI.
"""

import os
import sys
import unittest
import time
import json
import shutil
import tempfile

# Force DRY_RUN
os.environ["ATTICUS_DRY_RUN"] = "1"

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import atticus_feedback
import atticus_i18n
from system_one.engine import SystemOneEngine
from system_one.context import update_session_context, get_session_context, clear_session_context


class TestSystemOneJEV(unittest.TestCase):
    def setUp(self):
        self.engine = SystemOneEngine()
        self.test_dir = tempfile.mkdtemp()
        self.old_config_dir = atticus_feedback.CONFIG_DIR
        atticus_feedback.CONFIG_DIR = self.test_dir
        atticus_feedback.LAST_ACTION_PATH = os.path.join(self.test_dir, "last_action.json")
        atticus_feedback.PENDING_CHOICE_PATH = os.path.join(self.test_dir, "pending_choice.json")
        atticus_feedback.SKILLS_PATH = os.path.join(self.test_dir, "skills.json")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        atticus_feedback.CONFIG_DIR = self.old_config_dir

    def test_number_normalization(self):
        """Tests that spoken numbers like 'tre' or 'due' are converted to digits."""
        res = atticus_i18n.normalize_italian_numbers("scrivi un lorem ipsum di tre righe")
        self.assertIn("3 righe", res)

        res2 = atticus_i18n.normalize_italian_numbers("opzione uno")
        self.assertIn("1", res2)

    def test_word_create_and_format_parsing(self):
        """Tests full parameter extraction for Word creation."""
        prompt = "apri file vuoto su word, titolo Test Annuale in grassetto, scrivi un lorem ipsum di 3 righe ed evidenzia la parola lorem"
        conf, intent, params, alts = self.engine.analyze(prompt)

        self.assertGreaterEqual(conf, 0.85)
        self.assertEqual(intent, "word_create_and_format")
        self.assertEqual(params.get("title"), "Test Annuale")
        self.assertIn("Lorem ipsum dolor sit amet", params.get("body", ""))
        self.assertEqual(params.get("keyword"), "lorem")
        self.assertEqual(params.get("kw_hl"), "yellow")

    def test_context_awareness_word_implicit(self):
        """Tests that having Word as frontmost app enables implicit commands."""
        # Without context and without naming word:
        conf_no_ctx, intent_no_ctx, _, _ = self.engine.analyze("salva in pdf", frontmost_app="Finder")
        self.assertLess(conf_no_ctx, 0.50)

        # With Word in front:
        conf_ctx, intent_ctx, params_ctx, _ = self.engine.analyze("salva in pdf", frontmost_app="Microsoft Word")
        self.assertGreaterEqual(conf_ctx, 0.85)
        self.assertEqual(intent_ctx, "word_save")
        self.assertTrue(params_ctx.get("as_pdf"))

    def test_window_management_and_split(self):
        """Tests snap window and window split."""
        conf, intent, params, _ = self.engine.analyze("safari a destra")
        self.assertGreaterEqual(conf, 0.90)
        self.assertEqual(intent, "window_place")
        self.assertEqual(params.get("where"), "right")

        conf_s, intent_s, _, _ = self.engine.analyze("affianca finestre")
        self.assertGreaterEqual(conf_s, 0.85)
        self.assertEqual(intent_s, "window_split")

    def test_disambiguation_and_pending_choice_resolution(self):
        """Tests triggering disambiguation and resolving choice via IPC."""
        conf, intent, params, alts = self.engine.analyze("organizza finestre e documenti")
        self.assertEqual(intent, "disambiguation")
        self.assertEqual(len(alts), 3)

        # Check pending_choice.json was saved
        pending = atticus_feedback.get_pending_choice()
        self.assertIsNotNone(pending)
        self.assertEqual(len(pending.get("options", [])), 3)

        # Simulate user answering "uno"
        conf_res, intent_res, _, _ = self.engine.analyze("uno")
        self.assertEqual(conf_res, 0.99)
        self.assertEqual(intent_res, "window_split")

        # Check pending choice was cleared after resolution
        self.assertIsNone(atticus_feedback.get_pending_choice())

    def test_surgical_rollback_and_decay(self):
        """Tests surgical rollback and confidence decay on 'annulla'."""
        # 1. Setup skill with 0.85 confidence
        skills = {
            "sposta safari a destra": {
                "action": "window_place",
                "confidence": 0.85,
                "undo_count": 0
            }
        }
        with open(atticus_feedback.SKILLS_PATH, "w") as f:
            json.dump(skills, f)

        # 2. Record window placement action
        atticus_feedback.record_action(
            prompt="sposta safari a destra",
            action_type="window_place",
            skill_key="sposta safari a destra",
            metadata={"app": "Safari", "bounds": {"x": 50, "y": 50, "width": 600, "height": 400}}
        )

        # 3. Trigger negative feedback "annulla"
        self.assertTrue(atticus_feedback.is_negative_trigger("annulla"))
        handled, msg = atticus_feedback.handle_annulla()
        self.assertTrue(handled)
        self.assertIn("Azione annullata", msg)

        # 4. Verify confidence decay (0.85 * 0.65 = 0.552)
        with open(atticus_feedback.SKILLS_PATH, "r") as f:
            updated_skills = json.load(f)
        self.assertAlmostEqual(updated_skills["sposta safari a destra"]["confidence"], 0.552, places=2)
        self.assertEqual(updated_skills["sposta safari a destra"]["undo_count"], 1)

    def test_word_append_text_parsing(self):
        """Tests intent recognition and param extraction for append_text."""
        prompt = "modifica il documento word scrivendo Nuova sezione di bilancio"
        conf, intent, params, _ = self.engine.analyze(prompt)
        self.assertGreaterEqual(conf, 0.85)
        self.assertEqual(intent, "word_append_text")
        self.assertEqual(params.get("text"), "Nuova sezione di bilancio")

        # Implicit Word frontmost
        prompt_implicit = "aggiungi al documento: Conclusioni finali"
        conf2, intent2, params2, _ = self.engine.analyze(prompt_implicit, frontmost_app="Microsoft Word")
        self.assertGreaterEqual(conf2, 0.85)
        self.assertEqual(intent2, "word_append_text")
        self.assertEqual(params2.get("text"), "Conclusioni finali")

    def test_disambiguation_resolve_gemini(self):
        """Tests resolving disambiguation choice via 'chiedi a gemini' or 'gemini'."""
        conf, intent, params, alts = self.engine.analyze("organizza finestre e documenti")
        self.assertEqual(intent, "disambiguation")

        # Resolve via "chiedi a gemini"
        conf_res, intent_res, params_res, _ = self.engine.analyze("chiedi a gemini")
        self.assertEqual(intent_res, "ask_gemini")
        self.assertEqual(params_res.get("query"), "organizza finestre e documenti")

    def test_alternatives_deduplication(self):
        """Tests that _build_alternatives_from_candidates removes duplicate intents and labels."""
        candidates = [
            {"intent": "word_create_and_format", "action_key": "create_doc", "jev_score": 0.8},
            {"intent": "word_create_and_format", "action_key": "create_doc_2", "jev_score": 0.7},
            {"intent": "system2.gemini", "action_key": "gemini", "jev_score": 0.5},
            {"intent": "ask_gemini", "action_key": "ask", "jev_score": 0.4},
        ]
        alts = self.engine._build_alternatives_from_candidates(candidates, "bozza")
        intents = [a["action_id"] for a in alts]
        self.assertEqual(len(intents), len(set(intents)))
        self.assertIn("system2.gemini", intents)


if __name__ == "__main__":
    unittest.main()
