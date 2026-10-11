from __future__ import annotations

import sqlite3
import json
import secrets
import uuid
import gsi_engine
import alias_ai
import steam_links
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, redirect, render_template, request

APP_PORT = 5050
DB_PATH = Path("queue.db")

app = Flask(__name__)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today_str() -> str:
    return datetime.now().date().isoformat()


def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def column_exists(con: sqlite3.Connection, table: str, column: str) -> bool:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def add_column_if_missing(con: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if not column_exists(con, table, column):
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db() -> None:
    with db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                twitch_name TEXT PRIMARY KEY,
                display_name TEXT,
                steam_id TEXT UNIQUE,
                steam_name TEXT,
                played_count INTEGER NOT NULL DEFAULT 0,
                last_played_at TEXT
            );

            CREATE TABLE IF NOT EXISTS queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                twitch_name TEXT NOT NULL,
                display_name TEXT,
                status TEXT NOT NULL DEFAULT 'waiting',
                joined_at TEXT NOT NULL,
                playing_since TEXT
            );

            CREATE TABLE IF NOT EXISTS detected_players (
                steam_id TEXT PRIMARY KEY,
                steam_name TEXT,
                team TEXT,
                twitch_name TEXT,
                last_seen_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS rotation_draws (
                draw_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                animation_revision INTEGER NOT NULL DEFAULT 1,
                active INTEGER NOT NULL DEFAULT 1,
                payload_json TEXT NOT NULL
            );
            """
        )

        gsi_engine.init(con)
        steam_links.init(con)

        # Migrationen für bestehende queue.db-Dateien.
        add_column_if_missing(con, "users", "played_today", "INTEGER NOT NULL DEFAULT 0")
        add_column_if_missing(con, "users", "played_today_date", "TEXT")
        add_column_if_missing(con, "detected_players", "first_seen_at", "TEXT")
        add_column_if_missing(con, "detected_players", "detect_count", "INTEGER NOT NULL DEFAULT 1")

        con.execute(
            "UPDATE detected_players SET first_seen_at = COALESCE(first_seen_at, last_seen_at)"
        )
        con.execute(
            "INSERT OR IGNORE INTO app_state(key, value) VALUES('overlay_visible', '1')"
        )


def player_snapshot(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    """Create the stable player data shown during a draw animation."""
    data = dict(row)
    played_today = int(data.get("played_today") or 0)
    if data.get("played_today_date") != today_str():
        played_today = 0
    return {
        "id": int(data["id"]),
        "twitch_name": data.get("twitch_name"),
        "display_name": data.get("display_name"),
        "label": data.get("display_name") or data.get("twitch_name") or "Unbekannt",
        "steam_id": data.get("steam_id"),
        "steam_name": data.get("steam_name"),
        "played_count": int(data.get("played_count") or 0),
        "played_today": played_today,
        "in_a_row": int(data.get("in_a_row") or 0),
    }


def load_draw(con: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    owns_connection = con is None
    connection = con or db()
    try:
        row = connection.execute(
            """
            SELECT * FROM rotation_draws
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None

        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, json.JSONDecodeError):
            payload = {}

        payload.update(
            {
                "draw_id": row["draw_id"],
                "created_at": row["created_at"],
                "animation_revision": int(row["animation_revision"]),
                "active": bool(row["active"]),
            }
        )
        return payload
    finally:
        if owns_connection:
            connection.close()


def requested_ids(data: dict[str, Any], key: str) -> list[int]:
    raw_ids = data.get(key)
    if not isinstance(raw_ids, list):
        raise ValueError(f"{key} muss eine Liste sein.")

    result: list[int] = []
    for raw_id in raw_ids:
        if isinstance(raw_id, bool):
            raise ValueError(f"Ungültige ID in {key}.")
        try:
            queue_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Ungültige ID in {key}.") from exc
        if queue_id <= 0 or queue_id in result:
            raise ValueError(f"Ungültige oder doppelte ID in {key}.")
        result.append(queue_id)
    return result


