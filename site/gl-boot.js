/* Loads MapLibre only when the page is opened with ?map=gl, so everyone else downloads nothing extra. It runs before app.js. */
(function () {
  'use strict';
  if (!/(^|[?&])map=gl(&|$)/.test(location.search)) return;
  document.write('<link rel="stylesheet" href="vendor/maplibre/maplibre-gl.css">');
  document.write('<script src="vendor/maplibre/maplibre-gl-csp.js"><\/script>');
})();
