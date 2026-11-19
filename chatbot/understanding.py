"""Natural-language understanding for the CAMORRA AI Companion (explicit NLP code).

Pipeline for every message:
  1. tokenize + expand contractions                  (shared.nlp)
  2. spelling tolerance against the game vocabulary  (edit distance)
  3. lemmatize                                       ("voted" -> "vote")
  4. entity extraction with a CAMORRA gazetteer      (roles, phases, actions, buttons, mechanics)
  5. weighted-cue intent scoring                     (what does the player want?)
  6. follow-up detection + resolution against the temporary session memory
     ("When can I use it?" -> "it" = the role discussed in the previous turn)

The vocabulary below is a dictionary of concepts and synonyms. It is NOT a list of questions
and answers: new wordings are understood through lemmas, synonyms, typos and scoring.
"""
import re
from dataclasses import dataclass, field

from shared.nlp import (STOP_WORDS, Gazetteer, correct_spelling, lemmatize, normalize, tokenize)

# ----------------------------------------------------------------------------------------------
# Concept dictionary (synonyms -> canonical game concept)
# ----------------------------------------------------------------------------------------------
GAZETTEER_ENTRIES = {
    "ROLE": {
        "Mafia": ["mafia", "mob", "mobster", "killer", "murderer", "assassin", "villain", "culprit",
                  "bad guy", "bad team", "traitor", "werewolf", "wolf", "enemy", "enemies", "criminal"],
        "Detective": ["detective", "investigator", "inspector", "sleuth", "cop", "seer", "police"],
        "Doctor": ["doctor", "medic", "healer", "nurse", "physician", "doc"],
        "Villager": ["villager", "townsperson", "townsfolk", "citizen", "innocent", "normal player",
                     "regular player", "ordinary player", "plain villager"],
    },
    "TEAM": {
        "Town": ["town", "town team", "civilian", "good guy", "good team", "good side"],
    },
    "PHASE": {
        "night": ["night", "nighttime", "night phase", "tonight", "after dark", "nightfall"],
        "morning": ["morning", "morning report", "dawn", "daybreak", "sunrise"],
        "day": ["day", "daytime", "day phase", "daylight"],
        "discussion": ["discussion", "discuss", "debate", "talk", "talking", "conversation", "timer",
                       "countdown", "clock", "time limit"],
        "voting": ["voting", "vote", "ballot", "poll", "election"],
        "elimination": ["elimination", "eliminate", "eliminated", "lynch", "kick out", "vote out", "removed"],
        "role assignment": ["role assignment", "assign role", "assigned role", "role reveal", "deal role"],
        "setup": ["setup", "set up", "start screen", "configuration", "settings screen"],
        "game over": ["game over", "result screen", "final screen", "end screen", "win screen"],
    },
    "ACTION": {
        "investigate": ["investigate", "inspect", "scan", "examine", "look into", "find out", "interrogate",
                        "check someone", "check somebody", "check a player", "check a person", "check people",
                        "check players", "check who", "check if", "check whether", "check out"],
        "protect": ["protect", "save", "heal", "guard", "shield", "rescue", "cure"],
        "kill": ["kill", "murder", "attack", "target", "assassinate", "shoot", "stab", "victim"],
        "shortlist": ["shortlist", "short list", "candidate list"],
        "choose": ["select", "choose", "pick", "tap", "click", "press"],
        "activity": ["activity", "diary", "study", "read quietly", "go to sleep"],
    },
    "MECHANIC": {
        "tie": ["tie", "tied", "tiebreak", "tie break", "equal votes", "same number of votes", "draw"],
        "win": ["win", "winner", "victory", "victorious", "lose", "loser", "defeat", "win condition",
                "game end", "end of the game", "who wins"],
        "self-save": ["self save", "save myself", "protect myself", "save themselves", "protect themselves",
                      "save himself", "save herself", "protect yourself", "protect himself", "protect herself"],
        "partner": ["partner", "teammate", "fellow mafia", "other mafia", "ally"],
        "private result": ["investigation result", "private result", "detective result", "result card"],
        "pass device": ["pass the device", "pass device", "hand over the device", "pass the phone"],
        "sound": ["sound", "music", "audio", "volume", "mute", "owl", "wolf", "bird", "ambience",
                  "ambient", "noise", "speaker"],
        "companion": ["ai companion", "companion", "chatbot", "chat bot", "this chat", "chat panel",
                      "assistant", "chat"],
        "player count": ["how many players", "number of players", "player count", "total characters", "how many mafia",
                         "how many detectives", "how many doctors", "how many villagers", "how many roles",
                         "number of mafia", "how many people", "how many characters"],
    },
    "BUTTON": {
        "START THE GAME": ["start the game", "start game"],
        "SHOW MY ROLE": ["show my role", "show role", "reveal my role"],
        "HIDE MY ROLE": ["hide my role", "hide role"],
        "I'M READY": ["i'm ready", "i am ready", "ready button"],
        "CONTINUE": ["continue button", "continue"],
        "BEGIN NIGHT": ["begin night", "start night"],
        "BEGIN DISCUSSION": ["begin discussion", "start discussion"],
        "START VOTING": ["start voting", "begin voting"],
        "BEGIN NEXT NIGHT": ["begin next night", "next night"],
        "VIEW GAME RESULT": ["view game result"],
        "HIDE RESULT & CONTINUE": ["hide result and continue", "hide result"],
        "NEW GAME": ["new game", "restart", "play again"],
    },
}

