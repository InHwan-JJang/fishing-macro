"""Typed rows shared by history rendering and sorting; no desktop dependencies."""
from fishing_history import GRADES, sale_percent, EFFECTS

COLUMNS = ('time', 'band', 'today', 'species', 'grade', 'count', 'size', 'gold', 'exp', 'extra')
LABELS = ('시간', '구간', '오늘 낚시', '어종 / 종류', '등급', '누적 수', '크기(cm)', '획득 골드', '획득 EXP', '상세')
MODES = ('전체', '어종', '구간', '행운', '진주', '도감', '자동어', '레이드', '개별 세션')


def canonical_mode(mode):
    return {'구간': '구간별', '행운': '행운 기록', '도감': '도감 완성'}.get(mode, mode)
RAID_COLUMNS = ('time', 'boss_name', 'raid_type', 'damage', 'gold', 'stones', 'bonus', 'hp_current', 'hp_max', 'hp_percent')
RAID_LABELS = ('시간', '보스명', '조우 유형', '데미지', '보상 골드', '해신석', '달성 보상 골드', '남은 HP', '최대 HP', 'HP(%)')


def raid_rows(records):
    return [{key: (r['time'][:19].replace('T', ' ') if key == 'time' else r.get(key))
             for key in RAID_COLUMNS}
            for r in sorted(records, key=lambda r: (r['time'], r['id']), reverse=True)
            if r['kind'] == 'raid']


def display_raid_row(row):
    return ['—' if row[key] is None else f'{row[key]:,}' if isinstance(row[key], (int, float)) else row[key]
            for key in RAID_COLUMNS]


def row_for(group, grouped=False):
    latest = max(group, key=lambda r: (r['time'], r['id']))
    golds = [r['gold'] for r in group if 'gold' in r]
    exps = [r['exp'] for r in group if 'exp' in r]
    detail = []
    if latest.get('recovered'):
        detail.append('누락 복구')
    if latest.get('individual_session'):
        detail.append('개별 세션')
    if latest.get('boss_name'):
        detail.append(latest.get('raid_type', '레이드') + ': ' + latest['boss_name'])
    for key, title in (('pearls', '진주'), ('bait', '미끼'), ('damage', '데미지'), ('stones', '해신석'), ('bonus', '달성 보상 G')):
        if any(key in r for r in group):
            detail.append(f"{title} {sum(r.get(key, 0) for r in group):,}")
    if any(r.get('collection') for r in group):
        detail.append('도감 완성')
    for effect, label in EFFECTS:
        active = 'lucky' if effect == 'luck' else f'{effect}_active'
        lucky = sum(bool(r.get(active)) for r in group)
        if grouped and lucky > 1:
            detail.append(f'{label} 소비 합계 {lucky}회')
        if latest.get(f'{effect}_granted'):
            detail.append(f"{label} 부여 - 남은 횟수 {latest[f'{effect}_remaining']}회" if effect != 'luck' else
                          f"행운 부여 - 남은 행운 {latest['luck_remaining']}회")
        elif latest.get(active):
            remaining = latest.get(f'{effect}_remaining', 0)
            detail.append(f"{label} 소비 - 남은 횟수 {remaining}회" if effect != 'luck' else
                          f"행운 소비 - 남은 행운 {remaining}회")
        elif f'{effect}_remaining' in latest:
            detail.append(f"{label} 남은 횟수 {latest[f'{effect}_remaining']}회")
    if 'enhancement' in latest:
        detail.append(f"{latest['enhancement']}강")
    elif latest.get('card_attribute'):
        detail.append(latest['card_attribute'])
    return dict(time=latest['time'][:19].replace('T', ' '), band=sale_percent(latest),
                today=latest.get('today'), limit=latest.get('limit'), phase=latest.get('phase'),
                species=latest.get('species', latest.get('boss_name', {'auto':'자동어', 'pearl':'진주', 'raid':'레이드', 'operator':'운영자 출현'}.get(latest['kind'], '어종 미확인'))),
                grade=latest.get('grade', ''), count=latest.get('_cumulative', len(group)), size=latest.get('size'),
                gold=sum(golds) if golds else None,
                exp=sum(exps) if exps else None, extra=' · '.join(detail) or '—')


