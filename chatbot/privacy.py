"""Privacy and security boundary of the AI Companion.

The language model is NOT the security barrier. The rules enforced here, in plain Python and
before any model is called, are:

1. WHO is asking is decided by the game engine, never by the browser. In a pass-the-device game
   the "current player" is whoever's turn it is, and only after the game has recorded that the
   device was handed over (role shown / "I'M READY" pressed).
2. The model only ever receives that one player's OWN role (and own-turn facts), and nothing
   about anybody else. Other players' roles, targets and votes are never put into a prompt, so
   they cannot be leaked by clever wording.
3. Questions that try to extract secrets (who is Mafia, who did the Doctor save, ...) or that
   try to override the rules (prompt injection) are caught here and answered without the model.
4. Every reply is checked once more for player names appearing next to role words.
5. Chat sessions are bound to a "turn key". If the turn changes (another player, another phase)
   the session is automatically invalid, so one player's chat can never continue for the next.
"""
import re
from dataclasses import dataclass, field

from shared.nlp import expand_contractions

ROLE_RE = (r"(?:mafia|mafias|mob|mobster|mobsters|killer|killers|murderer|murderers|assassin|detective|"
           r"detectives|investigator|doctor|doctors|medic|healer|villager|villagers|civilian|civilians|"
           r"innocent|innocents|traitor|culprit|wolf|wolves|werewolf|werewolves|seer|bad guys?)")
ROLE_WORDS = frozenset("""mafia mafias mob mobster mobsters killer killers murderer murderers assassin detective
detectives investigator doctor doctors medic healer villager villagers civilian civilians innocent innocents
traitor culprit wolf wolves werewolf werewolves seer""".split())

