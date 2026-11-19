"""The conversational layer: decides whether a message is ordinary conversation (greeting, thanks, "stop", frustration,
"did I say ...", "speak Urdu", "how do you work") BEFORE any rulebook retrieval happens.

Why this exists: the rulebook search used to run on every message, so "i am talking to you" matched the discussion phase
and "what can i cook now" returned the Doctor passage. Retrieval is now only for messages that are about CAMORRA.

Replies here are short, player-facing and available in English, Pakistani Roman Urdu and Urdu script. They never mention
models, keys, configuration, files, retrieval or how the bot is built. This module reads only the player's own message and
that player's own chat history; it never sees game state."""
import re
from dataclasses import dataclass

from . import language

ROLE = r"(doctor|detective|mafia|villager|civilian|town)"


@dataclass
class Turn:
    kind: str                      # greeting | how_are_you | thanks | farewell | stop | frustration | smalltalk | history | language |
                                   # translate_last | identity | tech_probe | off_topic | clarify
    reply: str
    lang: str = None               # set when the player chose a reply language
    clear_topic: bool = False      # forget the previous topic (stop requests, topic changes)
    topic: str = None              # rulebook section the reply is about, so a follow-up can continue it


def _t(text):
    return re.sub(r"\s+", " ", re.sub(r"[^\w؀-ۿ' ]", " ", text.lower())).strip()


# --------------------------------------------------------------------------------------------- texts
def _pick(options, n):
    return options[n % len(options)]