def make_rows(records, mode, grade='전체'):
    mode = canonical_mode(mode)
    counters = {}
    annotated = []
    for original in sorted(records, key=lambda r: (r['time'], r['id'])):
        r = dict(original)
        key = (r.get('user'), r['time'][:10], r['kind'],
               r.get('species', r['id'] if r['kind'] == 'fish' else r['kind']))
        counters[key] = counters.get(key, 0) + 1
        r['_cumulative'] = counters[key]
        annotated.append(r)
    chosen = [r for r in annotated if grade == '전체' or r.get('grade') == grade]
    if mode == '개별 세션':
        chosen = [r for r in chosen if r.get('individual_session')]
    if mode in ('어종', '구간별', '도감 완성'):
        chosen = [r for r in chosen if r['kind'] == 'fish']
        if mode == '도감 완성':
            chosen = [r for r in chosen if r.get('collection')]
        groups = {}
        for r in chosen:
            key = (r.get('user'), r['time'][:10], r.get('species', '어종 미확인'))
            if mode == '구간별':
                key += (sale_percent(r),)
            groups.setdefault(key, []).append(r)
        rows = []
        for group in groups.values():
            row = row_for(group, True)
            if mode in ('어종', '구간별'):
                row['count'] = len(group)
            row['_order'] = max((r['time'], r['id']) for r in group)
            rows.append(row)
        return sorted(rows, key=lambda r:r['_order'], reverse=True)
    kind = {'자동어':'auto', '진주':'pearl', '레이드':'raid'}.get(mode)
    if kind:
        chosen = [r for r in chosen if r['kind'] == kind]
    if mode == '행운 기록':
        chosen = [r for r in chosen if r.get('any_lucky', r.get('lucky')) or
                  any(r.get(f'{effect}_granted') for effect, _ in EFFECTS)]
    return [row_for([r]) for r in sorted(chosen, key=lambda r: (r['time'], r['id']), reverse=True)]


def sort_rows(rows, column=None, direction=0):
    if not column or not direction:
        return list(rows)
    known, missing = [], []
    for row in rows:
        (missing if row.get(column) is None or (column == 'grade' and row['grade'] not in GRADES) else known).append(row)
    key = (lambda r: GRADES.index(r['grade'])) if column == 'grade' else (lambda r: r[column])
    return sorted(known, key=key, reverse=direction == 2) + missing


def display_row(row):
    values = []
    for column in COLUMNS:
        value = row[column]
        if column == 'today':
            values.append(('추가 ' if row.get('phase') == 'extra' else '') + f"{value:,} / {row['limit']:,}" if value is not None and row.get('limit') is not None else '—')
        elif value is None or value == '':
            values.append('—')
        elif column == 'band':
            values.append(f'{value}%')
        elif column == 'size':
            values.append(f'{value:,.1f}')
        elif column in ('count', 'gold', 'exp'):
            values.append(f'{value:,}')
        else:
            values.append(value)
    return values


def average_summaries(records, mode, grade='전체', grade_sorted=False, exclude_extra=False):
    """Per-catch weighted averages across species, only in meaningful contexts."""
    mode = canonical_mode(mode)
    if mode in ('진주', '자동어', '레이드', '도감 완성'):
        return []
    fish = [r for r in records if r['kind'] == 'fish' and
            (grade == '전체' or r.get('grade') == grade) and
            (not exclude_extra or (r.get('phase') != 'extra' and sale_percent(r) != 0))]
    groups = {}
    if mode == '구간별':
        for r in fish:
            band = sale_percent(r)
            label = f"{r['time'][:10]} {str(band)+'%' if band is not None else '구간 미확인'}"
            groups.setdefault(label, []).append(r)
    elif mode == '행운 기록':
        groups['행운 소비'] = [r for r in fish if r.get('any_lucky', r.get('lucky'))]
    elif grade != '전체':
        groups[grade] = fish
    elif grade_sorted:
        groups = {g: [r for r in fish if r.get('grade') == g] for g in GRADES}
    elif mode == '어종':
        groups['전체 어종'] = fish
    result = []
    for label, group in groups.items():
        known = [r['gold'] for r in group if r.get('gold') is not None]
        if not group and grade_sorted:
            continue
        average = f'{sum(known)/len(known):,.1f}G' if known else '—'
        result.append(f"{label}: 판매합계 {sum(known):,}G · 평균 {average} (골드 확인 {len(known):,}마리)")
    return result


def grade_probabilities(records, mode):
    """Observed per-catch grade ratios, before the grade radio filter."""
    mode = canonical_mode(mode)
    if mode not in ('전체', '어종', '구간별', '행운 기록', '도감 완성'):
        return []
    fish = [r for r in records if r['kind'] == 'fish']
    if mode == '행운 기록':
        fish = [r for r in fish if r.get('any_lucky', r.get('lucky'))]
    elif mode == '도감 완성':
        fish = [r for r in fish if r.get('collection')]
    groups = {'기록': fish}
    if mode == '구간별':
        groups = {}
        for r in fish:
            band = sale_percent(r)
            groups.setdefault(f'{band}%' if band is not None else '구간 미확인', []).append(r)
    result = []
    for label, group in groups.items():
        known = [r for r in group if r.get('grade') in GRADES]
        ratios = ' / '.join(f"{g} {sum(r['grade'] == g for r in known) / len(known) * 100:.1f}%" if known else f'{g} —' for g in GRADES)
        result.append(f'{label} 등급 비율 (실측 {len(known):,}마리, 등급 미확인 {len(group)-len(known):,}건 제외): {ratios}')
    return result
