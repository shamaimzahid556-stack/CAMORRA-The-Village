"""Detects which language a player is writing in: English, Urdu script, or Pakistani Roman Urdu (Urdu in Latin
letters). Deliberately small and rule-based: it only decides which language the model is asked to reply in and which
language the fixed redirect messages use. It never sees anything but the player's own message."""
import re

URDU_SCRIPT = re.compile(r"[؀-ۿݐ-ݿ]")

# Function words that are very common in Roman Urdu and are not English words. One alone is weak evidence
# ("main" and "he" exist in English), so the strong set needs a single hit and the weak set needs two.
_STRONG = frozenset("""kya kyun kyon kaise kaisay kese kaun kon kahan kab kitne kitna kitni hai hain hoga hogi honge hota hoti hote
nahi nahin nhi nahe mujhe mujh humein hamein aap apna apni apne ko ka ki ke se mein mai kar karo karna karen karein kar sakta sakti sakte
samjhao samjha batao bataiye bataye batana kaam shak agar toh to lekin magar aur ya yeh ye woh wo is us unka uska iska
chahiye chahie kiya kiye karta karti karte rahega hun hoon tha thi the abhi phir bhi sirf bohat bahut zyada kuch koi
jeet jeetay jeetega haar marna maar marne bacha bachao bachana waqt raat din isko isay aasan aasaan asaan karke dobara kisko shuru kaisi tarika naya nayi""".split())
_STRONG = _STRONG - frozenset("the to a an is in of and so do or no ok are as at be by if it my on we he me".split())   # real English words
_WEAK = frozenset("main me mera meri mere tum tu he ab ap na ji".split())
_ENGLISH_ONLY = frozenset("the to a an of and for with game beginner is are what how who why when does do can should would could please explain".split())


def detect(text):
    """Return "urdu" (Urdu script), "roman_urdu" or "english"."""
    if not text:
        return "english"
    if len(URDU_SCRIPT.findall(text)) >= 2:
        return "urdu"
    words = re.findall(r"[a-z']+", text.lower())
    if not words:
        return "english"
    strong = sum(1 for w in words if w in _STRONG)
    weak = sum(1 for w in words if w in _WEAK)
    english = sum(1 for w in words if w in _ENGLISH_ONLY)
    # "to", "ka", "ki" are common English-looking tokens: require real Roman Urdu evidence relative to English evidence
    if strong >= 2 and strong >= english:
        return "roman_urdu"
    if strong >= 1 and weak >= 1 and english == 0:
        return "roman_urdu"
    return "english"


DISPLAY = {"urdu": "Urdu (Urdu script)", "roman_urdu": "Pakistani Roman Urdu", "english": "English"}
MODEL_NOTE = {
    "roman_urdu": ("The player is writing in Pakistani Roman Urdu (Urdu in Latin letters, mixed with English game words such as "
                   "Detective or voting). Reply in natural Pakistani Roman Urdu, not Hindi phrasing and not Urdu script. Keep CAMORRA terms in English. "),
    "urdu": ("The player is writing in Urdu script. Reply in natural Urdu script, keeping CAMORRA terms such as Detective and "
             "Doctor recognisable. "),
}


