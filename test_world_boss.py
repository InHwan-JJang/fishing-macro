import tempfile
import unittest
from pathlib import Path

from fishing_history import History, Observer, parse_details
from history_storage import load_records
from history_view import raid_rows, display_raid_row, sort_rows


HEADER = '@사용자 월드 보스 크라켄 조우!\n\n💰 즉시 보상: 13,870G\n🔷 타격 보상: 해신석 +1개\n🎁 3,000회 달성 보상: 골드 +15,000G'
CARD = '월드 보스 크라켄\nHP [█░░░░░░░░░] 13.8%\n41,387,691 / 300,000,000\n⚔️ 13,870 데미지\n🎬 광고 시청은 선택사항이며, 완료하면 추가 선물을 받아요.\n📚 일일 낚시 완료! 추가 낚시가 열렸습니다.\n전체 낚시터 어종 출현 · 재화/경험치 없음'


def line(sender, body):
    return f'[{sender}] [오전 11:09] {body}'


class WorldBossTests(unittest.TestCase):
    def test_original_and_other_boss_names(self):
        for name in ('크라켄', '바다의 지배자'):
            data = parse_details((HEADER + '\n' + CARD).replace('크라켄', name))
            self.assertEqual((data['kind'], data['boss_name'], data['raid_type']), ('raid', name, '월드 보스'))
            self.assertEqual([data[k] for k in ('gold', 'damage', 'stones', 'bonus', 'hp_current', 'hp_max', 'hp_percent')],
                             [13870, 13870, 1, 15000, 41387691, 300000000, 13.8])
            self.assertNotIn('species', data)

    def test_fifo_interleaved_players_and_repeated_copy(self):
        history = History()
        observer = Observer(history, '박건')
        observer.baseline('')
        messages = [line('친구', '@방구석낚시꾼 낚시'), line('박건', '@방구석낚시꾼 낚시'),
                    line('방구석낚시꾼', HEADER.replace('크라켄', '다른 보스').replace('13,870', '99')),
                    line('방구석낚시꾼', HEADER),
                    line('방구석낚시꾼', CARD.replace('크라켄', '다른 보스').replace('13,870', '99')),
                    line('방구석낚시꾼', CARD)]
        for end in range(1, len(messages) + 1):
            observer.observe('\n'.join(messages[:end]))
        observer.observe('\n'.join(messages))
        rows = history.snapshot()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['boss_name'], rows[0]['damage'], rows[0]['gold']), ('크라켄', 13870, 13870))

    def test_csv_and_raid_display(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / 'raid.csv'
            history = History(path)
            history.update(1, parse_details(HEADER + '\n' + CARD))
            history.update(2, dict(kind='raid', gold=100))  # Existing CSV without new fields.
            rows = raid_rows(load_records(path))
            self.assertEqual(display_raid_row(rows[0])[1], '—')
            self.assertEqual(rows[1]['hp_current'], 41387691)
            self.assertEqual(sort_rows(rows, 'damage', 2)[0]['damage'], 13870)

    def test_echo_name(self):
        data = parse_details('@사용자 현무의 잔향을 마주쳤어요.\n잔향 보상: 14,970G\n잔향 피해: 7,485 데미지')
        self.assertEqual((data['boss_name'], data['raid_type'], data['kind']), ('현무의 잔향', '잔향', 'raid'))

    def test_raid_window_ignores_fish_grade_and_restores_columns(self):
        import tkinter as tk
        from history_window import HistoryWindow
        root = tk.Tk(); root.withdraw()
        history = History(); history.update(1, parse_details(HEADER + '\n' + CARD))
        window = HistoryWindow(root, history); window.window.withdraw()
        try:
            window.grade.set('에픽')
            window.mode.set('레이드'); window.refresh()
            self.assertEqual(len(window.tree.get_children()), 1)
            self.assertIn('13,870G', window.revenue.cget('text'))
            window.toggle_sort('damage')
            self.assertEqual(window.tree.heading('damage')['text'], '데미지 ▲')
            window.mode.set('전체'); window.refresh()
            self.assertEqual(window.grade.get(), '에픽')
            self.assertEqual(window.tree.heading('time')['text'], '시간 ▼')
        finally:
            window.close(); root.destroy()


if __name__ == '__main__':
    unittest.main()
