(() => {
  const stage = document.getElementById('drawStage');
  if (!stage) return;

  const params = new URLSearchParams(window.location.search);
  const soundEnabled = params.get('sound') !== '0';
  const demoMode = params.get('demo') === '1';
  const main = document.getElementById('drawMain');
  const final = document.getElementById('drawFinal');
  const candidateGrid = document.getElementById('drawCandidateGrid');
  const challengerGrid = document.getElementById('drawChallengerGrid');
  const finalGrid = document.getElementById('drawFinalGrid');
  const fxRoot = document.getElementById('drawFx');
  const crosshair = document.getElementById('drawCrosshair');
  const targetLock = document.getElementById('drawTargetLock');
  const muzzleFlash = document.getElementById('drawMuzzleFlash');

  let animationToken = 0;
  let runningKey = null;
  let lastPlayedKey = null;
  let pendingDraw = null;
  let audioContext = null;

  class AnimationCancelled extends Error {}

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, character => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
    }[character]));
  }

  function initials(name) {
    const words = String(name || '?').trim().split(/\s+/).filter(Boolean);
    return (words.length ? words.slice(0, 2).map(word => word[0]).join('') : '?').toUpperCase();
  }

  function drawKey(draw) {
    return `${draw.draw_id}:${draw.animation_revision}`;
  }

  function checkToken(token) {
    if (token !== animationToken) throw new AnimationCancelled();
  }

  function wait(ms, token) {
    return new Promise((resolve, reject) => {
      window.setTimeout(() => {
        if (token === animationToken) resolve();
        else reject(new AnimationCancelled());
      }, ms);
    });
  }

  function ensureAudio() {
    if (!soundEnabled) return null;
    try {
      if (!audioContext) {
        const Context = window.AudioContext || window.webkitAudioContext;
        if (!Context) return null;
        audioContext = new Context();
      }
      if (audioContext.state === 'suspended') audioContext.resume().catch(() => {});
      return audioContext;
    } catch (_) {
      return null;
    }
  }

  function tone(frequency, duration = .045, volume = .035, type = 'square', delay = 0) {
    const context = ensureAudio();
    if (!context) return;
    const start = context.currentTime + delay;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = type;
    oscillator.frequency.setValueAtTime(frequency, start);
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(volume, start + .008);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start(start);
    oscillator.stop(start + duration + .02);
  }

  function tickSound(progress) {
    tone(270 + progress * 180, .04, .025, 'square');
  }

  function heartbeatSound() {
    tone(74, .12, .11, 'sine');
    tone(62, .15, .09, 'sine', .18);
  }

  function promotionSound() {
    tone(260, .18, .045, 'sine');
    tone(390, .22, .045, 'sine', .12);
    tone(520, .28, .04, 'sine', .24);
  }

  function impactSound() {
    const context = ensureAudio();
    if (!context) return;

    tone(52, .48, .22, 'sine');
    const duration = .48;
    const buffer = context.createBuffer(1, Math.floor(context.sampleRate * duration), context.sampleRate);
    const data = buffer.getChannelData(0);
    for (let index = 0; index < data.length; index += 1) {
      data[index] = (Math.random() * 2 - 1) * Math.pow(1 - index / data.length, 2.7);
    }
    const source = context.createBufferSource();
    const filter = context.createBiquadFilter();
    const gain = context.createGain();
    source.buffer = buffer;
    filter.type = 'lowpass';
    filter.frequency.value = 620;
    gain.gain.value = .18;
    source.connect(filter).connect(gain).connect(context.destination);
    source.start();
  }

  function gunshotSound(shotIndex) {
    const context = ensureAudio();
    if (!context) return;

    const duration = .28;
    const buffer = context.createBuffer(1, Math.floor(context.sampleRate * duration), context.sampleRate);
    const data = buffer.getChannelData(0);
    for (let index = 0; index < data.length; index += 1) {
      const decay = Math.pow(1 - index / data.length, 5.2);
      data[index] = (Math.random() * 2 - 1) * decay;
    }

    const source = context.createBufferSource();
    const highpass = context.createBiquadFilter();
    const lowpass = context.createBiquadFilter();
    const compressor = context.createDynamicsCompressor();
    const gain = context.createGain();
    const delay = context.createDelay(.3);
    const echoGain = context.createGain();

    source.buffer = buffer;
    highpass.type = 'highpass';
    highpass.frequency.value = 120;
    lowpass.type = 'lowpass';
    lowpass.frequency.value = 3900 - shotIndex * 280;
    compressor.threshold.value = -18;
    compressor.ratio.value = 9;
    gain.gain.value = .23;
    delay.delayTime.value = .085;
    echoGain.gain.value = .18;

    source.connect(highpass).connect(lowpass).connect(compressor).connect(gain).connect(context.destination);
    gain.connect(delay).connect(echoGain).connect(context.destination);
    source.start();
    tone(70 - shotIndex * 4, .2, .13, 'sine');
    tone(185 + shotIndex * 15, .055, .075, 'sawtooth');
  }

  function playerCard(player, index) {
    const games = Number(player.in_a_row || 0);
    const gamesLabel = games ? `${games} SPIEL${games === 1 ? '' : 'E'} IN FOLGE` : 'BEREIT ZUR AUSLOSUNG';
    return `
      <article class="draw-player-card" data-player-id="${Number(player.id)}">
        <span class="draw-player-number">0${index + 1}</span>
        <div class="draw-player-avatar">${esc(initials(player.label))}</div>
        <div class="draw-player-name">${esc(player.label)}</div>
        <div class="draw-player-meta">${esc(gamesLabel)} · GESAMT ${Number(player.played_count || 0)}X</div>
        <span class="draw-player-status">IM LOSTOPF</span>
        <span class="draw-card-cracks"></span>
      </article>
    `;
  }

  function challengerCard(player) {
    return `
      <article class="draw-challenger-card" data-challenger-id="${Number(player.id)}">
        <div class="draw-challenger-avatar">${esc(initials(player.label))}</div>
        <div class="draw-challenger-copy">
          <strong>${esc(player.label)}</strong>
          <small>fordert einen Platz</small>
        </div>
        <span class="draw-challenger-status">WARTET</span>
      </article>
    `;
  }

  function renderDraw(draw) {
    document.getElementById('drawTitle').textContent = draw.title || 'SCHICHTWECHSEL';
    document.getElementById('drawSubtitle').textContent = draw.subtitle || '';
    document.getElementById('drawRoundLabel').textContent = 'WER BLEIBT IM TEAM?';
    document.getElementById('drawRoundCounter').textContent = 'AUSLOSUNG';

    const candidates = draw.candidates || [];
    candidateGrid.style.setProperty('--candidate-count', Math.max(1, candidates.length));
    candidateGrid.innerHTML = candidates.map(playerCard).join('');
    challengerGrid.innerHTML = (draw.challengers || []).map(challengerCard).join('');
    finalGrid.innerHTML = '';
    document.getElementById('drawBenchLine').innerHTML = '';
    main.classList.remove('is-leaving');
    final.classList.remove('is-visible');
    final.setAttribute('aria-hidden', 'true');
    fxRoot.innerHTML = '';
    stage.classList.remove('is-combat', 'is-shot');
    crosshair.classList.remove('is-active', 'is-locked');
    targetLock.classList.remove('is-visible');
    muzzleFlash.classList.remove('is-firing');
  }

  function playerCardElement(playerId) {
    return candidateGrid.querySelector(`[data-player-id="${Number(playerId)}"]`);
  }

  function challengerCardElement(playerId) {
    return challengerGrid.querySelector(`[data-challenger-id="${Number(playerId)}"]`);
  }

  function setCardStatus(card, text) {
    const status = card?.querySelector('.draw-player-status');
    if (status) status.textContent = text;
  }

  function moveCrosshair(card, locked = false) {
    if (!card) return;
    const bounds = card.getBoundingClientRect();
    const x = bounds.left + bounds.width * .5;
    const y = bounds.top + bounds.height * .48;
    crosshair.style.left = `${x}px`;
    crosshair.style.top = `${y}px`;
    targetLock.style.left = `${x}px`;
    targetLock.style.top = `${y}px`;
    crosshair.classList.add('is-active');
    crosshair.classList.toggle('is-locked', locked);
  }

  function lockTarget(card) {
    moveCrosshair(card, true);
    card?.classList.add('is-target-locked');
    targetLock.textContent = 'ZIEL ERFASST';
    targetLock.classList.add('is-visible');
    setCardStatus(card, 'ZIEL ERFASST');
    tone(720, .1, .05, 'square');
    tone(980, .16, .045, 'square', .13);
  }

  function clearTargetLock(card = null, keepCrosshair = true) {
    card?.classList.remove('is-target-locked');
    targetLock.classList.remove('is-visible');
    crosshair.classList.remove('is-locked');
    if (!keepCrosshair) crosshair.classList.remove('is-active');
  }

  async function sweep(activeIds, targetId, roundIndex, token) {
    const cards = activeIds.map(playerCardElement).filter(Boolean);
    const target = playerCardElement(targetId);
    if (!cards.length || !target) return;

    const totalSteps = 25 + roundIndex * 3;
    let cursor = roundIndex % cards.length;
    stage.classList.add('is-combat');
    crosshair.classList.add('is-active');
    heartbeatSound();

    for (let step = 0; step < totalSteps; step += 1) {
      checkToken(token);
      cards.forEach(card => card.classList.remove('is-scanning'));
      let activeCard;
      if (step === totalSteps - 1) {
        activeCard = target;
      } else {
        activeCard = cards[cursor % cards.length];
        cursor += 1;
      }
      activeCard.classList.add('is-scanning');
      moveCrosshair(activeCard);
      tickSound(step / totalSteps);

      const progress = step / (totalSteps - 1);
      let delay = 48 + Math.pow(progress, 3.25) * 285;
      if (step === totalSteps - 5) delay += 210;
      if (step === totalSteps - 2) heartbeatSound();
      await wait(delay, token);
    }

    target.classList.add('is-scanning');
    lockTarget(target);
    await wait(720, token);
  }

  function triggerShotFlash(originX, originY) {
    muzzleFlash.style.left = `${originX}px`;
    muzzleFlash.style.top = `${originY}px`;
    muzzleFlash.classList.remove('is-firing');
    stage.classList.remove('is-shot');
    void muzzleFlash.offsetWidth;
    muzzleFlash.classList.add('is-firing');
    stage.classList.add('is-shot');
    window.setTimeout(() => {
      muzzleFlash.classList.remove('is-firing');
      stage.classList.remove('is-shot');
    }, 150);
  }

  function spawnTracer(originX, originY, targetX, targetY) {
    const tracer = document.createElement('span');
    const deltaX = targetX - originX;
    const deltaY = targetY - originY;
    tracer.className = 'bullet-tracer';
    tracer.style.left = `${originX}px`;
    tracer.style.top = `${originY}px`;
    tracer.style.setProperty('--distance', `${Math.hypot(deltaX, deltaY)}px`);
    tracer.style.setProperty('--angle', `${Math.atan2(deltaY, deltaX) * 180 / Math.PI}deg`);
    fxRoot.appendChild(tracer);
    window.setTimeout(() => tracer.remove(), 320);
  }

  function addBulletHole(card, xPercent, yPercent) {
    const hole = document.createElement('span');
    hole.className = 'bullet-hole';
    hole.style.left = `${xPercent * 100}%`;
    hole.style.top = `${yPercent * 100}%`;
    card.appendChild(hole);
  }

  function spawnSparks(targetX, targetY) {
    for (let index = 0; index < 14; index += 1) {
      const spark = document.createElement('span');
      spark.className = 'impact-spark';
      spark.style.left = `${targetX + (Math.random() - .5) * 12}px`;
      spark.style.top = `${targetY + (Math.random() - .5) * 12}px`;
      spark.style.setProperty('--angle', `${Math.random() * 360}deg`);
      spark.style.setProperty('--length', `${12 + Math.random() * 25}px`);
      spark.style.setProperty('--travel', `${35 + Math.random() * 70}px`);
      fxRoot.appendChild(spark);
      window.setTimeout(() => spark.remove(), 520);
    }
  }

  async function fireBurst(card, token) {
    if (!card) return;
    const impactPoints = [
      [.43, .44],
      [.58, .56],
      [.51, .37]
    ];
    targetLock.textContent = 'FEUERSTOSS';
    setCardStatus(card, 'UNTER BESCHUSS');

    for (let shotIndex = 0; shotIndex < impactPoints.length; shotIndex += 1) {
      checkToken(token);
      const bounds = card.getBoundingClientRect();
      const [xPercent, yPercent] = impactPoints[shotIndex];
      const targetX = bounds.left + bounds.width * xPercent;
      const targetY = bounds.top + bounds.height * yPercent;
      const originX = window.innerWidth * .755;
      const originY = window.innerHeight * .82;
      triggerShotFlash(originX, originY);
      spawnTracer(originX, originY, targetX, targetY);
      addBulletHole(card, xPercent, yPercent);
      spawnSparks(targetX, targetY);
      gunshotSound(shotIndex);
      await wait(shotIndex === 2 ? 330 : 235, token);
    }
  }

  function spawnImpact(card) {
    if (!card) return;
    const bounds = card.getBoundingClientRect();
    const x = bounds.left + bounds.width * .52;
    const y = bounds.top + bounds.height * .48;

    for (let index = 0; index < 24; index += 1) {
      const shard = document.createElement('span');
      const angle = (Math.PI * 2 * index / 24) + (Math.random() - .5) * .5;
      const distance = 80 + Math.random() * 270;
      shard.className = 'stone-shard';
      shard.style.setProperty('--x', `${x + (Math.random() - .5) * 48}px`);
      shard.style.setProperty('--y', `${y + (Math.random() - .5) * 45}px`);
      shard.style.setProperty('--size', `${7 + Math.random() * 18}px`);
      shard.style.setProperty('--dx', `${Math.cos(angle) * distance}px`);
      shard.style.setProperty('--dy', `${Math.sin(angle) * distance + 90}px`);
      shard.style.setProperty('--rot', `${(Math.random() - .5) * 760}deg`);
      fxRoot.appendChild(shard);
    }

    for (let index = 0; index < 30; index += 1) {
      const dust = document.createElement('span');
      const angle = Math.random() * Math.PI * 2;
      const distance = 55 + Math.random() * 210;
      dust.className = 'dust-particle';
      dust.style.setProperty('--x', `${x + (Math.random() - .5) * 80}px`);
      dust.style.setProperty('--y', `${y + (Math.random() - .5) * 60}px`);
      dust.style.setProperty('--size', `${5 + Math.random() * 17}px`);
      dust.style.setProperty('--dx', `${Math.cos(angle) * distance}px`);
      dust.style.setProperty('--dy', `${Math.sin(angle) * distance}px`);
      fxRoot.appendChild(dust);
    }
    window.setTimeout(() => {
      fxRoot.querySelectorAll('.stone-shard, .dust-particle').forEach(node => node.remove());
    }, 1500);
  }

  async function resolveRound(round, activeIds, totalRounds, token) {
    document.getElementById('drawRoundLabel').textContent = `PLATZ ${round.number} WIRD VERLOST`;
    document.getElementById('drawRoundCounter').textContent = `RUNDE ${round.number} / ${totalRounds}`;

    await sweep(activeIds, Number(round.outgoing.id), round.number - 1, token);
    const outgoingCard = playerCardElement(round.outgoing.id);
    const incomingCard = challengerCardElement(round.incoming.id);
    await fireBurst(outgoingCard, token);
    await wait(120, token);
    outgoingCard?.classList.remove('is-scanning');
    clearTargetLock(outgoingCard);
    outgoingCard?.classList.add('is-benched');
    setCardStatus(outgoingCard, 'AUSGESCHALTET · BANK');
    spawnImpact(outgoingCard);
    impactSound();
    await wait(580, token);

    if (incomingCard) {
      incomingCard.classList.add('is-promoted');
      const status = incomingCard.querySelector('.draw-challenger-status');
      if (status) status.textContent = 'RÜCKT NACH';
    }
    promotionSound();
    await wait(1050, token);

    return activeIds.filter(id => Number(id) !== Number(round.outgoing.id));
  }

  function renderFinal(draw) {
    const lineup = draw.lineup || [];
    const columnCount = lineup.length <= 5 ? Math.max(1, lineup.length) : Math.ceil(lineup.length / 2);
    finalGrid.style.setProperty('--lineup-count', columnCount);
    finalGrid.style.maxWidth = `${Math.min(columnCount, 5) * 220 + Math.max(0, columnCount - 1) * 11}px`;
    const newcomerIds = new Set((draw.challengers || []).map(player => Number(player.id)));
    finalGrid.innerHTML = lineup.map((player, index) => {
      const isNew = newcomerIds.has(Number(player.id));
      return `
        <article class="draw-final-card ${isNew ? 'new' : ''}" style="--delay:${index * .1}s">
          <div class="draw-player-avatar">${esc(initials(player.label))}</div>
          <strong>${esc(player.label)}</strong>
          <small>${isNew ? 'NEU DABEI' : 'BLEIBT IM TEAM'}</small>
        </article>
      `;
    }).join('');

    const outgoingNames = (draw.outgoing || []).map(player => esc(player.label)).join(' & ');
    document.getElementById('drawBenchLine').innerHTML = `<span>AUF DER BANK:</span> <strong>${outgoingNames || '–'}</strong>`;
  }

  async function showFinal(draw, token) {
    clearTargetLock(null, false);
    stage.classList.remove('is-combat');
    candidateGrid.querySelectorAll('.draw-player-card:not(.is-benched)').forEach(card => {
      card.classList.add('is-safe');
      setCardStatus(card, 'BLEIBT IM TEAM');
    });
    document.getElementById('drawRoundLabel').textContent = 'AUSLOSUNG BEENDET';
    document.getElementById('drawRoundCounter').textContent = 'ENTSCHEIDUNG STEHT';
    await wait(1150, token);

    renderFinal(draw);
    main.classList.add('is-leaving');
    await wait(370, token);
    final.classList.add('is-visible');
    final.setAttribute('aria-hidden', 'false');
    promotionSound();
    await wait(4700, token);
  }

  async function hideStage(token) {
    if (token !== animationToken) return;
    stage.classList.add('is-closing');
    await new Promise(resolve => window.setTimeout(resolve, 520));
    if (token !== animationToken) return;
    stage.classList.remove('is-visible', 'is-closing');
    stage.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('draw-running');
  }

  async function markAnimationHidden(draw) {
    if (demoMode) return;
    try {
      await fetch('/api/draw/hide', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          draw_id: draw.draw_id,
          animation_revision: draw.animation_revision
        }),
        keepalive: true
      });
    } catch (_) {
      // The next poll reconciles state; the overlay should still disappear locally.
    }
  }

  async function playDraw(draw) {
    const key = drawKey(draw);
    const token = ++animationToken;
    runningKey = key;
    lastPlayedKey = key;
    pendingDraw = null;
    renderDraw(draw);
    document.body.classList.add('draw-running');
    stage.classList.remove('is-closing');
    stage.classList.add('is-visible');
    stage.setAttribute('aria-hidden', 'false');

    let completed = false;
    try {
      await wait(1550, token);
      let activeIds = (draw.candidates || []).map(player => Number(player.id));
      const rounds = draw.rounds || [];
      for (const round of rounds) {
        activeIds = await resolveRound(round, activeIds, rounds.length, token);
      }
      await showFinal(draw, token);
      completed = true;
      await hideStage(token);
    } catch (error) {
      if (!(error instanceof AnimationCancelled)) throw error;
    } finally {
      if (token === animationToken) {
        runningKey = null;
        if (completed) await markAnimationHidden(draw);
        const next = pendingDraw;
        pendingDraw = null;
        if (next && next.active && drawKey(next) !== lastPlayedKey) {
          window.setTimeout(() => playDraw(next), 300);
        }
      }
    }
  }

  function cancelAnimation() {
    animationToken += 1;
    runningKey = null;
    pendingDraw = null;
    stage.classList.remove('is-visible', 'is-closing');
    stage.classList.remove('is-combat', 'is-shot');
    clearTargetLock(null, false);
    stage.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('draw-running');
  }

  async function pollDraw() {
    try {
      const response = await fetch('/api/draw/state', {cache: 'no-store'});
      if (!response.ok) return;
      const payload = await response.json();
      const draw = payload.draw;
      if (!draw) return;
      const key = drawKey(draw);

      if (!draw.active) {
        if (runningKey === key) cancelAnimation();
        if (pendingDraw && drawKey(pendingDraw) === key) pendingDraw = null;
        return;
      }
      if (key === lastPlayedKey) return;
      if (runningKey) {
        pendingDraw = draw;
        return;
      }
      playDraw(draw).catch(() => cancelAnimation());
    } catch (_) {
      // A brief server restart should not break the Browser Source.
    }
  }

  function demoDraw() {
    const players = ['FelsFaust', 'KieselKing', 'GranitGerd', 'MarmorManni'].map((label, index) => ({
      id: index + 1,
      label,
      in_a_row: 2,
      played_count: 7 + index * 3
    }));
    const challengers = ['BusfahrerBen', 'QuarzQueen'].map((label, index) => ({
      id: index + 5,
      label,
      in_a_row: 1,
      played_count: 4 + index
    }));
    return {
      draw_id: 'demo',
      animation_revision: 1,
      active: true,
      title: 'SCHICHTWECHSEL',
      subtitle: '2 PLÄTZE · 4 KANDIDATEN · KEINE GNADE',
      candidates: players,
      challengers,
      rounds: [
        {number: 1, outgoing: players[1], incoming: challengers[0]},
        {number: 2, outgoing: players[3], incoming: challengers[1]}
      ],
      outgoing: [players[1], players[3]],
      staying: [players[0], players[2]],
      lineup: [players[0], players[2], ...challengers]
    };
  }

  if (demoMode) {
    window.setTimeout(() => playDraw(demoDraw()), 350);
  } else {
    pollDraw();
    window.setInterval(pollDraw, 450);
  }
})();
