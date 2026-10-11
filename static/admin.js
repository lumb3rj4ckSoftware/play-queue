let latestState = null;
let detectedSignature = '';
let detectedRenderLocked = false;
const detectedSelections = new Map();
let drawSelectionInitialized = false;
let drawStartInFlight = false;
const drawCandidateSelection = new Set();
const drawChallengerSelection = new Set();

async function fetchState() {
  const res = await fetch('/api/state');
  latestState = await res.json();
  render();
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, s => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
  }[s]));
}

function render() {
  renderDrawSetup();
  renderDrawLastResult();
  renderQueue();
  renderPlaying();
  renderDetectedIfNeeded();
  renderExtras();
}

function cleanupDrawSelection() {
  const playingIds = new Set((latestState.playing || []).map(p => Number(p.id)));
  const waitingIds = new Set((latestState.waiting || []).map(p => Number(p.id)));
  [...drawCandidateSelection].forEach(id => {
    if (!playingIds.has(id)) drawCandidateSelection.delete(id);
  });
  [...drawChallengerSelection].forEach(id => {
    if (!waitingIds.has(id)) drawChallengerSelection.delete(id);
  });
}

function autoSelectDraw(renderAfter = true) {
  if (!latestState) return;
  drawCandidateSelection.clear();
  drawChallengerSelection.clear();

  const playing = latestState.playing || [];
  const preferred = playing.filter(p => Number(p.in_a_row || 0) >= 2);
  const candidates = (preferred.length >= 2 ? preferred : playing).slice(0, 4);
  candidates.forEach(p => drawCandidateSelection.add(Number(p.id)));

  const challengerLimit = Math.min(2, candidates.length, (latestState.waiting || []).length);
  (latestState.waiting || []).slice(0, challengerLimit).forEach(p => {
    drawChallengerSelection.add(Number(p.id));
  });

  drawSelectionInitialized = true;
  if (renderAfter) renderDrawSetup();
}

function renderDrawSetup() {
  if (!latestState) return;
  if (!drawSelectionInitialized) autoSelectDraw(false);
  cleanupDrawSelection();

  const playing = latestState.playing || [];
  const waiting = latestState.waiting || [];
  const candidateRoot = document.getElementById('drawCandidateList');
  const challengerRoot = document.getElementById('drawChallengerList');

  candidateRoot.innerHTML = playing.length ? playing.map(player => {
    const id = Number(player.id);
    const checked = drawCandidateSelection.has(id) ? 'checked' : '';
    return `
      <label class="draw-admin-option ${checked ? 'selected' : ''}">
        <input type="checkbox" ${checked} onchange="toggleDrawCandidate(${id}, this.checked)">
        <span class="draw-option-avatar">${esc(initials(player.display_name || player.twitch_name))}</span>
        <span class="draw-option-copy">
          <strong>${esc(player.display_name || player.twitch_name)}</strong>
          <small>In Folge ${player.in_a_row || 0}x · Gesamt ${player.played_count || 0}x</small>
        </span>
        <span class="draw-option-check">✓</span>
      </label>
    `;
  }).join('') : `<p class="muted empty-draw-list">Niemand ist aktuell als spielend markiert.</p>`;

  challengerRoot.innerHTML = waiting.length ? waiting.map((player, index) => {
    const id = Number(player.id);
    const checked = drawChallengerSelection.has(id) ? 'checked' : '';
    return `
      <label class="draw-admin-option challenger ${checked ? 'selected' : ''}">
        <input type="checkbox" ${checked} onchange="toggleDrawChallenger(${id}, this.checked)">
        <span class="draw-option-avatar">${esc(initials(player.display_name || player.twitch_name))}</span>
        <span class="draw-option-copy">
          <strong>#${index + 1} ${esc(player.display_name || player.twitch_name)}</strong>
          <small>wartet seit ${esc(formatTime(player.joined_at))}</small>
        </span>
        <span class="draw-option-check">✓</span>
      </label>
    `;
  }).join('') : `<p class="muted empty-draw-list">Aktuell wartet niemand in der Queue.</p>`;

  const candidateCount = drawCandidateSelection.size;
  const challengerCount = drawChallengerSelection.size;
  document.getElementById('candidateCount').textContent = `${candidateCount} / 4`;
  document.getElementById('challengerCount').textContent = `${challengerCount} gewählt`;

  const hint = document.getElementById('drawSelectionHint');
  const button = document.getElementById('startDrawButton');
  let message = `${challengerCount} von ${candidateCount} Spielern machen Platz.`;
  let valid = true;
  if (candidateCount < 2) {
    message = 'Mindestens zwei aktuell Spielende auswählen.';
    valid = false;
  } else if (challengerCount < 1) {
    message = 'Mindestens einen Nachrücker auswählen.';
    valid = false;
  } else if (challengerCount > candidateCount) {
    message = 'Es sind mehr Nachrücker als Kandidaten ausgewählt.';
    valid = false;
  }
  hint.textContent = message;
  button.disabled = !valid || drawStartInFlight;
  button.textContent = drawStartInFlight ? 'Wird ausgelost …' : 'Schichtwechsel starten';
}

