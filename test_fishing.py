import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from fishing_history import History, Observer, parse_details, segment, aggregate, next_reset, KST
import fishing_macro as macro


def line(sender, body):
    return f"[{sender}] [오후 10:00] {body}"


COPIED_CHAT = """[정인환] [오후 10:59] @방구석낚시꾼 낚시
[방구석낚시꾼] [오후 10:59] @사용자 낚시 성공!

💰 획득 골드: 37G (120%)
💰 보유 골드: 744,754G
✨ 경험치: 4EXP (3,825 / 11,660)
🎣 오늘 낚시: 611 / 3,000

🎯 다음 추가 보상까지 389회!
[방구석낚시꾼] [오후 10:59] [가자미] 30.2cm
🐟 등급: 일반
낮게 붙어 있다가 올라오는 손맛이 제법 독특합니다.
[정인환] [오후 10:59] @방구석낚시꾼 낚시
[방구석낚시꾼] [오후 10:59] @사용자 낚시 성공!

💰 획득 골드: 163G (120%)
💰 보유 골드: 744,917G
✨ 경험치: 7EXP (3,832 / 11,660)
🎣 오늘 낚시: 612 / 3,000

🎯 다음 추가 보상까지 388회!
[방구석낚시꾼] [오후 10:59] [해마] 8.6cm
🐟 등급: 일반
작은 몸집인데도 존재감은 꽤 또렷합니다.
[박건] [오후 10:59] @방구석낚시꾼 낚시
[방구석낚시꾼] [오후 10:59] @사용자 낚시 성공!

💰 획득 골드: 154G (120%)
💰 보유 골드: 2,080,538G
✨ 경험치: 7EXP (16,210 / 18,120)
🎣 오늘 낚시: 943 / 3,000

🎯 다음 추가 보상까지 57회!
[방구석낚시꾼] [오후 10:59] [블루탱] 18.6cm
🐟 등급: 일반
색감이 먼저 눈에 들어오는 깔끔한 바다 어종입니다."""


class ActualCopiedChatTests(unittest.TestCase):
    def test_each_user_and_repeated_snapshots(self):
        for user, expected in [('정인환', [('가자미', 30.2, 37, 4, 611), ('해마', 8.6, 163, 7, 612)]),
                               ('박건', [('블루탱', 18.6, 154, 7, 943)])]:
            with self.subTest(user=user):
                history = History()
                observer = Observer(history, user)
                observer.baseline('')
                observer.observe(COPIED_CHAT)
                observer.observe(COPIED_CHAT)
                records = history.snapshot()
                self.assertEqual([(r['species'], r['size'], r['gold'], r['exp'], r['today']) for r in records], expected)
                self.assertTrue(all(r['grade'] == '일반' and r['multiplier'] == 120 and r['limit'] == 3000 for r in records))

    def test_incrementally_copied_cards(self):
        history = History()
        observer = Observer(history, '정인환')
        observer.baseline('')
        lines = COPIED_CHAT.splitlines()
        for index in range(1, len(lines) + 1):
            observer.observe('\n'.join(lines[:index]))
        records = history.snapshot()
        self.assertEqual([r['species'] for r in records], ['가자미', '해마'])
        self.assertEqual(sum(r['gold'] for r in records), 200)
        self.assertEqual(sum(r['exp'] for r in records), 11)


