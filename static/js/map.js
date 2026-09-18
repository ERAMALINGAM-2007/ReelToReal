// ReelToReal OpenStreetMap Leaflet Manager (100% Free - No API Key Required)

class MapManager {
  constructor() {
    this.map = null;
    this.markers = [];
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
      // Create Leaflet map
      this.map = L.map('map-element', {
        zoomControl: true,
        attributionControl: true
      }).setView([35.6762, 139.6503], 12);

      // OpenStreetMap standard tile layer - 100% free, public, no API key needed
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      }).addTo(this.map);

      this.initialized = true;
      this.loadPins();
    } catch (err) {
      console.error("Error initializing Leaflet map:", err);
    }
  }

  invalidateSize() {
    if (!this.initialized) {
      this.initMap();
    }
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

    try {
      const resp = await fetch('/api/map/pins');
      const pins = await resp.json();

      // Clear existing markers
      this.markers.forEach(m => {
        try { this.map.removeLayer(m); } catch (e) {}
      });
      this.markers = [];

      if (!pins || pins.length === 0) return;

      const group = [];

      pins.forEach(pin => {
        if (pin.latitude && pin.longitude) {
          const marker = this.createCategoryMarker(pin);
          marker.addTo(this.map);
          this.markers.push(marker);
          group.push([pin.latitude, pin.longitude]);
        }
      });

      if (group.length > 0) {
        this.map.fitBounds(group, { padding: [50, 50], maxZoom: 14 });
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
}

document.addEventListener('DOMContentLoaded', () => {
  window.mapManager = new MapManager();
});