function toggleDrawCandidate(id, checked) {
  id = Number(id);
  if (checked && drawCandidateSelection.size >= 4 && !drawCandidateSelection.has(id)) {
    alert('Es können maximal vier Spieler an einer Auslosung teilnehmen.');
  } else if (checked) {
    drawCandidateSelection.add(id);
  } else {
    drawCandidateSelection.delete(id);
  }
  renderDrawSetup();
}

function toggleDrawChallenger(id, checked) {
  id = Number(id);
  if (checked && drawChallengerSelection.size >= 4 && !drawChallengerSelection.has(id)) {
    alert('Es können maximal vier Spieler gleichzeitig nachrücken.');
  } else if (checked) {
    drawChallengerSelection.add(id);
  } else {
    drawChallengerSelection.delete(id);
  }
  renderDrawSetup();
}

function initials(name) {
  const words = String(name || '?').trim().split(/\s+/).filter(Boolean);
  if (!words.length) return '?';
  return words.slice(0, 2).map(word => word[0]).join('').toUpperCase();
}

function formatTime(value) {
  if (!value) return 'unbekannt';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleTimeString('de-DE', {hour: '2-digit', minute: '2-digit'});
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  let payload = {};
  try {
    payload = await response.json();
  } catch (_) {
    payload = {ok: false, message: `Ungültige Serverantwort (${response.status}).`};
  }
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.message || `Serverfehler (${response.status}).`);
  }
  return payload;
}

async function startDraw() {
  const candidateIds = [...drawCandidateSelection];
  const challengerIds = [...drawChallengerSelection];
  const namesById = new Map((latestState.queue || []).map(p => [Number(p.id), p.display_name || p.twitch_name]));
  const candidateNames = candidateIds.map(id => namesById.get(id)).join(', ');
  const challengerNames = challengerIds.map(id => namesById.get(id)).join(', ');
  const confirmed = confirm(
    `Auslosung jetzt starten?\n\nKandidaten: ${candidateNames}\nNachrücker: ${challengerNames}\n\nDas Ergebnis wird sofort gezogen und in die Queue übernommen.`
  );
  if (!confirmed) return;

  drawStartInFlight = true;
  renderDrawSetup();
  try {
    await requestJson('/api/draw/start', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({candidate_ids: candidateIds, challenger_ids: challengerIds})
    });
    drawCandidateSelection.clear();
    drawChallengerSelection.clear();
    drawSelectionInitialized = true;
    await fetchState();
  } catch (error) {
    alert(error.message);
  } finally {
    drawStartInFlight = false;
    renderDrawSetup();
  }
}

function renderDrawLastResult() {
  const root = document.getElementById('drawLastResult');
  const draw = latestState.draw;
  if (!draw) {
    root.innerHTML = '';
    return;
  }
  const outgoing = (draw.outgoing || []).map(p => esc(p.label)).join(', ');
  const incoming = (draw.challengers || []).map(p => esc(p.label)).join(', ');
  root.innerHTML = `
    <div class="draw-result-copy">
      <span class="draw-result-state ${draw.active ? 'active' : ''}">${draw.active ? 'Animation läuft' : 'Letztes Ergebnis'}</span>
      <strong>Bank: ${outgoing || '–'}</strong>
      <small>Neu dabei: ${incoming || '–'} · ${esc(formatTime(draw.created_at))}</small>
    </div>
    <div class="row-actions">
      <button class="ghost" onclick="replayDraw()">Animation wiederholen</button>
      ${draw.active ? '<button class="danger" onclick="hideDraw()">Animation ausblenden</button>' : ''}
    </div>
  `;
}