def queue_rows_by_ids(
    con: sqlite3.Connection,
    queue_ids: list[int],
    required_status: str,
) -> list[sqlite3.Row]:
    if not queue_ids:
        return []
    placeholders = ",".join("?" for _ in queue_ids)
    rows = con.execute(
        f"""
        SELECT q.*, u.steam_id, u.steam_name,
               u.in_a_row, u.played_count, u.played_today, u.played_today_date
        FROM queue q
        LEFT JOIN users u ON u.twitch_name = q.twitch_name
        WHERE q.id IN ({placeholders}) AND q.status = ?
        """,
        (*queue_ids, required_status),
    ).fetchall()
    by_id = {int(row["id"]): row for row in rows}
    return [by_id[queue_id] for queue_id in queue_ids if queue_id in by_id]


def playing_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT q.*, u.steam_id, u.steam_name,
               u.in_a_row, u.played_count, u.played_today, u.played_today_date
        FROM queue q
        LEFT JOIN users u ON u.twitch_name = q.twitch_name
        WHERE q.status = 'playing'
        ORDER BY q.playing_since ASC, q.id ASC
        """
    ).fetchall()


def get_state_value(key: str, default: str = "") -> str:
    with db() as con:
        row = con.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_state_value(key: str, value: str) -> None:
    with db() as con:
        con.execute(
            """
            INSERT INTO app_state(key, value)
            VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def normalize_name(name: str) -> str:
    return (name or "").strip().lstrip("@").lower()


def upsert_user(twitch_name: str, display_name: str | None = None) -> None:
    twitch_name = normalize_name(twitch_name)
    display_name = display_name or twitch_name
    with db() as con:
        con.execute(
            """
            INSERT INTO users(twitch_name, display_name)
            VALUES(?, ?)
            ON CONFLICT(twitch_name) DO UPDATE SET
                display_name = COALESCE(excluded.display_name, users.display_name)
            """,
            (twitch_name, display_name),
        )


def reset_daily_counter_if_needed(con: sqlite3.Connection, twitch_name: str) -> None:
    today = today_str()
    row = con.execute(
        "SELECT played_today_date FROM users WHERE twitch_name = ?",
        (twitch_name,),
    ).fetchone()
    if row and row["played_today_date"] != today:
        con.execute(
            "UPDATE users SET played_today = 0, played_today_date = ? WHERE twitch_name = ?",
            (today, twitch_name),
        )


def increment_played_counter(con: sqlite3.Connection, twitch_name: str) -> None:
    reset_daily_counter_if_needed(con, twitch_name)
    con.execute(
        """
        UPDATE users
        SET played_count = played_count + 1,
            played_today = played_today + 1,
            played_today_date = ?,
            last_played_at = ?
        WHERE twitch_name = ?
        """,
        (today_str(), now_iso(), twitch_name),
    )


def get_queue() -> list[dict[str, Any]]:
    with db() as con:
        rows = con.execute(
            """
            SELECT q.*, u.steam_id, u.steam_name, u.in_a_row, u.played_count, u.played_today, u.played_today_date
            FROM queue q
            LEFT JOIN users u ON u.twitch_name = q.twitch_name
            WHERE q.status IN ('waiting', 'playing')
            ORDER BY
                CASE q.status WHEN 'playing' THEN 0 ELSE 1 END,
                q.id ASC
            """
        ).fetchall()
        result = [dict(r) for r in rows]
        today = today_str()
        for item in result:
            if item.get("played_today_date") != today:
                item["played_today"] = 0
        return steam_links.attach(con, result)


def get_playing() -> list[dict[str, Any]]:
    with db() as con:
        rows = con.execute(
            """
            SELECT q.*, u.steam_id, u.steam_name, u.in_a_row, u.played_count, u.played_today, u.played_today_date
            FROM queue q
            LEFT JOIN users u ON u.twitch_name = q.twitch_name
            WHERE q.status = 'playing'
            ORDER BY q.playing_since ASC, q.id ASC
            """
        ).fetchall()
        result = [dict(r) for r in rows]
        today = today_str()
        for item in result:
            if item.get("played_today_date") != today:
                item["played_today"] = 0
        return steam_links.attach(con, result)


