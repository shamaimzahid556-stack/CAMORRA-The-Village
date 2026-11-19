"""Runs the Node-based front-end tests (chat widget + ambient sound) when Node.js is installed."""
import shutil
import subprocess
import unittest
from pathlib import Path

JS = Path(__file__).resolve().parent / "js"


@unittest.skipUnless(shutil.which("node"), "Node.js not installed: front-end tests skipped")
class FrontEnd(unittest.TestCase):
    def run_js(self, name):
        r = subprocess.run(["node", str(JS / name)], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_chat_widget(self):
        self.run_js("test_chat_ui.js")

    def test_ambient_sound(self):
        self.run_js("test_sound.js")

    def test_sound_files_exist_and_are_referenced(self):
        root = Path(__file__).resolve().parent.parent
        src = (root / "static" / "sound.js").read_text(encoding="utf-8")
        for name in ("day-ambience.wav", "night-ambience.wav", "dark-ambience.wav", "tension-loop.wav", "owl-hoot.mp3", "wolf-howl.mp3",
                     "crow-caw.mp3", "creak.mp3", "morning-bell.mp3", "night-fall.mp3", "ui-click.mp3", "role-reveal.mp3",
                     "win-civilians.mp3", "win-mafia.mp3"):
            self.assertIn(name, src)
            self.assertGreater((root / "static" / "sounds" / name).stat().st_size, 1_000, name)
        self.assertTrue((root / "static" / "chatbot logo.png").exists())
        html = (root / "static" / "index.html").read_text(encoding="utf-8")
        for needed in ("chatbot.css", "sound.css", "chatbot.js", "sound.js", "game.js", "style.css"):
            self.assertIn(needed, html)


if __name__ == "__main__":
    unittest.main()