# ---- Roman Urdu / Urdu -> English keywords --------------------------------------------------------------------------
# The rulebook is written in English, so for retrieval a question is mapped word by word to English keywords. Words
# without an entry stay as typed (CAMORRA terms such as Detective, Doctor, voting are English in Roman Urdu anyway).
# The player's original message is what the model sees; this mapped text is only used to find rulebook sections.
_ROMAN = {
    "kya": "what", "kaam": "job do", "karta": "does", "karti": "does", "karte": "do", "hota": "is", "hoti": "is", "hote": "are",
    "hai": "is", "hain": "are", "hoga": "happen", "hogi": "happen", "honge": "happen", "kaise": "how", "kaisay": "how", "kese": "how",
    "kyun": "why", "kyon": "why", "kaun": "who", "kon": "who", "kahan": "where", "kab": "when", "kitne": "how many",
    "kitni": "how many", "kitna": "how much", "agar": "if", "toh": "then", "sakta": "can", "sakti": "can", "sakte": "can",
    "samjhao": "explain", "samjha": "explain", "samjhaye": "explain", "samjhain": "explain", "batao": "tell", "bataiye": "tell",
    "bataye": "tell", "mujhe": "me", "shak": "suspicious suspect", "shuba": "suspicious", "chahiye": "should", "chahie": "should",
    "karna": "do", "karo": "do", "karen": "do", "karein": "do", "kare": "do", "bachana": "protect save", "bacha": "protect save",
    "bachao": "protect save", "bachata": "protect save", "jeet": "win", "jeetega": "win", "jeetay": "win", "jeetne": "win",
    "jeetna": "win", "haar": "lose", "raat": "night", "din": "day", "naya": "beginner new", "nayi": "beginner new", "new": "beginner new",
    "aur": "and", "nahi": "not", "nahin": "not", "nhi": "not", "pehle": "first", "baad": "after", "agla": "next", "agli": "next",
    "iska": "this", "uska": "that", "madad": "help", "tarika": "way", "qawaid": "rules", "usool": "rules", "khel": "game",
    "khud": "myself", "barabar": "equal", "tie": "tie tied", "maar": "kill", "marna": "kill", "mar": "kill", "kar": "do",
    "dein": "", "den": "", "diya": "", "dia": "", "ko": "", "ka": "", "ki": "", "ke": "", "hun": "", "hoon": "", "ho": "",
    "main": "", "mai": "", "mein": "", "me": "", "se": "", "par": "", "pe": "", "ye": "this", "yeh": "this", "woh": "that", "wo": "that",
    "apne": "own", "apna": "own", "aap": "you", "ap": "you", "sab": "all", "tamam": "all", "sirf": "only", "bohat": "very", "bahut": "very",
    "wala": "", "wali": "", "tha": "was", "thi": "was", "abhi": "now", "phir": "then", "bhi": "also", "ya": "or", "lekin": "but",
    "magar": "but", "koi": "any", "kuch": "something", "vote": "vote", "voting": "voting", "rakhna": "keep", "karun": "do", "karoon": "do",
    "hamesha": "always", "jawab": "answer", "sawal": "question", "mushkil": "difficult", "asaan": "simpler", "asan": "simpler", "aasan": "simpler", "aasaan": "simpler", "chota": "shorter", "mukhtasar": "shorter",
    "mafias": "mafia", "isko": "it", "ise": "it", "isay": "it", "karke": "", "kisko": "whom", "kis": "which", "dobara": "again", "kisi": "any", "doosra": "other", "dosra": "other", "aakhri": "last", "pehla": "first", "pehli": "first",
}
_URDU = {
    "ڈاکٹر": "doctor", "جاسوس": "detective", "ڈیٹیکٹو": "detective", "مافیا": "mafia", "ووٹ": "vote", "ووٹنگ": "voting",
    "رات": "night", "دن": "day", "جیت": "win", "جیتتا": "win", "کھیل": "game", "گیم": "game", "کیا": "what", "کرتا": "does",
    "کرتی": "does", "کام": "job do", "کیسے": "how", "کون": "who", "کب": "when", "کیوں": "why", "قواعد": "rules", "اصول": "rules",
    "شک": "suspicious", "بچا": "protect", "بچاتا": "protect", "ٹائی": "tie", "برابر": "tie", "کھلاڑی": "player", "پلیئر": "player",
    "سمجھاؤ": "explain", "سمجھائیں": "explain", "بتاؤ": "tell", "بتائیں": "tell", "شہری": "civilian", "عام": "villager",
    "نیا": "beginner new", "ہے": "", "ہیں": "", "کو": "", "کا": "", "کی": "", "کے": "", "میں": "", "سے": "", "اور": "and", "نہیں": "not",
}
_TOKEN = re.compile(r"[A-Za-z']+|[؀-ۿݐ-ݿ]+|\d+")


def to_english(text, code=None):
    """Map a Roman Urdu or Urdu message to English retrieval keywords. English text is returned unchanged."""
    code = code or detect(text)
    if code == "english":
        return text
    table = _URDU if code == "urdu" else _ROMAN
    out = []
    for tok in _TOKEN.findall(text):
        key = tok if code == "urdu" else tok.lower()
        if key in table:
            if table[key]:
                out.append(table[key])
        elif code == "urdu" and URDU_SCRIPT.search(tok):
            continue                                   # unknown Urdu word: nothing to retrieve with
        else:
            out.append(tok)
    return " ".join(out) or text