def get_detected_players() -> list[dict[str, Any]]:
    with db() as con:
        rows = con.execute(
            """
            SELECT d.*, u.display_name, u.in_a_row, u.played_count, u.played_today, u.played_today_date
            FROM detected_players d
            LEFT JOIN users u ON u.twitch_name = d.twitch_name
            ORDER BY d.first_seen_at DESC, d.last_seen_at DESC
            """
        ).fetchall()
        result = [dict(r) for r in rows]
        today = today_str()
        for item in result:
            if item.get("played_today_date") != today:
                item["played_today"] = 0
        return steam_links.attach(con, result)


def extract_players_from_gsi(payload: dict[str, Any]) -> list[dict[str, str]]:
    players: list[dict[str, str]] = []

    allplayers = payload.get("allplayers")
    if isinstance(allplayers, dict):
        for steam_id, player in allplayers.items():
            if not isinstance(player, dict):
                continue
            name = str(player.get("name") or player.get("clan") or steam_id)
            team = str(player.get("team") or "")
            players.append({"steam_id": str(steam_id), "steam_name": name, "team": team})

    player = payload.get("player")
    if isinstance(player, dict):
        steam_id = str(player.get("steamid") or player.get("steam_id") or "")
        name = str(player.get("name") or "")
        team = str(player.get("team") or "")
        if steam_id and not any(p["steam_id"] == steam_id for p in players):
            players.append({"steam_id": steam_id, "steam_name": name or steam_id, "team": team})

    return players


@app.route("/")
def index():
    return redirect("/admin")


@app.route("/admin")
def admin():
    return render_template("admin.html")


@app.route("/overlay")
def overlay():
    return render_template("overlay.html")


@app.route("/overlay/draw")
def draw_overlay():
    return render_template("draw_overlay.html")


@app.route("/api/join")
def api_join():
    raw_user = request.args.get("user", "")
    display = request.args.get("display", "") or raw_user
    twitch_name = normalize_name(raw_user)

    if not twitch_name:
        return jsonify({"ok": False, "message": "Kein User übergeben."}), 400

    upsert_user(twitch_name, display)

    with db() as con:
        existing = con.execute(
            """
            SELECT * FROM queue
            WHERE twitch_name = ? AND status IN ('waiting', 'playing')
            """,
            (twitch_name,),
        ).fetchone()

        if existing:
            return jsonify({"ok": True, "message": f"{display} ist bereits in der Queue."})

        con.execute(
            """
            INSERT INTO queue(twitch_name, display_name, status, joined_at)
            VALUES(?, ?, 'waiting', ?)
            """,
            (twitch_name, display, now_iso()),
        )

    return jsonify({"ok": True, "message": f"{display} wurde zur Queue hinzugefügt."})


@app.route("/api/leave")
def api_leave():
    twitch_name = normalize_name(request.args.get("user", ""))
    if not twitch_name:
        return jsonify({"ok": False, "message": "Kein User übergeben."}), 400

    with db() as con:
        con.execute(
            """
            UPDATE queue
            SET status = 'done'
            WHERE twitch_name = ? AND status IN ('waiting', 'playing')
            """,
            (twitch_name,),
        )
    return jsonify({"ok": True})


