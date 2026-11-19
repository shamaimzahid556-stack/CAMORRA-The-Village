// Runs the REAL static/sound.js against a fake audio engine and a manual clock.
const fs = require("fs"), path = require("path"), assert = require("assert");
const { makeWorld } = require("./fakedom");
const SRC = fs.readFileSync(path.join(__dirname, "../../static/sound.js"), "utf8");
const tick = () => new Promise(r => setImmediate(r));
const flush = async () => { for (let i = 0; i < 8; i++) await tick(); };

function loadModule() {
  const m = { exports: {} };
  new Function("module", "window", "document", SRC)(m, undefined, undefined);   // module mode: exports only, nothing auto-starts
  return m.exports;
}
const Sound = loadModule();

function rig(opts = {}) {
  const events = [];                // ordered log of what the audio engine was asked to do
  const live = new Set();           // sources currently playing
  const timers = []; let now = 0, wall = 1000, rnd = opts.random || (() => 0.1), failLoad = false;
  const store = { v: opts.stored || null };
  class Param { constructor() { this.value = 0; } setTargetAtTime(v) { this.value = v; } cancelScheduledValues() {} }
  const ctx = {
    currentTime: 0, state: "running", destination: {}, suspended: false,
    createGain() { return { gain: new Param(), connect() {}, disconnect() {} }; },
    createStereoPanner() { return { pan: { value: 0 }, connect() {}, disconnect() {} }; },
    createBufferSource() {
      const s = { buffer: null, loop: false, connect() {}, disconnect() {}, onended: null,
        start() { live.add(s); events.push(["start", s.buffer.name, s.loop]); },
        stop() { if (live.delete(s)) events.push(["stop", s.buffer.name]); } };
      return s;
    },
    resume() { ctx.suspended = false; events.push(["resume"]); }, suspend() { ctx.suspended = true; events.push(["suspend"]); },
  };
  const deps = {
    createContext: () => ctx,
    fetchBuffer: async (c, url) => { if (failLoad) throw new Error("404"); return { name: url.split("/").pop() }; },
    setTimeout: (f, ms) => { const t = { f, at: now + ms, id: timers.length + 1, live: true }; timers.push(t); return t.id; },
    clearTimeout: id => { const t = timers.find(x => x.id === id); if (t) t.live = false; },
    random: () => rnd(), now: () => wall, storage: { get: () => store.v, set: v => { store.v = v; (store.writes = store.writes || []).push(v); } },
  };
  const sound = new Sound.AmbientSound(deps);
  return {
    sound, events, live, store, ctx,
    names: () => [...live].map(s => s.buffer.name),
    beds: () => [...live].filter(s => s.loop).map(s => s.buffer.name),
    advance: async ms => { now += ms; for (const t of timers.filter(x => x.live && x.at <= now)) { t.live = false; t.f(); await flush(); } },
    wall: ms => { wall += ms; }, failLoads: v => (failLoad = v), setRandom: f => (rnd = f), pending: () => timers.filter(t => t.live).length,
    started: name => events.filter(e => e[0] === "start" && e[1] === name).length,
  };
}

const tests = [], t = (n, f) => tests.push([n, f]);

t("nothing plays before the first user gesture; then the right bed starts", async () => {
  const r = rig(); r.sound.setMode("night"); await flush();
  assert.deepStrictEqual(r.names(), [], "autoplay must wait for a gesture");
  r.sound.unlock(); await flush();
  assert.deepStrictEqual(r.beds(), ["night-ambience.wav"]);
  assert.ok(r.names().includes("night-fall.mp3"), "night-fall transition plays");
});

t("repeating the same mode never creates duplicate copies", async () => {
  const r = rig(); r.sound.unlock(); for (let i = 0; i < 12; i++) { r.sound.setMode("night"); } await flush();
  assert.strictEqual(r.started("night-ambience.wav"), 1);
  assert.strictEqual(r.started("night-fall.mp3"), 1);
  assert.deepStrictEqual(r.beds(), ["night-ambience.wav"]);
});

t("night -> day crossfades: one bed of each kind at most, old bed stopped, morning bell plays", async () => {
  const r = rig(); r.sound.unlock(); r.sound.setMode("night"); await flush();
  r.sound.setMode("day"); await flush();
  assert.ok(r.beds().includes("day-ambience.wav")); assert.strictEqual(r.started("morning-bell.mp3"), 1);
  await r.advance(5000);                                              // fade-out finished
  assert.deepStrictEqual(r.beds(), ["day-ambience.wav"], "night bed must be gone");
});

