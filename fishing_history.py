"""Session history and game text parsing. No desktop input or clipboard access."""
from debug_logging import LOG, traced
from collections import deque
from datetime import datetime, timedelta, timezone
import re
import threading

KST = timezone(timedelta(hours=9))
GRADES = ("일반", "레어", "에픽", "전설", "신화")
COLORS = dict(zip(GRADES, ("#151515", "#1565c0", "#7b1fa2", "#df6500", "#c62828")))
EFFECTS = (("luck", "행운"), ("frost", "특수 행운(만년서리의 숨결)"),
           ("fire", "특수 행운(만년화리의 숨결)"))
HEADER = re.compile(r"^\[(.+?)\] \[(?:오전|오후) \d{1,2}:\d{2}\] (.*)$")
COMMAND = re.compile(r"^@(\S+)\s+(낚시|수동|가방|미끼(?:\s+\d+)?)\s*$")


def now_kst():
    return datetime.now(KST)


def next_reset(now):
    target = now.replace(hour=0, minute=0, second=5, microsecond=0)
    return target if now < target else target + timedelta(days=1)


def number(text, pattern):
    match = re.search(pattern, text)
    return int(match[1].replace(",", "")) if match else None


def parse_details(text):
    data = {}
    extra = re.search(r'추가 낚시:\s*([\d,]+)\s*/\s*([\d,]+)', text)
    if extra:
        data.update(phase='extra', today=int(extra[1].replace(',', '')), limit=int(extra[2].replace(',', '')),
                    multiplier=0, gold=0, exp=0, kind='fish')
    patterns = {
        "gold": r"획득 골드:\s*([\d,]+)G",
        "balance": r"보유 골드:\s*([\d,]+)G",
        "multiplier": r"획득 골드:[^\n]*?\((\d+)%\)",
        "exp": r"경험치:\s*([\d,]+)\s*EXP",
        "today": r"오늘 낚시:\s*([\d,]+)",
        "limit": r"오늘 낚시:\s*[\d,]+\s*/\s*([\d,]+)",
        "pearls": r"보유 진주가\s*\+\s*([\d,]+)",
        "damage": r"(?:잔향 피해|가한 데미지|피해|데미지):\s*([\d,]+)",
        "stones": r"해신석\s*\+\s*([\d,]+)",
        "bonus": r"달성 보상:\s*골드\s*\+\s*([\d,]+)",
        "frost_remaining": r"만년서리의\s*숨결\s*:\s*남은\s*([\d,]+)\s*회",
        "fire_remaining": r"만년화리의\s*숨결\s*:\s*남은\s*([\d,]+)\s*회",
        "luck_remaining": r"행운\s*:\s*남은\s*([\d,]+)\s*회\s*낚시",
    }
    for key, pattern in patterns.items():
        value = number(text, pattern)
        if value is not None:
            data[key] = value
    fish = re.search(r"\[([^\]\n]+)\]\s*([\d,.]+)\s*(cm|m)\b", text)
    if fish:
        size = float(fish[2].replace(",", ""))
        data.update(species=fish[1].strip(), size=round(size * (100 if fish[3] == "m" else 1), 6))
    else:
        # A catch card need not have a physical length (e.g. equipment '9강').
        # Still consume its response slot so the next fish cannot inherit it.
        # Skip the [grade] summary and keep looking for size-less cards.
        card = next((match for match in re.finditer(r"^\[([^\]\n]+)\]([^\n]*)", text, re.MULTILINE)
                     if match[1].strip() not in GRADES), None)
        if card:
            data['species'] = card[1].strip()
            attribute = card[2].strip()
            if attribute:
                data['card_attribute'] = attribute
            enhancement = re.fullmatch(r"([\d,]+)\s*강", attribute)
            if enhancement:
                data['enhancement'] = int(enhancement[1].replace(',', ''))
    grade = re.search(r"등급:\s*(일반|레어|에픽|전설|신화)", text)
    if grade:
        data["grade"] = grade[1]
    if "도감 완성!" in text and "최대 크기" in text:
        data["collection"] = True
    world_boss = re.search(r"(?:^|\n|@\S+\s+)월드\s*보스\s+([^\n]+)", text)
    echo_boss = re.search(r"(?:^|\n|@\S+\s+)([^\n@]+?의 잔향)(?:을 마주쳤|\s*$)", text, re.MULTILINE)
    if world_boss:
        data.update(raid_type='월드 보스', boss_name=re.sub(r'\s+조우[!！]?.*$', '', world_boss[1]).strip())
        damage = number(text, r"([\d,]+)\s*데미지")
        if damage is not None:
            data.setdefault('damage', damage)
        hp = re.search(r"HP\s*\[[^\]\n]*\]\s*([\d.]+)%\s*\n([\d,]+)\s*/\s*([\d,]+)", text)
        if hp:
            data.update(hp_percent=float(hp[1]), hp_current=int(hp[2].replace(',', '')), hp_max=int(hp[3].replace(',', '')))
    elif echo_boss:
        data.update(raid_type='잔향', boss_name=echo_boss[1].strip())
    if re.search(r"운영자(?:가 찾아왔|\s*출현)", text):
        data['kind'] = 'operator'
        for key, pattern in {
            'gold': r'([\d,]+)\s*G\b',
            'pearls': r'진주\s*\+?\s*([\d,]+)\s*개',
            'bait': r'미끼\s*\+?\s*([\d,]+)\s*개',
            'stones': r'해신석\s*\+?\s*([\d,]+)\s*개',
        }.items():
            reward = number(text, pattern)
            if reward is not None:
                data[key] = reward
    elif "자동어" in text:
        data["kind"] = "auto"
    elif world_boss or echo_boss or "잔향 피해" in text or "레이드" in text or "잔향을 마주쳤" in text:
        data["kind"] = "raid"
        reward = number(text, r"(?:잔향 보상|즉시 보상):\s*([\d,]+)G")
        if reward is not None:
            data.setdefault("gold", reward)
    elif "진주 발견" in text or "pearls" in data:
        data["kind"] = "pearl"
    elif 'species' in data or ('today' in data and ('gold' in data or 'exp' in data)):
        data["kind"] = "fish"
    return data


