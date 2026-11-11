"""Izvlači referencu za kazne i kontrolne liste iz Excel fajlova."""

from __future__ import annotations

import re
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
FINES = ROOT / 'Kaznene mere.xlsx'
LISTS = ROOT / 'Kontrolne liste latinica.xlsx'

PARTY_SHEETS = (
    ('pravno', 'Pravno lice', 'PRAVNO LICE'),
    ('preduzetnik', 'Preduzetnik', 'PREDUZETNIK'),
    ('fizicko', 'Fizičko lice', 'FIZIČKO LICE'),
)
PENALTY_PREFIXES = ('PRIVREDNI PRESTUP', 'PREKRŠAJ')
ACTS_PREFIX = 'RADNJA KOJA PREDSTAVLJA'

CYR = str.maketrans({
    'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Ђ': 'Đ', 'Е': 'E', 'Ж': 'Ž',
    'З': 'Z', 'И': 'I', 'Ј': 'J', 'К': 'K', 'Л': 'L', 'Љ': 'Lj', 'М': 'M', 'Н': 'N',
    'Њ': 'Nj', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'Ћ': 'Ć', 'У': 'U',
    'Ф': 'F', 'Х': 'H', 'Ц': 'C', 'Ч': 'Č', 'Џ': 'Dž', 'Ш': 'Š',
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'ђ': 'đ', 'е': 'e', 'ж': 'ž',
    'з': 'z', 'и': 'i', 'ј': 'j', 'к': 'k', 'л': 'l', 'љ': 'lj', 'м': 'm', 'н': 'n',
    'њ': 'nj', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'ћ': 'ć', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'č', 'џ': 'dž', 'ш': 'š',
})


def lat(text) -> str:
    if text is None:
        return ''
    return str(text).translate(CYR).strip()


def clean_text(value) -> str:
    return ' '.join(lat(value).split())


def _is_penalty_heading(text: str) -> bool:
    upper = text.upper()
    return any(upper.startswith(prefix) for prefix in PENALTY_PREFIXES)


def _is_acts_heading(text: str) -> bool:
    return text.upper().startswith(ACTS_PREFIX)


def parse_fines_sheet(ws) -> list[dict]:
    groups: list[dict] = []
    current = None
    for row in ws.iter_rows(min_row=1, max_col=1, values_only=True):
        text = clean_text(row[0] if row else '')
        if not text:
            continue
        if text.casefold().startswith('brisana'):
            continue
        if _is_penalty_heading(text):
            current = {
                'penalty': text,
                'acts_label': '',
                'items': [],
            }
            groups.append(current)
            continue
        if current is None:
            continue
        if _is_acts_heading(text):
            current['acts_label'] = text
            continue
        current['items'].append(text)
    return [group for group in groups if group['items']]


def parse_fines_catalog() -> dict:
    wb = openpyxl.load_workbook(FINES, data_only=True)
    parties = []
    for key, label, sheet_name in PARTY_SHEETS:
        if sheet_name not in wb.sheetnames:
            raise ValueError(f'Nedostaje list „{sheet_name}” u {FINES.name}.')
        parties.append({
            'key': key,
            'label': label,
            'groups': parse_fines_sheet(wb[sheet_name]),
        })
    return {'kind': 'fines', 'parties': parties}


def fines_body(catalog: dict | None = None) -> str:
    data = catalog or parse_fines_catalog()
    lines = [
        'Kaznene mere prema Zakonu o bezbednosti hrane.',
        '',
        f'Izvor: {FINES.name} — univerzalna referenca za pravno lice, '
        'preduzetnika i fizičko lice.',
        '',
    ]
    for party in data['parties']:
        lines.append(party['label'].upper())
        lines.append('—')
        for group in party['groups']:
            lines.append(group['penalty'])
            if group.get('acts_label'):
                lines.append(group['acts_label'])
            for index, item in enumerate(group['items'], 1):
                lines.append(f'{index}. {item}')
            lines.append('')
        lines.append('')
    return '\n'.join(lines).strip() + '\n'


def _fines_entry():
    catalog = parse_fines_catalog()
    return {
        'code': 'IN-01',
        'kind': 'IN',
        'title': 'Kaznene mere',
        'source_filename': FINES.name,
        'body': fines_body(catalog),
        'checklist': catalog,
        'is_fixed': True,
        'note': '',
        'sort_order': 10,
    }


LEGEND_LINE = re.compile(
    r'^(DA|NE|NP|A|B|V|G)(?:\s*[-–—]\s*(.+))?$',
    re.IGNORECASE,
)
HEADER_ROWS = {'NAZIV SUBJEKTA', 'PITANJE'}