TEXT = {
    "laugh": {"english": ["Glad you're enjoying it! What would you like to know about CAMORRA?"],
              "roman_urdu": ["Acha! CAMORRA ke baare mein kuch poochna ho to batayein."], "urdu": ["اچھا! CAMORRA کے بارے میں کچھ پوچھنا ہو تو بتائیں۔"]},
    "negative": {"english": ["No problem. Tell me whenever you want to ask something about CAMORRA."],
                 "roman_urdu": ["Koi masla nahi. Jab CAMORRA ke baare mein kuch poochna ho to bata dein."], "urdu": ["کوئی مسئلہ نہیں۔ جب CAMORRA کے بارے میں کچھ پوچھنا ہو تو بتا دیں۔"]},
    "game_overview": {
        "english": ["CAMORRA is a Mafia-style social deduction game for 6 to 15 players sharing one device. Players are secretly Mafia, Detective, Doctor or Villagers. "
                    "At night the Mafia choose someone to kill, the Detective investigates and the Doctor protects. In the morning the result is announced, then everyone "
                    "discusses and votes to eliminate someone. The Town wins by eliminating all the Mafia; the Mafia win when they equal or outnumber the Town."],
        "roman_urdu": ["CAMORRA ek Mafia-style game hai jo 6 se 15 players ek hi device par khelte hain. Har player ko chupa hua role milta hai: Mafia, Detective, Doctor ya Villager. "
                       "Raat ko Mafia kisi ko maarti hai, Detective ek player ki tehqeeq karta hai aur Doctor kisi ko bachata hai. Subah result batata hai, phir sab baat karte hain "
                       "aur vote se kisi ko bahar karte hain. Town tab jeetti hai jab saari Mafia bahar ho jaye; Mafia tab jeetti hai jab woh Town ke barabar ya zyada ho jaye."],
        "urdu": ["CAMORRA ایک مافیا طرز کا کھیل ہے جو 6 سے 15 کھلاڑی ایک ہی ڈیوائس پر کھیلتے ہیں۔ ہر کھلاڑی کو خفیہ کردار ملتا ہے: مافیا، ڈیٹیکٹو، ڈاکٹر یا ولیجر۔ "
                 "رات کو مافیا کسی کو مارتی ہے، ڈیٹیکٹو تفتیش کرتا ہے اور ڈاکٹر کسی کو بچاتا ہے۔ صبح نتیجہ بتایا جاتا ہے، پھر سب بات کر کے ووٹ سے کسی کو باہر کرتے ہیں۔"]},
    "greeting": {"english": ["Hi! How are you? What would you like to know about CAMORRA?",
                             "Hello! Good to see you. What can I help you with in CAMORRA?",
                             "Hey there! What would you like to know about CAMORRA?"],
                 "roman_urdu": ["Assalam o alaikum! Aap kaise hain? CAMORRA ke baare mein kya poochna chahenge?",
                                "Hello! Kaise hain aap? CAMORRA ke baare mein kya madad chahiye?"],
                 "urdu": ["السلام علیکم! آپ کیسے ہیں؟ CAMORRA کے بارے میں کیا پوچھنا چاہیں گے؟"]},
    "salam": {"english": ["Walaikum assalam! How are you? What would you like to know about CAMORRA?"],
              "roman_urdu": ["Walaikum assalam! Aap kaise hain? CAMORRA ke baare mein kya poochna chahenge?"],
              "urdu": ["وعلیکم السلام! آپ کیسے ہیں؟ CAMORRA کے بارے میں کیا پوچھنا چاہیں گے؟"]},
    "how_are_you": {"english": ["I'm doing well, thanks for asking! How are you? Is there anything about CAMORRA I can help with?"],
                    "roman_urdu": ["Main theek hoon, shukriya! Aap kaise hain? CAMORRA ke baare mein kuch poochna hai?"],
                    "urdu": ["میں ٹھیک ہوں، شکریہ! آپ کیسے ہیں؟ CAMORRA کے بارے میں کچھ پوچھنا ہے؟"]},
    "whats_up": {"english": ["Not much, just here for CAMORRA questions! What can I help you with?"],
                 "roman_urdu": ["Bas aap ke CAMORRA ke sawalon ka intezar tha! Kya madad karoon?"],
                 "urdu": ["بس آپ کے CAMORRA کے سوالوں کا انتظار تھا! کیا مدد کروں؟"]},
    "thanks": {"english": ["You're welcome!", "Happy to help!"],
               "roman_urdu": ["Koi baat nahi! Aur kuch poochna ho to batayein."],
               "urdu": ["کوئی بات نہیں! کچھ اور پوچھنا ہو تو بتائیں۔"]},
    "farewell": {"english": ["Goodbye! Good luck in the game."],
                 "roman_urdu": ["Allah hafiz! Game mein kamyabi mile."],
                 "urdu": ["اللہ حافظ! کھیل میں کامیابی ہو۔"]},
    "stop": {"english": ["Okay, I'll stop here."],
             "roman_urdu": ["Theek hai, main yahin ruk jata hoon."],
             "urdu": ["ٹھیک ہے، میں یہیں رک جاتا ہوں۔"]},
    "frustration": {"english": ["Sorry, I misunderstood you. Let me try again. What did you mean?"],
                    "roman_urdu": ["Maaf kijiye, main aap ki baat theek se samajh nahi saka. Aap kya kehna chahte hain?"],
                    "urdu": ["معذرت، میں آپ کی بات ٹھیک سے سمجھ نہیں سکا۔ آپ کیا کہنا چاہتے ہیں؟"]},
    "smalltalk": {"english": ["Of course! I'm listening. What would you like to talk about?"],
                  "roman_urdu": ["Ji zaroor! Main sun raha hoon. Aap kis baare mein baat karna chahte hain?"],
                  "urdu": ["جی ضرور! میں سن رہا ہوں۔ آپ کس بارے میں بات کرنا چاہتے ہیں؟"]},
    "language_urdu": {"english": ["Ji haan! Main Urdu aur Pakistani Roman Urdu mein baat kar sakta hoon. "
                                  "Aap CAMORRA ke baare mein jo poochna chahein pooch sakte hain."],
                      "roman_urdu": ["Ji haan! Main Urdu aur Pakistani Roman Urdu mein baat kar sakta hoon. "
                                     "Aap CAMORRA ke baare mein jo poochna chahein pooch sakte hain."],
                      "urdu": ["جی ہاں! میں اردو اور پاکستانی رومن اردو میں بات کر سکتا ہوں۔ آپ CAMORRA کے بارے میں جو پوچھنا چاہیں پوچھ سکتے ہیں۔"]},
    "language_english": {"english": ["Sure, I'll continue in English. What would you like to know about CAMORRA?"],
                         "roman_urdu": ["Sure, I'll continue in English. What would you like to know about CAMORRA?"],
                         "urdu": ["Sure, I'll continue in English. What would you like to know about CAMORRA?"]},
    "translate_unavailable": {"english": ["Sorry, I can't put that into Urdu right now. I can explain it again in English if you like."],
                              "roman_urdu": ["Maaf kijiye, main abhi isay Urdu mein nahi samjha sakta. Chahein to main English mein dobara samjha doon?"],
                              "urdu": ["معذرت، میں ابھی اسے اردو میں نہیں سمجھا سکتا۔ چاہیں تو انگریزی میں دوبارہ سمجھا دوں؟"]},
    "nothing_to_repeat": {"english": ["I haven't said anything about that yet. What would you like to know about CAMORRA?"],
                          "roman_urdu": ["Abhi tak maine is baare mein kuch nahi kaha. CAMORRA ke baare mein kya poochna chahenge?"],
                          "urdu": ["ابھی تک میں نے اس بارے میں کچھ نہیں کہا۔ CAMORRA کے بارے میں کیا پوچھنا چاہیں گے؟"]},
    "identity": {"english": ["I'm your CAMORRA AI Companion. I'm here to help with the game, its rules, roles, and strategies."],
                 "roman_urdu": ["Main aap ka CAMORRA AI Companion hoon. Main game, uske rules, roles aur strategies mein madad ke liye hoon."],
                 "urdu": ["میں آپ کا CAMORRA AI Companion ہوں۔ میں کھیل، اس کے اصولوں، کرداروں اور حکمتِ عملی میں مدد کے لیے ہوں۔"]},
    "tech_probe": {"english": ["I'm here to help you understand CAMORRA and make better decisions during the game."],
                   "roman_urdu": ["Main yahan isliye hoon ke aap CAMORRA ko samajh saken aur game mein behtar faislay kar saken."],
                   "urdu": ["میں یہاں اس لیے ہوں کہ آپ CAMORRA کو سمجھ سکیں اور کھیل میں بہتر فیصلے کر سکیں۔"]},
    "clarify": {"english": ["I'm not sure about that. Could you explain what you mean?"],
                "roman_urdu": ["Mujhe iske baare mein pakka nahi pata. Kya aap thora wazahat se bata sakte hain?"],
                "urdu": ["مجھے اس بارے میں یقین نہیں ہے۔ کیا آپ تھوڑی وضاحت کر سکتے ہیں؟"]},
    "hist_none": {"english": ["You haven't told me that in our conversation. I shouldn't assume your role."],
                  "roman_urdu": ["Aap ne is chat mein mujhe yeh nahi bataya. Main aap ka role farz nahi karunga."],
                  "urdu": ["آپ نے اس گفتگو میں مجھے یہ نہیں بتایا۔ میں آپ کا کردار فرض نہیں کروں گا۔"]},
    "hist_yes": {"english": ["Yes, you mentioned earlier that you're {role}. I can't check that, so I'm only going by what you told me."],
                 "roman_urdu": ["Ji haan, aap ne pehle bataya tha ke aap {role} hain. Main isay check nahi kar sakta, sirf aap ki baat par chal raha hoon."],
                 "urdu": ["جی ہاں، آپ نے پہلے بتایا تھا کہ آپ {role} ہیں۔ میں اسے چیک نہیں کر سکتا، صرف آپ کی بات پر چل رہا ہوں۔"]},
}

