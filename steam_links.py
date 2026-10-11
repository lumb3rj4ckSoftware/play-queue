"""One Twitch user, multiple Steam accounts; legacy primary fields stay compatible."""

def init(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS steam_accounts (
        steam_id TEXT PRIMARY KEY,
        twitch_name TEXT NOT NULL,
        steam_name TEXT,
        status TEXT NOT NULL DEFAULT 'confirmed',
        created_at TEXT,
        updated_at TEXT
    );
    CREATE INDEX IF NOT EXISTS steam_accounts_user ON steam_accounts(twitch_name);
    CREATE TRIGGER IF NOT EXISTS legacy_steam_insert AFTER INSERT ON users
    WHEN NEW.steam_id IS NOT NULL AND NEW.steam_id <> ''
    BEGIN
        INSERT OR IGNORE INTO steam_accounts(steam_id,twitch_name,steam_name)
        VALUES(NEW.steam_id,NEW.twitch_name,NEW.steam_name);
    END;
    CREATE TRIGGER IF NOT EXISTS legacy_steam_update AFTER UPDATE OF steam_id ON users
    WHEN NEW.steam_id IS NOT NULL AND NEW.steam_id <> ''
    BEGIN
        INSERT OR IGNORE INTO steam_accounts(steam_id,twitch_name,steam_name)
        VALUES(NEW.steam_id,NEW.twitch_name,NEW.steam_name);
    END;
    ''')
    con.execute('''INSERT OR IGNORE INTO steam_accounts(steam_id,twitch_name,steam_name,status)
        SELECT u.steam_id,u.twitch_name,u.steam_name,
               CASE WHEN p.status='pending' THEN 'pending' ELSE 'confirmed' END
        FROM users u LEFT JOIN steam_proposals p ON p.steam_id=u.steam_id AND p.twitch_name=u.twitch_name
        WHERE u.steam_id IS NOT NULL AND u.steam_id<>'' ''')


def owner(con, steam_id):
    return con.execute('SELECT twitch_name FROM steam_accounts WHERE steam_id=?', (steam_id,)).fetchone()


def accounts(con, twitch_name):
    return [dict(row) for row in con.execute(
        'SELECT steam_id,steam_name,status FROM steam_accounts WHERE twitch_name=? ORDER BY status,steam_id',
        (twitch_name,))]


def attach(con, items):
    by_user = {}
    for row in con.execute('SELECT twitch_name,steam_id,steam_name,status FROM steam_accounts ORDER BY status,steam_id'):
        by_user.setdefault(row['twitch_name'], []).append({k: row[k] for k in ('steam_id', 'steam_name', 'status')})
    for item in items:
        item['steam_accounts'] = by_user.get(item.get('twitch_name'), [])
    return items


def sync_primary(con, twitch_name):
    row = con.execute('''SELECT steam_id,steam_name FROM steam_accounts WHERE twitch_name=?
        ORDER BY CASE status WHEN 'confirmed' THEN 0 ELSE 1 END,updated_at DESC,steam_id LIMIT 1''', (twitch_name,)).fetchone()
    con.execute('UPDATE users SET steam_id=?,steam_name=? WHERE twitch_name=?',
                (row['steam_id'] if row else None, row['steam_name'] if row else None, twitch_name))


def add(con, twitch_name, steam_id, steam_name, stamp, status='confirmed'):
    existing = owner(con, steam_id)
    if existing and existing['twitch_name'] != twitch_name:
        return False
    con.execute('''INSERT INTO steam_accounts VALUES(?,?,?,?,?,?)
        ON CONFLICT(steam_id) DO UPDATE SET
        steam_name=excluded.steam_name,status=excluded.status,updated_at=excluded.updated_at''',
                (steam_id, twitch_name, steam_name, status, stamp, stamp))
    sync_primary(con, twitch_name)
    return True


def seen(con, steam_id, steam_name, stamp):
    linked = owner(con, steam_id)
    if not linked:
        return
    con.execute('UPDATE steam_accounts SET steam_name=?,updated_at=? WHERE steam_id=?', (steam_name, stamp, steam_id))
    # Show the account actually observed in the match as the legacy primary label.
    con.execute('UPDATE users SET steam_id=?,steam_name=? WHERE twitch_name=?', (steam_id, steam_name, linked['twitch_name']))


def reject(con, steam_id, twitch_name):
    con.execute("DELETE FROM steam_accounts WHERE steam_id=? AND twitch_name=? AND status='pending'", (steam_id, twitch_name))
    sync_primary(con, twitch_name)
