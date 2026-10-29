"""Conservative, one-shot recovery from dated copied chat, never desktop input."""
from datetime import datetime
import re

from fishing_history import History, Observer, HEADER, KST, now_kst, parse_details

DATE = re.compile(r'^[-=\s]*(\d{4})\s*(?:년|[./-])\s*(\d{1,2})\s*(?:월|[./-])\s*(\d{1,2})\s*(?:일|\b)')
CLOCK = re.compile(r'\[(오전|오후) (\d{1,2}):(\d{2})\]')


def missing_runs(records, user, day):
    counts = sorted({r['today'] for r in records if r.get('user') == user and
                     r['time'][:10] == day and r.get('phase') != 'extra' and
                     r.get('today') is not None and r['kind'] in ('fish', 'pearl', 'auto', 'raid')})
    return [(a + 1, b - 1) for a, b in zip(counts, counts[1:]) if b > a + 1]


def dated_candidates(text, user, bot, day):
    class ReplayHistory(History):
        def update(self, key, data, stamp=None):
            super().update(key, data, self.stamp)

    history = ReplayHistory()
    observer = Observer(history, user)
    observer.capture_all = True
    observer.bot = bot
    current_day = None
    entries = []
    for line in text.splitlines():
        date = DATE.match(line)
        if date:
            try:
                current_day = datetime(*map(int, date.groups()), tzinfo=KST).date().isoformat()
            except ValueError:
                current_day = None
            entries.append(None)  # A day separator must not become part of a card.
            continue
        header = HEADER.match(line)
        if header:
            clock = CLOCK.search(line)
            hour = int(clock[2]) % 12 + (12 if clock[1] == '오후' else 0)
            stamp = f'{current_day}T{hour:02}:{clock[3]}:00+09:00' if current_day else None
            entries.append([header[1], header[2], stamp])
        elif entries and entries[-1] is not None and line.strip():
            entries[-1][1] += '\n' + line
    for entry in entries:
        if entry is None:
            observer.pending.clear()
            observer.responses.clear()
            observer.active = None
            continue
        sender, body, stamp = entry
        if not stamp or stamp[:10] != day:
            continue
        history.stamp = datetime.fromisoformat(stamp)
        # Orphan result headers can still be identified by the balance chain.
        # Keep their owner unknown; never assume that @사용자 means this player.
        if sender == observer.bot and body.startswith('@') and parse_details(body).get('kind') and not observer.pending:
            observer.pending.append(('', '낚시', history.new_id()))
        observer._consume(sender, body)
    rows = history.snapshot()
    previous = {}
    for row in rows:
        owner = row.get('user')
        prior = previous.get(owner)
        if owner and prior and row.get('today') is None:
            if row['kind'] == 'auto' and prior.get('today') is not None:
                row['today'] = prior['today'] + 1
            elif row['kind'] == 'raid' and prior.get('limit') == prior.get('today', -2) + 1:
                row['today'] = prior['limit']
            if 'today' in row:
                row['limit'] = prior.get('limit')
        if row.get('phase') != 'extra':
            previous[owner] = row
    return rows


def previous_balance(record):
    if 'balance' not in record:
        return None
    gold = record.get('gold')
    if gold is None and record['kind'] in ('pearl', 'auto'):
        gold = 0
    if gold is None:
        return None
    return record['balance'] - gold - record.get('bonus', 0)


def recover_missing(history, text, user, bot):
    day = now_kst().date().isoformat()
    with history._lock:
        records = history.snapshot()
        runs = missing_runs(records, user, day)
        requested = history.recovery_pending
        targets = [(lo, hi) for lo, hi in runs if requested or
                   any((day, user, n) not in history.recovery_attempted for n in range(lo, hi + 1))]
        if not requested and not targets:
            return
        history.recovery_pending = False
        for lo, hi in targets:
            history.recovery_attempted.update((day, user, n) for n in range(lo, hi + 1))
        candidates = dated_candidates(text, user, bot, day) if targets else []
        added = 0
        for lo, hi in targets:
            anchors = [r for r in records if r.get('user') == user and r['time'][:10] == day and
                       r.get('today') == hi + 1 and r.get('phase') != 'extra']
            if len(anchors) != 1:
                continue
            following = anchors[0]
            for count in range(hi, lo - 1, -1):
                options = [r for r in candidates if r.get('today') == count and r.get('phase') != 'extra']
                # Repeated copies of the identical result are one candidate.
                unique = {}
                for row in options:
                    unique[tuple(sorted((k, str(v)) for k, v in row.items() if k != 'id'))] = row
                options = list(unique.values())
                if len(options) == 1:
                    # A unique counter in today's chat is sufficient, including
                    # consecutive gaps. Do not compare or synthesize balances.
                    matches = options
                else:
                    expected = previous_balance(following)
                    matches = [r for r in options if r.get('user') in ('', user) and
                               expected is not None and r.get('balance') == expected]
                if len(matches) != 1:
                    break
                recovered = dict(matches[0])
                if recovered['kind'] == 'fish' and 'species' not in recovered:
                    break  # Do not fill a gap with another incomplete fish.
                recovered.pop('id', None)
                individual = hi > lo or any(r.get('individual_session') and r.get('user') == user and
                    r['time'][:10] == day and r.get('today') in (lo - 1, hi + 1) for r in records)
                recovered.update(user=user, recovered=True, individual_session=individual)
                history.update(history.new_id(), recovered)
                added += 1
                following = recovered
        history.recovery_status = f'누락 검사 완료: {added}건 복구'
        remaining = sum(hi - lo + 1 for lo, hi in missing_runs(history.snapshot(), user, day))
        if remaining:
            history.recovery_status += f' · {remaining}건 미복구 (오늘 날짜·카운트·소유자/골드 근거 부족)'
        history.version += 1
