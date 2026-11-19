// Runs the REAL static/chatbot.js against a fake DOM and a fake server.
const fs = require("fs"), path = require("path"), vm = require("vm"), assert = require("assert");
const { makeWorld } = require("./fakedom");
const SRC = fs.readFileSync(path.join(__dirname, "../../static/chatbot.js"), "utf8");
const tick = () => new Promise(r => setImmediate(r));
const flush = async () => { for (let i = 0; i < 6; i++) await tick(); };

function boot(initialStore) {
  const world = makeWorld();
  ["setup", "roleAssignment", "rolePass", "night", "gameOver"].forEach((id, i) => world.addPanel(id, i !== 0));
  const server = { styles: undefined, styleSeen: null, sessions: 0, closed: [], sent: [], hold: null, status: 200, nextStatus: null, deferSession: null };
  const sessionsOpen = [];
  async function fetchStub(url, opts) {
    const body = opts.body ? JSON.parse(opts.body) : {};
    const reply = (status, data) => ({ ok: status < 400, status, json: async () => data });
    if (url.endsWith("/session")) {
      const id = "S" + (++server.sessions);
      if (server.deferSession) await server.deferSession;
      sessionsOpen.push(id);
      return reply(server.status === 403 ? 403 : 200, server.status === 403 ? { detail: { message: "nope" } } : { session_id: id, mode: "offline", styles: server.styles });
    }
    if (url.endsWith("/close")) { server.closed.push(body.session_id); return reply(200, { closed: true }); }
    if (url.endsWith("/feedback")) { server.sent.push(["fb", body]); return reply(200, { recorded: true }); }
    server.sent.push(body);
    if (server.hold) await server.hold;
    server.styleSeen = body.style;
    if (server.nextStatus) { const s = server.nextStatus; server.nextStatus = null; return reply(s, { detail: { code: "x", message: "server said " + s } }); }
    return reply(200, { reply: "echo: " + body.message, message_id: server.sent.length, mode: "rules", sources: ["Roles › Doctor"] });
  }
  const storageTouched = [], store = Object.assign({}, initialStore || {});
  const trap = n => new Proxy({}, { get() { storageTouched.push(n); return () => null; }, set() { storageTouched.push(n); return true; } });
  const ls = { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } };
  const win = { addEventListener(t, f) { (win._l = win._l || {})[t] = f; }, localStorage: ls };
  const ctx = {
    window: win, document: world.document, fetch: fetchStub, MutationObserver: world.MutationObserver, AbortController,
    navigator: { sendBeacon: (u, b) => { server.closed.push("beacon:" + u); return true; } }, Blob: class { constructor(p) { this.p = p; } },
    console, setTimeout, localStorage: ls, sessionStorage: trap("sessionStorage"), indexedDB: trap("indexedDB"),
  };
  ctx.window.document = world.document;
  vm.runInNewContext(SRC, ctx);
  const fab = world.document.getElementById("camorraChatButton"), panel = world.document.getElementById("camorraChatPanel");
  const input = panel.querySelectorAll("camorra-chat-input")[0];
  const gear = panel.querySelectorAll("camorra-chat-gear")[0], settings = panel.querySelectorAll("camorra-chat-settings")[0];
  return { world, server, fab, panel, input, storageTouched, win, store, gear, settings,
    msgs: () => panel.querySelectorAll("camorra-chat-messages")[0],
    send: panel.querySelectorAll("camorra-chat-send")[0], close: panel.querySelectorAll("camorra-chat-close")[0],
    texts: () => panel.querySelectorAll("camorra-chat-messages")[0].children.map(c => c.textContent) };
}

const tests = [];
const t = (name, fn) => tests.push([name, fn]);

t("button uses the existing logo file with the space encoded", async () => {
  const a = boot(); const img = a.fab.children[0];
  assert.strictEqual(img.src, "/static/chatbot%20logo.png");
  assert.ok(!a.fab.textContent.match(/[\u{1F300}-\u{1FAFF}]/u), "no emoji icon");
  assert.strictEqual(a.panel.hidden, true);
});

t("click opens panel, Enter sends, answer shown, X resets everything", async () => {
  const a = boot();
  a.fab.click(); await flush();
  assert.strictEqual(a.panel.hidden, false);
  a.input.value = "What does the Doctor do?";
  const ev = a.input.dispatch("keydown", { key: "Enter", shiftKey: false });
  assert.ok(ev.defaultPrevented, "Enter must not submit anything");
  assert.ok(ev.propagationStopped, "keystrokes must not reach game shortcuts");
  await flush();
  assert.ok(a.texts().some(x => x.includes("echo: What does the Doctor do?")));
  assert.strictEqual(a.input.value, "");
  a.close.click(); await flush();
  assert.strictEqual(a.panel.hidden, true);
  assert.strictEqual(a.msgs().children.length, 0, "transcript cleared");
  assert.deepStrictEqual(a.server.closed, ["S1"], "server told to destroy the chat");
  // Player B opens a fresh chat
  a.fab.click(); await flush();
  const visible = a.texts().join("|");
  assert.ok(!visible.includes("Doctor do"), "previous conversation must not reappear");
  assert.strictEqual(a.msgs().children.length, 1, "only the welcome notice");
});

