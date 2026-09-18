// ReelToReal Main Frontend Logic

let currentCategory = 'all';
let savedItems = [];

document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  initIngestModal();
  loadSavedItems();
  initSearch();
});

// Tab Switcher
function initTabs() {
  const tabs = document.querySelectorAll('.nav-tab');
  const views = document.querySelectorAll('.tab-view');

  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const targetId = tab.getAttribute('data-tab');
      
      tabs.forEach(t => t.classList.remove('active'));
      views.forEach(v => v.classList.remove('active'));

      tab.classList.add('active');
      const targetView = document.getElementById(targetId);
      if (targetView) targetView.classList.add('active');

      if (targetId === 'map-view' && window.mapManager) {
        window.mapManager.invalidateSize();
        window.mapManager.loadPins();
      }
    });
  });

  // Category Pills
  const catPills = document.querySelectorAll('.cat-pill');
  catPills.forEach(pill => {
    pill.addEventListener('click', () => {
      catPills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      currentCategory = pill.getAttribute('data-category');
      renderFeedCards();
    });
  });
}

// Ingest Modal & Drag-Drop
function initIngestModal() {
  const modal = document.getElementById('ingest-modal');
  const btnOpen = document.getElementById('btn-open-ingest');
  const btnClose = document.getElementById('btn-close-ingest');
  const dropzone = document.getElementById('upload-dropzone');
  const fileInput = document.getElementById('file-input');
  const urlForm = document.getElementById('url-ingest-form');
  const progressBox = document.getElementById('processing-indicator');

  btnOpen.addEventListener('click', () => modal.classList.add('active'));
  btnClose.addEventListener('click', () => {
    modal.classList.remove('active');
    progressBox.classList.remove('active');
  });

  // Dropzone drag-and-drop
  ['dragenter', 'dragover'].forEach(name => {
    dropzone.addEventListener(name, (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });
  });

  ['dragleave', 'drop'].forEach(name => {
    dropzone.addEventListener(name, (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
    });
  });

  dropzone.addEventListener('drop', (e) => {
    const files = e.dataTransfer.files;
    if (files.length > 0) handleFileUpload(files[0]);
  });

  fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) handleFileUpload(e.target.files[0]);
  });

  // URL Ingest
  urlForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const urlInput = document.getElementById('video-url-input');
    const url = urlInput.value.trim();
    if (!url) return;

    showProcessing("Downloading & Analyzing video from link...");

    try {
      const resp = await fetch('/api/process/url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url })
      });
      const data = await resp.json();

      if (data.success) {
        urlInput.value = '';
        modal.classList.remove('active');
        await loadSavedItems();
        showNotification("Video added to Knowledge Base! ✨");
      } else {
        alert(data.message || "Failed to process video link.");
      }
    } catch (err) {
      alert("Error connecting to server: " + err.message);
    } finally {
      hideProcessing();
    }
  });
}

// File Upload Handler
async function handleFileUpload(file) {
  const modal = document.getElementById('ingest-modal');
  showProcessing(`Analyzing "${file.name}" with Gemini Multimodal API...`);

  const formData = new FormData();
  formData.append('file', file);

  try {
    const resp = await fetch('/api/process/file', {
      method: 'POST',
      body: formData
    });
    const data = await resp.json();

    if (data.success) {
      modal.classList.remove('active');
      await loadSavedItems();
      showNotification("Video analyzed and saved! ✨");
    } else {
      alert(data.message || "Error analyzing video file.");
    }
  } catch (err) {
    alert("Upload failed: " + err.message);
  } finally {
    hideProcessing();
  }
}

function showProcessing(text) {
  const box = document.getElementById('processing-indicator');
  const label = document.getElementById('processing-status-text');
  label.textContent = text;
  box.classList.add('active');
}

function hideProcessing() {
  const box = document.getElementById('processing-indicator');
  box.classList.remove('active');
}

// Search
function initSearch() {
  const input = document.getElementById('feed-search-input');
  input.addEventListener('input', () => {
    renderFeedCards();
  });
}

// Fetch Items from Backend
async function loadSavedItems() {
  try {
    const resp = await fetch('/api/items');
    savedItems = await resp.json();
    renderFeedCards();
    if (window.mapManager) window.mapManager.loadPins();
  } catch (err) {
    console.error("Failed to load saved items:", err);
  }
}

