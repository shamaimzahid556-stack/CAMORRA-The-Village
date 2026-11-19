/* CAMORRA ambient sound: horror everywhere, except the Civilians' victory.
 *
 * Which sound plays is decided from the game's own screens, which follow the engine's phases:
 *   setup (front page) / role assignment            -> DARK     dark drone, cold wind, whispers, wolf / creak / crow calls
 *   night intro / night pass / night action         -> NIGHT    crickets, night air, owl + wolf calls, deep bell on entry
 *   morning / discussion                            -> DAY      eerie morning: wind, low drone, cold birds, crows, bell on entry
 *   voting / elimination                            -> TENSION  heartbeat + dissonant strings, sting on entry
 *   game over, Civilians won                        -> happy, joyful music: the nightmare is over
 *   game over, Mafia won                            -> dark music, evil laughter, wolves, thunder: everything has ended
 * Every button press makes a dark knock, and SHOW MY ROLE makes a sting. No timers decide the phase.
 * Timers are used only for the random calls (wolf, owl, crow, creak) inside a mode.
 *
 * Safety rules:
 *   - Audio only starts after the player's first click/tap/key (browser autoplay rules).
 *   - Exactly one bed (looping background) per mode; changing mode crossfades and stops the old bed.
 *   - Every request is guarded by an "epoch" counter so a slow download can never start stale audio.
 *   - Muting stops everything. Any audio error is swallowed: the game is never affected.
 *   - Only the on/off preference is stored (localStorage key "camorra_sound"), nothing about gameplay or chat.
 */
