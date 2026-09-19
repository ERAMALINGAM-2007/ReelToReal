// ReelToReal AI Planner & Multi-Turn Chat Logic

let chatHistory = [];

document.addEventListener('DOMContentLoaded', () => {
  initPlannerChat();
});

function initPlannerChat() {
  const form = document.getElementById('planner-form');
  const input = document.getElementById('planner-input');
  const btnClear = document.getElementById('btn-clear-chat');
  const chips = document.querySelectorAll('.chip-btn');

  // Suggested prompt chips
  chips.forEach(chip => {
    chip.addEventListener('click', () => {
      const q = chip.getAttribute('data-query');
      input.value = q;
      form.dispatchEvent(new Event('submit'));
    });
  });

  // Clear chat
  btnClear.addEventListener('click', () => {
    chatHistory = [];
    const container = document.getElementById('chat-messages-container');
    container.innerHTML = `
      <div class="chat-msg ai">
        <div class="msg-avatar ai">✨</div>
        <div class="msg-body">
          <p><strong>Chat cleared.</strong> Ask me anything to generate your grounded personalized plan!</p>
        </div>
      </div>
    `;
    document.getElementById('planner-citations-list').innerHTML = `
      <p style="font-size: 0.8rem; color: var(--text-muted);">Saved clips retrieved for your current plan will appear here with clickable timestamps & details.</p>
    `;
    if (window.mapManager) window.mapManager.clearPlanRoute(true);
  });

  // Handle Query Submit
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = input.value.trim();
    if (!query) return;

    input.value = '';
    appendUserMessage(query);

    // Record turn in history
    chatHistory.push({ role: 'user', content: query });

    const typingMsg = appendTypingIndicator();

    try {
      const userId = window.currentUserId || localStorage.getItem('reeltoreal_user_id') || 'default';
      const resp = await fetch('/api/plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          max_items: 5,
          user_id: userId,
          chat_history: chatHistory.slice(-8)
        })
      });

      const data = await resp.json();
      typingMsg.remove();

      // Record assistant turn in history
      chatHistory.push({ role: 'assistant', content: data.plan_narrative });

      appendAIMessage(data.plan_narrative, data.citations, data.stops);
      updateSidebarCitations(data.citations);
    } catch (err) {
      typingMsg.remove();
      appendAIMessage("Sorry, I encountered an error creating your plan: " + err.message, [], []);
    }
  });
}

function appendUserMessage(text) {
  const container = document.getElementById('chat-messages-container');
  const msg = document.createElement('div');
  msg.className = 'chat-msg user';
  msg.innerHTML = `
    <div class="msg-avatar user">👤</div>
    <div class="msg-body">${escapeHtml(text)}</div>
  `;
  container.appendChild(msg);
  container.scrollTop = container.scrollHeight;
}

function appendTypingIndicator() {
  const container = document.getElementById('chat-messages-container');
  const msg = document.createElement('div');
  msg.className = 'chat-msg ai';
  msg.innerHTML = `
    <div class="msg-avatar ai">✨</div>
    <div class="msg-body" style="display: flex; align-items: center; gap: 8px;">
      <span style="font-size: 0.85rem; color: var(--text-secondary);">Searching personal knowledge base & synthesizing your grounded plan...</span>
      <div class="spinner" style="width: 16px; height: 16px; margin: 0; border-width: 2px;"></div>
    </div>
  `;
  container.appendChild(msg);
  container.scrollTop = container.scrollHeight;
  return msg;
}