t("a late answer after X never appears in the next chat", async () => {
  const a = boot(); let release; a.server.hold = new Promise(r => (release = r));
  a.fab.click(); await flush();
  a.input.value = "secret question for player A"; a.send.click(); await flush();
  a.close.click(); await flush();                              // Player A presses X while waiting
  a.server.hold = null; a.fab.click(); await flush();           // Player B opens the chat
  release(); await flush();                                     // A's answer finally arrives
  const all = a.texts().join("|");
  assert.ok(!all.includes("echo:"), "late reply leaked into B's chat: " + all);
  assert.ok(!all.includes("secret question"));
});

t("closing while the session is still being created does not leave a live session behind", async () => {
  const a = boot(); let release; a.server.deferSession = new Promise(r => (release = r));
  a.fab.click(); await tick();
  a.close.click(); await tick();
  release(); await flush();
  assert.ok(a.server.closed.includes("S1"), "session created after X must be destroyed immediately");
});

t("screen change (new player / phase) resets an open chat", async () => {
  const a = boot(); a.fab.click(); await flush();
  a.input.value = "hello"; a.send.click(); await flush();
  assert.ok(a.texts().length >= 2);
  a.world.showOnly("night"); await flush();
  assert.strictEqual(a.panel.hidden, true);
  assert.strictEqual(a.msgs().children.length, 0);
  assert.ok(a.server.closed.includes("S1"));
  assert.strictEqual(a.fab.hidden, false, "button still available on a normal screen");
});

t("role card reveal inside the same screen also resets the chat", async () => {
  const a = boot(); const card = a.world.document.createElement("div"); card.setAttribute("id", "roleRevealCard"); card.className = "hidden";
  a.world.document.body.appendChild(card);
  a.fab.click(); await flush(); card.classList.toggle("hidden", false); await flush();
  assert.strictEqual(a.panel.hidden, true);
});

t("results screen hides the button and the panel", async () => {
  const a = boot(); a.fab.click(); await flush();
  a.world.showOnly("gameOver"); await flush();
  assert.strictEqual(a.fab.hidden, true); assert.strictEqual(a.panel.hidden, true);
  a.world.showOnly("setup"); await flush();
  assert.strictEqual(a.fab.hidden, false, "button returns for the next game");
});

t("410 from the server clears the transcript and starts fresh on the next question", async () => {
  const a = boot(); a.fab.click(); await flush();
  a.server.nextStatus = 410; a.input.value = "first"; a.send.click(); await flush();
  const shown = a.texts().join("|");
  assert.ok(shown.includes("cleared"), shown); assert.ok(!shown.includes("first"), "old question must not stay visible");
  a.input.value = "second"; a.send.click(); await flush();
  assert.ok(a.texts().some(x => x.includes("echo: second")));
  assert.ok(a.server.sessions >= 2, "a new session was opened");
});

t("errors are shown, loading indicator is removed, input re-enabled", async () => {
  const a = boot(); a.fab.click(); await flush();
  a.server.nextStatus = 429; a.input.value = "x"; a.send.click(); await flush();
  assert.ok(a.texts().some(x => x.includes("server said 429")));
  assert.strictEqual(a.input.disabled, false); assert.strictEqual(a.send.disabled, false);
  assert.ok(!a.msgs().children.some(c => c.querySelectorAll("camorra-typing").length), "no stuck spinner");
});

t("loading indicator is shown while waiting", async () => {
  const a = boot(); a.fab.click(); await flush(); let release; a.server.hold = new Promise(r => (release = r));
  a.input.value = "hi"; a.send.click(); await flush();
  assert.ok(a.msgs().children.some(c => c.querySelectorAll("camorra-typing").length === 1));
  assert.strictEqual(a.send.disabled, true);
  release(); await flush();
  assert.strictEqual(a.send.disabled, false);
});

t("double sends are ignored while busy; empty messages are ignored", async () => {
  const a = boot(); a.fab.click(); await flush(); let release; a.server.hold = new Promise(r => (release = r));
  a.input.value = "one"; a.send.click(); await flush(); a.input.value = "two"; a.send.click(); await flush();
  release(); await flush();
  assert.strictEqual(a.server.sent.filter(x => x.message).length, 1);
  a.input.value = "   "; a.send.click(); await flush();
  assert.strictEqual(a.server.sent.filter(x => x.message).length, 1);
});