_SECRET_PATTERNS = [
    ("role_identity", rf"\bwho\s+(?:is|are|was|were)\s+(?:the\s+|a\s+|an\s+|our\s+|my\s+)?(?:real\s+|actual\s+|secret\s+|hidden\s+)?{ROLE_RE}\b"),
    ("role_identity", r"\bwho\b(?:\s+\w+){0,3}\s+(?:is|are)\s+(?:the\s+)?(?:really|secretly|actually)\b"),
    # hypothetical / "just guess" framings of the same secret question
    ("role_identity", rf"\b(?:suppose|imagine|hypothetically|pretend|if\s+you\s+(?:knew|could\s+see|were\s+allowed|had\s+to\s+guess)|just\s+guess|best\s+guess|take\s+a\s+guess|purely\s+theoretical)\b.*\b(?:who|which)\b.*\b{ROLE_RE}\b"),
    ("role_identity", rf"\bwhich\s+(?:player|person|one|of\s+(?:us|them|these|the\s+players)|name|character)\b.*\b{ROLE_RE}\b"),
    ("role_identity", rf"\b(?:tell|show|reveal|give|name|list|expose|identify|disclose|leak|spill)\b(?:\s+\w+){{0,3}}?\s+(?:me\s+)?(?:who|which)\b.*\b{ROLE_RE}\b"),
    ("role_identity", rf"\b(?:reveal|expose|disclose|leak|spill|identify|name|list)\s+(?:the\s+|all\s+(?:the\s+)?|every\s+)?{ROLE_RE}\b(?!\s+(?:role|roles|rule|rules|team|goal|objective|win|wins|ability|abilities|power|powers|do|does|work|works|mechanic|mechanics|action|actions|night|strategy|tips?|job))"),
    ("role_identity", r"\b(?:everyone|everybody|each\s+player|all\s+(?:the\s+)?players?|every\s+player)\b.{0,12}\b(?:role|roles|identity|identities)\b"),
    ("role_identity", r"\b(?:roles?|identit(?:y|ies))\s+of\s+(?:everyone|everybody|all|each|the\s+players|other\s+players)\b"),
    # indirect probing: position in the list, letters of the name, simple attributes of a hidden player
    ("role_identity", rf"\b(?:is|are|was)\s+(?:the\s+|a\s+|our\s+)?{ROLE_RE}\s+(?:in|among|on|at|within|inside|one\s+of)\b.*\b(?:list|half|row|group|first|second|third|last|top|bottom|left|right|middle|seat|position|order|names?|alphabet)\b"),
    ("role_identity", rf"\b{ROLE_RE}(?:'s)?\s+names?\s+(?:start|starts|begin|begins|end|ends|contain|contains|has|have|is|are|rhymes?)\b"),
    ("role_identity", rf"\b(?:does|do|is|are)\s+(?:the\s+)?{ROLE_RE}(?:'s)?\s+names?\b"),
    ("role_identity", rf"\bhow\s+many\s+letters\b.*\b{ROLE_RE}\b|\b{ROLE_RE}\b.*\bhow\s+many\s+letters\b"),
    ("role_identity", rf"\b(?:first|second|third|last|1st|2nd|3rd)\s+letter\b.*\b{ROLE_RE}\b|\b{ROLE_RE}\b.*\b(?:first|second|third|last|1st|2nd|3rd)\s+letter\b"),
    ("role_identity", rf"\bis\s+(?:the\s+|a\s+|our\s+)?{ROLE_RE}\s+(?:a\s+|an\s+)?(?:male|female|man|woman|boy|girl|older|younger|tall|short|boy|guy)\b"),
    ("role_identity", rf"\b(?:is|are)\s+(?:the\s+)?{ROLE_RE}\s+(?:in|among)\s+(?:the\s+)?(?:first|second|last|top|bottom)\b"),
    # Roman-Urdu / Urdu-script variants of the same questions ("mafia kaun hai?", "مافیا کون ہے؟").
    # Asking what a role IS ("doctor kaun hota hai") is a rules question and is not caught here.
    ("role_identity", rf"^(?!.*\b(?:hota|hoti|hote|karta|karti|karte|kaise|kyun|kyon|sakta|sakti|sakte|chahiye|karna|karun|bachata|bachati|bachaye|bachana|bachane)\b).*\b(?:kaun|kon|kis|kisko|kiska)\b.*\b{ROLE_RE}\b"),
    ("role_identity", rf"^(?!.*\b(?:hota|hoti|hote|karta|karti|karte|kaise|kyun|kyon|sakta|sakti|sakte|chahiye|karna|karun|bachata|bachati|bachaye|bachana|bachane)\b).*\b{ROLE_RE}\b.*\b(?:kaun|kon|kis|kisko|kiska)\b"),
    ("role_identity", rf"\b(?:batao|bata\s+do|bataiye|dikhao|dikha\s+do|bolo)\b.*\b{ROLE_RE}\b.*\b(?:kaun|kon|naam|name)\b"),
    ("role_identity", r"(?:کون|کس|کسے).{0,40}(?:مافیا|ڈاکٹر|جاسوس|ڈیٹیکٹو|ڈیٹیکٹیو|قاتل|ولن)|(?:مافیا|ڈاکٹر|جاسوس|ڈیٹیکٹو|ڈیٹیکٹیو|قاتل).{0,40}(?:کون|کس|کسے)"),
    ("night_secret", rf"\bwho\s+(?:did|does|do|will|would|has|have|had)\s+(?:the\s+)?{ROLE_RE}\b.*\b(?:kill|killed|target|targeted|pick|picked|choose|chose|chosen|select|selected|save|saved|protect|protected|investigate|investigated|check|checked|vote|voted)"),
    ("night_secret", r"\bwho\s+(?:was|were|got|is|gets|will\s+be)\s+(?:targeted|killed|saved|protected|investigated|picked|chosen|selected|shortlisted|on\s+the\s+shortlist)\b"),
    ("night_secret", r"\b(?:mafia|killers?)\s+(?:target|targets|victim|victims|choice|choices|pick|picks|shortlist)\b.*\b(?:last\s+night|tonight|this\s+night|who|which|what\s+is|what\s+was)\b"),
    ("night_secret", r"\b(?:who|which|what)\b.*\b(?:last\s+night|tonight)\b.*\b(?:mafia|doctor|detective)\b"),
    ("investigation_result", r"\b(?:what|which)\s+(?:was|is|were)\s+(?:the\s+)?(?:detective|investigation|private)\s*(?:result|results|finding|findings|outcome)"),
    ("investigation_result", r"\b(?:detective|investigation)\s+(?:result|results|finding|findings|outcome)\b.*\b(?:who|which|was|is)\b"),
    ("partners", r"\bwho\s+(?:is|are)\s+(?:my|the)\s+(?:mafia\s+)?(?:partner|partners|teammate|teammates|allies|ally)\b"),
    ("vote_secret", r"\bwho\s+(?:voted|votes|vote)\s+(?:for|against|on)\b"),
    ("vote_secret", r"\bhow\s+did\s+\w+(?:\s+\w+)?\s+vote\b"),
    ("other_session", r"\b(?:previous|last|other|earlier|prior|former|another)\s+(?:player|person|user|chat|conversation|session)'?s?\b.*\b(?:chat|chats|message|messages|conversation|asked|said|typed|question|questions|role)\b"),
    ("other_session", r"\bwhat\s+did\s+(?:the\s+)?(?:last|previous|other|earlier|another)\s+(?:player|person|user)\s+(?:ask|say|type|write)"),
    ("other_session", r"\b(?:repeat|show|print|read\s+back|summari[sz]e)\s+(?:everything|all|the\s+whole|your\s+whole|the\s+entire)\s+(?:above|before|earlier|so\s+far|history|conversation)\b"),
    ("injection", r"\b(?:ignore|disregard|forget|override|bypass|skip)\s+(?:all\s+|any\s+|the\s+|your\s+|these\s+|those\s+|every\s+)?(?:previous|prior|above|earlier|former|system|safety|privacy|security)?\s*(?:instructions?|rules?|prompts?|directions?|guidelines?|restrictions?|filters?|limits?|policy|policies)\b"),
    ("injection", r"\b(?:system|developer|hidden|secret|internal)\s+(?:prompt|message|instructions?)\b"),
    ("injection", r"\b(?:reveal|show|print|display|repeat|leak)\s+(?:me\s+)?(?:your|the)\s+(?:prompt|instructions?|rules\s+you\s+were\s+given|configuration|context)\b"),
    ("injection", r"\b(?:jailbreak|dan\s+mode|developer\s+mode|debug\s+mode|god\s+mode|admin\s+mode|sudo)\b"),
    ("injection", r"\b(?:you\s+are\s+now|from\s+now\s+on\s+you|pretend\s+(?:to\s+be|you\s+are|that\s+you)|act\s+as\s+(?:if|though|the\s+game\s*master|a\s+hacker|an?\s+(?:admin|developer|moderator))|role\s*-?\s*play\s+as)\b"),
    ("injection", r"\b(?:dump|print|show|output|reveal|leak)\s+(?:me\s+)?(?:the\s+)?(?:full\s+|entire\s+|whole\s+|raw\s+|hidden\s+|secret\s+|internal\s+)*(?:game\s+)?(?:state|memory|history|data|database|variables?|json)\b"),
    ("role_identity", rf"\b(?:hint|clue|letter|initial|syllable)s?\b.*\b(?:who|which|whose)\b.*\b{ROLE_RE}\b|\b{ROLE_RE}\b.*\b(?:hint|clue)\b.*\b(?:who|which|name|letter)\b"),
    ("role_identity", r"\bplayer\s*(?:id\s*)?#?\d+(?:'s)?\b.*\b(?:screen|role|private|secret)\b|\bmy\s+(?:player\s+)?id\b.*\b(?:screen|role|private|secret|show)\b"),
    ("role_identity", rf"\b{ROLE_RE}s?\b.*\b(?:name|list|identify)\s+(?:them|those|these|all\s+of\s+them)\b|\b(?:name|list|identify)\s+(?:them|those|these)\b.*\b{ROLE_RE}"),
    ("investigation_result", r"\bwhat\s+(?:did|has)\s+(?:the\s+)?detective\s+(?:find|found|learn|learned|see|saw|discover|discovered)\b"),
    ("night_secret", rf"\bwhat\s+(?:did|has)\s+(?:the\s+)?{ROLE_RE}\s+(?:choose|chose|pick|picked|select|selected|decide|decided|target|targeted)\b"),
]
_SECRET_RES = [(cat, re.compile(p, re.IGNORECASE | re.DOTALL)) for cat, p in _SECRET_PATTERNS]