# Some actions and mechanics only make sense for one role, so they imply it.
IMPLIED_ROLE = {("ACTION", "investigate"): "Detective", ("ACTION", "protect"): "Doctor", ("ACTION", "shortlist"): "Mafia",
                ("ACTION", "kill"): "Mafia", ("MECHANIC", "self-save"): "Doctor", ("MECHANIC", "partner"): "Mafia",
                ("MECHANIC", "private result"): "Detective"}

# Words that mean "find / expose the Mafia" -> a strategy question, not a role definition.
FIND_VERBS = frozenset("find identify catch detect spot expose uncover discover defeat beat stop fight guess recognize unmask".split())

# Intent cues: lemma (or lemma bigram/trigram) -> weight.
INTENT_CUES = {
    "role_explanation": {"role": 2, "power": 1.5, "ability": 2, "job": 1.5, "responsibility": 1.5, "purpose": 1,
                         "special": 0.8, "do what": 0.5, "can do": 0.8, "supposed": 0.6, "team": 1.2, "who be": 0.4},
    "night_guidance": {"night": 2.5, "tonight": 2.5, "my turn": 2, "turn": 1.2, "night turn": 1.5, "action": 1.2,
                       "ability": 0.8},
    "day_guidance": {"morning": 2.5, "discussion": 2.5, "discuss": 2, "talk": 1.5, "timer": 2, "countdown": 2,
                     "daytime": 2, "day": 1.2, "report": 1.5, "argue": 1.5},
    "voting_help": {"vote": 3.5, "voting": 3.5, "ballot": 3, "eliminate": 2, "elimination": 2, "tie": 2.5,
                    "majority": 2, "kick": 1.5},
    "win_condition": {"win": 3, "lose": 2.5, "victory": 3, "winner": 3, "defeat": 2, "game over": 2.5,
                      "end game": 2.5, "game end": 2.5, "objective": 2.5, "goal": 2.5, "how end": 2,
                      "who win": 3},
    "interface_help": {"button": 3, "click": 2.5, "press": 2.5, "tap": 2, "screen": 2, "where": 1.2, "menu": 1.5,
                       "sound": 2.5, "mute": 2.5, "volume": 2, "ready": 1, "disabled": 1, "panel": 1.5, "icon": 2},
    "troubleshooting": {"can not": 2, "disabled": 3, "stuck": 3, "error": 3, "wrong": 1.5, "confused": 3.4,
                        "confuse": 3.4, "confusing": 3.4, "understand": 1.5, "not work": 3, "unavailable": 3,
                        "problem": 2, "issue": 2, "refuse": 2, "broken": 2, "nothing happen": 3, "lost": 1.5,
                        "why": 1.4, "not allow": 2.5, "unable": 2.5, "missed": 2, "mistake": 2, "refresh": 2,
                        "glitch": 2.5, "bug": 2.5, "frozen": 2.5, "grey out": 3.2, "gray out": 3.2, "greyed": 3.2,
                        "grayed": 3.2, "dimmed": 3, "inactive": 3, "not click": 3, "can not click": 3, "locked": 2.5,
                        "blocked": 2.5, "unclickable": 3},
    "strategy": {"strategy": 3.6, "tip": 3.6, "advice": 3.6, "best way": 2.5, "trick": 2, "tactic": 2.5,
                 "suspicious": 2, "trust": 2, "lie": 2, "bluff": 2, "outsmart": 2.5, "who should": 2,
                 "how can we": 1.2, "how do we": 1.2, "clue": 2, "how should": 2, "act": 1.2, "behave": 2,
                 "accuse": 4, "blame": 3.6, "defend": 3.6, "play as": 2.5, "play the": 1.5, "lying": 1, "truth": 1.5, "liar": 2, "convince": 2, "survive": 2, "win as": 2.5},
    "situation_guidance": {"what do i do": 3.2, "what should i do": 3.2, "what now": 3.2, "what next": 3.2,
                           "what happen next": 3.2, "suppose to do": 3.2, "what do we do": 3.2, "what should we do": 3.2,
                           "what be going on": 3.2, "what be next": 3.2, "how do i proceed": 3.2, "how to proceed": 3.2,
                           "what come next": 3.2, "do now": 2.4, "do next": 2.4, "what can i do": 2.8, "where be i": 2.2,
                           "what be happening": 3, "i do not know what to do": 3.4},
    "game_overview": {"what be camorra": 4, "game": 0.6, "about": 0.5, "how play": 3, "how to play": 3,
                      "begin": 0.8, "start": 0.8, "player": 0.6, "many player": 2, "how many": 1.2,
                      "rule": 1.2, "overview": 3, "explain game": 3, "round": 1.5},
}
INTENT_ENTITY_WEIGHTS = {
    "ROLE": {"role_explanation": 2.5},
    "TEAM": {"role_explanation": 1.5, "win_condition": 0.8},
    "ACTION": {"night_guidance": 1.5},
    "BUTTON": {"interface_help": 3.5},
}
PHASE_INTENT = {"night": ("night_guidance", 3), "morning": ("day_guidance", 2.5), "day": ("day_guidance", 2),
                "discussion": ("day_guidance", 2.5), "voting": ("voting_help", 3), "elimination": ("voting_help", 2.5),
                "role assignment": ("role_explanation", 1.5), "setup": ("interface_help", 2.5),
                "game over": ("win_condition", 2.5)}
