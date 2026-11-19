"""Advice and dialogue handling that works ONLY from an `Evidence` object (see evidence.py).

This module imports no game state. It cannot look at hidden roles, so it cannot use them, even by
accident. A recommendation is produced from the asker's authorized evidence; when that evidence does
not favour any option the module says so and offers a clearly labelled neutral pick instead of
pretending to have a reason.
"""
import hashlib
import re
from dataclasses import dataclass, field

# ----------------------------------------------------------------------------------------------
# What is the user asking for?
# ----------------------------------------------------------------------------------------------
_PICK = r"(?:should|do|can|could|shall|would|must)\s+(?:i|we)"
RECO_PATTERNS = [
    ("kill", re.compile(rf"\b(?:who|whom|which\s+(?:player|person|one))\b.*\b{_PICK}\s+(?:target|kill|attack|murder|shoot|take\s+out|pick\s+as\s+(?:a\s+)?(?:target|victim))\b|"
                        r"\b(?:who|whom)\s+(?:to|is\s+the\s+best\s+to)\s+(?:target|kill)\b|\b(?:best|good)\s+(?:target|victim)\b", re.I)),
    ("protect", re.compile(rf"\b(?:who|whom|which\s+(?:player|person|one))\b.*\b{_PICK}\s+(?:protect|save|heal|guard|defend)\b|"
                           r"\b(?:who|whom)\s+to\s+(?:protect|save|heal)\b", re.I)),
    ("investigate", re.compile(rf"\b(?:who|whom|which\s+(?:player|person|one))\b.*\b{_PICK}\s+(?:investigate|check|inspect|search|look\s+into|examine|question)\b|"
                               r"\b(?:who|whom)\s+to\s+(?:investigate|check|inspect)\b", re.I)),
    ("shortlist", re.compile(rf"\b(?:who|whom|which\s+(?:players?|persons?))\b.*\b{_PICK}\s+(?:shortlist|put\s+on\s+the\s+shortlist)\b", re.I)),
    ("vote", re.compile(rf"\b(?:who|whom|which\s+(?:player|person|one))\b.*\b{_PICK}\s+(?:vote(?:\s+for|\s+out|\s+against)?|eliminate|lynch|accuse|oust)\b|"
                        r"\b(?:who|whom)\s+to\s+(?:vote|eliminate)\b", re.I)),
    ("pick", re.compile(rf"\b(?:who|whom|which\s+(?:player|person|one))\b.*\b{_PICK}\s+(?:pick|choose|select|go\s+for|go\s+with)\b|"
                        r"\bwhat\s+should\s+i\s+do\s+(?:tonight|this\s+(?:night|turn))\b", re.I)),
]
SUSPECT = re.compile(r"\b(?:who|which\s+(?:player|person|one))\b.*\b(?:seems?|looks?|is|are|appears?|feels?|acts?)\s+(?:the\s+most\s+|really\s+|a\s+bit\s+|kind\s+of\s+)?"
                     r"(?:suspicious|suspect|sus|shady|guilty|lying|fishy|untrustworthy|evil)\b|"
                     r"\bwho\s+(?:can|should|do)\s+(?:i|we)\s+(?:trust|suspect|doubt|distrust|blame)\b|\bwho\s+to\s+(?:trust|suspect|blame)\b", re.I)
WHY = re.compile(r"^\W*(?:and\s+)?(?:why|explain\s+(?:why|that|your\s+(?:answer|reasoning|choice|pick))|how\s+come|what(?:'s|\s+is)\s+(?:your|the)\s+(?:reason|reasoning|logic)|"
                 r"why\s+did\s+you\s+(?:recommend|say|suggest|pick|choose)|what\s+evidence|how\s+do\s+you\s+know)\b", re.I)
