"use strict";
/* motion.js: every animation in the app lives here, so it is easy to find, explain and tweak.
   Rules: only `transform` and `opacity` are animated, 150-350 ms, one easing, and nothing moves when the
   visitor has "reduce motion" switched on. app.js calls these helpers; the CSS handles hover/press/focus. */
const Motion = (() => {
  const EASE = "cubic-bezier(.22,1,.36,1)";               // same curve as --ease in styles.css
  const T = 250;                                          // default duration in ms (--t)
  const mq = matchMedia("(prefers-reduced-motion: reduce)");
  const reduced = () => mq.matches;

  /* Web Animations API wrapper. Does nothing for reduced-motion users. "backwards" fill keeps staggered
     items hidden until their own delay has passed; once finished, the element returns to normal CSS. */
  function play(el, frames, ms = T, opts = {}) {
    if (reduced() || !el) return null;
    return el.animate(frames, { duration: ms, easing: EASE, fill: "backwards", ...opts });
  }
  const RISE = (y = 12) => [{ opacity: 0, transform: `translateY(${y}px)` }, { opacity: 1, transform: "none" }];

  /* Fade and rise a list of elements one after another (card / list stagger). */
  function enter(els, { y = 12, step = 50, max = 8 } = {}) {
    [...els].forEach((el, i) => play(el, RISE(y), T + 50, { delay: Math.min(i, max) * step }));
  }
  /* Content blocks of a panel: cards inside the #...-out wrappers count as separate blocks. */
  function enterPanel(panel) {
    const blocks = [...panel.children].flatMap(c => (c.id && !c.classList.contains("card") ? [...c.children] : [c]));
    enter(blocks);
  }
  /* Short fade + rise, e.g. when the session or room changes. */
  const crossfade = el => play(el, RISE(8), T);

  /* Seats pop in one after another when a plan has just been generated (capped so it never drags on). */
  function pop(seats) {
    [...seats].forEach((el, i) => play(el, [{ opacity: 0, transform: "scale(.6)" }, { opacity: 1, transform: "scale(1)" }], T, { delay: Math.min(i * 7, 450) }));
  }

  /* Sliding tab indicator (FLIP): move the pill to its final place, then animate from where it was. */
  let ind = null, nav = null, last = null;
  function tabs(navEl) {
    nav = navEl; ind = nav.querySelector(".tab-ind");
    moveTab(false);
    addEventListener("resize", () => moveTab(false));
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => moveTab(false));   // label widths change once the font loads
  }
  function moveTab(animate = true) {
    const b = nav && nav.querySelector('[aria-selected="true"]'); if (!b) return;
    const x = b.offsetLeft, w = b.offsetWidth;
    ind.style.width = w + "px"; ind.style.transform = `translateX(${x}px)`;
    if (animate && last && !reduced() && (last.x !== x || last.w !== w))
      ind.animate([{ transform: `translateX(${last.x}px) scaleX(${last.w / w})` }, { transform: `translateX(${x}px)` }], { duration: 300, easing: EASE });
    last = { x, w };
    nav.scrollTo({ left: Math.max(0, x - 24), behavior: reduced() ? "auto" : "smooth" });         // keeps the active tab visible on phones
  }

  /* Stat numbers count up from 0. Elements opt in with data-count="42". (rAF only changes text, not layout.) */
  function countUp(el, to, ms = 700) {
    to = Number(to);
    if (!isFinite(to) || to <= 0 || reduced()) { el.textContent = to; return; }
    const t0 = performance.now();
    const step = now => {
      const p = Math.min(1, (now - t0) / ms);
      el.textContent = Math.round(to * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(step);
    };
    el.textContent = 0; requestAnimationFrame(step);
  }
  const countAll = root => root.querySelectorAll("[data-count]").forEach(el => countUp(el, el.dataset.count));

  /* Toasts: one message at a time, sliding in at the bottom right. Errors stay until closed or the next action. */
  function dismiss(el) {
    if (el._gone) return; el._gone = true; clearTimeout(el._timer);
    const a = play(el, [{ opacity: 1, transform: "none" }, { opacity: 0, transform: "translateX(28px)" }], 200, { fill: "forwards" });
    if (a) a.onfinish = () => el.remove(); else el.remove();
  }
  function toast(msg, kind = "info") {
    const box = document.getElementById("toasts");
    box.querySelectorAll(".toast").forEach(dismiss);
    if (!msg) return;
    const el = document.createElement("div"), p = document.createElement("p"), x = document.createElement("button");
    el.className = "toast " + kind; el.setAttribute("role", kind === "error" ? "alert" : "status");
    p.textContent = msg;                                   // textContent: messages can never inject HTML
    x.className = "toast-x"; x.type = "button"; x.textContent = "×"; x.setAttribute("aria-label", "Dismiss message");
    x.addEventListener("click", () => dismiss(el));
    el.append(p, x); box.append(el);
    play(el, [{ opacity: 0, transform: "translateY(18px) scale(.97)" }, { opacity: 1, transform: "none" }], 300);
    if (kind !== "error") el._timer = setTimeout(() => dismiss(el), kind === "warn" ? 9000 : 6000);
  }

  /* Loading skeleton shaped like the seating plan (shimmer is a moving gradient: transform only). */
  function skeleton(box) {
    const bar = (w, h = 16) => { const d = document.createElement("div"); d.className = "skel"; d.style.cssText = `width:${w};height:${h}px`; return d; };
    const wrap = (cls, ...kids) => { const d = document.createElement("div"); d.className = cls; d.append(...kids); return d; };
    const seats = wrap("grid", ...Array.from({ length: 24 }, () => { const s = bar("74px", 50); return s; }));
    seats.style.gridTemplateColumns = "repeat(6,74px)";
    const list = wrap("sessions", ...Array.from({ length: 4 }, () => bar("100%", 54)));
    const card = wrap("skel-card", bar("40%", 24), wrap("", bar("100%", 8)), seats);
    card.querySelectorAll(":scope > div:nth-child(2)").forEach(d => { d.style.margin = "14px 0"; });
    box.replaceChildren(wrap("layout", list, card));
    box.setAttribute("aria-busy", "true");
    play(box, [{ opacity: 0 }, { opacity: 1 }], 200);
  }

  /* Hover (or keyboard focus) on a seat or legend chip: that course lights up, every other course fades. */
  function highlight(root) {
    let lastEl = null;
    const set = el => {
      if (el === lastEl) return; lastEl = el;
      const code = el ? el.dataset.course : null;
      root.querySelectorAll("[data-course]").forEach(n => {
        const on = !!code && n.dataset.course === code;
        n.classList.toggle("dim", !!code && !on);
        n.classList.toggle("hl", on && n.classList.contains("seat"));
      });
    };
    root.addEventListener("mouseover", e => set(e.target.closest("[data-course]")));
    root.addEventListener("mouseleave", () => set(null));
    root.addEventListener("focusin", e => set(e.target.closest("[data-course]")));
    root.addEventListener("focusout", () => set(null));
    root.addEventListener("click", () => { lastEl = null; });          // a re-render replaces the seats: forget the old target
  }

  /* Upload cards light up while a file is dragged over them. The browser itself handles the drop. */
  function dropzones(root = document) {
    root.querySelectorAll("label.file").forEach(z => {
      ["dragenter", "dragover"].forEach(t => z.addEventListener(t, () => z.classList.add("drag")));
      ["dragleave", "drop", "dragend"].forEach(t => z.addEventListener(t, () => z.classList.remove("drag")));
    });
  }

  /* Waits a moment so a very fast API call does not make the skeleton flash. No wait for reduced motion. */
  const minDelay = ms => new Promise(r => setTimeout(r, reduced() ? 0 : ms));

  return { reduced, play, enter, enterPanel, crossfade, pop, tabs, moveTab, countUp, countAll, toast, skeleton, highlight, dropzones, minDelay };
})();
