/* Three-map area comparison: draw a circle, sweep HERE + Google + Grab, compare.
 *
 * Loaded before app.js and registered into its view table as `window.areaView`.
 * Helpers (api, state, qs, esc) come from app.js and are only referenced inside
 * functions, which run long after both files have loaded.
 *
 * Basemap: HERE Maps JS when a HERE API key is configured, MapLibre + OSM raster
 * otherwise. Both expose the same three operations to the rest of this file —
 * setCenter, drawCircle, plotPoints — so nothing below cares which one is live.
 */
(function () {
  const AREA = {
    opts: null,        // /area/options payload
    sweep: null,       // current sweep summary
    estimate: null,
    picker: null,      // basemap wrapper for the setup map
    result: null,      // basemap wrapper for the results map
    center: { lat: -8.6500, lng: 115.2150 },  // Denpasar, matches the seeded demo
    radius: 3000,
    categories: [],    // empty = every category
    providers: [],      // populated from /area/options with the configured ones
    filter: { bucket: '', category: '', provider: '' },
    poll: null,
  };

  const HERE_SCRIPTS = [
    'https://js.api.here.com/v3/3.1/mapsjs-core.js',
    'https://js.api.here.com/v3/3.1/mapsjs-service.js',
    'https://js.api.here.com/v3/3.1/mapsjs-mapevents.js',
    'https://js.api.here.com/v3/3.1/mapsjs-ui.js',
  ];

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      if (document.querySelector(`script[src="${src}"]`)) return resolve();
      const el = document.createElement('script');
      el.src = src; el.async = false;
      el.onload = resolve; el.onerror = () => reject(new Error(`Failed to load ${src}`));
      document.head.appendChild(el);
    });
  }

  function loadCss(href) {
    if (document.querySelector(`link[href="${href}"]`)) return;
    const el = document.createElement('link');
    el.rel = 'stylesheet'; el.href = href;
    document.head.appendChild(el);
  }

  /* ---------------------------------------------------------------- basemaps */

  // HERE Maps JS v3. Scripts must load in order: core, service, mapevents, ui.
  async function createHereMap(containerId, apiKey, onClick) {
    loadCss('https://js.api.here.com/v3/3.1/mapsjs-ui.css');
    for (const src of HERE_SCRIPTS) await loadScript(src);
    if (typeof H === 'undefined') throw new Error('HERE Maps JS did not load');

    const platform = new H.service.Platform({ apikey: apiKey });
    const layers = platform.createDefaultLayers();
    const container = document.getElementById(containerId);
    const map = new H.Map(container, layers.vector.normal.map, {
      center: { lat: AREA.center.lat, lng: AREA.center.lng },
      zoom: 13,
      pixelRatio: window.devicePixelRatio || 1,
    });
    new H.mapevents.Behavior(new H.mapevents.MapEvents(map));
    H.ui.UI.createDefault(map, layers);
    window.addEventListener('resize', () => map.getViewPort().resize());

    let circle = null;
    const markers = new H.map.Group();
    map.addObject(markers);

    if (onClick) {
      map.addEventListener('tap', (evt) => {
        const coord = map.screenToGeo(
          evt.currentPointer.viewportX, evt.currentPointer.viewportY
        );
        onClick({ lat: coord.lat, lng: coord.lng });
      });
    }

    return {
      kind: 'HERE',
      drawCircle(lat, lng, radius) {
        if (circle) map.removeObject(circle);
        circle = new H.map.Circle({ lat, lng }, radius, {
          style: { strokeColor: '#1d4ed8', lineWidth: 2, fillColor: 'rgba(29,78,216,0.10)' },
        });
        map.addObject(circle);
        map.getViewModel().setLookAtData({ bounds: circle.getBoundingBox() });
      },
      plotPoints(features) {
        markers.removeAll();
        features.forEach((f) => {
          const [lng, lat] = f.geometry.coordinates;
          const color = f.properties.color || '#7d8c95';
          const icon = new H.map.Icon(
            `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14">
               <circle cx="7" cy="7" r="5.5" fill="${color}" stroke="#fff" stroke-width="1.6"/>
             </svg>`,
            { size: { w: 14, h: 14 } }
          );
          const marker = new H.map.Marker({ lat, lng }, { icon });
          marker.setData(f.properties);
          markers.addObject(marker);
        });
        markers.addEventListener('tap', (evt) => {
          const p = evt.target.getData();
          if (p) showClusterPopup(p);
        });
        if (features.length) {
          map.getViewModel().setLookAtData({ bounds: markers.getBoundingBox() });
        }
      },
    };
  }

  // MapLibre + OpenStreetMap raster. The fallback when no HERE key is present.
  async function createLibreMap(containerId, onClick) {
    loadCss('https://unpkg.com/maplibre-gl@5.6.2/dist/maplibre-gl.css');
    await loadScript('https://unpkg.com/maplibre-gl@5.6.2/dist/maplibre-gl.js');
    if (typeof maplibregl === 'undefined') throw new Error('MapLibre did not load');

    const map = new maplibregl.Map({
      container: containerId,
      center: [AREA.center.lng, AREA.center.lat],
      zoom: 12,
      style: {
        version: 8,
        sources: {
          osm: {
            type: 'raster',
            tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            attribution: '© OpenStreetMap contributors',
          },
        },
        layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
      },
    });
    map.addControl(new maplibregl.NavigationControl(), 'top-right');
    if (onClick) map.on('click', (e) => onClick({ lat: e.lngLat.lat, lng: e.lngLat.lng }));

    const ready = new Promise((resolve) => map.on('load', resolve));

    // A geodesic circle as a polygon: MapLibre has no native circle-in-metres.
    function circlePolygon(lat, lng, radius, steps = 96) {
      const coords = [];
      const dx = radius / (111320 * Math.cos((lat * Math.PI) / 180));
      const dy = radius / 110574;
      for (let i = 0; i < steps; i++) {
        const theta = (i / steps) * 2 * Math.PI;
        coords.push([lng + dx * Math.cos(theta), lat + dy * Math.sin(theta)]);
      }
      coords.push(coords[0]);
      return { type: 'Feature', geometry: { type: 'Polygon', coordinates: [coords] } };
    }

    return {
      kind: 'MAPLIBRE',
      async drawCircle(lat, lng, radius) {
        await ready;
        const data = circlePolygon(lat, lng, radius);
        if (map.getSource('aoi')) { map.getSource('aoi').setData(data); }
        else {
          map.addSource('aoi', { type: 'geojson', data });
          map.addLayer({ id: 'aoi-fill', type: 'fill', source: 'aoi',
            paint: { 'fill-color': '#1d4ed8', 'fill-opacity': 0.10 } });
          map.addLayer({ id: 'aoi-line', type: 'line', source: 'aoi',
            paint: { 'line-color': '#1d4ed8', 'line-width': 2 } });
        }
        const dx = radius / (111320 * Math.cos((lat * Math.PI) / 180));
        const dy = radius / 110574;
        map.fitBounds([[lng - dx, lat - dy], [lng + dx, lat + dy]], { padding: 40 });
      },
      async plotPoints(features) {
        await ready;
        const data = { type: 'FeatureCollection', features };
        if (map.getSource('pts')) { map.getSource('pts').setData(data); return; }
        map.addSource('pts', { type: 'geojson', data });
        map.addLayer({
          id: 'pts', type: 'circle', source: 'pts',
          paint: {
            'circle-radius': 6,
            'circle-color': ['get', 'color'],
            'circle-stroke-color': '#fff',
            'circle-stroke-width': 1.5,
          },
        });
        map.on('click', 'pts', (e) => showClusterPopup(e.features[0].properties));
        map.on('mouseenter', 'pts', () => { map.getCanvas().style.cursor = 'pointer'; });
        map.on('mouseleave', 'pts', () => { map.getCanvas().style.cursor = ''; });
      },
    };
  }

  async function createMap(containerId, onClick) {
    const key = AREA.opts && AREA.opts.here_map_key;
    if (key) {
      try { return await createHereMap(containerId, key, onClick); }
      catch (err) {
        console.warn('HERE basemap failed, falling back to MapLibre:', err);
      }
    }
    return await createLibreMap(containerId, onClick);
  }

  function showClusterPopup(p) {
    const where = [
      p.in_here === true || p.in_here === 'true' ? 'HERE' : null,
      p.in_google === true || p.in_google === 'true' ? 'Google' : null,
      p.in_grab === true || p.in_grab === 'true' ? 'Grab' : null,
    ].filter(Boolean);
    qs('#drawerWrap').innerHTML = `
      <div class="modal-backdrop" onclick="if(event.target===this)window.areaCloseModal()">
        <div class="modal">
          <div class="modal-head">
            <div>
              <p class="eyebrow">${esc(p.bucket_label || p.bucket || '')}</p>
              <h2>${esc(p.name || 'Unnamed place')}</h2>
            </div>
            <button class="modal-close" onclick="window.areaCloseModal()">×</button>
          </div>
          <div class="modal-body">
            <div class="detail-grid">
              <div class="detail"><label>Address</label><strong>${esc(p.address || '—')}</strong></div>
              <div class="detail"><label>Category</label><strong>${esc(p.category || '—')}</strong></div>
              <div class="detail"><label>Present in</label><strong>${esc(where.join(', ') || 'None')}</strong></div>
              <div class="detail"><label>Missing from</label><strong>${
                esc(['HERE', 'Google', 'Grab'].filter((m) => !where.includes(m)).join(', ') || 'Nothing')
              }</strong></div>
            </div>
          </div>
        </div>
      </div>`;
  }
  window.areaCloseModal = () => { qs('#drawerWrap').innerHTML = ''; };

  /* ------------------------------------------------------------------- setup */

  function providerSummary() {
    const total = AREA.opts.providers.filter((p) => p.configured).length;
    const names = AREA.providers.join(', ') || 'none';
    return `Providers — <strong>${AREA.providers.length} of ${total}</strong> selected: <strong>${esc(names)}</strong>`;
  }

  function categorySummary() {
    const total = AREA.opts.categories.length;
    const selected = AREA.categories.length === 0 ? total : AREA.categories.length;
    const everything = selected === total;
    return `<strong>${selected} of ${total}</strong> categories selected` +
      (everything ? ' — every POI type in the circle' : ' — cost scales with this number');
  }

  function categoryChips() {
    const all = AREA.opts.categories;
    return all.map((c) => {
      const on = AREA.categories.length === 0 || AREA.categories.includes(c.value);
      return `<button type="button" class="city-chip${on ? ' active' : ''}"
                onclick="window.areaToggleCat('${c.value}')">${esc(c.label)}</button>`;
    }).join('');
  }

  function providerChips() {
    return AREA.opts.providers.map((p) => {
      const on = AREA.providers.includes(p.value) && p.configured;
      // An unconfigured provider is not selectable. There is no substitute data,
      // so offering it would only produce a comparison missing a whole leg.
      const attrs = p.configured
        ? `class="city-chip${on ? ' active' : ''}" onclick="window.areaToggleProvider('${p.value}')"`
        : `class="city-chip" style="opacity:.45;cursor:not-allowed" disabled`;
      return `<button type="button" ${attrs} title="${esc(p.note || '')}">${esc(p.label)}<span>${
        p.configured ? 'READY' : 'NO API KEY'}</span></button>`;
    }).join('');
  }

  function unconfiguredNotice() {
    const missing = AREA.opts.providers.filter((p) => !p.configured);
    let html = '';

    if (AREA.providers.length === 1) {
      html += `<div class="alert info" style="margin-top:12px">
        <strong>Single-source inventory.</strong>
        This run will list everything <b>${esc(AREA.providers[0])}</b> has in the circle.
        It cannot show coverage gaps — a place missing from the others was never asked
        about. Add a second provider to compare.
      </div>`;
    }
    if (!AREA.providers.length) {
      html += `<div class="alert warn" style="margin-top:12px">
        <strong>Select at least one provider.</strong>
      </div>`;
    }
    if (missing.length) {
      html += `<div class="alert warn" style="margin-top:12px">
        <strong>${missing.length} provider${missing.length > 1 ? 's are' : ' is'} not configured
        and cannot be compared:</strong>
        <ul style="margin:8px 0 0 18px">${missing.map((p) =>
          `<li><b>${esc(p.label)}</b> — ${esc(p.note)}</li>`).join('')}</ul>
      </div>`;
    }
    return html;
  }

  function estimateBox() {
    const e = AREA.estimate;
    if (!e) return `<div class="cost-box"><p class="muted">Set an area, then estimate the cost before running.</p></div>`;
    const rows = e.providers.map((p) => `
      <tr>
        <td><strong>${esc(p.provider)}</strong><br><small class="muted">${esc(p.note || '')}</small></td>
        <td>${p.calls_per_tile}/tile</td>
        <td>${p.calls_expected.toLocaleString()}</td>
        <td>${p.cost_expected_usd == null ? 'rate not configured' : '$' + p.cost_expected_usd.toFixed(2)}</td>
      </tr>`).join('');
    const heavy = (e.cost_expected_total_usd || 0) >= 20;
    return `
      <div class="cost-box${heavy ? ' cost-warn' : ''}">
        <div class="cost-big">$${(e.cost_expected_total_usd || 0).toFixed(2)}<small class="muted"> expected</small></div>
        <p class="muted" style="margin:4px 0 10px">${e.tiles} tiles · ${esc(e.categories.length)} categories${
          e.cost_is_complete ? '' : ' · one or more rates are not configured, so this total is incomplete'}</p>
        <table>
          <thead><tr><th>Provider</th><th>Calls</th><th>Expected</th><th>Cost</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
        <p class="muted" style="margin-top:10px;font-size:11px">${esc(e.note)}</p>
      </div>`;
  }

  // Repaint only the parts that changed.
  //
  // Re-rendering the whole setup panel would replace #areaPickerMap with a fresh empty
  // div while AREA.picker still points at the old, now-detached map — so the map simply
  // vanished on every category click. Selection state lives in AREA, not the DOM, so
  // the chips and the estimate box are the only things that need repainting.
  function refreshChoices() {
    const cats = document.getElementById('areaCatStrip');
    const provs = document.getElementById('areaProvStrip');
    const summary = document.getElementById('areaCatSummary');
    const notice = document.getElementById('areaProvNotice');
    const provSummary = document.getElementById('areaProvSummary');
    if (provSummary) provSummary.innerHTML = providerSummary();
    if (cats) cats.innerHTML = categoryChips();
    if (provs) provs.innerHTML = providerChips();
    if (summary) summary.innerHTML = categorySummary();
    if (notice) notice.innerHTML = unconfiguredNotice();
    const est = document.getElementById('areaEstimate');
    if (est) est.innerHTML = estimateBox();
    const run = document.getElementById('areaRunBtn');
    if (run) {
      run.disabled = AREA.providers.length === 0;
      run.title = run.disabled ? 'Select at least one provider' : '';
      run.textContent = AREA.providers.length === 1 ? 'Run single-source inventory' : 'Run comparison';
    }
  }

  window.areaToggleCat = (value) => {
    const all = AREA.opts.categories.map((c) => c.value);
    // An empty list means "everything", so materialise it before removing one.
    if (AREA.categories.length === 0) AREA.categories = all.slice();
    AREA.categories = AREA.categories.includes(value)
      ? AREA.categories.filter((v) => v !== value)
      : AREA.categories.concat([value]);
    if (AREA.categories.length === all.length) AREA.categories = [];
    AREA.estimate = null;
    refreshChoices();
  };

  window.areaAllCategories = () => {
    AREA.categories = [];          // empty means every category
    AREA.estimate = null;
    refreshChoices();
  };

  // The seven categories this deployment normally reports on.
  window.areaCoreCategories = () => {
    AREA.categories = AREA.opts.categories.filter((c) => c.core).map((c) => c.value);
    AREA.estimate = null;
    refreshChoices();
  };

  window.areaNoCategories = () => {
    // One placeholder keeps the list non-empty, so it cannot be mistaken for "all".
    AREA.categories = [AREA.opts.categories[0].value];
    AREA.estimate = null;
    refreshChoices();
  };

  window.areaToggleProvider = (value) => {
    AREA.providers = AREA.providers.includes(value)
      ? AREA.providers.filter((v) => v !== value)
      : AREA.providers.concat([value]);
    AREA.estimate = null;
    refreshChoices();
  };

  window.areaSetRadius = (value) => {
    AREA.radius = Math.max(100, Math.min(20000, Number(value) || 3000));
    AREA.estimate = null;
    if (AREA.picker) AREA.picker.drawCircle(AREA.center.lat, AREA.center.lng, AREA.radius);
    qs('#areaEstimate').innerHTML = estimateBox();
  };

  window.areaSetCenterText = () => {
    const lat = Number(qs('#areaLat').value), lng = Number(qs('#areaLng').value);
    if (Number.isFinite(lat) && Number.isFinite(lng)) {
      AREA.center = { lat, lng };
      AREA.estimate = null;
      if (AREA.picker) AREA.picker.drawCircle(lat, lng, AREA.radius);
      qs('#areaEstimate').innerHTML = estimateBox();
    }
  };

  window.areaEstimate = async () => {
    const btn = qs('#areaEstimateBtn');
    btn.disabled = true; btn.textContent = 'Estimating…';
    try {
      AREA.estimate = await api('/area/estimate', {
        method: 'POST',
        body: JSON.stringify({
          center_lat: AREA.center.lat, center_lng: AREA.center.lng,
          radius_m: AREA.radius, categories: AREA.categories, providers: AREA.providers,
        }),
      });
      qs('#areaEstimate').innerHTML = estimateBox();
    } catch (err) {
      qs('#areaEstimate').innerHTML = `<div class="alert error">${esc(err.message)}</div>`;
    } finally {
      btn.disabled = false; btn.textContent = 'Estimate cost';
    }
  };

  window.areaRun = async () => {
    if (!state.project) { alert('Select a project first.'); return; }
    if (!AREA.providers.length) { alert('Select at least one provider.'); return; }
    const cost = AREA.estimate ? AREA.estimate.cost_expected_total_usd : null;
    const warning = cost == null
      ? 'Cost has not been estimated. Run anyway?'
      : `This is expected to cost about $${cost.toFixed(2)} in provider API calls. Continue?`;
    if (!confirm(warning)) return;

    const btn = qs('#areaRunBtn');
    btn.disabled = true; btn.textContent = 'Starting…';
    try {
      AREA.sweep = await api('/area/sweeps', {
        method: 'POST',
        body: JSON.stringify({
          project_id: state.project.id,
          center_lat: AREA.center.lat, center_lng: AREA.center.lng,
          radius_m: AREA.radius, categories: AREA.categories, providers: AREA.providers,
        }),
      });
      startPolling();
    } catch (err) {
      alert(err.message);
      btn.disabled = false; btn.textContent = 'Run three-map comparison';
    }
  };

  function startPolling() {
    stopPolling();
    renderResults();
    AREA.poll = setInterval(async () => {
      try {
        AREA.sweep = await api(`/area/sweeps/${AREA.sweep.id}`);
        renderResults();
        if (['COMPLETED', 'FAILED', 'ABORTED_BUDGET'].includes(AREA.sweep.status)) {
          stopPolling();
          await renderResultMap();
          await renderClusterTable();
        }
      } catch (err) {
        stopPolling();
      }
    }, 2500);
  }

  function stopPolling() {
    if (AREA.poll) { clearInterval(AREA.poll); AREA.poll = null; }
  }

  function historyPanel() {
    const rows = AREA.history || [];
    if (!rows.length) return '';
    const badge = (s) => s === 'COMPLETED' ? '<span class="tag green">COMPLETE</span>'
      : s === 'FAILED' ? '<span class="tag red">FAILED</span>'
      : ['RUNNING', 'PENDING'].includes(s) ? '<span class="tag blue">RUNNING</span>'
      : '<span class="tag amber">PARTIAL</span>';
    return `<div class="panel" style="margin-top:14px">
      <div class="panel-title"><h3>Previous runs</h3>
        <span class="muted">Open a finished run to view its results and download the data</span></div>
      <div class="table-shell"><table class="table">
        <thead><tr><th>Run</th><th>Area</th><th>Sources</th><th>Places</th><th>Status</th><th></th></tr></thead>
        <tbody>${rows.map((s) => `
          <tr>
            <td><strong>${esc(s.label)}</strong><br><small class="muted">${
              s.started_at ? esc(s.started_at.replace('T', ' ').slice(0, 16)) : ''}</small></td>
            <td>${Number(s.radius_m).toFixed(0)} m</td>
            <td>${esc((s.providers || []).join(', '))}<br><small class="muted">${esc(s.mode || '')}</small></td>
            <td>${(s.clusters_total || 0).toLocaleString()}</td>
            <td>${badge(s.status)}</td>
            <td style="white-space:nowrap">
              <button class="button outline" onclick="window.areaOpenSweep(${s.id})">Open</button>
              ${s.clusters_total ? `<button class="button outline"
                onclick="window.areaExportXlsx(${s.id})" title="Download this run as Excel">Excel</button>` : ''}
            </td>
          </tr>`).join('')}</tbody>
      </table></div>
    </div>`;
  }

  window.areaOpenSweep = async (id) => {
    AREA.sweep = await api(`/area/sweeps/${id}`);
    AREA.result = null;                    // force a fresh map for this run
    AREA.filter = { bucket: '', category: '', provider: '' };
    renderResults();
    await renderResultMap();
    await renderClusterTable();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  async function renderSetup() {
    qs('#areaSetup').innerHTML = `
      <div class="panel">
        <div class="panel-title"><h3>1 · Choose the area</h3></div>
        <p class="muted">Click the map to place the centre, or type coordinates. The circle is what all three providers are asked about.</p>
        <div id="areaPickerMap" class="map-canvas" style="height:380px;border-radius:10px;overflow:hidden"></div>
        <div class="cov-grid" style="margin-top:12px">
          <label>Centre latitude<input id="areaLat" type="number" step="0.00001" value="${AREA.center.lat}" onchange="window.areaSetCenterText()"></label>
          <label>Centre longitude<input id="areaLng" type="number" step="0.00001" value="${AREA.center.lng}" onchange="window.areaSetCenterText()"></label>
        </div>
        <label>Radius in metres
          <input id="areaRadius" type="number" step="100" min="100" max="20000" value="${AREA.radius}"
                 onchange="window.areaSetRadius(this.value)">
        </label>
      </div>

      <div class="panel" style="margin-top:14px">
        <div class="panel-title">
          <h3>2 · Choose what to compare</h3>
          <div style="display:flex;gap:8px">
            <button type="button" class="button outline" onclick="window.areaAllCategories()">All categories</button>
            <button type="button" class="button outline" onclick="window.areaCoreCategories()">Core 7</button>
            <button type="button" class="button outline" onclick="window.areaNoCategories()">Clear</button>
          </div>
        </div>
        <p class="muted" id="areaCatSummary">${categorySummary()}</p>
        <div class="city-strip" id="areaCatStrip">${categoryChips()}</div>
        <p class="muted" style="margin-top:14px" id="areaProvSummary">${providerSummary()}</p>
        <div class="city-strip" id="areaProvStrip">${providerChips()}</div>
        <div id="areaProvNotice">${unconfiguredNotice()}</div>
      </div>

      <div class="panel" style="margin-top:14px">
        <div class="panel-title"><h3>3 · Check the cost, then run</h3></div>
        <div id="areaEstimate">${estimateBox()}</div>
        <div style="display:flex;gap:10px;margin-top:12px">
          <button class="button outline" id="areaEstimateBtn" onclick="window.areaEstimate()">Estimate cost</button>
          <button class="primary" id="areaRunBtn" onclick="window.areaRun()"
                  ${AREA.providers.length === 0 ? 'disabled title="Select at least one provider"' : ''}>
            ${AREA.providers.length === 1 ? 'Run single-source inventory' : 'Run comparison'}</button>
        </div>
      </div>
      ${historyPanel()}`;

    if (!AREA.picker) {
      try {
        AREA.picker = await createMap('areaPickerMap', (coord) => {
          AREA.center = coord;
          AREA.estimate = null;
          qs('#areaLat').value = coord.lat.toFixed(5);
          qs('#areaLng').value = coord.lng.toFixed(5);
          AREA.picker.drawCircle(coord.lat, coord.lng, AREA.radius);
          qs('#areaEstimate').innerHTML = estimateBox();
        });
        await AREA.picker.drawCircle(AREA.center.lat, AREA.center.lng, AREA.radius);
      } catch (err) {
        qs('#areaPickerMap').innerHTML =
          `<div class="map-fallback"><div><strong>No basemap available.</strong>
           <p>Coordinates can still be typed in below. (${esc(err.message)})</p></div></div>`;
      }
    }
  }

  /* ----------------------------------------------------------------- results */

  function providerFilterBar() {
    const used = AREA.sweep.providers || [];
    const counts = AREA.sweep.provider_counts || {};
    const chip = (value, label, n) => {
      const on = AREA.filter.provider === value;
      return `<button type="button" class="city-chip${on ? ' active' : ''}"
        onclick="window.areaFilterProvider('${value}')">${esc(label)}<span>${n}</span></button>`;
    };
    return `<div class="city-strip" style="margin:10px 0 4px">
      ${chip('', 'All records', AREA.sweep.clusters_total || 0)}
      ${used.map((pv) => chip(pv, pv, counts[pv] || 0)).join('')}
    </div>
    <p class="muted" style="margin:0 0 10px;font-size:11px">
      Filter to one source to see exactly what that map holds in this area.</p>`;
  }

  function bucketCards() {
    const counts = AREA.sweep.bucket_counts || {};
    const legend = (AREA.opts.buckets || []);
    return `<div class="sample-grid">${legend.map((b) => `
      <article class="sample-card" style="cursor:pointer;border-left:4px solid ${b.color}"
               onclick="window.areaFilterBucket('${b.value}')">
        <div class="sample-head">
          <div class="sample-name"><strong>${(counts[b.value] || 0).toLocaleString()}</strong>
          <span>${esc(b.label)}</span></div>
        </div>
      </article>`).join('')}</div>`;
  }

  function providerTotals() {
    const c = AREA.sweep.provider_counts || {};
    const breakdown = AREA.sweep.cost_breakdown || {};
    return `<div class="table-shell"><table class="table">
      <thead><tr><th>Provider</th><th>Places in circle</th><th>API calls</th><th>Cost</th><th>Coverage</th></tr></thead>
      <tbody>${['HERE', 'GOOGLE', 'GRAB'].map((p) => {
        const b = breakdown[p] || {};
        const partial = (AREA.sweep.partial_providers || []).includes(p);
        return `<tr>
          <td><strong>${p}</strong></td>
          <td>${(c[p] || 0).toLocaleString()}</td>
          <td>${(b.api_calls || 0).toLocaleString()}</td>
          <td>${b.cost_usd == null ? 'unpriced' : '$' + Number(b.cost_usd).toFixed(2)}</td>
          <td>${!AREA.sweep.providers.includes(p)
            ? '<span class="tag gray">NOT COMPARED</span>'
            : (partial
              ? `<span class="tag amber">PARTIAL</span><br><small class="muted">${esc(b.error || '')}</small>`
              : '<span class="tag green">COMPLETE</span>')}</td>
        </tr>`;
      }).join('')}</tbody></table></div>`;
  }

  function categoryTable() {
    const matrix = AREA.sweep.category_matrix || {};
    const keys = Object.keys(matrix).sort((a, b) => (matrix[b].clusters || 0) - (matrix[a].clusters || 0));
    if (!keys.length) return '';
    return `<div class="panel" style="margin-top:14px">
      <div class="panel-title"><h3>By category</h3></div>
      <div class="table-shell"><table class="table">
        <thead><tr><th>Category</th><th>Places</th><th>HERE</th><th>Google</th><th>Grab</th><th>In all three</th><th>In one map only</th></tr></thead>
        <tbody>${keys.map((k) => {
          const r = matrix[k];
          return `<tr>
            <td><strong>${esc(k)}</strong></td>
            <td>${r.clusters}</td><td>${r.HERE}</td><td>${r.GOOGLE}</td><td>${r.GRAB}</td>
            <td>${r.all_three}</td><td>${r.single_provider}</td>
          </tr>`;
        }).join('')}</tbody></table></div>
    </div>`;
  }

  function stageTrack() {
    const s = AREA.sweep;
    const stages = ['QUEUED', 'SWEEPING_HERE', 'SWEEPING_GOOGLE', 'SWEEPING_GRAB', 'MATCHING', 'FINISHED'];
    const at = stages.indexOf(s.stage);
    return `<div class="stage-track">${stages.map((st, i) => {
      const cls = s.stage === st ? 'active' : (at > i ? 'done' : '');
      return `<div class="${cls}">${st.replace('SWEEPING_', '').replace('_', ' ')}</div>`;
    }).join('')}</div>`;
  }

  window.areaFilterProvider = async (value) => {
    AREA.filter.provider = AREA.filter.provider === value ? '' : value;
    // Repaint only the chip bar. Re-rendering the whole results panel would replace
    // the map container while AREA.result still points at the detached map.
    const bar = document.getElementById('areaProvFilter');
    if (bar) bar.innerHTML = providerFilterBar();
    await renderResultMap();
    await renderClusterTable();
  };

  window.areaFilterBucket = async (bucket) => {
    AREA.filter.bucket = AREA.filter.bucket === bucket ? '' : bucket;
    await renderResultMap();
    await renderClusterTable();
  };

  window.areaBack = async () => {
    stopPolling();
    try {
      AREA.history = (await api(`/area/sweeps?project_id=${state.project.id}&limit=15`)).sweeps;
    } catch { /* keep whatever we had */ }
    AREA.sweep = null;
    AREA.result = null;
    AREA.filter = { bucket: '', category: '', provider: '' };
    render();
  };

  function renderResults() {
    const s = AREA.sweep;
    const running = ['PENDING', 'RUNNING'].includes(s.status);
    qs('#areaSetup').innerHTML = `
      <div class="panel">
        <div class="panel-title">
          <h3>${esc(s.label)}</h3>
          <button class="button outline" onclick="window.areaBack()">New comparison</button>
        </div>
        ${stageTrack()}
        ${s.error ? `<div class="alert error">${esc(s.error)}</div>` : ''}
        ${(s.partial_providers || []).length ? `<div class="alert warn">
          <strong>Partial coverage:</strong> ${esc((s.partial_providers || []).join(', '))} stopped early on a
          budget cap. Gaps attributed to those providers are not reliable.</div>` : ''}
        ${running ? `<p class="muted">Running… ${(s.api_calls || 0).toLocaleString()} API calls so far.</p>` : ''}
      </div>

      ${!running && s.is_comparison === false ? `
      <div class="panel" style="margin-top:14px">
        <div class="panel-title">
          <h3>${(s.clusters_total || 0).toLocaleString()} places found in ${esc((s.providers || []).join(''))}</h3>
          <span class="muted">${(s.api_calls || 0).toLocaleString()} calls · ${
            s.actual_cost_usd == null ? 'cost partly unpriced' : '$' + Number(s.actual_cost_usd).toFixed(2)}</span>
        </div>
        <div class="alert info">
          <strong>Single-source inventory.</strong> Only ${esc((s.providers || []).join(''))} was swept,
          so this is a list of what that map holds here — not a coverage comparison.
          Nothing on this page says another provider is missing a place.
        </div>
      </div>` : ''}

      ${!running && s.is_comparison !== false ? `
      <div class="panel" style="margin-top:14px">
        <div class="panel-title"><h3>${(s.clusters_total || 0).toLocaleString()} distinct places found</h3>
        <span class="muted">${(s.api_calls || 0).toLocaleString()} calls · ${
          s.actual_cost_usd == null ? 'cost partly unpriced' : '$' + Number(s.actual_cost_usd).toFixed(2)}</span></div>
        <p class="muted">Click a card to filter the map and table.</p>
        ${bucketCards()}
      </div>` : ''}

      ${!running ? `
      <div class="panel" style="margin-top:14px">
        <div class="panel-title"><h3>Per provider</h3></div>
        ${providerTotals()}
        <div id="areaProvFilter">${providerFilterBar()}</div>
      </div>

      ${categoryTable()}

      <div class="panel" style="margin-top:14px">
        <div class="panel-title"><h3>Comparison map</h3>
          <button class="primary" onclick="window.areaExportXlsx()">↓ Export Excel</button>
          <button class="button outline" onclick="window.areaExport()">CSV (filtered)</button></div>
        <div id="areaResultMap" class="map-canvas" style="height:460px;border-radius:10px;overflow:hidden"></div>
        <div class="map-legend" style="margin-top:10px">${(AREA.opts.buckets || []).map((b) =>
          `<span><i style="background:${b.color}"></i>${esc(b.label)}</span>`).join('')}</div>
      </div>

      <div class="panel" style="margin-top:14px" id="areaTablePanel">
        <div class="panel-title"><h3>Places</h3></div>
        <p class="muted">Loading…</p>
      </div>` : ''}`;
  }

  function download(url, filename) {
    return fetch(url, { headers: { Authorization: `Bearer ${state.token}` } })
      .then((r) => { if (!r.ok) throw new Error(`Download failed (${r.status})`); return r.blob(); })
      .then((blob) => {
        const href = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = href; a.download = filename;
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(href);
      })
      .catch((err) => alert(err.message));
  }

  // Excel for one sweep. An inventory exports a single POI sheet; a comparison
  // exports one sheet per presence bucket in the same file.
  window.areaExportXlsx = (id) => {
    const sweepId = id || (AREA.sweep && AREA.sweep.id);
    if (!sweepId) return;
    return download(`/api/v1/area/sweeps/${sweepId}/export.xlsx`,
                    `GeoDiscover_area_${sweepId}.xlsx`);
  };

  window.areaExport = () => {
    const q = new URLSearchParams();
    if (AREA.filter.bucket) q.set('bucket', AREA.filter.bucket);
    if (AREA.filter.category) q.set('category', AREA.filter.category);
    if (AREA.filter.provider) q.set('provider', AREA.filter.provider);
    // Authenticated route, so fetch with the token and save the blob rather than
    // navigating, which would send no Authorization header.
    download(`/api/v1/area/sweeps/${AREA.sweep.id}/export.csv?${q}`,
             `area_comparison_${AREA.sweep.id}.csv`);
  };

  async function renderResultMap() {
    if (!qs('#areaResultMap')) return;
    const q = new URLSearchParams();
    if (AREA.filter.bucket) q.set('bucket', AREA.filter.bucket);
    if (AREA.filter.category) q.set('category', AREA.filter.category);
    if (AREA.filter.provider) q.set('provider', AREA.filter.provider);
    const data = await api(`/area/sweeps/${AREA.sweep.id}/map.geojson?${q}`);
    if (!AREA.result) {
      try { AREA.result = await createMap('areaResultMap', null); }
      catch (err) {
        qs('#areaResultMap').innerHTML =
          `<div class="map-fallback"><div><strong>No basemap available.</strong>
           <p>${esc(err.message)}</p></div></div>`;
        return;
      }
      await AREA.result.drawCircle(AREA.sweep.center.lat, AREA.sweep.center.lng, AREA.sweep.radius_m);
    }
    await AREA.result.plotPoints(data.features);
  }

  async function renderClusterTable() {
    const panel = qs('#areaTablePanel');
    if (!panel) return;
    const q = new URLSearchParams({ limit: '250' });
    if (AREA.filter.bucket) q.set('bucket', AREA.filter.bucket);
    if (AREA.filter.category) q.set('category', AREA.filter.category);
    if (AREA.filter.provider) q.set('provider', AREA.filter.provider);
    const data = await api(`/area/sweeps/${AREA.sweep.id}/clusters?${q}`);
    const yes = (v) => (v ? '<span class="tag green">YES</span>' : '<span class="tag gray">—</span>');
    panel.innerHTML = `
      <div class="panel-title">
        <h3>Places ${AREA.filter.provider ? `· in ${esc(AREA.filter.provider)}` : ''}${
          AREA.filter.bucket ? ` · ${esc(AREA.filter.bucket)}` : ''}</h3>
        <span class="muted">${data.total.toLocaleString()} total${
          data.total > data.clusters.length ? `, showing ${data.clusters.length}` : ''}</span>
      </div>
      ${AREA.filter.bucket ? `<button class="button outline" onclick="window.areaFilterBucket('${AREA.filter.bucket}')">Clear filter</button>` : ''}
      <div class="table-shell"><table class="table">
        <thead><tr><th>Name</th><th>Category</th><th>HERE</th><th>Google</th><th>Grab</th><th>Presence</th><th>Address</th></tr></thead>
        <tbody>${data.clusters.map((c) => `
          <tr>
            <td><strong>${esc(c.name || '—')}</strong></td>
            <td>${esc(c.category_label || c.category)}</td>
            <td>${yes(c.here)}</td><td>${yes(c.google)}</td><td>${yes(c.grab)}</td>
            <td><span class="tag blue">${esc(c.bucket_label)}</span></td>
            <td><small>${esc(c.address || '')}</small></td>
          </tr>`).join('')}</tbody>
      </table></div>`;
  }

  /* -------------------------------------------------------------------- root */

  async function render() {
    qs('#content').innerHTML = `
      <div class="page-head">
        <div>
          <p class="eyebrow">THREE-MAP COMPARISON</p>
          <h2>Area Comparison</h2>
          <p class="muted">Draw a circle once. HERE, Google and Grab are each swept across every
          POI category inside it, then resolved into one list showing which maps know about each place.</p>
        </div>
      </div>
      <div id="areaSetup"></div>`;
    if (AREA.sweep) { renderResults(); await renderResultMap(); await renderClusterTable(); }
    else await renderSetup();
  }

  window.areaView = async function areaView() {
    if (!AREA.opts) {
      AREA.opts = await api('/area/options');
      AREA.providers = AREA.opts.providers.filter((p) => p.configured).map((p) => p.value);
    }
    // Past runs stay reachable after a reload; without this the only way back to a
    // finished sweep was to re-run and pay for it again.
    try {
      AREA.history = (await api(`/area/sweeps?project_id=${state.project.id}&limit=15`)).sweeps;
    } catch { AREA.history = []; }
    if (!AREA.sweep) { AREA.picker = null; }
    await render();
  };
})();