class ParsingTests(unittest.TestCase):
    def test_normal_and_big_catch(self):
        data = parse_details("@사용자 대어 출현!\n획득 골드: 4,161G (120%)\n경험치: 231EXP (9,925 / 16,980)\n오늘 낚시: 1,858 / 3,000\n[만년화리] 82.1cm\n등급: 전설")
        self.assertEqual((data['gold'], data['exp'], data['today'], data['species'], data['grade']), (4161, 231, 1858, '만년화리', '전설'))
        self.assertEqual(macro.classify_reply('@사용자 대어 출현!\n오늘 낚시: 1,858 / 3,000')[0], 'success')

    def test_unknown_exp_is_not_zero_gain(self):
        self.assertNotIn('exp', parse_details('경험치: EXP (7,156 / 11,280)'))

    def test_pearl(self):
        data = parse_details('진주 발견!\n보유 진주가 +1 증가했어요.\n오늘 낚시: 36 / 3,000\n현재 보유 진주: 329')
        self.assertEqual(data['pearls'], 1)
        self.assertEqual(data['today'], 36)

    def test_raid_does_not_double_rewards(self):
        data = parse_details('현무의 잔향을 마주쳤어요.\n잔향 보상: 14,970G\n잔향 보상: 해신석 +3개\n3,000회 달성 보상: 골드 +10,000G\n잔향 피해: 7,485 데미지\n획득 골드: 14,970G\n해신석 +3개')
        self.assertEqual((data['kind'], data['gold'], data['stones'], data['bonus'], data['damage']), ('raid', 14970, 3, 10000, 7485))

    def test_collection(self):
        self.assertTrue(parse_details('[우럭] 50.0cm\n도감 완성! 해당 어종의 최대 크기를 낚았어요!')['collection'])

    def test_segments(self):
        for date, count, expected in [('2026-10-27', 500, '150%'), ('2026-10-27', 2000, '120%'), ('2026-10-27', 2001, '100%'), ('2026-10-31', 2500, '120%'), ('2026-10-31', 2501, '100%')]:
            self.assertIn(expected, segment({'time': date + 'T12:00:00+09:00', 'today': count}))

    def test_schedule(self):
        for second, expected_day in [(0, 27), (4, 27), (5, 28), (6, 28)]:
            target = next_reset(datetime(2026, 10, 27, 0, 0, second, tzinfo=KST))
            self.assertEqual((target.day, target.hour, target.second), (expected_day, 0, 5))