SHORTER = re.compile(r"\b(?:make\s+it\s+(?:shorter|brief|short|concise)|shorter|shorten(?:\s+it)?|too\s+long|more\s+(?:briefly|concise)|in\s+(?:one|1|a\s+few)\s+(?:sentence|words?)|"
                     r"tl;?\s*dr|just\s+the\s+(?:answer|short\s+version)|keep\s+it\s+short|briefly)\b", re.I)
CORRECTION = re.compile(r"(?:that(?:'s|\s+is|\s+was)?\s+not\s+what\s+i\s+(?:asked|meant|wanted)|not\s+what\s+i\s+(?:asked|meant|wanted)|you\s+(?:didn'?t|did\s+not|don'?t|do\s+not)\s+(?:answer|understand|get)|"
                        r"you\s+misunderstood|you\s+(?:got|have)\s+it\s+wrong|that(?:'s|\s+is)\s+(?:wrong|incorrect|not\s+right|not\s+helpful|useless)|wrong\s+answer|you(?:'re|\s+are)\s+(?:wrong|mistaken|incorrect)|that(?:'s|\s+is)\s+not\s+true|"
                        r"no,?\s+i\s+(?:asked|meant|said)|i\s+(?:asked|meant)\s+(?:about|for|why|how|what|who)|answer\s+my\s+question|try\s+again|that\s+doesn'?t\s+help|not\s+helpful)", re.I)
ANOTHER = re.compile(r"\b(?:another|someone\s+else|different|other)\s+(?:one|option|player|person|choice|pick|answer|suggestion)\b|\bpick\s+(?:another|someone\s+else)\b|\bgive\s+me\s+another\b", re.I)
LEGAL_Q = re.compile(r"\b(?:who|which\s+players?)\s+(?:can|may)\s+i\s+(?:target|kill|protect|save|investigate|check|vote\s+for|vote\s+out|eliminate|choose|pick)\b|"
                     r"\b(?:what|which)\s+(?:are|is)\s+my\s+(?:options|choices|legal\s+(?:options|choices|targets))\b|\bwho\s+(?:is|are)\s+(?:still\s+)?(?:alive|left|in\s+the\s+game|out)\b", re.I)

VERB_ACTION = {"kill": "kill", "protect": "protect", "investigate": "investigate", "shortlist": "shortlist", "vote": "vote"}
ROLE_FOR = {"kill": "Mafia", "shortlist": "Mafia", "protect": "Doctor", "investigate": "Detective"}
VERB_WORD = {"kill": "target", "shortlist": "put on the shortlist", "protect": "protect", "investigate": "investigate", "vote": "vote for"}

CONVENTION = {
    "kill": "General Mafia-game convention (not a CAMORRA rule): Mafia teams usually weigh who looks most dangerous to them, but CAMORRA gives you no hidden information about that.",
    "shortlist": "General Mafia-game convention (not a CAMORRA rule): a shortlist is usually a mix of players, so the Mafia are not predictable.",
    "protect": "General Mafia-game convention (not a CAMORRA rule): Doctors often protect someone the Mafia might want removed, but nothing you are allowed to see shows who that is.",
    "investigate": "General Mafia-game convention (not a CAMORRA rule): Detectives usually investigate whoever the public discussion makes them doubt.",
    "vote": "General Mafia-game convention (not a CAMORRA rule): votes are usually based on what players said and did in the discussion.",
}


def classify(text):
    """Return one of: ('reco', action) | 'suspect' | 'why' | 'shorter' | 'correction' | 'another' | 'legal' | None."""
    t = re.sub(r"\s+", " ", text).strip()
    if is_general_task(t):
        return None
    if CORRECTION.search(t) and len(t.split()) <= 30:
        return "correction"
    if NEXT_STEP.match(t):
        return "next_step"
    if WHY_ELIMINATED.search(t):
        return "situation"
    if is_transform(t):
        return "transform"
    if SHORTER.search(t) and len(t.split()) <= 10:
        return "shorter"
    if WHY.match(t) and len(t.split()) <= 9:
        return "why"
    if ANOTHER.search(t) and len(t.split()) <= 12:
        return "another"
    if LEGAL_Q.search(t):
        return "legal"
    for action, rx in RECO_PATTERNS:
        if rx.search(t):
            return ("reco", action)
    if SUSPECT.search(t):
        return "suspect"
    return None


