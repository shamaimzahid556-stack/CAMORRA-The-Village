"""Offline answer composer: builds replies ONLY from verified rulebook sentences plus fixed,
rule-based templates. It is used when no language model is configured, and as the fallback when
the model service is unavailable. It cannot invent rules because it never writes free text about
the game: it selects and arranges sentences that already exist in game_knowledge/."""
import re

from shared.nlp import STOP_WORDS, normalize, tokenize

REFUSALS = {
    "role_identity": ("I can't tell you who has which role, and I can't confirm or deny a guess about any player. "
                      "Roles stay hidden until the game reveals them. What I can do is explain how each role works and "
                      "how the village can work out who is lying from what happens in the game."),
    "night_secret": ("Night choices (who the Mafia targeted, who the Doctor protected, who the Detective checked) are secret, "
                     "and I don't have access to them. The morning report screen shows whatever the game makes public. "
                     "I can explain how the night is resolved if that helps."),
    "investigation_result": ("A Detective's investigation result is private to the Detective, and I can't see or share it. "
                             "I can explain how the Detective's night action works."),
    "partners": ("I can't see anyone's partners. A Mafia player's partners are shown on their own role card, which only "
                 "that player should look at."),
    "vote_secret": ("Votes are private: the game doesn't show who voted for whom, and I can't see it either. "
                    "I can explain how votes are counted and what happens after voting."),
    "other_session": ("Each chat with me is private and starts completely fresh. I can't see anyone else's messages, "
                      "and mine disappear when the chat is closed."),
    "injection": ("I can't help with that, but I'm happy to help with CAMORRA's rules, roles, "
                  "phases and screens. What would you like to know?"),
}
OFF_TOPIC = "I'm not sure about that. Could you explain what you mean?"
OUT_OF_SCOPE = ("I'm the CAMORRA game expert, so I'll stick to the game: its rules, roles, phases, voting, strategy and what to do on "
                "your turn. I can't help with writing, translating, programming or general questions here. "
                "Is there something about CAMORRA I can explain?")
OUT_OF_SCOPE_ROMAN_URDU = ("Main CAMORRA game ka expert hoon, is liye sirf game ke baare mein madad kar sakta hoon: rules, roles, "
                           "night aur day phases, voting, strategy aur aapki current turn. Kya main CAMORRA ke baare mein kuch samjhaoon?")
PROBING_NOTE = ("I've now declined several questions that try to get at hidden information. Rewording them or asking "
                "hypothetically won't change my answer; I can only use what you are allowed to see.")
SAME_ANSWER = ("I don't have a different answer to that from the CAMORRA rules, and repeating myself wouldn't help. "
               "Tell me which part is wrong or missing, or ask it another way, and I'll try again.")
GREETING = "Hi! I'm the CAMORRA AI Companion. Ask me about the rules, the roles, the night and day phases, voting, or what a button does."
THANKS = "You're welcome! Ask me anything else about CAMORRA whenever you like."
ABOUT_BOT = ("I'm the CAMORRA AI Companion. I can explain the rules, each role in general, the night and day phases, voting, "
             "how to win and what each button does. I can't tell you anyone's secret role or choice, and this chat is private: "
             "it's cleared when you close it.")
NO_ANSWER = ("I can't confirm that from the CAMORRA rules I know, so I'd rather not guess. "
             "You could try asking about a specific role, phase or button. {hint}")
NO_SELF_ROLE = ("I can't see your role right now. When it's your turn to see it, your private role card shows it, "
                "and I can explain what each role does if you tell me which one you're curious about.")


def sentences(text):
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"(])", re.sub(r"\s+", " ", text).strip())
    return [p for p in parts if p]


def _overlap(sentence, query_lemmas, vocab):
    lem = set(normalize(tokenize(sentence), vocab)) - STOP_WORDS
    return len(lem & set(query_lemmas))


def pick_sentences(chunk, query_lemmas, vocab, limit=4, force_first=True):
    """Choose the sentences that best match the question, keeping the original order."""
    sents = sentences(chunk.text)
    if len(sents) <= limit:
        return sents
    ranked = sorted(range(len(sents)), key=lambda i: (-_overlap(sents[i], query_lemmas, vocab), i))
    if force_first:
        keep = sorted(ranked[: limit - 1] + ([0] if 0 not in ranked[: limit - 1] else []))
    else:
        keep = sorted(ranked[:limit])
    return [sents[i] for i in keep[:limit]]


def short_version(chunk, limit=2):
    return chunk.simple or " ".join(sentences(chunk.text)[:limit])