(function () {
  "use strict";

  var BASE = "/static/sounds/";
  var FILES = { dayBed: "day-ambience.wav", nightBed: "night-ambience.wav", darkBed: "dark-ambience.wav", tensionBed: "tension-loop.wav",
                owl: "owl-hoot.mp3", wolf: "wolf-howl.mp3", crow: "crow-caw.mp3", creak: "creak.mp3",
                morning: "morning-bell.mp3", nightfall: "night-fall.mp3", click: "ui-click.mp3", reveal: "role-reveal.mp3",
                winCivilians: "win-civilians.mp3", winMafia: "win-mafia.mp3" };
  // "win" is resolved to the winner's music when the results screen appears
  var MODE_BY_SCREEN = { setup: "dark", roleAssignment: "dark", rolePass: "dark", nightIntro: "night", nightPass: "night", night: "night",
                         morning: "day", discussion: "day", votePass: "tension", voting: "tension", elimination: "tension", gameOver: "win" };
  // gain: level of the looping bed. enter: one-shot played when the mode begins. calls: random one-shots while the mode lasts.
  var BED = {
    "dark": { file: "darkBed", gain: 0.30, enter: null, enterGain: 0,
              calls: { first: [5, 9], every: [10, 22], list: [{ k: "wolf", w: 0.55, gain: 0.5, norepeat: true }, { k: "creak", w: 0.25, gain: 0.4, norepeat: true }, { k: "crow", w: 0.20, gain: 0.45 }] } },
    "night": { file: "nightBed", gain: 0.34, enter: "nightfall", enterGain: 0.55,
               calls: { first: [6, 12], every: [14, 30], list: [{ k: "owl", w: 0.65, gain: 0.55 }, { k: "wolf", w: 0.35, gain: 0.5, norepeat: true }] } },
    "day": { file: "dayBed", gain: 0.50, enter: "morning", enterGain: 0.5,
             calls: { first: [8, 14], every: [16, 34], list: [{ k: "crow", w: 1, gain: 0.45 }] } },
    "tension": { file: "tensionBed", gain: 0.36, enter: "reveal", enterGain: 0.5, calls: null },
    "win-civilians": { file: "winCivilians", gain: 0.50, enter: null, enterGain: 0, calls: null },
    "win-mafia": { file: "winMafia", gain: 0.55, enter: null, enterGain: 0, calls: null }
  };
  var FADE_IN = 2.0, FADE_OUT = 1.6, MUTE_FADE = 0.15, CLICK_GAP_MS = 70;

  function AmbientSound(deps) {
    this.d = deps;                       // { createContext, fetchBuffer, setTimeout, clearTimeout, random, storage }
    this.ctx = null;
    this.master = null;
    this.unlocked = false;
    this.muted = false;
    this.desired = null;                 // mode the game wants right now
    this.lastStarted = undefined;        // mode whose bed was last started (decides transition sounds)
    this.epoch = 0;
    this.bed = null;                     // { mode, source, gain }
    this.fading = [];                    // beds that are fading out
    this.shots = [];                     // one-shots currently playing
    this.timer = null;
    this.lastShot = "";
    this.ui = [];                        // button / sting sounds currently playing
    this.lastClickAt = -1e9;
    this.now = deps.now || function () { return Date.now(); };
    this.failed = false;
    this.cache = {};
    this.onState = function () {};
    try { this.muted = deps.storage && deps.storage.get() === "off"; } catch (e) {}
  }

  AmbientSound.prototype._ensureContext = function () {
    if (this.ctx) return true;
    try {
      this.ctx = this.d.createContext();
      this.master = this.ctx.createGain();
      this.master.gain.value = this.muted ? 0 : 0.9;
      this.master.connect(this.ctx.destination);
      return true;
    } catch (e) { this.failed = true; this.ctx = null; return false; }
  };

  /** Called on the player's first interaction. */
  AmbientSound.prototype.unlock = function () {
    if (this.unlocked) return;
    this.unlocked = true;
    if (!this._ensureContext()) return;
    try { if (this.ctx.resume) this.ctx.resume(); } catch (e) {}
    this._load("click").catch(function () {});             // ready before the first button press is heard
    this._load("reveal").catch(function () {});
    this.apply();
  };

  AmbientSound.prototype.setMode = function (mode) {
    this.desired = mode || null;
    this.apply();
  };

  AmbientSound.prototype.setMuted = function (m) {
    this.muted = !!m;
    try { this.d.storage && this.d.storage.set(this.muted ? "off" : "on"); } catch (e) {}
    if (this.master && this.ctx) {
      try {
        var t = this.ctx.currentTime;
        this.master.gain.cancelScheduledValues(t);
        this.master.gain.setTargetAtTime(this.muted ? 0 : 0.9, t, MUTE_FADE);
      } catch (e) {}
    }
    if (this.muted) { this._stopEverything(); } else { this.apply(); }
    this.onState(this.muted);
  };

  AmbientSound.prototype._stopEverything = function () {
    this.epoch++;
    this._clearTimer();
    var beds = this.fading.concat(this.bed ? [this.bed] : []);
    this.bed = null; this.fading = [];
    beds.forEach(function (b) { this._hardStop(b); }, this);
    this.shots.forEach(function (s) { this._hardStop(s); }, this);
    this.shots = [];
    this.ui.forEach(function (s) { this._hardStop(s); }, this);
    this.ui = [];
  };

  AmbientSound.prototype._hardStop = function (obj) {
    try { obj.source.stop(); } catch (e) {}
    try { obj.source.disconnect && obj.source.disconnect(); } catch (e) {}
    try { obj.gain && obj.gain.disconnect && obj.gain.disconnect(); } catch (e) {}
    if (obj.killTimer) this.d.clearTimeout(obj.killTimer);
  };

  AmbientSound.prototype._clearTimer = function () {
    if (this.timer) { this.d.clearTimeout(this.timer); this.timer = null; }
  };

  AmbientSound.prototype.apply = function () {
    if (!this.unlocked || !this.ctx) return;           // waits for the first click
    if (this.muted) return;
    if (this.bed && this.bed.mode === this.desired) return;    // already playing the right bed: never duplicate
    this.epoch++;
    this._clearTimer();
    var epoch = this.epoch;
    var previous = this.bed;
    if (previous) this._fadeOut(previous);
    this.bed = null;
    this.shots.forEach(function (s) { this._fadeShot(s); }, this);   // night calls never bleed into the morning
    if (!this.desired) { this.lastStarted = undefined; return; }     // silence: setup, role assignment, game over
    var mode = this.desired;
    var announce = this.lastStarted !== mode;
    this._startBed(mode, epoch, announce);
  };

  AmbientSound.prototype._fadeOut = function (bed) {
    var self = this;
    try {
      var t = this.ctx.currentTime;
      bed.gain.gain.cancelScheduledValues(t);
      bed.gain.gain.setTargetAtTime(0, t, FADE_OUT / 3);
    } catch (e) {}
    this.fading.push(bed);
    bed.killTimer = this.d.setTimeout(function () {
      self._hardStop(bed);
      self.fading = self.fading.filter(function (b) { return b !== bed; });
    }, (FADE_OUT + 0.6) * 1000);
  };

  AmbientSound.prototype._fadeShot = function (shot) {
    var self = this;
    if (shot.fading) return;
    shot.fading = true;
    try { var t = this.ctx.currentTime; shot.gain.gain.cancelScheduledValues(t); shot.gain.gain.setTargetAtTime(0, t, 0.25); } catch (e) {}
    shot.killTimer = this.d.setTimeout(function () {
      self._hardStop(shot);
      self.shots = self.shots.filter(function (x) { return x !== shot; });
    }, 900);
  };

  AmbientSound.prototype._load = function (key) {
    var self = this;
    if (!this.cache[key]) {
      this.cache[key] = this.d.fetchBuffer(this.ctx, BASE + FILES[key]).catch(function (e) { delete self.cache[key]; throw e; });
    }
    return this.cache[key];
  };

  AmbientSound.prototype._startBed = function (mode, epoch, announce) {
    var self = this, cfg = BED[mode];
    if (!cfg) return;
    this._load(cfg.file).then(function (buffer) {
      if (epoch !== self.epoch || self.muted) return;        // superseded while downloading: do nothing
      // never two beds of the same mode: stop any fading copy of it immediately
      self.fading = self.fading.filter(function (b) {
        if (b.mode === mode) { self._hardStop(b); return false; }
        return true;
      });
      var src = self.ctx.createBufferSource(), g = self.ctx.createGain();
      src.buffer = buffer; src.loop = true;
      g.gain.value = 0;
      src.connect(g); g.connect(self.master);
      var t = self.ctx.currentTime;
      src.start(0);
      g.gain.setTargetAtTime(cfg.gain, t, FADE_IN / 3);
      self.bed = { mode: mode, source: src, gain: g };
      self.lastStarted = mode;
      if (announce && cfg.enter) self._shot(cfg.enter, cfg.enterGain, epoch);
      if (cfg.calls) self._scheduleCall(epoch, true);
    }).catch(function () { self.failed = true; });             // audio trouble must never reach the game
  };

  AmbientSound.prototype._shot = function (key, gain, epoch) {
    var self = this;
    this._load(key).then(function (buffer) {
      if (epoch !== self.epoch || self.muted) return;
      var src = self.ctx.createBufferSource(), g = self.ctx.createGain();
      src.buffer = buffer; g.gain.value = gain;
      var node = g;
      if (self.ctx.createStereoPanner) {
        var p = self.ctx.createStereoPanner(); p.pan.value = (self.d.random() * 2 - 1) * 0.7;
        src.connect(g); g.connect(p); p.connect(self.master);
      } else { src.connect(g); g.connect(self.master); }
      var rec = { source: src, gain: g };
      self.shots.push(rec);
      src.onended = function () { self.shots = self.shots.filter(function (s) { return s !== rec; }); };
      src.start(0);
    }).catch(function () { self.failed = true; });
  };

  /** Random calls (wolf, owl, crow, creak) while a mode lasts. Never when muted or after the mode changed. */
  AmbientSound.prototype._pickCall = function (list) {
    var r = this.d.random(), acc = 0, choice = list[list.length - 1], i;
    for (i = 0; i < list.length; i++) { acc += list[i].w; if (r < acc) { choice = list[i]; break; } }
    if (choice.norepeat && choice.k === this.lastShot) {          // a wolf never howls twice in a row
      for (i = 0; i < list.length; i++) if (list[i].k !== this.lastShot) { choice = list[i]; break; }
    }
    return choice;
  };

  AmbientSound.prototype._scheduleCall = function (epoch, first) {
    var self = this, mode = this.desired, cfg = BED[mode] && BED[mode].calls;
    if (!cfg) return;
    var range = first ? cfg.first : cfg.every;
    var delay = (range[0] + this.d.random() * (range[1] - range[0])) * 1000;
    this._clearTimer();
    this.timer = this.d.setTimeout(function () {
      self.timer = null;
      if (epoch !== self.epoch || self.muted || self.desired !== mode) return;
      var pick = self._pickCall(cfg.list);
      self.lastShot = pick.k;
      self._shot(pick.k, pick.gain, epoch);
      self._scheduleCall(epoch, false);
    }, delay);
  };

  /** Button knock / role-reveal sting. Independent of the phase; silent when muted or before the first gesture. */
  AmbientSound.prototype.click = function (kind) {
    if (!this.unlocked || !this.ctx || this.muted) return;
    var now = this.now();
    if (kind !== "reveal" && now - this.lastClickAt < CLICK_GAP_MS) return;
    this.lastClickAt = now;
    var self = this, key = kind === "reveal" ? "reveal" : "click", gain = kind === "reveal" ? 0.55 : 0.45;
    this._load(key).then(function (buffer) {
      if (self.muted) return;
      var src = self.ctx.createBufferSource(), g = self.ctx.createGain();
      src.buffer = buffer; g.gain.value = gain;
      src.connect(g); g.connect(self.master);
      var rec = { source: src, gain: g };
      self.ui.push(rec);
      src.onended = function () { self.ui = self.ui.filter(function (s) { return s !== rec; }); };
      src.start(0);
    }).catch(function () {});
  };

  AmbientSound.prototype.visibility = function (hidden) {
    if (!this.ctx) return;
    try {
      if (hidden && this.ctx.suspend) this.ctx.suspend();
      else if (!hidden && !this.muted && this.ctx.resume) this.ctx.resume();
    } catch (e) {}
  };

  /* ------------------------------------------------------------------ browser wiring */
  function realDeps() {
    return {
      createContext: function () { var C = window.AudioContext || window.webkitAudioContext; return new C(); },
      fetchBuffer: function (ctx, url) {
        return fetch(url, { cache: "force-cache" }).then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.arrayBuffer();
        }).then(function (ab) {
          return new Promise(function (res, rej) { var p = ctx.decodeAudioData(ab, res, rej); if (p && p.then) p.then(res, rej); });
        });
      },
      setTimeout: function (f, ms) { return window.setTimeout(f, ms); },
      clearTimeout: function (id) { window.clearTimeout(id); },
      random: Math.random,
      now: function () { return Date.now(); },
      storage: {
        get: function () { try { return window.localStorage.getItem("camorra_sound"); } catch (e) { return null; } },
        set: function (v) { try { window.localStorage.setItem("camorra_sound", v); } catch (e) {} }
      }
    };
  }

  function activeScreenId() {
    var panels = document.querySelectorAll(".panel");
    for (var i = 0; i < panels.length; i++) if (!panels[i].classList.contains("hidden")) return panels[i].id;
    return "";
  }

  function makeIcon(muted) {
    var ns = "http://www.w3.org/2000/svg";
    if (!document.createElementNS) { var s = document.createElement("span"); s.textContent = muted ? "off" : "on"; return s; }
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2"); svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round");
    var p1 = document.createElementNS(ns, "path"); p1.setAttribute("d", "M11 5 6 9H3v6h3l5 4z");
    svg.appendChild(p1);
    if (muted) {
      var a = document.createElementNS(ns, "path"); a.setAttribute("d", "M22 9l-6 6"); svg.appendChild(a);
      var b = document.createElementNS(ns, "path"); b.setAttribute("d", "M16 9l6 6"); svg.appendChild(b);
    } else {
      var c = document.createElementNS(ns, "path"); c.setAttribute("d", "M15.5 8.5a5 5 0 0 1 0 7"); svg.appendChild(c);
      var d = document.createElementNS(ns, "path"); d.setAttribute("d", "M18.5 5.5a9 9 0 0 1 0 13"); svg.appendChild(d);
    }
    return svg;
  }

  function start(deps) {
    var sound = new AmbientSound(deps || realDeps());
    var btn = document.createElement("button");
    btn.type = "button"; btn.id = "camorraSoundButton"; btn.className = "camorra-sound-fab";
    document.body.appendChild(btn);
    function paint() {
      btn.className = "camorra-sound-fab" + (sound.muted ? " is-muted" : "");
      btn.setAttribute("aria-pressed", sound.muted ? "true" : "false");
      btn.setAttribute("aria-label", sound.muted ? "Turn ambient sound on" : "Turn ambient sound off");
      btn.title = sound.muted ? "Sound is off. Click to turn on." : "Sound is on. Click to turn off.";
      while (btn.firstChild) btn.removeChild(btn.firstChild);
      btn.appendChild(makeIcon(sound.muted));
    }
    sound.onState = paint;
    paint();
    btn.addEventListener("click", function () { sound.unlock(); sound.setMuted(!sound.muted); });

    function winnerMode() {
      var g = document.getElementById("gameOver");                 // game.js marks the winner on this panel before showing it
      if (!g || !g.classList) return null;
      return g.classList.contains("mafia-won") ? "win-mafia" : (g.classList.contains("civilians-won") ? "win-civilians" : null);
    }
    function screen() {
      var id = activeScreenId(), mode = MODE_BY_SCREEN.hasOwnProperty(id) ? MODE_BY_SCREEN[id] : null;
      sound.setMode(mode === "win" ? winnerMode() : mode);
    }
    document.addEventListener("click", function (e) {
      var t = e && e.target, b = t && t.closest ? t.closest("button") : null;
      if (b) sound.click(b.id === "showRoleButton" ? "reveal" : "click");
    }, true);
    var unlockEvents = ["pointerdown", "keydown", "touchstart"];
    function onFirst() {
      unlockEvents.forEach(function (n) { window.removeEventListener(n, onFirst, true); });
      sound.unlock(); screen();
    }
    unlockEvents.forEach(function (n) { window.addEventListener(n, onFirst, true); });

    var observer = new MutationObserver(function (records) {
      for (var i = 0; i < records.length; i++) {
        var t = records[i].target;
        if (t && t.classList && t.classList.contains("panel")) { screen(); return; }
      }
    });
    observer.observe(document.body, { subtree: true, attributes: true, attributeFilter: ["class"] });
    document.addEventListener("visibilitychange", function () { sound.visibility(document.hidden); });
    screen();
    window.CamorraSound = sound;
    return sound;
  }

  var api = { AmbientSound: AmbientSound, MODE_BY_SCREEN: MODE_BY_SCREEN, FILES: FILES, BED: BED, start: start };
  if (typeof module !== "undefined") module.exports = api;
  if (typeof window !== "undefined" && typeof module === "undefined") {
    window.CamorraSoundInternals = api;
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { start(); }); else start();
  }
})();
