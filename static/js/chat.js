// ReelToReal AI Planner & Chat Logic

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
  });

  // Handle Query Submit
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = input.value.trim();
    if (!query) return;

    input.value = '';
    appendUserMessage(query);

    const typingMsg = appendTypingIndicator();

    try {
      const resp = await fetch('/api/plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, max_items: 5 })
      });

      const data = await resp.json();
      typingMsg.remove();

      appendAIMessage(data.plan_narrative, data.citations);
      updateSidebarCitations(data.citations);
    } catch (err) {
      typingMsg.remove();
      appendAIMessage("Sorry, I encountered an error creating your plan: " + err.message, []);
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
      <span style="font-size: 0.85rem; color: var(--text-secondary);">Searching saved knowledge base & synthesizing your plan...</span>
      <div class="spinner" style="width: 16px; height: 16px; margin: 0; border-width: 2px;"></div>
    </div>
  `;
  container.appendChild(msg);
  container.scrollTop = container.scrollHeight;
  return msg;
}

function appendAIMessage(markdownText, citations) {
  const container = document.getElementById('chat-messages-container');
  const msg = document.createElement('div');
  msg.className = 'chat-msg ai';

  // Parse markdown
  const htmlContent = window.marked ? window.marked.parse(markdownText) : markdownText;

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

  msg.innerHTML = `
    <div class="msg-avatar ai">✨</div>
    <div class="msg-body">
      ${htmlContent}
      ${citationsHtml}
    </div>
  `;
  container.appendChild(msg);
  container.scrollTop = container.scrollHeight;
}

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