t("Escape closes and clears; unload closes via beacon", async () => {
  const a = boot(); a.fab.click(); await flush();
  a.input.dispatch("keydown", { key: "Escape" }); await flush();
  assert.strictEqual(a.panel.hidden, true);
  a.fab.click(); await flush(); a.win._l.pagehide(); await flush();
  assert.ok(a.server.closed.some(x => String(x).startsWith("beacon:")));
});

t("only the chosen answer style is stored; never chat text, ids or cookies; no innerHTML", async () => {
  const a = boot(); a.fab.click(); await flush(); a.input.value = "my private question"; a.send.click(); await flush();
  a.gear.click(); a.settings.querySelectorAll("camorra-style-option").find(b => b.getAttribute("data-style") === "robotic").click(); await flush();
  a.close.click(); await flush();
  assert.deepStrictEqual(Object.keys(a.store), ["camorra_chat_style"]);
  assert.strictEqual(a.store.camorra_chat_style, "robotic");
  assert.ok(!JSON.stringify(a.store).includes("private"), "no chat text in storage");
  assert.deepStrictEqual(a.storageTouched, []);
  const code = SRC.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
  assert.ok(!/innerHTML|outerHTML|insertAdjacentHTML|document\.cookie|sessionStorage|indexedDB/.test(code));
  assert.strictEqual((code.match(/localStorage/g) || []).length, 2, "localStorage appears only in the style preference helper");
});

t("settings: gear opens the style list, choosing a style is sent with the next message and remembered", async () => {
  const a = boot(); a.fab.click(); await flush();
  assert.strictEqual(a.settings.hidden, true);
  a.gear.click(); assert.strictEqual(a.settings.hidden, false);
  const opts = a.settings.querySelectorAll("camorra-style-option");
  assert.ok(opts.length >= 7, "at least 7 modes offered");
  ["friendly", "personal", "robotic", "beginner", "concise", "detailed", "noir"].forEach(id => assert.ok(opts.some(b => b.getAttribute("data-style") === id), id));
  opts.find(b => b.getAttribute("data-style") === "noir").click(); await flush();
  assert.strictEqual(a.settings.hidden, true, "menu closes after choosing");
  assert.strictEqual(a.panel.getAttribute("data-style"), "noir");
  assert.ok(!a.texts().some(x => x.includes("Answer style:")), "no developer-style notice appears in the chat");
  a.input.value = "hi"; a.send.click(); await flush();
  assert.strictEqual(a.server.styleSeen, "noir");
  assert.ok(a.panel.querySelectorAll("camorra-chat-title")[0].textContent.includes("Noir narrator"));
});

t("a saved style is restored on the next page load; unknown saved values fall back to friendly", async () => {
  const saved = boot({ camorra_chat_style: "concise" });
  assert.strictEqual(saved.panel.getAttribute("data-style"), "concise");
  const evil = boot({ camorra_chat_style: "evil<script>alert(1)</script>" });
  assert.strictEqual(evil.panel.getAttribute("data-style"), "friendly");
  assert.strictEqual(evil.store.camorra_chat_style, "friendly", "the bad value is replaced");
  const none = boot();
  assert.strictEqual(none.panel.getAttribute("data-style"), "friendly");
});

t("closing the chat also closes the settings menu and keeps nothing of the conversation", async () => {
  const a = boot(); a.fab.click(); await flush(); a.gear.click(); assert.strictEqual(a.settings.hidden, false);
  a.close.click(); await flush(); assert.strictEqual(a.settings.hidden, true);
});

t("feedback buttons send a rating once", async () => {
  const a = boot(); a.fab.click(); await flush(); a.input.value = "hi"; a.send.click(); await flush();
  const kids = a.msgs().children;
  const idx = kids.findIndex(c => c.textContent.includes("echo:"));
  const bot = kids[idx], rate = kids[idx + 1];
  assert.ok(!bot.textContent.includes("Was this helpful"), "feedback is not part of the answer text");
  assert.ok(!bot.textContent.includes("Based on"), "no source labels");
  const buttons = rate.all().filter(e => e.tagName === "BUTTON");
  buttons[1].click(); await flush();
  assert.strictEqual(a.server.sent.filter(x => x[0] === "fb").length, 1);
  assert.ok(rate.textContent.includes("Thanks"));
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("PASS " + name); } catch (e) { failed++; console.log("FAIL " + name + "\n     " + (e.message || e)); }
  }
  console.log(`\n${tests.length - failed}/${tests.length} chat UI tests passed`);
  process.exit(failed ? 1 : 0);
})();
