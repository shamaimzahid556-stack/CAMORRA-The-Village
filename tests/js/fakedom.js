// Minimal DOM stand-in, just enough to run chatbot.js and sound.js under Node (no browser needed).
class ClassList {
  constructor(el) { this.el = el; this.set = new Set(); }
  _n() { this.el._world.notify(this.el); }
  add(...c) { c.forEach(x => this.set.add(x)); this._n(); }
  remove(...c) { c.forEach(x => this.set.delete(x)); this._n(); }
  contains(c) { return this.set.has(c); }
  toggle(c, force) { const on = force === undefined ? !this.set.has(c) : force; on ? this.set.add(c) : this.set.delete(c); this._n(); }
}
class El {
  constructor(tag, world) {
    this.tagName = tag.toUpperCase(); this._world = world; this.children = []; this.parentNode = null;
    this.attrs = {}; this.listeners = {}; this.classList = new ClassList(this); this._text = ""; this.hidden = false;
    this.id = ""; this.value = ""; this.disabled = false; this.style = {}; this.nodeType = 1; this.scrollTop = 0; this.scrollHeight = 0;
  }
  set className(v) { this.classList.set = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get className() { return [...this.classList.set].join(" "); }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); c.parentNode = null; return c; }
  get firstChild() { return this.children[0] || null; }
  setAttribute(k, v) { this.attrs[k] = v; if (k === "id") this.id = v; }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  dispatch(type, extra) {
    const ev = Object.assign({ type, defaultPrevented: false, propagationStopped: false,
      preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.propagationStopped = true; } }, extra || {});
    (this.listeners[type] || []).forEach(fn => fn(ev));
    return ev;
  }
  click() { const ev = this.dispatch("click", { target: this }); this._world.document.fire("click", { target: this }); return ev; }
  closest(sel) { let e = this; while (e && e.nodeType === 1) { if (e.tagName === sel.toUpperCase()) return e; e = e.parentNode; } return null; }
  focus() { this._world.document.activeElement = this; }
  set textContent(v) { this.children = []; this._text = String(v); }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(""); }
  all() { return this.children.flatMap(c => (c.nodeType === 1 ? [c, ...c.all()] : [])); }
  querySelectorAll(sel) {
    const cls = sel.replace(/^\./, "");
    return this.all().filter(e => e.classList.contains(cls));
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
function makeWorld() {
  const world = { observers: [], timers: [] };
  world.notify = el => world.observers.forEach(o => o._fire(el));
  world.MutationObserver = class {
    constructor(cb) { this.cb = cb; }
    observe() { world.observers.push(this); }
    _fire(el) { this.cb([{ target: el, type: "attributes", attributeName: "class" }]); }
    disconnect() {}
  };
  const body = new El("body", world);
  world.document = {
    body, readyState: "complete", activeElement: null, hidden: false,
    createElement: t => new El(t, world),
    createElementNS: (ns, t) => new El(t, world),
    createTextNode: t => ({ nodeType: 3, textContent: String(t) }),
    querySelectorAll: s => body.querySelectorAll(s),
    _l: {}, addEventListener(t, fn) { (this._l[t] = this._l[t] || []).push(fn); },
    fire(t, ev) { (this._l[t] || []).forEach(fn => fn(ev)); },
    getElementById: id => body.all().find(e => e.id === id) || null,
  };
  world.addPanel = (id, hidden) => { const p = world.document.createElement("section"); p.setAttribute("id", id); p.className = "panel" + (hidden ? " hidden" : ""); body.appendChild(p); return p; };
  world.showOnly = id => { body.querySelectorAll(".panel").forEach(p => p.classList.toggle("hidden", p.id !== id)); };
  return world;
}
module.exports = { makeWorld, El };
