/* Loads MapLibre unless the page is opened with ?map=leaflet (the rollback switch). It runs before app.js; if MapLibre cannot start, app.js falls back to Leaflet by itself. */
(function () {
  'use strict';
  if (/(^|[?&])map=leaflet(&|$)/.test(location.search)) return;
  document.write('<link rel="stylesheet" href="vendor/maplibre/maplibre-gl.css">');
  document.write('<script src="vendor/maplibre/maplibre-gl-csp.js"><\/script>');
})();
