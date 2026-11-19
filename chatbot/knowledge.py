"""Loads the verified CAMORRA knowledge base (game_knowledge/*.md) into searchable chunks.

* One chunk = one `## heading` section of a markdown file.
* A line starting with "Simple version:" is stored separately and used when a player says they
  did not understand (confusion-aware answers).
* `{{placeholders}}` are filled from game_knowledge/facts.json, which chatbot/verify_rules.py
  checks against the real game engine, so the numbers in the text cannot go stale.
* Files in game_knowledge/approved/ may replace a chunk's *simple explanation only*. They can
  never change rules text. game_knowledge/proposals/ is never loaded.
"""
import json
import re
from dataclasses import dataclass, field

from .config import KNOWLEDGE_DIR


@dataclass
class Chunk:
    id: str
    file: str
    doc_title: str
    title: str
    text: str
    simple: str = ""
    approved_simple: bool = False

    @property
    def label(self):
        return f"{self.doc_title} › {self.title}"


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def load_facts(directory=KNOWLEDGE_DIR):
    facts = json.loads((directory / "facts.json").read_text(encoding="utf-8"))
    facts.pop("_comment", None)
    acts = facts.get("villager_activities", [])
    facts["villager_activity_count"] = len(acts)
    facts["villager_activities"] = ", ".join(acts)
    facts["discussion_minutes"] = facts["discussion_seconds"] // 60
    facts["answer_styles"] = ", ".join(facts.get("answer_styles", []))
    return facts


def _fill(text, facts, where):
    def repl(m):
        key = m.group(1).strip()
        if key not in facts:
            raise KeyError(f"Unknown placeholder {{{{{key}}}}} in {where}")
        return str(facts[key])
    return re.sub(r"\{\{\s*([a-z_]+)\s*\}\}", repl, text)


def _tidy(sentence):
    """Make a simple explanation start with a capital letter and end with a full stop."""
    sentence = sentence.strip()
    if not sentence:
        return sentence
    sentence = sentence[0].upper() + sentence[1:]
    return sentence if sentence[-1] in ".!?" else sentence + "."


def _split_markdown(raw, stem, facts):
    doc_title, chunks, cur_title, cur_lines = stem.replace("_", " ").title(), [], None, []

    def flush():
        if cur_title is None:
            return
        body, simple = [], ""
        for line in cur_lines:
            if line.lower().startswith("simple version:"):
                simple = line.split(":", 1)[1].strip()
            else:
                body.append(line)
        simple = _tidy(simple)
        text = _fill("\n".join(body).strip(), facts, f"{stem}.md")
        if text:
            chunks.append(Chunk(f"{stem}.{slugify(cur_title)}", stem, doc_title, cur_title, text,
                                _fill(simple, facts, f"{stem}.md")))

    for line in raw.splitlines():
        if line.startswith("# ") and not line.startswith("## "):
            doc_title = line[2:].strip()
        elif line.startswith("## "):
            flush()
            cur_title, cur_lines = line[3:].strip(), []
        elif cur_title is not None:
            cur_lines.append(line)
    flush()
    for c in chunks:
        c.doc_title = doc_title
    return chunks


@dataclass
class KnowledgeBase:
    facts: dict = field(default_factory=dict)
    chunks: list = field(default_factory=list)

    def __post_init__(self):
        self.by_id = {c.id: c for c in self.chunks}

    def get(self, chunk_id):
        return self.by_id.get(chunk_id)


def load_knowledge(directory=KNOWLEDGE_DIR, include_approved=True):
    facts = load_facts(directory)
    chunks = []
    for path in sorted(directory.glob("*.md")):
        chunks.extend(_split_markdown(path.read_text(encoding="utf-8"), path.stem, facts))
    kb = KnowledgeBase(facts, chunks)
    if include_approved:
        for path in sorted((directory / "approved").glob("*.md")):
            lines = path.read_text(encoding="utf-8").splitlines()
            if not lines or not lines[0].lower().startswith("chunk:"):
                continue
            target = kb.get(lines[0].split(":", 1)[1].strip())
            text = " ".join(l.strip() for l in lines[1:] if l.strip())
            if target is not None and text:
                target.simple, target.approved_simple = _tidy(text), True
    return kb
