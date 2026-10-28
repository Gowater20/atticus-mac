#!/usr/bin/env python3
"""
Unit Test Suite for Rizzo Flow Client, Fast-Path User Corrections, and Indefinite Undo Persistence.
Tests:
- rizzo_client: wire format, options generation, probability extraction across all standard formats, timeouts
- atticus_feedback: indefinite undo (no 5s drop), skill consolidation on new action, 0ms cache, dataset append
- system_one/engine: fast-path override, offline blocking alert, neural JEV calculation
- atticus: fast() wiring for error_rizzo_offline
"""

import os
import sys
import json
import time
import shutil
import tempfile
import unittest
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

# Force DRY_RUN
os.environ["ATTICUS_DRY_RUN"] = "1"

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import atticus
import atticus_feedback
from system_one import rizzo_client
from system_one.engine import SystemOneEngine


class MockRizzoHandler(BaseHTTPRequestHandler):
    response_payload = {}
    response_code = 200
    delay = 0.0

    def do_POST(self):
        if self.delay > 0:
            time.sleep(self.delay)
        content_len = int(self.headers.get('Content-Length', 0))
        post_body = self.rfile.read(content_len)
        MockRizzoHandler.last_request = json.loads(post_body.decode('utf-8'))

        self.send_response(self.response_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(self.response_payload).encode('utf-8'))

    def log_message(self, format, *args):
        pass  # Suppress HTTP server output in test logs


