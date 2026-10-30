import unittest
from collections import deque

import fishing_macro as macro
from fishing_history import CatchCounters, History, Observer


def line(sender, body):
    return f'[{sender}] [오후 2:00] {body}'


def result(count, phase='daily'):
    label = '오늘 낚시' if phase == 'daily' else '추가 낚시'
    return f'@사용자 낚시 성공!\n획득 골드: 10G\n{label}: {count} / 4000'


class CounterOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.history = History()
        self.observer = Observer(self.history, '나')
        self.observer.baseline('')
        self.text = ''

    def append(self, sender, body):
        self.text += '\n' + line(sender, body)
        self.observer.observe(self.text)

    def catch(self, owner, count, species, phase='daily'):
        self.append(owner, '@봇 낚시')
        self.append('봇', result(count, phase))
        self.append('봇', f'[{species}] 10cm\n등급: 일반')

    def test_reordered_players_are_matched_by_next_count(self):
        self.catch('나', 1442, '내이전')
        self.catch('친구', 519, '친구이전')
        self.append('나', '@봇 낚시')
        self.append('친구', '@봇 낚시')
        self.append('봇', result(520))
        self.append('봇', result(1443))
        self.append('봇', '[친구물고기] 10cm')
        self.append('봇', '[내물고기] 10cm')
        rows = self.history.snapshot()
        self.assertEqual([(r['today'], r['species']) for r in rows], [(1442, '내이전'), (1443, '내물고기')])
        self.assertEqual(macro.my_replies(self.text, '나')[-1][1][1], 1443)
        self.assertEqual(macro.latest_reply_after_my_command(self.text, '나')[1], 1443)

    def test_foreign_result_without_command_is_discarded_with_its_card(self):
        for wrong in (520, 2000, 1442):
            with self.subTest(wrong=wrong):
                self.setUp()
                self.catch('나', 1442, '이전')
                self.append('나', '@봇 낚시')
                self.append('봇', result(wrong))
                self.append('봇', '[다른사람] 10cm')
                self.assertEqual(len(self.history.snapshot()), 1)
                self.assertIsNone(macro.latest_reply_after_my_command(self.text, '나'))
                self.append('봇', result(1443))
                self.append('봇', '[정상] 10cm')
                self.assertEqual([(r['today'], r['species']) for r in self.history.snapshot()], [(1442, '이전'), (1443, '정상')])

    def test_partial_header_is_removed_when_counter_arrives(self):
        self.catch('나', 1442, '이전')
        self.append('나', '@봇 낚시')
        self.append('봇', '@사용자 낚시 성공!\n획득 골드: 99G')
        self.text += '\n오늘 낚시: 520 / 4000'
        self.observer.observe(self.text)
        self.append('봇', '[다른사람] 10cm')
        self.assertEqual(len(self.history.snapshot()), 1)
        self.assertEqual(self.observer.today, 1442)

    def test_extra_phase_and_auto_do_not_break_counter(self):
        self.catch('나', 1442, '일반')
        self.append('나', '@봇 낚시')
        self.append('봇', '@사용자 자동어 출현!')
        self.catch('나', 1443, '해제후')
        self.catch('나', 1, '추가첫번째', 'extra')
        self.catch('나', 2, '추가두번째', 'extra')
        self.assertEqual([r.get('species') for r in self.history.snapshot() if r['kind'] == 'fish'],
                         ['일반', '해제후', '추가첫번째', '추가두번째'])

    def test_same_next_count_is_ambiguous_and_day_resets(self):
        counters = CatchCounters()
        for owner in ('나', '친구'):
            counters.remember(owner, {'today': 10, 'kind': 'fish'}, '2026-10-30')
        pending = deque([('나', '낚시', 1), ('친구', '낚시', 2)])
        self.assertIsNone(counters.take(pending, {'today': 11}, '2026-10-30'))
        self.assertEqual(len(pending), 2)
        self.assertTrue(counters.accepts('나', {'today': 1}, '2026-10-31'))

    def test_foreign_limit_does_not_trigger_completion(self):
        self.catch('나', 1442, '이전')
        self.append('나', '@봇 낚시')
        self.append('봇', result(4000))
        self.assertFalse(macro.limit_hit_after_my_command(self.text, '나', 4000))
        job = macro.MacroJob.__new__(macro.MacroJob)
        job.today = 1442; job.phase = 'daily'
        self.assertTrue(job._stale(('success', 2000, 4000, None)))
        self.assertFalse(job._stale(('success', 1443, 4000, None)))
