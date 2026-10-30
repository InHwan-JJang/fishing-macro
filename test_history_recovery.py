import tempfile
import unittest
from pathlib import Path

from fishing_history import History, Observer, now_kst
from history_recovery import recover_missing, dated_candidates, missing_runs, interpolate_recovered_times
from history_storage import load_records, save_csv
from history_view import make_rows, sort_rows


DAY = now_kst().date().isoformat()
DATE = now_kst().strftime('%Y년 %m월 %d일 목요일')


def line(sender, body):
    return f'[{sender}] [오후 1:00] {body}'


def catch(count, balance, owner='나', kind='fish', gold=10):
    body = {'fish': '낚시 성공!', 'pearl': '진주 발견!', 'auto': '자동어 출현!',
            'raid': '현무의 잔향을 마주쳤어요.'}[kind]
    text = line(owner, '@봇 낚시') + '\n' if owner else ''
    text += line('봇', f'@사용자 {body}\n오늘 낚시: {count} / 3000\n획득 골드: {gold}G\n보유 골드: {balance}G')
    card = {'fish': '[가자미] 10cm\n등급: 일반\n경험치: 5EXP',
            'pearl': '보유 진주가 +1 증가했어요.', 'auto': '', 'raid': '잔향 피해: 10'}[kind]
    if card:
        text += '\n' + line('봇', card)
    return text


