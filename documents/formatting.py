import re
from dataclasses import dataclass

FINE_ITEM = re.compile(r'^(\d+)\.\s+(.+)$')
FINE_META = re.compile(r'^\s+(.+?)\s+·\s+(.+)$')

KNOWN_HEADINGS = (
    'Cilj primene',
    'Oblast primene',
    'Područje primene',
    'Definicije',
    'Odgovornosti',
    'Postupak',
    'Veza sa drugim dokumentima',
    'Veza sa standardima',
    'Vezane procedure',
    'Potrebni resursi',
    'Zapisi',
    'Obrasci',
    'Prilozi',
    'Izmene dokumenta',
    'Legenda',
    'Napomena',
    'Preventivne mere',
    'Korektivne mere',
)

_HEADING_ALTS = '|'.join(re.escape(h) for h in KNOWN_HEADINGS)
# Prvo numerisani naslovi ("2. Oblast…"), pa goli naslovi — bez lomljenja "postupak".
NUMBERED_HEADING_CHUNK = re.compile(
    rf'(?<!\n)(\d+\.\d*\s+(?:{_HEADING_ALTS})\b)'
)
BARE_HEADING_CHUNK = re.compile(
    rf'(?<!\n)(?<!\d\.)(?<!\d\. )((?:{_HEADING_ALTS})\b)'
)

NUMBERED_LINE = re.compile(r'^((?:\d+\.)+\d*)\s+(.+)$')
BULLET = re.compile(r'^[-–•]\s+(.+)$')
FIELD_LINE = re.compile(r'^([^:\n]{2,55}):\s*(.*)$')
SECTION_CAPS = re.compile(r'^[A-ZČĆŽŠĐ0-9][A-ZČĆŽŠĐ0-9\s/–-]{2,40}$')
CONTINUATION = re.compile(
    r'^(je|su|se|će|bi|da|i|u|za|sa|od|na|po|ovo|ovim|ova)\b',
    re.IGNORECASE,
)


@dataclass
class Block:
    type: str
    text: str = ''
    n: str = ''
    meta: str = ''


def parse_fine_entries(body: str):
    intro = []
    entries = []
    current = None
    for raw in (body or '').splitlines():
        line = raw.rstrip()
        m_item = FINE_ITEM.match(line)
        if m_item:
            if current:
                entries.append(current)
            current = {
                'n': m_item.group(1),
                'finding': m_item.group(2).strip(),
                'norm': '',
                'fine': '',
            }
            continue
        m_meta = FINE_META.match(line)
        if m_meta and current:
            current['norm'] = m_meta.group(1).strip()
            current['fine'] = m_meta.group(2).strip()
            continue
        if current is None and line and line not in {'—', '-'}:
            if line.startswith('Neusaglašenost'):
                continue
            intro.append(line)
    if current:
        entries.append(current)
    return {
        'intro': '\n'.join(intro).strip(),
        'entries': entries,
    }


