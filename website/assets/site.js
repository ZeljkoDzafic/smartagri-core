// SmartAgri presentation site: menu, interface tabs, screenshot dialog, copy button. No dependencies.
"use strict";

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