async function replayDraw() {
  try {
    await requestJson('/api/draw/replay', {method: 'POST'});
    await fetchState();
  } catch (error) {
    alert(error.message);
  }
}

async function hideDraw() {
  const draw = latestState.draw || {};
  try {
    await requestJson('/api/draw/hide', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        draw_id: draw.draw_id,
        animation_revision: draw.animation_revision
      })
    });
    await fetchState();
  } catch (error) {
    alert(error.message);
  }
}

function counterBadges(item) {
  return `
    <span class="badge">In Folge ${item.in_a_row || 0}x</span>
    <span class="badge">Gesamt ${item.played_count || 0}x</span>
  `;
}

function renderQueue() {
  const root = document.getElementById('queueList');
  const waiting = latestState.waiting || [];

  if (!waiting.length) {
    root.innerHTML = `<p class="muted">Niemand wartet aktuell. Chat muss mal REIN IN DEN BUS.</p>`;
    return;
  }

  root.innerHTML = waiting.map((q, index) => `
    <div class="row">
      <div>
        <div class="row-title">#${index + 1} ${esc(q.display_name || q.twitch_name)}
          ${counterBadges(q)}
        </div>
        <div class="row-sub">
          Twitch: ${esc(q.twitch_name)}
          ${q.steam_name ? ` · Steam: ${esc(q.steam_name)}` : ''}
        </div>
      </div>
      <div class="row-actions">
        <button onclick="markPlaying(${q.id})">Zu aktuell spielend hinzufügen</button>
        <button class="danger" onclick="removeFromQueue(${q.id})">Entfernen</button>
      </div>
    </div>
  `).join('');
}

function renderPlaying() {
  const root = document.getElementById('playingList');
  const playing = latestState.playing || [];

  if (!playing.length) {
    root.innerHTML = `<p class="muted">Aktuell ist niemand manuell als spielend markiert.</p>`;
    return;
  }

  root.innerHTML = playing.map(q => `
    <div class="row playing-row">
      <div>
        <div class="row-title">${esc(q.display_name || q.twitch_name)}
          ${counterBadges(q)}
        </div>
        <div class="row-sub">
          ${q.steam_name ? `Steam: ${esc(q.steam_name)} · ` : ''}
          ${q.steam_id ? `SteamID: ${esc(q.steam_id)}` : 'Keine SteamID verknüpft'}
          ${(q.steam_accounts || []).length > 1 ? `<div class="account-aliases">Weitere Konten: ${q.steam_accounts.filter(a => a.steam_id !== q.steam_id).map(a => `${esc(a.steam_name || a.steam_id)} (${esc(a.steam_id)})`).join(' · ')}</div>` : ''}
        </div>
      </div>
      <div class="row-actions">
        <button onclick="moveBackToWaiting(${q.id})" class="ghost">Zurück in Queue</button>
        <button class="danger" onclick="removeFromQueue(${q.id})">Abschließen</button>
      </div>
    </div>
  `).join('');
}

function buildDetectedSignature() {
  const detected = latestState.detected_players || [];
  const queueUsers = latestState.link_users || latestState.queue || [];
  return JSON.stringify({
    detected: detected.map(p => ({
      steam_id: p.steam_id,
      steam_name: p.steam_name,
      display_name: p.display_name,
      team: p.team,
      twitch_name: p.twitch_name,
      played_count: p.played_count || 0,
      in_a_row: p.in_a_row || 0,
      steam_accounts: p.steam_accounts || []
    })),
    search: document.getElementById('detectedSearch').value,
    queue: queueUsers.map(q => ({
      twitch_name: q.twitch_name,
      display_name: q.display_name,
      status: q.status,
      last_joined_at: q.last_joined_at,
      steam_accounts: q.steam_accounts || []
    }))
  });
}

function renderDetectedIfNeeded() {
  if (detectedRenderLocked) return;

  const focused = document.activeElement;
  if (focused && focused.closest && focused.closest('#detectedList')) return;

  const signature = buildDetectedSignature();
  if (signature === detectedSignature) return;

  detectedSignature = signature;
  renderDetected();
}