t("owl and wolf calls happen only at night, and stop when day starts", async () => {
  const r = rig(); r.sound.unlock(); r.sound.setMode("night"); await flush();
  await r.advance(13000);
  assert.strictEqual(r.started("owl-hoot.mp3") + r.started("wolf-howl.mp3"), 1, "first call after 6-12 s");
  await r.advance(40000);
  const calls = r.started("owl-hoot.mp3") + r.started("wolf-howl.mp3");
  assert.ok(calls >= 2);
  r.sound.setMode("day"); await flush(); const before = calls;
  await r.advance(120000);
  assert.strictEqual(r.started("owl-hoot.mp3") + r.started("wolf-howl.mp3"), before, "no owl/wolf during the day");
  assert.ok(!r.names().includes("owl-hoot.mp3") && !r.names().includes("wolf-howl.mp3"));
});

t("a wolf never howls twice in a row", async () => {
  const r = rig({ random: () => 0.99 }); r.sound.unlock(); r.sound.setMode("night"); await flush();
  const order = []; const spy = r.events.length;
  for (let i = 0; i < 6; i++) { await r.advance(40000); }
  const calls = r.events.filter(e => e[0] === "start" && /owl|wolf/.test(e[1])).map(e => e[1]);
  for (let i = 1; i < calls.length; i++) assert.ok(!(calls[i] === "wolf-howl.mp3" && calls[i - 1] === "wolf-howl.mp3"));
  assert.ok(calls.includes("wolf-howl.mp3") && calls.includes("owl-hoot.mp3"));
});

t("muting silences everything and unmuting restores exactly one bed without replaying the transition", async () => {
  const r = rig(); r.sound.unlock(); r.sound.setMode("night"); await flush(); await r.advance(13000);
  r.sound.setMuted(true);
  assert.deepStrictEqual(r.names(), [], "nothing audible when muted");
  assert.strictEqual(r.pending(), 0, "no pending owl/wolf timers while muted");
  r.sound.setMode("day"); await flush();                              // phase changes while muted: still silent
  assert.deepStrictEqual(r.names(), []);
  const nf = r.started("night-fall.mp3");
  r.sound.setMuted(false); await flush();
  assert.deepStrictEqual(r.beds(), ["day-ambience.wav"]);
  assert.strictEqual(r.started("night-fall.mp3"), nf);
});

t("game over fades everything out and no call happens afterwards", async () => {
  const r = rig(); r.sound.unlock(); r.sound.setMode("night"); await flush();
  r.sound.setMode(null); await flush(); await r.advance(6000);
  assert.deepStrictEqual(r.names(), [], "fully stopped after the fade");
  await r.advance(200000);
  assert.strictEqual(r.started("owl-hoot.mp3") + r.started("wolf-howl.mp3"), 0);
});

t("a new game after game over announces its first night again", async () => {
  const r = rig(); r.sound.unlock(); r.sound.setMode("night"); await flush(); r.sound.setMode(null); await flush(); await r.advance(6000);
  r.sound.setMode("night"); await flush();
  assert.strictEqual(r.started("night-fall.mp3"), 2);
});

t("rapid phase flapping ends with exactly one bed of the final mode", async () => {
  const r = rig(); r.sound.unlock();
  for (let i = 0; i < 20; i++) { r.sound.setMode(i % 2 ? "day" : "night"); if (i % 3 === 0) await flush(); }
  r.sound.setMode("night"); await flush(); await r.advance(10000);
  assert.deepStrictEqual(r.beds(), ["night-ambience.wav"]);
});

t("audio errors never throw and never break later playback", async () => {
  const r = rig(); r.failLoads(true); r.sound.unlock(); r.sound.setMode("night"); await flush();
  assert.deepStrictEqual(r.names(), []); assert.ok(r.sound.failed);
  r.failLoads(false); r.sound.setMode("day"); await flush();
  assert.deepStrictEqual(r.beds(), ["day-ambience.wav"]);
});

t("a slow download cannot start stale audio", async () => {
  const r = rig(); let release;
  const slow = new Promise(res => (release = res));
  r.sound.d.fetchBuffer = async (c, url) => { if (url.includes("night-ambience")) await slow; return { name: url.split("/").pop() }; };
  r.sound.unlock(); r.sound.setMode("night"); await flush();
  r.sound.setMode("day"); await flush();                              // phase moved on while the night file downloads
  release(); await flush();
  assert.deepStrictEqual(r.beds(), ["day-ambience.wav"], "late night bed must not start");
});

