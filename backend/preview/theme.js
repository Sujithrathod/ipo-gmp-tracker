// Runs before first paint: light theme unless the user picked dark on this device.
(function () {
  var t = "light";
  try { t = localStorage.getItem("theme") === "dark" ? "dark" : "light"; } catch (e) {}
  document.documentElement.dataset.theme = t;
})();