@app.route("/api/state")
def api_state():
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        gsi_engine.refresh(con, now_iso())
    queue = get_queue()
    waiting = [q for q in queue if q["status"] == "waiting"]
    playing_queue = [q for q in queue if q["status"] == "playing"]
    detected = get_detected_players()

    overlay_playing: list[dict[str, Any]] = []
    for p in playing_queue:
        overlay_playing.append(
            {
                "label": p["display_name"] or p["twitch_name"],
                "twitch_name": p["twitch_name"],
                "steam_name": p["steam_name"],
                "steam_id": p["steam_id"],
                "played_count": p["played_count"] or 0,
                "played_today": p["played_today"] or 0,
                "in_a_row": p["in_a_row"] or 0,
                "source": "queue",
            }
        )

    # Fallback: Falls noch niemand manuell auf playing gesetzt wurde,
    # zeige erkannte CS2-Spieler an.
    if not overlay_playing:
        gsi_status = json.loads(get_state_value("gsi_status", "{}"))
        for d in detected:
            if (gsi_status.get("phase") != "live" or d["team"] != gsi_status.get("own_team")
                    or d["last_seen_at"] != gsi_status.get("last_seen")):
                continue
            label = d["display_name"] or d["twitch_name"] or d["steam_name"] or d["steam_id"]
            overlay_playing.append(
                {
                    "label": label,
                    "twitch_name": d["twitch_name"],
                    "steam_name": d["steam_name"],
                    "steam_id": d["steam_id"],
                    "played_count": d["played_count"] or 0,
                    "played_today": d["played_today"] or 0,
                    "in_a_row": d["in_a_row"] or 0,
                    "source": "gsi",
                }
            )

    return jsonify(
        {
            "ok": True,
            "overlay_visible": get_state_value("overlay_visible", "1") == "1",
            "queue": queue,
            "waiting": waiting,
            "playing": playing_queue,
            "overlay_playing": overlay_playing,
            "detected_players": detected,
            "link_users": get_link_users(),
            "draw": load_draw(),
            "proposals": get_proposals(),
            "gsi_status": json.loads(get_state_value("gsi_status", "{}")),
            "ai_status": alias_ai.status(),
        }
    )

@app.route("/api/chat-queue")
def api_chat_queue():
    queue = get_queue()
    waiting = [q for q in queue if q["status"] == "waiting"]
    playing = [q for q in queue if q["status"] == "playing"]

    playing_names = [
        q["display_name"] or q["twitch_name"]
        for q in playing
    ]

    waiting_names = [
        f"{index + 1}. {q['display_name'] or q['twitch_name']}"
        for index, q in enumerate(waiting)
    ]

    if not playing_names and not waiting_names:
        message = "🎮 Aktuell spielt niemand mit und die Queue ist leer. Schreib !join, um reinzukommen."

    elif playing_names and waiting_names:
        message = (
            "🎮 Gerade spielend: "
            + ", ".join(playing_names)
            + " | ⏳ Warteschlange: "
            + " | ".join(waiting_names)
        )

    elif playing_names:
        message = (
            "🎮 Gerade spielend: "
            + ", ".join(playing_names)
            + " | ⏳ Warteschlange ist leer."
        )

    else:
        message = (
            "🎮 Gerade spielt niemand aus der Queue. "
            + "⏳ Warteschlange: "
            + " | ".join(waiting_names)
        )

    return jsonify({
        "ok": True,
        "message": message
    })

@app.route("/api/show-overlay")
def api_show_overlay():
    set_state_value("overlay_visible", "1")
    return jsonify({"ok": True, "overlay_visible": True})


@app.route("/api/hide-overlay")
def api_hide_overlay():
    set_state_value("overlay_visible", "0")
    return jsonify({"ok": True, "overlay_visible": False})


@app.route("/api/remove/<int:queue_id>", methods=["POST"])
def api_remove(queue_id: int):
    with db() as con:
        con.execute("UPDATE queue SET status = 'done' WHERE id = ?", (queue_id,))
    return jsonify({"ok": True})


@app.route("/api/waiting/<int:queue_id>", methods=["POST"])
def api_waiting(queue_id: int):
    with db() as con:
        con.execute(
            """
            UPDATE queue
            SET status = 'waiting', playing_since = NULL
            WHERE id = ? AND status = 'playing'
            """,
            (queue_id,),
        )
    return jsonify({"ok": True})


