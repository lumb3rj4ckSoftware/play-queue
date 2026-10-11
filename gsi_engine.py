"""Persistent match roster accumulation, participation and provisional linking."""
import json
import re
import unicodedata
import uuid
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor
import alias_ai
import steam_links

_pool = ThreadPoolExecutor(max_workers=1)
_jobs = {}
TEAM_SIZES = {'competitive': 5, 'premier': 5, 'scrimcomp5v5': 5, 'scrimcomp2v2': 2}
SUPPORTED_MODES = set(TEAM_SIZES) | {'casual'}


def init(con):
    if 'in_a_row' not in [r['name'] for r in con.execute('PRAGMA table_info(users)')]:
        con.execute('ALTER TABLE users ADD COLUMN in_a_row INTEGER NOT NULL DEFAULT 0')
    con.executescript('''
    CREATE TABLE IF NOT EXISTS matches (
      id TEXT PRIMARY KEY, map_name TEXT, finished INTEGER DEFAULT 0,
      complete INTEGER DEFAULT 0, created_at TEXT);
    CREATE TABLE IF NOT EXISTS match_players (
      match_id TEXT, twitch_name TEXT, steam_id TEXT, PRIMARY KEY(match_id,twitch_name));
    CREATE TABLE IF NOT EXISTS steam_proposals (
      steam_id TEXT PRIMARY KEY, twitch_name TEXT, steam_name TEXT,
      confidence REAL, method TEXT, status TEXT DEFAULT 'pending', created_at TEXT);
    CREATE TABLE IF NOT EXISTS rejected_links (
      steam_id TEXT, twitch_name TEXT, PRIMARY KEY(steam_id,twitch_name));
    CREATE TABLE IF NOT EXISTS match_observations (
      match_id TEXT, steam_id TEXT, round_no INTEGER, team TEXT, steam_name TEXT,
      last_seen_at TEXT, PRIMARY KEY(match_id,steam_id,round_no));
    CREATE TABLE IF NOT EXISTS match_user_baselines (
      match_id TEXT, twitch_name TEXT, in_a_row INTEGER, PRIMARY KEY(match_id,twitch_name));
    CREATE TABLE IF NOT EXISTS match_team_rounds (
      match_id TEXT, round_no INTEGER, team TEXT, PRIMARY KEY(match_id,round_no));
    ''')
    if 'steam_id' not in [r['name'] for r in con.execute('PRAGMA table_info(match_players)')]:
        con.execute('ALTER TABLE match_players ADD COLUMN steam_id TEXT')


def canonical(name):
    name = unicodedata.normalize('NFKD', str(name or '')[:128].lower()).translate(str.maketrans('013457@$', 'oieastas'))
    name = re.sub('[^a-z0-9]', '', name)
    return re.sub(r'^x{2,}|x{2,}$', '', name)


def similarity(a, b):
    a, b = canonical(a), canonical(b)
    if min(len(a), len(b)) < 3:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def model_score(a, b):
    return alias_ai.score(a, b)


def teammates_for_match(con, match_id):
    # Sides are resolved for the round in which each observation was received.
    # Comparing every old observation to today's CT/T side would mix opponents in at halftime.
    rows = con.execute('''SELECT o.* FROM match_observations o
        JOIN match_team_rounds t ON t.match_id=o.match_id AND t.round_no=o.round_no AND t.team=o.team
        WHERE o.match_id=? ORDER BY o.round_no ASC, o.last_seen_at ASC''', (match_id,)).fetchall()
    by_id = {}
    for row in rows:
        by_id[row['steam_id']] = {'steam_id': row['steam_id'], 'steam_name': row['steam_name'], 'team': row['team']}
    return list(by_id.values())


