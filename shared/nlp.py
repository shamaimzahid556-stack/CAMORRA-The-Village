"""NLP toolkit (AI subject: NLP).  Written from scratch, standard library only.

These are the text-processing building blocks used by the CAMORRA chatbot (see `chatbot/`):

  tokenize + expand_contractions   split a message into normalised words
  lemmatize                        "voted" -> "vote", "was" -> "be"      (used for matching)
  edit_distance + correct_spelling "detecive" -> "detective"             (typo tolerance)
  Gazetteer                        named-entity extraction (roles, phases, buttons ...)
  TfidfIndex                       bag-of-words / TF-IDF vectors + cosine similarity (retrieval)
  stem                             rule-based stemmer  (coursework demo; production code uses lemmas)

What is NOT here: the language model that writes the final sentence is an external service (or
the offline composer in `chatbot/responder.py`). These functions are the explicit NLP code.
"""
import math
import re
from collections import Counter

# --------------------------------------------------------------------------------------------
# Tokenization
# --------------------------------------------------------------------------------------------
_SPECIAL_CONTRACTIONS = {
    "can't": "can not", "cannot": "can not", "won't": "will not", "shan't": "shall not",
    "i'm": "i am", "let's": "let us", "y'all": "you all", "ain't": "is not",
}


def expand_contractions(text):
    """"can't" -> "can not", "it's" -> "it is", "doesn't" -> "does not" (before tokenizing)."""
    text = text.lower().replace("\u2019", "'").replace("\u2018", "'")
    for k, v in _SPECIAL_CONTRACTIONS.items():
        text = re.sub(r"\b" + re.escape(k) + r"\b", v, text)
    text = re.sub(r"\b(\w+)n't\b", r"\1 not", text)
    text = re.sub(r"\b(\w+)'(re|ve|ll|d)\b", lambda m: m.group(1) + " " +
                  {"re": "are", "ve": "have", "ll": "will", "d": "would"}[m.group(2)], text)
    text = re.sub(r"\b(it|he|she|that|there|here|what|who|where|how|when|why)'s\b", r"\1 is", text)
    text = re.sub(r"\b(\w+)'s\b", r"\1", text)          # possessive: "doctor's" -> "doctor"
    return text


def tokenize(text):
    """Lower-case word and number tokens, contractions expanded."""
    return re.findall(r"[a-z0-9]+", expand_contractions(text))


STOP_WORDS = frozenset("""
a an the and or but if so of to in on at for with by from as into about than then too very just
is am are was were be been being do does did doing have has had having
i me my mine we us our you your yours he him his she her it its they them their this that these those
what which who whom whose when where why how there here
will would can could should shall may might must
also really please tell explain ok okay hey hi hello
""".split())


# --------------------------------------------------------------------------------------------
# Lemmatization (dictionary of irregular forms + suffix rules)
# --------------------------------------------------------------------------------------------
_IRREGULAR = {
    "was": "be", "were": "be", "is": "be", "are": "be", "am": "be", "been": "be", "being": "be",
    "did": "do", "does": "do", "done": "do", "doing": "do", "has": "have", "had": "have",
    "chose": "choose", "chosen": "choose", "found": "find", "saw": "see", "seen": "see",
    "went": "go", "gone": "go", "knew": "know", "known": "know", "said": "say", "told": "tell",
    "gave": "give", "given": "give", "took": "take", "taken": "take", "got": "get", "made": "make",
    "left": "leave", "kept": "keep", "lost": "lose", "won": "win", "caught": "catch",
    "lied": "lie", "lying": "lie", "dying": "die", "died": "die", "hid": "hide", "hidden": "hide",
    "men": "man", "women": "woman", "people": "person", "children": "child",
    "better": "good", "best": "good", "worse": "bad", "worst": "bad",
    "players": "player", "mafias": "mafia", "bodies": "body", "lives": "life",
}
_KEEP = frozenset("""
morning evening nothing something anything everything king thing during spring string ring bring
sing wing sting swing bus gas this his is us yes pass miss boss class less mess process access
status focus bonus virus always perhaps news series species mafia villa
""".split())
_VOWELS = "aeiou"


def lemmatize(word, vocab=None):
    """Return the dictionary form of `word`.

    `vocab` (optional set of known words) lets the rules choose real words:
    "voting" -> "vot" -> "vote" because "vote" is in the vocabulary.
    """
    w = word.lower()
    if w in _IRREGULAR:
        return _IRREGULAR[w]
    if w in _KEEP or len(w) <= 3 or not w.isalpha():
        return w

    def pick(stem_):
        """Choose between stem_, stem_+'e' and an un-doubled stem using the vocabulary."""
        cands = [stem_]
        if len(stem_) >= 2 and stem_[-1] == stem_[-2] and stem_[-1] not in "lsz":
            cands.insert(0, stem_[:-1])                       # stopp -> stop
        cands.append(stem_ + "e")                             # vot -> vote
        if vocab:
            for c in cands:
                if c in vocab:
                    return c
        if len(stem_) >= 2 and stem_[-1] == stem_[-2] and stem_[-1] not in "lsz":
            return stem_[:-1]
        # long stems ending in "at" (investigat, eliminat) almost always lost a final 'e'
        if len(stem_) >= 7 and stem_.endswith("at"):
            return stem_ + "e"
        # consonant-vowel-consonant stems of 3-4 letters usually lost a final 'e'
        if (3 <= len(stem_) <= 4 and stem_[-1] not in _VOWELS + "wxy"
                and stem_[-2] in _VOWELS and stem_[-3] not in _VOWELS):
            return stem_ + "e"
        return stem_

    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("ing") and len(w) > 5:
        return pick(w[:-3])
    if w.endswith("ed") and len(w) > 4:
        return pick(w[:-2])
    if w.endswith(("sses", "xes", "zes", "ches", "shes")) and len(w) > 4:
        return w[:-2]
    if w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) > 3:
        return w[:-1]
    return w