@app.route("/api/playing/<int:queue_id>", methods=["POST"])
def api_playing(queue_id: int):
    with db() as con:
        row = con.execute("SELECT * FROM queue WHERE id = ?", (queue_id,)).fetchone()
        if not row:
            return jsonify({"ok": False, "message": "Queue-Eintrag nicht gefunden."}), 404

        # Wichtig: Es werden NICHT mehr alle anderen Spieler zurück auf waiting gesetzt.
        # Dadurch können mehrere Leute gleichzeitig als aktuell spielend markiert werden.
        if row["status"] != "playing":
            con.execute(
                """
                UPDATE queue
                SET status = 'playing', playing_since = ?
                WHERE id = ?
                """,
                (now_iso(), queue_id),
            )


    return jsonify({"ok": True})


@app.route("/api/finish-playing", methods=["POST"])
def api_finish_playing():
    with db() as con:
        con.execute(
            """
            UPDATE queue
            SET status = 'done'
            WHERE status = 'playing'
            """
        )
    return jsonify({"ok": True})


@app.route("/api/clear-queue", methods=["POST"])
def api_clear_queue():
    with db() as con:
        con.execute(
            """
            UPDATE queue
            SET status = 'done'
            WHERE status IN ('waiting', 'playing')
            """
        )
    return jsonify({"ok": True})


@app.route("/api/clear-detected", methods=["POST"])
def api_clear_detected():
    with db() as con:
        con.execute("DELETE FROM detected_players")
    return jsonify({"ok": True})


@app.route("/api/link-steam", methods=["POST"])
def api_link_steam():
    data = request.get_json(silent=True) or {}
    twitch_name = normalize_name(data.get("twitch_name", ""))
    steam_id = str(data.get("steam_id", "")).strip()
    steam_name = str(data.get("steam_name", "")).strip()
    if not twitch_name or not steam_id:
        return jsonify(ok=False,message="Twitchname oder SteamID fehlt."),400
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        owner = steam_links.owner(con, steam_id)
        if owner and owner['twitch_name'] != twitch_name:
            return jsonify(ok=False,message="Dieses Steam-Konto ist bereits einem anderen Twitch-Nutzer zugeordnet."),409
        con.execute('INSERT OR IGNORE INTO users(twitch_name,display_name) VALUES(?,?)',(twitch_name,twitch_name))
        steam_links.add(con,twitch_name,steam_id,steam_name,now_iso())
        con.execute("UPDATE steam_proposals SET status='confirmed' WHERE steam_id=? AND twitch_name=?",(steam_id,twitch_name))
        con.execute('UPDATE detected_players SET twitch_name=? WHERE steam_id=?',(twitch_name,steam_id))
    return jsonify(ok=True)


def get_link_users():
    cutoff = (datetime.fromisoformat(now_iso()) - timedelta(hours=12)).isoformat(timespec='seconds')
    with db() as con:
        rows = con.execute("""SELECT u.twitch_name,u.display_name,MAX(q.joined_at) AS last_joined_at,
            CASE WHEN MAX(CASE WHEN q.status='playing' THEN 1 ELSE 0 END)=1 THEN 'playing'
                 WHEN MAX(CASE WHEN q.status='waiting' THEN 1 ELSE 0 END)=1 THEN 'waiting' ELSE 'done' END AS status
            FROM users u JOIN queue q ON q.twitch_name=u.twitch_name
            GROUP BY u.twitch_name
            HAVING MAX(CASE WHEN q.status IN ('playing','waiting') THEN 1 ELSE 0 END)=1
                OR datetime(MAX(q.joined_at))>=datetime(?)
            ORDER BY CASE WHEN MAX(CASE WHEN q.status IN ('playing','waiting') THEN 1 ELSE 0 END)=1 THEN 0 ELSE 1 END,
                last_joined_at DESC,u.twitch_name COLLATE NOCASE""",(cutoff,)).fetchall()
        return steam_links.attach(con,[dict(row) for row in rows])


@app.route("/api/draw/state")
def api_draw_state():
    return jsonify({"ok": True, "draw": load_draw()})