def segment(record):
    if record.get('phase') == 'extra':
        return '추가 낚시 · 0%'
    count = record.get("today")
    if count is None:
        return "횟수 미확인"
    weekend = datetime.fromisoformat(record["time"]).weekday() >= 5
    middle = 2500 if weekend else 2000
    if count <= 500:
        return "1~500회 · 150%"
    if count <= middle:
        return f"501~{middle}회 · 120%"
    return f"{middle + 1}회~ · 100%"


def messages(text):
    result = []
    for line in text.splitlines():
        match = HEADER.match(line)
        if match:
            result.append([match[1], match[2]])
        elif result and line.strip():
            result[-1][1] += "\n" + line
    return [tuple(item) for item in result]


class History:
    """One application session; records survive stopping/restarting a job."""
    def __init__(self, path=None):
        self._lock = threading.RLock()
        self.records = {}
        self.serial = 0
        self.version = 0
        self.path = path
        self.saved_version = 0
        self.save_error = None
        self.recovery_pending = False
        self.recovery_attempted = set()
        self.recovery_status = ''

    @traced
    def request_recovery(self):
        with self._lock:
            self.recovery_pending = True
            self.recovery_status = '다음 낚시 결과를 복사할 때 한 번 검사합니다.'
            self.version += 1

    def new_id(self):
        with self._lock:
            self.serial += 1
            return self.serial

    def update(self, key, data, stamp=None):
        with self._lock:
            old = self.records.get(key, {})
            merged = dict(old, **data)
            merged.setdefault("time", (stamp or now_kst()).isoformat(timespec="seconds"))
            merged.setdefault("id", key)
            if merged != old:
                LOG.debug("HISTORY update key=%s data=%r", key, merged)
                self.records[key] = merged
                self.version += 1
                self.save()

    def save(self):
        from history_storage import save_csv
        with self._lock:
            if self.path is None or self.saved_version == self.version:
                return self.save_error is None
            try:
                save_csv(self.path, self.snapshot())
                self.saved_version = self.version
                self.save_error = None
                return True
            except OSError as error:
                LOG.exception("HISTORY save failed path=%s", self.path)
                self.save_error = str(error)
                return False

    @classmethod
    def load(cls, path):
        from history_storage import load_records
        records = load_records(path)
        history = cls()  # Imported history is read-only and never merged into live captures.
        history.records = {r['id']: r for r in records}
        history.serial = max(history.records, default=0)
        history.version = 1
        return history

    def snapshot(self):
        with self._lock:
            return annotate_luck([dict(r) for r in self.records.values() if r.get("kind")])


