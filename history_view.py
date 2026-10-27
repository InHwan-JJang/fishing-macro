"""Typed rows shared by history rendering and sorting; no desktop dependencies."""
from fishing_history import GRADES, sale_percent, EFFECTS

COLUMNS = ('time', 'band', 'today', 'species', 'grade', 'count', 'size', 'gold', 'average', 'exp', 'extra')
LABELS = ('시간', '구간', '오늘 낚시', '어종 / 종류', '등급', '마릿수', '크기(cm)', '획득 골드', '평균 골드', '획득 EXP', '상세')
MODES = ('모두보기', '시간순', '등급별', '구간별', '행운', '도감 완성', '자동어', '진주', '레이드')


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
                grade=latest.get('grade', ''), count=len(group), size=latest.get('size'),
                gold=sum(golds) if golds else None, average=sum(golds)/len(golds) if golds else None,
                exp=sum(exps) if exps else None, extra=' · '.join(detail) or '—')


def make_rows(records, mode, grade='전체'):
    fish = [r for r in records if r['kind'] == 'fish']
    if mode in ('모두보기', '등급별', '구간별', '도감 완성'):
        chosen = fish
        if mode == '도감 완성':
            completed = {r.get('species') for r in fish if r.get('collection')}
            chosen = [r for r in fish if r.get('species') in completed]
        chosen = [r for r in chosen if grade == '전체' or r.get('grade') == grade]
        groups = {}
        for r in chosen:
            key = (r.get('species', '어종 미확인'),)
            if mode == '구간별':
                key += (r['time'][:10], sale_percent(r))
            groups.setdefault(key, []).append(r)
        rows = [row_for(group, True) for group in groups.values()]
        if mode == '등급별':
            rows.sort(key=lambda r: (GRADES.index(r['grade']) if r['grade'] in GRADES else 99, r['species']))
        elif mode == '구간별':
            rows.sort(key=lambda r: (r['time'][:10], -(r['band'] if r['band'] is not None else -1), r['species']))
        else:
            rows.sort(key=lambda r: r['species'])
        return rows
    kind = {'자동어':'auto', '진주':'pearl', '레이드':'raid'}.get(mode)
    chosen = [r for r in records if (not kind or r['kind'] == kind) and (grade == '전체' or r.get('grade') == grade)]
    if mode == '행운':
        chosen = [r for r in chosen if r.get('any_lucky', r.get('lucky'))]
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
        elif column in ('size', 'average'):
            values.append(f'{value:,.1f}')
        elif column in ('count', 'gold', 'exp'):
            values.append(f'{value:,}')
        else:
            values.append(value)
    return values
