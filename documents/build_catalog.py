"""Napravi documents/library/catalog.json iz Word šablona.

Tekst se prepisuje iz izvučenog sadržaja. Dokumenti koji zavise od objekta
ostaju bez tela: u bazi stoji samo šifra, naslov i ime izvornog fajla.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "HACCP MAXXI PRO TEAM"
EXTRACT_DIR = Path(r"C:\Users\Igor\AppData\Local\Temp\hasap-ascii")
OUT = Path(__file__).resolve().parent / "library" / "catalog.json"

# (code, kind, title, file prefix, extract id or None, is_fixed, note)
ENTRIES = [
    ("HP-01", "HP", "Opis proizvoda", "HP-1-", None, False, "Naziv, namena, pakovanje i mesto prodaje zavise od objekta."),
    ("HP-02", "HP", "Dijagram toka", "HP-2-", None, False, "Crtež procesa je poseban za svaki objekat. U šablonu nema tekstualnog dijagrama."),
    ("HP-03", "HP", "Analiza opasnosti", "HP-3-", None, False, "Opasnosti i ocena rizika prate tehnologiju i asortiman objekta."),
    ("HP-04", "HP", "HACCP plan", "HP-4-", None, False, "Kritične tačke, granice, ko meri i korektivne mere zavise od procesa."),
    ("PR-01", "PR", "Odluka o HACCP timu", "PR-1-", None, False, "Imena članova tima, mesto i datum potpisa su podaci objekta."),
    ("PR-02", "PR", "Interne provere", "PR-2-", "29", True, ""),
    ("PR-03", "PR", "Dezinsekcija i deratizacija", "PR-3-", "30", True, ""),
    ("PR-04", "PR", "Upravljanje neusaglašenostima", "PR-4-", "31", True, ""),
    ("PR-05", "PR", "Korektivne i preventivne mere", "PR-5-", "32", True, ""),
    ("UP-01", "UP", "Prijem i skladištenje", "UP-1-", "38", True, ""),
    ("UP-02", "UP", "Lična higijena", "UP-2-", "39", True, ""),
    ("UP-03", "UP", "Čišćenje i održavanje higijene", "UP-3-", "40", True, ""),
    ("UP-04", "UP", "Identifikacija i sledljivost", "UP-4-", "41", True, ""),
    ("UP-05", "UP", "Opoziv proizvoda", "UP-5-", "42", True, ""),
    ("UP-06", "UP", "Kontrola merne opreme", "UP-06-", "35", True, ""),
    ("UP-07", "UP", "Izrada i upravljanje dokumentima", "UP-07-", "36", True, ""),
    ("UP-08", "UP", "Verifikacija CCP", "UP-08-", None, False, "Način verifikacije prati kritične tačke tog objekta."),
    ("OB-01", "OB", "Nalog za korektivne mere", "OB-1-", "06", True, ""),
    ("OB-02", "OB", "Plan interne provere", "OB-2-", "17", True, ""),
    ("OB-03", "OB", "Lista dozvoljenih sredstava", "OB-3-", None, False, "Spisak hemikalija zavisi od onoga što objekat stvarno koristi."),
    ("OB-04", "OB", "Plan DD", "OB-4-", "21", True, ""),
    ("OB-05", "OB", "Evidencija DD", "OB-5-", "22", True, ""),
    ("OB-06", "OB", "Monitoring glodara", "OB-6-", "23", True, ""),
    ("OB-07", "OB", "Monitoring insekata", "OB-7-", "24", True, ""),
    ("OB-08", "OB", "Registar neusaglašenosti i korektivnih mera", "OB-8-", "25", True, ""),
    ("OB-09", "OB", "Povlačenje proizvoda", "OB-9-", "26", True, ""),
    ("OB-10", "OB", "Praćenje temperature hlađenja", "OB-10-", "07", True, ""),
    ("OB-11", "OB", "Higijena radnog prostora", "OB-11-", "08", True, ""),
    ("OB-12", "OB", "Radni nalog u proizvodnji", "OB-12-", "09", True, ""),
    ("OB-13", "OB", "Izjava posetilaca", "OB-13-", "10", True, ""),
    ("OB-14", "OB", "Identifikacija i sledljivost", "OB-14-", "11", True, ""),
    ("OB-15", "OB", "Prijem sirovina", "OB-15-", "12", True, ""),
    ("OB-16", "OB", "Praćenje temperature pečenja", "OB-16", "13", True, ""),
    ("OB-17", "OB", "Registar dokumenta", "OB-17-", "14", True, ""),
    ("OB-18", "OB", "Plan slanja uzoraka", "OB-18-", None, False, "Vrste uzoraka i ritam zavise od asortimana objekta."),
    ("OB-19", "OB", "Kontrola sita", "OB-19-", "16", True, ""),
    ("OB-20", "OB", "Praćenje i kontrola mernih instrumenata", "OB-20-", "18", True, ""),
    ("OB-21", "OB", "Spisak merne opreme", "OB-21-", "19", True, ""),
]

DROP = re.compile(
    r"^(\d+\.?|\d+/\d+|[OUI]|Red\.?( broj)?|broj|Dijagram( toka)?|Aktivnost|Odgovoran|Dokument|Prenos|br|strana|Opis izmene)$",
    re.I,
)
FILLED = re.compile(r"Vesna Stojanović|15\.01\.2025|Maxxi|Borč|113496914", re.I)


def source_name(prefix):
    matches = [p.name for p in SOURCE_DIR.iterdir() if p.name.startswith(prefix)]
    if len(matches) != 1:
        raise SystemExit(f"Očekivan jedan fajl za {prefix}, nađeno: {matches}")
    return matches[0]


def clean(text):
    text = text.replace("\ufeff", "").replace("\u00a0", " ")
    lines = []
    for chunk in re.split(r"\s*\|\s*", text):
        chunk = re.sub(r"\s+", " ", chunk).strip(" -|")
        if not chunk or DROP.match(chunk) or len(chunk) <= 2:
            continue
        if re.fullmatch(r"[iIuU/\s]+", chunk):
            continue
        if FILLED.search(chunk):
            continue
        if lines and lines[-1] == chunk:
            continue
        lines.append(chunk)
    body = "\n\n".join(lines)
    body = re.sub(r"\s+(?=\d+\.(?:\d+\.?)?\s)", "\n\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body


def main():
    index = {}
    for line in (EXTRACT_DIR / "index.txt").read_text(encoding="utf-8").splitlines():
        num, name = line.split("\t", 1)
        index[num] = name

    catalog = []
    for order, (code, kind, title, prefix, extract_id, is_fixed, note) in enumerate(ENTRIES, start=1):
        filename = source_name(prefix)
        body = ""
        if is_fixed:
            if extract_id not in index:
                raise SystemExit(f"Nema izvoda {extract_id} za {code}")
            raw = (EXTRACT_DIR / f"{extract_id}.txt").read_text(encoding="utf-8")
            body = clean(raw)
            if not body:
                raise SystemExit(f"Prazan tekst za {code}")
        catalog.append({
            "code": code,
            "kind": kind,
            "title": title,
            "source_filename": filename,
            "is_fixed": is_fixed,
            "note": note,
            "sort_order": order,
            "body": body,
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    fixed = sum(1 for row in catalog if row["is_fixed"])
    print(f"{OUT} entries={len(catalog)} fixed={fixed} chars={sum(len(r['body']) for r in catalog)}")


if __name__ == "__main__":
    main()
