// ReelToReal OpenStreetMap Leaflet Manager (100% Free - No API Key Required)

class MapManager {
  constructor() {
    this.map = null;
    this.markers = [];
    this.planMarkers = [];
    this.routePolyline = null;
    this.initialized = false;
  }

  initMap() {
    const mapContainer = document.getElementById('map-element');
    if (!mapContainer || this.initialized) return;

    if (typeof L === 'undefined') {
      console.warn("Leaflet library not yet loaded, retrying...");
      setTimeout(() => this.initMap(), 300);
      return;
    }

    try {
      // Create Leaflet map centered on India by default
      this.map = L.map('map-element', {
        zoomControl: true,
        attributionControl: true
      }).setView([20.5937, 78.9629], 5);

      // OpenStreetMap standard tile layer - 100% free, public, no API key needed
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      }).addTo(this.map);

      this.initialized = true;
      this.bindMapControls();
      this.loadPins();
    } catch (err) {
      console.error("Error initializing Leaflet map:", err);
    }
  }

  bindMapControls() {
    const btnIndia = document.getElementById('btn-map-recenter-india');
    if (btnIndia) {
      btnIndia.onclick = () => this.recenterOnIndia();
    }
  }

  recenterOnIndia() {
    if (!this.map) return;
    const indiaPins = [];
    this.markers.forEach(m => {
      const ll = m.getLatLng();
      if (ll && ll.lat >= 6.0 && ll.lat <= 37.5 && ll.lng >= 68.0 && ll.lng <= 97.5) {
        indiaPins.push([ll.lat, ll.lng]);
      }
    });

    if (indiaPins.length > 0) {
      this.map.fitBounds(indiaPins, { padding: [60, 60], maxZoom: 12 });
    } else {
      this.map.setView([20.5937, 78.9629], 5);
    }
  }

  invalidateSize() {
    if (!this.initialized) {
      this.initMap();
    }
    this.bindMapControls();
    if (this.map) {
      setTimeout(() => {
        this.map.invalidateSize();
      }, 150);
    }
  }

  async loadPins() {
    if (!this.map) {
      this.initMap();
      return;
    }

    this.clearPlanRoute(false);

    try {
      const userId = window.currentUserId || localStorage.getItem('reeltoreal_user_id') || 'default';
      const resp = await fetch(`/api/map/pins?user_id=${encodeURIComponent(userId)}`);
      const pins = await resp.json();

      // Clear existing markers
      this.markers.forEach(m => {
        try { this.map.removeLayer(m); } catch (e) {}
      });
      this.markers = [];

      if (!pins || pins.length === 0) {
        this.map.setView([20.5937, 78.9629], 5);
        return;
      }

      const allPins = [];
      const indiaPins = [];

      pins.forEach(pin => {
        if (pin.latitude && pin.longitude) {
          const marker = this.createCategoryMarker(pin);
          marker.addTo(this.map);
          this.markers.push(marker);
          allPins.push([pin.latitude, pin.longitude]);

          // Check if coordinate is in the India geographic region
          if (pin.latitude >= 6.0 && pin.latitude <= 37.5 && pin.longitude >= 68.0 && pin.longitude <= 97.5) {
            indiaPins.push([pin.latitude, pin.longitude]);
          }
        }
      });

      // If there are pins in India, prioritize framing them
      if (indiaPins.length > 0) {
        this.map.fitBounds(indiaPins, { padding: [60, 60], maxZoom: 12 });
      } else if (allPins.length > 0) {
        this.map.fitBounds(allPins, { padding: [60, 60], maxZoom: 12 });
      } else {
        this.map.setView([20.5937, 78.9629], 5);
      }
    } catch (err) {
      console.error("Failed to load map pins:", err);
    }
  }

  createCategoryMarker(pin) {
    const colorMap = {
      food: '#f97316',
      travel: '#0ea5e9',
      activity: '#10b981',
      fitness: '#ec4899',
      shopping: '#8b5cf6',
      product: '#eab308',
      tip: '#06b6d4',
      other: '#64748b'
    };

    const iconMap = {
      food: '🍜',
      travel: '✈️',
      activity: '🧗',
      fitness: '💪',
      shopping: '🛍️',
      product: '📦',
      tip: '💡',
      other: '📍'
    };

    const color = colorMap[pin.category.toLowerCase()] || '#6366f1';
    const emoji = iconMap[pin.category.toLowerCase()] || '📍';

    const customHtml = `
      <div style="
        background: ${color};
        width: 34px;
        height: 34px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 0 15px ${color};
        border: 2px solid #ffffff;
        font-size: 15px;
        cursor: pointer;
        transition: transform 0.2s ease;
      ">${emoji}</div>
    `;

    const icon = L.divIcon({
      html: customHtml,
      className: 'custom-map-pin',
      iconSize: [34, 34],
      iconAnchor: [17, 17],
      popupAnchor: [0, -20]
    });

    const marker = L.marker([pin.latitude, pin.longitude], { icon });

    const highlights = (pin.highlights || []).slice(0, 2).map(h => `<li>${h}</li>`).join('');
    const tips = (pin.actionable_tips || []).slice(0, 1).map(t => `<p style="font-size: 0.75rem; color: #fbbf24; margin-top: 4px;">💡 ${t}</p>`).join('');

    const popupContent = `
      <div style="min-width: 220px; padding: 4px; font-family: 'Plus Jakarta Sans', sans-serif;">
        <span style="font-size: 0.7rem; font-weight: 700; text-transform: uppercase; color: ${color};">${pin.category}</span>
        <h4 style="font-size: 0.95rem; font-weight: 700; margin: 2px 0 6px 0; color: #fff;">${pin.title}</h4>
        ${pin.place_name ? `<p style="font-size: 0.8rem; color: #a5b4fc; margin-bottom: 6px;">📍 ${pin.place_name} (${pin.city || ''})</p>` : ''}
        ${highlights ? `<ul style="font-size: 0.75rem; color: #cbd5e1; padding-left: 1rem; margin-bottom: 6px;">${highlights}</ul>` : ''}
        ${tips}
        <button onclick="openPreviewModal('${pin.id}')" style="
          margin-top: 8px;
          width: 100%;
          background: #6366f1;
          color: #fff;
          border: none;
          padding: 6px 12px;
          border-radius: 6px;
          font-weight: 600;
          font-size: 0.75rem;
          cursor: pointer;
          transition: background 0.2s;
        ">🎬 Watch Clip</button>
      </div>
    `;

    marker.bindPopup(popupContent);
    return marker;
  }

  // --- Grounded Plan Route Overlay ---

  highlightPlanRoute(stops) {
    if (!this.map) {
      this.initMap();
    }

    this.clearPlanRoute(false);

    if (!stops || stops.length === 0) return;

    const validStops = stops.filter(s => s.latitude && s.longitude);
    if (validStops.length === 0) {
      alert("None of the stops in this itinerary have geocoded coordinates.");
      return;
    }

    // Hide general markers temporarily to focus on the plan route
    this.markers.forEach(m => {
      try { this.map.removeLayer(m); } catch (e) {}
    });

    const latlngs = [];

    validStops.forEach((stop, idx) => {
      const point = [stop.latitude, stop.longitude];
      latlngs.push(point);

      const stopHtml = `
        <div style="
          background: #6366f1;
          width: 32px;
          height: 32px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          color: #fff;
          font-weight: 800;
          font-size: 14px;
          box-shadow: 0 0 16px rgba(99,102,241,0.8);
          border: 3px solid #ffffff;
          cursor: pointer;
        ">${stop.stop_number || idx + 1}</div>
      `;

      const icon = L.divIcon({
        html: stopHtml,
        className: 'custom-plan-stop-icon',
        iconSize: [32, 32],
        iconAnchor: [16, 16],
        popupAnchor: [0, -18]
      });

      const marker = L.marker(point, { icon });

      const popupContent = `
        <div style="min-width: 200px; padding: 4px; font-family: 'Plus Jakarta Sans', sans-serif;">
          <span style="font-size: 0.7rem; font-weight: 800; color: #818cf8; text-transform: uppercase;">Stop ${stop.stop_number} · ${stop.time_or_period}</span>
          <h4 style="font-size: 0.95rem; font-weight: 700; margin: 4px 0 4px 0; color: #fff;">${stop.place_name}</h4>
          ${stop.activity ? `<p style="font-size: 0.8rem; color: #cbd5e1; margin-bottom: 6px;">${stop.activity}</p>` : ''}
          ${stop.item_id ? `
            <button onclick="openPreviewModal('${stop.item_id}')" style="
              width: 100%; background: #6366f1; color: #fff; border: none; padding: 5px 10px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; cursor: pointer;
            ">🎬 View Saved Clip</button>
          ` : ''}
        </div>
      `;

      marker.bindPopup(popupContent);
      marker.addTo(this.map);
      this.planMarkers.push(marker);
    });

    // Draw route connecting polyline
    if (latlngs.length > 1) {
      this.routePolyline = L.polyline(latlngs, {
        color: '#6366f1',
        weight: 5,
        opacity: 0.85,
        dashArray: '8, 8',
        lineCap: 'round'
      }).addTo(this.map);
    }

    this.map.fitBounds(latlngs, { padding: [80, 80], maxZoom: 15 });

    // Add / Update route reset banner
    this.renderRouteBanner(validStops.length);
  }

  renderRouteBanner(stopCount) {
    let banner = document.getElementById('map-route-banner');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'map-route-banner';
      banner.style.cssText = `
        position: absolute;
        top: 1rem;
        right: 1rem;
        z-index: 1000;
        background: rgba(17, 24, 39, 0.9);
        border: 1px solid var(--accent-primary);
        padding: 8px 14px;
        border-radius: 8px;
        display: flex;
        align-items: center;
        gap: 10px;
        color: #fff;
        font-size: 0.82rem;
        box-shadow: 0 10px 25px rgba(0,0,0,0.6);
        backdrop-filter: blur(10px);
      `;
      const mapContainer = document.getElementById('map-element');
      mapContainer.appendChild(banner);
    }

    banner.innerHTML = `
      <span>🗺️ <strong>Active Plan Route</strong>: ${stopCount} Stops</span>
      <button onclick="window.mapManager.loadPins()" style="
        background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2);
        color: #fff; border-radius: 4px; padding: 3px 8px; font-size: 0.72rem; cursor: pointer;
      ">Show All Saved Pins</button>
    `;
    banner.style.display = 'flex';
  }

  clearPlanRoute(restorePins = true) {
    if (this.routePolyline) {
      try { this.map.removeLayer(this.routePolyline); } catch (e) {}
      this.routePolyline = null;
    }
    this.planMarkers.forEach(m => {
      try { this.map.removeLayer(m); } catch (e) {}
    });
    this.planMarkers = [];

    const banner = document.getElementById('map-route-banner');
    if (banner) banner.style.display = 'none';

    if (restorePins && this.markers.length > 0) {
      this.markers.forEach(m => m.addTo(this.map));
    }
  }
}

document.addEventListener('DOMContentLoaded', () => {
  window.mapManager = new MapManager();
});
