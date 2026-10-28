import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fishing_macro as macro
from fishing_history import History, Observer, parse_details
from history_storage import load_records
from history_view import make_rows, display_row


def header(n):
    return f'@사용자 낚시 성공!\n📚 추가 낚시: {n} / 1,000\n🌊 지정 낚시터 미적용 · 전체 낚시터 어종 등장\n🎒 재화·경험치 없음\n\n[일반] 개구리 · 16.4cm'


class ExtraFishingTests(unittest.TestCase):
    def test_header_waits_for_real_card_and_persists(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / 'history.csv'
            history = History(path); observer = Observer(history, '박건'); observer.baseline('')
            text = '[박건] [오전 11:31] @방구석낚시꾼 낚시\n[방구석낚시꾼] [오전 11:31] ' + header(2)
            observer.observe(text)
            self.assertNotIn('species', history.snapshot()[0])
            text += '\n[방구석낚시꾼] [오전 11:31] [개구리] 16.4cm\n🐟 등급: 일반'
            observer.observe(text); observer.observe(text)
            rows = load_records(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual([rows[0][k] for k in ('species','grade','size','today','limit','gold','exp','phase')],
                             ['개구리','일반',16.4,2,1000,0,0,'extra'])
            display = display_row(make_rows(rows, '전체')[0])
            self.assertEqual(display[1:3], ['0%', '추가 2 / 1,000'])

    def test_start_in_extra_phase_keeps_running(self):
        with patch('threading.Thread.start'):
            job = macro.MacroJob(0, '박건', 2, False)
        replies = iter([macro.classify_reply(header(2)), macro.classify_reply(header(3))])
        with patch.object(job, '_sleep', return_value=False), patch.object(job, '_wait_until_ready', return_value=True), \
             patch.object(job, '_command', return_value=True) as command, patch.object(job, '_await_reply', side_effect=lambda: next(replies)), \
             patch.object(macro, 'copy_chat', return_value=''), patch.object(macro, 'release_stuck_keys'):
            job._run()
        self.assertIsNone(job.error)
        self.assertEqual((job.phase, job.today, job.limit, job.end_reason, command.call_count), ('extra',3,1000,'finished',2))
        job.today = 1000
        self.assertTrue(job._phase_limit_hit(('extra_success',1000,1000)))
        job.phase = 'daily'; job.today = 3000; job.limit = 3000
        self.assertTrue(job._phase_limit_hit(('success',3000,3000,None)))
        job.today = 1; job.limit = 1000
        self.assertTrue(job._phase_limit_hit(('extra_success',1,1000)))

    def test_daily_raid_completion_still_stops(self):
        self.assertTrue(macro.limit_hit(macro.classify_reply('일일 낚시 완료! 추가 낚시가 열렸습니다.'),3000))
        self.assertEqual(macro.classify_reply(header(2)), ('extra_success',2,1000))


if __name__ == '__main__':
    unittest.main()
