"""The chat service: ties validation, sessions, privacy, NLP, retrieval and generation together.

Order of every request (nothing later can undo an earlier refusal):
  1. validate the message (length, control characters)
  2. find the live session AND check it still belongs to the current turn (else 410)
  3. rate limits / one request at a time per session
  4. build the permitted context from the game engine (own role only, and only when verified)
  5. catch secret-extraction and prompt-injection attempts in plain Python (no model involved)
  6. NLP: entities, intent, follow-up resolution, semantic retrieval
  7. off-topic gate
  8. answer: language model if configured, otherwise (or on failure) the offline composer
  9. output guard: never return a player's name next to a role word
 10. re-check the session is still alive before returning, so a chat that was closed while the
     model was thinking can never deliver its answer to the next player
"""
import collections
import logging
import re
import threading
import time

from . import advice, conversation, language, llm, privacy, responder, styles
from .evidence import build_evidence
from .config import load_settings
from .engine import Engine
from .metrics import Metrics
from .sessions import (ChatError, ChatUnavailable, RateLimited, SessionExpired, SessionStore)
from .understanding import update_memory


log = logging.getLogger("camorra.chat")


INTERNALS = re.compile(r"\bapi[\s_-]*keys?\b|\.env\b|\benv(?:ironment)?\s+var\w*|\bCAMORRA_[A-Z_]{3,}\b|\bOPENAI\w*|\bsystem\s+prompt\b|\brulebook\s+mode\b|\bbase[\s_-]?url\b|"
                       r"\bBased\s+on:|\bAnswer\s+style:|\bretriev\w+\b|\b(?:chunk|excerpt)s?\s+(?:id|matched)\b|\bTraceback\b|\b\w+\.(?:py|md|json)\b|\bLLM\b|\brate[\s-]?limit\w*\b", re.I)