# ----------------------------------------------------------------------------------------------
# Recommendations
# ----------------------------------------------------------------------------------------------
@dataclass
class Advice:
    reply: str
    kind: str = "advice"                 # advice | clarification
    action: str = "none"
    options: tuple = ()
    choice: object = None                # a name, or None when nothing is recommended
    neutral: bool = False                # True: the choice is a labelled tie-break, not a deduction
    evidence_ids: tuple = ()             # which evidence items the answer is justified by
    why: str = ""                        # explanation text for "why?"
    extra: dict = field(default_factory=dict)


def _neutral_pick(evidence, action, options, skip=()):
    """A deterministic tie-break that depends only on public/turn information, never on hidden roles:
    the same question gets the same answer instead of a flip-flopping random one."""
    pool = [o for o in options if o not in skip] or list(options)
    digest = hashlib.sha256(f"{evidence.turn_key}|{action}|{len(skip)}".encode()).hexdigest()
    return pool[int(digest, 16) % len(pool)]


def _ids(evidence, *needles):
    out = []
    for item_id, desc in evidence.items:
        if any(n in desc for n in needles):
            out.append(item_id)
    return tuple(out)


def recommend(evidence, action, skip=()):
    asker_action = evidence.action
    word = VERB_WORD.get(action, "choose")

    if action == "pick":
        action = {"shortlist": "shortlist"}.get(asker_action, asker_action)
        word = VERB_WORD.get(action, "choose")
        if action == "none":
            return Advice("I don't have a pending decision for you right now. Your options show up on your own turn screen; "
                          "ask me again after you press I'M READY and I can tell you what you are allowed to choose.",
                          "clarification", evidence_ids=_ids(evidence, "Players still in"))

    needed_role = ROLE_FOR.get(action)
    if needed_role and evidence.role is None:
        return Advice("I can only advise on a night action during your own verified turn. Press I'M READY when you hold the "
                      "device and it is your turn, then ask again.", "clarification", action=action,
                      evidence_ids=_ids(evidence, "Players still in"))
    if needed_role and evidence.role != needed_role:
        mine = {"Mafia": "choose a victim", "Doctor": "protect someone", "Detective": "investigate someone",
                "Villager": "pick a harmless activity"}.get(evidence.role, "take your turn")
        return Advice(f"In CAMORRA that is not something your role does. As the {evidence.role} your night action is to {mine}. "
                      f"Do you want help with that?", "clarification", action=action,
                      evidence_ids=_ids(evidence, "own role"))
    if action == "vote":
        if evidence.action != "vote" or not evidence.options:
            return Advice("Voting happens after the discussion. When the voting screen shows your turn, ask me again and I can "
                          "go through what you are allowed to use.", "clarification", action="vote",
                          evidence_ids=_ids(evidence, "Players still in"))
    elif action != evidence.action and not (action == "kill" and evidence.action == "shortlist"):
        if evidence.action == "none":
            return Advice("It isn't your decision turn right now. Ask me again on your night turn after I'M READY.",
                          "clarification", action=action, evidence_ids=_ids(evidence, "Players still in"))
    options = tuple(evidence.options)
    if not options:
        return Advice("There is nobody valid to choose from right now, so there is nothing to recommend.", "clarification",
                      action=action, evidence_ids=_ids(evidence, "Players still in"))

    choice = _neutral_pick(evidence, action, options, skip)
    used = _ids(evidence, "Legal", "must choose", "shortlist", "voting screen", "own role")
    used = used or _ids(evidence, "Players still in")
    noun = {"kill": "target", "protect": "player to protect", "investigate": "player to investigate",
            "vote": "player to vote for", "shortlist": "shortlist"}.get(action, "choice")
    if action == "shortlist":
        picks = list(dict.fromkeys([choice] + [o for o in options if o != choice][:2]))
        reply = (f"Nothing you're allowed to see favours anyone, so I can't recommend shortlist names on evidence. "
                 f"Legal choices: {', '.join(options)} (pick 2 to 4). If you just need a start: {', '.join(picks)} "
                 f"(a neutral tie-break, not a reason).")
        choice = ", ".join(picks)
    else:
        reply = (f"Nothing you're allowed to see favours any {noun}, so I can't recommend one on evidence. "
                 f"Legal options: {', '.join(options)}. If you just need a pick: {choice} (a neutral tie-break, not a reason).")
    why = (f"I used only {', '.join(used)}: your legal options and the public list of players. None of that separates the options, "
           f"so {choice} is a tie-break chosen without looking at anyone's hidden role. Your own reasons from the discussion "
           f"should outweigh it.")
    return Advice(reply.strip(), "advice", action=action, options=options, choice=choice, neutral=True,
                  evidence_ids=used, why=why, extra={"convention": CONVENTION.get(action, "")})


