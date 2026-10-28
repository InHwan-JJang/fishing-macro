import unittest
from fishing_history import History, parse_details, sale_percent
from history_view import make_rows, sort_rows, display_row, COLUMNS, MODES


def record(key, **fields):
    return dict(id=key, user='나', time=f'2026-10-28T12:00:{key:02d}+09:00',
                kind='fish', species='가자미', grade='일반', today=key, limit=3000, **fields)


class LuckTests(unittest.TestCase):
    def test_capybara_grants_ten_future_lucky_catches(self):
        history = History()
        for key in range(1,13):
            data = record(key)
            if key == 1:
                data['species'] = '카피바라'
            if key <= 10:
                data['luck_remaining'] = 11-key
            history.update(key,data)
        rows = history.snapshot()
        self.assertTrue(rows[0]['luck_granted'])
        self.assertFalse(rows[0]['lucky'])
        self.assertEqual([r['today'] for r in rows if r['lucky']], list(range(2,12)))
        self.assertFalse(rows[-1]['lucky'])

    def test_grant_is_recomputed_when_card_arrives_later(self):
        history = History()
        history.update(1,record(1,luck_remaining=10))
        self.assertFalse(history.snapshot()[0]['lucky'])
        history.update(1,dict(species='카피바라',size=90.2))
        self.assertFalse(history.snapshot()[0]['lucky'])

    def test_partial_initial_balance_is_consumption(self):
        for remaining in (1, 3, 7, 9, 19):
            history = History()
            history.update(1, record(1, luck_remaining=remaining))
            row = history.snapshot()[0]
            self.assertTrue(row['lucky'])
            self.assertFalse(row['luck_granted'])
            self.assertEqual(make_rows([row], '모두보기')[0]['extra'],
                             f'행운 소비 - 남은 행운 {remaining}회')

    def test_full_grant_and_consumed_multiple_of_ten(self):
        history = History()
        history.update(1, record(1, luck_remaining=20))
        history.update(2, record(2, luck_remaining=10))
        history.records[2]['today'] = 11
        rows = history.snapshot()
        self.assertTrue(rows[0]['luck_granted'])
        self.assertFalse(rows[0]['lucky'])
        self.assertTrue(rows[1]['lucky'])
        self.assertFalse(rows[1]['luck_granted'])

    def test_special_effects_are_independent_and_include_final_cast(self):
        history = History()
        history.update(1, record(1, frost_remaining=2, fire_remaining=1, luck_remaining=3))
        history.update(2, record(2, frost_remaining=1, luck_remaining=2))
        history.update(3, record(3, luck_remaining=1))
        history.update(4, record(4))
        rows = history.snapshot()
        self.assertEqual([r['fire_active'] for r in rows], [True, True, False, False])
        self.assertEqual([r['frost_active'] for r in rows], [True, True, True, False])
        detail = make_rows(rows, '시간순')[-1]['extra']
        self.assertIn('특수 행운(만년서리의 숨결)', detail)
        self.assertIn('특수 행운(만년화리의 숨결)', detail)
        self.assertEqual(len(make_rows(rows, '행운')), 4)

    def test_parse_spaces(self):
        self.assertEqual(parse_details('행운 : 남은 10회 낚시')['luck_remaining'], 10)

    def test_final_lucky_catch_and_duplicate_snapshots(self):
        history = History()
        for key, left in ((1, 2), (2, 1), (3, None), (4, None)):
            data = record(key)
            if left is not None:
                data['luck_remaining'] = left
            history.update(key, data)
        expected = [True, True, True, False]
        self.assertEqual([r['lucky'] for r in history.snapshot()], expected)
        self.assertEqual([r['lucky'] for r in history.snapshot()], expected)
        self.assertEqual(len(make_rows(history.snapshot(), '행운')), 3)

    def test_user_day_and_missing_catches(self):
        history = History()
        history.update(1, record(1, luck_remaining=2))
        other = record(2); other['user'] = '친구'
        history.update(2, other)
        history.update(3, record(3))  # One missing catch, final charge still used.
        tomorrow = record(4); tomorrow['time'] = '2026-10-29T12:00:00+09:00'
        history.update(4, tomorrow)
        self.assertEqual([r['lucky'] for r in history.snapshot()], [True, False, True, False])

    def test_new_buff_and_auto_do_not_consume_twice(self):
        history = History()
        history.update(1, record(1, luck_remaining=1))
        auto = record(2); auto['kind'] = 'auto'
        history.update(2, auto)
        data = record(3, luck_remaining=10); data['today'] = 2
        history.update(3, data)
        final = record(4); final['today'] = 12
        history.update(4, final)
        self.assertEqual([r['lucky'] for r in history.snapshot()], [True, False, False, True])