MECHANIC_INTENT = {"tie": ("voting_help", 2.5), "win": ("win_condition", 3), "self-save": ("night_guidance", 2),
                   "partner": ("role_explanation", 1.5), "private result": ("night_guidance", 2),
                   "pass device": ("interface_help", 2.5), "sound": ("interface_help", 3),
                   "companion": ("interface_help", 2.5), "player count": ("game_overview", 3)}

SIMPLER_PHRASES = ["still do not understand", "do not understand", "do not get it", "not clear", "unclear",
                   "explain again", "explain more simply", "simpler", "simply", "simple word", "simple term",
                   "eli5", "what do you mean", "say that again", "another way", "too complicated", "lost me", "i be lost",
                   "make it easier", "easier to understand", "in plain", "dumb it down", "do not follow", "does not make sense",
                   "make sense", "re explain", "reexplain", "once more", "rephrase", "break it down"]
DETAIL_PHRASES = ["more detail", "more info", "go deeper", "elaborate", "tell me more", "detail", "step by step",
                  "in depth", "full explanation", "everything about", "more about", "expand"]
FOLLOWUP_STARTS = ("and ", "what about", "how about", "also ", "then ", "but ", "ok and", "okay and",
                   "what if", "why not", "where ", "when ")
FOLLOW_CUE = re.compile(r"^\W*(?:ok\w*\W+)?(?:please\s+)?(?:explain\s+(?:it\s+|that\s+)?(?:more|again|further)|tell\s+me\s+more|more\s+(?:details?|please)|elaborate|go\s+on|continue|why\b|how\s+come|what\s+(?:happens|happened|comes|is)\s+(?:then|next|after(?:wards)?)|what\s+next|isko|iska|iski|uska|uski|isay|aur\s+(?:agar|batao|kuch)|phir\s+kya|give\s+(?:me\s+)?an?\s+example|an?\s+example|for\s+example|example\b)", re.I)
PRONOUNS = frozenset("it that this those these them they there one its".split())
PERSONAL = frozenset("i me my mine myself we our".split())
GREETING = re.compile(r"^(?:hi|hello|hey|hiya|yo|good\s+(?:morning|evening|afternoon)|greetings|howdy|sup)\b[\s!.,?]*$", re.I)
_THANKS_OPEN = r"(?:thanks?|thank\s+you|thx|ty|cheers|great|perfect|awesome|got\s+it|ok(?:ay)?|cool|nice)"
_THANKS_FILL = r"(?:thanks?|thank|you|thx|ty|so|very|much|a|lot|man|mate|bro|buddy|that|this|it|helps?|helped|helpful|again|all|the|for|your|help|great|perfect|awesome|cool|nice|ok(?:ay)?|got)"
# Only pure thanks / acknowledgements: "nice what does detective do" is a real question, not thanks.
THANKS = re.compile(rf"^{_THANKS_OPEN}(?:[\s,!.]+{_THANKS_FILL})*[\s!.,?]*$", re.I)
ABOUT_BOT = re.compile(
    r"\b(?:what\s+can\s+you\s+do|your\s+name|are\s+you\s+(?:a\s+)?(?:bot|ai|real|human)|what\s+is\s+this\s+chat|how\s+do\s+you\s+work)\b"
    r"|^\W*(?:(?:so|hey|hi|hello)\W+)?(?:who|what)\s+are\s+you\b\W*(?:exactly|really|even)?\W*$",
    re.I,
)
# Words that signal the question is about the game even if no entity was recognised.
DOMAIN_LEMMAS = frozenset("""game player role night day vote voting mafia detective doctor villager win lose button screen
turn phase discussion morning elimination eliminate target kill protect save investigate shortlist partner device
timer rule rules play team camorra civilian town screen""".split())