@app.route("/api/draw/start", methods=["POST"])
def api_draw_start():
    data = request.get_json(force=True, silent=True) or {}
    try:
        candidate_ids = requested_ids(data, "candidate_ids")
        challenger_ids = requested_ids(data, "challenger_ids")
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    if not 2 <= len(candidate_ids) <= 4:
        return jsonify(
            {"ok": False, "message": "Bitte 2 bis 4 auslosbare Spieler auswählen."}
        ), 400
    if not 1 <= len(challenger_ids) <= len(candidate_ids):
        return jsonify(
            {
                "ok": False,
                "message": "Die Zahl der Nachrücker muss zwischen 1 und der Zahl der Kandidaten liegen.",
            }
        ), 400

    with db() as con:
        # A write lock prevents two rapid clicks from applying two rotations.
        con.execute("BEGIN IMMEDIATE")
        candidates = queue_rows_by_ids(con, candidate_ids, "playing")
        challengers = queue_rows_by_ids(con, challenger_ids, "waiting")

        if len(candidates) != len(candidate_ids):
            return jsonify(
                {
                    "ok": False,
                    "message": "Mindestens ein Kandidat spielt inzwischen nicht mehr. Bitte Auswahl aktualisieren.",
                }
            ), 409
        if len(challengers) != len(challenger_ids):
            return jsonify(
                {
                    "ok": False,
                    "message": "Mindestens ein Nachrücker wartet inzwischen nicht mehr. Bitte Auswahl aktualisieren.",
                }
            ), 409

        # secrets.SystemRandom uses the operating system's secure random source.
        outgoing = secrets.SystemRandom().sample(candidates, len(challengers))
        outgoing_ids = {int(row["id"]) for row in outgoing}
        staying = [row for row in candidates if int(row["id"]) not in outgoing_ids]

        draw_time = now_iso()
        con.executemany(
            "UPDATE queue SET status = 'done', playing_since = NULL WHERE id = ?",
            [(int(row["id"]),) for row in outgoing],
        )

        for challenger in challengers:
            con.execute(
                """
                UPDATE queue
                SET status = 'playing', playing_since = ?
                WHERE id = ? AND status = 'waiting'
                """,
                (draw_time, int(challenger["id"])),
            )


        # Refresh promoted players so the new counters in the animation are correct.
        promoted = queue_rows_by_ids(con, challenger_ids, "playing")
        promoted_by_id = {int(row["id"]): row for row in promoted}
        promoted = [promoted_by_id[queue_id] for queue_id in challenger_ids]

        rounds = [
            {
                "number": index + 1,
                "outgoing": player_snapshot(outgoing[index]),
                "incoming": player_snapshot(promoted[index]),
            }
            for index in range(len(outgoing))
        ]

        payload = {
            "title": "SCHICHTWECHSEL",
            "subtitle": f"{len(challengers)} PLÄTZE · {len(candidates)} KANDIDATEN · KEINE GNADE",
            "candidates": [player_snapshot(row) for row in candidates],
            "challengers": [player_snapshot(row) for row in promoted],
            "rounds": rounds,
            "outgoing": [player_snapshot(row) for row in outgoing],
            "staying": [player_snapshot(row) for row in staying],
            "lineup": [player_snapshot(row) for row in playing_rows(con)],
        }

        draw_id = uuid.uuid4().hex
        con.execute("UPDATE rotation_draws SET active = 0 WHERE active = 1")
        con.execute(
            """
            INSERT INTO rotation_draws(
                draw_id, created_at, animation_revision, active, payload_json
            )
            VALUES(?, ?, 1, 1, ?)
            """,
            (draw_id, draw_time, json.dumps(payload, ensure_ascii=False)),
        )

    draw = load_draw()
    return jsonify(
        {
            "ok": True,
            "message": "Schichtwechsel wurde ausgelost und die Queue aktualisiert.",
            "draw": draw,
        }
    )