def normalize(tokens, vocab=None):
    """tokens -> lemmas."""
    return [lemmatize(t, vocab) for t in tokens]


# --------------------------------------------------------------------------------------------
# Stemming (coursework demonstration; the chatbot itself matches on lemmas)
# --------------------------------------------------------------------------------------------
def stem(word):
    """Crude Porter-style suffix stripping. A stem need not be a real word: voted -> vot."""
    w = word.lower()
    if w in _KEEP or len(w) <= 3:
        return w
    for suf, rep in (("ational", "ate"), ("ies", "y"), ("sses", "ss"), ("ing", ""), ("edly", ""),
                     ("ed", ""), ("ly", ""), ("es", ""), ("s", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            out = w[: len(w) - len(suf)] + rep
            if rep == "" and len(out) > 2 and out[-1] == out[-2] and out[-1] not in "lsz":
                out = out[:-1]
            return out
    return w


# --------------------------------------------------------------------------------------------
# Spelling tolerance
# --------------------------------------------------------------------------------------------
def edit_distance(a, b):
    """Damerau-Levenshtein (optimal string alignment): insert, delete, substitute, swap."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[la][lb]


def correct_spelling(token, vocab, protected=frozenset()):
    """Return the closest `vocab` word for a misspelled token, else the token unchanged.

    Conservative on purpose: words shorter than 5 letters are never changed, one edit is allowed
    up to 7 letters and two edits for longer words, and `protected` real words are left alone.
    """
    if token in vocab or token in protected or token in STOP_WORDS or len(token) < 5 or not token.isalpha():
        return token
    allowed = 1 if len(token) <= 7 else 2
    best, best_d = None, allowed + 1
    for cand in vocab:
        if abs(len(cand) - len(token)) > allowed or not cand.isalpha():
            continue
        dist = edit_distance(token, cand)
        if dist < best_d or (dist == best_d and best is not None and cand < best):
            best, best_d = cand, dist
    return best if best is not None and best_d <= allowed else token


# --------------------------------------------------------------------------------------------
# Named-entity recognition (gazetteer = dictionary of names and their aliases)
# --------------------------------------------------------------------------------------------
class Gazetteer:
    """Finds entities by matching (lemmatised) word sequences, longest match first.

    entries: {entity_type: {canonical_name: [alias phrase, ...]}}
    """

    def __init__(self, entries, vocab=None):
        self.vocab = vocab
        self.table = {}
        self.max_len = 1
        for etype, items in entries.items():
            for canonical, aliases in items.items():
                for phrase in [canonical] + list(aliases):
                    key = tuple(normalize(tokenize(phrase), vocab))
                    if key:
                        self.table[key] = (etype, canonical)
                        self.max_len = max(self.max_len, len(key))

    def find(self, lemmas):
        """lemmas -> list of (entity_type, canonical, start, end)."""
        found, i = [], 0
        while i < len(lemmas):
            for n in range(min(self.max_len, len(lemmas) - i), 0, -1):
                hit = self.table.get(tuple(lemmas[i:i + n]))
                if hit:
                    found.append((hit[0], hit[1], i, i + n))
                    i += n
                    break
            else:
                i += 1
        return found


# --------------------------------------------------------------------------------------------
# Bag of words, TF-IDF and cosine similarity
# --------------------------------------------------------------------------------------------
def bag_of_words(tokens):
    """Counter of word -> how many times it appears (word order is ignored)."""
    return Counter(tokens)


def char_ngrams(token, n=3):
    padded = f"#{token}#"
    return [padded[i:i + n] for i in range(max(1, len(padded) - n + 1))]


class TfidfIndex:
    """TF-IDF vectors for a list of documents (each a list of tokens) plus cosine search.

    tf  = 1 + log(count)              idf = log((N + 1) / (df + 1)) + 1
    Two views are scored: whole words, and 3-letter character pieces (which still match when a
    word is misspelled or inflected).
    """

    def __init__(self, docs_tokens, use_chars=False):
        self.use_chars = use_chars
        self.n_docs = len(docs_tokens)
        feats = [self._features(d) for d in docs_tokens]
        df = Counter()
        for f in feats:
            df.update(f.keys())
        self.idf = {t: math.log((self.n_docs + 1) / (c + 1)) + 1 for t, c in df.items()}
        self.vectors = [self._vector(f) for f in feats]

    def _features(self, tokens):
        if self.use_chars:
            tokens = [g for t in tokens for g in char_ngrams(t)]
        return bag_of_words(tokens)

    def _vector(self, counts):
        vec = {t: (1 + math.log(c)) * self.idf.get(t, 1.0) for t, c in counts.items() if t in self.idf}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    def similarities(self, query_tokens):
        q = self._vector(self._features(query_tokens))
        return [sum(w * doc.get(t, 0.0) for t, w in q.items()) for doc in self.vectors]