def _validated_rows(ws):
    rows: set[int] = set()
    values = None
    validations = getattr(ws, 'data_validations', None)
    if not validations:
        return rows, values
    for rule in validations.dataValidation:
        formula = (rule.formula1 or '').strip().strip('"')
        if (rule.type or '') != 'list' or not formula or formula.startswith('#'):
            continue
        parsed = [part.strip() for part in formula.split(',') if part.strip()]
        if not parsed:
            continue
        for cell_range in rule.sqref.ranges:
            if cell_range.min_col <= 3 <= cell_range.max_col:
                values = parsed
                rows.update(range(cell_range.min_row, cell_range.max_row + 1))
    return rows, values


def _legend(ws, codes):
    meanings = {code: '' for code in codes}
    wanted = {code.upper(): code for code in codes}
    for row in ws.iter_rows(min_row=1, max_col=1, values_only=True):
        text = clean_text(row[0] if row else '')
        match = LEGEND_LINE.fullmatch(text)
        if not match:
            continue
        code = wanted.get(match.group(1).upper())
        if code is None:
            continue
        meaning = clean_text(match.group(2) or '')
        if meaning.isupper():
            meaning = meaning.capitalize()
        meanings[code] = meaning
    return [
        {'value': code, 'label': code, 'meaning': meanings[code]}
        for code in codes
    ]


def _render_body(title: str, scale, items) -> str:
    lines = [
        f'Kontrolna lista: {title}',
        '',
        'Naziv subjekta:',
        '',
    ]
    number = 0
    for item in items:
        if item['type'] == 'section':
            lines.extend(['', item['text'], ''])
        elif item['type'] == 'q':
            number += 1
            lines.append(f"{number}. {item['text']}")
        elif item['type'] == 'remarks':
            lines.extend(['', 'PRIMEDBE I SUGESTIJE', ''])
    lines.extend(['', 'Odgovori'])
    for option in scale:
        if option['meaning']:
            lines.append(f"{option['label']} — {option['meaning']}")
        else:
            lines.append(option['label'])
    return '\n'.join(lines).strip() + '\n'


def parse_checklist(sheet_name: str) -> dict:
    wb = openpyxl.load_workbook(LISTS, data_only=False)
    ws = wb[sheet_name]
    question_rows, scale_values = _validated_rows(ws)
    if not scale_values:
        raise ValueError(f'Lista {sheet_name} nema ponuđene odgovore.')
    items = []
    for row in range(1, ws.max_row + 1):
        text = clean_text(ws.cell(row, 1).value)
        if not text:
            continue
        upper = text.upper()
        if upper in HEADER_ROWS:
            continue
        if upper.startswith('PRIMEDBE'):
            items.append({'type': 'remarks'})
            break
        if upper.startswith(('ČEKIRATI', 'CHEKIRATI', 'NAPOMENA')):
            break
        if row in question_rows:
            items.append({'type': 'q', 'key': str(row), 'text': text})
        elif row > 3:
            items.append({'type': 'section', 'text': text})
    title = clean_text(ws.cell(1, 2).value) or clean_text(ws.cell(1, 1).value) or sheet_name
    scale = _legend(ws, scale_values)
    return {
        'sheet_title': title,
        'body': _render_body(title, scale, items),
        'checklist': {'scale': scale, 'items': items},
    }


def checklist_body(sheet_name: str) -> str:
    return parse_checklist(sheet_name)['body']


def _checklist_entry(code, title, sheet, sort_order):
    parsed = parse_checklist(sheet)
    return {
        'code': code,
        'kind': 'IN',
        'title': title,
        'source_filename': LISTS.name,
        'body': parsed['body'],
        'checklist': parsed['checklist'],
        'is_fixed': True,
        'note': '',
        'sort_order': sort_order,
    }


def build_entries():
    return [
        _fines_entry(),
        _checklist_entry('IN-02', 'Kontrolna lista — sledljivost', 'Sledljivost', 20),
        _checklist_entry('IN-03', 'Kontrolna lista — higijena', 'Higijena', 30),
        _checklist_entry('IN-04', 'Kontrolna lista — HACCP', 'HACCP', 40),
    ]


if __name__ == '__main__':
    for entry in build_entries():
        checklist = entry.get('checklist') or {}
        items = checklist.get('items', [])
        questions = [item for item in items if item['type'] == 'q']
        sections = [item['text'] for item in items if item['type'] == 'section']
        scale = [option['value'] for option in checklist.get('scale', [])]
        print(entry['code'], entry['title'], 'q', len(questions), 'sections', sections, 'scale', scale)