class DailyHistory(History):
    """Daily files, with stable in-process IDs for responses crossing midnight."""
    def __init__(self, directory, legacy_directory=None):
        from pathlib import Path
        super().__init__()
        self.directory = Path(directory)
        self.legacy_directory = Path(legacy_directory) if legacy_directory else None
        self.loaded_days = set()
        self.dirty_days = set()
        self.day = None
        self.ensure_day()

    def ensure_day(self):
        from history_storage import load_records, save_csv
        day = now_kst().date().isoformat()
        with self._lock:
            if day == self.day:
                return
            LOG.info("HISTORY day change previous=%s next=%s", self.day, day)
            path = self.directory / f'{day}.csv'
            if day not in self.loaded_days:
                if path.exists():
                    rows = load_records(path)
                    if any(r['time'][:10] != day for r in rows):
                        raise ValueError(f'{path.name}: 다른 날짜의 기록이 포함되어 있습니다.')
                else:
                    rows = []
                    # One-time import only when the canonical daily file is absent.
                    for folder in (self.directory, self.legacy_directory):
                        if folder and folder.exists():
                            for old in sorted(folder.glob('*.csv')):
                                rows.extend(r for r in load_records(old) if r['time'][:10] == day)
                    unique = {}
                    for row in rows:
                        # Same user's same daily catch across copied session exports.
                        identity = ((row.get('user'), row['kind'], row.get('phase', 'daily'), row['today'])
                                    if row.get('today') is not None and row['kind'] in ('fish', 'pearl', 'raid')
                                    else tuple(sorted((k, str(v)) for k, v in row.items() if k != 'id')))
                        unique.setdefault(identity, {}).update(row)
                    rows = list(unique.values())
                    for index, row in enumerate(rows, 1):
                        row['id'] = index
                    save_csv(path, rows)
                for row in rows:
                    self.serial += 1
                    row['id'] = self.serial
                    self.records[self.serial] = row
                self.loaded_days.add(day)
            self.day, self.path = day, path
            self.version += 1

    def new_id(self):
        with self._lock:
            self.ensure_day()
            return super().new_id()

    def update(self, key, data, stamp=None):
        with self._lock:
            self.ensure_day()
            date = self.records.get(key, {}).get('time', (stamp or now_kst()).isoformat())[:10]
            self.dirty_days.add(date)
            super().update(key, data, stamp)

    def snapshot(self):
        with self._lock:
            return annotate_luck([dict(r) for r in self.records.values()
                                  if r.get('kind') and r['time'][:10] == self.day])

    def save(self):
        from history_storage import save_csv
        with self._lock:
            try:
                for day in list(self.dirty_days):
                    rows = annotate_luck([dict(r) for r in self.records.values()
                                          if r.get('kind') and r['time'][:10] == day])
                    save_csv(self.directory / f'{day}.csv', rows)
                    self.dirty_days.remove(day)
                self.save_error = None
                self.saved_version = self.version
                return True
            except OSError as error:
                LOG.exception("HISTORY save failed path=%s", self.path)
                self.save_error = str(error)
                return False


