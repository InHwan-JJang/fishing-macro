"""Typed rows shared by history rendering and sorting; no desktop dependencies."""
from fishing_history import GRADES, sale_percent, EFFECTS

COLUMNS = ('time', 'band', 'today', 'species', 'grade', 'count', 'size', 'gold', 'exp', 'extra')
LABELS = ('시간', '구간', '오늘 낚시', '어종 / 종류', '등급', '누적 수', '크기(cm)', '획득 골드', '획득 EXP', '상세')
MODES = ('전체', '어종', '행운 기록', '진주', '도감 완성', '자동어', '레이드')


def row_for(group, grouped=False):
    latest = max(group, key=lambda r: (r['time'], r['id']))
    golds = [r['gold'] for r in group if 'gold' in r]
    exps = [r['exp'] for r in group if 'exp' in r]
    detail = []
    for key, title in (('pearls', '진주'), ('damage', '데미지'), ('stones', '해신석'), ('bonus', '달성 보상 G')):
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
                today=latest.get('today'), limit=latest.get('limit'),
                species=latest.get('species', {'auto':'자동어', 'pearl':'진주', 'raid':'레이드'}.get(latest['kind'], '어종 미확인')),
                grade=latest.get('grade', ''), count=latest.get('_cumulative', len(group)), size=latest.get('size'),
                gold=sum(golds) if golds else None,
                exp=sum(exps) if exps else None, extra=' · '.join(detail) or '—')


def make_rows(records, mode, grade='전체'):
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
            values.append(f"{value:,} / {row['limit']:,}" if value is not None and row.get('limit') is not None else '—')
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


def average_summaries(records, mode, grade='전체', grade_sorted=False):
    """Per-catch weighted averages across species, only in meaningful contexts."""
    if mode in ('진주', '자동어', '레이드', '도감 완성'):
        return []
    fish = [r for r in records if r['kind'] == 'fish' and
            (grade == '전체' or r.get('grade') == grade)]
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
