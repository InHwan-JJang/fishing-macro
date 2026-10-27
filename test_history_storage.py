import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from fishing_history import History
from history_storage import load_records, delete_past_files

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'history' / 'session.csv'

    def test_each_update_is_durable_and_enrichment_replaces_row(self):
        history = History(self.path)
        history.update(1, dict(kind='fish', gold=535, exp=30, today=2850, limit=3000))
        self.assertEqual(load_records(self.path)[0]['gold'],535)
        history.update(1, dict(species='파괴된 전직 장비', grade='레어', enhancement=9))
        records = load_records(self.path)
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['enhancement'],9)
        history.update(2, dict(kind='fish', species='올챙이', grade='일반', gold=12, exp=4, size=8.2))
        loaded = History.load(self.path)
        self.assertEqual(len(loaded.snapshot()),2)
        self.assertEqual(loaded.snapshot()[1]['exp'],4)
        self.assertIsNone(loaded.path)
        self.assertFalse(self.path.with_suffix('.csv.tmp').exists())

    def test_failed_save_retains_previous_file_and_retries(self):
        history=History(self.path)
        history.update(1,dict(kind='fish',gold=10))
        with patch('history_storage.os.replace', side_effect=PermissionError('locked')):
            history.update(1,dict(gold=20))
        self.assertIsNotNone(history.save_error)
        self.assertEqual(load_records(self.path)[0]['gold'],10)
        self.assertTrue(history.save())
        self.assertEqual(load_records(self.path)[0]['gold'],20)

    def test_legacy_json_and_csv_without_id(self):
        path=self.root/'old.json'
        path.write_text('[{"time":"2026-10-28T01:00:00+09:00","kind":"fish","id":7,"collection":true}]',encoding='utf-8')
        self.assertTrue(History.load(path).snapshot()[0]['collection'])
        path=self.root/'old.csv'
        path.write_text('time,kind,gold\n2026-10-28T01:00:00+09:00,fish,12\n',encoding='utf-8')
        self.assertEqual(load_records(path)[0]['id'],1)

    def test_special_effect_csv_roundtrip(self):
        history=History(self.path)
        history.update(1,dict(kind='fish', today=1, frost_remaining=20, fire_remaining=10))
        row=History.load(self.path).snapshot()[0]
        self.assertEqual(row['frost_remaining'],20)
        self.assertEqual(row['fire_remaining'],10)
        self.assertTrue(row['frost_granted'])
        self.assertFalse(row['any_lucky'])

    def test_invalid_load_rejected(self):
        path=self.root/'bad.csv'
        path.write_text('time,kind,size\n2026-10-28,fish,nan\n',encoding='utf-8')
        with self.assertRaises(ValueError): History.load(path)

    def test_delete_validates_all_and_protects_current(self):
        history=History(self.path); history.update(1,dict(kind='fish'))
        past=self.path.parent/'past.csv'; past.write_bytes(self.path.read_bytes())
        with self.assertRaises(ValueError): delete_past_files([past,self.path],self.path.parent,self.path)
        self.assertTrue(past.exists())
        outside=self.root/'outside.csv'; outside.write_bytes(past.read_bytes())
        with self.assertRaises(ValueError): delete_past_files([outside],self.path.parent,self.path)
        delete_past_files([past],self.path.parent,self.path)
        self.assertFalse(past.exists()); self.assertTrue(self.path.exists())

    def test_load_and_start_guard(self):
        from fishing_macro import App
        app=App.__new__(App); app.job=object(); app._dialog_open=False
        with patch('fishing_macro.filedialog.askopenfilename') as dialog:
            app.load_history(); dialog.assert_not_called()
        app.job=None; app._dialog_open=True
        app._settings=Mock()
        app.start(); app._settings.assert_not_called()

    def test_import_does_not_modify_live_records(self):
        import tkinter as tk
        from history_window import HistoryWindow
        root=tk.Tk(); root.withdraw()
        history=History(self.path); history.update(1,dict(kind='fish',species='장비',enhancement=9))
        loaded=History.load(self.path)
        busy=[False]
        window=HistoryWindow(root,history,is_busy=lambda:busy[0]); window.window.withdraw()
        try:
            window.set_history(loaded,str(self.path))
            history.update(2,dict(kind='pearl',pearls=1))
            self.assertEqual(len(window.history.snapshot()),1)
            window.show_current()
            self.assertEqual(len(window.history.snapshot()),2)
            busy[0]=True
            window.window.after_cancel(window.timer); window.poll()
            self.assertEqual(str(window.load_button['state']),'disabled')
        finally:
            window.close(); root.destroy()

class DailyStorageTests(unittest.TestCase):
    setUp = StorageTests.setUp
    def daily(self):
        from fishing_history import DailyHistory
        return DailyHistory(self.root/'fishing-macro-history', self.root/'history')

    def test_restart_continues_daily_records(self):
        h=self.daily(); key=h.new_id(); h.update(key,dict(kind='fish',gold=100))
        resumed=self.daily()
        self.assertEqual(len(resumed.snapshot()),1)
        next_key=resumed.new_id(); self.assertGreater(next_key,key)
        resumed.update(next_key,dict(kind='fish',gold=20))
        self.assertEqual(sum(r['gold'] for r in self.daily().snapshot()),120)

    def test_midnight_switch_and_late_previous_card(self):
        from datetime import datetime
        from fishing_history import KST
        with patch('fishing_history.now_kst',return_value=datetime(2026,10,28,23,59,59,tzinfo=KST)):
            h=self.daily(); old=h.new_id(); h.update(old,dict(kind='fish',gold=10))
        with patch('fishing_history.now_kst',return_value=datetime(2026,10,29,0,0,5,tzinfo=KST)):
            h.ensure_day()
            self.assertEqual(h.snapshot(),[])
            new=h.new_id(); h.update(new,dict(kind='fish',gold=20))
            h.update(old,dict(species='가자미'))
            self.assertEqual(len(h.snapshot()),1)
            self.assertEqual(h.snapshot()[0]['gold'],20)
            previous=load_records(h.directory/'2026-10-28.csv')
            self.assertEqual(previous[0]['species'],'가자미')
            self.assertEqual(len(self.daily().snapshot()),1)

    def test_import_old_sessions_once_and_preserve_originals(self):
        from fishing_history import now_kst
        for name, count in [('one.csv',1),('two.csv',2)]:
            h=History(self.root/'history'/name)
            h.update(1,dict(kind='fish',today=count,user='나',gold=10))
        h=self.daily()
        self.assertEqual(len(h.snapshot()),2)
        self.assertEqual(len(self.daily().snapshot()),2)
        self.assertTrue((self.root/'history'/'one.csv').exists())
        self.assertEqual(h.path.name,now_kst().date().isoformat()+'.csv')

    def test_invalid_daily_file_is_not_overwritten(self):
        from fishing_history import now_kst
        folder=self.root/'fishing-macro-history'; folder.mkdir()
        path=folder/(now_kst().date().isoformat()+'.csv')
        path.write_text('broken',encoding='utf-8')
        with self.assertRaises(ValueError): self.daily()
        self.assertEqual(path.read_text(encoding='utf-8'),'broken')


if __name__=='__main__': unittest.main()