@app.route("/api/draw/replay", methods=["POST"])
def api_draw_replay():
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT draw_id FROM rotation_draws ORDER BY created_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "message": "Es gibt noch keine Auslosung."}), 404
        con.execute("UPDATE rotation_draws SET active = 0 WHERE active = 1")
        con.execute(
            """
            UPDATE rotation_draws
            SET active = 1, animation_revision = animation_revision + 1
            WHERE draw_id = ?
            """,
            (row["draw_id"],),
        )
    return jsonify({"ok": True, "draw": load_draw()})


@app.route("/api/draw/hide", methods=["POST"])
def api_draw_hide():
    data = request.get_json(force=True, silent=True) or {}
    draw_id = str(data.get("draw_id") or "").strip()
    raw_revision = data.get("animation_revision")

    with db() as con:
        latest = con.execute(
            """
            SELECT draw_id, animation_revision
            FROM rotation_draws
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """
        ).fetchone()
        if not latest:
            return jsonify({"ok": True, "draw": None})

        if draw_id and draw_id != latest["draw_id"]:
            return jsonify({"ok": False, "message": "Diese Auslosung ist nicht mehr aktuell."}), 409
        if raw_revision is not None:
            try:
                revision = int(raw_revision)
            except (TypeError, ValueError):
                return jsonify({"ok": False, "message": "Ungültige Animationsversion."}), 400
            if revision != int(latest["animation_revision"]):
                return jsonify({"ok": False, "message": "Die Animation wurde bereits neu gestartet."}), 409

        con.execute(
            "UPDATE rotation_draws SET active = 0 WHERE draw_id = ?",
            (latest["draw_id"],),
        )
    return jsonify({"ok": True, "draw": load_draw()})


def get_proposals():
    with db() as con:
        return [dict(r) for r in con.execute("SELECT * FROM steam_proposals WHERE status='pending' ORDER BY created_at DESC")]


@app.route("/api/proposal", methods=["POST"])
def api_proposal():
    data = request.get_json(silent=True) or {}
    sid, action = str(data.get("steam_id", "")), data.get("action")
    if action not in ("confirm", "reject"):
        return jsonify(ok=False, message="Ungültige Aktion."), 400
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        proposal = con.execute("SELECT * FROM steam_proposals WHERE steam_id=? AND status='pending'",(sid,)).fetchone()
        if not proposal:
            return jsonify(ok=False,message="Vorschlag nicht mehr offen."),409
        name = proposal["twitch_name"]
        if action == "reject":
            con.execute("INSERT OR IGNORE INTO rejected_links VALUES(?,?)",(sid,name))
            con.execute("UPDATE detected_players SET twitch_name=NULL WHERE steam_id=? AND twitch_name=?",(sid,name))
            steam_links.reject(con,sid,name)
            counted = 0
            affected = con.execute("SELECT match_id FROM match_players WHERE twitch_name=? AND steam_id=?",(name,sid)).fetchall()
            for row in affected:
                alternative = next((p for p in gsi_engine.teammates_for_match(con,row['match_id'])
                                    if p['steam_id'] != sid and (linked := steam_links.owner(con,p['steam_id']))
                                    and linked['twitch_name'] == name),None)
                if alternative:
                    con.execute("UPDATE match_players SET steam_id=? WHERE match_id=? AND twitch_name=?",(alternative['steam_id'],row['match_id'],name))
                else:
                    con.execute("DELETE FROM match_players WHERE match_id=? AND twitch_name=?",(row['match_id'],name))
                    counted += 1
            series = 0
            for match in con.execute("SELECT * FROM matches ORDER BY rowid"):
                participated = con.execute("SELECT 1 FROM match_players WHERE match_id=? AND twitch_name=?",(match['id'],name)).fetchone()
                if participated:
                    series += 1
                elif match['complete'] and match['finished']:
                    series = 0
            con.execute("UPDATE users SET in_a_row=?,played_count=MAX(0,played_count-?) WHERE twitch_name=?",(series,counted,name))
        if action == "confirm":
            con.execute("UPDATE steam_accounts SET status='confirmed' WHERE steam_id=? AND twitch_name=?",(sid,name))
        con.execute("UPDATE steam_proposals SET status=? WHERE steam_id=?",('confirmed' if action=='confirm' else 'rejected',sid))
    return jsonify(ok=True)