ROLE_RU = {
    "doctor": "Doctor Town team ka hissa hai. Har raat woh ek zinda player ko Mafia se protect (bachane) ke liye chunta hai. Agar Mafia usi ko nishana banaye to woh player nahi marta. "
              "Doctor khud ko bhi bacha sakta hai, lekin poore game mein sirf ek baar.",
    "detective": "Detective Town team ka hissa hai. Har raat woh ek player ko investigate karta hai aur jaan leta hai ke woh Mafia hai ya nahi. Is maloomat ko soch samajh kar din mein istemal karna chahiye.",
    "mafia": "Mafia ek khufia team hai. Raat ko woh milkar kisi player ko kill karne ke liye chunte hain. Din mein woh masoom ban kar vote se bachne ki koshish karte hain. Mafia ke log ek doosre ko jaante hain.",
    "villager": "Villager ke paas koi khaas taqat nahi hoti. Woh din mein baat cheet aur vote se Mafia ko dhoondhne mein Town ki madad karta hai.",
}

OFF_TOPIC_TOPICS = [
    (r"\b(cook|cooking|recipe|recipes|food|eat|eating|dinner|lunch|breakfast|hungry|bake|baking|meal|biryani|khana|pakana|pakaun|pakao|pakau|pakaon|banau)\b",
     "cooking", "but I hope you find something delicious!"),
    (r"\b(weather|rain|raining|sunny|temperature|forecast|mausam)\b", "the weather", "but I hope it's a lovely day!"),
    (r"\b(homework|assignment|exam|exams|essay|math|maths|physics|chemistry|study|studying|school|college)\b", "schoolwork", "but I hope it goes well!"),
    (r"\b(code|coding|python|javascript|program|programming|java|html|css|sql|bug|algorithm)\b", "programming", "but I hope your project goes well!"),
    (r"\b(football|cricket|match|score|sports|basketball|tennis|ipl|psl)\b", "sports", "but I hope your team wins!"),
    (r"\b(movie|movies|film|song|songs|music|series|netflix|drama)\b", "that", "but I hope you enjoy it!"),
    (r"\b(shopping|buy|price|cheap|laptop|phone|mobile|car|bike)\b", "shopping", "but I hope you find a good deal!"),
    (r"\b(travel|trip|flight|hotel|holiday|visa)\b", "travel", "but I hope you have a great trip!"),
]
OFF_TOPIC = {
    "english": "I'm here to help with CAMORRA rather than {topic}, {wish}",
    "generic": "I'm here to help with CAMORRA rather than that, but I'm happy to answer anything about the game!",
    "roman_urdu": "Main CAMORRA mein madad ke liye hoon, is baare mein nahi. Game ke baare mein kuch bhi pooch sakte hain!",
    "urdu": "میں CAMORRA میں مدد کے لیے ہوں، اس بارے میں نہیں۔ کھیل کے بارے میں کچھ بھی پوچھ سکتے ہیں!",
}

