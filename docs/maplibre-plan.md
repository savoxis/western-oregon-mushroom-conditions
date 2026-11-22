# Plan: moving the shrooms map from Leaflet to MapLibre GL JS

Status: MapLibre is the default (Nov 22, 2026, after a phone check). `?map=leaflet` opens the old Leaflet map; if MapLibre cannot start the page falls back to Leaflet by itself.

## Why consider it

- Smoother zoom (fractional zoom, GPU drawing), and thousands of sightings as one circle layer instead of DOM markers.
- Native clustering for the sightings (a GeoJSON source option), data-driven styling, hover/selected state without redrawing.
- One map stack across the three sites (hunting and fishing already use it), so fixes and styling carry over.

## What it costs

- About 1 MB of JavaScript against Leaflet's 148 KB, on a site people mostly open on phones.
- A rewrite of the map section of `site/app.js` (roughly lines 490 to 1000): the heat layer, the zone markers, sightings, burns, land tiles and popups.
- WebGL is required. Some old phones and locked-down browsers do not have it, so a fallback is part of the work.
- The server's content security policy needs the tile hosts added to `connect-src` (the MapLibre CSP build loads tiles with fetch, not img tags) and its worker file allowed (same origin, so `worker-src 'self'`).

## Mapping the current pieces

| Today (Leaflet) | MapLibre |
|---|---|
| USGS topo tiles, BLM land tiles | Raster sources and layers (land is a toggled layer) |
| Heat surface: canvas pane between tiles and markers, Gaussian blend (sigma 25 km, reach 80 km), clipped to the Oregon ring | Same algorithm onto an offscreen canvas at a fixed grid; add it as an image source with the Oregon bounding corners and `updateImage` per time-machine frame. Clip to the ring on the canvas as now. Cheaper than redrawing on every pan |
| Zone markers (HTML icons with score badges) | `maplibregl.Marker` with the same DOM icons for the ~80 zones (keeps the look), or a symbol layer if icons can be sprites |
| Sightings (many small markers, photo popups) | GeoJSON source + circle layer, native clustering, same lazy photo lookup in a popup |
| Burn scars (polygons, dashed when closed) | Fill and line layers with a data-driven dash |
| Evidence rings (ev-none, ev-thin) | Circle layer with a data-driven stroke |
| Popups, panel shift on wide screens | MapLibre popups, same panel logic (`map.resize()` after the panel opens) |

## Phases (each shippable and reversible)

1. **Spike on a branch** (half a day): base map, zone markers, the heat image source and the time-machine animation. Compare frame times and page weight with the live site on a mid-range phone. Go or no-go here.
2. **Sightings and photos**: circle layer, clustering, the evidence filters, the photo popup (the lazy GBIF lookup stays as is).
3. **Burns, land layer, popups, panel behaviour, keyboard and screen-reader paths** (the Leaflet map today has marker titles used as labels).
4. **Fallback**: if `maplibregl.supported()` is false or WebGL fails, show the zone list view (already there) with a note, rather than a blank map.
5. **Release behind a flag** (`?map=gl`) for a week, then flip the default. Keep the Leaflet code path for one release as the rollback.

## Tests and checks

- Screenshot comparison of live mode and a time-machine day against the current map (same zone selected).
- Frame time while the time machine plays, on a phone-class CPU profile.
- Content security policy: load the page with the production header and confirm no blocked requests.
- The existing builder and calc tests do not touch the map, so they stay as they are.

## Decision rule

Go ahead only if phase 1 shows smoother zoom and playback on a phone at an acceptable size cost, and the two new sites have been stable with MapLibre in real use. Otherwise keep Leaflet: nothing about the shrooms map is broken today.

## Spike results (Nov 22, 2026, `site/spike-gl.html` on the `maplibre-spike` branch, not deployed)

Built in one sitting from the same data files as the live page: USGS topo, the Gaussian heat surface as an image source clipped to Oregon, and the zones as a circle layer.

- **The heat surface works as planned.** 119 points (zones plus the statewide grid) blend in 15 ms (0.04 degree cells), 26 ms (0.03) or 51 ms (0.02), computed once per data change. The live page recomputes its surface on every pan and zoom frame, so panning is where the saving is. A time-machine frame costs one computation, well inside the 110 ms step.
- **Zoom stayed smooth** in the preview pane: 140 frames over four animated zooms, mean 33 ms, worst 50 ms, with no heat recomputation during them. That pane is software-rendered, so a real phone GPU should do at least as well; this still needs a check on an actual phone.
- **Clean under the content security policy rules** that matter here: the worker is a same-origin file, the heat image is a data URL (the live policy already allows `data:` images), and tiles load by fetch, so `connect-src` must list the two tile hosts.
- **Not in the spike yet:** zone labels and score badges, sightings with clustering and photo popups, burns, the land layer, popups, the panel shift and the time-machine controls. Zone labels are the one design question: text on a MapLibre map needs a font glyph service, so the plan keeps the existing HTML marker icons for the ~80 zones.
- **Cost unchanged:** about 970 KB of script against Leaflet's 148 KB.

Verdict: phase 1 passes on feasibility. The decision rule above still applies: wait for the hunting and fishing sites to run on MapLibre in real use and test on a phone before starting phase 2.

## Phases 2 and 3 built behind a flag (Nov 22, 2026, `maplibre-spike` branch, not deployed)

`?map=gl` now runs the real page on MapLibre. Without the flag nothing changes for anyone and MapLibre is not even downloaded (`gl-boot.js` loads it only when asked).

Working in the preview with live data: the topo base, the heat surface (computed once per data change as an image, clipped to Oregon), all 41 zone markers with the same score icons, tooltips, keyboard activation and selection pulse, species and mode switching, the time machine, the land-ownership layer, sightings as one circle layer with the photo popup, the 2026 burn scars with their popups, "Show all burns", zoom buttons, the click-anywhere regional estimate, and fly-to with the side-panel offset. No console errors. If MapLibre cannot start (no WebGL), the page falls back to Leaflet by itself.

Still to do before it could become the default:
1. Phone test on real hardware (frame rate, battery, memory) and a compare against Leaflet on the same phone.
2. ~~Production header~~ Done: `connect-src` lists the two tile hosts; the worker is same origin. The heat surface is a canvas source, so no `data:` entry is needed in `connect-src`.
3. Pixel polish: marker label timing at the zoom threshold, popup auto-pan under the top bar, attribution placement.
4. Decide about clustering the sightings (MapLibre can do it natively; today they are plain dots).
5. A week behind the flag with real users, then flip the default and keep the Leaflet path for one release.
