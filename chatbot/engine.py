"""Knowledge base + NLP pipeline in one object. Shared by the chat service, the evaluation
harness and the improvement tools so they all behave identically."""
from shared.nlp import normalize, tokenize

from .knowledge import load_knowledge
from .retrieval import Retriever
from .understanding import Understanding, resolve_followup

# Below this combined score (and with no recognised game concept) a question is treated as
# unrelated to CAMORRA instead of being answered from a weakly matching section.
OFF_TOPIC_SCORE = 0.16


class Engine:
    def __init__(self, kb=None):
        self.kb = kb or load_knowledge()
        surface = set()
        for c in self.kb.chunks:
            surface.update(tokenize(f"{c.title} {c.text} {c.simple}"))
        vocab = surface | set(normalize(sorted(surface)))
        self.understanding = Understanding(vocab)
        self.retriever = Retriever(self.kb, self.understanding)

    def interpret(self, text, memory=None, ctx_role=None, ctx_phase=None, k=4):
        """text -> (analysis, resolved entities, ranked hits, notes)."""
        analysis = self.understanding.analyse(text)
        entities, notes = resolve_followup(analysis, memory or {}, ctx_role, ctx_phase)
        hits = self.retriever.search(analysis.content, entities, analysis.intent_scores, k)
        return analysis, entities, hits, notes

    def is_about_camorra(self, analysis, entities, hits):
        from .understanding import OFF_TOPIC_MARKERS
        strong = any(e.type in ("ROLE", "TEAM", "PHASE", "BUTTON") for e in entities)
        if not strong and OFF_TOPIC_MARKERS & set(analysis.lemmas) | (OFF_TOPIC_MARKERS & set(analysis.tokens)):
            return False
        if any(e.type in ("ROLE", "TEAM", "PHASE", "BUTTON", "MECHANIC") for e in entities):
            return True
        if any(l in self.understanding.vocab_domain for l in analysis.lemmas):
            return True
        known = [l for l in analysis.content if l in self.retriever.words.idf]
        mostly_known = bool(analysis.content) and len(known) / len(analysis.content) >= 0.5
        return bool(hits) and hits[0].score >= OFF_TOPIC_SCORE and analysis.intent != "unknown" and mostly_known