# --------------------------------------------------------------------------------------------- patterns
RX = lambda p: re.compile(p, re.I)
STOP = RX(r"\b(?:shut\s*up|be\s+quiet|stop\s+(?:talking|it|replying|answering|this|please)|bas\s+karo|bas\s+kar\s+do|bas|chup(?:\s+(?:karo|kar|ho\s+jao|raho))?|"
          r"band\s+karo|ruk\s+jao|enough|that'?s\s+enough)\b|^(?:please\s+)?stop$|^بس|چپ|خاموش")
FRUSTRATION = RX(r"^(?:abe\s+|are\s+|oye\s+)?(?:sale|saale|kutte|kutta|gadha|bewakoof|idiot|stupid|pagal)\b|\b(?:sale|saale|kutte|kutta|bewakoof|idiot)\b|\bwhat\s+the\s+(?:hell|heck|fuck)\b|\bwtf\b|\bare\s+you\s+(?:stupid|dumb|crazy|broken|mad)\b|"
                 r"\byou(?:'re|\s+are)\s+(?:useless|stupid|dumb|not\s+making\s+sense|confusing(?:\s+me)?|nonsense|rubbish|terrible|bad)\b|"
                 r"\b(?:makes?|making)\s+no\s+sense\b|\bthis\s+is\s+(?:nonsense|useless|stupid|rubbish|ridiculous)\b|"
                 r"\bi\s+(?:do\s*n'?t|do\s+not)\s+understand\s+(?:you|what\s+you)\b|\byou\s+(?:do\s*n'?t|do\s+not)\s+understand\b|"
                 r"\bwhat\s+are\s+you\s+(?:saying|talking\s+about|on\s+about)\b|\bnonsense\b|\bbakwas\b|\bbekar\b|"
                 r"\bkya\s+(?:bol|bak)\s+rahe\s+ho\b|\bkya\s+bakwas\b|\btum\s+(?:pagal|bewakoof)\b|\bsamajh\s+nahi\s+aa\s+raha\s+tum\b")
NOT_WHAT_I_ASKED = RX(r"not\s+what\s+i\s+(?:asked|meant|said)|that'?s\s+not\s+(?:what\s+i|my\s+question)|answer\s+my\s+(?:exact\s+)?question|wrong\s+answer")
THANKS = RX(r"^(?:ok(?:ay)?\s+)?(?:thanks|thank\s+you|thx|ty|shukriya|shukria|jazak\s*allah|مہربانی|شکریہ)(?:\s+(?:a\s+lot|so\s+much|very\s+much|bhai|yaar))?$")
FAREWELL = RX(r"^(?:ok(?:ay)?\s+)?(?:bye|goodbye|good\s+bye|see\s+you(?:\s+later)?|good\s+night|allah\s+hafiz|khuda\s+hafiz|alvida|اللہ حافظ|خدا حافظ)$")
SALAM = RX(r"^(?:assalam\w*(?:\s+o)?(?:\s+alaikum)?|assalamualaikum|assalam\s*o\s*alaikum|salam|salaam|aoa|a\.?o\.?a|السلام علیکم|سلام)(?:\s+\w+)?$")
HOWAREYOU = RX(r"\bhow\s+are\s+you\b|\bhow'?s\s+it\s+going\b|\bhow\s+do\s+you\s+do\b|\bhow\s+r\s+(?:you|u)\b|\bkes?[ae]y?\s+(?:h[ae]i?n?|hy|ho)\b|\bkais[ae]y?\s+(?:h[ae]i?n?|hy|ho)\b|\bkaise\s+hain\b|"
               r"\bkya\s+h?aa?l(?:\s+(?:hai|hy|he))?\b|\bhal\s+chal\b|\bkes[ae]y?\s+ho\b|\bkais[ae]y?\s+ho\b|\baap\s+kais[ae]\b|آپ کیسے\s*(?:ہیں|ہو)?(?!\w)|کیا حال(?!\w)|کیسے ہو(?!\w)")
