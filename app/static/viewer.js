// Geospatial Measurement Engine - Interactive Map Viewer

(function () {
  'use strict';

  // --- State ---
  const state = {
    file: null, // FileDetailResponse
    geojsonData: null, // GeoJSON FeatureCollection
    selectedUnit: 'ha', // 'm2' | 'ha' | 'acres' | 'km2'
    selectedFeatureIndex: null, // integer feature index
    activeFilter: 'all', // 'all' | 'Polygon' | 'Line' | 'Point' | 'issues'
    activeTab: 'features', // 'features' | 'measure' | 'verify'
    layersByIndex: new Map(), // index -> Leaflet layer
    featuresByIndex: new Map(), // index -> GeoJSON feature
    filteredIndices: [], // list of feature indices matching activeFilter
    renderedCount: 0, // for lazy chunked rendering
    chunkSize: 100,
  };

  // --- Conversions ---
  const AREA_CONVERSIONS = {
    m2: { label: 'm²', factor: 1.0, decimals: 1 },
    ha: { label: 'ha', factor: 0.0001, decimals: 2 },
    acres: { label: 'acres', factor: 0.000247105, decimals: 2 },
    km2: { label: 'km²', factor: 0.000001, decimals: 4 },
  };

  // --- DOM Elements ---
  const fileInput = document.getElementById('file-input');
  const toolbarFilename = document.getElementById('toolbar-filename');
  const topUploadBtn = document.getElementById('top-upload-btn');
  const railUploadBtn = document.getElementById('rail-upload-btn');
  const railFeaturesBtn = document.getElementById('rail-features-btn');
  const railDownloadBtn = document.getElementById('rail-download-btn');
  const railThemeBtn = document.getElementById('rail-theme-btn');

  // Tabs
  const tabBtnFeatures = document.getElementById('tab-btn-features');
  const tabBtnMeasure = document.getElementById('tab-btn-measure');
  const tabBtnVerify = document.getElementById('tab-btn-verify');
  const panelFeatures = document.getElementById('panel-features');
  const panelMeasure = document.getElementById('panel-measure');
  const panelVerify = document.getElementById('panel-verify');

  // Features list & filter chips
  const featuresList = document.getElementById('features-list');
  const filterChips = document.querySelectorAll('.filter-chip');

  // Measure tab elements
  const measureEmptyMsg = document.getElementById('measure-empty-msg');
  const measureDetail = document.getElementById('measure-detail');
  const measureName = document.getElementById('measure-name');
  const measureType = document.getElementById('measure-type');
  const measureBadge = document.getElementById('measure-badge');
  const measureBigVal = document.getElementById('measure-big-val');
  const measureOtherUnits = document.getElementById('measure-other-units');
  const rowDimension = document.getElementById('row-dimension');
  const labelDimension = document.getElementById('label-dimension');
  const valDimension = document.getElementById('val-dimension');
  const valMethod = document.getElementById('val-method');
  const valMeasurementCrs = document.getElementById('val-measurement-crs');
  const valSourceCrs = document.getElementById('val-source-crs');
  const valSourceLayer = document.getElementById('val-source-layer');
  const propertiesTable = document.getElementById('properties-table');

  // Verify tab elements
  const verifyEmptyMsg = document.getElementById('verify-empty-msg');
  const verifyDetail = document.getElementById('verify-detail');
  const verifyProjCrs = document.getElementById('verify-proj-crs');
  const verifyProjVal = document.getElementById('verify-proj-val');
  const verifyGeodVal = document.getElementById('verify-geod-val');
  const verifyDeltaBadge = document.getElementById('verify-delta-badge');
  const verifyDeltaText = document.getElementById('verify-delta-text');
  const verifyWarningsSection = document.getElementById('verify-warnings-section');
  const verifyFeatureWarnings = document.getElementById('verify-feature-warnings');
  const verifyFileCrs = document.getElementById('verify-file-crs');
  const verifyDuration = document.getElementById('verify-duration');
  const verifyFileWarningsContainer = document.getElementById('verify-file-warnings-container');
  const verifyFileWarnings = document.getElementById('verify-file-warnings');

  // Stats strip
  const statsArea = document.getElementById('stats-area');
  const statsLength = document.getElementById('stats-length');
  const statsMaxDelta = document.getElementById('stats-max-delta');
  const statsFeatures = document.getElementById('stats-features');

  // --- Theme State & Toggle ---
  const themeIcon = document.getElementById('theme-icon');
  let currentTheme = localStorage.getItem('viewer_theme') || 'light';
  let tileLayer = null;

  function applyTheme(theme) {
    currentTheme = theme;
    localStorage.setItem('viewer_theme', theme);
    document.documentElement.setAttribute('data-theme', theme);

    if (themeIcon) {
      themeIcon.className = theme === 'dark' ? 'ti ti-sun' : 'ti ti-moon';
    }

    if (tileLayer) {
      const tileUrl = theme === 'dark'
        ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
        : 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png';
      tileLayer.setUrl(tileUrl);
    }
  }

  function toggleTheme() {
    const nextTheme = currentTheme === 'dark' ? 'light' : 'dark';
    applyTheme(nextTheme);
    announce(`Theme switched to ${nextTheme} mode.`);
  }

  // --- Map & Layers ---
  let map = null;
  let activeGeojsonGroup = null;

  function initMap() {
    map = L.map('map', {
      center: [20.5937, 78.9629],
      zoom: 5,
      zoomControl: false,
    });

    L.control.zoom({ position: 'topright' }).addTo(map);

    const tileUrl = currentTheme === 'dark'
      ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
      : 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png';

    // CARTO Positron / Dark Matter tiles with attribution
    tileLayer = L.tileLayer(tileUrl, {
      subdomains: 'abcd',
      maxZoom: 20,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    }).addTo(map);

    activeGeojsonGroup = L.featureGroup().addTo(map);
  }

  // --- Feature Styling Functions ---
  function getNormalStyle(feature) {
    const geomType = feature.geometry?.type || '';
    const status = feature.properties?.status;

    if (status === 'ERROR') {
      return {
        color: '#791F1F',
        weight: 1.5,
        dashArray: '4 4',
        fillColor: '#FCEBEB',
        fillOpacity: 0.2,
      };
    }
    if (status === 'SKIPPED') {
      return {
        color: '#7A4A00',
        weight: 1.5,
        dashArray: '4 4',
        fillColor: '#FDF3E1',
        fillOpacity: 0.15,
      };
    }

    if (geomType.includes('Polygon')) {
      return {
        color: '#1F3A5F',
        weight: 1.5,
        opacity: 1,
        fillColor: '#1F3A5F',
        fillOpacity: 0.12,
        dashArray: null,
      };
    }
    if (geomType.includes('Line')) {
      return {
        color: '#1F3A5F',
        weight: 2.5,
        opacity: 1,
        dashArray: '7 4',
      };
    }
    return {
      radius: 5,
      fillColor: '#FFFFFF',
      color: '#1B2430',
      weight: 2,
      opacity: 1,
      fillOpacity: 1,
    };
  }

  function getHoverStyle(feature) {
    const geomType = feature.geometry?.type || '';
    if (geomType.includes('Polygon')) {
      return { weight: 2.0, fillOpacity: 0.18 };
    }
    if (geomType.includes('Line')) {
      return { weight: 3.5 };
    }
    return { radius: 7 };
  }

  function getSelectedStyle(feature) {
    const geomType = feature.geometry?.type || '';
    if (geomType.includes('Polygon')) {
      return {
        color: '#B86E00',
        weight: 2.5,
        fillColor: '#E08A00',
        fillOpacity: 0.26,
        dashArray: null,
      };
    }
    if (geomType.includes('Line')) {
      return {
        color: '#B86E00',
        weight: 3.0,
        dashArray: null,
      };
    }
    return {
      radius: 6,
      fillColor: '#E08A00',
      color: '#B86E00',
      weight: 2.5,
      fillOpacity: 1,
    };
  }

  function styleLayer(layer, feature, isSelected, isHovered) {
    if (!layer) return;
    if (isSelected) {
      const s = getSelectedStyle(feature);
      if (layer.setStyle) layer.setStyle(s);
    } else if (isHovered) {
      const h = getHoverStyle(feature);
      if (layer.setStyle) layer.setStyle(h);
    } else {
      const n = getNormalStyle(feature);
      if (layer.setStyle) layer.setStyle(n);
    }
  }

  // --- Helpers ---
  function getFeatureName(feature, index) {
    const p = feature.properties || {};
    if (p.name !== undefined && p.name !== null && String(p.name).trim() !== '') {
      return String(p.name);
    }
    if (p.Name !== undefined && p.Name !== null && String(p.Name).trim() !== '') {
      return String(p.Name);
    }
    return `Feature ${index + 1}`;
  }

  function formatAreaValue(valM2) {
    if (valM2 === null || valM2 === undefined || isNaN(valM2)) return '—';
    const conv = AREA_CONVERSIONS[state.selectedUnit] || AREA_CONVERSIONS.ha;
    const converted = valM2 * conv.factor;
    return `${Number(converted.toFixed(conv.decimals)).toLocaleString()} ${conv.label}`;
  }

  function formatLengthValue(valM) {
    if (valM === null || valM === undefined || isNaN(valM)) return '—';
    if (valM >= 1000) {
      return `${Number((valM / 1000).toFixed(2)).toLocaleString()} km`;
    }
    return `${Number(valM.toFixed(1)).toLocaleString()} m`;
  }

  function getFeatureDisplayValue(feature) {
    const geomType = feature.geometry?.type || '';
    const m = feature.properties?.measurement;

    if (geomType.includes('Point')) {
      return { text: 'none', isMuted: true };
    }

    if (feature.properties?.status === 'ERROR') {
      return { text: 'error', isMuted: true };
    }

    if (!m) return { text: '—', isMuted: true };

    if (m.kind === 'area' && typeof m.value === 'number') {
      return { text: formatAreaValue(m.value), isMuted: false };
    }
    if (m.kind === 'length' && typeof m.value === 'number') {
      return { text: formatLengthValue(m.value), isMuted: false };
    }
    return { text: '—', isMuted: true };
  }

  function getIconClass(geomType) {
    if (geomType.includes('Polygon')) return 'ti ti-vector-triangle';
    if (geomType.includes('Line')) return 'ti ti-route';
    if (geomType.includes('Point')) return 'ti ti-map-pin';
    return 'ti ti-shapes';
  }

  // --- Selection Synchronization ---
  function selectFeature(index, flyToMap = true) {
    const prevIndex = state.selectedFeatureIndex;
    state.selectedFeatureIndex = index;

    // Reset style of previous selection
    if (prevIndex !== null) {
      const prevLayer = state.layersByIndex.get(prevIndex);
      const prevFeat = state.featuresByIndex.get(prevIndex);
      if (prevLayer && prevFeat) {
        styleLayer(prevLayer, prevFeat, false, false);
      }
      const prevRow = document.querySelector(`.feature-row[data-index="${prevIndex}"]`);
      if (prevRow) {
        prevRow.classList.remove('selected');
        prevRow.setAttribute('aria-selected', 'false');
      }
    }

    // Apply style to new selection
    if (index !== null) {
      const layer = state.layersByIndex.get(index);
      const feat = state.featuresByIndex.get(index);
      if (layer && feat) {
        styleLayer(layer, feat, true, false);

        if (flyToMap && map) {
          if (layer.getBounds) {
            const b = layer.getBounds();
            if (b.isValid()) {
              map.flyToBounds(b, { maxZoom: 17, padding: [60, 60], duration: 0.6 });
            }
          } else if (layer.getLatLng) {
            map.flyTo(layer.getLatLng(), Math.max(map.getZoom(), 15), { duration: 0.6 });
          }
        }
      }

      const row = document.querySelector(`.feature-row[data-index="${index}"]`);
      if (row) {
        row.classList.add('selected');
        row.setAttribute('aria-selected', 'true');
        row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    }

    // Update Measure and Verify tabs for selected feature
    updateMeasureTab(index);
    updateVerifyTab(index);
  }

  // --- Filtering & Filter Chips ---
  function updateFilterCounts() {
    let countPoly = 0;
    let countLine = 0;
    let countPoint = 0;
    let countIssues = 0;

    if (state.geojsonData && Array.isArray(state.geojsonData.features)) {
      state.geojsonData.features.forEach(f => {
        const t = f.geometry?.type || '';
        const s = f.properties?.status;
        if (t.includes('Polygon')) countPoly++;
        if (t.includes('Line')) countLine++;
        if (t.includes('Point')) countPoint++;
        if (s === 'SKIPPED' || s === 'ERROR') countIssues++;
      });
    }

    const total = state.geojsonData?.features?.length || 0;

    filterChips.forEach(chip => {
      const f = chip.dataset.filter;
      const countEl = chip.querySelector('.chip-count');
      if (!countEl) return;
      if (f === 'all') countEl.textContent = total;
      else if (f === 'Polygon') countEl.textContent = countPoly;
      else if (f === 'Line') countEl.textContent = countLine;
      else if (f === 'Point') countEl.textContent = countPoint;
      else if (f === 'issues') countEl.textContent = countIssues;
    });
  }

  function setFilter(filterName) {
    state.activeFilter = filterName;

    filterChips.forEach(chip => {
      const isActive = chip.dataset.filter === filterName;
      chip.classList.toggle('active', isActive);
      chip.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });

    applyFilter();
  }

  function applyFilter() {
    if (!state.geojsonData || !Array.isArray(state.geojsonData.features)) {
      state.filteredIndices = [];
      renderFeaturesListChunk(true);
      return;
    }

    state.filteredIndices = [];
    state.geojsonData.features.forEach(f => {
      const idx = f.properties?.index !== undefined ? f.properties.index : 0;
      const t = f.geometry?.type || '';
      const s = f.properties?.status;

      let matches = false;
      if (state.activeFilter === 'all') matches = true;
      else if (state.activeFilter === 'Polygon' && t.includes('Polygon')) matches = true;
      else if (state.activeFilter === 'Line' && t.includes('Line')) matches = true;
      else if (state.activeFilter === 'Point' && t.includes('Point')) matches = true;
      else if (state.activeFilter === 'issues' && (s === 'SKIPPED' || s === 'ERROR')) matches = true;

      if (matches) {
        state.filteredIndices.push(idx);
      }
    });

    renderFeaturesListChunk(true);
  }

  // --- Features List Rendering (XSS Safe + Chunked) ---
  function renderFeaturesListChunk(reset = false) {
    if (reset) {
      featuresList.textContent = ''; // clear without innerHTML
      state.renderedCount = 0;
    }

    const start = state.renderedCount;
    const end = Math.min(start + state.chunkSize, state.filteredIndices.length);

    for (let i = start; i < end; i++) {
      const idx = state.filteredIndices[i];
      const feature = state.featuresByIndex.get(idx);
      if (!feature) continue;

      const row = createFeatureRowElement(feature, idx);
      featuresList.appendChild(row);
    }

    state.renderedCount = end;
  }

  function createFeatureRowElement(feature, index) {
    const geomType = feature.geometry?.type || '';
    const status = feature.properties?.status;
    const isSelected = state.selectedFeatureIndex === index;

    const row = document.createElement('div');
    row.className = `feature-row${isSelected ? ' selected' : ''}`;
    row.dataset.index = index;
    row.setAttribute('role', 'option');
    row.setAttribute('aria-selected', isSelected ? 'true' : 'false');
    row.tabIndex = 0;

    // Left side: Icon + Name
    const left = document.createElement('div');
    left.className = 'feature-row-left';

    const icon = document.createElement('i');
    icon.className = `feature-icon ${getIconClass(geomType)}`;
    icon.setAttribute('aria-hidden', 'true');
    left.appendChild(icon);

    const name = document.createElement('span');
    name.className = 'feature-name';
    name.textContent = getFeatureName(feature, index);
    left.appendChild(name);

    row.appendChild(left);

    // Right side: Value + Status dot (if skipped/error)
    const right = document.createElement('div');
    right.className = 'feature-row-right';

    const valDisplay = getFeatureDisplayValue(feature);
    const val = document.createElement('span');
    val.className = `feature-val num${valDisplay.isMuted ? ' muted' : ''}`;
    val.textContent = valDisplay.text;
    right.appendChild(val);

    if (status === 'SKIPPED') {
      const dot = document.createElement('span');
      dot.className = 'feature-status-dot skipped';
      dot.setAttribute('title', 'Skipped feature');
      right.appendChild(dot);
    } else if (status === 'ERROR') {
      const dot = document.createElement('span');
      dot.className = 'feature-status-dot error';
      dot.setAttribute('title', 'Processing error');
      right.appendChild(dot);
    }

    row.appendChild(right);

    // Event listeners: click selects and flies
    row.addEventListener('click', () => {
      selectFeature(index, true);
    });

    // Hover highlights shape on map
    row.addEventListener('mouseenter', () => {
      if (state.selectedFeatureIndex !== index) {
        const layer = state.layersByIndex.get(index);
        if (layer) styleLayer(layer, feature, false, true);
      }
    });

    row.addEventListener('mouseleave', () => {
      if (state.selectedFeatureIndex !== index) {
        const layer = state.layersByIndex.get(index);
        if (layer) styleLayer(layer, feature, false, false);
      }
    });

    return row;
  }

  // --- Keyboard Navigation in List ---
  function setupListKeyboardNav() {
    featuresList.addEventListener('keydown', (e) => {
      if (state.filteredIndices.length === 0) return;

      const currentIdx = state.selectedFeatureIndex;
      const currentPos = state.filteredIndices.indexOf(currentIdx);

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        const nextPos = currentPos < state.filteredIndices.length - 1 ? currentPos + 1 : 0;
        selectFeature(state.filteredIndices[nextPos], true);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        const prevPos = currentPos > 0 ? currentPos - 1 : state.filteredIndices.length - 1;
        selectFeature(state.filteredIndices[prevPos], true);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (currentIdx !== null) {
          setActiveTab('measure');
        }
      }
    });

    // Scroll listener for lazy loading chunks
    featuresList.addEventListener('scroll', () => {
      if (
        featuresList.scrollTop + featuresList.clientHeight >=
        featuresList.scrollHeight - 60
      ) {
        if (state.renderedCount < state.filteredIndices.length) {
          renderFeaturesListChunk(false);
        }
      }
    });
  }

  // --- Measure Tab Details ---
  function updateMeasureTab(index) {
    if (index === null || !state.featuresByIndex.has(index)) {
      measureEmptyMsg.style.display = 'block';
      measureDetail.style.display = 'none';
      return;
    }

    const feature = state.featuresByIndex.get(index);
    const p = feature.properties || {};
    const m = p.measurement || null;
    const geomType = feature.geometry?.type || p.geometry_type || 'Unknown';
    const status = p.status || 'OK';

    measureEmptyMsg.style.display = 'none';
    measureDetail.style.display = 'flex';

    // Header: Name, Type, Status Badge
    measureName.textContent = getFeatureName(feature, index);
    measureType.textContent = geomType;

    measureBadge.textContent = status;
    measureBadge.className = `status-badge ${
      status === 'ERROR' ? 'badge-error' : status === 'SKIPPED' ? 'badge-skipped' : 'badge-ok'
    }`;

    // Point handling: Never show SKIPPED for points
    if (geomType.includes('Point')) {
      measureBadge.textContent = 'OK';
      measureBadge.className = 'status-badge badge-ok';
      measureBigVal.textContent = 'Points have no measurement.';
      measureBigVal.style.fontSize = '14px';
      measureOtherUnits.textContent = '';
      rowDimension.style.display = 'none';
      valMethod.textContent = m?.method || 'point-zero-dimensional';
      valMeasurementCrs.textContent = m?.measurement_crs || 'EPSG:4326';
      valSourceCrs.textContent = p.crs || state.file?.crs || 'EPSG:4326';
      valSourceLayer.textContent = p.source_layer || 'default';
      renderPropertiesTable(p);
      return;
    }

    measureBigVal.style.fontSize = 'var(--font-size-lg)';

    // Polygons & Lines measurement values
    if (m && m.kind === 'area' && typeof m.value === 'number') {
      const valM2 = m.value;
      measureBigVal.textContent = formatAreaValue(valM2);

      // Other units muted line: show the other 3 units
      const otherUnits = [];
      ['ha', 'm2', 'acres', 'km2'].forEach(u => {
        if (u !== state.selectedUnit) {
          const c = AREA_CONVERSIONS[u];
          otherUnits.push(`${Number((valM2 * c.factor).toFixed(c.decimals)).toLocaleString()} ${c.label}`);
        }
      });
      measureOtherUnits.textContent = otherUnits.join(' · ');

      // Perimeter
      rowDimension.style.display = 'flex';
      labelDimension.textContent = 'Perimeter';
      valDimension.textContent = m.perimeter ? formatLengthValue(m.perimeter) : '—';
    } else if (m && m.kind === 'length' && typeof m.value === 'number') {
      measureBigVal.textContent = formatLengthValue(m.value);
      measureOtherUnits.textContent = `${Number(m.value.toFixed(1)).toLocaleString()} m`;
      rowDimension.style.display = 'flex';
      labelDimension.textContent = 'Length';
      valDimension.textContent = formatLengthValue(m.value);
    } else {
      measureBigVal.textContent = status === 'ERROR' ? 'Measurement error' : '—';
      measureOtherUnits.textContent = '';
      rowDimension.style.display = 'none';
    }

    valMethod.textContent = m?.method || '—';
    valMeasurementCrs.textContent = m?.measurement_crs || '—';
    valSourceCrs.textContent = p.crs || state.file?.crs || 'EPSG:4326';
    valSourceLayer.textContent = p.source_layer || 'default';

    renderPropertiesTable(p);
  }

  function renderPropertiesTable(properties) {
    propertiesTable.textContent = '';
    const excluded = new Set(['index', 'source_layer', 'geometry_type', 'crs', 'status', 'warnings', 'measurement']);

    let count = 0;
    Object.entries(properties).forEach(([k, v]) => {
      if (excluded.has(k)) return;
      count++;
      const row = document.createElement('div');
      row.className = 'prop-row';

      const keyEl = document.createElement('span');
      keyEl.className = 'prop-k';
      keyEl.textContent = k;
      keyEl.title = k;

      const valEl = document.createElement('span');
      valEl.className = 'prop-v';
      valEl.textContent = typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v);
      valEl.title = String(v);

      row.appendChild(keyEl);
      row.appendChild(valEl);
      propertiesTable.appendChild(row);
    });

    if (count === 0) {
      const empty = document.createElement('div');
      empty.className = 'prop-v';
      empty.style.color = 'var(--text-2)';
      empty.textContent = 'No custom properties.';
      propertiesTable.appendChild(empty);
    }
  }

  function updateVerifyFooter() {
    verifyFileCrs.textContent = state.file?.crs || 'EPSG:4326';
    verifyDuration.textContent = state.file?.processing_duration_ms
      ? `${state.file.processing_duration_ms} ms`
      : '—';

    const fileWarns = state.file?.warnings || [];
    verifyFileWarnings.textContent = '';
    if (fileWarns.length > 0) {
      verifyFileWarningsContainer.style.display = 'block';
      fileWarns.forEach(w => {
        const li = document.createElement('li');
        li.textContent = w;
        verifyFileWarnings.appendChild(li);
      });
    } else {
      verifyFileWarningsContainer.style.display = 'none';
    }
  }

  // --- Verify Tab Details ---
  function updateVerifyTab(index) {
    updateVerifyFooter();

    if (index === null || !state.featuresByIndex.has(index)) {
      verifyEmptyMsg.style.display = 'block';
      verifyDetail.style.display = 'none';
      return;
    }

    const feature = state.featuresByIndex.get(index);
    const p = feature.properties || {};
    const m = p.measurement || null;
    const geomType = feature.geometry?.type || '';

    verifyEmptyMsg.style.display = 'none';
    verifyDetail.style.display = 'flex';

    if (geomType.includes('Point')) {
      verifyProjCrs.textContent = 'None';
      verifyProjVal.textContent = '0-dimensional (no planar check)';
      verifyGeodVal.textContent = '0-dimensional (no geodesic check)';
      verifyDeltaBadge.textContent = '0.00%';
      verifyDeltaBadge.className = 'delta-badge delta-ok num';
      verifyDeltaText.textContent = 'Points are zero-dimensional and have no planar or geodesic discrepancy.';
    } else if (m && typeof m.value === 'number') {
      verifyProjCrs.textContent = m.measurement_crs || 'Planar';
      verifyProjVal.textContent = m.kind === 'area' ? formatAreaValue(m.value) : formatLengthValue(m.value);

      if (typeof m.geodesic_value === 'number') {
        verifyGeodVal.textContent = m.kind === 'area' ? formatAreaValue(m.geodesic_value) : formatLengthValue(m.geodesic_value);
      } else {
        verifyGeodVal.textContent = '—';
      }

      const delta = typeof m.delta_percent === 'number' ? m.delta_percent : 0;
      verifyDeltaBadge.textContent = `${delta.toFixed(2)}%`;

      if (delta < 0.1) {
        verifyDeltaBadge.className = 'delta-badge delta-ok num';
        verifyDeltaText.textContent = 'Planar and geodesic measurements are within tight 0.1% tolerance.';
      } else if (delta <= 0.5) {
        verifyDeltaBadge.className = 'delta-badge delta-warn num';
        verifyDeltaText.textContent = 'Moderate projection distortion detected across this geometry (0.1% to 0.5%).';
      } else {
        verifyDeltaBadge.className = 'delta-badge delta-err num';
        verifyDeltaText.textContent = 'Significant projection distortion exceeds recommended 0.5% threshold.';
      }
    } else {
      verifyProjCrs.textContent = '—';
      verifyProjVal.textContent = '—';
      verifyGeodVal.textContent = '—';
      verifyDeltaBadge.textContent = '—';
      verifyDeltaBadge.className = 'delta-badge num';
      verifyDeltaText.textContent = 'No measurement available for comparison.';
    }

    // Feature Warnings
    const featWarnings = p.warnings || [];
    verifyFeatureWarnings.textContent = '';
    if (featWarnings.length > 0) {
      verifyWarningsSection.style.display = 'block';
      featWarnings.forEach(w => {
        const li = document.createElement('li');
        li.textContent = w;
        verifyFeatureWarnings.appendChild(li);
      });
    } else {
      verifyWarningsSection.style.display = 'none';
    }
  }

  // --- Render Features onto Leaflet Map ---
  function renderGeoJSONOnMap(geojson) {
    if (!geojson || !Array.isArray(geojson.features)) return;

    activeGeojsonGroup.clearLayers();
    state.layersByIndex.clear();
    state.featuresByIndex.clear();

    geojson.features.forEach((feature, fallbackIdx) => {
      const idx = feature.properties?.index !== undefined ? feature.properties.index : fallbackIdx;
      state.featuresByIndex.set(idx, feature);

      const layer = L.geoJSON(feature, {
        style: () => getNormalStyle(feature),
        pointToLayer: (feat, latlng) => {
          return L.circleMarker(latlng, getNormalStyle(feat));
        },
      });

      // Bind events to each sublayer
      layer.eachLayer(subLayer => {
        subLayer.on('click', (e) => {
          L.DomEvent.stopPropagation(e);
          selectFeature(idx, false);
          setActiveTab('measure');
        });

        subLayer.on('mouseover', () => {
          if (state.selectedFeatureIndex !== idx) {
            styleLayer(subLayer, feature, false, true);
          }
        });

        subLayer.on('mouseout', () => {
          if (state.selectedFeatureIndex !== idx) {
            styleLayer(subLayer, feature, false, false);
          }
        });

        state.layersByIndex.set(idx, subLayer);
        activeGeojsonGroup.addLayer(subLayer);
      });
    });

    // Fit map bounds
    const bounds = activeGeojsonGroup.getBounds();
    if (bounds.isValid()) {
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 16 });
    }
  }

  // --- UI Banner & State Helpers ---
  const emptyCard = document.getElementById('empty-card');
  const emptyUploadBtn = document.getElementById('empty-upload-btn');
  const dragOverlay = document.getElementById('drag-overlay');
  const toolbarProgress = document.getElementById('toolbar-progress');
  const inspectorBanner = document.getElementById('inspector-banner');
  const bannerText = document.getElementById('banner-text');
  const bannerCloseBtn = document.getElementById('banner-close-btn');
  const a11yAnnouncer = document.getElementById('a11y-announcer');

  function announce(msg) {
    if (a11yAnnouncer) {
      a11yAnnouncer.textContent = msg;
    }
  }

  function showBanner(text, type = 'error', actionBtn = null) {
    inspectorBanner.style.display = 'flex';
    inspectorBanner.className = `inspector-banner banner-${type}`;
    bannerText.textContent = '';

    const msgSpan = document.createElement('span');
    msgSpan.textContent = text;
    bannerText.appendChild(msgSpan);

    if (actionBtn) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn-filter-issues';
      btn.textContent = actionBtn.label;
      btn.addEventListener('click', actionBtn.onClick);
      bannerText.appendChild(btn);
    }

    announce(`${type}: ${text}`);
  }

  function hideBanner() {
    inspectorBanner.style.display = 'none';
  }

  function showLoading(isLoading) {
    state.isLoading = isLoading;
    toolbarProgress.style.display = isLoading ? 'block' : 'none';

    if (isLoading) {
      // Render skeleton rows in features list
      featuresList.textContent = '';
      for (let i = 0; i < 6; i++) {
        const skel = document.createElement('div');
        skel.className = 'skeleton-row';

        const left = document.createElement('div');
        left.className = 'skeleton-left';

        const iconBox = document.createElement('div');
        iconBox.className = 'skeleton-box skeleton-icon';
        left.appendChild(iconBox);

        const textBox = document.createElement('div');
        textBox.className = 'skeleton-box skeleton-text';
        left.appendChild(textBox);

        skel.appendChild(left);

        const valBox = document.createElement('div');
        valBox.className = 'skeleton-box skeleton-val';
        skel.appendChild(valBox);

        featuresList.appendChild(skel);
      }
    }
  }

  // --- API Communication: Upload & Polling ---
  async function handleFileUpload(file) {
    hideBanner();
    showLoading(true);
    announce(`Uploading ${file.name}...`);
    toolbarFilename.textContent = file.name;
    toolbarFilename.title = file.name;

    const formData = new FormData();
    formData.append('file', file);

    try {
      // Step 1: POST to /api/files/?wait=true
      const res = await fetch('/api/files/?wait=true', {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || `Upload failed with HTTP ${res.status}`);
      }

      const uploadData = await res.json();
      const fileId = uploadData.id;

      // Step 2: Poll if PENDING/PROCESSING
      let fileStatus = uploadData.status;
      let fileMeta = null;
      const startTime = Date.now();

      while (fileStatus === 'PENDING' || fileStatus === 'PROCESSING') {
        if (Date.now() - startTime > 120000) {
          throw new Error('Processing timed out after 2 minutes. The file may be too large or the server is busy.');
        }
        await new Promise(r => setTimeout(r, 1000));
        const metaRes = await fetch(`/api/files/${fileId}/`);
        if (!metaRes.ok) {
          throw new Error('Failed checking processing status.');
        }
        fileMeta = await metaRes.json();
        fileStatus = fileMeta.status;
      }

      if (fileStatus === 'FAILED') {
        throw new Error(fileMeta?.error || 'Dataset processing failed.');
      }

      if (!fileMeta) {
        const metaRes = await fetch(`/api/files/${fileId}/`);
        fileMeta = await metaRes.json();
      }
      state.file = fileMeta;

      // Step 3: Fetch GeoJSON measurements (paginated if > 1000)
      const firstRes = await fetch(`/api/files/${fileId}/measurements/?format=geojson&limit=1000&offset=0`);
      if (!firstRes.ok) {
        throw new Error('Failed to retrieve GeoJSON measurements.');
      }
      const geojson = await firstRes.json();
      const totalFeatures = geojson.total || (geojson.features ? geojson.features.length : 0);

      let currentOffset = 1000;
      while (geojson.features && geojson.features.length < totalFeatures) {
        const nextRes = await fetch(`/api/files/${fileId}/measurements/?format=geojson&limit=1000&offset=${currentOffset}`);
        if (!nextRes.ok) break;
        const nextData = await nextRes.json();
        if (!nextData.features || nextData.features.length === 0) break;
        geojson.features.push(...nextData.features);
        currentOffset += nextData.features.length;
      }
      state.geojsonData = geojson;

      // Hide empty card and show complete UI
      if (emptyCard) emptyCard.style.display = 'none';
      railDownloadBtn.disabled = false;

      // Check PARTIAL status
      if (fileMeta.status === 'PARTIAL') {
        showBanner("Some features couldn't be measured", 'partial', {
          label: 'Filter issues',
          onClick: () => {
            setActiveTab('features');
            setFilter('issues');
          },
        });
      }

      // Render map, filters, list, and summary
      renderGeoJSONOnMap(geojson);
      updateFilterCounts();
      applyFilter();
      refreshStatsStrip();
      updateVerifyFooter();

      // If features exist, select the first one by default
      if (state.filteredIndices.length > 0) {
        selectFeature(state.filteredIndices[0], false);
      }

      announce(`Loaded ${fileMeta.feature_count} features.`);
    } catch (err) {
      console.error('Error during upload:', err);
      showBanner(err.message || 'Error uploading file.', 'error');
      // If error occurred before loading, restore empty list or reset
      if (!state.file) {
        featuresList.textContent = '';
      }
    } finally {
      showLoading(false);
    }
  }

  // --- Download GeoJSON ---
  function downloadGeoJSON() {
    if (!state.geojsonData) return;
    const blob = new Blob([JSON.stringify(state.geojsonData, null, 2)], {
      type: 'application/geo+json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${state.file?.filename || 'dataset'}_measurements.geojson`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // --- Tab Switching ---
  function setActiveTab(tabName) {
    state.activeTab = tabName;

    const tabs = [
      { name: 'features', btn: tabBtnFeatures, panel: panelFeatures },
      { name: 'measure', btn: tabBtnMeasure, panel: panelMeasure },
      { name: 'verify', btn: tabBtnVerify, panel: panelVerify },
    ];

    tabs.forEach(t => {
      const isActive = t.name === tabName;
      t.btn.classList.toggle('active', isActive);
      t.btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
      t.btn.tabIndex = isActive ? 0 : -1;
      if (isActive) {
        t.panel.removeAttribute('hidden');
        t.panel.classList.add('active');
      } else {
        t.panel.setAttribute('hidden', '');
        t.panel.classList.remove('active');
      }
    });

    railFeaturesBtn.classList.toggle('active', tabName === 'features');

    if (tabName === 'measure') {
      updateMeasureTab(state.selectedFeatureIndex);
    } else if (tabName === 'verify') {
      updateVerifyTab(state.selectedFeatureIndex);
    }
  }

  function setupTabKeyboardNav() {
    const tabsList = document.querySelector('.inspector-tabs');
    const tabButtons = [tabBtnFeatures, tabBtnMeasure, tabBtnVerify];
    const tabNames = ['features', 'measure', 'verify'];

    tabsList.addEventListener('keydown', (e) => {
      let currentIndex = tabButtons.indexOf(document.activeElement);
      if (currentIndex === -1) return;

      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        e.preventDefault();
        const nextIndex = (currentIndex + 1) % tabButtons.length;
        setActiveTab(tabNames[nextIndex]);
        tabButtons[nextIndex].focus();
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault();
        const prevIndex = (currentIndex - 1 + tabButtons.length) % tabButtons.length;
        setActiveTab(tabNames[prevIndex]);
        tabButtons[prevIndex].focus();
      }
    });
  }

  // --- Unit Switching ---
  function setUnit(unit) {
    if (!AREA_CONVERSIONS[unit]) return;
    state.selectedUnit = unit;
    announce(`Unit changed to ${AREA_CONVERSIONS[unit].label}`);
    document.querySelectorAll('.unit-btn').forEach(btn => {
      const isCurrent = btn.dataset.unit === unit;
      btn.classList.toggle('active', isCurrent);
      btn.setAttribute('aria-checked', isCurrent ? 'true' : 'false');
    });

    // Instantly update Features list rows
    document.querySelectorAll('.feature-row').forEach(row => {
      const idx = parseInt(row.dataset.index, 10);
      const feat = state.featuresByIndex.get(idx);
      if (feat) {
        const valEl = row.querySelector('.feature-val');
        if (valEl) {
          const valDisplay = getFeatureDisplayValue(feat);
          valEl.textContent = valDisplay.text;
          valEl.className = `feature-val num${valDisplay.isMuted ? ' muted' : ''}`;
        }
      }
    });

    // Instantly update Measure tab and Stats strip
    if (state.selectedFeatureIndex !== null) {
      updateMeasureTab(state.selectedFeatureIndex);
    }
    refreshStatsStrip();
  }

  // --- Stats Strip Updates ---
  function refreshStatsStrip() {
    if (!state.file) {
      statsArea.textContent = '—';
      statsLength.textContent = '—';
      statsMaxDelta.textContent = '—';
      statsMaxDelta.style.color = 'var(--text)';
      statsFeatures.textContent = '0 ok';
      return;
    }

    const summary = state.file.summary || {};
    const totalAreaM2 = summary.total_area_m2 || 0;
    const totalLengthM = summary.total_length_m || 0;

    statsArea.textContent = formatAreaValue(totalAreaM2);
    statsLength.textContent = formatLengthValue(totalLengthM);

    // Max delta calculation
    let maxDelta = 0;
    if (state.geojsonData && Array.isArray(state.geojsonData.features)) {
      state.geojsonData.features.forEach(f => {
        const d = f.properties?.measurement?.delta_percent;
        if (typeof d === 'number' && d > maxDelta) {
          maxDelta = d;
        }
      });
    }

    statsMaxDelta.textContent = `${maxDelta.toFixed(2)}%`;
    if (maxDelta < 0.1) {
      statsMaxDelta.style.color = 'var(--ok-text)';
    } else if (maxDelta <= 0.5) {
      statsMaxDelta.style.color = 'var(--warn-text)';
    } else {
      statsMaxDelta.style.color = 'var(--err-text)';
    }

    const okCount = summary.ok_count || 0;
    const skippedCount = summary.skipped_count || 0;
    const errorCount = summary.error_count || 0;

    let featText = `${okCount} ok`;
    if (skippedCount > 0) featText += ` · ${skippedCount} skipped`;
    if (errorCount > 0) featText += ` · ${errorCount} error`;
    statsFeatures.textContent = featText;
  }

  // --- Event Listeners Setup ---
  function setupListeners() {
    tabBtnFeatures.addEventListener('click', () => setActiveTab('features'));
    tabBtnMeasure.addEventListener('click', () => setActiveTab('measure'));
    tabBtnVerify.addEventListener('click', () => setActiveTab('verify'));

    railFeaturesBtn.addEventListener('click', () => setActiveTab('features'));
    railDownloadBtn.addEventListener('click', downloadGeoJSON);
    if (railThemeBtn) railThemeBtn.addEventListener('click', toggleTheme);

    const triggerUpload = () => fileInput.click();
    topUploadBtn.addEventListener('click', triggerUpload);
    railUploadBtn.addEventListener('click', triggerUpload);
    if (emptyUploadBtn) emptyUploadBtn.addEventListener('click', triggerUpload);
    if (bannerCloseBtn) bannerCloseBtn.addEventListener('click', hideBanner);

    // Global Drag & Drop handling
    let dragCounter = 0;
    window.addEventListener('dragenter', (e) => {
      e.preventDefault();
      dragCounter++;
      if (dragOverlay) dragOverlay.style.display = 'flex';
    });

    window.addEventListener('dragleave', (e) => {
      e.preventDefault();
      dragCounter--;
      if (dragCounter <= 0 && dragOverlay) {
        dragCounter = 0;
        dragOverlay.style.display = 'none';
      }
    });

    window.addEventListener('dragover', (e) => {
      e.preventDefault();
    });

    window.addEventListener('drop', (e) => {
      e.preventDefault();
      dragCounter = 0;
      if (dragOverlay) dragOverlay.style.display = 'none';
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        handleFileUpload(e.dataTransfer.files[0]);
      }
    });

    fileInput.addEventListener('change', (e) => {
      if (e.target.files.length > 0) {
        handleFileUpload(e.target.files[0]);
      }
    });

    document.querySelectorAll('.unit-btn').forEach(btn => {
      btn.addEventListener('click', () => setUnit(btn.dataset.unit));
    });

    filterChips.forEach(chip => {
      chip.addEventListener('click', () => setFilter(chip.dataset.filter));
    });

    setupListKeyboardNav();
    setupTabKeyboardNav();
  }

  // --- Initialization ---
  document.addEventListener('DOMContentLoaded', () => {
    applyTheme(currentTheme);
    initMap();
    setupListeners();
  });
})();