def suspicion(evidence):
    ids = _ids(evidence, "Players still in", "Public events", "already out")
    facts = list(evidence.public_events)
    if facts:
        known = " Public facts so far: " + " ".join(facts)
    else:
        known = " So far the game has announced nothing yet that points at anyone."
    reply = ("I can't honestly say who is suspicious: the game gives me no public evidence about who is Mafia, and I never use "
             "hidden roles." + known + " If you tell me what players said or did during the discussion (for example who "
             "changed their story, or who accused whom), I can help you weigh that. Whose behaviour are you unsure about?")
    why = ("I only had the public list of players and the events the game announced to everyone. They do not single anyone out, "
           "so naming a suspect would have been a guess presented as evidence.")
    return Advice(reply, "advice", action="suspect", evidence_ids=ids, why=why)


GAME_TERMS = re.compile(r"\b(?:camorra|mafia|doctor|detective|villager|civilians?|vote|voting|votes|roles?|buttons?|screens?|game|players?|night|"
                        r"discussion|elimination|eliminated|shortlist|companion|chat\s*bot)\b", re.I)
TASK_START = re.compile(r"^\W*(?:please\s+|can\s+you\s+|could\s+you\s+)?(?:write|draft|compose|translate|convert|debug|refactor|summari[sz]e|"
                        r"rewrite|proofread|generate|solve|calculate|compare|brainstorm|plan|teach\s+me|help\s+me\s+(?:write|with\s+my|learn|study|plan))\b", re.I)
TECH = re.compile(r"\b(?:python|javascript|typescript|java|c\+\+|html|css|sql|regex|traceback|exception|stack\s*trace|code|function|script|"
                  r"capital\s+of|essay|poem|email|e-mail|homework|recipe|weather|football|cricket)\b", re.I)


def is_general_task(text):
    """A request that is clearly not about CAMORRA itself (write/translate/code/compare...). Stops a stray word
    such as "morning" in "translate good morning" from pulling in an unrelated rulebook section."""
    if GAME_TERMS.search(text):
        return False
    return bool(TASK_START.search(text) or TECH.search(text))


def legal_options(evidence, text=""):
    if evidence.options:
        label = {"kill": "kill", "protect": "protect", "investigate": "investigate", "shortlist": "shortlist",
                 "vote": "vote for"}.get(evidence.action, "choose")
        reply = f"Players you can {label} right now: {', '.join(evidence.options)}."
        if evidence.action == "vote":
            reply += " The voting screen shows your exact list."
        return Advice(reply, "advice", action=evidence.action, options=evidence.options,
                      evidence_ids=_ids(evidence, "Legal", "voting screen", "shortlist", "Players still in"))
    lead = "Voting comes after the discussion, and the voting screen shows your exact list. " if re.search(r"\bvot", text, re.I) else ""
    return Advice(lead + "Players still in the game: " + (", ".join(evidence.alive) or "none")
                  + (". Out: " + ", ".join(evidence.out) if evidence.out else "") + ".", "advice",
                  evidence_ids=_ids(evidence, "Players still in", "already out"))


