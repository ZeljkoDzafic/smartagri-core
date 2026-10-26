// SmartAgri presentation site: scroll reveals, menu, interface tabs, screenshot dialog, copy button. No dependencies.
"use strict";

// Section reveals on scroll. Content is visible without JavaScript and with reduced motion: the hidden start state
// applies only under html.js-reveal, which is set here when IntersectionObserver exists and motion is allowed.
(function () {
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce || !("IntersectionObserver" in window)) return;
  const items = Array.from(document.querySelectorAll(".reveal"));
  document.documentElement.classList.add("js-reveal");
  items.forEach((el) => {
    const siblings = Array.from(el.parentElement.children).filter((c) => c.classList.contains("reveal"));
    el.style.transitionDelay = Math.min(siblings.indexOf(el), 6) * 70 + "ms";
  });
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
  }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
  items.forEach((el) => io.observe(el));
  // Anything already in view (or reached by an anchor jump) is shown without waiting for the observer.
  window.addEventListener("hashchange", () => items.forEach((el) => el.classList.add("in")), { once: true });
})();

// Mobile menu
const menu = document.getElementById("menu-toggle");
const nav = document.getElementById("main-nav");
function closeMenu() { menu.setAttribute("aria-expanded", "false"); nav.classList.remove("open"); }
menu.addEventListener("click", () => {
  const open = menu.getAttribute("aria-expanded") !== "true";
  menu.setAttribute("aria-expanded", String(open));
  nav.classList.toggle("open", open);
});
nav.querySelectorAll("a").forEach((a) => a.addEventListener("click", closeMenu));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });

// Tabs (arrow keys, Home, End)
const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
function select(tab, focus) {
  tabs.forEach((t) => {
    const on = t === tab;
    t.setAttribute("aria-selected", String(on));
    t.tabIndex = on ? 0 : -1;
    document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
  });
  if (focus) tab.focus();
}
tabs.forEach((tab, i) => {
  tab.addEventListener("click", () => select(tab, false));
  tab.addEventListener("keydown", (e) => {
    const n = tabs.length;
    const next = { ArrowRight: (i + 1) % n, ArrowLeft: (i - 1 + n) % n, Home: 0, End: n - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    select(tabs[next], true);
  });
});

// Screenshot dialog
const dialog = document.getElementById("image-dialog");
const dialogImage = document.getElementById("dialog-image");
let opener = null;
document.querySelectorAll("[data-image]").forEach((button) => button.addEventListener("click", () => {
  opener = button;
  dialogImage.src = button.dataset.image;
  dialogImage.alt = button.querySelector("img") ? button.querySelector("img").alt : "";
  document.getElementById("dialog-caption").textContent = button.dataset.caption || "";
  dialog.showModal();
  document.body.classList.add("modal-open");
  document.getElementById("close-dialog").focus();
}));
document.getElementById("close-dialog").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });
dialog.addEventListener("close", () => { document.body.classList.remove("modal-open"); if (opener) opener.focus(); });

// Copy the install commands (falls back to selecting the text)
document.getElementById("copy-install").addEventListener("click", async () => {
  const button = document.getElementById("copy-install");
  const status = document.getElementById("copy-status");
  const block = document.getElementById("install-command");
  try {
    await navigator.clipboard.writeText(block.textContent.trim());
    button.textContent = "Copied";
    status.textContent = "Commands copied to the clipboard.";
    setTimeout(() => { button.textContent = "Copy"; status.textContent = ""; }, 2500);
  } catch (e) {
    const range = document.createRange();
    range.selectNodeContents(block);
    const sel = window.getSelection();
    sel.removeAllRanges(); sel.addRange(range);
    status.textContent = "Select the commands and copy them manually.";
  }
});