def propose(con, teammates, stamp, match_id, schedule=True):
    candidates = con.execute("SELECT DISTINCT u.* FROM users u JOIN queue q USING(twitch_name) WHERE q.status='playing'").fetchall()
    scores = {}
    pending = set()
    for p in teammates:
        if steam_links.owner(con,p['steam_id']):
            continue
        for u in candidates:
            sid, name = p['steam_id'], u['twitch_name']
            if con.execute('SELECT 1 FROM rejected_links WHERE steam_id=? AND twitch_name=?', (sid, name)).fetchone():
                continue
            lexical = max(similarity(name, p['steam_name']), similarity(u['display_name'] or '', p['steam_name']))
            confidence, method = lexical, 'Namensvergleich'
            key = (match_id, sid, name, p['steam_name'])
            if not schedule and key not in _jobs:
                continue
            # A minimum lexical resemblance prevents model speculation about unrelated identities.
            if alias_ai.enabled() and lexical >= .5:
                if key not in _jobs and schedule:
                    running = sum(not j.done() for j in _jobs.values())
                    if running < 16:
                        _jobs[key] = _pool.submit(model_score, name, p['steam_name'])
                job = _jobs.get(key)
                if job is None or not job.done():
                    pending.add((sid, name))
                else:
                    try:
                        result = job.result()
                    except Exception:
                        result = None
                    if result is not None:
                        confidence = result if result >= .9 else 0.0
                        method = 'Eingebautes KI-Modell'
                    # None = dependencies/download/output unavailable: keep lexical fallback.
            scores[(sid, name)] = (confidence, method, p)
    for (sid, name), (score, method, p) in sorted(scores.items(), key=lambda item: -item[1][0]):
        if any(s == sid or n == name for s, n in pending):
            continue
        alternatives = [v[0] for (s, n), v in scores.items() if (s == sid or n == name) and (s, n) != (sid, name)]
        if score < .88 or (alternatives and score - max(alternatives) < .12):
            continue
        if steam_links.owner(con,sid):
            continue
        changed = steam_links.add(con,name,sid,p['steam_name'],stamp,status='pending')
        if changed:
            con.execute("INSERT OR REPLACE INTO steam_proposals VALUES(?,?,?,?,?,'pending',?)", (sid, name, p['steam_name'], score, method, stamp))
            con.execute('UPDATE detected_players SET twitch_name=? WHERE steam_id=?', (name, sid))


def reconcile(con, match_id, teammates, stamp):
    match = con.execute('SELECT finished FROM matches WHERE id=?', (match_id,)).fetchone()
    finished = bool(match and match['finished'])
    for p in teammates:
        user = steam_links.owner(con,p['steam_id'])
        steam_links.seen(con,p['steam_id'],p['steam_name'],stamp)
        if not user:
            continue
        name = user['twitch_name']
        first = con.execute('INSERT OR IGNORE INTO match_players(match_id,twitch_name,steam_id) VALUES(?,?,?)', (match_id, name, p['steam_id'])).rowcount
        if first:
            con.execute('UPDATE users SET in_a_row=in_a_row+1,played_count=played_count+1,last_played_at=? WHERE twitch_name=?', (stamp, name))
            if finished:
                baseline = con.execute('SELECT in_a_row FROM match_user_baselines WHERE match_id=? AND twitch_name=?', (match_id, name)).fetchone()
                if baseline:
                    con.execute('UPDATE users SET in_a_row=? WHERE twitch_name=?', (baseline['in_a_row'] + 1, name))
            else:
                con.execute("UPDATE queue SET status='playing',playing_since=? WHERE twitch_name=? AND status='waiting'", (stamp, name))


def finish(con, match_id):
    match = con.execute('SELECT * FROM matches WHERE id=?', (match_id,)).fetchone()
    if not match or match['finished']:
        return
    if match['complete']:
        con.execute('UPDATE users SET in_a_row=0 WHERE twitch_name NOT IN (SELECT twitch_name FROM match_players WHERE match_id=?)', (match_id,))
    con.execute('UPDATE matches SET finished=1 WHERE id=?', (match_id,))


def load_tracking(con):
    row = con.execute("SELECT value FROM app_state WHERE key='gsi_tracking'").fetchone()
    return json.loads(row['value']) if row else {}


def refresh(con, stamp):
    """Consume completed AI jobs and new manual links for the live roster during UI polling."""
    state = load_tracking(con)
    if state.get('phase') not in ('live', 'gameover') or not state.get('match_id'):
        return
    teammates = teammates_for_match(con, state['match_id'])
    propose(con, teammates, stamp, state['match_id'], schedule=not state.get('closed'))
    reconcile(con, state['match_id'], teammates, stamp)


def valid_players(players):
    return [p for p in players if p['team'] in ('CT', 'T') and p['steam_id'].isdigit() and int(p['steam_id']) > 0]


