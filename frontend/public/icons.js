/* Inline SVG sprite — injected into #sprite on every page (file:// safe). */
(function () {
  const S = (id, body, viewBox) =>
    `<symbol id="${id}" viewBox="${viewBox || "0 0 24 24"}">${body}</symbol>`;

  const sprite = [
    S("i-logo", '<path d="M3 13h3.2l2.1-6.2 3.4 11.4L14.6 10l1.6 3H21"/>'),
    S(
      "i-grid",
      '<rect x="3" y="3" width="7.5" height="7.5" rx="1.6"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.6"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.6"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.6"/>'
    ),
    S(
      "i-layers",
      '<path d="M12 3 3 7.7l9 4.7 9-4.7L12 3Z"/><path d="m3 12.2 9 4.7 9-4.7"/><path d="m3 16.7 9 4.7 9-4.7"/>'
    ),
    S("i-activity", '<path d="M3 12h4l2.4-7 4.2 14L16.2 12H21"/>'),
    S(
      "i-sliders",
      '<path d="M4 6h9M18 6h2M4 12h4M13 12h7M4 18h11M20 18h0"/><circle cx="15" cy="6" r="2.2"/><circle cx="10" cy="12" r="2.2"/><circle cx="17" cy="18" r="2.2"/>'
    ),
    S("i-search", '<circle cx="11" cy="11" r="7"/><path d="m20.5 20.5-3.8-3.8"/>'),
    S(
      "i-bell",
      '<path d="M6 9a6 6 0 0 1 12 0c0 4.6 2 5.8 2 5.8H4S6 13.6 6 9Z"/><path d="M10.4 19a2 2 0 0 0 3.2 0"/>'
    ),
    S("i-refresh", '<path d="M20 11a8 8 0 1 0-.7 4.4"/><path d="M20 4.5V11h-6.5"/>'),
    S("i-chevron-down", '<path d="m6 9.5 6 6 6-6"/>'),
    S("i-arrow-right", '<path d="M4 12h16M14 6l6 6-6 6"/>'),
    S("i-arrow-left", '<path d="M20 12H4M10 6l-6 6 6 6"/>'),
    S("i-arrow-up-right", '<path d="M7 17 17 7M8 7h9v9"/>'),
    S(
      "i-more",
      '<circle cx="12" cy="5" r="1.4" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="12" cy="19" r="1.4" fill="currentColor" stroke="none"/>'
    ),
    S("i-check", '<path d="m5 12.5 4.5 4.5L19 6.5"/>'),
    S("i-x", '<path d="M6 6l12 12M18 6 6 18"/>'),
    S("i-clock", '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>'),
    S(
      "i-server",
      '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01M16 7.5h1M16 16.5h1"/>'
    ),
    S(
      "i-shield",
      '<path d="M12 3 5 6v5.2c0 4.5 3 7.6 7 9.3 4-1.7 7-4.8 7-9.3V6l-7-3Z"/><path d="m9.2 11.8 2 2 3.6-3.8"/>'
    ),
    S("i-zap", '<path d="m13 2.5-8 11.5h5.6L9.8 21.5 18 9.8h-5.4l.4-7.3Z"/>'),
    S(
      "i-database",
      '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/><path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/>'
    ),
    S("i-terminal", '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3M13 15h4"/>'),
    S(
      "i-branch",
      '<circle cx="6.5" cy="6" r="2.2"/><circle cx="6.5" cy="18" r="2.2"/><circle cx="17.5" cy="7.5" r="2.2"/><path d="M6.5 8.2v7.6M17.5 9.7v.8a4 4 0 0 1-4 4H9"/>'
    ),
    S("i-key", '<circle cx="8" cy="8" r="4.2"/><path d="m11 11 8.5 8.5M16.2 16.2l2.2-2.2M18.4 18.4l2.2-2.2"/>'),
    S(
      "i-external",
      '<path d="M14 4.5h5.5V10M19.5 4.5 11.5 12.5M17.5 14v4.5a2 2 0 0 1-2 2H5.5a2 2 0 0 1-2-2V8.5a2 2 0 0 1 2-2H10"/>'
    ),
    S("i-play", '<path d="M8 4.8v14.4L19.5 12 8 4.8Z"/>'),
    S(
      "i-copy",
      '<path d="M8 8V5.5a2 2 0 0 1 2-2h8.5a2 2 0 0 1 2 2V14a2 2 0 0 1-2 2H16"/><rect x="3.5" y="8" width="12.5" height="12.5" rx="2"/>'
    ),
    S("i-lock", '<rect x="4" y="10" width="16" height="11" rx="2.2"/><path d="M8 10V7.2a4 4 0 0 1 8 0V10"/>'),
    S("i-mail", '<rect x="3" y="5" width="18" height="14" rx="2.2"/><path d="m4 7 8 6 8-6"/>'),
    S("i-user", '<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5c0-3.8 3.4-6 7.5-6s7.5 2.2 7.5 6"/>'),
    S("i-filter", '<path d="M4 5.5h16l-6.2 7.2v6l-3.6 1.8v-7.8L4 5.5Z"/>'),
    S(
      "i-columns",
      '<rect x="3" y="4" width="18" height="16" rx="2.2"/><path d="M9 4v16M15 4v16"/>'
    ),
    S("i-plus", '<path d="M12 4.5v15M4.5 12h15"/>'),
    S(
      "i-alert-triangle",
      '<path d="M12 4 2.8 20h18.4L12 4Z"/><path d="M12 10v4.4M12 17.4h.01"/>'
    ),
    S("i-check-circle", '<circle cx="12" cy="12" r="8.6"/><path d="m8.2 12.4 2.6 2.6 5-5.4"/>'),
    S("i-info", '<circle cx="12" cy="12" r="8.6"/><path d="M12 11v5.4M12 7.8h.01"/>'),
    S("i-logout", '<path d="M9 4.5H5.5a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2H9M16 8.5l4 3.5-4 3.5M20 12H9"/>'),
    S(
      "i-settings",
      '<circle cx="12" cy="12" r="3.1"/><path d="M12 2.8v3M12 18.2v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M2.8 12h3M18.2 12h3M4.9 19.1 7 17M17 7l2.1-2.1"/>'
    ),
    S(
      "i-cpu",
      '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9.5 2.5v3.5M14.5 2.5v3.5M9.5 18v3.5M14.5 18v3.5M2.5 9.5H6M2.5 14.5H6M18 9.5h3.5M18 14.5h3.5"/><rect x="10" y="10" width="4" height="4" rx="1"/>'
    ),
    S(
      "i-box",
      '<path d="M12 3 3 7.5v9L12 21l9-4.5v-9L12 3Z"/><path d="M3 7.5 12 12l9-4.5M12 12v9"/>'
    ),
    S(
      "i-wheel",
      '<circle cx="12" cy="12" r="8.6"/><circle cx="12" cy="12" r="3.1"/><path d="M12 3.4v5.5M12 15.1v5.5M3.4 12h5.5M15.1 12h5.5M6 6l3.5 3.5M14.5 14.5 18 18M18 6l-3.5 3.5M9.5 14.5 6 18"/>'
    ),
    S(
      "i-flame",
      '<path d="M12 21c4 0 6.4-2.6 6.4-6 0-3.6-2.6-5.6-3.6-9.2-2 1.5-2.9 3.5-2.9 5.9-1-.9-1.5-2.3-1.3-4C8.1 9.6 5.6 12 5.6 15c0 3.4 2.4 6 6.4 6Z"/>'
    ),
    S(
      "i-torch",
      '<path d="M12 3.2c2 2.4 3.2 4.6 3.2 6.8 0 2.4-1.4 4.2-3.2 5.1-1.8-.9-3.2-2.7-3.2-5.1 0-2.2 1.2-4.4 3.2-6.8Z"/><path d="M9.4 17.4h5.2M9.8 20.4h4.4"/>'
    ),
    S(
      "i-wifi",
      '<path d="M4 8.5a13 13 0 0 1 16 0M6.5 12a9.4 9.4 0 0 1 11 0M9.3 15.5a5.6 5.6 0 0 1 5.4 0"/><path d="M12 19.4h.01"/>'
    ),
    S("i-corner-down", '<path d="M6 5v7a3 3 0 0 0 3 3h10M15 11l4 4-4 4"/>'),
    S("i-inbox", '<path d="M4 13h4l1.5 3h5L16 13h4"/><path d="M5.5 4.5h13l1.5 8.5v3a2 2 0 0 1-2 2h-12a2 2 0 0 1-2-2v-3l1.5-8.5Z"/>'),
    S("i-target", '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none"/>')
  ].join("");

  const mount = document.getElementById("sprite");
  if (mount) mount.innerHTML = sprite;
})();