# ----------------------------------------------------------------------------------------------
# Public facts: names whose roles the game itself revealed
# ----------------------------------------------------------------------------------------------
ASKS_ROLE = re.compile(r"\b(?:role|was|were|is|are|mafia|doctor|detective|villager|civilian|innocent|town|team|side|what|who)\b", re.I)


def public_fact_answer(evidence, text):
    """If the question names players whose fate the game made public, answer from that public record."""
    mentioned = [n for n in evidence.all_names()
                 if re.search(r"(?<![A-Za-z0-9])" + re.escape(n) + r"(?![A-Za-z0-9])", text, re.I)]
    known = [n for n in mentioned if n in evidence.revealed or n in evidence.out]
    if not known or len(known) != len(mentioned) or not ASKS_ROLE.search(text):
        return None
    parts = []
    for n in known:
        if n in evidence.revealed:
            parts.append(f"{n} is out of the game and the game revealed their role: {evidence.revealed[n]}.")
        else:
            parts.append(f"{n} was eliminated during the night, and the game does not reveal the roles of night victims.")
    return Advice(" ".join(parts), "advice", evidence_ids=_ids(evidence, "Public events", "already out"))


# ----------------------------------------------------------------------------------------------
# Shortening and corrections
# ----------------------------------------------------------------------------------------------
def _sentences(text):
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"(])", re.sub(r"\s+", " ", text).strip())
    return [p for p in parts if p]


def shorten(previous, limit=1):
    """Shorten the previous answer itself (not a new topic)."""
    if not previous:
        return None
    previous = re.sub(r"^Direct answer:\s*", "", previous)
    sents = [s for s in _sentences(previous) if not s.startswith("(")]
    if not sents:
        return None
    short = " ".join(sents[:limit])
    if short.strip() == previous.strip():
        short = sents[0]
        if len(short) > 160:
            short = short[:157].rsplit(" ", 1)[0] + "..."
    return short


# ----------------------------------------------------------------------------------------------
# Next step, comparisons, style/length modifiers
# ----------------------------------------------------------------------------------------------
NEXT_STEP = re.compile(r"^\W*(?:(?:ok(?:ay)?|so|and|hey)\W+)*(?:what\s+(?:should|do|can|shall|must)\s+i\s+do(?:\s+(?:next|now|here|then|this\s+turn|right\s+now|in\s+(?:my|the)\s+(?:current\s+)?turn|in\s+this\s+turn))*|"
                       r"what(?:'s|\s+is)\s+(?:my|the)\s+next\s+(?:step|move|action)(?:\s+(?:in|for)\s+(?:my\s+)?(?:current\s+)?turn)?|what\s+now|what\s+next|"
                       r"(?:what\s+)?(?:is\s+)?my\s+(?:current\s+)?turn\W*what\s+(?:next|now)|how\s+do\s+i\s+(?:continue|proceed)|what\s+happens\s+(?:now|next)\s+for\s+me)\W*$", re.I)
