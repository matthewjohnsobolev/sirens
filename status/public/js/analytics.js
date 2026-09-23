(function () {
  "use strict";

  function send(name, params) {
    if (window.track) window.track(name, params);
  }

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!target || !target.closest) return;

    if (target.closest(".btn-report")) {
      send("report_cta_click", { link_location: "status" });
      return;
    }

    var navLink = target.closest(".foot-nav a") || target.closest(".logo");
    if (navLink) {
      send("site_nav_click", {
        link_location: "status",
        link_url: navLink.getAttribute("href") || "",
      });
      return;
    }

    var bar = target.closest(".bar");
    if (bar) {
      var comp = bar.closest(".comp");
      send("status_bar_open", {
        component_key: comp
          ? comp.getAttribute("data-key") || "unknown"
          : "unknown",
        hour_state: bar.getAttribute("data-state") || "unknown",
      });
    }
  });
})();