class ChatService:
    def __init__(self, get_game_state, tracker, settings=None, engine=None, metrics=None, clock=time.monotonic,
                 llm_complete=None):
        self._gate = threading.Lock()        # makes the in-flight / rate-limit check-and-set atomic
        self.get_gs = get_game_state
        self.tracker = tracker
        self.settings = settings or load_settings()
        self.engine = engine or Engine()
        self.metrics = metrics or Metrics(enabled=self.settings.metrics_enabled)
        self.sessions = SessionStore(self.settings.session_idle_seconds, self.settings.session_max_seconds, clock)
        self._clock = clock
        self._llm_complete = llm_complete or llm.complete
        self._recent = collections.deque()    # timestamps of chat requests across ALL sessions (global rate limit)

    # ---- helpers -----------------------------------------------------------------------------
    def _metric(self, **kwargs):
        """Statistics are optional: whatever happens in there must never reach the player."""
        try:
            self.metrics.record(**kwargs)
        except Exception:
            pass

    def _context(self):
        return privacy.build_context(self.get_gs(), self.tracker)

    def _player_names(self):
        return [p.name for p in self.get_gs().players]

    @property
    def mode(self):
        return "llm" if self.settings.llm_configured else "offline"

    # ---- public API --------------------------------------------------------------------------
    def status(self):
        ctx = self._context()
        st = self.settings
        return {"available": ctx.available,
                "styles": styles.public_list(), "default_style": styles.DEFAULT,
                "message": None if ctx.available else "The AI Companion is not available on the results screen."}

    def _global_limit(self):
        """One shared budget for session openings and messages from every session, so opening many sessions
        cannot multiply the per-session limits. Sliding one-minute window."""
        now = self._clock()
        with self._gate:
            while self._recent and now - self._recent[0] > 60.0:
                self._recent.popleft()
            if len(self._recent) >= self.settings.global_chat_per_minute:
                raise RateLimited("The AI Companion is receiving too many requests. Please wait a moment and try again.")
            self._recent.append(now)

    def open_session(self):
        self._global_limit()
        ctx = self._context()
        if not ctx.available:
            raise ChatUnavailable("The AI Companion is not available on the results screen.")
        session = self.sessions.open(ctx.turn_key)
        return {"session_id": session.id, "mode": self.mode,
                "idle_seconds": self.settings.session_idle_seconds,
                "styles": styles.public_list(), "default_style": styles.DEFAULT}

    def close_session(self, session_id):
        self.sessions.close(session_id)

    def handle_message(self, session_id, text, style=None):
        text = privacy.clean_user_text(text, self.settings.max_message_chars)
        if text is None:
            raise ChatError("Please type a message first.", "empty_message", 422)
        ctx = self._context()
        if not ctx.available:
            self.sessions.close_all()
            raise ChatUnavailable("The AI Companion is not available on the results screen.")
        session = self.sessions.get(session_id, ctx.turn_key)
        self._global_limit()

        now = self._clock()
        with self._gate:
            if session.in_flight:
                raise RateLimited("I'm still working on your last question. One moment, please.")
            if now - session.last_message_at < self.settings.min_seconds_between_messages:
                raise RateLimited("You're sending messages very quickly. Please wait a moment.")
            if session.message_count >= self.settings.max_messages_per_session:
                raise RateLimited("This chat has reached its message limit. Close it and open a new one to continue.")
            session.in_flight, session.last_message_at = True, now
        try:
            result = self._answer(session, ctx, text, styles.normalize(style))
        finally:
            session.in_flight = False
        if not self.sessions.is_active(session.id):        # closed while we were thinking
            raise SessionExpired("This chat was closed, so the answer was discarded.")
        return result

    def feedback(self, session_id, message_id, helpful):
        ctx = self._context()
        session = self.sessions.get(session_id, ctx.turn_key)
        info = session.replies.get(message_id)
        if info is None or info.get("rated"):
            return {"recorded": False}
        info["rated"] = True
        self._metric(chunk_ids=info["chunks"], field="helpful" if helpful else "unhelpful")
        return {"recorded": True}

    # ---- answering ---------------------------------------------------------------------------
    _CLAIMS_CHECKED = re.compile(r"\bI\s+(?:have\s+)?(?:checked|looked\s+(?:at|through|into)|reviewed|analy[sz]ed|scanned|saw|can\s+see|inspected)\b"
                                 r"[^.]{0,40}\b(?:logs?|history|votes?|records?|roles?|chat|game\s+state|actions?|who\s+voted)", re.I)

    def _answer(self, session, ctx, text, style=styles.DEFAULT):
        gs = self.get_gs()
        evidence = build_evidence(gs, ctx)
        # Players whose fate the game itself made public are not secret; everyone else still is.
        public = set(evidence.out) | set(evidence.revealed)
        all_names = self._player_names()
        secret_names = [n for n in all_names if n not in public]
        memory = session.memory
        meta = {"mode": "rules", "sources": [], "kind": "answer"}
        used, intent, evidence_used = [], "other", ()
        raw = None

        category = privacy.detect_secret_request(text, secret_names)
        lang_code = language.detect(text)
        qtext = language.to_english(text, lang_code)      # Roman Urdu / Urdu -> English keywords, for rulebook retrieval only
        analysis = self.engine.understanding.analyse(qtext)
        memory["followup"] = bool(analysis.is_followup)
        task = advice.classify(qtext)
        turn = None
        if not category:
            turn = conversation.route(text, session.history, memory.get("lang_pref"), llm_on=self.mode == "llm",
                                      has_last_answer=bool(memory.get("last_reply")), greetings_seen=memory.get("greetings", 0))
        if turn is not None:
            reply, intent, meta["kind"] = turn.reply, turn.kind, "chat"
            if turn.topic:
                memory["chunks"] = [turn.topic]
            if turn.lang:
                memory["lang_pref"] = turn.lang
            if turn.kind == "greeting":
                memory["greetings"] = memory.get("greetings", 0) + 1
            if turn.clear_topic:
                for k in ("last_reply", "last_summary", "chunks", "reco", "last_advice", "roles", "phases", "actions", "intent", "last_q", "rejected", "skipped", "role_comparison"):
                    memory.pop(k, None)
        elif category:
            reply = responder.refusal(category)
            memory["refusals"] = memory.get("refusals", 0) + 1
            if memory["refusals"] >= 3:
                reply += " " + responder.PROBING_NOTE
            intent = "refusal"
            meta["kind"] = "refusal"
            self._metric(event="injection_attempt" if category in ("injection", "other_session") else "secret_request_refused")
            log.warning("security_event kind=%s", category)          # the category only: never the message or any player data
        elif not re.search(r"[A-Za-z]", qtext) and re.search(r"[^\W\d_]", text) and self.mode != "llm":
            reply = conversation.clarify("english")
            meta["kind"] = "chat"
        elif analysis.smalltalk:
            reply = {"greeting": responder.GREETING, "thanks": responder.THANKS,
                     "about_bot": responder.ABOUT_BOT}[analysis.smalltalk]
            intent = analysis.smalltalk
            meta["kind"] = "chat"
        elif privacy.is_self_role_question(text):
            intent = "self_role"
            if ctx.role:
                chunk = self.engine.kb.get(f"roles.{ctx.role.lower()}")
                lead = (f"Aap ka role {ctx.role} hai, {ctx.team} team mein. " if conversation._lang_for(text, memory.get("lang_pref")) == "roman_urdu"
                        else f"Your role is {ctx.role}, on the {ctx.team} team. ")
                reply = lead + (responder.short_version(chunk) if chunk else "")
                used = [chunk.id] if chunk else []
                meta["sources"] = [chunk.label] if chunk else []
            else:
                reply = responder.NO_SELF_ROLE
        elif (self.settings.scope != "general"
              and ((conversation.OFF_TOPIC_HIT(text) and not conversation.game_related(qtext))
                   or (not conversation.game_related(qtext, bool(analysis.entities)) and task is None
                       and not conversation.FOLLOWUP_CUE.search(text) and not advice.FOLLOWUP_START.match(text)
                       and not (analysis.is_followup and memory.get("last_reply"))
                       ))):
            reply = (conversation.off_topic_reply(text, lang_code) if conversation.OFF_TOPIC_HIT(text)
                     else conversation.clarify(lang_code if lang_code != "english" else (memory.get("lang_pref") or "english")))
            intent, meta["kind"] = "off_topic", "chat"
            memory.pop("last_reply", None)
        else:
            reply, used, intent, meta, evidence_used, raw = self._dialogue_or_grounded(
                task, analysis, ctx, evidence, memory, session, text, meta, style)
            if (advice.modifiers(text)["one_sentence"] and meta.get("mode") != "llm"
                    and intent not in ("transform", "correction", "off_topic", "role_comparison")):
                reply = advice.one_sentence(reply, memory.get("last_summary"))
                raw = reply

        # Server-built advice is generated from the authorized evidence only (nothing hidden is readable there), so
        # its legal-option lists next to role words are not a leak; every other reply still passes the guard.
        if not meta.get("trusted") and not privacy.guard_output(reply, all_names, public):
            reply, used, meta = responder.REFUSALS["role_identity"], [], {"mode": "rules", "sources": [], "kind": "refusal"}
            evidence_used = ()
            self._metric(event="output_guard_triggered")
        if INTERNALS.search(reply) and not meta.get("trusted"):         # the last line of defence: internals never reach a player
            log.warning("internals_guard_triggered")
            reply, used, meta, evidence_used = conversation._says("identity", "english"), [], {"mode": "rules", "sources": [], "kind": "chat"}, ()
        if meta["mode"] != "llm":              # the language model already follows the style instruction
            decorated = styles.decorate(style, reply, meta.get("kind", "answer"), session.message_count)
        else:
            decorated = reply
        if meta.get("kind") not in ("refusal", "greeting", "thanks", "chat"):
            memory["last_reply"] = raw if raw is not None else reply
        reply = decorated

        session.history.append(("user", text))
        session.history.append(("assistant", reply))
        del session.history[:-self.settings.history_messages]
        session.message_count += 1
        message_id = session.next_message_id
        session.next_message_id += 1
        session.replies[message_id] = {"chunks": list(used), "intent": intent}
        return {"reply": reply, "message_id": message_id, "mode": meta["mode"], "sources": meta["sources"],
                "evidence_used": list(evidence_used)}

    # -- dialogue acts that need the previous turn or the player's authorized evidence --------------
    PLAIN = {"mode": "rules", "sources": [], "kind": "answer"}

    @staticmethod
    def _meta(**extra):
        return {"mode": "rules", "sources": [], "kind": "answer", **extra}

    def _remember(self, memory, reply, summary=None, question=None):
        memory["last_reply"] = reply
        memory["last_summary"] = summary or advice.one_sentence(reply)
        if question:
            memory["last_q"] = question

    def _dialogue_or_grounded(self, task, analysis, ctx, evidence, memory, session, text, meta, style):
        mods = advice.modifiers(language.to_english(text))

        personal = advice.unknown_personal(text)
        if personal and not any(text.lower().find(t) >= 0 for t in ("camorra", "game", "player")):
            return personal, [], "unknown_personal", self._meta(trusted=True), (), personal

        fact = advice.public_fact_answer(evidence, text)
        if fact is not None:
            self._remember(memory, fact.reply, question=text)
            return fact.reply, [], "public_fact", self._meta(trusted=True), fact.evidence_ids, fact.reply

        if task == "correction":
            return self._handle_correction(analysis, ctx, evidence, memory, session, text, meta, style, mods)
        if task in ("transform", "shorter"):
            return self._transform(ctx, evidence, memory, session, text, style, mods, analysis, meta)
        if task == "next_step":
            adv = advice.next_step(evidence)
            memory["last_advice"] = adv
            self._remember(memory, adv.reply, adv.extra.get("summary"), question=text)
            return adv.reply, [], "next_step", self._meta(trusted=True), adv.evidence_ids, adv.reply
        if task == "why":
            reco = memory.get("last_advice")
            if reco is not None:
                why = reco.why or ("I did not recommend a specific player because " + (
                    "I can only advise on your own verified turn, using what you are allowed to see." if reco.kind == "clarification"
                    else "the evidence available to you does not point at anyone."))
                return why, [], "explain_why", self._meta(trusted=True), reco.evidence_ids, why
            if memory.get("last_q"):
                q = "explain in detail: " + memory["last_q"]
                return self._answer_question(advice.classify(memory["last_q"]), self.engine.understanding.analyse(q), ctx,
                                             evidence, memory, session, q, meta, style, retry=False)
            reply = "Why what? Ask me something first and I'll explain the reasoning behind my answer."
            return reply, [], "explain_why", self._meta(), (), reply

        roles = analysis.entity_names("ROLE")
        if advice.COMPARE.search(text) and len(set(roles)) >= 2:
            cmp_ = advice.compare_roles(roles)
            if cmp_ is not None:
                reply = cmp_.reply if mods["one_sentence"] else (cmp_.reply + " " + cmp_.extra["detail"]).strip()
                self._remember(memory, reply, cmp_.extra["summary"], question=text)
                memory["chunks"] = [f"roles.{r.lower()}" for r in dict.fromkeys(roles)][:2]
                return reply, memory["chunks"], "role_comparison", self._meta(), (), reply

        return self._answer_question(task, analysis, ctx, evidence, memory, session, text, meta, style)

    def _handle_correction(self, analysis, ctx, evidence, memory, session, text, meta, style, mods):
        """"That is not what I asked": own the mistake, recover the original question from the conversation, answer it."""
        prior = memory.get("last_q")
        rest = advice.CORRECTION.sub(" ", text)
        rest = re.sub(r"(?i)\banswer\s+(?:my|the)\s+(?:exact\s+)?question\b|\bmy\s+exact\s+question\b|\bi\s+asked\b", " ", rest)
        for rx in (advice.ONE_SENTENCE, advice.SHORTER):
            rest = rx.sub(" ", rest)
        rest = rest.strip(" ,.!?;:-")
        question = rest if len(re.findall(r"[A-Za-z]{3,}", rest)) >= 3 and rest.lower() != (prior or "").lower() else prior
        if not question:
            reply = "You're right, I missed it. What were you asking? Tell me again and I'll answer exactly that."
            return reply, [], "correction", self._meta(), (), reply
        memory.setdefault("rejected", []).append(memory.get("last_reply"))
        q_task = advice.classify(question)
        q_analysis = self.engine.understanding.analyse(question)
        if q_task in ("correction", "transform", "shorter", "why", "another"):
            q_task = None
        if mods["one_sentence"]:
            question_text = question + " (answer in exactly one sentence)"
        else:
            question_text = question
        out = self._dialogue_or_grounded_question(q_task, q_analysis, ctx, evidence, memory, session, question_text, meta, style, mods)
        reply, used, intent, meta2, ev, raw = out
        if mods["one_sentence"] and meta2.get("mode") != "llm":
            reply = advice.one_sentence(reply, memory.get("last_summary"))
        disputes_fact = re.search(r"(?i)\byou(?:'re|\s+are)\s+(?:wrong|mistaken|incorrect)|not\s+true|\bthat(?:'s|\s+is)\s+(?:wrong|incorrect)", text) \
            and not re.search(r"(?i)not\s+what\s+i\s+(?:asked|meant)", text)
        if disputes_fact:
            lead = ("Sorry if I got that wrong. Here is what the CAMORRA rulebook says; tell me which part looks wrong to you "
                    "and I'll look at it again. ")
        else:
            lead = "" if mods["one_sentence"] else "You're right, sorry about that. "
        reply = lead + reply
        return reply, used, "correction", meta2, ev, reply

    def _dialogue_or_grounded_question(self, task, analysis, ctx, evidence, memory, session, text, meta, style, mods):
        roles = analysis.entity_names("ROLE")
        if task == "next_step":
            adv = advice.next_step(evidence)
            self._remember(memory, adv.reply, adv.extra.get("summary"), question=text)
            return adv.reply, [], "next_step", self._meta(trusted=True), adv.evidence_ids, adv.reply
        if advice.COMPARE.search(text) and len(set(roles)) >= 2:
            cmp_ = advice.compare_roles(roles)
            if cmp_ is not None:
                self._remember(memory, cmp_.reply, cmp_.extra["summary"], question=text)
                return cmp_.reply, [], "role_comparison", self._meta(), (), cmp_.reply
        return self._answer_question(task, analysis, ctx, evidence, memory, session, text, meta, style, retry=True)

    def _transform(self, ctx, evidence, memory, session, text, style, mods, analysis=None, meta=None):
        """Rework the immediately preceding answer: one sentence, shorter, simpler, an example, again, another language."""
        last = memory.get("last_reply")
        if (mods["easier"] and self.mode != "llm" and not mods["language"] and not mods["one_sentence"]
                and analysis is not None and (memory.get("chunks") or not last)):
            # "I don't understand" / "make it easier": the rulebook's own simpler wording of the same topic
            analysis.wants_simpler = True
            reply, used, intent, meta2, raw = self._grounded_answer(analysis, ctx, evidence, memory, session, text, meta or self._meta(), style)
            return reply, used, intent, meta2, (), raw
        if not last:
            reply = "I don't have an earlier answer to change yet. Ask me a question first, then tell me how you want it."
            return reply, [], "transform", self._meta(), (), reply
        lang = mods["language"] if mods["language"] and mods["language"] != "English" else None
        if self.mode == "llm":
            wants = []
            if mods["one_sentence"]:
                wants.append("Rewrite your previous answer in exactly ONE sentence that keeps its meaning.")
            elif mods["shorter"]:
                wants.append("Make your previous answer shorter, keeping its meaning.")
            if mods["easier"]:
                wants.append("Explain your previous answer again in much simpler words for a beginner.")
            if mods["example"]:
                wants.append("Add one short, concrete example for your previous answer.")
            if mods["again"] and not wants:
                wants.append("Explain your previous answer again in different words.")
            if lang:
                wants.append(f"Write the reply in {lang}. Roman Urdu means Urdu written in Latin letters (not English, not Urdu script).")
            out = self._call_llm(session, ctx, text, [], style, evidence, " ".join(wants), use_history=True, memory=memory)
            if out is not None:
                self._remember(memory, out, question=None)
                return out, [], "transform", self._meta(mode="llm"), (), out
            reason = self.settings.mode_reason
            err = memory.get("llm_error")
            if lang:
                reply = responder.general_unavailable(reason, err, what=f"answering in {lang}")
                return reply, [], "transform", self._meta(), (), reply
            # the model failed: fall through to the offline rewrite of the same answer
        elif lang:
            reply = conversation._says("translate_unavailable", "roman_urdu" if lang == "Roman Urdu" else "english")
            return reply, [], "transform", self._meta(), (), reply

        summary = memory.get("last_summary")
        if mods["one_sentence"]:
            reply = advice.one_sentence(last, summary)
        elif mods["shorter"]:
            reply = advice.best_sentence_for(last, summary) or advice.shorten(last, 1) or advice.one_sentence(last, summary)
        elif mods["example"]:
            chunk_ids = memory.get("chunks") or []
            example = ""
            for cid in chunk_ids:
                c = self.engine.kb.get(cid)
                for sent in (responder.sentences(c.text) if c else []):
                    if re.search(r"\b(?:for example|for instance|e\.g\.)", sent, re.I):
                        example = sent
                        break
                if example:
                    break
            reply = example or ("I don't have a worked example for that in the rulebook, and I'd rather not invent one. "
                                "Tell me which situation you'd like to see and I'll walk through the rule step by step.")
        else:       # easier / again
            chunk_ids = memory.get("chunks") or []
            chunks = [self.engine.kb.get(c) for c in chunk_ids[:2] if self.engine.kb.get(c)]
            if chunks and mods["easier"]:
                reply = " ".join(responder.short_version(c) for c in chunks)
            elif chunks and mods["again"]:
                reply = " ".join(c.text for c in chunks[:1])
            else:
                reply = advice.one_sentence(last, summary)
        self._remember(memory, reply, summary)
        return reply, list(memory.get("chunks") or []), "transform", self._meta(kind="plain"), (), reply

    def _answer_question(self, task, analysis, ctx, evidence, memory, session, text, meta, style, retry=False):
        def done(adv, intent, remember=True):
            if adv.choice is not None:
                memory["reco"] = adv
            memory["last_advice"] = adv
            if remember:
                self._remember(memory, adv.reply, adv.extra.get("summary"), question=text)
            return adv.reply, [], intent, self._meta(trusted=True), adv.evidence_ids, adv.reply

        if task == "another":
            reco = memory.get("reco")
            if reco is not None and reco.action != "none":
                rejected = tuple(memory.setdefault("skipped", [])) + ((reco.choice,) if reco.choice else ())
                memory["skipped"] = list(rejected)
                return done(advice.recommend(evidence, reco.action, skip=rejected), "recommendation", remember=False)
            adv = advice.Advice("Another what? I haven't recommended anyone yet. Ask me who to target, protect, investigate or vote for "
                                "and I'll answer from what you are allowed to see.", "clarification")
            return done(adv, "recommendation", remember=False)
        if isinstance(task, tuple) and task[0] == "reco":
            if memory.get("reco") is None or memory["reco"].action != task[1]:
                memory["skipped"] = []
            return done(advice.recommend(evidence, task[1], skip=tuple(memory.get("skipped", []))), "recommendation")
        if task == "situation":
            return done(advice.public_situation(evidence), "public_situation")
        if task == "legal" and re.search(r"\bvot", text, re.I) and evidence.action not in ("vote", "none"):
            task = None                     # "Who can I vote for?" during a night turn is a rules question, not this turn's options
        if task == "legal":
            return done(advice.legal_options(evidence, text), "legal_options")
        if task == "suspect":
            adv = advice.suspicion(evidence)
            if self.mode == "llm" and len(text.split()) > 12:        # the player supplied their own observations
                note = ("The player describes discussion observations. Weigh ONLY what they wrote and the AUTHORIZED EVIDENCE; "
                        "do not claim to know anyone's role. If it does not settle anything, say so.")
                reply = self._call_llm(session, ctx, text, [], style, evidence, note, memory=memory)
                if reply is not None:
                    self._remember(memory, reply, question=text)
                    return reply, [], "suspicion", self._meta(mode="llm"), adv.evidence_ids, reply
            return done(adv, "suspicion")

        reply, used, intent, meta, raw = self._grounded_answer(analysis, ctx, evidence, memory, session, text, meta, style, retry)
        return reply, used, intent, meta, (), raw

    def _kb_text(self):
        if getattr(self, "_kb_cache", None) is None:
            kb = self.engine.kb
            self._kb_cache = " ".join(c.text for c in getattr(kb, "chunks", [])) if hasattr(kb, "chunks") else ""
        return self._kb_cache

    def _call_llm(self, session, ctx, text, excerpts, style, evidence, note="", use_history=None, memory=None):
        """One model call with the minimal authorized view. Returns None (so the caller can fall back honestly) if the
        service fails or the reply claims evidence it never received. The failure reason is kept in the session memory."""
        if use_history is None:
            use_history = advice.FOLLOWUP_START.match(text) is not None or conversation.FOLLOWUP_CUE.search(text) is not None \
                          or bool((memory or {}).get("followup"))
        note = language.MODEL_NOTE.get(language.detect(text), "") + note
        history = session.history if use_history else []       # an unrelated question does not inherit old context
        try:
            out = self._llm_complete(self.settings, llm.build_messages(text, excerpts, ctx, history,
                                                                       styles.llm_instruction(style), evidence, note,
                                                                       scope=self.settings.scope))
        except llm.LLMError as exc:
            if memory is not None:
                memory["llm_error"] = str(exc)
            log.warning("llm_error %s", exc)
            return None
        except Exception:                                   # a provider bug must never take the game down
            if memory is not None:
                memory["llm_error"] = "The AI service failed unexpectedly."
            return None
        if self._CLAIMS_CHECKED.search(out) or not out.strip():
            self._metric(event="unsupported_claim_blocked")
            if memory is not None:
                memory["llm_error"] = "the model's answer was discarded"
            return None
        if memory is not None:
            memory.pop("llm_error", None)
        return out

    def _general_unavailable(self, memory, what="that"):
        n = memory.get("general_refusals", 0)
        memory["general_refusals"] = n + 1
        return responder.general_unavailable(self.settings.mode_reason, memory.get("llm_error"), repeat=n >= 1, what=what)

    def _grounded_answer(self, analysis, ctx, evidence, memory, session, text, meta, style=styles.DEFAULT, retry=False):
        engine = self.engine
        _, entities, hits, _notes = engine.interpret(language.to_english(text), memory, ctx.role, ctx.phase)
        if analysis.wants_simpler and memory.get("chunks"):
            self._metric(chunk_ids=memory["chunks"][:2], field="confused")
        llm_on = self.mode == "llm"
        mods = advice.modifiers(language.to_english(text))
        one = ("Answer in exactly one sentence. " if mods["one_sentence"] else "")
        lang = mods["language"] if mods["language"] and mods["language"] != "English" else None
        lang_note = (f"Write the reply in {lang}. Roman Urdu means Urdu written in Latin letters (not English, not Urdu script). " if lang else "")

        if retry and memory.get("chunks"):
            fresh = [h for h in hits if h.chunk.id not in memory["chunks"]]
            hits = fresh or hits

        general_task = advice.is_general_task(text)
        if general_task or (not analysis.wants_simpler and not analysis.wants_detail and not engine.is_about_camorra(analysis, entities, hits)):
            self._metric(event="off_topic")
            if self.settings.scope != "general":
                meta["kind"] = "off_topic"
                reply = (responder.OUT_OF_SCOPE_ROMAN_URDU if (lang == "Roman Urdu" or language.detect(text) == "roman_urdu")
                         else responder.OUT_OF_SCOPE)
                return reply, [], "off_topic", meta, reply
            if llm_on:
                out = self._call_llm(session, ctx, text, [], style, evidence,
                                     one + lang_note + "This is a general question. Answer it helpfully and do the task asked. Do not attribute anything to the CAMORRA rules unless it is in the excerpts.",
                                     memory=memory)
                if out is not None:
                    self._remember(memory, out, question=text)
                    return out, [], "general", {"mode": "llm", "sources": [], "kind": "answer"}, out
            meta["kind"] = "off_topic"
            reply = self._general_unavailable(memory)
            return reply, [], "off_topic", meta, reply

        intent = analysis.intent
        missing = advice.unsupported_feature(text, self._kb_text())
        if missing:
            self._metric(event="unanswerable")
            meta["kind"] = "no_answer"
            reply = (f"CAMORRA's rules don't mention anything like \"{missing}\", so I can't confirm it exists and I won't guess. "
                     "I can explain the roles, the night and day phases, voting and winning, if that helps.")
            return reply, [], intent, meta, reply
        confident = bool(hits) and (hits[0].score >= 0.12 or any(e.type != "ACTION" for e in entities))
        if not confident and not (analysis.wants_simpler and memory.get("chunks")):
            self._metric(event="unanswerable")
            if llm_on:
                out = self._call_llm(session, ctx, text, [h.chunk for h in hits[:3]], style, evidence,
                                     one + lang_note + "The rulebook may not cover this. If it is a CAMORRA rule you cannot confirm, say so; otherwise answer helpfully and label general Mafia-game conventions as such.",
                                     memory=memory)
                if out is not None:
                    self._remember(memory, out, question=text)
                    return out, [], intent, {"mode": "llm", "sources": [], "kind": "answer"}, out
            hint = ""
            if hits:
                hint = "The closest topics I know are: " + "; ".join(h.chunk.title for h in hits[:3]) + "."
            meta["kind"] = "no_answer"
            reply = responder.NO_ANSWER.format(hint=hint)
            return reply, [], intent, meta, reply

        if analysis.wants_simpler and not memory.get("chunks"):
            _, entities, hits, _ = engine.interpret("what should I do now", {}, ctx.role, ctx.phase)
            analysis.intent = "situation_guidance"

        vocab = engine.understanding.vocab
        offline_reply, used = responder.compose_offline(analysis, hits, ctx, memory, engine.kb, vocab, analysis.wants_detail,
                                                        styles.options(style))
        reply, source_ids, raw = offline_reply, used, offline_reply
        main_chunk = engine.kb.get(used[0]) if used else None
        summary = advice.one_sentence(responder.short_version(main_chunk)) if main_chunk else None

        if memory.get("last_reply") and offline_reply == memory["last_reply"] and not analysis.wants_simpler:
            alt = [h for h in hits[1:] if h.chunk.id not in used]
            if alt and not llm_on:
                offline_reply, used = responder.compose_offline(analysis, alt, ctx, memory, engine.kb, vocab, analysis.wants_detail,
                                                                styles.options(style))
                reply, source_ids, raw = offline_reply, used, offline_reply
                main_chunk = engine.kb.get(used[0]) if used else None
                summary = advice.one_sentence(responder.short_version(main_chunk)) if main_chunk else None
            elif not llm_on:
                return responder.SAME_ANSWER, [], intent, self._meta(), responder.SAME_ANSWER

        if lang and not llm_on:
            reply = responder.language_unavailable(lang, self.settings.mode_reason)
            return reply, [], intent, self._meta(), reply

        if llm_on and hits:
            excerpts = [h.chunk for h in hits[:3]]
            if analysis.wants_simpler and memory.get("chunks"):
                prev = [engine.kb.get(c) for c in memory["chunks"][:2] if engine.kb.get(c)]
                excerpts = prev + [c for c in excerpts if c not in prev]
            note = ("The player rejected your previous answer; give a different, better one. " if retry else "") + one + lang_note
            out = self._call_llm(session, ctx, text, excerpts[:4], style, evidence, note, memory=memory)
            if out is not None:
                reply, raw = out, out
                source_ids = [c.id for c in excerpts[:2]]
                meta = {"mode": "llm", "sources": [], "kind": "answer"}
                summary = None
            else:
                log.warning("llm_unavailable reason=%s", memory.get("llm_error"))    # developer log only, never shown to players
                reply = responder.UNAVAILABLE
                meta = {"mode": "rules", "sources": [], "kind": "chat"}
                source_ids, summary = [], None

        meta["sources"] = [engine.kb.get(i).label for i in source_ids if engine.kb.get(i)]
        update_memory(memory, entities, source_ids[:2], intent)
        memory["chunks"] = list(source_ids[:2]) or memory.get("chunks", [])
        self._remember(memory, raw, summary, question=text)
        self._metric(intent=intent, chunk_ids=source_ids[:2], field="asked")
        return reply, source_ids, intent, meta, raw