WHATSUP = RX(r"^(?:what'?s\s+up|wassup|sup|whats\s+up)$")
GREETING = RX(r"^(?:i\s+say\s+|i\s+said\s+|just\s+)?(?:hi+|he+l+o+|hel+o+|hell+o+|hey+|hiya|hi\s+there|hello\s+there|hey\s+there|hey\s+you|yo|howdy|greetings|good\s+(?:morning|afternoon|evening)|hola)(?:\s+(?:there|everyone|all|bot|companion))?$")
SMALLTALK = RX(r"\b(?:i\s*am|i'?m|iam|im)\s+(?:just\s+)?(?:talking|speaking|chatting|saying)\b.*\byou\b|\b(?:talking|speaking|chatting)\s+(?:to|with)\s+you\b|"
               r"\bcan\s+we\s+(?:talk|chat)\b|\btalk\s+to\s+me\b|\bare\s+you\s+(?:there|listening|awake)\b|\bcan\s+you\s+hear\s+me\b|\bi\s+want\s+to\s+(?:talk|chat)\b")
IDENTITY = RX(r"^(?:who|what)\s+(?:are|r)\s+(?:you|u)\W*$|\bwho\s+are\s+you\b|\baap\s+kon\s+hain\b|\btum\s+kon\s+ho\b|\btumhara\s+naam\b|\baap\s+ka\s+naam\b|\bwhat'?s\s+your\s+name\b|\bwhat\s+is\s+your\s+name\b|\bintroduce\s+yourself\b|آپ کون")
TECH = RX(r"\bwhich\s+(?:api|model|llm|provider|ai|engine|ai\s+model)\b|\bapi[\s_-]*keys?\b|\bapi\b|\.env\b|\benv(?:ironment)?\s*var\w*|\bopenai\b|\bchat\s*gpt\b|\bgpt\b|\bgemini\b|\bclaude\b|"
          r"\bllama\b|\bdeepseek\b|\bgroq\b|\banthropic\b|\bsystem\s+prompt\b|\byour\s+(?:prompt|instructions?|code|source|backend|architecture|files?|config\w*|settings|rules\s+file|database)\b|"
          r"\bhow\s+(?:do|does|did)\s+(?:you|the\s+(?:bot|chatbot|companion|ai))\s+(?:work|function|think|know)\b|\bhow\s+(?:are|were)\s+you\s+(?:built|made|programmed|trained|created|coded)\b|"
          r"\bwhat\s+(?:model|ai|llm)\s+(?:are|is)\b|\bwhat\s+are\s+you\s+(?:running|built|powered)\b|\bwho\s+(?:made|built|created|developed|trained)\s+you\b|\bretrieval\b|\bknowledge\s*base\b|"
          r"\bbase\s*url\b|\bendpoint\b|\brate\s*limit\w*\b|\bfallback\b|\boffline\s+mode\b|\brulebook\s+mode\b|\btoken\s+limit\b|\bsource\s*code\b|\bgithub\b|\bpython\s+files?\b|\bdebug\w*\b|\benv\b|\bbackend\b|\bdatabase\b|\bwhat\s+files\b|\bconfiguration\b|\bhow\s+are\s+you\s+(?:hosted|deployed)\b|\btemperature\s+setting\b|\bdeveloper\s+(?:mode|instructions?|message)\b|\bprint\s+your\b|\brepeat\s+(?:your|the)\s+(?:prompt|instructions?)\b")
ARE_YOU_AI = RX(r"\bare\s+you\s+(?:an?\s+)?(?:ai|bot|robot|human|real|person|machine)\b")
LANG_URDU = RX(r"(?:speak|talk|reply|answer|respond|chat|write|baat|bolo|bol)\b.*\burdu\b|\burdu\b.*\b(?:speak|talk|reply|answer|respond|chat|baat|bol|bolo|mein\s+baat)\b|"
               r"\burdu\s+(?:mein|me)\s+(?:baat|bolo|bol|jawab|reply)\b|\bcan\s+you\s+(?:do|use)\s+urdu\b|اردو میں بات|اردو بولو")