class ViewTests(unittest.TestCase):
    def test_equipment_display_and_totals(self):
        data=record(1,gold=535,exp=30,enhancement=9)
        data.update(species='파괴된 전직 장비',grade='레어')
        row=make_rows([data],'모두보기')[0]
        self.assertEqual((row['count'],row['gold'],row['exp']),(1,535,30))
        self.assertEqual(row['extra'],'9강')
        self.assertEqual(display_row(row)[COLUMNS.index('size')],'—')

    def test_zero_percent_and_explicit_multiplier(self):
        data = record(1); data['today'] = 3001
        self.assertEqual(sale_percent(data), 0)
        data.update(today=600, multiplier=150)
        self.assertEqual(sale_percent(data), 150)
        data['multiplier'] = 0
        self.assertEqual(sale_percent(data), 0)

    def test_all_view_keeps_latest_metadata_and_totals(self):
        first = record(1, size=12.0, gold=10, exp=3, multiplier=150)
        last = record(2, size=37.4, gold=20, exp=5, multiplier=120, lucky=True)
        rows = make_rows([first, last], '모두보기')
        row = rows[0]
        self.assertEqual((row['count'], row['gold'], row['exp'], row['size'], row['band']), (2,30,8,37.4,120))
        self.assertEqual(display_row(row)[COLUMNS.index('today')], '2 / 3,000')
        self.assertNotIn('최근 포획', row['extra'])
        self.assertNotIn('낚은 수 ↑', MODES)

    def test_numeric_sort_and_default_restore(self):
        a = record(1, gold=100, size=3740); b = record(2, gold=9, size=24670)
        rows = make_rows([a,b], '시간순')
        self.assertEqual([r['gold'] for r in sort_rows(rows,'gold',1)], [9,100])
        self.assertEqual([r['size'] for r in sort_rows(rows,'size',2)], [24670,3740])
        self.assertEqual(sort_rows(rows,'gold',0), rows)

    def test_grade_sort_and_unknown_last(self):
        a=record(1); b=record(2); b['grade']='신화'
        c=record(3); c.pop('grade')
        rows=make_rows([a,b,c],'시간순')
        self.assertEqual([r['grade'] for r in sort_rows(rows,'grade',1)], ['일반','신화',''])
        self.assertEqual([r['grade'] for r in sort_rows(rows,'grade',2)], ['신화','일반',''])

    def test_band_groups_remain_separate(self):
        a=record(1,gold=10,multiplier=150); b=record(2,gold=20,multiplier=0)
        rows=make_rows([a,b],'구간별')
        self.assertEqual([r['band'] for r in rows], [150,0])
        self.assertTrue(all(r['time'] and r['size'] is None and r['extra'] for r in rows))


class WindowTests(unittest.TestCase):
    def test_grade_filters_summary_and_can_restore_all(self):
        import tkinter as tk
        from history_window import HistoryWindow
        root=tk.Tk(); root.withdraw()
        history=History()
        history.update(1,record(1,gold=10,exp=2))
        rare=record(2,gold=100,exp=20); rare['grade']='레어'
        history.update(2,rare)
        pearl=record(3,pearls=1); pearl.update(kind='pearl'); pearl.pop('grade')
        history.update(3,pearl)
        window=HistoryWindow(root,history); window.window.withdraw()
        try:
            window.grade.set('레어'); window.refresh()
            self.assertEqual(window.revenue.cget('text'),'총 판매수익 100G')
            self.assertIn('물고기 1마리',window.summary.cget('text'))
            self.assertIn('20 EXP',window.summary.cget('text'))
            self.assertIn('진주 +0개',window.summary.cget('text'))
            self.assertNotIn('일반',window.detail.cget('text'))
            window.grade.set('전체'); window.refresh()
            self.assertEqual(window.revenue.cget('text'),'총 판매수익 110G')
            self.assertIn('22 EXP',window.summary.cget('text'))
            window.grade.set('신화'); window.refresh()
            self.assertIn('물고기 0마리',window.summary.cget('text'))
        finally:
            window.close(); root.destroy()

    def test_scaled_table_rows_fit_font(self):
        import tkinter as tk
        from history_window import HistoryWindow
        root=tk.Tk(); root.withdraw()
        try:
            for scale in (1.0,1.5,2.0,2.5):
                root.tk.call('tk','scaling',scale)
                window=HistoryWindow(root,History()); window.window.withdraw()
                try:
                    window.table_font.configure(size=18)
                    window._update_row_height()
                    height=int(window.table_style.lookup('History.Treeview','rowheight'))
                    self.assertGreaterEqual(height,window.table_font.metrics('linespace')+6)
                finally:
                    window.close()
        finally:
            root.destroy()

    def test_header_cycle_is_single_column_and_survives_refresh(self):
        import tkinter as tk
        from history_window import HistoryWindow
        root=tk.Tk(); root.withdraw()
        history=History(); history.update(1,record(1,gold=100,size=30))
        window=HistoryWindow(root,history); window.window.withdraw()
        try:
            self.assertEqual(window.tree['columns'], COLUMNS)
            window.toggle_sort('gold')
            self.assertEqual((window.sort_column,window.sort_direction), ('gold',1))
            window.refresh()
            self.assertEqual(window.sort_direction,1)
            window.toggle_sort('gold'); self.assertEqual(window.sort_direction,2)
            window.toggle_sort('gold'); self.assertIsNone(window.sort_column)
            window.toggle_sort('time'); window.toggle_sort('size')
            self.assertEqual((window.sort_column,window.sort_direction), ('size',1))
            self.assertNotIn('▲',window.tree.heading('time')['text'])
            for mode in MODES:
                window.mode.set(mode); window.refresh()
            self.assertIn('총 판매수익',window.revenue.cget('text'))
        finally:
            window.close(); root.destroy()


if __name__ == '__main__':
    unittest.main()