def personal_notes(ctx, analysis):
    """Extra, verified, own-turn guidance for the asking player (never about anyone else).
    Only added when the question is about the asker themselves, and never when they asked about a
    different role (a Detective asking about the Doctor gets no Detective notes)."""
    if not ctx or not ctx.role:
        return []
    asked_roles = {e.name for e in analysis.entities if e.type == "ROLE"}
    if asked_roles and ctx.role not in asked_roles:
        return []
    personal = analysis.is_personal or analysis.intent == "situation_guidance"
    if not personal or analysis.intent not in ("troubleshooting", "situation_guidance", "night_guidance",
                                               "role_explanation", "clarification"):
        return []
    notes = []
    if ctx.phase == "NIGHT":
        notes.append(f"You're the {ctx.role}, and this is your private night turn.")
        if ctx.role == "Doctor":
            notes.append("Your one self-save is still available." if ctx.facts.get("self_save_available")
                         else "Your one self-save has already been used, so you must protect someone else.")
        if ctx.role == "Detective":
            notes.append("You can't investigate yourself.")
        if ctx.role == "Mafia":
            stage = ctx.facts.get("stage")
            if stage == "build_shortlist":
                notes.append("You are the first living Mafia, so you build the shared shortlist first, then pick a target from it.")
            elif stage == "choose_from_shortlist":
                notes.append("The shortlist has been set, so choose one target from it.")
            elif stage == "choose_victim":
                notes.append("You're the only living Mafia, so you choose one living non-Mafia player directly.")
        if ctx.role == "Villager":
            notes.append("Your night choice has no effect on the game.")
    elif ctx.phase == "ROLE_ASSIGNMENT":
        notes.append(f"Your role is {ctx.role}, as shown on your role card.")
    return notes


def compose_offline(analysis, hits, ctx, memory, kb, vocab, wants_detail=False, opts=None):
    """Return (reply, used_chunk_ids)."""
    opts = opts or {}
    wants_detail = wants_detail or bool(opts.get("detail"))
    notes = personal_notes(ctx, analysis)
    if opts.get("concise"):
        notes = notes[:1]
    # confusion-aware: restate the previous topic in simpler words
    if analysis.wants_simpler and memory.get("chunks"):
        chunks = [kb.get(cid) for cid in memory["chunks"][:2] if kb.get(cid)]
        if chunks:
            body = " ".join(short_version(c) for c in chunks)
            return ("No problem, here is the same thing in simpler words. " + body +
                    " If a part is still unclear, tell me which part and I'll go through it step by step."), [c.id for c in chunks]
    if analysis.wants_simpler and not memory.get("chunks") and not hits:
        return ("Happy to explain more simply. Which part is confusing: a role, the night, the voting, or a button?"), []

    if not hits:
        return NO_ANSWER.format(hint=""), []
    main = hits[0].chunk
    used = [main.id]
    if wants_detail:
        parts = [main.text] + ([hits[1].chunk.text] if len(hits) > 1 and hits[1].score > 0.6 * hits[0].score else [])
        used = [hits[0].chunk.id] + ([hits[1].chunk.id] if len(parts) > 1 else [])
        reply = "\n\n".join(parts)
    else:
        if opts.get("simple"):
            body = [short_version(main)]
        else:
            body = pick_sentences(main, analysis.content, vocab, limit=2, force_first=False) if opts.get("concise") \
                else pick_sentences(main, analysis.content, vocab, limit=3)
        reply = " ".join(body)
        # a second section when it is nearly as relevant and says something different
        # (e.g. "what does the Mafia do, and how can we defeat them?" has two parts)
        if (not opts.get("concise") and not opts.get("simple") and len(hits) > 1 and hits[1].score >= 0.70 * hits[0].score
                and hits[1].chunk.id != main.id and len(reply) < 600):
            extra = pick_sentences(hits[1].chunk, analysis.content, vocab, limit=2, force_first=False)
            if " ".join(extra) not in reply:
                reply += " " + " ".join(extra)
                used.append(hits[1].chunk.id)
    if notes:
        reply = " ".join(notes) + " " + reply
    return reply, used


def refusal(category, helpful_hint=True):
    text = REFUSALS.get(category, REFUSALS["role_identity"])
    return text


GAME_ONLY = "I can only help with CAMORRA here: its rules, roles, phases, voting and strategy. What would you like to know?"
UNAVAILABLE = "Sorry, I couldn't process that just now. Please try again."


def general_unavailable(reason=None, error=None, repeat=False, what="that"):
    """Player-facing reply when a request could not be served. The technical reason is never shown to players;
    it goes to the server log (see ChatService)."""
    if reason in ("no_api_key", "forced_offline", None) and not error:
        return GAME_ONLY
    return UNAVAILABLE


def language_unavailable(language=None, reason=None):
    return GAME_ONLY if reason in ("no_api_key", "forced_offline") else UNAVAILABLE