t("front page and role assignment play the DARK bed with wolf, creak and crow calls (never an owl)", async () => {
  const r = rig(); r.sound.unlock(); r.sound.setMode("dark"); await flush();
  assert.deepStrictEqual(r.beds(), ["dark-ambience.wav"]);
  assert.strictEqual(r.started("night-fall.mp3") + r.started("morning-bell.mp3"), 0, "dark mode has no entry sound");
  const picks = [0.1, 0.5, 0.9, 0.7, 0.2];
  for (const p of picks) { r.setRandom(() => p); await r.advance(30000); }
  const calls = r.events.filter(e => e[0] === "start" && /wolf|creak|crow/.test(e[1])).map(e => e[1]);
  assert.ok(calls.length >= 3, "calls happen: " + calls);
  assert.ok(!r.events.some(e => e[1] === "owl-hoot.mp3"), "no owl on the front page");
  for (let i = 1; i < calls.length; i++) assert.ok(!(calls[i] === "wolf-howl.mp3" && calls[i - 1] === "wolf-howl.mp3"));
});

t("voting / elimination play the heartbeat TENSION bed with a sting on entry and no random calls", async () => {
  const r = rig(); r.sound.unlock(); r.sound.setMode("day"); await flush(); r.sound.setMode("tension"); await flush();
  assert.ok(r.beds().includes("tension-loop.wav")); assert.strictEqual(r.started("role-reveal.mp3"), 1);
  await r.advance(6000); assert.deepStrictEqual(r.beds(), ["tension-loop.wav"]);
  r.sound.setMode("tension"); await flush(); assert.strictEqual(r.started("role-reveal.mp3"), 1, "no repeat sting while staying in the mode");
  assert.strictEqual(r.pending(), 0, "no random calls during the vote");
});

t("day has crows (not owl or wolf); night still has owl and wolf", async () => {
  const r = rig(); r.sound.unlock(); r.sound.setMode("day"); await flush(); await r.advance(60000);
  assert.ok(r.started("crow-caw.mp3") >= 1); assert.strictEqual(r.started("owl-hoot.mp3") + r.started("wolf-howl.mp3"), 0);
});

t("Civilians win: joyful music only, no horror calls, previous bed fades away", async () => {
  const r = rig(); r.sound.unlock(); r.sound.setMode("tension"); await flush(); r.sound.setMode("win-civilians"); await flush(); await r.advance(6000);
  assert.deepStrictEqual(r.beds(), ["win-civilians.mp3"]);
  await r.advance(120000);
  assert.deepStrictEqual(r.names().filter(n => /wolf|owl|crow|creak/.test(n)), []);
});

t("Mafia win: dark music bed, and nothing from the happy track", async () => {
  const r = rig(); r.sound.unlock(); r.sound.setMode("tension"); await flush(); r.sound.setMode("win-mafia"); await flush(); await r.advance(6000);
  assert.deepStrictEqual(r.beds(), ["win-mafia.mp3"]); assert.strictEqual(r.started("win-civilians.mp3"), 0);
});

t("button clicks: knock sound, throttled, reveal sting is never throttled, silent before the first gesture and when muted", async () => {
  const r = rig(); r.sound.click("click"); await flush(); assert.strictEqual(r.started("ui-click.mp3"), 0, "before the first gesture");
  r.sound.unlock(); await flush();
  r.sound.click("click"); await flush(); r.sound.click("click"); await flush();
  assert.strictEqual(r.started("ui-click.mp3"), 1, "two presses within 70 ms make one sound");
  r.wall(200); r.sound.click("click"); await flush(); assert.strictEqual(r.started("ui-click.mp3"), 2);
  r.sound.click("reveal"); r.sound.click("reveal"); await flush(); assert.strictEqual(r.started("role-reveal.mp3"), 2);
  r.sound.setMuted(true); assert.deepStrictEqual(r.names(), [], "muting stops a sting that is still playing");
  r.wall(500); r.sound.click("click"); await flush(); assert.strictEqual(r.started("ui-click.mp3"), 2, "no click sound while muted");
});

t("a failed click-sound download never throws", async () => {
  const r = rig(); r.sound.unlock(); await flush(); r.failLoads(true); r.sound.d.fetchBuffer = async () => { throw new Error("404"); };
  r.sound.cache = {}; r.sound.click("click"); await flush();
});

t("the screen map follows the game's phases", async () => {
  const M = Sound.MODE_BY_SCREEN;
  for (const s of ["setup", "roleAssignment", "rolePass"]) assert.strictEqual(M[s], "dark", s);
  for (const s of ["nightIntro", "nightPass", "night"]) assert.strictEqual(M[s], "night", s);
  for (const s of ["morning", "discussion"]) assert.strictEqual(M[s], "day", s);
  for (const s of ["votePass", "voting", "elimination"]) assert.strictEqual(M[s], "tension", s);
  assert.strictEqual(M.gameOver, "win");
  for (const mode of Object.values(M).filter(m => m !== "win")) assert.ok(Sound.BED[mode], "a bed exists for " + mode);
  for (const k of Object.values(Sound.BED).flatMap(b => [b.file, b.enter].filter(Boolean))) assert.ok(Sound.FILES[k], "file mapped for " + k);
});