COMPARE = re.compile(r"\b(?:difference|differences|differ|differs|compare|comparison|versus|vs\.?|different\s+from|distinguish|how\s+is\s+\w+\s+different)\b", re.I)
ONE_SENTENCE = re.compile(r"\b(?:in\s+(?:one|1|a\s+single)\s+sentence|one[- ]sentence|single\s+sentence|in\s+one\s+line)\b", re.I)
EASIER = re.compile(r"\b(?:easier|simpler|simple\s+words|simply|more\s+simply|beginner|eli5|like\s+i'?m\s+(?:five|5)|i\s+(?:still\s+)?(?:don'?t|do\s+not)\s+understand|confusing|dumb\s+it\s+down)\b", re.I)
EXAMPLE = re.compile(r"\b(?:give\s+(?:me\s+)?(?:an?\s+)?example|for\s+example|an\s+example|show\s+(?:me\s+)?an?\s+example|example\s+please)\b", re.I)
AGAIN = re.compile(r"\b(?:explain\s+(?:it\s+|that\s+|this\s+)?again|say\s+(?:it\s+|that\s+)?again|repeat(?:\s+(?:it|that))?|once\s+more|re-?explain|go\s+over\s+(?:it|that)\s+again)\b", re.I)
LANGUAGE = re.compile(r"\b(?:in|into|to)\s+(roman\s+urdu|urdu|hindi|arabic|spanish|french|german|turkish|chinese|punjabi|pashto|sindhi|bengali|english)\b", re.I)
FOLLOWUP_START = re.compile(r"^\W*(?:and\s+|also\s+|so\s+|then\s+|ok\w*\W+)?(?:it|that|this|those|them|he|she|they|why|how\s+come|what\s+about|and\s+if|explain|make|give|say|can\s+you\s+(?:explain|make|say|give|repeat|shorten)|could\s+you|please\s+(?:explain|make|give|repeat)|shorter|longer|simpler|easier|again|more)\b", re.I)


def modifiers(text):
    """What the user wants done to the previous answer (or to the answer being given)."""
    t = text or ""
    lang = LANGUAGE.search(t)
    return {
        "one_sentence": bool(ONE_SENTENCE.search(t)),
        "shorter": bool(SHORTER.search(t)),
        "easier": bool(EASIER.search(t)),
        "example": bool(EXAMPLE.search(t)),
        "again": bool(AGAIN.search(t)),
        "language": re.sub(r"\s+", " ", lang.group(1)).title() if lang else None,
    }


_FILLER = frozenset("""explain it that this again please can you could would make give me an a the example examples in into to one 1 single
sentence line shorter short shorten longer easier simpler simple simply words word roman urdu hindi arabic spanish french german
turkish chinese punjabi pashto sindhi bengali english say repeat once more briefly brief concise tldr tl dr too long i still don't
dont do not understand confusing is so and also then ok okay for with version answer your previous last explanation reply response
using use like eli5 five beginner dumb down go over re-explain reexplain what mean means meaning""".split())


def is_transform(text):
    """A short follow-up that only asks to rework the previous answer (shorter, simpler, an example, another
    language, one sentence...). A message that also names a topic ("Explain binary search ... with a Python
    example") is a new question, not a follow-up."""
    t = re.sub(r"\s+", " ", text).strip()
    if len(t.split()) > 14:
        return False
    m = modifiers(t)
    if not any(m.values()):
        return False
    left = [w for w in re.findall(r"[a-z0-9']+", t.lower()) if w not in _FILLER]
    return not left


ROLE_TAGLINE = {
    "Mafia": "secretly chooses one player to kill each night",
    "Detective": "investigates one player each night to learn privately whether they are Mafia",
    "Doctor": "protects one player each night so a Mafia kill on that player fails",
    "Villager": "has no special power and only takes a harmless night activity",
}
ROLE_TEAM = {"Mafia": "Mafia", "Detective": "Town", "Doctor": "Town", "Villager": "Town"}


def compare_roles(role_names, simples=None):
    """Compare two (or more) roles using only the rulebook-verified one-line descriptions above."""
    roles = [r for r in dict.fromkeys(role_names) if r in ROLE_TAGLINE][:3]
    if len(roles) < 2:
        return None
    parts = [f"the {r} {ROLE_TAGLINE[r]}" for r in roles]
    first = "The " + parts[0][4:] + ", while " + (", while ".join(parts[1:])) + "."
    teams = {ROLE_TEAM[r] for r in roles}
    team = ("Both are on the Town team." if teams == {"Town"} and len(roles) == 2
            else f"They are on different teams ({', '.join(f'{r}: {ROLE_TEAM[r]}' for r in roles)}).") if len(teams) <= 2 else ""
    extra = ""
    if "Doctor" in roles:
        extra = " The Doctor may protect themselves only once per game."
    if "Detective" in roles:
        extra += " A Mafia member the Detective finds is eliminated at the end of that night."
    return Advice(first, "advice", extra={"summary": first, "detail": (team + extra).strip()})