_SELF_ROLE = [
    re.compile(r"\b(?:what|which)\s+(?:is\s+)?my\s+(?:role|identity|character|team|side)\b", re.I),
    re.compile(r"\b(?:what|which)\s+(?:role|team|side|character)\s+(?:am\s+i|do\s+i\s+have|did\s+i\s+get)\b", re.I),
    re.compile(r"\bwhat\s+am\s+i\s*[?.!]*\s*$", re.I),
    re.compile(rf"\bam\s+i\s+(?:the\s+|a\s+|an\s+)?{ROLE_RE}\b", re.I),
    re.compile(r"\bremind\s+me\s+(?:of\s+)?(?:what\s+)?my\s+role\b", re.I),
    re.compile(r"\bwho\s+am\s+i\b|\bmain\s+kon\s+h(?:oon|un|u)\b|\bm[ea]\s+kon\s+h(?:oon|un|u)\b|\bmer[ae]\s+(?:role|kirdar|character)\b|\bmeri\s+(?:team|side)\b", re.I),
]

_NAME_ROLE_Q = re.compile(
    r"\b(?:is|are|was|were|be|hai|hain|tha|thi|ho|really|actually|secretly|seems?|think|believe|sure|trust|role|identity|team|side|alignment|claims?|claimed|says?|said)\b", re.I)