// Render Feed Cards
function renderFeedCards() {
  const grid = document.getElementById('feed-cards-grid');
  const emptyState = document.getElementById('feed-empty-state');
  const searchVal = document.getElementById('feed-search-input').value.toLowerCase().trim();

  let filtered = savedItems.filter(item => {
    const matchesCategory = (currentCategory === 'all') || (item.analysis.category.toLowerCase() === currentCategory);
    
    let matchesSearch = true;
    if (searchVal) {
      const blob = (item.analysis.search_blob || "").toLowerCase();
      const title = item.analysis.title.toLowerCase();
      matchesSearch = blob.includes(searchVal) || title.includes(searchVal);
    }
    return matchesCategory && matchesSearch;
  });

  grid.innerHTML = '';

  if (filtered.length === 0) {
    emptyState.style.display = 'block';
    return;
  } else {
    emptyState.style.display = 'none';
  }

  filtered.forEach(item => {
    const card = document.createElement('div');
    card.className = 'clip-card';

    const catClass = `cat-${item.analysis.category.toLowerCase()}`;
    const place = item.analysis.entities.place_name || '';
    const city = item.analysis.entities.city || '';
    const locationText = place ? `${place}${city ? ` · ${city}` : ''}` : (city || '');

    const highlights = (item.analysis.entities.highlights || []).slice(0, 2).join(', ');
    const tips = (item.analysis.entities.actionable_tips || []).slice(0, 1).join('; ');

    const tagsHtml = (item.analysis.tags || []).slice(0, 4).map(t => `<span class="item-tag">#${t}</span>`).join('');

    card.innerHTML = `
      <div>
        <div class="card-top">
          <span class="category-tag ${catClass}">${item.analysis.category}</span>
          <button class="btn-delete" title="Delete" onclick="deleteItem('${item.id}', event)">🗑️</button>
        </div>
        <h3 class="card-title">${item.analysis.title}</h3>
        ${locationText ? `<div class="place-badge">📍 ${locationText}</div>` : ''}
        <p class="card-summary">${item.analysis.transcript_summary || item.analysis.visual_summary}</p>
        
        <div class="card-entities">
          ${item.analysis.timeline_events && item.analysis.timeline_events.length > 0 ? `<div class="entity-row"><span class="entity-label" style="color: #60a5fa;">Timeline:</span><span class="entity-val" style="color: #60a5fa; font-weight: 700;">⏱️ ${item.analysis.timeline_events.length} activities logged</span></div>` : ''}
          ${item.analysis.entities.cuisine_or_type ? `<div class="entity-row"><span class="entity-label">Type:</span><span class="entity-val">${item.analysis.entities.cuisine_or_type}</span></div>` : ''}
          ${highlights ? `<div class="entity-row"><span class="entity-label">Must-try:</span><span class="entity-val">${highlights}</span></div>` : ''}
          ${tips ? `<div class="entity-row"><span class="entity-label">Tip:</span><span class="entity-val" style="color: #fbbf24;">${tips}</span></div>` : ''}
        </div>

        <div class="tag-list">${tagsHtml}</div>
      </div>

      <div class="card-footer">
        <button class="btn-card-action" onclick="openPreviewModal('${item.id}')">
          <span>🎬</span> View Clip & Analysis
        </button>
        ${item.latitude ? `<span style="font-size: 0.75rem; color: #34d399;">📍 Mapped</span>` : ''}
      </div>
    `;

    grid.appendChild(card);
  });
}

// Delete Item
async function deleteItem(id, event) {
  event.stopPropagation();
  if (!confirm("Are you sure you want to delete this saved video?")) return;

  try {
    const resp = await fetch(`/api/items/${id}`, { method: 'DELETE' });
    if (resp.ok) {
      savedItems = savedItems.filter(i => i.id !== id);
      renderFeedCards();
      if (window.mapManager) window.mapManager.loadPins();
    }
  } catch (err) {
    alert("Delete failed: " + err.message);
  }
}

