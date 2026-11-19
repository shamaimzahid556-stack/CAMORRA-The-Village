"""Answer styles ("modes") of the AI Companion.

A style changes HOW the assistant talks (tone, length, level of detail). It never changes WHAT it
may say: the same verified rulebook sections, the same privacy rules and the same refusals apply in
every style. The browser sends only a style id; anything that is not in STYLES falls back to the
default, so a style can never be used to smuggle text or instructions into a prompt.
"""
from .responder import sentences

DEFAULT = "friendly"

STYLES = {
    "friendly": {"label": "Friendly", "description": "Warm and encouraging. The default."},
    "personal": {"label": "Personal", "description": "Talks to you directly, like your own game companion."},
    "robotic": {"label": "Robotic", "description": "Machine-style status messages."},
    "beginner": {"label": "Beginner", "description": "Very simple words and short sentences."},
    "concise": {"label": "Concise", "description": "The shortest answer that still helps."},
    "detailed": {"label": "Detailed", "description": "Full, step-by-step explanations."},
    "noir": {"label": "Noir narrator", "description": "Dark and atmospheric, like the game itself."},
}

LLM_INSTRUCTIONS = {
    "friendly": "Style: warm, patient and encouraging, like a helpful friend. 2 to 5 sentences.",
    "personal": ("Style: speak directly to the player like a personal companion who is sitting next to them. Casual, first person "
                 "('I'), second person ('you'), contractions are fine. 2 to 5 sentences."),
    "robotic": ("Style: speak like a retro game robot. Short declarative sentences, one idea per line, status words in capitals "
                "such as AFFIRMATIVE, PROCESSING, WARNING. No jokes. Still be accurate."),
    "beginner": ("Style: explain as if to someone who has never played a social deduction game. Very simple words, short sentences, "
                 "no jargon, one tiny example if it helps."),
    "concise": "Style: as short as possible. Maximum 2 sentences. No introduction and no closing remark.",
    "detailed": "Style: thorough and step by step, with everything the rules say on the topic. Up to 10 sentences or a short numbered list.",
    "noir": ("Style: a dark, atmospheric noir narrator. Moody, short, a little menacing, but every rule you state must stay exactly accurate. "
             "2 to 5 sentences."),
}

_OPEN = {
    "personal": ["Hey! ", "Alright, here's the deal: ", "Okay, so here's what you need to know: ", "Got you. "],
    "beginner": ["Let's keep it simple. ", "No worries, here it is in plain words. "],
    "noir": ["The night is long, friend. ", "Listen close. ", "Here's how the story goes. "],
}
_CLOSE = {
    "personal": [" I'm right here if you want me to go over any part again.", " Just ask if anything is still fuzzy."],
    "beginner": [" Ask me if any word is confusing."],
    "noir": [" Trust no one.", " The village is watching."],
}
_SPECIAL = {
    "robotic": {"refusal": "ACCESS DENIED.", "greeting": "UNIT ONLINE.", "thanks": "ACKNOWLEDGED.",
                "off_topic": "OUT OF SCOPE.", "no_answer": "DATA NOT FOUND.", "answer": "PROCESSING... QUERY ACCEPTED."},
    "noir": {"refusal": "That secret stays in the dark, friend.", "greeting": "Welcome, stranger.",
             "off_topic": "That's not a story I tell, friend.", "no_answer": "Some things even the night doesn't know."},
    "personal": {"refusal": "Sorry, I can't help with that one.", "off_topic": "Ha, that's outside my little world.",
                 "no_answer": "Hmm, I'm not sure about that one."},
    "friendly": {"refusal": "I'm sorry, I can't help with that.", "no_answer": "Good question, but"},
}


def normalize(style):
    return style if isinstance(style, str) and style in STYLES else DEFAULT


def public_list():
    return [{"id": k, "label": v["label"], "description": v["description"]} for k, v in STYLES.items()]


def llm_instruction(style):
    return LLM_INSTRUCTIONS[normalize(style)]


def options(style):
    """How the offline composer should behave for this style."""
    style = normalize(style)
    return {"detail": style == "detailed", "simple": style == "beginner", "concise": style == "concise"}


def decorate(style, text, kind="answer", n=0):
    """Wrap an offline / rule-based reply in the style's voice. Content is never changed or removed."""
    style = normalize(style)
    if not text or kind == "chat":      # ordinary conversation is never dressed up
        return text
    if style == "robotic":
        head = _SPECIAL["robotic"].get(kind, _SPECIAL["robotic"]["answer"])
        lines = []
        for para in text.split("\n"):
            for sent in sentences(para):
                lines.append("> " + sent)
        return head + "\n" + "\n".join(lines) + ("\nEND OF TRANSMISSION." if kind == "answer" else "")
    if kind in ("refusal", "off_topic", "no_answer", "greeting", "thanks"):
        lead = _SPECIAL.get(style, {}).get(kind, "")
        return (lead + " " + text) if lead else text
    if kind != "answer":
        return text
    opens, closes = _OPEN.get(style), _CLOSE.get(style)
    if not opens:                       # concise, detailed: no decoration
        return text
    return opens[n % len(opens)] + text + (closes[n % len(closes)] if closes else "")