class Observer:
    """Read only newly copied messages; enrich an existing catch with later card text."""
    def __init__(self, history, user):
        self.history, self.user = history, user
        self.previous = []
        self.pending = deque()
        self.active = None
        self.bot = None
        self.today = None
        self.limit = None
        self.responses = deque(maxlen=128)
        self.buff_requests = deque()
        self.buff_seen = set()
        self.bag_count = None
        self.bag_version = 0
        self.awaiting_baseline = False

    def baseline(self, text):
        LOG.debug("OBSERVER baseline chars=%s user=%r", len(text), self.user)
        self.previous = messages(text)

    def observe(self, text):
        self.observed_catch = False
        self._observe(text)
        if self.observed_catch:
            from history_recovery import recover_missing
            recover_missing(self.history, text, self.user, self.bot)

    def _observe(self, text):
        if self.awaiting_baseline:
            self.baseline(text)
            self.awaiting_baseline = False
            return
        current = messages(text)
        old = self.previous
        self.previous = current
        # Normal append, including a multi-line card finishing in the last message.
        prefix = 0
        while prefix < min(len(old), len(current)) and old[prefix] == current[prefix]:
            prefix += 1
        if prefix == len(old):
            fresh = current[prefix:]
        elif prefix == len(old) - 1 and prefix < len(current) and current[prefix][0] == old[-1][0] and current[prefix][1].startswith(old[-1][1]):
            fresh = [(current[prefix][0], current[prefix][1][len(old[-1][1]):])] + current[prefix + 1:]
        else:
            # Kakao may discard older messages from its copied window.
            overlap = 0
            for size in range(min(len(old), len(current)), 0, -1):
                if old[-size:] == current[:size]:
                    overlap = size
                    break
            if old and not overlap:
                LOG.warning("OBSERVER lost overlap; rebaseline old=%s current=%s", len(old), len(current))
                return  # Rebaseline instead of counting old history again.
            fresh = current[overlap:]
        for sender, body in fresh:
            self._consume(sender, body)

    def _consume(self, sender, body):
        command = COMMAND.match(body)
        if command:
            LOG.debug("CHAT command sender=%r body=%r", sender, body)
            self.bot = command[1]
            self.pending.append((sender, command[2], self.history.new_id()))
            return
        if sender != self.bot:
            return
        LOG.debug("CHAT bot=%r body=%r", sender, body)
        details = parse_details(body)
        if not details.get("kind") and ("숨을 고른" in body or "아직" in body):
            details["kind"] = "other"
        if body.startswith("@사용자") or body.startswith("@" + self.user):
            if self.pending:
                owner, command, key = self.pending.popleft()
                self.active = dict(owner=owner, command=command, key=key, text="", kind=details.get("kind"), complete=False)
                self.responses.append(self.active)
            elif details.get("kind"):
                # A result without a corresponding command must not overwrite
                # the preceding player's catch (e.g. a missed command).
                self.active = None
        elif details.get('kind') == 'operator' or details.get("species") or "pearls" in details or "damage" in details or "boss_name" in details or "미끼:" in body:
            card_kind = ('operator' if details.get('kind') == 'operator' else "fish" if "species" in details else "pearl" if "pearls" in details
                         else "raid" if "damage" in details or "boss_name" in details else "bag")
            candidates = [r for r in self.responses if not r["complete"] and
                          (r["kind"] == card_kind or
                           (r["kind"] is None and r["command"] == "낚시" and card_kind in ("fish", "pearl", "raid", "operator")) or
                           (card_kind == "bag" and r["command"] == "가방"))]
            # Both players' responses remain pending until their own card arrives.
            # A pearl card can therefore never be appended to a fish response.
            self.active = candidates[0] if candidates else None
        if not self.active:
            return
        context = self.active
        context["text"] += "\n" + body
        owner, command, key = context["owner"], context["command"], context["key"]
        data = parse_details(context["text"])
        if data.get("kind"):
            context["kind"] = data["kind"]
        if "species" in data or "pearls" in data or "damage" in data or (data.get('kind') == 'operator' and 'gold' in data):
            context["complete"] = True
        if owner != self.user and not getattr(self, 'capture_all', False):
            return
        if command == "가방":
            count = number(context["text"], r"미끼:\s*([\d,]+)\s*개")
            if count is not None and self.bag_count is None:
                self.bag_count = count
                self.bag_version += 1
                context["complete"] = True
            return
        if command != "낚시":
            return
        if not data:
            return
        if data.get('kind') in ('fish', 'pearl', 'auto', 'raid'):
            self.observed_catch = True
        if "today" in data:
            self.today = data["today"]
        if "limit" in data:
            self.limit = data["limit"]
        if data.get("kind") == "auto" and not getattr(self, 'capture_all', False):
            data.setdefault("today", (self.today or 0) + 1)
        if data.get("kind") == "raid" and self.limit and not getattr(self, 'capture_all', False):
            data.setdefault("today", self.limit)
            data.setdefault("limit", self.limit)
        data["user"] = owner
        self.history.update(key, data)
        current = next((r for r in self.history.snapshot() if r['id'] == key), {})
        grants = [current[f'{effect}_remaining'] for effect, _ in EFFECTS
                  if current.get(f'{effect}_granted')]
        if grants and key not in self.buff_seen:
            self.buff_seen.add(key)
            # Concurrent effects cover the same future casts; do not add durations.
            self.buff_requests.append(max(grants))