def normalize_for_matching(text):
    return re.sub(r"\s+", " ", expand_contractions(text)).strip()


def names_in_text(text, names):
    """Players whose names appear in `text` (case-insensitive, whole-word)."""
    found = []
    for name in names:
        if len(name) < 2 or name.lower() in ROLE_WORDS:
            continue
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", text, re.IGNORECASE):
            found.append(name)
    return found


def is_self_role_question(text):
    t = normalize_for_matching(text)
    return any(p.search(t) for p in _SELF_ROLE)


_PUBLIC_RULE_Q = re.compile(r"^(?:does|do|is|will|can|would|what\s+does|how\s+does)\s+(?:the\s+)?(?:morning\s+report|report|announcement|elimination\s+screen|result\s+screen|game[- ]over\s+screen|screen)\b", re.I)


def detect_secret_request(text, player_names=()):
    """Return a category string if `text` tries to extract hidden information or override the
    rules, else None. Deliberately conservative: a false alarm only produces a polite answer
    that explains the limit and still offers legitimate help."""
    t = normalize_for_matching(text)
    # "Does the morning report show who the Doctor protected?" asks how the SCREEN works, not who the Doctor protected.
    about_screen = _PUBLIC_RULE_Q.search(t) is not None
    for category, regex in _SECRET_RES:
        if about_screen and category in ("role_identity", "night_secret", "vote_secret"):
            continue
        if regex.search(t):
            return category
    named = names_in_text(t, player_names)
    if named:
        has_role_word = re.search(rf"\b{ROLE_RE}\b", t, re.IGNORECASE) is not None
        asks_identity = re.search(r"\b(?:role|identity|team|side|alignment|class|character)\b", t, re.I) is not None
        asks_vote = re.search(r"\b(?:voted|vote)\b", t, re.I) is not None and re.search(r"\bwho\b|\bhow\b", t, re.I)
        if (has_role_word and _NAME_ROLE_Q.search(t)) or asks_identity:
            return "role_identity"
        if asks_vote:
            return "vote_secret"
    return None


def guard_output(reply, player_names=(), public_names=()):
    """Last line of defence: refuse to return text that pairs a real player's name with a role.

    Names that are short (under 3 characters) or that look like role words themselves ("Wolf",
    "Seer") would cause constant false alarms with the loose proximity check above, so they get a
    stricter check instead: only "<name> is/was/= the <role>" style statements are refused."""
    public = {n.lower() for n in public_names}      # players whose fate/role the game itself announced
    for name in player_names:
        if not name or name.lower() in public:
            continue
        pattern = r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])"
        if len(name) < 3 or name.lower() in ROLE_WORDS:
            if re.search(pattern + rf"\s*(?:is|was|are|were|=|:|-|\u2014|\u2013|->)\s*(?:the\s+|a\s+|an\s+)?{ROLE_RE}\b",
                         reply, re.IGNORECASE):
                return False
            continue
        for m in re.finditer(pattern, reply, re.IGNORECASE):
            window = reply[max(0, m.start() - 45): m.end() + 45]
            if re.search(rf"\b{ROLE_RE}\b", window, re.IGNORECASE):
                return False
    return True


def clean_user_text(text, max_chars):
    """Strip control characters and collapse whitespace. Returns None for empty input."""
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars] if text else None


# ----------------------------------------------------------------------------------------------
# Who is asking? (derived from the game engine, read-only)
# ----------------------------------------------------------------------------------------------
def next_night_actor(gs):
    """The player whose night turn it is. Read-only: GameState.get_current_night_player() moves
    the turn counter as a side effect, which an observer must never do."""
    for i in range(gs.night_turn_index, len(gs.night_order_ids)):
        p = gs.get_player(gs.night_order_ids[i])
        if p is not None and p.alive:
            return p
    return None


