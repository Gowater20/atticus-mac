#!/usr/bin/env python3
"""
Unit Test Suite for Microsoft Excel Pilot Module (System 1)
Tests:
- apple_catalog.json: verification of Excel app definition, actions, triggers, and rollback strategies
- system_one/apps/excel: AppleScript generation, column letter conversions, parameter escaping, DRY_RUN execution
- system_one/executor: app name resolution ('excel' -> 'Microsoft Excel') and rollback strategy routing
- system_one/engine: semantic parsing, parameter extraction, JEV scoring, execution, and context tracking
- atticus_feedback: surgical rollback (close_created_workbook_verified) and undo rollback (excel_undo)
"""

import os
import sys
import json
import shutil
import tempfile
import unittest

# Force DRY_RUN mode for test isolation
os.environ["ATTICUS_DRY_RUN"] = "1"

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import atticus_feedback
from system_one.apps import excel
from system_one.executor import resolve_app_name, execute_rollback_strategy
from system_one.engine import SystemOneEngine


class TestExcelModule(unittest.TestCase):
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

    # --- 1. Catalog Verification ---

    def test_catalog_excel_definition(self):
        catalog = self.engine.catalog
        self.assertIn("apps", catalog)
        self.assertIn("excel", catalog["apps"])

        excel_app = catalog["apps"]["excel"]
        self.assertEqual(excel_app.get("name"), "Microsoft Excel")
        self.assertEqual(excel_app.get("bundle_id"), "com.microsoft.Excel")

        actions = excel_app.get("actions", {})
        self.assertIn("create_workbook", actions)
        self.assertIn("insert_table", actions)
        self.assertIn("format_cells", actions)

        cw = actions["create_workbook"]
        self.assertEqual(cw.get("risk_level"), "low")
        self.assertEqual(cw.get("rollback_strategy"), "close_created_workbook_verified")
        self.assertIn("nuovo foglio excel", cw.get("triggers_it", []))

        it = actions["insert_table"]
        self.assertEqual(it.get("risk_level"), "medium")
        self.assertEqual(it.get("rollback_strategy"), "excel_undo")

        fc = actions["format_cells"]
        self.assertEqual(fc.get("risk_level"), "medium")
        self.assertEqual(fc.get("rollback_strategy"), "excel_undo")

    # --- 2. Excel App Helpers & AppleScript Generation ---

    def test_column_letter_conversion(self):
        self.assertEqual(excel.col_letter(1), "A")
        self.assertEqual(excel.col_letter(2), "B")
        self.assertEqual(excel.col_letter(26), "Z")
        self.assertEqual(excel.col_letter(27), "AA")
        self.assertEqual(excel.col_letter(28), "AB")

    def test_escape_as_string(self):
        self.assertEqual(excel._escape_as_string(""), '""')
        self.assertEqual(excel._escape_as_string("Test"), '"Test"')
        self.assertEqual(excel._escape_as_string('Test "quotes"'), '"Test \\"quotes\\""')
        self.assertEqual(excel._escape_as_string("Riga 1\nRiga 2"), '"Riga 1" & return & "Riga 2"')

    def test_excel_applescript_dry_run(self):
        ok, wb = excel.create_workbook(title="Budget 2026", headers=["Mese", "Entrate", "Uscite"])
        self.assertTrue(ok)
        self.assertEqual(wb, "DRY_RUN_OK")

        ok, msg = excel.insert_table(headers=["Col 1", "Col 2"])
        self.assertTrue(ok)

        ok, msg = excel.format_cells(range_ref="A1:B10", bold=True, currency=True)
        self.assertTrue(ok)

        ok, msg = excel.close_workbook(wb_name="Cartel1", saving=False)
        self.assertTrue(ok)

        ok, msg = excel.undo_last()
        self.assertTrue(ok)

    # --- 3. Executor Routing & Rollback Strategy ---

    def test_executor_routing(self):
        self.assertEqual(resolve_app_name("excel"), "Microsoft Excel")
        self.assertEqual(resolve_app_name("com.microsoft.excel"), "Microsoft Excel")
        self.assertEqual(resolve_app_name("word"), "Microsoft Word")

    def test_executor_rollback_strategies(self):
        ok, msg = execute_rollback_strategy("close_created_workbook_verified", {"wb_name": "TestBook.xlsx"})
        self.assertTrue(ok)
        self.assertIn("TestBook.xlsx", msg)

        ok, msg = execute_rollback_strategy("excel_undo", {})
        self.assertTrue(ok)
        self.assertIn("Excel", msg)

    # --- 4. Engine Semantic Parsing & Extraction ---

    def test_analyze_create_workbook_with_title_and_headers(self):
        text = "crea file excel con titolo Bilancio 2026 e colonne Mese, Ricavi, Costi"
        conf, intent, params, alts = self.engine.analyze(text)

        self.assertGreaterEqual(conf, 0.85)
        self.assertEqual(intent, "excel_create_workbook")
        self.assertEqual(params.get("title"), "Bilancio 2026")
        self.assertEqual(params.get("headers"), ["Mese", "Ricavi", "Costi"])

    def test_analyze_create_workbook_simple(self):
        text = "nuovo foglio excel"
        conf, intent, params, alts = self.engine.analyze(text)

        self.assertGreaterEqual(conf, 0.85)
        self.assertEqual(intent, "excel_create_workbook")
        self.assertEqual(params.get("title"), "")
        self.assertEqual(params.get("headers"), [])

    def test_analyze_insert_table(self):
        text = "inserisci tabella con colonne Prodotto, Quantita, Prezzo"
        conf, intent, params, alts = self.engine.analyze(text, frontmost_app="Microsoft Excel")

        self.assertGreaterEqual(conf, 0.85)
        self.assertEqual(intent, "excel_insert_table")
        self.assertEqual(params.get("headers"), ["Prodotto", "Quantita", "Prezzo"])

    def test_analyze_format_cells_currency(self):
        text = "formatta celle B2:B20 in valuta"
        conf, intent, params, alts = self.engine.analyze(text, frontmost_app="Microsoft Excel")

        self.assertGreaterEqual(conf, 0.85)
        self.assertEqual(intent, "excel_format_cells")
        self.assertEqual(params.get("range"), "B2:B20")
        self.assertTrue(params.get("currency"))

    def test_analyze_format_cells_bold(self):
        text = "grassetto su celle"
        conf, intent, params, alts = self.engine.analyze(text, frontmost_app="Microsoft Excel")

        self.assertGreaterEqual(conf, 0.85)
        self.assertEqual(intent, "excel_format_cells")
        self.assertEqual(params.get("range"), "selection")
        self.assertTrue(params.get("bold"))

    # --- 5. Execution & Surgical Rollback Integration ---

    def test_execute_create_workbook_and_surgical_rollback(self):
        ok, msg = self.engine.execute(
            "excel_create_workbook",
            {"title": "Report Annuale", "headers": ["Q1", "Q2", "Q3", "Q4"]},
            prompt="crea foglio excel per report"
        )
        self.assertTrue(ok)
        self.assertIn("Report Annuale", msg)

        # Verify action tracking in atticus_feedback
        action = atticus_feedback.get_last_action()
        self.assertIsNotNone(action)
        self.assertEqual(action.get("action_type"), "excel_create")
        self.assertEqual(action.get("rollback_strategy"), "close_created_workbook_verified")
        self.assertEqual(action.get("metadata", {}).get("title"), "Report Annuale")

        # Test handle_annulla() surgical rollback
        undone, undo_msg = atticus_feedback.handle_annulla()
        self.assertTrue(undone)
        self.assertIn("Chiusa cartella di lavoro", undo_msg)

        # Verify last action was cleared
        self.assertIsNone(atticus_feedback.get_last_action())

    def test_execute_format_cells_and_undo_rollback(self):
        ok, msg = self.engine.execute(
            "excel_format_cells",
            {"range": "A1:C1", "bold": True, "currency": False},
            prompt="grassetto su celle A1:C1"
        )
        self.assertTrue(ok)

        # Verify action tracking
        action = atticus_feedback.get_last_action()
        self.assertIsNotNone(action)
        self.assertEqual(action.get("action_type"), "excel_undo")
        self.assertEqual(action.get("rollback_strategy"), "excel_undo")

        # Test handle_annulla() native undo
        undone, undo_msg = atticus_feedback.handle_annulla()
        self.assertTrue(undone)
        self.assertIn("Annullata ultima modifica su Excel", undo_msg)


if __name__ == "__main__":
    unittest.main()