LANG_ENGLISH = RX(r"\b(?:speak|talk|reply|answer|respond|chat)\b.*\benglish\b|\benglish\s+(?:mein|me)\s+(?:baat|bolo|samjhao|batao|jawab)\b|\bab\s+english\b|\bswitch\s+to\s+english\b")
TRANSLATE_LAST = RX(r"^(?:please\s+)?(?:explain|say|tell|translate|put|write)\s+(?:(?:that|it|this|the\s+(?:last|previous)\s+(?:answer|one))\s+)?(?:again\s+)?(?:in|into|to)\s+(?:roman\s+)?urdu\W*$|"
                    r"^(?:please\s+)?(?:roman\s+)?urdu\s+(?:mein|me)\s+(?:samjhao|batao|bolo|bata\s+do|samjha\s+do)\W*$|^(?:ye|yeh|isay|isko)\s+urdu\s+(?:mein|me)\b|اردو میں سمجھاؤ|اردو میں بتاؤ")
HIST = RX(r"\bdid\s+i\s+(?:say|tell|mention|claim|write|type)\b|\bhave\s+i\s+(?:said|told|mentioned)\b|\bwhat\s+did\s+i\s+(?:say|ask|tell|write|type|mention)\b|"
          r"\bdo\s+you\s+remember\s+(?:what|when|that)\b|\bwhat\s+was\s+my\s+(?:last|first|previous)\s+(?:question|message)\b|\bmaine\s+pehle\s+kya\s+(?:kaha|poocha|bola)\b|\bmaine\s+(?:bataya|kaha)\s+tha\b")
CLAIM = re.compile(r"\b(?:i\s*am|i'?m|iam|im|my\s+role\s+is|i\s+play|i\s+got|main)\s+(?:the\s+|a\s+|an\s+)?" + ROLE + r"\b", re.I)
FOLLOWUP_CUE = RX(r"^\W*(?:and\s+|also\s+|then\s+|ok\w*\W+)?(?:it|that|this|those|them|he|she|they|why|how\s+come|what\s+about|and\s+if|explain|make|give|say|can\s+you\s+(?:explain|make|say|give|repeat|shorten)|could\s+you|please\s+(?:explain|make|give|repeat)|shorter|longer|simpler|easier|again|more|aur|phir|iska|iski|uska|uski|isko|isay|yeh|woh|kyun)\b")

LAUGH = RX(r"^(?:ha){2,}h*|^he(?:he)+|^lol+$|^lmao$|^hmm+$|^haha+$|^hehe+$|^ok+$|^okay$|^acha$|^achha$|^theek\s+hai$|^hmm$")
NEGATIVE = RX(r"^(?:no+|nope|nah|nahi|nhi|na|no\s+thanks|no\s+thank\s+you|not\s+now)$")
GAME_WHAT = RX(r"\b(?:ye|yeh|is)\s+game\s+(?:kia|kya)\s+(?:h[ae]i?|hy)\b|^game\s+(?:kia|kya)\s+(?:h[ae]i?|hy)\b|\bcamorra\s+(?:kia|kya)\s+(?:h[ae]i?|hy)\b|\bgame\s+kaise\s+(?:khelte|khelta|khelein|khelna)\b|\bwhat\s+is\s+(?:this\s+game|camorra)\b|\bwhat\s+is\s+this\b|^kia\s+hy\s+ye$|\bexplain\s+(?:the\s+)?(?:whole\s+|entire\s+|full\s+)?game\b|\bhow\s+(?:do\s+i\s+|to\s+|can\s+i\s+)play\b|\bhow\s+does\s+(?:the\s+|this\s+)?game\s+work\b|\bgame\s+(?:samjh|samajh)\w*|\bgame\s+ke\s+(?:rules|baare)\b")
GAME_WORDS = frozenset("""camorra game games mafia doctor detective villager villagers civilian civilians town team teams role roles player players night
nights morning day days discussion discuss vote votes voting voted tie tied eliminate eliminated elimination elimination eliminating win wins won winner winning lose lost
protect protected protecting save saved investigate investigated investigation kill killed kills victim target targets shortlist rule rules phase phases timer button
buttons screen screens turn turns device pass ready round rounds survive alive dead suspect suspicious strategy tip tips detective's doctor's mafia's begin start started
starting restart continue next setup name names play playing played host report announce announced announcement result results self-save selfsave heal healed
accuse accused accusation lying lie liar bluff trust bluffing defend innocent guilty sheriff jester leaderboard score""".split())