class ObserverTests(unittest.TestCase):
    def test_equipment_does_not_take_next_tadpole(self):
        self.append('나', '@방구석낚시꾼 낚시')
        self.append('방구석낚시꾼', '@사용자 낚시 성공!\n획득 골드: 535G\n경험치: 30EXP\n행운: 남은 9회 낚시\n오늘 낚시: 2,850 / 3,000')
        self.append('방구석낚시꾼', '[파괴된 전직 장비] 9강\n등급: 레어')
        self.append('나', '@방구석낚시꾼 낚시')
        self.append('방구석낚시꾼', '@사용자 낚시 성공!\n획득 골드: 12G\n경험치: 4EXP\n행운: 남은 8회 낚시\n오늘 낚시: 2,851 / 3,000')
        self.append('방구석낚시꾼', '[올챙이] 8.2cm\n등급: 일반')
        rows = self.history.snapshot()
        self.assertEqual([(r['species'], r['grade'], r['gold'], r['exp']) for r in rows],
                         [('파괴된 전직 장비', '레어', 535, 30), ('올챙이', '일반', 12, 4)])
        self.assertEqual(rows[0]['enhancement'], 9)
        self.assertNotIn('size', rows[0])
        self.assertEqual(rows[1]['size'], 8.2)

    def test_unknown_card_attribute_also_completes_response(self):
        self.append('나', '@방구석낚시꾼 낚시')
        self.append('방구석낚시꾼', '@사용자 낚시 성공!\n획득 골드: 100G')
        self.append('방구석낚시꾼', '[특수 획득물] 특수 표기\n등급: 에픽')
        self.catch('올챙이')
        rows = self.history.snapshot()
        self.assertEqual([r['species'] for r in rows], ['특수 획득물', '올챙이'])
        self.assertEqual(rows[0]['card_attribute'], '특수 표기')

    def setUp(self):
        self.history = History()
        self.obs = Observer(self.history, '나')
        self.text = line('이전사람', '오래된 대화')
        self.obs.baseline(self.text)

    def append(self, sender, body):
        self.text += '\n' + line(sender, body)
        self.obs.observe(self.text)

    def catch(self, species='하프 물범', effect=''):
        self.append('나', '@방구석낚시꾼 낚시')
        self.append('방구석낚시꾼', '@사용자 낚시 성공!\n획득 골드: 719G (120%)\n경험치: 38EXP (5,607 / 18,120)\n오늘 낚시: 598 / 3,000' + effect)
        self.append('방구석낚시꾼', f'[{species}] 114.3cm\n등급: 레어')

    def test_split_card_and_duplicate_poll(self):
        self.catch(effect='\n행운: 남은 10회 낚시')
        self.obs.observe(self.text)
        self.obs.observe(self.text)
        rows = self.history.snapshot()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['species'], '하프 물범')
        self.assertEqual(list(self.obs.buff_requests), [10])

    def test_bait_uses_effect_not_species(self):
        self.catch('카피바라', '\n행운: 남은 20회 낚시')
        self.assertEqual(list(self.obs.buff_requests), [20])

    def test_named_species_without_grant_does_not_use_bait(self):
        self.catch('만년화리')
        self.assertEqual(list(self.obs.buff_requests), [])

    def test_partial_existing_effect_does_not_use_bait(self):
        self.catch('가자미', '\n만년서리의 숨결: 남은 3회 대어 확률 +2.0%p')
        self.assertEqual(list(self.obs.buff_requests), [])
        row = self.history.snapshot()[0]
        self.assertTrue(row['frost_active'])
        self.assertFalse(row['frost_granted'])
        self.assertFalse(row['lucky'])

    def test_concurrent_effects_use_longer_duration_once(self):
        self.catch('새 어종', '\n행운: 남은 10회 낚시\n만년서리의 숨결: 남은 20회 대어 확률 +2.0%p')
        self.obs.observe(self.text)
        self.assertEqual(list(self.obs.buff_requests), [20])

    def test_twenty_baits(self):
        self.catch('만년화리', '\n만년화리의 숨결: 남은 20회 대어 확률 +2.0%p')
        self.assertEqual(list(self.obs.buff_requests), [20])

    def test_old_history_not_imported(self):
        self.obs.baseline(line('나', '@방구석낚시꾼 낚시') + '\n' + line('방구석낚시꾼', '@사용자 낚시 성공!'))
        self.obs.observe('\n'.join(line(*m) for m in self.obs.previous))
        self.assertEqual(self.history.snapshot(), [])

    def test_other_player_excluded(self):
        self.append('다른사람', '@방구석낚시꾼 낚시')
        self.append('방구석낚시꾼', '@사용자 낚시 성공!\n[우럭] 10cm\n등급: 일반')
        self.assertEqual(self.history.snapshot(), [])

    def test_card_extension(self):
        self.catch()
        self.text += '\n도감 완성! 해당 어종의 최대 크기를 낚았어요!'
        self.obs.observe(self.text)
        self.assertTrue(self.history.snapshot()[0]['collection'])
        self.assertEqual(len(self.history.snapshot()), 1)

    def test_bag_split(self):
        self.catch()
        self.append('나', '@방구석낚시꾼 가방')
        self.append('방구석낚시꾼', '@사용자 보유 재화를 확인해 보세요.')
        self.append('방구석낚시꾼', '내 가방\n골드: 2,079,800G\n미끼: 7개\n진주: 351개')
        self.assertEqual(self.obs.bag_count, 7)
        self.assertEqual(len(self.history.snapshot()), 1)

    def test_auto_occurrence(self):
        self.catch()
        self.append('나', '@방구석낚시꾼 낚시')
        self.append('방구석낚시꾼', '@사용자 자동어 출현!')
        self.assertEqual(self.history.snapshot()[-1]['today'], 599)

    def test_aggregate_actual_gold(self):
        self.catch()
        self.catch()
        result = aggregate(self.history.snapshot())[0]
        self.assertEqual((result['count'], result['gold'], result['exp']), (2, 1438, 76))

    def test_abyss_in_meters(self):
        self.append('나', '@방구석낚시꾼 낚시')
        self.append('방구석낚시꾼', '@사용자 대어 출현!\n획득 골드: 12,069G (120%)\n어비스: 해신석 +3개\n경험치: 622EXP (5,109 / 19,260)\n오늘 낚시: 942 / 3,000')
        self.append('방구석낚시꾼', '[어비스] 37.4m\n등급: 전설')
        record = self.history.snapshot()[0]
        self.assertEqual((record['species'], record['size'], record['kind']), ('어비스', 3740.0, 'fish'))
        self.assertEqual((record['gold'], record['exp'], record['stones']), (12069, 622, 3))

    def test_two_fish_headers_before_two_cards(self):
        self.append('친구', '@방구석낚시꾼 낚시')
        self.append('나', '@방구석낚시꾼 낚시')
        self.append('방구석낚시꾼', '@사용자 낚시 성공!\n획득 골드: 483G (120%)\n오늘 낚시: 1,221 / 3,000')
        self.append('방구석낚시꾼', '@사용자 대어 출현!\n획득 골드: 5,028G (120%)\n경험치: 274EXP\n오늘 낚시: 1,183 / 3,000')
        self.append('방구석낚시꾼', '[피라니아] 21.6cm\n등급: 레어')
        self.append('방구석낚시꾼', '[거북선] 246.7m\n등급: 전설')
        record = self.history.snapshot()[0]
        self.assertEqual((record['species'], record['size'], record['gold'], record['today']), ('거북선', 24670.0, 5028, 1183))
        self.assertEqual(len(self.history.snapshot()), 1)

    def test_pearl_and_fish_cards_do_not_mix(self):
        for reverse_cards in (False, True):
            with self.subTest(reverse_cards=reverse_cards):
                self.setUp()
                self.append('친구', '@방구석낚시꾼 낚시')
                self.append('나', '@방구석낚시꾼 낚시')
                self.append('방구석낚시꾼', '@사용자 진주 발견!')
                self.append('방구석낚시꾼', '@사용자 낚시 성공!\n획득 골드: 874G (150%)\n경험치: 46EXP\n오늘 낚시: 238 / 3,000')
                cards = ['보유 진주가 +1 증가했어요.\n오늘 낚시: 321 / 3,000', '[복어] 34.8cm\n등급: 레어']
                for card in (reversed(cards) if reverse_cards else cards):
                    self.append('방구석낚시꾼', card)
                self.obs.observe(self.text)
                record = self.history.snapshot()[0]
                self.assertEqual((record['kind'], record['species'], record['today']), ('fish', '복어', 238))
                self.assertNotIn('pearls', record)
                self.assertEqual(self.obs.today, 238)

    def test_my_pearl_does_not_receive_friends_fish(self):
        self.append('나', '@방구석낚시꾼 낚시')
        self.append('친구', '@방구석낚시꾼 낚시')
        self.append('방구석낚시꾼', '@사용자 진주 발견!')
        self.append('방구석낚시꾼', '@사용자 낚시 성공!\n획득 골드: 874G\n오늘 낚시: 238 / 3,000')
        self.append('방구석낚시꾼', '보유 진주가 +1 증가했어요.\n오늘 낚시: 321 / 3,000')
        self.append('방구석낚시꾼', '[복어] 34.8cm\n등급: 레어')
        record = self.history.snapshot()[0]
        self.assertEqual((record['kind'], record['pearls'], record['today']), ('pearl', 1, 321))
        self.assertNotIn('species', record)
        self.assertNotIn('gold', record)

    def test_delayed_buff_card_belongs_to_its_owner(self):
        self.append('친구', '@방구석낚시꾼 낚시')
        self.append('나', '@방구석낚시꾼 낚시')
        self.append('방구석낚시꾼', '@사용자 낚시 성공!')
        self.append('방구석낚시꾼', '@사용자 낚시 성공!')
        self.append('방구석낚시꾼', '[하프 물범] 110cm\n등급: 레어')
        self.append('방구석낚시꾼', '[가자미] 30.2cm\n등급: 일반')
        self.assertEqual(list(self.obs.buff_requests), [])
        self.assertEqual(self.history.snapshot()[0]['species'], '가자미')