t("only the on/off preference is stored, and it is restored", async () => {
  const r = rig(); r.sound.setMuted(true); r.sound.setMuted(false);
  assert.deepStrictEqual(r.store.writes, ["off", "on"]);
  const r2 = rig({ stored: "off" }); assert.strictEqual(r2.sound.muted, true);
  r2.sound.unlock(); r2.sound.setMode("night"); await flush();
  assert.deepStrictEqual(r2.names(), [], "stored mute preference respected");
});

t("tab hidden suspends audio, visible resumes it (unless muted)", async () => {
  const r = rig(); r.sound.unlock(); r.sound.visibility(true); assert.ok(r.ctx.suspended);
  r.sound.visibility(false); assert.ok(!r.ctx.suspended);
  r.sound.setMuted(true); r.sound.visibility(true); r.sound.visibility(false); assert.ok(r.ctx.suspended, "stays suspended while muted");
});

t("the real wiring: sound button, screen observer, first-click unlock, button knocks, winner music (fake DOM)", async () => {
  const world = makeWorld();
  ["setup", "roleAssignment", "night", "morning", "voting", "gameOver"].forEach((id, i) => world.addPanel(id, i !== 0));
  const roleBtn = world.document.createElement("button"); roleBtn.setAttribute("id", "showRoleButton"); world.document.body.appendChild(roleBtn);
  const plain = world.document.createElement("button"); world.document.body.appendChild(plain);
  const listeners = {};
  const win = { AudioContext: function () {}, addEventListener(t, f) { listeners[t] = f; }, removeEventListener() {} };
  const live = new Set(), started = [];
  const ctx = { currentTime: 0, destination: {}, createGain: () => ({ gain: { value: 0, setTargetAtTime() {}, cancelScheduledValues() {} }, connect() {}, disconnect() {} }),
    createBufferSource: () => { const s = { loop: false, connect() {}, disconnect() {}, start() { live.add(s); started.push(s.buffer.name); }, stop() { live.delete(s); } }; return s; },
    resume() {}, suspend() {} };
  const mod = { exports: {} };
  const doc = Object.assign(world.document, { hidden: false });
  new Function("module", "window", "document", "fetch", "MutationObserver", SRC)(mod, win, doc, async () => ({}), world.MutationObserver);
  let wall = 0;
  const deps = { createContext: () => ctx, fetchBuffer: async (c, u) => ({ name: u.split("/").pop() }), setTimeout: () => 0, clearTimeout() {},
                 random: () => 0.5, now: () => (wall += 500), storage: { get: () => null, set: () => {} } };
  const sound = mod.exports.start(deps);
  const btn = doc.getElementById("camorraSoundButton");
  assert.ok(btn && btn.getAttribute("aria-pressed") === "false");
  assert.strictEqual(live.size, 0, "front page: still waiting for a first interaction");
  listeners.pointerdown(); await flush();
  assert.ok([...live].some(s => s.buffer.name === "dark-ambience.wav"), "front page plays the dark bed after the first click");
  plain.click(); await flush(); assert.ok(started.includes("ui-click.mp3"), "any button makes the knock");
  roleBtn.click(); await flush(); assert.ok(started.includes("role-reveal.mp3"), "SHOW MY ROLE makes the sting");
  world.showOnly("night"); await flush(); assert.strictEqual(sound.bed.mode, "night");
  world.showOnly("voting"); await flush(); assert.strictEqual(sound.bed.mode, "tension");
  // game.js marks the winner on #gameOver BEFORE showing it: the music must follow the winner
  const g = doc.getElementById("gameOver"); g.classList.toggle("mafia-won", true); g.classList.toggle("civilians-won", false);
  assert.strictEqual(sound.bed.mode, "tension", "winner class alone (panel still hidden) changes nothing");
  world.showOnly("gameOver"); await flush(); assert.strictEqual(sound.bed.mode, "win-mafia");
  world.showOnly("setup"); await flush(); assert.strictEqual(sound.bed.mode, "dark");
  g.classList.toggle("mafia-won", false); g.classList.toggle("civilians-won", true);
  world.showOnly("gameOver"); await flush(); assert.strictEqual(sound.bed.mode, "win-civilians");
  btn.click(); await flush(); assert.strictEqual(sound.muted, true); assert.strictEqual(live.size, 0);
  assert.strictEqual(btn.getAttribute("aria-pressed"), "true");
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("PASS " + name); } catch (e) { failed++; console.log("FAIL " + name + "\n     " + (e.stack || e).split("\n").slice(0, 3).join("\n     ")); }
  }
  console.log(`\n${tests.length - failed}/${tests.length} sound tests passed`);
  process.exit(failed ? 1 : 0);
})();
