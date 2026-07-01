import unittest

from rivalsmeta_adapter import (
    is_rivalsmeta_match_url,
    match_id_from_rivalsmeta_url,
    normalise_rivalsmeta_match_payload,
    read_limited_response_body,
)


MATCH_UID = "5169091_1782826338_2042119_11001_33"


class RivalsMetaAdapterTests(unittest.TestCase):
    def test_url_with_or_without_player_query_has_same_match_id(self):
        plain = f"https://rivalsmeta.com/matches/{MATCH_UID}"
        queried = f"{plain}?player_uid=1064511620"

        self.assertEqual(match_id_from_rivalsmeta_url(plain), MATCH_UID)
        self.assertEqual(match_id_from_rivalsmeta_url(queried), MATCH_UID)
        self.assertTrue(is_rivalsmeta_match_url(queried))

    def test_rejects_non_rivalsmeta_and_lookalike_hosts(self):
        self.assertFalse(is_rivalsmeta_match_url(f"http://rivalsmeta.com/matches/{MATCH_UID}"))
        self.assertFalse(is_rivalsmeta_match_url(f"https://rivalsmeta.com.example/matches/{MATCH_UID}"))
        self.assertFalse(is_rivalsmeta_match_url(f"https://example.com/matches/{MATCH_UID}"))

    def test_normalises_match_player_hero_and_ban_fields(self):
        payload = normalise_rivalsmeta_match_payload({
            "match_uid": MATCH_UID,
            "match_time_stamp": 1782827191,
            "game_mode_id": 3,
            "dynamic_fields": {"ban_pick_info": [{"hero_id": 1045, "is_pick": 0}]},
            "match_players": [{
                "player_uid": 1064511620,
                "nick_name": "LatinMaestro",
                "camp": 1,
                "is_win": 0,
                "k": 12,
                "d": 8,
                "a": 6,
                "last_kill": 5,
                "solo_kill": 1,
                "total_hero_damage": 8983.4,
                "total_hero_heal": 14861.1,
                "total_damage_taken": 9724.3,
                "player_heroes": [{
                    "hero_id": 1050,
                    "play_time": 577.8,
                    "k": 12,
                    "d": 8,
                    "a": 6,
                    "session_hit_rate": 0.55,
                }],
            }],
        })

        md = payload["match_details"]
        player = md["match_players"][0]
        hero = player["player_heroes"][0]
        self.assertEqual(md["game_mode"]["game_mode_name"], "Custom")
        self.assertEqual(md["timestamp"], 1782827191)
        self.assertEqual(md["match_dynamic_fields"]["ban_pick_info"][0]["hero_id"], 1045)
        self.assertEqual((player["kills"], player["deaths"], player["assists"]), (12, 8, 6))
        self.assertEqual(player["final_hits"], 5)
        self.assertEqual((hero["kills"], hero["deaths"], hero["assists"]), (12, 8, 6))


class _ChunkedContent:
    def __init__(self, chunks):
        self.chunks = chunks

    async def iter_chunked(self, _size):
        for chunk in self.chunks:
            yield chunk


class RivalsMetaResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_all_chunks_before_json_decoding(self):
        content = _ChunkedContent([b'{"match_uid":', b'"123_456",', b'"match_players":[]}'])

        body = await read_limited_response_body(content)

        self.assertEqual(body, b'{"match_uid":"123_456","match_players":[]}')

    async def test_rejects_response_over_size_limit(self):
        content = _ChunkedContent([b"12345", b"67890", b"x"])

        with self.assertRaisesRegex(ValueError, "unexpectedly large"):
            await read_limited_response_body(content, max_bytes=10)


if __name__ == "__main__":
    unittest.main()