# Topics that are clearly not about CAMORRA (keeps the bot focused and saves model calls).
OFF_TOPIC_MARKERS = frozenset("""football soccer cricket basketball weather forecast recipe cook cooking poem poetry joke jokes
story essay homework movie film song lyrics music_video celebrity politics election_news stock bitcoin crypto python java javascript
programming code coding math maths equation capital country president translate translation horoscope news temperature
match cats dog dogs pizza restaurant flight hotel""".split())


@dataclass
class Entity:
    type: str
    name: str
    text: str = ""


@dataclass
class Analysis:
    raw: str
    tokens: list
    lemmas: list
    content: list                     # lemmas without stop words (used for retrieval)
    entities: list                    # [Entity]
    intent: str
    intent_scores: dict
    wants_simpler: bool = False
    wants_detail: bool = False
    is_followup: bool = False
    is_personal: bool = False
    smalltalk: str = ""               # "greeting" | "thanks" | "about_bot" | ""
    corrected: dict = field(default_factory=dict)

    def entity_names(self, etype):
        return [e.name for e in self.entities if e.type == etype]


class Understanding:
    """Build once (needs the knowledge base vocabulary for spelling tolerance and lemmatization)."""

    def __init__(self, kb_vocabulary):
        domain = set()
        for items in GAZETTEER_ENTRIES.values():
            for canonical, aliases in items.items():
                for phrase in [canonical] + aliases:
                    domain.update(tokenize(phrase))
        self.vocab = frozenset(set(kb_vocabulary) | domain)
        self.vocab_domain = frozenset(normalize(sorted(DOMAIN_LEMMAS), self.vocab))
        self.gazetteer = Gazetteer(GAZETTEER_ENTRIES, self.vocab)
        self.cues = {intent: {" ".join(normalize(tokenize(cue), self.vocab)): w for cue, w in cues.items()}
                     for intent, cues in INTENT_CUES.items()}
        self.simpler = [" ".join(normalize(tokenize(p), self.vocab)) for p in SIMPLER_PHRASES]
        self.detail = [" ".join(normalize(tokenize(p), self.vocab)) for p in DETAIL_PHRASES]
        # real English words that must never be "corrected" into a game word
        self.protected = frozenset("""saying talking speaking chatting asking telling listening cooking playing writing reading thinking their there where while which would could should about after again always another because before being
        between choose chosen clear click close doing during every first found given going great happen having himself itself
        later makes might never other people place point right should since something still taken thing think those three through
        under until using wanted whether whole without wrong yours""".split())

    # -- text -> lemmas ---------------------------------------------------------------------
    def normalise(self, text):
        tokens = tokenize(text)
        fixed, corrected = [], {}
        for t in tokens:
            c = correct_spelling(t, self.vocab, self.protected)
            if c != t:
                corrected[t] = c
            fixed.append(c)
        return tokens, normalize(fixed, self.vocab), corrected

    def analyse(self, text):
        tokens, lemmas, corrected = self.normalise(text)
        entities = [Entity(t, n, " ".join(lemmas[s:e])) for t, n, s, e in self.gazetteer.find(lemmas)]
        for e in list(entities):
            role = IMPLIED_ROLE.get((e.type, e.name))
            if role and not any(x.type == "ROLE" and x.name == role for x in entities):
                entities.append(Entity("ROLE", role, "(implied by the action)"))
        content = [l for l in lemmas if l not in STOP_WORDS]
        joined = " " + " ".join(lemmas) + " "

        small = ""
        stripped = text.strip()
        if GREETING.match(stripped):
            small = "greeting"
        elif THANKS.match(stripped) and len(tokens) <= 5:
            small = "thanks"
        elif ABOUT_BOT.search(stripped):
            small = "about_bot"

        wants_simpler = any(f" {p} " in joined for p in self.simpler)
        wants_detail = any(f" {p} " in joined for p in self.detail)

        scores = {k: 0.0 for k in self.cues}
        for intent, cues in self.cues.items():
            for cue, w in cues.items():
                if f" {cue} " in joined:
                    scores[intent] += w
        for e in entities:
            if e.type in INTENT_ENTITY_WEIGHTS:
                for intent, w in INTENT_ENTITY_WEIGHTS[e.type].items():
                    scores[intent] += w
            if e.type == "PHASE" and e.name in PHASE_INTENT:
                intent, w = PHASE_INTENT[e.name]
                scores[intent] += w
            if e.type == "MECHANIC" and e.name in MECHANIC_INTENT:
                intent, w = MECHANIC_INTENT[e.name]
                scores[intent] += w
        mafia_or_team = any(e.type in ("ROLE", "TEAM") and e.name in ("Mafia", "Town") for e in entities)
        if mafia_or_team and any(l in FIND_VERBS for l in lemmas):
            scores["strategy"] += 4.5
            scores["role_explanation"] *= 0.4

        intent = max(scores, key=scores.get) if max(scores.values()) > 0 else "unknown"
        has_topic = any(e.type in ("ROLE", "TEAM", "PHASE", "ACTION", "MECHANIC", "BUTTON") for e in entities)
        n_content = len(content)
        starts = " ".join(tokens)
        is_followup = bool(
            FOLLOW_CUE.match(text) or (set(lemmas) & PRONOUNS and not has_topic) or wants_simpler or wants_detail
            or (starts.startswith(FOLLOWUP_STARTS) and not has_topic)
            or (set(lemmas) & PRONOUNS and n_content <= 5))
        if (wants_simpler or wants_detail) and not has_topic:
            intent = "clarification"
        return Analysis(text, tokens, lemmas, content, entities, intent, scores, wants_simpler, wants_detail,
                        is_followup, bool(set(tokens) & PERSONAL), small, corrected)