def next_step(evidence):
    ids = _ids(evidence, "Players still in", "own role", "Legal", "voting screen", "shortlist")
    opts = ", ".join(evidence.options)
    ph, role, st = evidence.phase, evidence.role, evidence.facts.get("stage")
    if ph == "SETUP":
        text = "Choose how many players and Mafia, type a unique name for every player, then press START THE GAME."
    elif ph == "ROLE_ASSIGNMENT":
        text = ("That is your private role card: remember it, then press HIDE MY ROLE and pass the device on." if role
                else "Pass the device to the player named on screen; they press SHOW MY ROLE in private.")
    elif ph == "NIGHT":
        if role is None:
            return Advice("The device is on the 'pass the device' screen. When the named player holds it they press I'M READY; "
                          "ask me again then and I'll tell you exactly what to do.", "clarification", evidence_ids=ids)
        if role == "Mafia":
            if st == "build_shortlist":
                text = f"You are the first living Mafia: pick 2 to 4 players for the shared shortlist ({opts}), then press CONTINUE."
            elif st == "choose_from_shortlist":
                text = f"Pick one target from the shared shortlist ({opts}), then press CONTINUE."
            else:
                text = f"Pick one living non-Mafia player as tonight's victim ({opts}), then press CONTINUE."
        elif role == "Doctor":
            own = "Your one self-save is still available." if evidence.facts.get("self_save_available") else "Your self-save is already used, so protect someone else."
            text = f"Choose one player to protect ({opts}). {own} Then press CONTINUE."
        elif role == "Detective":
            text = (f"Choose one player to investigate ({opts}). You will then see a private MAFIA or INNOCENT card; press "
                    f"HIDE RESULT & CONTINUE and pass the device on.")
        else:
            text = "Pick any one of the activities on your screen (it has no effect on the game), then press CONTINUE and pass the device on."
    elif ph == "VOTING":
        text = (f"Choose the player you want to eliminate ({opts}); you can't vote for yourself. Then press CONTINUE and pass the device on."
                if opts else "Press I'M READY when the named voter holds the device, then choose one player to eliminate.")
    elif ph == "ELIMINATION":
        text = "Press BEGIN NEXT NIGHT (or VIEW GAME RESULT if the game has ended)."
    else:
        text = ("Discuss with the group; START VOTING moves on early, and voting starts by itself when the timer reaches zero. "
                "If the morning report is still showing, press BEGIN DISCUSSION first.")
    return Advice(text, "advice", evidence_ids=ids, extra={"summary": text})


def one_sentence(text, preferred=None):
    """Reduce an answer to ONE sentence that keeps its meaning: use the stored summary when there is one, else the
    most informative early sentence (never a bare 'No.')."""
    if preferred:
        return _first_sentence(preferred)
    for sent in _sentences(re.sub(r"^Direct answer:\s*", "", text or "")):
        if (len(sent.split()) >= 5 and not sent.startswith("(")
                and not re.search(r"\bis\s+on\s+the\s+(?:town|mafia)\s+team\b", sent, re.I)):     # "The Doctor is on the Town team." says nothing about what the role does
            return sent
    return _first_sentence(text or "")


def best_sentence_for(text, summary):
    """The sentence of `text` that best matches the stored summary of it, so a 'shorter' answer is a real sentence of the
    longer one and says what the topic is about (not a bare 'The Doctor is on the Town team.')."""
    if not summary:
        return None
    want = set(re.findall(r"[a-z]{3,}", summary.lower()))
    best, score = None, 0.0
    for sent in _sentences(text or ""):
        words = set(re.findall(r"[a-z]{3,}", sent.lower()))
        if not words or sent.startswith("(") or len(sent.split()) < 5:
            continue
        overlap = len(want & words) / max(1, len(want))
        if overlap > score:
            best, score = sent, overlap
    return best if score >= 0.5 and len(best) < 0.8 * len(text) else None


