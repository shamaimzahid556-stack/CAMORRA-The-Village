"""Measures how well retrieval finds the right rulebook sections for a set of test questions."""
import json

from .config import KNOWLEDGE_DIR
from .understanding import update_memory


def load_eval(path=None):
    return json.loads((path or KNOWLEDGE_DIR / "eval_questions.json").read_text(encoding="utf-8"))


def run_eval(engine, data=None, verbose=False):
    data = data or load_eval()
    rows, top1, top3, n = [], 0, 0, 0
    for item in data["single"]:
        a, ents, hits, _ = engine.interpret(item["q"], None, item.get("role"), item.get("phase"), k=3)
        ids = [h.chunk.id for h in hits]
        ok1, ok3 = bool(ids) and ids[0] in item["expect"], any(i in item["expect"] for i in ids)
        n += 1; top1 += ok1; top3 += ok3
        rows.append((ok1, ok3, item["q"], ids[:3]))
    for conv in data.get("conversations", []):
        memory = {}
        for turn in conv["turns"]:
            a, ents, hits, _ = engine.interpret(turn["q"], memory, None, None, k=3)
            ids = [h.chunk.id for h in hits]
            if a.wants_simpler and memory.get("chunks"):      # confusion-aware turns reuse the previous topic
                ids = list(memory["chunks"])
            ok1, ok3 = bool(ids) and ids[0] in turn["expect"], any(i in turn["expect"] for i in ids)
            n += 1; top1 += ok1; top3 += ok3
            rows.append((ok1, ok3, f"[{conv['name']}] {turn['q']}", ids[:3]))
            update_memory(memory, ents, ids[:2], a.intent)
    n_safe = max(n, 1)    # an empty question set reports 0.0 instead of dividing by zero
    result = {"total": n, "top1": top1 / n_safe, "top3": top3 / n_safe, "failures": [r for r in rows if not r[1]],
              "weak": [r for r in rows if r[1] and not r[0]]}
    if verbose:
        for ok1, ok3, q, ids in rows:
            if not ok3:
                print("  MISS ", q, "->", ids)
    return result