// Preview Modal
function openPreviewModal(id) {
  const item = savedItems.find(i => i.id === id);
  if (!item) return;

  const modal = document.getElementById('video-preview-modal');
  const title = document.getElementById('preview-modal-title');
  const videoBox = document.getElementById('preview-video-container');
  const detailsBox = document.getElementById('preview-modal-details');

  title.textContent = item.analysis.title;

  if (item.media_url) {
    videoBox.innerHTML = `
      <video controls autoplay style="max-height: 360px; width: 100%; border-radius: 8px;">
        <source src="${item.media_url}" type="video/mp4">
        Your browser does not support the video tag.
      </video>
    `;
  } else {
    videoBox.innerHTML = `<div style="padding: 2rem; color: var(--text-muted);">Source URL: <a href="${item.source_identifier}" target="_blank" style="color: #818cf8;">${item.source_identifier}</a></div>`;
  }

  const highlights = (item.analysis.entities.highlights || []).map(h => `<li>${h}</li>`).join('');
  const tips = (item.analysis.entities.actionable_tips || []).map(t => `<li>${t}</li>`).join('');
  
  // Render Exhaustive Timeline
  let timelineHtml = '';
  if (item.analysis.timeline_events && item.analysis.timeline_events.length > 0) {
    const events = item.analysis.timeline_events.map((ev, idx) => `
      <div style="
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.06);
        border-left: 3px solid var(--accent-primary);
        border-radius: 6px;
        padding: 0.75rem 1rem;
        margin-bottom: 0.6rem;
      ">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
          <span style="font-weight: 700; color: #fff; font-size: 0.9rem;">${idx + 1}. ${ev.activity}</span>
          <span style="font-size: 0.75rem; color: #a5b4fc; background: rgba(99,102,241,0.15); padding: 2px 8px; border-radius: 4px;">⏱️ ${ev.time_or_sequence}</span>
        </div>
        ${ev.location ? `<div style="font-size: 0.75rem; color: #34d399; margin-bottom: 4px;">📍 Location: ${ev.location}</div>` : ''}
        <div style="font-size: 0.8rem; color: #cbd5e1; margin-bottom: 3px;"><strong>🗣️ Spoken Audio:</strong> ${ev.audio_details}</div>
        <div style="font-size: 0.8rem; color: #94a3b8;"><strong>👁️ Visuals Shown:</strong> ${ev.visual_details}</div>
      </div>
    `).join('');

    timelineHtml = `
      <div style="margin-top: 1rem;">
        <h4 style="color: #60a5fa; margin-bottom: 0.5rem; display: flex; align-items: center; gap: 6px;">
          <span>⏳</span> Chronological Activity Timeline (Every Event & Detail)
        </h4>
        <div style="max-height: 280px; overflow-y: auto; padding-right: 4px;">
          ${events}
        </div>
      </div>
    `;
  }

  // Places & Products tags
  const placesHtml = (item.analysis.all_places_visited || []).map(p => `<span style="font-size: 0.75rem; background: rgba(14,165,233,0.15); color: #38bdf8; border: 1px solid rgba(14,165,233,0.3); padding: 2px 8px; border-radius: 4px;">📍 ${p}</span>`).join(' ');
  const productsHtml = (item.analysis.all_products_or_items || []).map(pr => `<span style="font-size: 0.75rem; background: rgba(234,179,8,0.15); color: #facc15; border: 1px solid rgba(234,179,8,0.3); padding: 2px 8px; border-radius: 4px;">🛍️ ${pr}</span>`).join(' ');

  detailsBox.innerHTML = `
    <div style="margin-top: 1rem;">
      <h4 style="color: #fff; margin-bottom: 0.25rem;">Overall Audio & Spoken Summary</h4>
      <p style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 0.75rem;">${item.analysis.transcript_summary}</p>

      <h4 style="color: #fff; margin-bottom: 0.25rem;">Overall Visual & Frame Summary</h4>
      <p style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 0.75rem;">${item.analysis.visual_summary}</p>

      ${placesHtml ? `<div style="margin-bottom: 0.75rem;"><strong style="font-size: 0.8rem; color: #fff;">Places Visited:</strong> <div style="display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px;">${placesHtml}</div></div>` : ''}
      ${productsHtml ? `<div style="margin-bottom: 0.75rem;"><strong style="font-size: 0.8rem; color: #fff;">Featured Products / Dishes:</strong> <div style="display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px;">${productsHtml}</div></div>` : ''}

      ${timelineHtml}

      ${highlights ? `<h4 style="color: #facc15; margin-top: 1rem; margin-bottom: 0.25rem;">Key Highlights</h4><ul style="font-size: 0.85rem; color: var(--text-secondary); padding-left: 1.25rem; margin-bottom: 0.75rem;">${highlights}</ul>` : ''}
      ${tips ? `<h4 style="color: #f87171; margin-bottom: 0.25rem;">Actionable Tips</h4><ul style="font-size: 0.85rem; color: var(--text-secondary); padding-left: 1.25rem; margin-bottom: 0.75rem;">${tips}</ul>` : ''}
      
      ${item.analysis.full_audio_transcript ? `
        <details style="margin-top: 0.75rem; background: rgba(0,0,0,0.25); padding: 0.5rem 0.75rem; border-radius: 6px; font-size: 0.8rem;">
          <summary style="cursor: pointer; color: #a5b4fc; font-weight: 600;">📜 Full Spoken Dialogue Breakdown</summary>
          <p style="color: var(--text-secondary); margin-top: 0.5rem; white-space: pre-wrap;">${item.analysis.full_audio_transcript}</p>
        </details>
      ` : ''}
    </div>
  `;

  modal.classList.add('active');
  document.getElementById('btn-close-preview').onclick = () => {
    videoBox.innerHTML = '';
    modal.classList.remove('active');
  };
}

function showNotification(msg) {
  const toast = document.createElement('div');
  toast.style.cssText = `
    position: fixed; bottom: 2rem; right: 2rem;
    background: #6366f1; color: #fff; padding: 0.75rem 1.5rem;
    border-radius: 8px; font-weight: 600; font-size: 0.9rem;
    box-shadow: 0 10px 25px rgba(99,102,241,0.5); z-index: 2000;
    animation: fadeIn 0.3s ease;
  `;
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}
