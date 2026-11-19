/* CAMORRA AI Companion (front end).
 *
 * PRIVACY RULES IMPLEMENTED HERE
 *  - Chat messages and the session id are never written to localStorage / sessionStorage / IndexedDB / cookies (only the chosen
 *    answer style is remembered in localStorage). The session id and
 *    the messages live only in JavaScript variables and in the DOM of the open panel.
 *  - Closing the panel (X) really resets: DOM cleared, input cleared, pending request aborted, a
 *    "generation" counter bumped so any late answer is ignored, and the server is told to destroy the chat.
 *  - Any change of game screen (pass the device, next voter, new phase ...) also resets the chat.
 *  - The panel is hidden on the results screen.
 * The game's own script (game.js) is not modified or touched; screen changes are observed from the outside.
 */
(function () {
  "use strict";

  var API = "/api/ai/chat";
  var LOGO = "/static/chatbot%20logo.png";
  var WELCOME = "Hi! I'm the CAMORRA AI Companion. Ask me anything about CAMORRA: how to play, the roles, what to do on your turn, voting, strategy, or what a button does. " +
                "I can't reveal anyone's secret role or choice.";

  /* ------------------------------------------------------------------ controller (pure logic) */
  var STYLE_KEY = "camorra_chat_style";           // the ONLY thing this widget ever stores: the chosen answer style
  var STYLES_FALLBACK = [
    { id: "friendly", label: "Friendly", description: "Warm and encouraging. The default." },
    { id: "personal", label: "Personal", description: "Talks to you directly, like your own game companion." },
    { id: "robotic", label: "Robotic", description: "Machine-style status messages." },
    { id: "beginner", label: "Beginner", description: "Very simple words and short sentences." },
    { id: "concise", label: "Concise", description: "The shortest answer that still helps." },
    { id: "detailed", label: "Detailed", description: "Full, step-by-step explanations." },
    { id: "noir", label: "Noir narrator", description: "Dark and atmospheric, like the game itself." }
  ];

  var prefs = {
    get: function () { try { return window.localStorage.getItem(STYLE_KEY); } catch (e) { return null; } },
    set: function (v) { try { window.localStorage.setItem(STYLE_KEY, v); } catch (e) {} }
  };

  function ChatController(api, view) {
    this.api = api;
    this.view = view;
    this.styles = STYLES_FALLBACK;
    this.style = "friendly";
    this.sessionId = null;
    this.generation = 0;     // bumped on every reset; answers from an older generation are discarded
    this.abort = null;
    this.isOpen = false;
    this.busy = false;
    this.available = true;
  }

  ChatController.prototype._known = function (id) {
    for (var i = 0; i < this.styles.length; i++) if (this.styles[i].id === id) return this.styles[i];
    return null;
  };

  /** Switch the answer style. Only the style id is remembered; chat content never is. */
  ChatController.prototype.setStyle = function (id, announce) {
    var s = this._known(id) || this._known("friendly");
    this.style = s.id;
    prefs.set(s.id);
    this.view.setStyle(s);
  };

  ChatController.prototype.loadSavedStyle = function () {
    var saved = prefs.get();
    this.setStyle(saved && this._known(saved) ? saved : "friendly", false);
  };

  ChatController.prototype._newAbort = function () {
    if (this.abort) { try { this.abort.abort(); } catch (e) {} }
    this.abort = (typeof AbortController !== "undefined") ? new AbortController() : null;
    return this.abort ? this.abort.signal : undefined;
  };

  ChatController.prototype.openPanel = async function () {
    if (!this.available || this.isOpen) return;
    var gen = ++this.generation;
    this.isOpen = true;
    this.view.clear();
    this.view.show();
    this.view.addNotice(WELCOME);
    this.view.focus();
    await this._startSession(gen);
  };

  ChatController.prototype._startSession = async function (gen) {
    var res = await this.api.openSession(this._newAbort());
    if (gen !== this.generation) {                       // closed or reset while we were waiting
      if (res && res.ok && res.data && res.data.session_id) this.api.close(res.data.session_id);
      return false;
    }
    if (res.ok) {
      this.sessionId = res.data.session_id;
            if (res.data.styles && res.data.styles.length) {          // the server's list is the source of truth
        this.styles = res.data.styles;
        this.view.setStyleList(this.styles, this.style);
        if (!this._known(this.style)) this.setStyle("friendly", false);
      }
      return true;
    }
    if (res.status === 403) { this.setAvailable(false); return false; }
    this.view.addError(res.message || "The AI Companion could not start. Please try again.");
    return false;
  };

  /** The X button, screen changes, page unload: a REAL reset, not just hiding the panel. */
  ChatController.prototype.closePanel = function (reason, useBeacon) {
    this.generation++;                                   // invalidates every in-flight answer
    if (this.abort) { try { this.abort.abort(); } catch (e) {} this.abort = null; }
    var old = this.sessionId;
    this.sessionId = null;
    this.isOpen = false;
    this.busy = false;
    this.view.setLoading(false);
    this.view.clear();
    this.view.clearInput();
    this.view.closeSettings();
    this.view.hide();
    if (old) this.api.close(old, !!useBeacon);
  };

  ChatController.prototype.onScreenChange = function () {
    if (this.isOpen || this.sessionId) this.closePanel("screen-change");
  };

  ChatController.prototype.setAvailable = function (ok) {
    this.available = ok;
    this.view.setFabVisible(ok);
    if (!ok && (this.isOpen || this.sessionId)) this.closePanel("unavailable");
  };

  ChatController.prototype.send = async function (rawText) {
    var text = (rawText || "").trim();
    if (!text || this.busy || !this.isOpen) return;
    var gen = this.generation;
    this.busy = true;
    this.view.addUser(text);
    this.view.clearInput();
    this.view.setLoading(true);

    if (!this.sessionId) {
      var started = await this._startSession(gen);
      if (gen !== this.generation) return;
      if (!started) { this.busy = false; this.view.setLoading(false); return; }
    }
    var res = await this.api.send(this.sessionId, text, this._newAbort(), this.style);
    if (gen !== this.generation) return;                 // late answer from a closed / reset chat: dropped
    this.busy = false;
    this.view.setLoading(false);

    if (res.ok) {
      this.view.addBot(res.data.reply, { messageId: res.data.message_id });
    } else if (res.status === 410) {                     // chat expired (turn changed / timeout / closed)
      this.sessionId = null;
      this.generation++;
      this.view.clear();
      this.view.addNotice("This chat was cleared because the game moved on to a different screen or player. Ask again to start a fresh private chat.");
      this.view.focus();
    } else if (res.status === 403) {
      this.setAvailable(false);
    } else {
      this.view.addError(res.message || "Something went wrong. Please try again.");
    }
    this.view.focus();
  };

  ChatController.prototype.rate = async function (messageId, helpful) {
    if (!this.sessionId) return;
    await this.api.feedback(this.sessionId, messageId, helpful);
  };

  /* ------------------------------------------------------------------ network layer */
  function jsonFetch(url, method, body, signal) {
    var opts = { method: method, cache: "no-store", credentials: "same-origin", signal: signal,
                 headers: { "Content-Type": "application/json" } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        var d = data && data.detail;
        var message = d && typeof d === "object" ? d.message : (typeof d === "string" ? d : undefined);
        return { ok: r.ok, status: r.status, data: data, message: message };
      });
    }).catch(function (err) {
      if (err && err.name === "AbortError") return { ok: false, status: 0, aborted: true, message: "" };
      return { ok: false, status: 0, message: "I can't reach the game server right now. Please check that it is running." };
    });
  }

  var realApi = {
    openSession: function (signal) { return jsonFetch(API + "/session", "POST", {}, signal); },
    send: function (sid, message, signal, style) { return jsonFetch(API, "POST", { session_id: sid, message: message, style: style || "friendly" }, signal); },
    feedback: function (sid, id, helpful) { return jsonFetch(API + "/feedback", "POST", { session_id: sid, message_id: id, helpful: helpful }); },
    close: function (sid, beacon) {
      var payload = JSON.stringify({ session_id: sid });
      if (beacon && navigator.sendBeacon) {
        try { navigator.sendBeacon(API + "/close", new Blob([payload], { type: "application/json" })); return; } catch (e) {}
      }
      try { fetch(API + "/close", { method: "POST", keepalive: true, cache: "no-store", headers: { "Content-Type": "application/json" }, body: payload }); } catch (e) {}
    }
  };

  /* ------------------------------------------------------------------ DOM view */
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;       // textContent only: never innerHTML
    return e;
  }

  function gearIcon() {
    var ns = "http://www.w3.org/2000/svg";
    if (!document.createElementNS) return document.createTextNode("\u2699");
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2"); svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round");
    var c = document.createElementNS(ns, "circle"); c.setAttribute("cx", "12"); c.setAttribute("cy", "12"); c.setAttribute("r", "3"); svg.appendChild(c);
    var p = document.createElementNS(ns, "path");
    p.setAttribute("d", "M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z");
    svg.appendChild(p);
    return svg;
  }

  function buildView(controllerRef) {
    var fab = el("button", "camorra-chat-fab");
    fab.type = "button"; fab.id = "camorraChatButton";
    fab.setAttribute("aria-label", "Open the CAMORRA AI Companion"); fab.setAttribute("aria-expanded", "false");
    var fabImg = el("img"); fabImg.src = LOGO; fabImg.alt = ""; fab.appendChild(fabImg);

    var panel = el("section", "camorra-chat-panel");
    panel.id = "camorraChatPanel"; panel.hidden = true;
    panel.setAttribute("role", "dialog"); panel.setAttribute("aria-label", "CAMORRA AI Companion");

    var header = el("div", "camorra-chat-header");
    var hImg = el("img"); hImg.src = LOGO; hImg.alt = "";
    var title = el("div", "camorra-chat-title");
    var titleName = el("strong", "", "CAMORRA AI Companion");
    var titleMode = el("span", "", "Private chat");
    title.appendChild(titleName); title.appendChild(titleMode);
    var gearBtn = el("button", "camorra-chat-gear");
    gearBtn.type = "button"; gearBtn.setAttribute("aria-label", "Chat settings: answer style"); gearBtn.setAttribute("aria-expanded", "false");
    gearBtn.title = "Chat settings";
    gearBtn.appendChild(gearIcon());
    var closeBtn = el("button", "camorra-chat-close", "\u00D7");
    closeBtn.type = "button"; closeBtn.setAttribute("aria-label", "Close and clear this chat");
    header.appendChild(hImg); header.appendChild(title); header.appendChild(gearBtn); header.appendChild(closeBtn);

    var settings = el("div", "camorra-chat-settings"); settings.hidden = true;
    settings.setAttribute("role", "radiogroup"); settings.setAttribute("aria-label", "Answer style");
    var settingsTitle = el("div", "camorra-settings-title", "Answer style");
    var settingsHint = el("div", "camorra-settings-hint", "How should I talk to you? This changes my tone and length, never the rules or what I'm allowed to reveal.");
    var optionsBox = el("div", "camorra-settings-options");
    settings.appendChild(settingsTitle); settings.appendChild(settingsHint); settings.appendChild(optionsBox);

    var messages = el("div", "camorra-chat-messages");
    messages.setAttribute("role", "log"); messages.setAttribute("aria-live", "polite");

    var footer = el("div", "camorra-chat-footer");
    footer.appendChild(el("p", "camorra-chat-privacy", "Private: this chat is cleared when you close it or the turn changes."));
    var row = el("div", "camorra-chat-inputrow");
    var input = el("input", "camorra-chat-input");
    input.type = "text"; input.maxLength = 500; input.autocomplete = "off"; input.spellcheck = true;
    input.placeholder = "Ask about the rules\u2026"; input.setAttribute("aria-label", "Your question");
    var sendBtn = el("button", "camorra-chat-send", "SEND");
    sendBtn.type = "button";
    row.appendChild(input); row.appendChild(sendBtn); footer.appendChild(row);

    panel.appendChild(header); panel.appendChild(settings); panel.appendChild(messages); panel.appendChild(footer);
    document.body.appendChild(fab); document.body.appendChild(panel);

    var typingNode = null, currentLabel = "Friendly", currentMode = "rules", chooseHandler = function () {}, optionNodes = [];
    function scroll() { messages.scrollTop = messages.scrollHeight; }
    function subtitle() { titleMode.textContent = "Private chat \u00B7 " + currentLabel; }
    function buildOptions(list, selectedId) {
      while (optionsBox.firstChild) optionsBox.removeChild(optionsBox.firstChild);
      optionNodes = [];
      list.forEach(function (s) {
        var b = el("button", "camorra-style-option" + (s.id === selectedId ? " is-selected" : ""));
        b.type = "button"; b.setAttribute("role", "radio"); b.setAttribute("aria-checked", s.id === selectedId ? "true" : "false");
        b.setAttribute("data-style", s.id);
        b.appendChild(el("strong", "", s.label)); b.appendChild(el("span", "", s.description));
        b.addEventListener("click", function () { chooseHandler(s.id); });
        optionsBox.appendChild(b); optionNodes.push(b);
      });
    }
    buildOptions(STYLES_FALLBACK, "friendly");

    var view = {
      show: function () { panel.hidden = false; fab.setAttribute("aria-expanded", "true"); },
      hide: function () { panel.hidden = true; fab.setAttribute("aria-expanded", "false"); },
      clear: function () { while (messages.firstChild) messages.removeChild(messages.firstChild); typingNode = null; },
      clearInput: function () { input.value = ""; },
      focus: function () { try { input.focus(); } catch (e) {} },
      setFabVisible: function (v) { fab.hidden = !v; if (!v) panel.hidden = true; },
      setMode: function (m) { currentMode = m; subtitle(); },
      setStyle: function (s) {
        currentLabel = s.label; subtitle(); panel.setAttribute("data-style", s.id);
        optionNodes.forEach(function (b) {
          var on = b.getAttribute("data-style") === s.id;
          b.className = "camorra-style-option" + (on ? " is-selected" : ""); b.setAttribute("aria-checked", on ? "true" : "false");
        });
      },
      setStyleList: function (list, selectedId) { buildOptions(list, selectedId); },
      onChooseStyle: function (fn) { chooseHandler = fn; },
      toggleSettings: function () { settings.hidden = !settings.hidden; gearBtn.setAttribute("aria-expanded", settings.hidden ? "false" : "true"); },
      closeSettings: function () { settings.hidden = true; gearBtn.setAttribute("aria-expanded", "false"); },
      addUser: function (t) { messages.appendChild(el("div", "camorra-msg user", t)); scroll(); },
      addNotice: function (t) { messages.appendChild(el("div", "camorra-msg notice", t)); scroll(); },
      addError: function (t) { messages.appendChild(el("div", "camorra-msg error", t)); scroll(); },
      addBot: function (t, info) {
        var box = el("div", "camorra-msg bot"), rateNode = null;
        box.appendChild(document.createTextNode(t));
        if (info && info.messageId) {
          var rate = el("div", "camorra-rate");
          rate.appendChild(el("span", "", "Was this helpful?"));
          var yes = el("button", "", "Yes"), no = el("button", "", "No");
          yes.type = no.type = "button";
          function done(h) {
            controllerRef().rate(info.messageId, h);
            while (rate.firstChild) rate.removeChild(rate.firstChild);
            rate.appendChild(el("span", "", "Thanks for the feedback."));
          }
          yes.addEventListener("click", function () { done(true); });
          no.addEventListener("click", function () { done(false); });
          rate.appendChild(yes); rate.appendChild(no); rateNode = rate;
        }
        messages.appendChild(box); if (rateNode) messages.appendChild(rateNode); scroll();
      },
      setLoading: function (on) {
        sendBtn.disabled = on; input.disabled = on;
        if (on && !typingNode) {
          typingNode = el("div", "camorra-msg bot");
          var dots = el("span", "camorra-typing");
          dots.appendChild(el("i")); dots.appendChild(el("i")); dots.appendChild(el("i"));
          typingNode.appendChild(dots); typingNode.setAttribute("aria-label", "The AI Companion is thinking");
          messages.appendChild(typingNode); scroll();
        } else if (!on && typingNode) {
          if (typingNode.parentNode) typingNode.parentNode.removeChild(typingNode);
          typingNode = null;
        }
        if (!on) { try { input.focus(); } catch (e) {} }
      },
      _nodes: { fab: fab, panel: panel, closeBtn: closeBtn, input: input, sendBtn: sendBtn, gearBtn: gearBtn, settings: settings }
    };
    return view;
  }

  /* ------------------------------------------------------------------ wiring */
  function activeScreenId() {
    var panels = document.querySelectorAll(".panel");
    for (var i = 0; i < panels.length; i++) if (!panels[i].classList.contains("hidden")) return panels[i].id;
    return "";
  }

  function start() {
    var controller = null;
    var view = buildView(function () { return controller; });
    controller = new ChatController(realApi, view);
    var n = view._nodes;

    n.fab.addEventListener("click", function () {
      if (controller.isOpen) controller.closePanel("fab"); else controller.openPanel();
    });
    n.closeBtn.addEventListener("click", function () { controller.closePanel("x"); });
    n.gearBtn.addEventListener("click", function () { view.toggleSettings(); });
    view.onChooseStyle(function (id) { controller.setStyle(id, true); view.closeSettings(); view.focus(); });
    controller.loadSavedStyle();
    n.sendBtn.addEventListener("click", function () { controller.send(n.input.value); });
    n.input.addEventListener("keydown", function (e) {
      e.stopPropagation();                                // keep typing away from any game shortcut
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); controller.send(n.input.value); }
      else if (e.key === "Escape") { e.preventDefault(); controller.closePanel("escape"); }
    });

    // Game screen changes (observed from outside; game.js is untouched)
    var lastScreen = activeScreenId();
    function applyScreen() {
      var now = activeScreenId();
      controller.onScreenChange();
      controller.setAvailable(now !== "gameOver");
      lastScreen = now;
    }
    var watch = ["roleRevealCard", "roleAssignmentStage"];
    var observer = new MutationObserver(function (records) {
      for (var i = 0; i < records.length; i++) {
        var t = records[i].target;
        if (t && t.classList && (t.classList.contains("panel") || watch.indexOf(t.id) !== -1)) { applyScreen(); return; }
      }
    });
    observer.observe(document.body, { subtree: true, attributes: true, attributeFilter: ["class"] });
    controller.setAvailable(lastScreen !== "gameOver");

    window.addEventListener("pagehide", function () { controller.closePanel("unload", true); });
    window.CamorraChat = controller;                      // handle for tests / debugging (holds no history)
  }

  if (typeof window !== "undefined") window.CamorraChatInternals = { ChatController: ChatController, WELCOME: WELCOME };
  if (typeof document !== "undefined" && typeof module === "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
  }
  if (typeof module !== "undefined") module.exports = { ChatController: ChatController, WELCOME: WELCOME };
})();
