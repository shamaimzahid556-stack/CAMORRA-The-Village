"""Semantic retrieval over the verified knowledge base.

How a section is scored for a question:
  * TF-IDF cosine over lemmas              (word meaning, ignoring word form)
  * TF-IDF cosine over 3-letter pieces     (still matches after typos / inflections)
  * entity boosts                          (the question mentions the Detective -> sections about
                                            the Detective score higher; "START VOTING" -> the
                                            section that explains that button)
  * intent prior                           (a strategy question prefers strategy_tips.md)

The synonym dictionary in understanding.py maps "investigator", "killer", "medic" ... to the
real game concepts, so "How do I find the killer?" reaches the Detective and Mafia sections.
This is lexical + concept-based retrieval. It is not a neural embedding model. For a rulebook of
this size that is simple, free, offline and easy to debug; an embedding model can be added later
behind the same `search()` interface.
"""
from dataclasses import dataclass

from shared.nlp import STOP_WORDS, TfidfIndex, tokenize, normalize

INTENT_FILE_PRIOR = {
    "role_explanation": {"roles": 0.10, "game_overview": 0.03},
    "night_guidance": {"night_actions": 0.10, "roles": 0.04},
    "day_guidance": {"game_phases": 0.10},
    "voting_help": {"voting": 0.12},
    "win_condition": {"win_conditions": 0.12},
    "interface_help": {"interface_guide": 0.12},
    "troubleshooting": {"troubleshooting": 0.12},
    "strategy": {"strategy_tips": 0.22, "roles": 0.02},
    "game_overview": {"game_overview": 0.12},
    "situation_guidance": {"night_actions": 0.06, "game_phases": 0.06, "voting": 0.04, "roles": 0.03},
}


@dataclass
class Hit:
    chunk: object
    score: float
    word_sim: float
    char_sim: float
    boost: float


class Retriever:
    def __init__(self, kb, understanding):
        self.kb, self.u = kb, understanding
        self.chunks = kb.chunks
        self._docs, self._ents, self._title_ents, self._title_len = [], [], [], []
        for c in self.chunks:
            title_l = normalize(tokenize(c.title), understanding.vocab)
            body_l = normalize(tokenize(c.text + " " + c.simple), understanding.vocab)
            self._title_len.append(len([l for l in title_l if l not in STOP_WORDS]))
            self._docs.append([l for l in title_l * 2 + body_l if l not in STOP_WORDS])
            self._ents.append({(t, n) for t, n, _, _ in understanding.gazetteer.find(body_l + title_l)})
            self._title_ents.append({(t, n) for t, n, _, _ in understanding.gazetteer.find(title_l)})
        self.words = TfidfIndex(self._docs)
        self.chars = TfidfIndex(self._docs, use_chars=True)

    def search(self, content_lemmas, entities, intent_scores=None, k=4):
        if not content_lemmas and not entities:
            return []
        ws = self.words.similarities(content_lemmas)
        cs = self.chars.similarities(content_lemmas)
        q_ents = {(e.type, e.name) for e in entities}
        # concepts carried over from the previous turn count for half as much as ones typed just now
        weight = {}
        for e in entities:
            w = 0.5 if getattr(e, "text", "").startswith("(from previous") else 1.0
            weight[(e.type, e.name)] = max(weight.get((e.type, e.name), 0.0), w)
        # blend the file priors of every plausible intent (a message can be "night" AND "confused")
        prior = {}
        top = max((intent_scores or {}).values(), default=0)
        if top > 0:
            for name, sc in intent_scores.items():
                if sc >= 0.4 * top:
                    for f, w in INTENT_FILE_PRIOR.get(name, {}).items():
                        prior[f] = prior.get(f, 0.0) + w * min(1.0, sc / top)
        hits = []
        for i, c in enumerate(self.chunks):
            boost = 0.0
            for ent in q_ents:
                etype = ent[0]
                if ent in self._title_ents[i]:
                    boost += weight[ent] * {"ROLE": 0.30, "PHASE": 0.14, "BUTTON": 0.30, "MECHANIC": 0.20, "TEAM": 0.20,
                                            "ACTION": 0.08}.get(etype, 0.05)
                elif ent in self._ents[i]:
                    boost += weight[ent] * {"ROLE": 0.07, "PHASE": 0.03, "BUTTON": 0.22, "MECHANIC": 0.10, "TEAM": 0.05,
                                            "ACTION": 0.06}.get(etype, 0.02)
            boost += prior.get(c.file, 0.0)
            # a section titled about a DIFFERENT phase / role than the one asked about is a worse match
            for etype, penalty in (("PHASE", 0.20), ("ROLE", 0.15)):
                asked = {n for t, n in q_ents if t == etype}
                titled = {n for t, n in self._title_ents[i] if t == etype}
                if asked and titled and not (asked & titled):
                    boost -= penalty
            # sections about side features (sound, the chat helper) only win when the question is about them
            for aux in (("MECHANIC", "sound"), ("MECHANIC", "companion")):
                if aux in self._title_ents[i] and aux not in q_ents:
                    boost -= 0.10
            if not any(t == "ROLE" for t, _ in q_ents) and any(t == "ROLE" for t, _ in self._title_ents[i]):
                boost -= 0.06                      # no role mentioned: prefer the general section
            if self._title_len[i] <= 2 and any(e in self._title_ents[i] for e in q_ents):
                boost += 0.12                      # the section is named exactly after the concept asked about
            score = 0.62 * ws[i] + 0.20 * cs[i] + boost
            hits.append(Hit(c, score, ws[i], cs[i], boost))
        hits.sort(key=lambda h: -h.score)
        return hits[:k]