def current_voter(gs):
    alive = gs.get_alive_players()
    return alive[gs.voting_turn_index] if 0 <= gs.voting_turn_index < len(alive) else None


@dataclass
class TurnTracker:
    """Remembers that the device really was handed to a player ("SHOW MY ROLE" or "I'M READY"
    was pressed). Without that, nobody is treated as the active private player."""
    role_revealed_for: object = None
    night_ready_for: object = None

    def observe(self, path, status, gs):
        if status != 200:
            return
        if path in ("/api/start", "/api/new-game"):
            self.role_revealed_for = self.night_ready_for = None
        elif path == "/api/role/show":
            p = gs.get_current_role_reveal_player()
            self.role_revealed_for = p.player_id if p else None
        elif path == "/api/night/ready":
            p = next_night_actor(gs)
            self.night_ready_for = (gs.night_number, p.player_id) if p else None


@dataclass(frozen=True)
class PrivateContext:
    phase: str                 # public label of the game phase
    available: bool            # False once the game is over
    screen: str                # public description of what is on screen
    role: object = None        # ONLY the asking player's own role, and only when permitted
    team: object = None
    facts: dict = field(default_factory=dict)   # own-turn facts only, never about other players
    turn_key: str = ""
    actor_id: object = None    # the verified asking player (only set together with `role`)
    voter_id: object = None    # the voter whose pass screen is showing (public); never carries a role


def build_context(gs, tracker):
    """The only game information the chatbot may see. No other player's name, role or action."""
    phase = gs.phase
    if gs.game_over or phase == "GAME_OVER":
        return PrivateContext("GAME_OVER", False, "The game has ended.", turn_key="OVER")
    if not gs.players:
        return PrivateContext("SETUP", True, "The setup screen.", turn_key="SETUP")

    if phase == "ROLE_ASSIGNMENT":
        p = gs.get_current_role_reveal_player()
        revealed = p is not None and tracker.role_revealed_for == p.player_id
        key = f"RA|{gs.role_reveal_index}|{int(revealed)}"
        if revealed:
            return PrivateContext(phase, True, "A player is looking at their private role card.",
                                  p.role.name, p.role.team, turn_key=key, actor_id=p.player_id)
        return PrivateContext(phase, True, "The role assignment screens.", turn_key=key)

    if phase == "NIGHT":
        actor = next_night_actor(gs)
        if actor is None:
            return PrivateContext(phase, True, "The night is ending.", turn_key=f"N|{gs.night_number}|end")
        ready = tracker.night_ready_for == (gs.night_number, actor.player_id)
        key = f"N|{gs.night_number}|{actor.player_id}|{int(ready)}"
        if not ready:
            return PrivateContext(phase, True, "The device is being passed to the next player for their night turn.",
                                  turn_key=key)
        facts = {}
        role = actor.role.name
        if role == "Doctor":
            facts["self_save_available"] = not gs.doctor_self_save_used
        elif role == "Mafia":
            alive_mafia = gs.get_alive_mafia()
            multiple = len(alive_mafia) > 1
            first = alive_mafia[0].player_id if alive_mafia else None
            facts["multiple_mafia_alive"] = multiple
            facts["is_first_mafia"] = actor.player_id == first
            facts["shortlist_already_saved"] = bool(gs.mafia_shortlist_ids)
            if not multiple:
                facts["stage"] = "choose_victim"
            elif actor.player_id == first and not gs.mafia_shortlist_ids:
                facts["stage"] = "build_shortlist"
            else:
                facts["stage"] = "choose_from_shortlist"
        return PrivateContext(phase, True, "A player is taking their private night turn.", role, actor.role.team,
                              facts, key, actor_id=actor.player_id)

    if phase == "VOTING":
        voter = current_voter(gs)
        vid = voter.player_id if voter else "end"
        return PrivateContext(phase, True, "The private voting round.", turn_key=f"V|{gs.day_number}|{vid}",
                              voter_id=voter.player_id if voter else None)

    if phase == "ELIMINATION":
        return PrivateContext(phase, True, "The elimination screen.", turn_key=f"E|{gs.day_number}")

    # DISCUSSION (covers the morning report and the discussion timer)
    return PrivateContext(phase, True, "The morning report or the daytime discussion.", turn_key=f"D|{gs.day_number}")