def _first_sentence(text):
    sents = _sentences(text or "")
    return sents[0] if sents else (text or "").strip()


PERSONAL_UNKNOWN = re.compile(r"\b(?:what(?:'s|\s+is)|who(?:'s|\s+is)|tell\s+me|do\s+you\s+know|where(?:'s|\s+is|\s+do\s+i)|when(?:'s|\s+is))\s+(?:my|our)\s+"
                              r"(?:\w+\s+)?(?:name|mother|father|mom|mum|dad|sister|brother|wife|husband|girlfriend|boyfriend|friend|teacher|boss|"
                              r"age|birthday|address|phone|number|password|email|salary|house|home|city|school|job|dog|cat)\b", re.I)


def unknown_personal(text):
    """Questions about the user's private life: the assistant has no such information and must not invent it."""
    if PERSONAL_UNKNOWN.search(text):
        return ("I don't have any personal information about you, so I can't tell you that. "
                "If you tell me in this chat, I can use it for as long as the chat lasts.")
    return None


# ----------------------------------------------------------------------------------------------
# Features CAMORRA does not have: say so instead of answering with a loosely related section
# ----------------------------------------------------------------------------------------------
UNSUPPORTED_TERMS = ("leaderboard", "leaderboards", "ranking", "rankings", "high score", "highscore", "scoreboard", "points system",
                     "achievements", "achievement", "badge", "badges", "login", "log in", "account", "accounts", "multiplayer online",
                     "play online", "online multiplayer", "lobby", "matchmaking", "in-app purchase", "premium", "subscription",
                     "auto kill", "auto-kill", "autokill", "undo", "replay", "save game", "load game", "godfather", "werewolf",
                     "bodyguard", "jester", "sheriff", "seer", "medic", "hunter", "witch", "cupid", "serial killer", "mason", "spy", "cop", "escort", "vigilante", "tracker role", "mayor", "executioner")


def unsupported_feature(text, kb_text):
    """The first feature word in the question that appears nowhere in the rulebook, or None."""
    t = " " + re.sub(r"[^a-z0-9' -]+", " ", text.lower()) + " "
    low = kb_text.lower()
    for term in UNSUPPORTED_TERMS:
        if re.search(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", t) and term not in low:
            return term
    return None


WHY_ELIMINATED = re.compile(r"\bwhy\b.*\b(?:was|were|did|is|got|gets?)\b.*\b(?:eliminated|killed|removed|voted\s+out|out\s+of\s+the\s+game|died|dead)\b|"
                            r"\bwho\s+(?:was|got)\s+(?:eliminated|voted\s+out|killed)\b|\bwhat\s+happened\s+(?:last\s+night|today|so\s+far)\b|"
                            r"\b(?:current|public)\s+(?:game\s+)?situation\b", re.I)


def public_situation(evidence):
    """Explain who is out and why, using only what the game announced to everyone."""
    ids = _ids(evidence, "Players still in", "already out", "Public events")
    events = [e for e in evidence.public_events]
    if not events and not evidence.out:
        text = ("Nobody has been eliminated yet. In CAMORRA a player leaves the game in one of three ways: the Mafia's night kill, "
                "the Detective finding a Mafia member, or the day vote. The morning report and the elimination screen say which. "
                f"Still in the game: {', '.join(evidence.alive)}.")
    else:
        text = " ".join(events) if events else ""
        if evidence.out:
            text += (" " if text else "") + f"Out of the game: {', '.join(evidence.out)}. Still in: {', '.join(evidence.alive)}."
        text += " That is everything the game has announced publicly; I can't see anything private."
    return Advice(text.strip(), "advice", evidence_ids=ids)