function renderDetected() {
  const root = document.getElementById('detectedList');
  const allDetected = latestState.detected_players || [];
  const query = document.getElementById('detectedSearch').value;
  const detected = allDetected.map((p,index) => ({p,index,score:PQNameSearch.rank(query,p)}))
    .filter(item => item.score > 0).sort((a,b) => b.score-a.score || a.index-b.index).map(item => item.p);
  const queueUsers = latestState.link_users || latestState.queue || [];
  document.getElementById('detectedSearchInfo').textContent = `${detected.length} von ${allDetected.length} Spielern`;

  if (!detected.length) {
    root.innerHTML = `<p class="muted">${allDetected.length ? 'Keine passenden Spieler gefunden. Probiere einen kürzeren Namen oder eine SteamID.' : 'Noch keine Spieler via CS2 GSI erkannt.'}</p>`;
    return;
  }

  root.innerHTML = detected.map(p => {
    const selectId = `link-${String(p.steam_id).replace(/[^a-zA-Z0-9_-]/g, '')}`;
    const availableUsers = [...queueUsers];
    if (p.twitch_name && !availableUsers.some(q => q.twitch_name === p.twitch_name)) {
      availableUsers.push({twitch_name:p.twitch_name, display_name:p.display_name, status:'linked', steam_accounts:p.steam_accounts});
    }
    const selectedName = detectedSelections.has(p.steam_id) ? detectedSelections.get(p.steam_id) : p.twitch_name;
    const options = availableUsers.map(q => {
      const selected = q.twitch_name === selectedName ? 'selected' : '';
      const context = q.status === 'playing' ? 'spielt gerade' : q.status === 'waiting' ? 'wartet' : q.status === 'linked' ? 'bereits verknüpft' : `zuletzt in Queue ${formatTime(q.last_joined_at)}`;
      const accounts = (q.steam_accounts || []).length;
      const label = `${q.display_name || q.twitch_name} · ${context}${accounts ? ` · ${accounts} Steam-${accounts === 1 ? 'Konto' : 'Konten'}` : ''}`;
      return `<option value="${esc(q.twitch_name)}" ${selected}>${esc(label)}</option>`;
    }).join('');

    return `
      <div class="row">
        <div>
          <div class="row-title">${esc(p.steam_name || p.steam_id)}
            ${p.twitch_name ? `<span class="badge">verknüpft: ${esc(p.twitch_name)}</span>` : ''}
            ${counterBadges(p)}
            ${(p.steam_accounts || []).length > 1 ? `<span class="badge">${p.steam_accounts.length} Steam-Konten</span>` : ''}
          </div>
          <div class="row-sub">
            SteamID: ${esc(p.steam_id)} · Team: ${esc(p.team || '-')} · erkannt: ${esc(p.first_seen_at || p.last_seen_at)}
          </div>
        </div>
        <div class="row-actions">
          <select id="${esc(selectId)}" data-steam-select="${esc(p.steam_id)}" aria-label="Twitch-Nutzer für ${esc(p.steam_name || p.steam_id)}" onfocus="detectedRenderLocked = true" onblur="detectedRenderLocked = false; setTimeout(fetchState, 250)">
            <option value="">Twitch-User wählen</option>
            ${options}
          </select>
          <button data-link-id="${esc(p.steam_id)}" data-link-name="${esc(p.steam_name || '')}" data-select-id="${esc(selectId)}">Verknüpfen</button>
        </div>
      </div>
    `;
  }).join('');
}

function filterDetected() {
  if (!latestState) return;
  detectedRenderLocked = false;
  renderDetected();
  detectedSignature = buildDetectedSignature();
}
document.addEventListener('change', event => {
  if (event.target.matches('[data-steam-select]')) detectedSelections.set(event.target.dataset.steamSelect,event.target.value);
});

document.addEventListener('click', event => { const b = event.target.closest('[data-link-id]'); if(b) linkSteam(b.dataset.linkId,b.dataset.linkName,b.dataset.selectId); });

async function post(url, body = null) {
  try {
    await requestJson(url, {
      method: 'POST',
      headers: body ? {'Content-Type': 'application/json'} : {},
      body: body ? JSON.stringify(body) : null
    });
    await fetchState();
  } catch (error) {
    alert(error.message);
  }
}

