import sqlite3
import tempfile
import unittest
from pathlib import Path

import app as playqueue


class RotationDrawTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db_path = playqueue.DB_PATH
        playqueue.DB_PATH = Path(self.tempdir.name) / "queue.db"
        playqueue.app.config.update(TESTING=True)
        playqueue.init_db()
        self.client = playqueue.app.test_client()

    def tearDown(self):
        playqueue.DB_PATH = self.original_db_path
        self.tempdir.cleanup()

    def seed_rotation(self):
        today = playqueue.today_str()
        with playqueue.db() as con:
            for index in range(1, 7):
                name = f"player{index}"
                con.execute(
                    """
                    INSERT INTO users(
                        twitch_name, display_name, played_count, played_today, played_today_date
                    ) VALUES(?, ?, ?, ?, ?)
                    """,
                    (name, f"Player {index}", index * 3, 2 if index <= 4 else 0, today),
                )
                con.execute(
                    """
                    INSERT INTO queue(
                        twitch_name, display_name, status, joined_at, playing_since
                    ) VALUES(?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        f"Player {index}",
                        "playing" if index <= 4 else "waiting",
                        f"2026-08-25T00:0{index}:00",
                        f"2026-08-25T00:1{index}:00" if index <= 4 else None,
                    ),
                )

        with playqueue.db() as con:
            rows = con.execute("SELECT id, twitch_name FROM queue ORDER BY id").fetchall()
        ids = {row["twitch_name"]: int(row["id"]) for row in rows}
        return [ids[f"player{i}"] for i in range(1, 5)], [ids["player5"], ids["player6"]]

    def active_statuses(self):
        with playqueue.db() as con:
            return {
                row["twitch_name"]: row["status"]
                for row in con.execute("SELECT twitch_name, status FROM queue ORDER BY id")
            }

    def test_start_draw_applies_exactly_two_replacements(self):
        candidates, challengers = self.seed_rotation()
        response = self.client.post(
            "/api/draw/start",
            json={"candidate_ids": candidates, "challenger_ids": challengers},
        )
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertTrue(result["ok"])
        draw = result["draw"]

        self.assertTrue(draw["active"])
        self.assertEqual(len(draw["candidates"]), 4)
        self.assertEqual(len(draw["challengers"]), 2)
        self.assertEqual(len(draw["outgoing"]), 2)
        self.assertEqual(len(draw["staying"]), 2)
        self.assertEqual(len(draw["rounds"]), 2)
        self.assertEqual(len(draw["lineup"]), 4)

        outgoing_names = {player["twitch_name"] for player in draw["outgoing"]}
        staying_names = {player["twitch_name"] for player in draw["staying"]}
        self.assertEqual(outgoing_names | staying_names, {f"player{i}" for i in range(1, 5)})
        self.assertFalse(outgoing_names & staying_names)

        statuses = self.active_statuses()
        for name in outgoing_names:
            self.assertEqual(statuses[name], "done")
        for name in staying_names | {"player5", "player6"}:
            self.assertEqual(statuses[name], "playing")

        with playqueue.db() as con:
            promoted = con.execute(
                "SELECT twitch_name, played_today FROM users WHERE twitch_name IN ('player5', 'player6')"
            ).fetchall()
        self.assertEqual({row["twitch_name"]: row["played_today"] for row in promoted}, {"player5": 0, "player6": 0})

    def test_replay_never_changes_the_queue_again(self):
        candidates, challengers = self.seed_rotation()
        started = self.client.post(
            "/api/draw/start",
            json={"candidate_ids": candidates, "challenger_ids": challengers},
        ).get_json()["draw"]
        statuses_after_draw = self.active_statuses()

        replay_response = self.client.post("/api/draw/replay")
        self.assertEqual(replay_response.status_code, 200)
        replayed = replay_response.get_json()["draw"]
        self.assertEqual(replayed["draw_id"], started["draw_id"])
        self.assertEqual(replayed["animation_revision"], 2)
        self.assertEqual(replayed["outgoing"], started["outgoing"])
        self.assertEqual(self.active_statuses(), statuses_after_draw)

        hidden = self.client.post(
            "/api/draw/hide",
            json={
                "draw_id": replayed["draw_id"],
                "animation_revision": replayed["animation_revision"],
            },
        )
        self.assertEqual(hidden.status_code, 200)
        self.assertFalse(hidden.get_json()["draw"]["active"])

    def test_invalid_selection_is_rejected_without_mutation(self):
        candidates, challengers = self.seed_rotation()
        before = self.active_statuses()
        response = self.client.post(
            "/api/draw/start",
            json={"candidate_ids": candidates[:1], "challenger_ids": challengers[:1]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])
        self.assertEqual(self.active_statuses(), before)

    def test_existing_routes_are_still_registered(self):
        expected = {
            "/admin",
            "/overlay",
            "/api/join",
            "/api/leave",
            "/api/state",
            "/api/chat-queue",
            "/api/show-overlay",
            "/api/hide-overlay",
            "/api/finish-playing",
            "/api/clear-queue",
            "/api/clear-detected",
            "/api/link-steam",
            "/gsi",
        }
        registered = {rule.rule for rule in playqueue.app.url_map.iter_rules()}
        self.assertTrue(expected.issubset(registered))

    def test_admin_and_both_overlay_pages_render(self):
        for url, marker in (
            ("/admin", "Schichtwechsel"),
            ("/overlay", "drawStage"),
            ("/overlay/draw", "drawCrosshair"),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn(marker.encode(), response.data)

    def test_join_and_leave_continue_to_work(self):
        joined = self.client.get("/api/join?user=TestUser&display=Test%20User")
        self.assertEqual(joined.status_code, 200)
        state = self.client.get("/api/state").get_json()
        self.assertEqual([player["twitch_name"] for player in state["waiting"]], ["testuser"])

        left = self.client.get("/api/leave?user=TestUser")
        self.assertEqual(left.status_code, 200)
        state = self.client.get("/api/state").get_json()
        self.assertEqual(state["waiting"], [])


if __name__ == "__main__":
    unittest.main()
