/* Deterministic local search: case, accents, leetspeak and small spelling errors. */
(function (root) {
  'use strict';
  function normalize(value) {
    return String(value || '').slice(0, 128).toLowerCase().normalize('NFKD')
      .replace(/[\u0300-\u036f]/g, '').replace(/[013457@$]/g, c => ({'0':'o','1':'i','3':'e','4':'a','5':'s','7':'t','@':'a','$':'s'}[c]))
      .replace(/[^a-z0-9]/g, '').replace(/^x{2,}|x{2,}$/g, '');
  }
  function distance(a, b) {
    let row = Array.from({length: b.length + 1}, (_, i) => i);
    for (let i = 1; i <= a.length; i++) {
      const next = [i];
      for (let j = 1; j <= b.length; j++) {
        next[j] = Math.min(next[j - 1] + 1, row[j] + 1, row[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      }
      row = next;
    }
    return row[b.length];
  }
  function rank(query, player) {
    const raw = String(query || '').trim().toLowerCase().slice(0, 80);
    if (!raw) return 1;
    if (/^\d+$/.test(raw)) return String(player.steam_id || '').includes(raw) ? 3 : 0;
    const needle = normalize(raw);
    if (!needle) return 0;
    const fields = [player.steam_name, player.twitch_name, player.display_name];
    let best = 0;
    for (const value of fields) {
      if (!value) continue;
      const text = normalize(value);
      if (text === needle) best = Math.max(best, 4);
      else if (text.includes(needle)) best = Math.max(best, 3);
      else if (needle.length >= 3 && text.length >= 3) {
        const similarity = 1 - distance(needle, text) / Math.max(needle.length, text.length);
        if (similarity >= .7) best = Math.max(best, similarity);
      }
    }
    return best;
  }
  const api = {normalize, distance, rank};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.PQNameSearch = api;
})(typeof window !== 'undefined' ? window : globalThis);