# ----------------------------------------------------------------------------------------------
# Follow-up memory (temporary, lives inside one private chat session only)
# ----------------------------------------------------------------------------------------------
PHASE_FROM_CONTEXT = {"SETUP": "setup", "ROLE_ASSIGNMENT": "role assignment", "NIGHT": "night", "DISCUSSION": "discussion",
                      "VOTING": "voting", "ELIMINATION": "elimination"}


def resolve_followup(analysis, memory, ctx_role=None, ctx_phase=None):
    """Return (entities, notes). Entities from the previous turn are inherited when the new
    message depends on them ("it", "that", "when can I use it", "explain more simply"), and the
    asking player's OWN role (from the verified turn context) fills in "my role / what do I do".
    """
    entities = list(analysis.entities)
    have_role = any(e.type == "ROLE" for e in entities)
    have_phase = any(e.type == "PHASE" for e in entities)
    notes = []
    if analysis.is_followup and memory:
        if not have_role:
            for r in memory.get("roles", []):
                entities.append(Entity("ROLE", r, "(from previous question)"))
            if memory.get("roles"):
                notes.append("role inherited from previous question")
        if not have_phase and not any(e.type in ("BUTTON", "MECHANIC") for e in entities):
            for p in memory.get("phases", []):
                entities.append(Entity("PHASE", p, "(from previous question)"))
        if not any(e.type == "ACTION" for e in entities):
            for a in memory.get("actions", []):
                entities.append(Entity("ACTION", a, "(from previous question)"))
    have_role = any(e.type == "ROLE" for e in entities)
    if analysis.intent == "situation_guidance" and ctx_phase in PHASE_FROM_CONTEXT \
            and not any(e.type == "PHASE" for e in entities):
        entities.append(Entity("PHASE", PHASE_FROM_CONTEXT[ctx_phase], "(the current game phase)"))
        notes.append("phase from verified context")
    if ctx_role and not have_role and analysis.intent in ("situation_guidance", "role_explanation", "night_guidance") \
            and (analysis.is_personal or analysis.intent == "situation_guidance"):
        entities.append(Entity("ROLE", ctx_role, "(your own role, verified by the game)"))
        notes.append("own role from verified context")
    return entities, notes


def update_memory(memory, entities, chunk_ids, intent):
    """Remember what the last answer was about, so follow-ups can refer to it."""
    roles = [e.name for e in entities if e.type == "ROLE"]
    phases = [e.name for e in entities if e.type == "PHASE"]
    actions = [e.name for e in entities if e.type == "ACTION"]
    if roles or phases or actions or chunk_ids:
        memory["roles"] = roles or memory.get("roles", [])
        memory["phases"] = phases or memory.get("phases", [])
        memory["actions"] = actions or memory.get("actions", [])
    memory["chunks"] = list(chunk_ids) or memory.get("chunks", [])
    memory["intent"] = intent
    return memory