function appendAIMessage(markdownText, citations, stops) {
  const container = document.getElementById('chat-messages-container');
  const msg = document.createElement('div');
  msg.className = 'chat-msg ai';

  // Parse markdown
  const htmlContent = window.marked ? window.marked.parse(markdownText) : markdownText;

  // Render Citations
  let citationsHtml = '';
  if (citations && citations.length > 0) {
    const pills = citations.map(c => `
      <span class="citation-pill" onclick="openPreviewModal('${c.id}')">
        📹 ${c.title} ${c.place_name ? `(${c.place_name})` : ''}
      </span>
    `).join('');

    citationsHtml = `
      <div class="citation-pill-container">
        <span style="font-size: 0.75rem; color: var(--text-muted); width: 100%;">Grounded in saved clips:</span>
        ${pills}
      </div>
    `;
  }

  // Render Timetable Stops if available
  let stopsHtml = '';
  if (stops && stops.length > 0) {
    const stopPills = stops.map(s => `
      <div style="
        display: flex; align-items: center; gap: 8px;
        background: rgba(255,255,255,0.04); border: 1px solid var(--border-color);
        padding: 5px 10px; border-radius: 6px; font-size: 0.8rem;
      ">
        <span style="background: #6366f1; color: #fff; width: 20px; height: 20px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 0.75rem; font-weight: 700;">${s.stop_number}</span>
        <strong style="color: #fff;">${s.place_name}</strong>
        <span style="color: var(--text-muted); font-size: 0.75rem;">(${s.time_or_period})</span>
      </div>
    `).join('');

    stopsHtml = `
      <div style="margin-top: 0.85rem; padding: 0.75rem; background: rgba(99,102,241,0.08); border: 1px solid rgba(99,102,241,0.2); border-radius: 8px;">
        <div style="font-size: 0.78rem; font-weight: 700; color: #a5b4fc; margin-bottom: 6px; text-transform: uppercase;">📍 Plan Stops Overview</div>
        <div style="display: flex; flex-direction: column; gap: 5px;">${stopPills}</div>
      </div>
    `;
  }

  // Plan Action Buttons (View on Map & Copy Itinerary)
  const stopsJsonEscaped = escapeAttr(JSON.stringify(stops || []));
  const rawTextEscaped = escapeAttr(markdownText);

  const actionsHtml = `
    <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 0.85rem; padding-top: 0.5rem; border-top: 1px solid rgba(255,255,255,0.06);">
      ${stops && stops.length > 0 ? `
        <button class="btn-plan-action" onclick="viewPlanOnMap(this)" data-stops='${stopsJsonEscaped}'>
          <span>🗺️</span> View Plan on Map
        </button>
      ` : ''}
      <button class="btn-plan-action" onclick="copyPlanToClipboard(this)" data-plan='${rawTextEscaped}'>
        <span>📋</span> Copy Itinerary
      </button>
    </div>
  `;

  // Quick Follow-Up Chips
  const followUpChipsHtml = `
    <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 0.75rem;">
      <span style="font-size: 0.72rem; color: var(--text-muted); align-self: center;">Ask follow-up:</span>
      <button class="btn-followup-chip" onclick="sendFollowUp(this)">💡 Make it more budget-friendly</button>
      <button class="btn-followup-chip" onclick="sendFollowUp(this)">💡 What are the key tips & hours?</button>
      <button class="btn-followup-chip" onclick="sendFollowUp(this)">💡 Suggest another dessert or drink spot</button>
    </div>
  `;

  msg.innerHTML = `
    <div class="msg-avatar ai">✨</div>
    <div class="msg-body">
      ${htmlContent}
      ${stopsHtml}
      ${citationsHtml}
      ${actionsHtml}
      ${followUpChipsHtml}
    </div>
  `;
  container.appendChild(msg);
  container.scrollTop = container.scrollHeight;
}

// Map Routing from Plan
window.viewPlanOnMap = function(btn) {
  try {
    const stops = JSON.parse(btn.getAttribute('data-stops') || '[]');
    if (!stops || stops.length === 0) return;

    // Switch active tab to Map View
    const mapTab = document.querySelector('.nav-tab[data-tab="map-view"]');
    if (mapTab) mapTab.click();

    setTimeout(() => {
      if (window.mapManager) {
        window.mapManager.invalidateSize();
        window.mapManager.highlightPlanRoute(stops);
      }
    }, 200);
  } catch (err) {
    console.error("Failed to view plan on map:", err);
  }
};

// Copy Itinerary to Clipboard
window.copyPlanToClipboard = async function(btn) {
  const planText = btn.getAttribute('data-plan') || '';
  try {
    await navigator.clipboard.writeText(planText);
    if (typeof showNotification === 'function') {
      showNotification("Itinerary copied to clipboard! 📋");
    } else {
      alert("Itinerary copied to clipboard!");
    }
  } catch (err) {
    console.warn("Clipboard API write failed, fallback:", err);
    alert("Plan copied!");
  }
};

// Quick follow-up trigger
window.sendFollowUp = function(btn) {
  const query = btn.textContent.replace('💡', '').trim();
  const input = document.getElementById('planner-input');
  const form = document.getElementById('planner-form');
  if (input && form) {
    input.value = query;
    form.dispatchEvent(new Event('submit'));
  }
};

function updateSidebarCitations(citations) {
  const sidebar = document.getElementById('planner-citations-list');
  if (!citations || citations.length === 0) {
    sidebar.innerHTML = `<p style="font-size: 0.8rem; color: var(--text-muted);">No specific saved clips matched this query.</p>`;
    return;
  }

  sidebar.innerHTML = '';
  citations.forEach(c => {
    const card = document.createElement('div');
    card.style.cssText = `
      background: rgba(255,255,255,0.04);
      border: 1px solid var(--border-color);
      border-radius: 8px;
      padding: 0.75rem;
      cursor: pointer;
      transition: all 0.2s;
    `;
    card.onmouseover = () => card.style.borderColor = '#6366f1';
    card.onmouseout = () => card.style.borderColor = 'rgba(255,255,255,0.08)';
    card.onclick = () => openPreviewModal(c.id);

    card.innerHTML = `
      <div style="font-size: 0.85rem; font-weight: 700; color: #fff; margin-bottom: 2px;">${c.title}</div>
      ${c.place_name ? `<div style="font-size: 0.75rem; color: #a5b4fc;">📍 ${c.place_name} (${c.city || ''})</div>` : ''}
      <div style="font-size: 0.7rem; color: var(--text-muted); margin-top: 4px; display: flex; justify-content: space-between;">
        <span>${c.category.toUpperCase()}</span>
        <span style="color: #34d399;">Match: ${Math.round(c.similarity_score * 100)}%</span>
      </div>
    `;
    sidebar.appendChild(card);
  });
}

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function escapeAttr(str) {
  return str.replace(/'/g, "&#39;").replace(/"/g, "&quot;");
}