class TestRizzoAndUndo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Start mock HTTP server on an available localhost port
        cls.server = HTTPServer(('127.0.0.1', 0), MockRizzoHandler)
        cls.port = cls.server.server_address[1]
        cls.endpoint = f"http://127.0.0.1:{cls.port}/v1/systemone"
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_config_dir = atticus_feedback.CONFIG_DIR
        atticus_feedback.CONFIG_DIR = self.test_dir
        atticus_feedback.LAST_ACTION_PATH = os.path.join(self.test_dir, "last_action.json")
        atticus_feedback.PENDING_CHOICE_PATH = os.path.join(self.test_dir, "pending_choice.json")
        atticus_feedback.SKILLS_PATH = os.path.join(self.test_dir, "skills.json")
        atticus_feedback.USER_CORRECTIONS_FILE = os.path.join(self.test_dir, "user_corrections.json")
        atticus_feedback.CORRECTIONS_DATASET_FILE = os.path.join(self.test_dir, "corrections_dataset.jsonl")
        self.engine = SystemOneEngine()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        atticus_feedback.CONFIG_DIR = self.old_config_dir

    # --- 1. Rizzo Client Tests ---

    def test_build_catalog_options_and_criteria(self):
        catalog = {
            "apps": {
                "word": {
                    "actions": {
                        "create_document": {"description": "Crea documento word", "triggers_it": ["nuovo file"]},
                        "save_document": {"description": "Salva documento word"}
                    }
                },
                "window": {
                    "actions": {
                        "snap_left": {"description": "Posiziona finestra a sinistra"}
                    }
                }
            }
        }
        options = rizzo_client.build_catalog_options(catalog)
        self.assertIn("word_create_document", options)
        self.assertIn("word_save_document", options)
        self.assertIn("window_snap_left", options)
        self.assertEqual(len(options), 3)

        criteria = rizzo_client.build_catalog_criteria(catalog)
        self.assertIn("word_create_document", criteria)
        self.assertIn("Crea documento word", criteria["word_create_document"])
        self.assertIn("nuovo file", criteria["word_create_document"])

        # Test normalize_action_id
        self.assertEqual(rizzo_client.normalize_action_id("word_create_document", to_dot=True), "word.create_document")
        self.assertEqual(rizzo_client.normalize_action_id("word.create_document", to_dot=False), "word_create_document")

    def test_extract_probabilities_structures(self):
        options = ["word_create_document", "window_snap_left"]

        # Structure 1: answers.intent with choice and probability
        body1 = {"answers": {"intent": {"choice": "word_create_document", "probability": 0.95}}}
        p1 = rizzo_client._extract_probabilities(body1, options)
        self.assertEqual(p1["word_create_document"], 0.95)
        self.assertEqual(p1["window_snap_left"], 0.0)

        # Structure 2: answers.intent as direct mapping
        body2 = {"answers": {"intent": {"word_create_document": 0.8, "window_snap_left": 0.2}}}
        p2 = rizzo_client._extract_probabilities(body2, options)
        self.assertEqual(p2["word_create_document"], 0.8)
        self.assertEqual(p2["window_snap_left"], 0.2)

        # Structure 3: questions.intent with probabilities
        body3 = {"questions": {"intent": {"probabilities": {"word_create_document": 0.75, "window_snap_left": 0.25}}}}
        p3 = rizzo_client._extract_probabilities(body3, options)
        self.assertEqual(p3["word_create_document"], 0.75)
        self.assertEqual(p3["window_snap_left"], 0.25)

        # Structure 4: root choice + probability
        body4 = {"choice": "window_snap_left", "probability": 0.88}
        p4 = rizzo_client._extract_probabilities(body4, options)
        self.assertEqual(p4["window_snap_left"], 0.88)

        # Structure 5: root mapping with unnormalized weights
        body5 = {"word_create_document": 80, "window_snap_left": 20}
        p5 = rizzo_client._extract_probabilities(body5, options)
        self.assertEqual(p5["word_create_document"], 0.8)
        self.assertEqual(p5["window_snap_left"], 0.2)

    def test_query_rizzo_intent_success_and_wire_format(self):
        MockRizzoHandler.response_payload = {
            "answers": {
                "intent": {
                    "choice": "window_snap_left",
                    "probability": 0.92
                }
            }
        }
        MockRizzoHandler.delay = 0.0

        probs = rizzo_client.query_rizzo_intent(
            prompt="metti safari a sinistra",
            catalog={"apps": {"window": {"actions": {"snap_left": {}}}}},
            context={"frontmost_app": "Safari"},
            endpoint=self.endpoint,
            timeout=0.25
        )

        self.assertIn("window_snap_left", probs)
        self.assertEqual(probs["window_snap_left"], 0.92)

        # Verify Wire Format
        req = MockRizzoHandler.last_request
        self.assertIn("state", req)
        self.assertIn("Safari", req["state"])
        self.assertEqual(req["model"], "rizzo-latest")
        self.assertEqual(req["questions"]["intent"]["type"], "choice")
        self.assertIn("instructions", req["questions"]["intent"])
        self.assertIn("window_snap_left", req["questions"]["intent"]["criteria"])

    def test_query_rizzo_intent_timeout(self):
        # Server delay exceeds timeout
        MockRizzoHandler.delay = 0.35
        with self.assertRaises(Exception):
            rizzo_client.query_rizzo_intent(
                prompt="test",
                endpoint=self.endpoint,
                timeout=0.10
            )
        MockRizzoHandler.delay = 0.0

    # --- 2. Feedback & Undo Persistence Tests ---

    def test_indefinite_undo_persistence(self):
        """Tests that last action is NOT dropped after 5 seconds."""
        atticus_feedback.record_action(
            prompt="crea documento",
            action_type="word_create",
            metadata={"doc_name": "TestDoc"}
        )

        # Verify it exists
        action = atticus_feedback.get_last_action()
        self.assertIsNotNone(action)
        self.assertEqual(action.get("prompt"), "crea documento")

        # Fake an elapsed time of 100 seconds
        with open(atticus_feedback.LAST_ACTION_PATH, "r") as f:
            data = json.load(f)
        data["timestamp"] = time.time() - 100.0
        with open(atticus_feedback.LAST_ACTION_PATH, "w") as f:
            json.dump(data, f)

        # Calling get_last_action() without max_age MUST still return the action!
        action_later = atticus_feedback.get_last_action()
        self.assertIsNotNone(action_later)
        self.assertEqual(action_later.get("prompt"), "crea documento")

    def test_record_action_consolidates_previous_action(self):
        """Recording a second action reinforces the skill of the first action."""
        skills = {
            "azione_uno": {
                "confidence": 0.80,
                "success_count": 0,
                "status": "active"
            }
        }
        with open(atticus_feedback.SKILLS_PATH, "w") as f:
            json.dump(skills, f)

        # Record action 1
        atticus_feedback.record_action("azione uno", "window_place", skill_key="azione_uno")

        # Record action 2 (this should reinforce azione_uno)
        atticus_feedback.record_action("azione due", "word_create", skill_key="azione_due")

        with open(atticus_feedback.SKILLS_PATH, "r") as f:
            updated = json.load(f)
        self.assertGreater(updated["azione_uno"]["confidence"], 0.80)
        self.assertEqual(updated["azione_uno"]["success_count"], 1)

    def test_fast_path_user_corrections(self):
        """Tests saving and retrieving user corrections with 0ms in-memory cache."""
        saved = atticus_feedback.save_user_correction(
            prompt="metti safari a destra",
            intent="window_place",
            source="disambiguation_card",
            params={"app": "Safari", "where": "right"}
        )
        self.assertTrue(saved)

        # Fast lookup via get_user_correction
        corr = atticus_feedback.get_user_correction("metti safari a destra")
        self.assertIsNotNone(corr)
        self.assertEqual(corr["intent"], "window_place")
        self.assertEqual(corr["params"]["where"], "right")

        # Verify dataset jsonl has the entry
        dataset_path = atticus_feedback.CORRECTIONS_DATASET_FILE
        self.assertTrue(os.path.exists(dataset_path))
        with open(dataset_path, "r") as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 1)
        dataset_obj = json.loads(lines[0])
        self.assertEqual(dataset_obj["intent"], "window_place")

    # --- 3. System 1 Engine Integration Tests ---

    def test_engine_fast_path_user_correction(self):
        """Verifies engine immediately returns confidence 1.0 on learned corrections."""
        atticus_feedback.save_user_correction(
            prompt="apri word al volo",
            intent="word_create_and_format",
            params={"title": "Appunti Rapidi", "body": ""}
        )

        conf, intent, params, alts = self.engine.analyze("apri word al volo")
        self.assertEqual(conf, 1.0)
        self.assertEqual(intent, "word_create_and_format")
        self.assertEqual(params.get("title"), "Appunti Rapidi")
        self.assertEqual(len(alts), 0)

    def test_engine_rizzo_offline_blocking_alert(self):
        """When useRizzoFlow is True and server is offline, returns blocking alert."""
        settings_path = os.path.join(self.test_dir, "settings.json")
        with open(settings_path, "w") as f:
            json.dump({
                "useRizzoFlow": True,
                "rizzoFlowUrl": "http://127.0.0.1:9999"  # Port with no server
            }, f)

        conf, intent, params, alts = self.engine.analyze("safari a destra")
        self.assertEqual(conf, 1.0)
        self.assertEqual(intent, "error_rizzo_offline")
        self.assertIn("Rizzo Flow non è attivo sulla porta 8017", params.get("message", ""))

        # Verify atticus.fast() wiring returns message directly
        msg = atticus.fast("safari a destra")
        self.assertIn("Rizzo Flow non è attivo sulla porta 8017", msg)

    def test_engine_rizzo_neural_jev_scoring(self):
        """When useRizzoFlow is True and server responds, computes neural JEV."""
        settings_path = os.path.join(self.test_dir, "settings.json")
        with open(settings_path, "w") as f:
            json.dump({
                "useRizzoFlow": True,
                "rizzoFlowUrl": f"http://127.0.0.1:{self.port}"
            }, f)

        MockRizzoHandler.response_payload = {
            "answers": {
                "intent": {
                    "choice": "window_snap_right",
                    "probability": 0.95
                }
            }
        }

        conf, intent, params, alts = self.engine.analyze("sposta safari a destra")
        self.assertGreaterEqual(conf, 0.90)
        self.assertEqual(intent, "window_place")
        self.assertEqual(params.get("where"), "right")


if __name__ == "__main__":
    unittest.main()