def process(con, payload, players, stamp):
    state = load_tracking(con)
    provider = payload.get('provider') or {}
    timestamp = provider.get('timestamp')
    if isinstance(timestamp, (int, float)) and timestamp < state.get('timestamp', 0):
        return False
    m = payload.get('map') or {}
    phase = m.get('phase', '')
    mode = m.get('mode') or state.get('mode', '')
    if state.get('match_id') and 'mode' not in state:
        state['mode'] = mode  # Upgrade from previous tracking schema without starting a second match.
    map_name = m.get('name') or state.get('map', '')
    round_no = int(m['round']) if 'round' in m else state.get('round', 0)
    live = phase == 'live' and mode in SUPPORTED_MODES
    provider_id = str(provider.get('steamid') or state.get('provider_id', ''))
    changed_provider = bool(state.get('provider_id') and provider_id != state['provider_id'])
    round_restart = ('round' in m and 'team_ct' in m and 'team_t' in m and round_no == 0
                     and state.get('round', 0) > 0
                     and sum(int((m.get(t) or {}).get('score', 0)) for t in ('team_ct', 'team_t')) == 0)
    new_match = live and (not state.get('match_id') or state.get('closed') or changed_provider
                         or state.get('map') != map_name or state.get('mode') != mode
                         or state.get('phase') in ('warmup', 'gameover') or round_restart)
    if new_match:
        if state.get('match_id'):
            finish(con, state['match_id'])
        state.update(match_id=uuid.uuid4().hex, closed=False, map=map_name, mode=mode, provider_id=provider_id)
        con.execute('INSERT INTO matches(id,map_name,created_at) VALUES(?,?,?)', (state['match_id'], map_name, stamp))
        con.execute('INSERT INTO match_user_baselines SELECT ?,twitch_name,in_a_row FROM users', (state['match_id'],))
        # Keep only a bounded cache of finished results; queued jobs don't touch the DB.
        for key in list(_jobs):
            if key[0] != state['match_id'] and _jobs[key].done():
                del _jobs[key]
    match_id = state.get('match_id')
    own_team = ''
    expected = TEAM_SIZES.get(mode)
    eligible = bool(match_id and not state.get('closed') and map_name == state.get('map')
                    and mode == state.get('mode') and mode in SUPPORTED_MODES
                    and phase in ('live', 'gameover'))
    if eligible:
        observations = valid_players(players)
        prior_roster = teammates_for_match(con, match_id)
        known_teammates = {p['steam_id'] for p in prior_roster}
        own = next((p for p in observations if p['steam_id'] == provider_id), None)
        # If provider is absent while dead, an already established teammate is an anchor.
        anchors = {p['team'] for p in observations if p['steam_id'] in known_teammates}
        if own:
            own_team = own['team']
        elif len(anchors) == 1:
            own_team = next(iter(anchors))
        else:
            known_round = con.execute('SELECT team FROM match_team_rounds WHERE match_id=? AND round_no=?', (match_id, round_no)).fetchone()
            own_team = known_round['team'] if known_round else ''
        if own_team:
            con.execute('INSERT OR REPLACE INTO match_team_rounds VALUES(?,?,?)', (match_id, round_no, own_team))
        for p in observations:
            con.execute('''INSERT INTO match_observations VALUES(?,?,?,?,?,?)
                ON CONFLICT(match_id,steam_id,round_no) DO UPDATE SET
                team=excluded.team,steam_name=excluded.steam_name,last_seen_at=excluded.last_seen_at''',
                        (match_id, p['steam_id'], round_no, p['team'], p['steam_name'], stamp))
        teammates = teammates_for_match(con, match_id)
        # Own team includes the streamer. No opponent roster or simultaneous snapshot is needed.
        # More distinct identities than slots (e.g. substitutions) are conservatively incomplete.
        complete = bool(expected and len(teammates) == expected)
        con.execute('UPDATE matches SET complete=? WHERE id=?', (int(complete), match_id))
        propose(con, teammates, stamp, match_id)
        reconcile(con, match_id, teammates, stamp)
    if phase in ('gameover', 'warmup') and match_id and not state.get('closed'):
        finish(con, match_id)
        state['closed'] = True
    state.update(phase=phase, round=round_no, mode=mode, provider_id=provider_id)
    if isinstance(timestamp, (int, float)):
        state['timestamp'] = timestamp
    con.execute("INSERT OR REPLACE INTO app_state VALUES('gsi_tracking',?)", (json.dumps(state),))
    roster = teammates_for_match(con, match_id) if match_id else []
    complete = bool(expected and len(roster) == expected)
    note = (f'Eigenes Team vollständig gesammelt: {len(roster)}/{expected}' if complete
            else f'Eigenes Team gesammelt: {len(roster)}/{expected or "?"} – Pausen noch nicht sicher nachweisbar')
    con.execute("INSERT OR REPLACE INTO app_state VALUES('gsi_status',?)", (json.dumps({
        'last_seen': stamp, 'own_team': own_team, 'roster_count': len(players), 'phase': phase,
        'match_id': match_id, 'team_collected': len(roster), 'team_expected': expected,
        'team_complete': complete, 'teammates': roster, 'note': note}),))
    return True