def seed(history, count, balance, **extra):
    history.update(history.new_id(), dict(kind='fish', today=count, balance=balance, gold=10,
                                         user='나', time=DAY + 'T13:00:00+09:00', **extra))


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.h = History()
        seed(self.h, 776, 100)
        seed(self.h, 778, 120)

    def run_recovery(self, chat):
        recover_missing(self.h, chat, '나', '봇')
        return [r for r in self.h.snapshot() if r.get('recovered')]

    def test_recovery_time_is_midpoint_and_persists(self):
        self.h.records[1]['time'] = DAY + 'T14:50:10+09:00'
        self.h.records[2]['time'] = DAY + 'T14:50:20+09:00'
        rows = self.run_recovery(DATE + '\n' + catch(777, 110))
        self.assertEqual(rows[0]['time'], DAY + 'T14:50:15+09:00')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path = Path(folder) / 'history.csv'
            save_csv(path, self.h.snapshot())
            loaded = load_records(path)
            self.assertEqual([r['today'] for r in make_rows(loaded, '전체')], [778, 777, 776])
            self.assertEqual([r['today'] for r in sort_rows(make_rows(loaded, '전체'), 'time', 1)], [776, 777, 778])

    def test_consecutive_recovery_times_evenly_spaced_across_minute(self):
        self.h.records[1]['time'] = DAY + 'T14:50:58+09:00'
        self.h.records[2].update(today=780, time=DAY + 'T14:51:06+09:00')
        rows = self.run_recovery(DATE + '\n' + '\n'.join(catch(n, 110) for n in (777, 778, 779)))
        self.assertEqual([r['time'] for r in sorted(rows, key=lambda r: r['today'])],
                         [DAY + 'T14:51:00+09:00', DAY + 'T14:51:02+09:00', DAY + 'T14:51:04+09:00'])

    def test_fractional_midpoint_sorts_in_both_directions(self):
        self.h.records[1]['time'] = DAY + 'T14:50:10+09:00'
        self.h.records[2]['time'] = DAY + 'T14:50:11+09:00'
        rows = self.run_recovery(DATE + '\n' + catch(777, 110))
        self.assertEqual(rows[0]['time'], DAY + 'T14:50:10.500000+09:00')
        view = make_rows(self.h.snapshot(), '전체')
        self.assertEqual([r['today'] for r in sort_rows(view, 'time', 1)], [776, 777, 778])
        self.assertEqual([r['today'] for r in sort_rows(view, 'time', 2)], [778, 777, 776])

    def test_missing_or_ambiguous_neighbor_keeps_original_time(self):
        candidate = dict(kind='fish', today=777, user='나', time=DAY + 'T13:00:00+09:00')
        for records in ([self.h.records[2]], [self.h.records[1]],
                        [self.h.records[1], dict(self.h.records[1]), self.h.records[2]],
                        [dict(self.h.records[1], user='친구'), self.h.records[2]],
                        [dict(self.h.records[1], phase='extra'), self.h.records[2]]):
            row = dict(candidate)
            interpolate_recovered_times([row], records, '나', DAY)
            self.assertEqual(row['time'], candidate['time'])

    def test_equal_or_reversed_anchor_times_are_not_changed(self):
        for second in ('00', '10'):
            self.h.records[1]['time'] = DAY + f'T13:00:{second}+09:00'
            rows = self.run_recovery(DATE + '\n' + catch(777, 110))
            self.assertEqual(rows[0]['time'], DAY + 'T13:00:00+09:00')
            self.setUp()

    def test_single_duplicate_count_selects_gold_chain(self):
        rows = self.run_recovery(DATE + '\n' + catch(777, 510, '친구') + '\n' + catch(777, 110))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['balance'], 110)
        self.assertFalse(rows[0]['individual_session'])
        self.assertEqual(rows[0]['species'], '가자미')
        self.assertFalse(missing_runs(self.h.snapshot(), '나', DAY))
        self.assertEqual(len(self.run_recovery(DATE + '\n' + catch(777, 110))), 1)

    def test_unique_counter_ignores_balance_but_not_explicit_foreign_owner(self):
        for owner in ('나', '친구', ''):
            with self.subTest(owner=owner):
                self.setUp()
                rows = self.run_recovery(DATE + '\n' + catch(777, 999, owner))
                if owner == '친구':
                    self.assertEqual(rows, [])
                    continue
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['balance'], 999)

    def test_unique_consecutive_counters_need_no_gold_fields(self):
        self.h = History()
        seed(self.h, 776, 100)
        seed(self.h, 779, 120)
        chat = DATE + '\n' + catch(777, 999) + '\n' + catch(778, 999)
        chat = chat.replace('\n획득 골드: 10G', '').replace('\n보유 골드: 999G', '')
        rows = self.run_recovery(chat)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r['individual_session'] and 'balance' not in r for r in rows))

    def test_multiple_candidates_without_gold_match_remain_missing(self):
        rows = self.run_recovery(DATE + '\n' + catch(777, 999) + '\n' + catch(777, 888, '친구'))
        self.assertEqual(rows, [])

    def test_dates_required_and_past_dates_rejected(self):
        self.assertEqual(self.run_recovery(catch(777, 110)), [])
        self.h.request_recovery()
        self.assertEqual(self.run_recovery('2020년 1월 1일 수요일\n' + catch(777, 110)), [])
        self.h.request_recovery()
        self.assertEqual(len(self.run_recovery(DATE + '\n' + catch(777, 110))), 1)

    def test_automatic_one_shot_manual_retry(self):
        self.run_recovery('')
        self.assertEqual(self.run_recovery(DATE + '\n' + catch(777, 110)), [])
        self.h.request_recovery()
        self.assertEqual(len(self.run_recovery(DATE + '\n' + catch(777, 110))), 1)
        self.assertFalse(self.h.recovery_pending)

    def test_consecutive_chain_is_individual_and_persists(self):
        self.h = History()
        seed(self.h, 776, 100)
        seed(self.h, 780, 140)
        chat = DATE + '\n' + '\n'.join(catch(n, 100 + (n-776)*10) for n in (777, 778, 779))
        rows = self.run_recovery(chat)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r['individual_session'] for r in rows))
        self.assertEqual(len(make_rows(self.h.snapshot(), '개별 세션')), 3)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path = Path(folder) / 'history.csv'
            save_csv(path, rows)
            self.assertTrue(all(r['individual_session'] and r['recovered'] for r in load_records(path)))

    def test_unique_orphan_can_be_recovered(self):
        rows = self.run_recovery(DATE + '\n' + catch(777, 110, owner=''))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['user'], '나')

    def test_special_kinds(self):
        for kind in ('pearl', 'auto', 'raid'):
            with self.subTest(kind=kind):
                self.setUp()
                rows = self.run_recovery(DATE + '\n' + catch(777, 110, kind=kind))
                self.assertEqual(rows[0]['kind'], kind)

    def test_auto_and_final_raid_inferred_per_owner(self):
        chat = DATE + '\n' + catch(2999, 110) + '\n' + line('나', '@봇 낚시') + '\n' + line('봇', '@사용자 자동어 출현!')
        rows = dated_candidates(chat, '나', '봇', DAY)
        self.assertEqual(rows[-1]['today'], 3000)
        chat = chat.replace('자동어 출현!', '현무의 잔향을 마주쳤어요.\n잔향 보상: 10G')
        self.assertEqual(dated_candidates(chat, '나', '봇', DAY)[-1]['today'], 3000)

    def test_observer_waits_for_next_fishing_capture(self):
        obs = Observer(self.h, '나')
        chat = DATE + '\n' + catch(777, 110)
        obs.baseline(chat)
        self.h.request_recovery()
        obs.observe(chat)
        self.assertTrue(self.h.recovery_pending)
        obs.observe(chat + '\n' + catch(779, 130))
        self.assertFalse(self.h.recovery_pending)
        self.assertTrue(any(r.get('recovered') for r in self.h.snapshot()))

    def test_ambiguous_gold_not_added(self):
        self.assertEqual(self.run_recovery(DATE + '\n' + catch(777, 110) + '\n' +
                                          catch(777, 110, owner='')), [])

    def test_extra_counts_do_not_create_daily_gaps(self):
        seed(self.h, 999, 0, phase='extra')
        self.assertEqual(missing_runs(self.h.snapshot(), '나', DAY), [(777, 777)])

    def test_bonus_is_included_in_balance_chain(self):
        self.h.records[2].update(balance=1120, bonus=1000)
        self.assertEqual(len(self.run_recovery(DATE + '\n' + catch(777, 110))), 1)

    def test_zero_gold_pearl_in_consecutive_gap(self):
        self.h = History()
        seed(self.h, 776, 100)
        seed(self.h, 779, 120)
        pearl = line('나', '@봇 낚시') + '\n' + line('봇', '@사용자 진주 발견!\n오늘 낚시: 778 / 3000\n보유 진주가 +1 증가했어요.')
        rows = self.run_recovery(DATE + '\n' + catch(777, 110) + '\n' + pearl)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r['individual_session'] for r in rows))

    def test_day_separator_cannot_supply_wrong_day_card(self):
        chat = DATE + '\n' + catch(777, 110).split('\n[봇] [오후 1:00] [가자미]')[0]
        chat += '\n2099년 1월 1일 목요일\n' + line('봇', '[다른날] 10cm\n등급: 일반')
        self.assertEqual(self.run_recovery(chat), [])

    def test_window_filters_totals_and_only_shows_nonzero_warnings(self):
        import tkinter as tk
        from history_window import HistoryWindow
        root = tk.Tk()
        root.withdraw()
        h = History()
        seed(h, 1, 10, species='가자미', exp=5, grade='일반')
        seed(h, 2, 20, individual_session=True)
        window = HistoryWindow(root, h)
        try:
            window.refresh()
            self.assertIn('어종 미확인 1건', window.warning.cget('text'))
            self.assertEqual(str(window.warning.cget('foreground')), '#c62828')
            window.exclude_individual.set(True)
            window.refresh()
            self.assertEqual(window.warning.cget('text'), '')
            self.assertEqual(window.warning.winfo_manager(), '')
            self.assertEqual(window.revenue.cget('text'), '총 판매수익 10G')
            self.assertEqual(len(window.tree.get_children()), 1)
            window.window.geometry('1800x700')
            root.update()
            self.assertGreater(int(window.detail.cget('wraplength')), 1700)
            window.request_recovery()
            self.assertTrue(h.recovery_pending)
            self.assertTrue(window.recovery_button.instate(['disabled']))
        finally:
            window.close()
            root.destroy()


if __name__ == '__main__':
    unittest.main()