class IntegrationTests(unittest.TestCase):
    def test_copy_restores_input_focus_before_waiting_for_clipboard(self):
        # Real Kakao reproduction: queued copy completes at focus reattachment,
        # not while the macro is just sleeping and polling the sequence number.
        state = {'sequence': 1, 'text': 'previous clipboard', 'copy_requested': False}

        def focus(handle):
            if handle == 20 and state['copy_requested']:
                state['sequence'] = 2
                state['text'] = COPIED_CHAT
            return True

        def keys(*vks):
            if vks == (macro.VK_CONTROL, macro.VK_C):
                state['copy_requested'] = True
            return True

        def ready(before):
            self.assertNotEqual(state['sequence'], before)
            return state['text']

        with patch.object(macro, 'find_child', side_effect=[10, 20]), \
             patch.object(macro, 'GetForegroundWindow', return_value=1), \
             patch.object(macro, 'get_clipboard_text', side_effect=lambda: state['text']), \
             patch.object(macro, 'GetClipboardSequenceNumber', side_effect=lambda: state['sequence']), \
             patch.object(macro, 'focus_control', side_effect=focus), \
             patch.object(macro, 'press_keys', side_effect=keys), \
             patch.object(macro, 'wait_for_copied_text', side_effect=ready), \
             patch.object(macro, 'set_clipboard') as restore, \
             patch.object(macro.time, 'sleep'):
            self.assertEqual(macro.copy_chat(1), COPIED_CHAT)
            restore.assert_called_once_with('previous clipboard')

    def test_clipboard_change_before_text_is_ready(self):
        with patch.object(macro, 'GetClipboardSequenceNumber', return_value=2), \
             patch.object(macro, 'get_clipboard_text', side_effect=[None, None, COPIED_CHAT]) as read, \
             patch.object(macro.time, 'sleep'):
            self.assertEqual(macro.wait_for_copied_text(1), COPIED_CHAT)
            self.assertEqual(read.call_count, 3)

    def test_clipboard_timeout(self):
        with patch.object(macro, 'GetClipboardSequenceNumber', return_value=2), \
             patch.object(macro, 'get_clipboard_text', return_value=None), \
             patch.object(macro.time, 'monotonic', side_effect=[0, 0.1, 3.1]), \
             patch.object(macro.time, 'sleep'):
            self.assertIsNone(macro.wait_for_copied_text(1))

    def test_unchanged_clipboard_is_not_accepted(self):
        with patch.object(macro, 'GetClipboardSequenceNumber', return_value=1), \
             patch.object(macro, 'get_clipboard_text') as read, \
             patch.object(macro.time, 'monotonic', side_effect=[0, 0.1, 3.1]), \
             patch.object(macro.time, 'sleep'):
            self.assertIsNone(macro.wait_for_copied_text(1))
            read.assert_not_called()

    def timer_app(self):
        app = macro.App.__new__(macro.App)
        app._scheduled_at = datetime(2026, 10, 27, 0, 0, 5, tzinfo=KST)
        app._schedule_pending = False
        app._shutdown_at = None
        app._dialog_open = False
        app._shutdown_deferred = False
        app.shutdown_var = Mock(get=Mock(return_value=True))
        app._next_save = float('inf')
        app.job = None
        app.start = Mock()
        app.schedule_label = Mock()
        return app

    def test_schedule_fires_once(self):
        app = self.timer_app()
        with patch.object(macro, 'now_kst', return_value=datetime(2026, 10, 27, 0, 0, 5, tzinfo=KST)):
            app._timers()
            app._timers()
        app.start.assert_called_once_with(scheduled=True)

    def test_schedule_waits_for_old_worker(self):
        app = self.timer_app()
        job = app.job = Mock()
        with patch.object(macro, 'now_kst', return_value=datetime(2026, 10, 27, 0, 0, 5, tzinfo=KST)):
            app._timers()
            app.start.assert_not_called()
            job.stop.assert_called_once_with()
            app.job = None
            app._timers()
        app.start.assert_called_once_with(scheduled=True)

    def test_cancel_shutdown(self):
        app = self.timer_app()
        app._shutdown_at = 123
        app._notice = Mock()
        app.cancel_shutdown()
        self.assertIsNone(app._shutdown_at)

    def test_shutdown_cancelled_when_history_save_fails(self):
        app = self.timer_app()
        app._scheduled_at = None
        app._shutdown_at = 0
        app._persist_history = Mock(return_value=False)
        with patch.object(macro.subprocess, 'run') as run:
            app._timers()
            run.assert_not_called()

    def policy_app(self, scheduled=False, reservation=False):
        app = macro.App.__new__(macro.App)
        app.job = None
        app.shutdown_var = Mock(get=Mock(return_value=True))
        app.schedule_var = Mock(get=Mock(return_value=reservation))
        app._job_scheduled = scheduled
        app._save_options = Mock()
        app._limit_completed = True
        app._schedule_pending = False
        app._shutdown_at = None
        app._shutdown_deferred = False
        app._scheduled_at = object() if reservation else None
        return app

    def test_shutdown_waits_for_reserved_run_then_ends(self):
        app = self.policy_app(reservation=True)
        app._update_shutdown_policy()
        self.assertIsNone(app._shutdown_at)
        self.assertTrue(app._shutdown_deferred)
        app._job_scheduled = True
        app._update_shutdown_policy()
        self.assertIsNotNone(app._shutdown_at)
        self.assertFalse(app._shutdown_deferred)
        self.assertIsNone(app._scheduled_at)
        app.schedule_var.set.assert_called_with(False)

    def test_removing_reservation_after_limit_arms_shutdown(self):
        app = self.policy_app(reservation=True)
        app._update_shutdown_policy()
        app.schedule_var.get.return_value = False
        app._arm_schedule()
        self.assertIsNotNone(app._shutdown_at)

    def test_adding_reservation_cancels_countdown(self):
        app = self.policy_app()
        app._update_shutdown_policy()
        app.schedule_var.get.return_value = True
        app._arm_schedule()
        self.assertIsNone(app._shutdown_at)
        self.assertTrue(app._shutdown_deferred)

    def test_unchecking_shutdown_cancels_deferred_and_countdown(self):
        app = self.policy_app(reservation=True)
        app._update_shutdown_policy()
        app.shutdown_var.get.return_value = False
        app._update_shutdown_policy()
        self.assertFalse(app._shutdown_deferred)
        self.assertIsNone(app._shutdown_at)

    def test_no_shutdown_before_limit_or_while_running(self):
        app = self.policy_app()
        app._limit_completed = False
        app._update_shutdown_policy()
        self.assertIsNone(app._shutdown_at)
        app._limit_completed = True
        app.job = Mock()
        app._update_shutdown_policy()
        self.assertIsNone(app._shutdown_at)

    def test_bait_caps(self):
        for available, maximum, expected in [(30, 10, 10), (30, 20, 20), (7, 20, 7), (0, 20, 0)]:
            job = macro.MacroJob.__new__(macro.MacroJob)
            job.observer = Mock(bag_count=None, bag_version=0)
            def observe(_):
                job.observer.bag_count = available
                job.observer.bag_version += 1
            job.observer.observe.side_effect = observe
            job._command = Mock(return_value=True)
            job._sleep = Mock(return_value=False)
            job._wait_until_ready = Mock(return_value=True)
            job._await_reply = Mock(return_value=())
            job.target = 1
            with patch.object(macro, 'copy_chat', return_value='bag'):
                self.assertTrue(job._use_bait(maximum))
            commands = [call.args[0] for call in job._command.call_args_list]
            self.assertEqual(commands, ['가방'] + ([f'미끼 {expected}'] if expected else []))

    def test_shutdown_only_on_daily_limit(self):
        for reason, should_shutdown in [('finished', False), ('limit', True), ('target_closed', False), (None, False)]:
            app = macro.App.__new__(macro.App)
            app.job = Mock(end_reason=reason, error=None)
            app._set_busy = Mock()
            app._progress = Mock(return_value='')
            app.shutdown_var = Mock(get=Mock(return_value=True))
            app.schedule_var = Mock(get=Mock(return_value=False))
            app._job_scheduled = False
            app._limit_completed = False
            app._shutdown_deferred = False
            app._schedule_pending = False
            app._shutdown_at = None
            app._finish_job()
            self.assertEqual(app._shutdown_at is not None, should_shutdown)


if __name__ == '__main__':
    unittest.main()
