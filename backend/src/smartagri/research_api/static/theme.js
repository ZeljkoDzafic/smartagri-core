// Applies the stored appearance (auto, light, dark) before the page is painted.
(function () {
  var theme = "auto";
  try { theme = localStorage.getItem("smartagri.theme") || "auto"; } catch (e) { /* storage unavailable */ }
  if (theme === "light" || theme === "dark") document.documentElement.setAttribute("data-theme", theme);
})();