@app.route("/api/draw/return", methods=["POST"])
def api_draw_return():
    data = request.get_json(silent=True) or {}
    try:
        missing_ids = requested_ids(data,"missing_ids")
    except ValueError as exc:
        return jsonify(ok=False,message=str(exc)),400
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        draw = load_draw(con)
        if not draw or data.get("draw_id") != draw['draw_id']:
            return jsonify(ok=False,message="Schichtwechsel ist nicht mehr aktuell."),409
        allowed = {p['id'] for p in draw['challengers']}
        used = set(draw.get('returned_missing_ids',[]))
        if not missing_ids or not set(missing_ids)<=allowed or set(missing_ids)&used:
            return jsonify(ok=False,message="Bitte noch nicht ersetzte Nachrücker auswählen."),400
        missing = queue_rows_by_ids(con,missing_ids,'playing')
        pool_ids = [p['id'] for p in draw['outgoing'] if p['id'] not in draw.get('returned_ids',[])]
        pool = queue_rows_by_ids(con,pool_ids,'done')
        pool = [p for p in pool if not con.execute("SELECT 1 FROM queue WHERE twitch_name=? AND status IN ('waiting','playing')",(p['twitch_name'],)).fetchone()]
        if len(missing)!=len(missing_ids) or len(pool)<len(missing):
            return jsonify(ok=False,message="Auswahl hat sich geändert oder nicht genug Rückkehrer verfügbar."),409
        returned = secrets.SystemRandom().sample(pool,len(missing))
        for row in missing:
            con.execute("UPDATE queue SET status='waiting',playing_since=NULL WHERE id=?",(row['id'],))
        for row in returned:
            con.execute("UPDATE queue SET status='playing',playing_since=? WHERE id=?",(now_iso(),row['id']))
        draw.setdefault('returned_ids',[]).extend(p['id'] for p in returned)
        draw.setdefault('returned_missing_ids',[]).extend(missing_ids)
        draw['lineup'] = [player_snapshot(r) for r in playing_rows(con)]
        con.execute("UPDATE rotation_draws SET active=0,payload_json=? WHERE draw_id=?",(json.dumps(draw,ensure_ascii=False),draw['draw_id']))
    return jsonify(ok=True,returned=[player_snapshot(r) for r in returned])


@app.route("/gsi", methods=["POST"])
def gsi():
    payload = request.get_json(force=True, silent=True) or {}
    if not isinstance(payload,dict):
        return jsonify(ok=False,message="Ungültige GSI-Daten."),400
    players = extract_players_from_gsi(payload)
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        accepted = gsi_engine.process(con,payload,players,now_iso())
        if not accepted:
            return jsonify(ok=True,players_detected=0,ignored="older_packet")
        for p in players:
            linked = steam_links.owner(con,p['steam_id'])
            con.execute("""INSERT INTO detected_players(steam_id,steam_name,team,twitch_name,first_seen_at,last_seen_at,detect_count)
                VALUES(?,?,?,?,?,?,1) ON CONFLICT(steam_id) DO UPDATE SET
                steam_name=excluded.steam_name,team=excluded.team,twitch_name=excluded.twitch_name,
                last_seen_at=excluded.last_seen_at,detect_count=detect_count+1""",
                (p['steam_id'],p['steam_name'],p['team'],linked['twitch_name'] if linked else None,now_iso(),now_iso()))
    return jsonify(ok=True,players_detected=len(players))


if __name__ == "__main__":
    init_db()
    alias_ai.prepare_background()
    print(f"SteinHQ Play Queue läuft auf http://127.0.0.1:{APP_PORT}/admin")
    app.run(host="127.0.0.1", port=APP_PORT, debug=False)
