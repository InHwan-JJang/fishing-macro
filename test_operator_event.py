import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fishing_macro as macro
from fishing_history import History, Observer, parse_details
from history_storage import load_records
from history_view import make_rows


BOT = '방구석낚시꾼'
HEADER = '@사용자 운영자가 찾아왔어요!'
CARD = ('🎣 방구석낚시꾼 운영자 출현!\n요즘 모발이 약해진 것 같아요...\n기분 탓이겠죠?\n'
        '🎁 모발보다 소중한 선물\n🎁 15,000G · 진주 1개\n· 미끼 1개 · 해신석 1개')


def line(sender, body):
    return f'[{sender}] [오후 4:49] {body}'


class OperatorEventTests(unittest.TestCase):
    def test_header_and_card_classification(self):
        for text in (HEADER, CARD, HEADER + '\n' + CARD):
            self.assertEqual(parse_details(text)['kind'], 'operator')
            self.assertEqual(macro.classify_reply(text), ('operator',))
        self.assertEqual(parse_details(CARD), dict(kind='operator', gold=15000, pearls=1, bait=1, stones=1))
        self.assertNotIn('gold', parse_details(HEADER))

    def test_incremental_card_duplicate_copy_and_following_fish(self):
        history = History()
        observer = Observer(history, '박건')
        observer.baseline('')
        text = '\n'.join([line('박건', '@' + BOT + ' 낚시'), line(BOT, HEADER), line(BOT, CARD),
                          line('박건', '@' + BOT + ' 낚시'),
                          line(BOT, '@사용자 낚시 성공!\n획득 골드: 100G\n오늘 낚시: 10 / 4000'),
                          line(BOT, '[가자미] 34.1cm\n등급: 일반')])
        lines = text.splitlines()
        for end in range(1, len(lines) + 1):
            observer.observe('\n'.join(lines[:end]))
        observer.observe(text)
        records = history.snapshot()
        self.assertEqual(len(records), 2)
        self.assertEqual([r['kind'] for r in records], ['operator', 'fish'])
        self.assertEqual([records[0][k] for k in ('gold', 'pearls', 'bait', 'stones')], [15000, 1, 1, 1])
        self.assertNotIn('today', records[0])
        self.assertEqual(records[1]['gold'], 100)
        self.assertNotIn('pearls', records[1])
        self.assertFalse(records[0]['any_lucky'])

    def test_other_players_reward_is_not_misattributed(self):
        history = History(); observer = Observer(history, '박건'); observer.baseline('')
        text = '\n'.join([line('친구', '@' + BOT + ' 낚시'), line('박건', '@' + BOT + ' 낚시'),
                          line(BOT, HEADER), line(BOT, HEADER),
                          line(BOT, CARD.replace('15,000', '99,000')), line(BOT, CARD)])
        observer.observe(text)
        self.assertEqual(len(history.snapshot()), 1)
        self.assertEqual(history.snapshot()[0]['gold'], 15000)

    def test_csv_roundtrip_and_display(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / 'history.csv'
            history = History(path); history.update(1, parse_details(CARD))
            records = load_records(path)
            self.assertEqual(records[0]['bait'], 1)
            row = make_rows(records, '전체')[0]
            self.assertEqual((row['species'], row['gold']), ('운영자 출현', 15000))
            for detail in ('진주 1', '미끼 1', '해신석 1'):
                self.assertIn(detail, row['extra'])
            self.assertEqual(make_rows(records, '어종'), [])
            self.assertEqual(make_rows(records, '레이드'), [])

    def test_macro_continues_fishing_without_manual_command(self):
        with patch('threading.Thread.start'):
            job = macro.MacroJob(0, '박건', 2, False)
        with patch.object(job, '_sleep', return_value=False), \
             patch.object(job, '_wait_until_ready', return_value=True), \
             patch.object(job, '_command', return_value=True) as command, \
             patch.object(job, '_await_reply', side_effect=[('operator',), ('success', 10, 4000, None)]), \
             patch.object(macro, 'copy_chat', return_value=''), patch.object(macro, 'release_stuck_keys'):
            job._run()
        self.assertIsNone(job.error)
        self.assertEqual([call.args[0] for call in command.call_args_list], ['낚시', '낚시'])
        self.assertEqual(job.end_reason, 'finished')

    def test_window_totals_include_all_operator_rewards(self):
        import tkinter as tk
        from history_window import HistoryWindow
        root = tk.Tk(); root.withdraw()
        history = History(); history.update(1, parse_details(CARD))
        window = HistoryWindow(root, history); window.window.withdraw()
        try:
            window.refresh()
            summary = window.summary.cget('text')
            for value in ('운영자 출현 1회', '15,000G', '진주 1개', '미끼 1개', '해신석 1개'):
                self.assertIn(value, summary)
            self.assertIn('총 판매수익 0G', window.revenue.cget('text'))
        finally:
            window.close(); root.destroy()