async function markPlaying(id) {
  await post(`/api/playing/${id}`);
}

async function moveBackToWaiting(id) {
  await post(`/api/waiting/${id}`);
}

async function removeFromQueue(id) {
  await post(`/api/remove/${id}`);
}

async function finishPlaying() {
  await post('/api/finish-playing');
}

async function clearQueue() {
  if (!confirm('Queue wirklich leeren?')) return;
  await post('/api/clear-queue');
}

async function clearDetected() {
  if (!confirm('Erkannte CS2-Spieler wirklich leeren?')) return;
  detectedSignature = '';
  await post('/api/clear-detected');
}

async function showOverlay() {
  await fetch('/api/show-overlay');
  await fetchState();
}

async function hideOverlay() {
  await fetch('/api/hide-overlay');
  await fetchState();
}

async function linkSteam(steamId, steamName, selectId) {
  const select = document.getElementById(selectId);
  const twitchName = select.value;
  if (!twitchName) return alert('Bitte Twitch-User auswählen.');

  detectedRenderLocked = false;
  detectedSignature = '';

  detectedSelections.delete(steamId);
  await post('/api/link-steam', {
    twitch_name: twitchName,
    steam_id: steamId,
    steam_name: steamName
  });
}

setInterval(() => fetchState().catch(console.error), 1500);

const returnSelection = new Set();
function renderExtras() {
  const status = latestState.gsi_status || {};
  const ai = latestState.ai_status || {};
  document.getElementById('gsiStatus').textContent = `${(latestState.waiting || []).length} warten · ${(latestState.playing || []).length} in der Lobby · CS2: ${status.phase || 'keine Daten'} · ${status.note || 'Warte auf GSI'} · KI: ${ai.message || 'Lokales Modell noch nicht geladen'}`;
  document.getElementById('proposalList').innerHTML = (latestState.proposals || []).map((p,index) => `
    <div class="row"><div><div class="row-title">${esc(p.twitch_name)} ↔ ${esc(p.steam_name)} <span class="badge">Vorläufig</span></div><div class="row-sub">${esc(p.steam_id)} · ${esc(p.method)} · ${Math.round(p.confidence*100)} % Ähnlichkeit</div></div><div class="row-actions"><button data-proposal-index="${index}" data-action="confirm">Bestätigen</button><button class="danger" data-proposal-index="${index}" data-action="reject">Ablehnen</button></div></div>`).join('') || '<p class="muted">Keine offenen Vorschläge.</p>';
  document.querySelectorAll('[data-proposal-index]').forEach(button => button.onclick = () => post('/api/proposal', {steam_id: latestState.proposals[Number(button.dataset.proposalIndex)].steam_id, action: button.dataset.action}));
  const draw = latestState.draw;
  const available = draw ? (draw.challengers || []).filter(p => !(draw.returned_missing_ids || []).includes(p.id) && (latestState.playing || []).some(q => q.id === p.id)) : [];
  const ids = new Set(available.map(p=>p.id));
  [...returnSelection].forEach(id=>{if(!ids.has(id))returnSelection.delete(id);});
  document.getElementById('returnChoices').innerHTML = available.map(p=>`<label class="return-choice"><input type="checkbox" data-return-id="${Number(p.id)}" ${returnSelection.has(p.id)?'checked':''}> ${esc(p.label)}</label>`).join('') || '<p class="muted">Keine austauschbaren Nachrücker aus dem letzten Schichtwechsel.</p>';
  document.querySelectorAll('[data-return-id]').forEach(input => input.onchange=()=>{const id=Number(input.dataset.returnId);if(input.checked)returnSelection.add(id);else returnSelection.delete(id); document.getElementById('returnButton').disabled=!returnSelection.size;});
  document.getElementById('returnButton').disabled=!returnSelection.size;
}
async function returnPlayers() {
  try {
    const result = await requestJson('/api/draw/return',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({draw_id:latestState.draw.draw_id,missing_ids:[...returnSelection]})});
    returnSelection.clear();
    await fetchState();
    alert(`Zurück in der Lobby: ${result.returned.map(p=>p.label).join(', ')}`);
  } catch(error) { alert(error.message); }
}

fetchState().catch(console.error);
