import unittest
from fishing_history import History
from history_view import MODES, average_summaries, grade_probabilities, make_rows


def catch(key, **fields):
    return dict(id=key, time=f'2026-10-28T12:00:{key:02d}+09:00', kind='fish', user='나', species='개구리', **fields)


class StatisticsTests(unittest.TestCase):
    def test_exclude_extra_changes_average_not_records(self):
        rows = [catch(1, grade='일반', gold=100), catch(2, grade='레어', gold=300),
                catch(3, grade='일반', gold=0, phase='extra', multiplier=0)]
        self.assertIn('133.3G', average_summaries(rows, '어종')[0])
        self.assertIn('200.0G', average_summaries(rows, '어종', exclude_extra=True)[0])
        self.assertEqual(len(make_rows(rows, '전체')), 3)
        self.assertEqual(make_rows(rows, '전체')[0]['extra'], '—')
        self.assertIn('평균 —', average_summaries(rows[2:], '어종', exclude_extra=True)[0])

    def test_grade_ratios_use_catches_and_scope(self):
        rows = [catch(1, grade='일반', lucky=True), catch(2, grade='레어', collection=True),
                catch(3, grade='일반'), catch(4)]
        self.assertIn('일반 66.7%', grade_probabilities(rows, '어종')[0])
        self.assertIn('등급 미확인 1건 제외', grade_probabilities(rows, '전체')[0])
        self.assertIn('일반 100.0%', grade_probabilities(rows, '행운')[0])
        self.assertIn('레어 100.0%', grade_probabilities(rows, '도감')[0])
        for mode in ('진주', '자동어', '레이드'):
            self.assertEqual(grade_probabilities(rows, mode), [])
        self.assertIn('일반 —', grade_probabilities([], '전체')[0])

    def test_tab_order_and_window_average_toggle(self):
        import tkinter as tk
        from history_window import HistoryWindow
        self.assertEqual(MODES, ('전체','어종','구간','행운','진주','도감','자동어','레이드','개별 세션'))
        root=tk.Tk(); root.withdraw()
        history=History()
        history.update(1, catch(1, grade='일반', gold=100))
        history.update(2, catch(2, grade='일반', gold=0, phase='extra', multiplier=0))
        window=HistoryWindow(root,history); window.window.withdraw()
        try:
            window.tabs.select(MODES.index('어종')); window.change_tab()
            self.assertIn('50.0G', window.detail.cget('text'))
            before=window.tree.item(window.tree.get_children()[0], 'values')
            window.exclude_extra.set(True); window.refresh()
            self.assertIn('100.0G', window.detail.cget('text'))
            self.assertEqual(before, window.tree.item(window.tree.get_children()[0], 'values'))
        finally:
            window.close(); root.destroy()