def aggregate(records):
    grouped = {}
    for record in records:
        if record.get("kind") != "fish":
            continue
        name = record.get("species", "어종 미확인")
        item = grouped.setdefault(name, dict(species=name, grade=record.get("grade", ""), count=0, gold=0, gold_count=0, exp=0, collection=False))
        item["count"] += 1
        if "gold" in record:
            item["gold"] += record["gold"]
            item["gold_count"] += 1
        item["exp"] += record.get("exp", 0)
        item["collection"] |= record.get("collection", False)
    return list(grouped.values())


def annotate_luck(records):
    """Track each effect independently, isolated by player and day."""
    anchors = {}
    for record in sorted(records, key=lambda r: (r['time'], r['id'])):
        count = record.get('today')
        for effect, _ in EFFECTS:
            key = (record.get('user'), record['time'][:10], record.get('phase', 'daily'), effect)
            remaining = record.get(f'{effect}_remaining')
            anchor = anchors.get(key)
            applied = granted = False
            if record['kind'] in ('fish', 'pearl'):
                if anchor and count is not None:
                    distance = count - anchor[0]
                    applied = 0 < distance <= anchor[1]
                if remaining is not None and remaining > 0:
                    expected = max(0, anchor[1] - (count - anchor[0])) if anchor and count is not None and count > anchor[0] else 0
                    granted = remaining % 10 == 0 and remaining > expected
                    applied = not granted
                if remaining is not None and count is not None:
                    anchors[key] = (count, remaining)
                elif anchor and count is not None and (count <= anchor[0] or count > anchor[0] + anchor[1]):
                    anchors.pop(key, None)
            record['lucky' if effect == 'luck' else f'{effect}_active'] = applied
            record[f'{effect}_granted'] = granted
        record['any_lucky'] = record['lucky'] or record['frost_active'] or record['fire_active']
    return records


def sale_percent(record):
    if record.get('multiplier') in (150, 120, 100, 0):
        return record['multiplier']
    count = record.get('today')
    if count is None:
        return None
    weekend = datetime.fromisoformat(record['time']).weekday() >= 5
    if count > record.get('limit', 4000 if weekend else 3000):
        return 0
    return 150 if count <= 500 else 120 if count <= (2500 if weekend else 2000) else 100