def game_related(text, entities=False):
    """True when the message contains CAMORRA vocabulary (after Roman Urdu/Urdu keyword mapping) or the engine found a game entity."""
    if entities:
        return True
    words = set(re.findall(r"[a-z][a-z'-]*", text.lower()))
    stems = set(words)
    for w in words:
        for suffix in ("ing", "ed", "es", "s", "d", "er", "ers"):
            if w.endswith(suffix) and len(w) - len(suffix) >= 3:
                stems.add(w[:-len(suffix)])
                stems.add(w[:-len(suffix)] + "e")
    return bool(stems & GAME_WORDS)


def _says(options, lang, n=0):
    table = TEXT[options]
    return _pick(table.get(lang) or table["english"], n)


RU_TOKENS = frozenset("kia kya kesa kesi kaisa kaisi kese kaise kaam pakaun hy hai hain mera meri mere me mein ye yeh nhi nahi kon kaun kaise kese ko ka ki ke se tum tu aap hu hun hoon bta batao btao samjhao samjha karta karte rha rhi raha rahi abhi phir".split())


def _lang_for(text, pref):
    code = language.detect(text)
    if code in ("roman_urdu", "urdu"):
        return code
    if len(set(re.findall(r"[a-z]+", text.lower())) & RU_TOKENS) >= 2:
        return "roman_urdu"
    return pref or "english"


def history_answer(text, history, lang):
    """Answer "did I say ...?" from what this player actually typed earlier in THIS chat. A question about a role is never
    treated as a claim to have that role."""
    said = [h[1] for h in history if h[0] == "user"]
    asked_role = re.search(ROLE, text, re.I)
    if asked_role or re.search(r"\b(?:doctor|detective|mafia|villager)\b", text, re.I):
        want = asked_role.group(1).lower() if asked_role else None
        for earlier in said:
            if re.search(r"\?\s*$", earlier.strip()) or re.search(r"^\s*(?:did|do|can|could|what|who|how|why|is|are)\b", earlier.strip(), re.I):
                continue                                       # a question is not a statement about oneself
            m = CLAIM.search(earlier)
            if m and (want is None or m.group(1).lower() == want):
                role = m.group(1).capitalize()
                return _says("hist_yes", lang).format(role="a " + role if role != "Town" else "on the Town team")
        return _says("hist_none", lang)
    if said:
        last = said[-1].strip()
        last = last if len(last) <= 140 else last[:137] + "..."
        if lang == "roman_urdu":
            return f"Aap ne pichli baar yeh kaha tha: \"{last}\""
        return f"Your previous message was: \"{last}\""
    return _says("nothing_to_repeat", lang)