def normalize_body(text: str) -> str:
    text = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    text = NUMBERED_HEADING_CHUNK.sub(r'\n\n\1', text)
    text = BARE_HEADING_CHUNK.sub(r'\n\n\1', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _heading_match(line: str):
    for h in KNOWN_HEADINGS:
        if line.startswith(h):
            rest = line[len(h):]
            if rest == '' or rest[:1] in {' ', ':', '—', '-', '\t'}:
                return h, rest.lstrip(' :—-\t')
    return None, ''


def _flush_para(parts: list[str], blocks: list[Block]):
    text = ' '.join(p.strip() for p in parts if p.strip())
    text = re.sub(r'\s{2,}', ' ', text).strip()
    if text:
        blocks.append(Block(type='p', text=text))
    parts.clear()


def _split_heading_and_body(content: str) -> tuple[str, str]:
    hit, rest = _heading_match(content)
    if hit:
        return hit, rest
    # "Održavanje higijene opreme Sva oprema..." — naslov do nove rečenice velikim slovom
    m = re.match(
        r'^((?:[A-ZČĆŽŠĐĐ][\wčćžšđđ]*)(?:\s+[\wčćžšđđ/-]+){1,6})\s+([A-ZČĆŽŠĐĐ].+)$',
        content,
    )
    if m and len(m.group(1).split()) <= 7:
        return m.group(1).strip(), m.group(2).strip()
    if '. ' in content[:110]:
        first, rem = content.split('. ', 1)
        if 2 <= len(first.split()) <= 10:
            return first, rem
    return content, ''


def parse_document_blocks(body: str, *, form_labels: bool = False) -> list[Block]:
    text = normalize_body(body)
    blocks: list[Block] = []
    para: list[str] = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            _flush_para(para, blocks)
            continue

        m_num = NUMBERED_LINE.match(line)
        if m_num:
            _flush_para(para, blocks)
            num = m_num.group(1)
            content = m_num.group(2).strip()
            is_sub = bool(re.match(r'^\d+\.\d+', num))
            known, known_rest = _heading_match(content)

            if content.endswith('?'):
                blocks.append(Block(type='q', n=num.rstrip('.'), text=content))
            elif known:
                blocks.append(Block(type='h', n=num, text=known))
                if known_rest:
                    para.append(known_rest)
            elif is_sub:
                title, rest = _split_heading_and_body(content)
                blocks.append(Block(type='h', n=num, text=title))
                if rest:
                    para.append(rest)
            elif len(content) <= 140:
                blocks.append(Block(type='q', n=num.rstrip('.'), text=content))
            else:
                title, rest = _split_heading_and_body(content)
                blocks.append(Block(type='h', n=num, text=title))
                if rest:
                    para.append(rest)
            continue

        known, known_rest = _heading_match(line)
        if known:
            _flush_para(para, blocks)
            # "Cilj primene Cilj primene je da..." → jedan naslov + pun pasus
            if known_rest.casefold().startswith(known.casefold()):
                known_rest = known_rest[len(known):].lstrip(' :—-\t')
            blocks.append(Block(type='h', text=known))
            if known_rest:
                if CONTINUATION.match(known_rest):
                    para.append(f'{known} {known_rest}')
                else:
                    para.append(known_rest)
            continue

        m_bullet = BULLET.match(line)
        if m_bullet:
            _flush_para(para, blocks)
            blocks.append(Block(type='li', text=m_bullet.group(1).strip()))
            continue

        if SECTION_CAPS.match(line) and not line.endswith('?'):
            _flush_para(para, blocks)
            blocks.append(Block(type='section', text=line))
            continue

        m_field = FIELD_LINE.match(line)
        if m_field and len(m_field.group(1).split()) <= 8:
            label = m_field.group(1).strip()
            value = m_field.group(2).strip()
            # uvodne linije kontrolnih lista ostaju kao pasus
            if label.casefold() in {'izvor', 'odgovori tipično', 'kontrolna lista'}:
                _flush_para(para, blocks)
                blocks.append(Block(
                    type='p',
                    text=f'{label}: {value}' if value else label,
                ))
                continue
            _flush_para(para, blocks)
            blocks.append(Block(type='field', text=label, meta=value))
            continue

        if form_labels:
            if re.search(r'\b(SP|NP|MP)\b', line) and len(line) <= 60:
                _flush_para(para, blocks)
                blocks.append(Block(type='field', text=line))
                continue
            if (
                len(line) <= 40
                and line.count(' ') <= 4
                and not line.endswith('.')
                and line[0].isupper()
                and not line[:1].isdigit()
            ):
                if line.endswith(':') or len(line.split()) <= 3:
                    _flush_para(para, blocks)
                    blocks.append(Block(type='field', text=line.rstrip(':')))
                    continue

        para.append(line)

    _flush_para(para, blocks)
    return _cleanup_blocks(blocks)


def _cleanup_blocks(blocks: list[Block]) -> list[Block]:
    cleaned: list[Block] = []
    for b in blocks:
        if b.type == 'h' and cleaned and cleaned[-1].type == 'h':
            if cleaned[-1].text.casefold() == b.text.casefold() and not b.n:
                continue
        if b.type == 'p' and cleaned and cleaned[-1].type == 'h':
            title = cleaned[-1].text.casefold().rstrip('.')
            body = b.text.casefold()
            if body.startswith(title):
                b.text = b.text[len(cleaned[-1].text.rstrip('.')):].lstrip(' .:—-')
                if not b.text:
                    continue
        if b.type == 'p' and re.fullmatch(r'\d+\.', b.text):
            continue
        cleaned.append(b)
    return cleaned


def format_fixed_document(code: str, body: str, kind: str = '') -> dict:
    if code == 'IN-01':
        return {'mode': 'fines', **parse_fine_entries(body)}

    form_labels = (kind or code[:2]) == 'OB'
    blocks = parse_document_blocks(body, form_labels=form_labels)
    q_count = sum(1 for b in blocks if b.type == 'q')
    field_count = sum(1 for b in blocks if b.type == 'field')
    h_count = sum(1 for b in blocks if b.type == 'h')

    if q_count >= 5:
        mode = 'checklist'
    elif form_labels and field_count >= 3:
        mode = 'form'
    elif h_count >= 2:
        mode = 'doc'
    elif field_count >= 4:
        mode = 'form'
    else:
        mode = 'doc'
    return {'mode': mode, 'blocks': blocks}
