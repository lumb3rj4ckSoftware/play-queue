import os
from unittest.mock import patch
from concurrent.futures import Future
import unittest
import test_rotation_draw as rotation
import app as pq
import gsi_engine as engine

class GSITest(unittest.TestCase):
    tearDown = rotation.RotationDrawTest.tearDown
    seed_rotation = rotation.RotationDrawTest.seed_rotation
    active_statuses = rotation.RotationDrawTest.active_statuses
    def setUp(self):
        rotation.RotationDrawTest.setUp(self)
        engine._jobs.clear()
        self.fallback = Future(); self.fallback.set_result(None)
        self.ai_patch = patch.object(engine._pool, 'submit', return_value=self.fallback)
        self.ai_patch.start()
        self.addCleanup(self.ai_patch.stop)

    def add(self, name, sid=None, status='waiting'):
        self.client.get('/api/join',query_string={'user':name})
        with pq.db() as con:
            con.execute('UPDATE users SET steam_id=? WHERE twitch_name=?',(sid,name))
            con.execute('UPDATE queue SET status=? WHERE twitch_name=?',(status,name))

    def packet(self, phase='live', names=None, round_no=0, full=True, mode='competitive', timestamp=None):
        names = names if names is not None else {'2':'Tessa'}
        players = {'1':{'name':'Stein','team':'CT'}}
        players.update({sid:{'name':name,'team':'CT'} for sid,name in names.items()})
        if full:
            for i in range(len(players),5): players[str(20+i)]={'name':f'ally{i}','team':'CT'}
            for i in range(5): players[str(30+i)]={'name':f'enemy{i}','team':'T'}
        provider={'steamid':'1'}
        if timestamp is not None: provider['timestamp']=timestamp
        return {'provider':provider,'map':{'name':'de_mirage','mode':mode,'phase':phase,'round':round_no,'team_ct':{'score':round_no},'team_t':{'score':0}},'allplayers':players,'player':{'steamid':'1','name':'Stein','team':'CT'}}

    def send(self, **kwargs):
        r=self.client.post('/gsi',json=self.packet(**kwargs)); self.assertEqual(r.status_code,200);return r.get_json()

    def user(self,name='tessa'):
        with pq.db() as con:return dict(con.execute('SELECT * FROM users WHERE twitch_name=?',(name,)).fetchone())

    def test_automatic_promotion_and_one_count_per_match(self):
        self.add('tessa','2')
        self.send(phase='warmup');self.assertEqual(self.user()['in_a_row'],0)
        for n in (0,1,2,3):self.send(round_no=n)
        self.assertEqual(self.user()['in_a_row'],1)
        self.assertEqual(self.client.get('/api/state').json['playing'][0]['twitch_name'],'tessa')
        self.send(phase='gameover',round_no=24)
        self.send(phase='gameover',round_no=24)
        self.send(phase='warmup');self.send()
        self.assertEqual(self.user()['in_a_row'],2)
        self.assertEqual(self.user()['played_count'],2)

    def test_absent_match_resets_then_returns_at_one(self):
        self.add('tessa','2');self.send();self.send(phase='gameover')
        self.send(names={});self.send(phase='gameover',names={})
        self.assertEqual(self.user()['in_a_row'],0)
        self.send();self.assertEqual(self.user()['in_a_row'],1)

    def test_partial_roster_cannot_reset_series(self):
        self.add('tessa','2');self.send();self.send(phase='gameover')
        self.send(names={},full=False);self.send(phase='gameover',names={},full=False)
        self.assertEqual(self.user()['in_a_row'],1)

    def test_stylized_name_proposal_confirm(self):
        self.add('tessa',status='playing');self.send(names={'2':'XxT3ssaxX'})
        state=self.client.get('/api/state').json
        self.assertEqual(state['proposals'][0]['twitch_name'],'tessa')
        self.assertEqual(self.user()['steam_id'],'2')
        self.assertEqual(self.user()['in_a_row'],1)
        self.client.post('/api/proposal',json={'steam_id':'2','action':'confirm'})
        self.assertEqual(self.client.get('/api/state').json['proposals'],[])

    def test_rejection_undoes_provisional_count_and_blocks_repeat(self):
        self.add('tessa',status='playing');self.send(names={'2':'XxT3ssaxX'})
        self.client.post('/api/proposal',json={'steam_id':'2','action':'reject'})
        self.send(names={'2':'XxT3ssaxX'})
        self.assertIsNone(self.user()['steam_id']);self.assertEqual(self.user()['in_a_row'],0)
        self.assertEqual(self.user()['played_count'],0)
        with pq.db() as con:self.assertIsNone(con.execute('SELECT twitch_name FROM detected_players WHERE steam_id="2"').fetchone()[0])

    def test_ambiguous_names_do_not_link(self):
        self.add('tessa',status='playing');self.add('tessaa',status='playing');self.send(names={'2':'XxT3ssaxX'})
        self.assertIsNone(self.user()['steam_id'])

    def test_opponent_and_spectated_opponent_do_not_link(self):
        self.add('tessa',status='playing');p=self.packet(names={})
        p['allplayers']['30']['name']='XxT3ssaxX';p['player']={'steamid':'30','name':'XxT3ssaxX','team':'T'}
        self.client.post('/gsi',json=p);self.assertIsNone(self.user()['steam_id'])

    def test_manual_promotion_and_rotation_do_not_count(self):
        self.add('tessa','2');q=self.client.get('/api/state').json['waiting'][0]
        self.client.post(f"/api/playing/{q['id']}");self.assertEqual(self.user()['in_a_row'],0)

    def test_restart_maintains_idempotency(self):
        self.add('tessa','2');self.send();pq.init_db();self.send();self.assertEqual(self.user()['in_a_row'],1)

    def test_same_map_score_reset_starts_new_match(self):
        self.add('tessa','2');self.send(round_no=12);self.send(round_no=0)
        self.assertEqual(self.user()['in_a_row'],2)

    def test_old_packet_and_deathmatch_do_not_count(self):
        self.add('tessa','2');self.send(timestamp=200);self.send(phase='warmup',timestamp=100);self.send(timestamp=201)
        self.assertEqual(self.user()['in_a_row'],1)
        self.send(mode='deathmatch');self.assertEqual(self.user()['in_a_row'],1)

    def test_local_model_result_used(self):
        self.add('tessa',status='playing')
        future=Future();future.set_result(.97)
        with patch.dict(os.environ,{'PLAYQUEUE_AI_MODEL':'test-model'}),patch.object(engine._pool,'submit',return_value=future):
            self.send(names={'2':'tessy'})
        proposal=self.client.get('/api/state').json['proposals'][0]
        self.assertEqual(proposal['method'],'Eingebautes KI-Modell')

    def test_return_draw_is_transactional_and_no_duplicate_return(self):
        candidates,challengers=self.seed_rotation()
        draw=self.client.post('/api/draw/start',json={'candidate_ids':candidates,'challenger_ids':challengers}).json['draw']
        before=self.active_statuses()
        r=self.client.post('/api/draw/return',json={'draw_id':draw['draw_id'],'missing_ids':challengers[:1]})
        self.assertEqual(r.status_code,200);self.assertEqual(len(r.json['returned']),1)
        after=self.active_statuses();self.assertEqual(list(after.values()).count('playing'),4)
        again=self.client.post('/api/draw/return',json={'draw_id':draw['draw_id'],'missing_ids':challengers[:1]})
        self.assertEqual(again.status_code,400);self.assertEqual(self.active_statuses(),after)
        self.assertNotEqual(before,after)

    def test_manual_steam_conflict_returns_409(self):
        self.add('tessa','2');self.add('other')
        r=self.client.post('/api/link-steam',json={'twitch_name':'other','steam_id':'2'})
        self.assertEqual(r.status_code,409)

    def test_model_is_direct_not_http(self):
        with patch.object(engine.alias_ai,'score',return_value=.96) as scoring:
            self.assertEqual(engine.model_score('tessa','XxT3ssaxX'),.96)
            scoring.assert_called_once_with('tessa','XxT3ssaxX')

    def test_sparse_live_packet_does_not_create_new_match(self):
        self.add('tessa','2');self.send(round_no=5)
        packet=self.packet();packet['map']={'phase':'live','mode':'competitive'}
        self.client.post('/gsi',json=packet)
        self.assertEqual(self.user()['in_a_row'],1)

    def spectate(self, sid, name, team='CT', round_no=0, phase='live', with_self=False):
        packet=self.packet(names={},full=False,round_no=round_no,phase=phase)
        packet.pop('allplayers')
        packet['player']={'steamid':sid,'name':name,'team':team}
        if with_self:
            packet['allplayers']={'1':{'name':'Stein','team':'CT'},sid:{'name':name,'team':team}}
        response=self.client.post('/gsi',json=packet)
        self.assertEqual(response.status_code,200)

    def test_sequential_five_teammates_without_ten_player_snapshot_reset_absent(self):
        self.add('tessa','2')
        self.send();self.send(phase='gameover')
        self.spectate('1','Stein')
        for sid in ('3','4','5','6'):
            self.spectate(sid,'Ally'+sid)
        state=self.client.get('/api/state').json
        self.assertEqual(state['gsi_status']['team_collected'],5)
        self.assertTrue(state['gsi_status']['team_complete'])
        self.spectate('6','Ally6',phase='gameover')
        self.assertEqual(self.user()['in_a_row'],0)

    def test_spectated_player_uses_cached_round_team(self):
        self.add('tessa','2')
        self.spectate('1','Stein',round_no=4)
        self.spectate('2','Tessa',round_no=4)
        self.assertEqual(self.user()['in_a_row'],1)
        self.assertEqual(self.client.get('/api/state').json['playing'][0]['twitch_name'],'tessa')

    def test_restart_keeps_accumulated_team_and_own_team(self):
        self.add('tessa','2')
        self.spectate('1','Stein',round_no=4)
        pq.init_db()
        self.spectate('2','Tessa',round_no=4)
        self.assertEqual(self.user()['in_a_row'],1)
        self.assertEqual(self.client.get('/api/state').json['gsi_status']['team_collected'],2)

    def test_new_match_does_not_reuse_team_from_old_match(self):
        self.add('tessa','2');self.send();self.send(phase='gameover')
        self.spectate('30','EnemyTessa',team='T')
        self.assertEqual(self.client.get('/api/state').json['gsi_status']['team_collected'],0)
        self.assertEqual(self.user()['in_a_row'],1)

    def test_halftime_does_not_mix_opponents_or_duplicate_count(self):
        self.add('tessa','2');self.spectate('1','Stein',round_no=11);self.spectate('2','Tessa',round_no=11)
        self.spectate('1','Stein',team='T',round_no=12)
        self.spectate('30','Enemy',team='CT',round_no=12)
        self.spectate('2','Tessa',team='T',round_no=12)
        self.assertEqual(self.user()['in_a_row'],1)
        collected=self.client.get('/api/state').json['gsi_status']['teammates']
        self.assertEqual({p['steam_id'] for p in collected},{'1','2'})

    def test_unknown_round_side_retroactively_classified_with_own_player(self):
        self.add('tessa','2')
        self.spectate('2','Tessa',round_no=12,team='T')
        self.assertEqual(self.user()['in_a_row'],0)
        self.spectate('1','Stein',round_no=12,team='T')
        self.assertEqual(self.user()['in_a_row'],1)

    def test_delayed_ai_result_applied_by_admin_poll_from_accumulated_roster(self):
        self.add('tessa',status='playing')
        pending=Future()
        with patch.object(engine._pool,'submit',return_value=pending):
            self.spectate('1','Stein',round_no=2)
            self.spectate('2','XxT3ssaxX',round_no=2)
            self.assertIsNone(self.user()['steam_id'])
            # Currently received player is now someone else; proposal uses stored roster.
            self.spectate('3','Other',round_no=2)
            pending.set_result(.99)
            state=self.client.get('/api/state').json
            self.assertEqual(state['proposals'][0]['steam_id'],'2')
            self.assertEqual(self.user()['in_a_row'],1)

    def test_gameover_last_observation_is_counted_before_final_reset(self):
        self.add('tessa','2')
        self.spectate('1','Stein',round_no=4)
        for sid in ('3','4','5'):self.spectate(sid,'Ally'+sid,round_no=4)
        self.spectate('2','Tessa',phase='gameover',round_no=4)
        self.assertEqual(self.user()['in_a_row'],1)
        self.assertTrue(self.client.get('/api/state').json['gsi_status']['team_complete'])

    def test_manual_late_link_uses_previous_observation(self):
        self.add('unrelated',status='playing')
        self.spectate('1','Stein',round_no=3);self.spectate('2','Tessa',round_no=3)
        self.spectate('3','Other',round_no=3)
        self.client.post('/api/link-steam',json={'twitch_name':'unrelated','steam_id':'2'})
        self.client.get('/api/state')
        self.assertEqual(self.user('unrelated')['in_a_row'],1)

    def test_wingman_own_team_two_suffices_for_reset(self):
        self.add('tessa','2');self.send(mode='scrimcomp2v2',full=False);self.send(mode='scrimcomp2v2',full=False,phase='gameover')
        self.send(mode='scrimcomp2v2',names={'3':'Other'},full=False)
        self.send(mode='scrimcomp2v2',names={'3':'Other'},full=False,phase='gameover')
        self.assertEqual(self.user()['in_a_row'],0)

    def test_opponents_alone_never_complete_own_team(self):
        self.add('tessa','2');self.send();self.send(phase='gameover')
        self.spectate('1','Stein',round_no=2)
        for sid in ('30','31','32','33','34'):self.spectate(sid,'Enemy'+sid,team='T',round_no=2)
        self.spectate('34','Enemy34',team='T',round_no=2,phase='gameover')
        self.assertEqual(self.user()['in_a_row'],1)
        self.assertFalse(self.client.get('/api/state').json['gsi_status']['team_complete'])

    def test_upgrade_old_tracking_does_not_count_current_match_twice(self):
        import json
        self.add('tessa','2');self.send()
        with pq.db() as con:
            state=engine.load_tracking(con);state.pop('mode')
            con.execute("UPDATE app_state SET value=? WHERE key='gsi_tracking'",(json.dumps(state),))
        pq.init_db();self.send()
        self.assertEqual(self.user()['in_a_row'],1)

    def test_ai_finishing_after_gameover_corrects_series(self):
        self.add('tessa',status='playing')
        with pq.db() as con:con.execute("UPDATE users SET in_a_row=3 WHERE twitch_name='tessa'")
        pending=Future()
        with patch.object(engine._pool,'submit',return_value=pending):
            self.spectate('1','Stein',round_no=2)
            self.spectate('2','XxT3ssaxX',round_no=2)
            for sid in ('3','4','5'):self.spectate(sid,'Ally'+sid,round_no=2)
            self.spectate('1','Stein',round_no=2,phase='gameover')
            self.assertEqual(self.user()['in_a_row'],0)
            pending.set_result(.99)
            self.client.get('/api/state')
            self.assertEqual(self.user()['in_a_row'],4)
            self.assertEqual(self.user()['played_count'],1)
            self.client.get('/api/state');self.assertEqual(self.user()['in_a_row'],4)