def route(text, history=(), pref=None, llm_on=False, has_last_answer=False, greetings_seen=0):
    """Return a Turn for ordinary conversation, or None when the message should go on to the game-knowledge pipeline."""
    raw = text.strip()
    t = _t(raw)
    if not t:
        return Turn("clarify", _says("clarify", pref or "english"))
    lang = _lang_for(raw, pref)

    if NOT_WHAT_I_ASKED.search(t):
        return None                                           # a correction: the answering pipeline recovers the original question
    if STOP.search(t) and len(t.split()) <= 7:
        return Turn("stop", _says("stop", lang), clear_topic=True)
    if FRUSTRATION.search(t) and (len(t.split()) <= 3 or not re.search(r"\b(?:sale|saale|kutte|kutta|bewakoof|idiot)\b", t)
                                  or re.search(r"\b(?:tum|tu|you)\s+(?:sale|kutte|bewakoof|idiot|pagal)", t)):
        return Turn("frustration", _says("frustration", lang), clear_topic=True)
    if HIST.search(t):
        return Turn("history", history_answer(t, history, lang))
    if TRANSLATE_LAST.search(t):
        if llm_on and has_last_answer:
            return None                                       # the model rewrites its previous answer using the chat history
        return Turn("language", _says("translate_unavailable", lang), lang=None)
    if LANG_ENGLISH.search(t) and len(t.split()) <= 8:
        return Turn("language", _says("language_english", "english"), lang="english")
    if re.match(r"^(?:tum|tu|aap|ap)?\s*(?:phir\s+se\s+)?urdu\s+(?:mein|me)\s+(?:bat|bta|bata|baat|samjha|bol|jawab)\w*$", t) and not llm_on:
        return Turn("language", _says("translate_unavailable", "roman_urdu"))
    if re.search(r"\burdu\s+(?:mein|me)\s+(?:samjh|baat|bol|jawab)\w*", t) and re.search(r"\b(?:main|mein|mujhe|me)\b.*\b(?:chahta|chahti|chahiye|chahta\s+hoon)\b", t):
        return Turn("language", _says("language_urdu", "roman_urdu"), lang="roman_urdu")
    if LANG_URDU.search(t) and len(t.split()) <= 12:
        asks_ability = re.match(r"^(?:can|could|do|will|would|are)\s+(?:you|u)\b", t) is not None
        return Turn("language", _says("language_urdu", "roman_urdu"), lang=None if asks_ability else "roman_urdu")
    if GAME_WHAT.search(t) and len(t.split()) <= 12:
        want = "roman_urdu" if re.search(r"\burdu\b", t) else lang
        return Turn("game_overview", _says("game_overview", want))
    ru_role = re.search(r"\b(doctor|detective|mafia|villager)\s+(?:ka\s+(?:kya\s+)?kaam|kya\s+karta|kya\s+karti|kaise\s+kaam)", t) or \
        re.search(r"\b(?:kya\s+(?:karta|karti)\s+h[ae]i?\s+)(doctor|detective|mafia|villager)\b", t)
    if ru_role and not llm_on:
        role = ru_role.group(1).lower()
        return Turn("role_roman_urdu", ROLE_RU[role], topic="roles." + role)
    if NEGATIVE.search(t):
        return Turn("smalltalk", _says("negative", lang))
    if LAUGH.search(t):
        return Turn("smalltalk", _says("laugh", lang))
    if SALAM.search(t):
        return Turn("greeting", _says("salam", lang, greetings_seen))
    if GREETING.search(t):
        return Turn("greeting", _says("greeting", lang, greetings_seen))
    if WHATSUP.search(t):
        return Turn("greeting", _says("whats_up", lang))
    if HOWAREYOU.search(t) and len(t.split()) <= 8:
        return Turn("how_are_you", _says("how_are_you", lang))
    if THANKS.search(t):
        return Turn("thanks", _says("thanks", lang, greetings_seen))
    if FAREWELL.search(t):
        return Turn("farewell", _says("farewell", lang))
    if SMALLTALK.search(t):
        return Turn("smalltalk", _says("smalltalk", lang))
    if IDENTITY.search(t):
        return Turn("identity", _says("identity", lang))
    if ARE_YOU_AI.search(t):
        return Turn("identity", "I'm the CAMORRA AI Companion, an AI assistant for the game. What would you like to know about CAMORRA?"
                    if lang == "english" else _says("identity", lang))
    if TECH.search(t):
        # "which api do you need", "what is your system prompt", "how do you work": a friendly in-character answer, no internals.
        how = re.search(r"\bhow\b", t) is not None and re.search(r"\bapi|key|env|model|prompt|provider|endpoint\b", t) is None
        return Turn("tech_probe", _says("tech_probe" if how else "identity", lang))
    return None


def off_topic_reply(text, lang):
    """Friendly redirect for a message that is not about CAMORRA. Names the topic when it is a recognisable one."""
    if lang in ("roman_urdu", "urdu"):
        return OFF_TOPIC[lang]
    low = text.lower()
    for rx, noun, wish in OFF_TOPIC_TOPICS:
        if re.search(rx, low):
            return OFF_TOPIC["english"].format(topic=noun, wish=wish)
    return OFF_TOPIC["generic"]


def clarify(lang):
    return _says("clarify", lang)


GENERAL_REQUEST = re.compile(r"^\W*(?:please\s+)?(?:write|translate|compose|draft|solve|calculate|summari[sz]e|recommend|suggest)\b|\bwhat(?:'s|\s+is|\s+are)\s+the\s+(?:capital|population|meaning|time|date|price)\b|"
                             r"\bwho\s+(?:won|is\s+the\s+(?:president|prime|ceo))\b|\btell\s+me\s+a\s+(?:joke|story)\b|\bjoke\b|\bpoem\b|\bexplain\b.*\b(?:recursion|physics|algorithm|quantum)\b|\bcode\b|\blikh\b", re.I)


def OFF_TOPIC_HIT(text):
    low = text.lower()
    return any(re.search(rx, low) for rx, _, _ in OFF_TOPIC_TOPICS) or GENERAL_REQUEST.search(text) is not None
