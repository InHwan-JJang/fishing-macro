"""Atomic session CSV persistence and validated history loading."""
import csv
import json
import math
import os
from datetime import datetime
from pathlib import Path

FIELDS = ('id', 'time', 'user', 'kind', 'species', 'grade', 'size', 'today', 'limit',
          'gold', 'multiplier', 'balance', 'exp', 'pearls', 'damage', 'stones', 'bonus',
          'collection', 'luck_remaining', 'lucky', 'luck_granted', 'enhancement', 'card_attribute',
          'frost_remaining', 'fire_remaining', 'frost_active', 'fire_active',
          'frost_granted', 'fire_granted', 'any_lucky',
          'boss_name', 'raid_type', 'hp_current', 'hp_max', 'hp_percent')
INTEGERS = {'id', 'today', 'limit', 'gold', 'multiplier', 'balance', 'exp', 'pearls',
            'damage', 'stones', 'bonus', 'luck_remaining', 'enhancement', 'frost_remaining', 'fire_remaining', 'hp_current', 'hp_max'}
BOOLEANS = {'collection', 'lucky', 'luck_granted', 'frost_active', 'fire_active', 'frost_granted', 'fire_granted', 'any_lucky'}


def save_csv(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.csv.tmp')
    try:
        with temporary.open('w', encoding='utf-8-sig', newline='') as file:
            writer = csv.DictWriter(file, FIELDS, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(records)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_records(path):
    path = Path(path)
    with path.open(encoding='utf-8-sig', newline='') as file:
        if path.suffix.lower() == '.json':
            source = json.load(file)
            if not isinstance(source, list):
                raise ValueError('히스토리 JSON 목록이 아닙니다.')
        else:
            reader = csv.DictReader(file)
            if not {'time', 'kind'}.issubset(reader.fieldnames or []):
                raise ValueError('낚시 히스토리 CSV가 아닙니다.')
            source = list(reader)
    records, ids = [], set()
    for index, row in enumerate(source, 1):
        try:
            if not isinstance(row, dict):
                raise ValueError('기록 형식 오류')
            data = {}
            for key in FIELDS:
                value = row.get(key)
                if value is None or value == '':
                    continue
                if key in BOOLEANS:
                    if str(value).lower() not in ('true', 'false', '1', '0'):
                        raise ValueError(f'{key} 값 오류')
                    value = str(value).lower() in ('true', '1')
                elif key in INTEGERS:
                    value = int(str(value).replace(',', ''))
                    if value < 0:
                        raise ValueError(f'{key} 음수')
                elif key in ('size', 'hp_percent'):
                    value = float(value)
                    if not math.isfinite(value) or value < 0 or (key == 'hp_percent' and value > 100):
                        raise ValueError('크기 값 오류')
                elif not isinstance(value, str):
                    raise ValueError(f'{key} 문자열 오류')
                data[key] = value
            datetime.fromisoformat(data['time'])
            if data['kind'] not in ('fish', 'pearl', 'auto', 'raid'):
                raise ValueError('기록 종류 오류')
            data.setdefault('id', index)
            if data['id'] in ids:
                raise ValueError('중복 기록 ID')
            ids.add(data['id'])
            records.append(data)
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError(f'{index}번째 기록을 읽을 수 없습니다: {error}') from error
    return records


def delete_past_files(paths, directory, active_path):
    """Caller confirms exact selections; validate every path before deleting any."""
    root = Path(directory).resolve()
    active = Path(active_path).resolve()
    selected = [Path(p).resolve() for p in paths]
    for path in selected:
        if path == active or path.parent != root or path.suffix.lower() != '.csv' or not path.is_file():
            raise ValueError(f'삭제할 수 없는 파일: {path.name}')
    for path in selected:
        path.unlink()
