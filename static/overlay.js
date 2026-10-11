async function loadOverlay() {
  const res = await fetch('/api/state');
  const state = await res.json();

  const root = document.getElementById('overlayRoot');
  root.classList.toggle('hidden', !state.overlay_visible);

  renderPlaying(state.overlay_playing || []);
  renderQueue(state.waiting || []);
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, s => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
  }[s]));
}

function renderPlaying(players) {
  const root = document.getElementById('overlayPlaying');

  if (!players.length) {
    root.innerHTML = `<div class="player-card main"><div class="player-name">Noch offen</div><div class="player-meta">!join im Chat und ab in die Queue</div></div>`;
    return;
  }

  root.innerHTML = players.slice(0, 5).map(p => `
    <div class="player-card main">
      <div class="player-name">${esc(p.label)}</div>
      <div class="player-meta">
        ${p.twitch_name ? 'Twitch linked' : 'Steam detected'}
        · In Folge ${p.in_a_row || 0}x
        · Gesamt ${p.played_count || 0}x
      </div>
    </div>
  `).join('');
}

function renderQueue(waiting) {
  const root = document.getElementById('overlayQueue');

  if (!waiting.length) {
    root.innerHTML = `<div class="queue-item"><span>Queue ist leer</span><span class="queue-pos">!join</span></div>`;
    return;
  }

  root.innerHTML = waiting.slice(0, 6).map((q, i) => `
    <div class="queue-item">
      <span>${esc(q.display_name || q.twitch_name)}</span>
      <span class="queue-pos">#${i + 1}</span>
    </div>
  `).join('');
}

loadOverlay();
setInterval(loadOverlay, 1200);
