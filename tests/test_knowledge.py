import shutil
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT
from chatbot import verify_rules
from chatbot.knowledge import load_knowledge, load_facts


class KnowledgeIntegrity(unittest.TestCase):
    def test_documented_facts_match_the_real_game_engine(self):
        failed = [c for c in verify_rules.run_checks() if not c.ok]
        self.assertEqual(failed, [], failed)

    def test_every_documented_file_is_loaded_and_placeholders_resolved(self):
        kb = load_knowledge()
        self.assertGreaterEqual(len(kb.chunks), 60)
        for c in kb.chunks:
            self.assertNotIn("{{", c.text + c.simple)
        files = {c.file for c in kb.chunks}
        for needed in ("game_overview", "roles", "game_phases", "night_actions", "voting", "win_conditions",
                       "interface_guide", "troubleshooting"):
            self.assertIn(needed, files)

    def test_every_role_in_the_code_is_documented(self):
        kb = load_knowledge()
        for role in load_facts()["roles"]:
            self.assertIsNotNone(kb.get(f"roles.{role.lower()}"), role)

    def test_unknown_placeholder_fails_loudly(self):
        tmp = Path(tempfile.mkdtemp())
        shutil.copytree(ROOT / "game_knowledge", tmp / "k")
        (tmp / "k" / "roles.md").write_text("# R\n\n## X\nThere are {{no_such_fact}} things.\n", encoding="utf-8")
        with self.assertRaises(KeyError):
            load_knowledge(tmp / "k")

    def test_approved_text_changes_only_the_simple_explanation(self):
        tmp = Path(tempfile.mkdtemp())
        shutil.copytree(ROOT / "game_knowledge", tmp / "k")
        (tmp / "k" / "approved" / "roles.detective.md").write_text(
            "chunk: roles.detective\nThe Detective checks one person each night.\n", encoding="utf-8")
        (tmp / "k" / "proposals" / "roles.mafia.md").write_text(
            "chunk: roles.mafia\nMafia can kill twice.\n", encoding="utf-8")
        base, kb = load_knowledge(), load_knowledge(tmp / "k")
        self.assertEqual(base.get("roles.detective").text, kb.get("roles.detective").text)
        self.assertEqual(kb.get("roles.detective").simple, "The Detective checks one person each night.")
        self.assertEqual(base.get("roles.mafia").simple, kb.get("roles.mafia").simple)   # proposals are never loaded

    def test_docs_do_not_claim_unimplemented_features(self):
        text = " ".join(c.text for c in load_knowledge().chunks).lower()
        for bad in ("sheriff", "jester", "skip button exists", "chat room"):
            self.assertNotIn(bad, text)


if __name__ == "__main__":
    unittest.main()
