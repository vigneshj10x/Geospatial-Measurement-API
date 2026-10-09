// Geospatial Measurement Engine - Interactive Map Viewer

(function () {
  'use strict';

  // --- State ---
  const state = {
    file: null, // FileDetailResponse metadata
    geojsonData: null, // RFC 7946 GeoJSON FeatureCollection
    selectedUnit: 'ha', // 'm2' | 'ha' | 'acres' | 'km2'
    selectedFeatureIndex: null, // index of currently selected feature
    activeFilter: 'all', // 'all' | 'Polygon' | 'Line' | 'Point' | 'issues'
    activeTab: 'features', // 'features' | 'measure' | 'verify'
    layersByIndex: new Map(), // index -> Leaflet layer
    featuresByIndex: new Map(), // index -> GeoJSON feature
  };

  // --- Conversions ---
  const AREA_CONVERSIONS = {
    m2: { label: 'm²', factor: 1.0, decimals: 2 },
    ha: { label: 'ha', factor: 0.0001, decimals: 2 },
    acres: { label: 'acres', factor: 0.000247105, decimals: 2 },
    km2: { label: 'km²', factor: 0.000001, decimals: 4 },
  };

  // --- DOM Elements ---
  const mapEl = document.getElementById('map');
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

  // Features list
  const featuresList = document.getElementById('features-list');

  // Stats strip
  const statsArea = document.getElementById('stats-area');
  const statsLength = document.getElementById('stats-length');
  const statsMaxDelta = document.getElementById('stats-max-delta');
  const statsFeatures = document.getElementById('stats-features');

  // --- Map Initialization ---
  let map = null;
  let activeGeojsonGroup = null;

  function initMap() {
    map = L.map('map', {
      center: [20.5937, 78.9629],
      zoom: 5,
      zoomControl: false,
    });

    // Top right zoom control
    L.control.zoom({ position: 'topright' }).addTo(map);

    // CARTO Positron light tiles with attribution
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
      subdomains: 'abcd',
      maxZoom: 20,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    }).addTo(map);

    activeGeojsonGroup = L.featureGroup().addTo(map);
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

    if (tabName === 'features') {
      railFeaturesBtn.classList.add('active');
    } else {
      railFeaturesBtn.classList.remove('active');
    }
  }

  // --- Unit Switching ---
  function setUnit(unit) {
    if (!AREA_CONVERSIONS[unit]) return;
    state.selectedUnit = unit;
    document.querySelectorAll('.unit-btn').forEach(btn => {
      const isCurrent = btn.dataset.unit === unit;
      btn.classList.toggle('active', isCurrent);
      btn.setAttribute('aria-checked', isCurrent ? 'true' : 'false');
    });
    refreshStatsStrip();
  }

  // --- Stats Strip Updates ---
  function refreshStatsStrip() {
    if (!state.file) {
      statsArea.textContent = '—';
      statsLength.textContent = '—';
      statsMaxDelta.textContent = '—';
      statsMaxDelta.className = 'stats-val num';
      statsFeatures.textContent = '0 ok';
      return;
    }

    const summary = state.file.summary || {};
    const totalAreaM2 = summary.total_area_m2 || 0;
    const totalLengthM = summary.total_length_m || 0;

    // Convert area
    const conv = AREA_CONVERSIONS[state.selectedUnit] || AREA_CONVERSIONS.ha;
    const convertedArea = totalAreaM2 * conv.factor;
    statsArea.textContent = `${Number(convertedArea.toFixed(conv.decimals)).toLocaleString()} ${conv.label}`;

    // Convert length
    if (totalLengthM >= 1000) {
      statsLength.textContent = `${Number((totalLengthM / 1000).toFixed(2)).toLocaleString()} km`;
    } else {
      statsLength.textContent = `${Number(totalLengthM.toFixed(1)).toLocaleString()} m`;
    }

    // Max delta calculation across features
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
    statsMaxDelta.className = 'stats-val num';
    if (maxDelta < 0.1) {
      statsMaxDelta.style.color = 'var(--ok-text)';
    } else if (maxDelta <= 0.5) {
      statsMaxDelta.style.color = 'var(--warn-text)';
    } else {
      statsMaxDelta.style.color = 'var(--err-text)';
    }

    // Features count text: "4 ok", and append " · 1 skipped" or " · 1 error" only when > 0
    const okCount = summary.ok_count || 0;
    const skippedCount = summary.skipped_count || 0;
    const errorCount = summary.error_count || 0;

    let featText = `${okCount} ok`;
    if (skippedCount > 0) {
      featText += ` · ${skippedCount} skipped`;
    }
    if (errorCount > 0) {
      featText += ` · ${errorCount} error`;
    }
    statsFeatures.textContent = featText;
  }

  // --- Event Listeners Setup ---
  function setupListeners() {
    tabBtnFeatures.addEventListener('click', () => setActiveTab('features'));
    tabBtnMeasure.addEventListener('click', () => setActiveTab('measure'));
    tabBtnVerify.addEventListener('click', () => setActiveTab('verify'));

    railFeaturesBtn.addEventListener('click', () => setActiveTab('features'));

    const triggerUpload = () => fileInput.click();
    topUploadBtn.addEventListener('click', triggerUpload);
    railUploadBtn.addEventListener('click', triggerUpload);

    document.querySelectorAll('.unit-btn').forEach(btn => {
      btn.addEventListener('click', () => setUnit(btn.dataset.unit));
    });
  }

  // --- Initialize App ---
  document.addEventListener('DOMContentLoaded', () => {
    initMap();
    setupListeners();
  });
})();
