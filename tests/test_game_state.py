from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from studio import game_db,game_state


class GameStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'history.sqlite3'
        game_db.migrate(self.path);self.store=game_db.GameStore(self.path)
    def tearDown(self):self.tmp.cleanup()

    def test_restart_and_select_are_persistent_no_absence_penalty(self):
        initial=self.store.read()
        self.store.create('second','另一个故事');self.store.select('second')
        game_db.migrate(self.path);other=game_db.GameStore(self.path)
        self.assertEqual(other.session()['profile_id'],'second')
        self.assertEqual(other.read('default'),initial)
        self.assertEqual(other.read()['stats'],initial['stats'])

    def test_ids_names_and_limits(self):
        for identity in ('../escape','C:\\bad','a/b','',True):
            with self.subTest(identity=identity),self.assertRaises(ValueError):self.store.create(identity,'name')
        with self.assertRaises(ValueError):self.store.create('ok',' ')
        with self.assertRaises(ValueError):self.store.select('missing')
        with self.assertRaises(ValueError):self.store.create('default','duplicate')

    def test_rule_limits_clamp_and_milestones(self):
        state=game_state.new_state();state['stats']['mood']=99;state['stats']['energy']=0
        value,actual=game_state.apply_delta(state,{'mood':20,'energy':-20})
        self.assertEqual(value['stats']['mood'],100);self.assertEqual(actual,{'mood':1,'energy':0})
        self.assertEqual(value['relationship_stage'],'acquaintance')
        value,_=game_state.apply_delta(value,{},milestone='introduced')
        self.assertEqual(value['relationship_stage'],'familiar')
        value,_=game_state.apply_delta(value,{},milestone='lasting_bond')
        self.assertEqual(value['relationship_stage'],'familiar')
        for delta in ({'affection':True},{'mood':1.5},{'energy':21},{'affection':50},{'sql':'DROP TABLE'}):
            with self.subTest(delta=delta),self.assertRaises(ValueError):game_state.apply_delta(state,delta)

    def test_atomic_daily_caps_and_new_day(self):
        now=datetime(2026,10,15,10)
        first=self.store.commit_effect('default',0,'local_test','once',{'affection':4},now=now)
        second=self.store.commit_effect('default',1,'local_test','twice',{'affection':4},now=now)
        self.assertEqual(first['stats']['affection'],29);self.assertEqual(second['stats']['affection'],30)
        tomorrow=self.store.commit_effect('default',2,'local_test','tomorrow',{'affection':4},now=now+timedelta(days=1))
        self.assertEqual(tomorrow['stats']['affection'],34)
        self.assertEqual(game_db.GameStore(self.path).read(),tomorrow)

    def test_idempotent_concurrent_commit(self):
        def commit(_):return self.store.commit_effect('default',0,'local_test','same_choice',{'trust':1})
        with ThreadPoolExecutor(max_workers=4) as workers:results=list(workers.map(commit,range(10)))
        self.assertTrue(all(value==results[0] for value in results))
        self.assertEqual(self.store.read()['stats']['trust'],31)
        with game_db.connect(self.path) as db:self.assertEqual(db.execute('SELECT count(*) FROM game_journal').fetchone()[0],1)
        with self.assertRaises(ValueError):self.store.commit_effect('default',0,'local_test','same_choice',{'trust':2})
        with self.assertRaises(ValueError):self.store.commit_effect('default',0,'local_test','same_choice',{'trust':True})

    def test_stale_revision_and_invalid_delta_never_write(self):
        before=self.store.read()
        for revision,delta in ((4,{'mood':1}),(True,{}),(0,{'energy':999}),(0,{'mood':False})):
            with self.subTest(revision=revision,delta=delta),self.assertRaises(ValueError):
                self.store.commit_effect('default',revision,'local_test','bad',delta)
        self.assertEqual(self.store.read(),before)
        with game_db.connect(self.path) as db:self.assertEqual(db.execute('SELECT count(*) FROM game_journal').fetchone()[0],0)

    def test_journal_failure_rolls_back_state(self):
        before=self.store.read()
        with game_db.connect(self.path) as db:
            db.execute("CREATE TRIGGER fail_journal BEFORE INSERT ON game_journal BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.DatabaseError):self.store.commit_effect('default',0,'local_test','bad',{'mood':1})
        self.assertEqual(self.store.read(),before)

    def test_schema_rejects_bool_float_unknown_fields_and_paths(self):
        for key,value in (('revision',False),('stats',{'affection':1.5}),('relationship_stage',[]),('profile_id','../x'),('toggles',{'proactive_events':0,'touch_interaction':0})):
            state=game_state.new_state();state[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):game_state.validate_state(state)
        state=game_state.new_state();state['api_key']='not-valid'
        with self.assertRaises(ValueError):game_state.validate_state(state)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'history.sqlite3'
        with game_db.connect(self.path) as db:
            db.execute('CREATE TABLE messages(id INTEGER PRIMARY KEY,created_at TEXT,role TEXT,content TEXT,source TEXT)')
            db.execute("INSERT INTO messages VALUES(7,'old-date','assistant','private old reply','demo')")
            db.execute('CREATE TABLE memories(id INTEGER PRIMARY KEY,created_at TEXT,content TEXT,enabled INTEGER)')
            db.execute("INSERT INTO memories VALUES(8,'old-date','private old memory',0)")
    def tearDown(self):self.tmp.cleanup()

    def test_old_db_backup_and_idempotent_migration_preserve_rows(self):
        backup=game_db.migrate(self.path)
        self.assertTrue(backup.is_file())
        with game_db.connect(backup) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT content FROM messages WHERE id=7').fetchone()[0],'private old reply')
        self.assertIsNone(game_db.migrate(self.path))
        with game_db.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT profile_id,content FROM messages WHERE id=7').fetchone()[:],('default','private old reply'))
            self.assertEqual(db.execute('SELECT enabled FROM memories WHERE id=8').fetchone()[0],0)
            self.assertEqual(db.execute('PRAGMA foreign_keys').fetchone()[0],1)
        self.assertEqual(len(list(backup.parent.glob('history_*.sqlite3'))),1)

    def test_failed_migration_rolls_back_ddl_and_keeps_backup(self):
        with patch.object(game_state,'new_state',side_effect=RuntimeError('simulated failure')):
            with self.assertRaises(RuntimeError):game_db.migrate(self.path)
        with game_db.connect(self.path) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name='game_state'").fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM messages').fetchone()[0],1)
        self.assertEqual(len(list((self.path.parent/'backups').glob('*.sqlite3'))),1)

    def test_future_db_is_refused_unchanged(self):
        with game_db.connect(self.path) as db:db.execute('PRAGMA user_version=999')
        with self.assertRaises(ValueError):game_db.migrate(self.path)
        with game_db.connect(self.path) as db:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],999)


if __name__=='__main__':unittest.main()
