from datetime import datetime, timedelta
import unittest
from unittest.mock import patch
import test_gsi as gsi_tests
import app as pq
import steam_links


class SteamAccountsTest(unittest.TestCase):
    setUp = gsi_tests.GSITest.setUp
    tearDown = gsi_tests.GSITest.tearDown
    add = gsi_tests.GSITest.add
    send = gsi_tests.GSITest.send
    packet = gsi_tests.GSITest.packet
    spectate = gsi_tests.GSITest.spectate
    user = gsi_tests.GSITest.user

    def link(self,name,sid,steam_name='Account'):
        response=self.client.post('/api/link-steam',json={'twitch_name':name,'steam_id':sid,'steam_name':steam_name})
        self.assertEqual(response.status_code,200)

    def ids(self,name='tessa'):
        with pq.db() as con:return {a['steam_id'] for a in steam_links.accounts(con,name)}

    def test_two_accounts_keep_both_links_and_detected_rows(self):
        self.add('tessa')
        self.link('tessa','2','Main');self.link('tessa','3','Alt')
        self.send(names={'2':'Main','3':'Alt'})
        self.assertEqual(self.ids(),{'2','3'})
        state=self.client.get('/api/state').json
        self.assertEqual({p['steam_id'] for p in state['detected_players'] if p['twitch_name']=='tessa'},{'2','3'})
        self.assertEqual(len(state['playing'][0]['steam_accounts']),2)
        self.assertEqual(self.user()['in_a_row'],1)
        self.assertEqual(self.user()['played_count'],1)

    def test_account_switch_between_matches_keeps_series(self):
        self.add('tessa');self.link('tessa','2');self.link('tessa','3')
        self.send(names={'2':'Main'});self.send(phase='gameover',names={'2':'Main'})
        self.send(names={'3':'Alt'});self.send(phase='gameover',names={'3':'Alt'})
        self.assertEqual(self.user()['in_a_row'],2)
        self.assertEqual(self.user()['played_count'],2)
        self.assertEqual(self.ids(),{'2','3'})

    def test_steam_account_cannot_belong_to_two_twitch_users(self):
        self.add('tessa');self.add('other');self.link('tessa','2');self.link('tessa','3')
        r=self.client.post('/api/link-steam',json={'twitch_name':'other','steam_id':'3'})
        self.assertEqual(r.status_code,409);self.assertEqual(self.ids(),{'2','3'})

    def test_pending_additional_account_does_not_replace_confirmed_account(self):
        self.add('tessa','2',status='playing')
        self.spectate('1','Stein');self.spectate('3','XxT3ssaxX')
        self.assertEqual(self.ids(),{'2','3'})
        self.client.post('/api/proposal',json={'steam_id':'3','action':'confirm'})
        with pq.db() as con:self.assertEqual({a['status'] for a in steam_links.accounts(con,'tessa')},{'confirmed'})

    def test_reject_additional_account_keeps_confirmed_main_and_count(self):
        self.add('tessa','2',status='playing')
        self.spectate('1','Stein');self.spectate('2','Main');self.spectate('3','XxT3ssaxX')
        self.client.post('/api/proposal',json={'steam_id':'3','action':'reject'})
        self.assertEqual(self.ids(),{'2'})
        self.assertEqual(self.user()['steam_id'],'2')
        self.assertEqual(self.user()['in_a_row'],1)
        self.assertEqual(self.user()['played_count'],1)

    def test_reject_first_counted_alias_keeps_match_if_other_confirmed_account_played(self):
        self.add('tessa','2',status='playing')
        self.spectate('1','Stein');self.spectate('3','XxT3ssaxX');self.spectate('2','Main')
        self.client.post('/api/proposal',json={'steam_id':'3','action':'reject'})
        self.assertEqual(self.user()['in_a_row'],1)
        self.assertEqual(self.user()['played_count'],1)
        with pq.db() as con:self.assertEqual(con.execute("SELECT steam_id FROM match_players WHERE twitch_name='tessa'").fetchone()[0],'2')

    def test_repeated_mapping_is_idempotent_and_display_name_preserved(self):
        self.client.get('/api/join',query_string={'user':'tessa','display':'Tessa ♥'})
        self.link('tessa','2');self.link('tessa','2','Renamed')
        self.assertEqual(self.ids(),{'2'});self.assertEqual(self.user()['display_name'],'Tessa ♥')

    def test_legacy_accounts_migrate_once_including_pending_status(self):
        self.add('tessa','2')
        with pq.db() as con:
            con.execute("INSERT INTO steam_proposals VALUES('2','tessa','Tessa',.95,'test','pending',?)",(pq.now_iso(),))
            con.execute('DROP TABLE steam_accounts')
        pq.init_db();pq.init_db()
        self.assertEqual(self.ids(),{'2'})
        with pq.db() as con:self.assertEqual(steam_links.accounts(con,'tessa')[0]['status'],'pending')

    def test_recent_removed_users_are_unique_and_expire_after_twelve_hours(self):
        fixed=datetime(2026,10,11,12,0,0)
        for name,hours in [('recent',11),('old',13),('boundary',12),('active',24)]:
            self.add(name)
            with pq.db() as con:
                con.execute('UPDATE queue SET joined_at=?,status=? WHERE twitch_name=?',((fixed-timedelta(hours=hours)).isoformat(), 'waiting' if name=='active' else 'done',name))
        with pq.db() as con:
            con.execute("INSERT INTO queue(twitch_name,status,joined_at) VALUES('recent','done',?)",((fixed-timedelta(hours=2)).isoformat(),))
        with patch.object(pq,'now_iso',return_value=fixed.isoformat()):
            users=self.client.get('/api/state').json['link_users']
        names=[u['twitch_name'] for u in users]
        self.assertEqual(set(names),{'recent','boundary','active'})
        self.assertEqual(names.count('recent'),1)
        self.assertEqual(next(u for u in users if u['twitch_name']=='recent')['status'],'done')

    def test_recent_removed_user_can_be_manually_linked(self):
        self.add('tessa');self.client.get('/api/leave?user=tessa')
        self.assertIn('tessa',[u['twitch_name'] for u in self.client.get('/api/state').json['link_users']])
        self.link('tessa','2');self.assertEqual(self.ids(),{'2'})
