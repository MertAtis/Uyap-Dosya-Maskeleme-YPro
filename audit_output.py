#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Maskeli çıktı denetim aracı (audit_output.py) — yalnızca geliştirme/denetim içindir.

Kullanım:
    python3 audit_output.py KAYNAK ÇIKTI [--ocr-cache DİZİN] [--details DOSYA]

- stdout'a yalnızca SAYILAR ve dosya adları yazılır; ham değerler (TCKN, IBAN, adres vb.)
  YALNIZCA --details dosyasına yazılır. Bu dosyayı paylaşmayın.
- Kaynak metin: KAYNAK/<göreli yol> varsa o, yoksa --ocr-cache/<göreli yol>.
- Çıkış kodu: sızıntı (geçerli TCKN, ham IBAN, maskesiz cep telefonu, maskesiz kişi adresi)
  varsa 1, yoksa 0.

Bölümler:
  A) Sızıntı   B) Fazla maskeleme   C) Etiket tutarlılığı   D) Yapı   E) Koruma
"""

import argparse
import difflib
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple

try:
    from uyap_redactor import UyapRedactor
except ImportError:
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    if _script_dir not in sys.path:
        sys.path.insert(0, _script_dir)
    from uyap_redactor import UyapRedactor

TEXT_EXTS = (".md", ".txt", ".json")
REPORT_NAME = "DAVA_DÖNÜŞÜM_VE_GÜVENLİK_RAPORU.md"

# Hem eski sabit ([TCKN_GİZLENDİ]) hem numaralı ([TCKN_3]) etiketler
MASK_KINDS = r'(?:TCKN|IBAN|KART|HESAP|TEL|SERİ_NO|MRZ|SİCİL|ADRES)'
MASK_RE = re.compile(
    r'\[(?:[A-ZÇĞİÖŞÜ_]+_GİZLENDİ|' + MASK_KINDS + r'_\d+)\]'
)

# Eski etiket adı -> tür
LEGACY_KIND = {
    "TCKN": "TCKN", "TELEFON": "TEL", "SERİ_NO": "SERİ_NO", "KİMLİK_MRZ_KODU": "MRZ",
    "IBAN": "IBAN", "KART_NO": "KART", "HESAP_NO": "HESAP", "ADRES": "ADRES", "SİCİL": "SİCİL",
}


def mask_kind(label: str) -> str:
    inner = label[1:-1]
    m = re.fullmatch(r'(.+)_GİZLENDİ', inner)
    if m:
        return LEGACY_KIND.get(m.group(1), m.group(1))
    return re.sub(r'_\d+$', '', inner)


def is_numbered(label: str) -> bool:
    return bool(re.search(r'_\d+\]$', label))


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------
def is_valid_tckn(t: str) -> bool:
    if len(t) != 11 or not t.isdigit() or t[0] == '0' or len(set(t[:10])) == 1:
        return False
    d = [int(c) for c in t]
    if ((d[0] + d[2] + d[4] + d[6] + d[8]) * 7 - (d[1] + d[3] + d[5] + d[7])) % 10 != d[9]:
        return False
    return sum(d[:10]) % 10 == d[10]


def ocr_digits(s: str) -> str:
    return (s.replace('l', '1').replace('I', '1').replace('|', '1')
            .replace('O', '0').replace('o', '0'))


# 32+ karakterlik onaltılık özetler (sha256 vb., JSON meta verisi): içlerindeki rakam dizileri TCKN/IBAN değildir.
HEX_TOKEN_RE = re.compile(r'(?<![0-9A-Za-z])(?=[0-9]*[a-fA-F])[0-9a-fA-F]{32,}(?![0-9A-Za-z])')


def strip_hex_tokens(text: str) -> str:
    return HEX_TOKEN_RE.sub(lambda m: " " * len(m.group(0)), text)


def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return UyapRedactor.normalize_spaces(f.read())
    except Exception:
        return None


def exists_nfc_nfd(base_dir: str, rel: str) -> bool:
    for form in ("NFC", "NFD"):
        if os.path.exists(os.path.join(base_dir, unicodedata.normalize(form, rel))):
            return True
    return False


def _find_nfc_nfd_file(base_dir: str, rel: str) -> Optional[str]:
    for form in ("NFC", "NFD"):
        p = os.path.join(base_dir, unicodedata.normalize(form, rel))
        if os.path.isfile(p):
            return p
    return None


def _extract_non_ocr_from_base(base_dir: str, rel: str, allow_kaynak: bool = True) -> Optional[str]:
    """Verilen taban dizinde rel (.md çıktısı) için .udf ve Office (.docx/.doc/.xlsx) kaynaklarını arar."""
    if not rel.lower().endswith(".md"):
        return None
    stem = rel[:-3]
    prefixes = ("", "_kaynak") if allow_kaynak else ("",)

    # Önce .udf
    udf_rel = stem + ".udf"
    for pref in prefixes:
        cand = os.path.join(pref, udf_rel) if pref else udf_rel
        p = _find_nfc_nfd_file(base_dir, cand)
        if p:
            raw = UyapRedactor.extract_udf_raw(p)
            return UyapRedactor.normalize_spaces(raw) if raw else None

    # Sonra Office (.docx, .doc, .xlsx)
    for ext, fn in (
        (".docx", UyapRedactor.extract_word_raw),
        (".doc", UyapRedactor.extract_word_raw),
        (".xlsx", UyapRedactor.extract_xlsx_raw),
    ):
        off_rel = stem + ext
        for pref in prefixes:
            cand = os.path.join(pref, off_rel) if pref else off_rel
            p = _find_nfc_nfd_file(base_dir, cand)
            if p:
                raw = fn(p)
                return UyapRedactor.normalize_spaces(raw) if raw else None

    # En son metin katmanlı PDF (taranmış PDF'ler OCR önbelleğiyle denetlenir; burada yeniden OCR yapılmaz)
    pdf_rel = stem + ".pdf"
    for pref in prefixes:
        cand = os.path.join(pref, pdf_rel) if pref else pdf_rel
        p = _find_nfc_nfd_file(base_dir, cand)
        if p:
            try:
                import fitz
                with fitz.open(p) as doc:
                    sample = "".join(doc[i].get_text() for i in range(min(3, len(doc))))
                if len(sample.strip()) < 50:
                    return None
            except Exception:
                return None
            raw = UyapRedactor.extract_pdf_raw(p)
            return UyapRedactor.normalize_spaces(raw) if raw else None
    return None


def _resolve_archive_inner(
    src: str, rel: str, archive_cache: Dict[str, str]
) -> Tuple[Optional[str], Optional[str]]:
    """
    Göreli yoldaki '<ad> (EYP)/' veya '<ad> (ZIP)/' bölümlerini kaynakta açarak
    (çıkarılan_dizin, iç_göreli_yol) çiftini döndürür.
    """
    norm_rel = unicodedata.normalize("NFC", rel)
    parts = [p for p in norm_rel.replace("\\", "/").split("/") if p]
    i = 0
    cur_base = src
    allow_kaynak = True

    while i < len(parts):
        found_j = None
        for j in range(i, len(parts) - 1):
            if parts[j].endswith(" (EYP)") or parts[j].endswith(" (ZIP)"):
                found_j = j
                break
        if found_j is None:
            if cur_base == src:
                return None, None
            return cur_base, os.path.join(*parts[i:])

        tag = parts[found_j][-6:]
        arc_ext = ".eyp" if tag == " (EYP)" else ".zip"
        arc_name = parts[found_j][:-6] + arc_ext
        sub_rel = os.path.join(*parts[i:found_j], arc_name) if found_j > i else arc_name

        prefixes = ("", "_kaynak") if allow_kaynak else ("",)
        arc_path = None
        for pref in prefixes:
            cand = os.path.join(pref, sub_rel) if pref else sub_rel
            arc_path = _find_nfc_nfd_file(cur_base, cand)
            if arc_path:
                break
        if not arc_path:
            return None, None

        cache_key = unicodedata.normalize("NFC", os.path.realpath(arc_path))
        if cache_key not in archive_cache:
            tmp_dir = os.path.realpath(tempfile.mkdtemp(prefix="uyap_audit_arsiv_"))
            archive_cache[cache_key] = tmp_dir
            UyapRedactor._extract_archive_safely(arc_path, tmp_dir)

        cur_base = archive_cache[cache_key]
        allow_kaynak = False
        i = found_j + 1

    return None, None


def _is_archive_ocr_source(src: str, rel: str, archive_cache: Dict[str, str]) -> bool:
    """Arşiv içinden OCR ile üretilmiş (.pdf/.tif/.png/.jpg/.heic) bir belgenin kaynağı arşivde mevcut mu?"""
    if not src or not rel.lower().endswith(".md"):
        return False
    arc_dir, inner_rel = _resolve_archive_inner(src, rel, archive_cache)
    if not arc_dir or not inner_rel:
        return False
    stem = inner_rel[:-3]
    for ext in UyapRedactor.OCR_DOC_EXTS:
        if _find_nfc_nfd_file(arc_dir, stem + ext):
            return True
    return False


def find_source_text(
    src: str,
    ocr_cache: Optional[str],
    rel: str,
    archive_cache: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    for base in (src, ocr_cache):
        if not base:
            continue
        p = _find_nfc_nfd_file(base, rel)
        if p:
            t = read_text(p)
            if t is None:
                return None
            if rel.endswith(".json"):
                # Çıktı JSON'u yeniden biçimlendirildiğinden kaynağı aynı biçime getir
                try:
                    return json.dumps(json.loads(t), ensure_ascii=False, indent=2)
                except Exception:
                    return t
            return t

    if not src:
        return None

    # Öncelik: önce mevcut .md/.txt/.json ve OCR önbelleği, sonra .udf, sonra Office (.docx/.doc/.xlsx)
    direct = _extract_non_ocr_from_base(src, rel, allow_kaynak=True)
    if direct is not None:
        return direct

    # Arşiv çıktıları: '<ad> (EYP)/' veya '<ad> (ZIP)/'
    local_cache = archive_cache if archive_cache is not None else {}
    try:
        arc_dir, inner_rel = _resolve_archive_inner(src, rel, local_cache)
        if arc_dir and inner_rel:
            p_inner = _find_nfc_nfd_file(arc_dir, inner_rel)
            if p_inner:
                return read_text(p_inner)
            return _extract_non_ocr_from_base(arc_dir, inner_rel, allow_kaynak=False)
    finally:
        if archive_cache is None:
            for d in local_cache.values():
                shutil.rmtree(d, ignore_errors=True)
    return None


# ---------------------------------------------------------------------------
# A) Sızıntı
# ---------------------------------------------------------------------------
TCKN_RE = re.compile(r'(?<!\d)[1-9]\d{10}(?!\d)')
TCKN_SPLIT_RE = re.compile(r'(?<![0-9A-Za-z])[0-9lIO](?:[ |/,.]?[0-9lIO]){10,13}(?![0-9A-Za-z])')
IBAN_RE = re.compile(r'TR(?:[ \t.\-^]*[0-9lIOo]){24}')
PHONE_RE = re.compile(
    r'(?<![\d])(?:(?:\+\s?90|0090)[\s.\-]?)?(?:\(0\)|0)?[\s.\-]?\(?5[0-69]\d\)?[\s.\-]?\d{3}[\s.\-]?\d{2}[\s.\-]?\d{2}(?![\d])'
)

ADDR_TOKENS = {
    "mah": re.compile(r'(?i)\b(?:Mah\.|Mh\.|Mahallesi|Mahalle(?:si)?)(?![A-Za-zçğıöşü])'),
    "sk": re.compile(r'(?i)\b(?:Sk\.|Sok\.|Sokak|Sokağ[ıi])(?![A-Za-zçğıöşü])'),
    "cad": re.compile(r'(?i)\b(?:Cad\.|Cd\.|Caddesi|Cadde)(?![A-Za-zçğıöşü])'),
    "bulvar": re.compile(r'(?i)\bBulvar[ıi]'),
    "no": re.compile(r'(?i)\bNo\s*[:.]?\s*\d|\bN\s*[:.]\s*\d'),
    "kapi": re.compile(r'(?i)Kap[ıi]\s*No'),
    "d": re.compile(r'(?<![A-Za-zÇĞİÖŞÜçğıöşü])D\s*[:.]\s*\d'),
    "k": re.compile(r'(?<![A-Za-zÇĞİÖŞÜçğıöşü])K\s*[:.]\s*\d'),
}
INSTITUTION_RE = re.compile(
    r'(?i)Bankas[ıi]|Banka\b|Genel\s+Müdürlü|Müdürlü|Adliye|Mahkeme|Noter|Baro|Başkanlığ|'
    r'Başsavcılı|Savcılığ|PTT|Belediye|A\.?\s?Ş\.?|Ltd|Şirket|Şube|Valili|Kaymakaml|Bakanlı|'
    r'Kurumu|Hastane|Üniversite|Odası|Daire\s+Başkan|SGK|Emniyet|Karakol|Jandarma|İcra\s+Dairesi|'
    r'Vergi\s+Dairesi|Tapu|Nüfus\s+Müdürlü|Hukuk\s+Bürosu|Avukatl[ıi]k\s+Ortakl|'
    # iş yeri yapıları (redaktör de bunları kurum/iş yeri sayar: _ADDR_INST_RE ile aynı küme)
    r'\bPlaza\b|\bTowers?\b|\bCenter\b|İş\s+Merkezi|Katılım\s+Bankas|Sigorta|Holding'
)

LINK_RE = re.compile(r'!?\[([^\]\n]*)\]\((?:<[^>\n]+>|[^)\n]+)\)')
# "evrak no 4521", "dosya no: 12" gibi belge numarası ifadeleri adres kapı numarası değildir
DOC_NO_RE = re.compile(
    r'(?i)\b(?:evrak|dosya|esas|karar|say[ıi]|dava|belge|protokol|takip|talimat|soruşturma|hazırlık|poliçe|acente)\s+no\b'
)


PERSON_CUE_RE = re.compile(r'(?i)MERN[İI]S|\badresini\b|yükümlü|\bikamet|\boturur|\bisimli\b')

TEMPLATE_ADDR_RE = re.compile(r'(?i)\(?\s*caddesi\s*/\s*sokağı\s*\)?')

OLAY_RE = re.compile(
    r'(?i)suçun\s+yeri|olay\s+yeri|kaza\s+yeri|meydana\s+gel|\bönünde\b|kavşağ|sıralarında|'
    r'trafik\s+kazas|Yer\s*\(Cadde|'
    r'\bopr\s*:|\b(?:operat[öo]r|baz(?:\s+istasyon\w*)?|BTS|CGI|hücre\w*|LAC)\b|'
    r'\b\d{2}\.\d{4,}\s*[-,;]?\s*\d{2}\.\d{4,}\b'
)


_KUNYE_RE = re.compile(
    r'(?i)vergi|\bVKN\b|V\.\s?D\.|mersis|ticaret\s+sicil|\btel\b|telefon|faks|\bKEP\b|e-?posta|web'
)
_PERSON_ID_RE = re.compile(r'(?i)T\.?\s?C\.?\s*(?:Kimlik|No)|TCKN|\[TCKN_')


def _company_block_above(lines: List[str], i: int, max_up: int = 6) -> bool:
    """Adres satırının üstünde yalnız şirket künyesi satırları ve en üstte kurum/şirket adı varsa True
    (redaktördeki 'şirket taraf bloğu' kuralıyla uyumlu; araya kişi kimliği girerse False)."""
    seen = 0
    for j in range(i - 1, -1, -1):
        s = lines[j].strip()
        if not s:
            continue
        seen += 1
        if seen > max_up or _PERSON_ID_RE.search(s):
            return False
        if INSTITUTION_RE.search(s):
            return True
        if not _KUNYE_RE.search(s):
            return False
    return False


def address_type_count(line: str) -> int:
    return sum(1 for r in ADDR_TOKENS.values() if r.search(line))


def scan_leaks(rel: str, text: str, known_tckns, known_ibans, out: Dict, check_addr: bool = True):
    text = strip_hex_tokens(text)
    lines = text.splitlines()
    for m in TCKN_RE.finditer(text):
        if is_valid_tckn(m.group(0)):
            out["tckn"].append((rel, m.group(0)))
    for m in TCKN_SPLIT_RE.finditer(text):
        raw = m.group(0)
        if TCKN_RE.fullmatch(raw):
            continue
        digits = re.sub(r'\D', '', ocr_digits(raw))
        if len(digits) == 11 and is_valid_tckn(digits):
            out["tckn_possible"].append((rel, raw))
    compact = re.sub(r'[ \t]', '', text)
    # Satırlara / başlıklara bölünmüş IBAN: boşluk, satır sonu, #, |, * atılmış metinde ara
    compact_ml = re.sub(r'[\s#|*.\-]', '', text)
    single = re.sub(r'[ \t.\-^]', '', text)
    for m in re.finditer(r'TR\d{24}(?!\d)', compact_ml):
        if m.group(0) not in single:
            out["iban_multiline"].append((rel, m.group(0)))
    for t in known_tckns:
        if re.search(r'(?<!\d)' + t + r'(?!\d)', compact):
            out["tckn_known"].append((rel, t))
    for m in IBAN_RE.finditer(text):
        raw = m.group(0)
        if sum(c.isdigit() for c in raw) >= 15:
            out["iban"].append((rel, raw))
    compact2 = re.sub(r'[\s.\-^#|*]', '', ocr_digits(text))
    for ib in known_ibans:
        if ib in compact2:
            out["iban_known"].append((rel, "TR" + ib))
    for m in PHONE_RE.finditer(text):
        out["phone"].append((rel, m.group(0)))
    if not check_addr or os.path.basename(rel) == REPORT_NAME:
        return  # aracın kendi raporu veya dosya yolu için adres taraması yapılmaz
    for i, line in enumerate(lines):
        if MASK_RE.search(line):
            continue
        # Dilekçe formu şablon ifadesi "(caddesi / sokağı)" adres değildir
        line = TEMPLATE_ADDR_RE.sub(" ", line)
        # Markdown bağlantıları (yol/dosya adı) ve belge-numarası ifadeleri adres belirteci sayılmaz
        line = DOC_NO_RE.sub(" ", LINK_RE.sub(lambda m: m.group(1), line))
        if address_type_count(line) >= 2:
            prev2 = [lines[j] for j in range(i - 1, max(-1, i - 5), -1) if lines[j].strip()][:2]
            next_line = next((lines[j] for j in range(i + 1, min(len(lines), i + 3)) if lines[j].strip()), "")
            near = "\n".join(prev2 + [next_line])
            if OLAY_RE.search(line) or (not PERSON_CUE_RE.search(line) and OLAY_RE.search("\n".join(lines[max(0, i - 1): i]))):
                kind = "olay"
            elif PERSON_CUE_RE.search(line):
                # MERNİS / "adresini ..." / yükümlü / ikamet: kişi adresi (aynı satırda kurum adı geçse de)
                kind = "kisi"
            elif INSTITUTION_RE.search(line) or INSTITUTION_RE.search(near):
                # Kurum adı aynı satırda, önceki 2 dolu satırda ya da sonraki dolu satırda aranır (kurum adı
                # adresten önce/sonra alt satıra taşabilir); daha uzak bağlam (belge başlığı vb.) yetmez.
                kind = "kurum"
            elif _company_block_above(lines, i):
                # Şirket adı ile adres arasında yalnız künye satırları (VKN/MERSİS/ticaret sicil/tel/KEP)
                kind = "kurum"
            else:
                kind = "kisi"
            out["addr_" + kind].append((rel, i + 1, lines[i].strip()))


MAPPING_RE = re.compile(
    r'(?P<lab>' + MASK_RE.pattern + r')[ \t]*(?:=|:|->|→|\t)[ \t]*(?P<val>(?:TR)?\d{6,})(?!\d)'
)
# Etiketin yerine geçtiği değerin biçimi: yalnızca bu uzunlukta bir sayı etiketin hemen yanındaysa
# eşleme tablosu sayılır (OCR'lı tablo sütunlarındaki ": [TCKN_1] : 12345678 :" gibi bitişik
# protokol/dosya numaraları ve alt satıra taşan sütun değerleri eşleme değildir).
_MAPPING_SHAPE = {
    "TCKN": lambda d: len(d) == 11, "IBAN": lambda d: len(d) == 24, "KART": lambda d: len(d) == 16,
    "TEL": lambda d: len(d) in (10, 11), "HESAP": lambda d: len(d) >= 10,
}


def has_mapping_leak(text: str) -> bool:
    for m in MAPPING_RE.finditer(text):
        shape = _MAPPING_SHAPE.get(mask_kind(m.group("lab")))
        if shape and shape(re.sub(r"\D", "", m.group("val"))):
            return True
    return False


def collect_source_ids(text: str) -> Tuple[set, set]:
    text = strip_hex_tokens(text)
    tckns = set()
    for m in TCKN_RE.finditer(text):
        if is_valid_tckn(m.group(0)):
            tckns.add(m.group(0))
    for m in TCKN_SPLIT_RE.finditer(text):
        d = re.sub(r'\D', '', ocr_digits(m.group(0)))
        if len(d) == 11 and is_valid_tckn(d):
            tckns.add(d)
    ibans = set()
    for m in IBAN_RE.finditer(text):
        d = re.sub(r'\D', '', ocr_digits(m.group(0)[2:]))
        if len(d) == 24:
            ibans.add(d)
    for m in re.finditer(r'TR(\d{24})(?!\d)', re.sub(r'[\s#|*.\-]', '', text)):
        ibans.add(m.group(1))
    return tckns, ibans


LINK_NORM_RE = re.compile(r'!?\[([^\]\n]*)\]\((?:<[^>\n]+>|[^)\n]+)\)')


def norm_links(line: str) -> str:
    """Bağlantı yeniden yazımlarını hizalama için nötrle (görsel aktarılmadı / OCR metni)."""
    line = re.sub(r'\[görsel aktarılmadı: ([^\]]*)\]', r'\1', line)
    line = LINK_NORM_RE.sub(lambda m: re.sub(r' \(OCR metni\)$', '', m.group(1)), line)
    return line


# ---------------------------------------------------------------------------
# B) Fazla maskeleme
# ---------------------------------------------------------------------------
ANALYSIS_RE = {
    "tarih": re.compile(r'\b\d{1,2}[./]\d{1,2}[./]\d{4}\b'),
    "esas_yil": re.compile(r'\b(?:19|20)\d{2}\s*/\s*\d+'),
    "tutar": re.compile(r'(?i)\d[\d.,]*\s*(?:TL\b|₺|Türk\s+Liras)'),
    "kanun": re.compile(r'\b(?:HMK|TMK|TBK|İİK|IIK|TCK|CMK)\b[^\n]{0,15}?\d'),
    "url_eposta": re.compile(r'(?i)https?://|www\.|@|\.gov\.tr|\bkep\b|uyap\.'),
}


def extract_mask_pieces(src_line: str, out_line: str) -> Optional[List[Tuple[str, str]]]:
    """Çıktı satırındaki her maskenin yerine geçtiği kaynak parçasını döndürür."""
    parts = MASK_RE.split(out_line)
    labels = MASK_RE.findall(out_line)
    if not labels:
        return []
    pattern = "^" + "(.*?)".join(re.escape(p) for p in parts) + "$"
    try:
        m = re.match(pattern, src_line, re.S)
    except re.error:
        return None
    if not m:
        return None
    return list(zip(labels, m.groups()))


def analysis_flags(piece: str) -> List[str]:
    return [k for k, r in ANALYSIS_RE.items() if r.search(piece)]


# ---------------------------------------------------------------------------
# C) Tutarlılık için normalize anahtar
# ---------------------------------------------------------------------------
def norm_value(kind: str, piece: str) -> Optional[str]:
    p = ocr_digits(piece)
    d = re.sub(r'\D', '', p)
    if kind == "TCKN":
        return d if len(d) == 11 else None
    if kind == "IBAN":
        return d[-24:] if len(d) >= 24 else None
    if kind == "TEL":
        return d[-10:] if len(d) >= 10 else None
    if kind in ("SİCİL", "KART", "HESAP"):
        return d or None
    return None


# ---------------------------------------------------------------------------
# E) Koruma
# ---------------------------------------------------------------------------
PRESERVE_RE = {
    "tarih": re.compile(r'(?<!\d)\d{1,2}[./]\d{1,2}[./]\d{4}(?!\d)'),
    "esas_yil": re.compile(r'(?<![\d/])(?:19|20)\d{2}/\d{1,7}(?![\d/])'),
    "tutar": re.compile(r'(?i)(?<![\d.,])\d{1,3}(?:[.,]\d{3})*(?:,\d{1,2})?\s?(?:TL\b|₺)'),
    "kanun": re.compile(r'\b(?:HMK|TMK|TBK|İİK|TCK|CMK)\b\.?\s*(?:\d+\.?\s*)?(?:md\.|madde(?:si)?)?\s*\d+'),
}


LINK_DEST_RE = re.compile(r'\]\((?:<[^>\n]*>|[^)\n]*)\)')
IMAGE_NOTE_RE = re.compile(r'(?m)^> \*\*Görseller:\*\*.*$')


def preserve_view(text: str) -> str:
    """Koruma sayımı için metin: bağlantı hedefleri (yol/dosya adı) ve görsel-klasörü notu hariç.
    Dosya adlarındaki "(CMK 90)" / "(2024/123)" gibi parçalar belge içeriği değil yol bilgisidir;
    bağlantı yeniden yazımında (OCR metni / aktarılmadı) hedef değişir ya da kalkar."""
    return IMAGE_NOTE_RE.sub("", LINK_DEST_RE.sub("](#)", text))


def _collect_source_rel_candidates(
    src: str,
    ocr_cache: Optional[str],
    archive_cache: Dict[str, str],
) -> List[str]:
    """Kaynak klasördeki (ve arşiv/OCR önbelleğindeki) olası çıktı göreli yollarını toplar."""
    cands: List[str] = []
    seen = set()

    def _add_cand(r: str) -> None:
        nr = unicodedata.normalize("NFC", r.replace("\\", "/"))
        if nr not in seen:
            seen.add(nr)
            cands.append(nr)

    def _walk_dir(base_dir: str, prefix: str = "", allow_kaynak: bool = True, allow_archives: bool = True) -> None:
        if not base_dir or not os.path.isdir(base_dir):
            return
        for root, dirs, files in os.walk(base_dir):
            rel_root = os.path.relpath(root, base_dir)
            parts = [] if rel_root == "." else rel_root.split(os.sep)
            if any(p in UyapRedactor.SKIP_DIRS for p in parts if p != "_kaynak"):
                dirs[:] = []
                continue
            dirs.sort()
            for f in sorted(files):
                full_p = os.path.join(root, f)
                rel_p = unicodedata.normalize("NFC", os.path.relpath(full_p, base_dir))
                if allow_kaynak and rel_p.startswith("_kaynak/"):
                    clean_p = rel_p[len("_kaynak/"):]
                else:
                    clean_p = rel_p
                ext = os.path.splitext(f)[1].lower()
                virt_base = f"{prefix}/{clean_p}" if prefix else clean_p
                if ext in TEXT_EXTS:
                    _add_cand(virt_base)
                elif ext in UyapRedactor.TEXT_DOC_EXTS or ext in UyapRedactor.OCR_DOC_EXTS:
                    _add_cand(os.path.splitext(virt_base)[0] + ".md")
                    _add_cand(virt_base + ".md")
                elif allow_archives and ext in UyapRedactor.ARCHIVE_EXTS:
                    tag = "(EYP)" if ext == ".eyp" else "(ZIP)"
                    arc_prefix = f"{os.path.splitext(virt_base)[0]} {tag}"
                    ck = unicodedata.normalize("NFC", os.path.realpath(full_p))
                    if ck not in archive_cache:
                        tmp_d = os.path.realpath(tempfile.mkdtemp(prefix="uyap_audit_cand_"))
                        archive_cache[ck] = tmp_d
                        UyapRedactor._extract_archive_safely(full_p, tmp_d)
                    _walk_dir(archive_cache[ck], prefix=arc_prefix, allow_kaynak=False, allow_archives=(ext == ".eyp"))

    _walk_dir(src, allow_kaynak=True, allow_archives=True)
    if ocr_cache:
        _walk_dir(ocr_cache, allow_kaynak=False, allow_archives=False)
    return cands


def _match_masked_source_rel(masked_rel: str, src_candidates: List[str]) -> Optional[str]:
    """Maske etiketi ([TEL_1], [TCKN_1] vb.) içeren çıktı yolunu jokerle kaynakta tek adaya eşler."""
    if not MASK_RE.search(masked_rel):
        return None
    norm_rel = unicodedata.normalize("NFC", masked_rel.replace("\\", "/"))
    parts = norm_rel.split("/")
    pat_parts = []
    for idx, seg in enumerate(parts):
        # Çakışma eki " (2)" dosya uzantısından hemen önce veya klasör sonunda olabilir
        if idx == len(parts) - 1:
            stem, ext = os.path.splitext(seg)
            stem_clean = re.sub(r' \(\d+\)$', '', stem)
            target_seg = stem_clean + ext
        else:
            target_seg = re.sub(r' \(\d+\)$', '', seg)
        chunks = MASK_RE.split(target_seg)
        masks = MASK_RE.findall(target_seg)
        if not masks:
            pat_parts.append(re.escape(target_seg))
        else:
            seg_rx = re.escape(chunks[0])
            for ch in chunks[1:]:
                seg_rx += r'[^/]+' + re.escape(ch)
            pat_parts.append(seg_rx)
    rx = re.compile("^" + "/".join(pat_parts) + "$")
    matches = [c for c in src_candidates if rx.match(c)]
    if len(matches) == 1:
        return matches[0]
    return None


# ---------------------------------------------------------------------------
# Ana denetim
# ---------------------------------------------------------------------------
def audit(src: str, out: str, ocr_cache: Optional[str] = None) -> Dict:
    src = os.path.abspath(src)
    out = os.path.abspath(out)
    res: Dict = {
        "leaks": defaultdict(list),
        "over": [],            # (rel, lineno, label, piece, flags)
        "unaligned": [],       # (rel, out_lineno, src_lines, out_lines)
        "binary_files": [],
        "broken_links": [],
        "source_broken_links": [],  # kaynakta da kopuk metin bağlantıları (aracın kusuru değil)
        "index_mismatch": [],
        "mapping_leak": [],
        "unexpected_files": [],
        "masked_name_unmatched": [],
        "preserve_total": Counter(),
        "preserve_lost": defaultdict(list),
        "files_scanned": 0,
        "files_with_source": 0,
    }

    out_files = []
    for root, _dirs, files in os.walk(out):
        for f in sorted(files):
            p = os.path.join(root, f)
            rel = unicodedata.normalize("NFC", os.path.relpath(p, out))
            if not f.lower().endswith(TEXT_EXTS):
                res["binary_files"].append(rel)
                continue
            out_files.append((rel, p))
    out_files.sort()

    # Kaynakta görülen tüm TCKN / IBAN değerleri
    pairs = []
    known_tckns, known_ibans = set(), set()
    archive_cache: Dict[str, str] = {}
    src_candidates: Optional[List[str]] = None
    try:
        for rel, p in out_files:
            o = read_text(p) or ""
            orig_rel = rel
            s = find_source_text(src, ocr_cache, rel, archive_cache=archive_cache)
            if s is None and MASK_RE.search(rel):
                if src_candidates is None:
                    src_candidates = _collect_source_rel_candidates(src, ocr_cache, archive_cache)
                matched = _match_masked_source_rel(rel, src_candidates)
                if matched:
                    orig_rel = matched
                    s = find_source_text(src, ocr_cache, matched, archive_cache=archive_cache)
            pairs.append((rel, p, s, o, orig_rel))
            if s:
                t, i = collect_source_ids(s)
                known_tckns |= t
                known_ibans |= i

        val_to_labels = defaultdict(set)
        label_to_vals = defaultdict(set)

        for brel in res["binary_files"]:
            scan_leaks(f"{brel} (dosya adı)", brel.replace(os.sep, "\n"), known_tckns, known_ibans, res["leaks"], check_addr=False)

        for rel, p, s, o, orig_rel in pairs:
            res["files_scanned"] += 1
            scan_leaks(rel, o, known_tckns, known_ibans, res["leaks"])
            scan_leaks(f"{rel} (dosya adı)", rel.replace(os.sep, "\n"), known_tckns, known_ibans, res["leaks"], check_addr=False)

            # Eşleme tablosu sızıntısı: etiket ile ham değer yan yana
            if has_mapping_leak(o):
                res["mapping_leak"].append(rel)
            if s is None:
                if os.path.basename(rel) != REPORT_NAME and not _is_archive_ocr_source(src, orig_rel, archive_cache):
                    if MASK_RE.search(rel):
                        res["masked_name_unmatched"].append(rel)
                    else:
                        res["unexpected_files"].append(rel)
                continue
            res["files_with_source"] += 1

            # E) Koruma
            for kind, rx in PRESERVE_RE.items():
                sv, ov = preserve_view(s), preserve_view(o)
                sc = Counter(re.sub(r'\s+', ' ', m.group(0)) for m in rx.finditer(sv))
                oc = Counter(re.sub(r'\s+', ' ', m.group(0)) for m in rx.finditer(ov))
                res["preserve_total"][kind] += sum(sc.values())
                for val, n in sc.items():
                    if oc[val] < n:
                        res["preserve_lost"][kind].append((rel, val, n - oc[val]))

            if s == o:
                continue
            s_lines = s.splitlines()
            o_lines = o.splitlines()
            sm = difflib.SequenceMatcher(None, s_lines, o_lines, autojunk=False)
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag == "equal":
                    continue
                if tag == "replace" and (i2 - i1) == (j2 - j1):
                    line_pairs = list(zip(range(i1, i2), range(j1, j2)))
                    leftover = False
                else:
                    line_pairs = []
                    leftover = True
                    if tag == "replace":
                        # Satır sayısı farklı: benzerliğe göre eşle, kalanları yutulma say
                        used = set()
                        for jj in range(j1, j2):
                            best, bi = 0.0, None
                            for ii in range(i1, i2):
                                if ii in used:
                                    continue
                                r = difflib.SequenceMatcher(None, s_lines[ii], o_lines[jj]).quick_ratio()
                                if r > best:
                                    best, bi = r, ii
                            if bi is not None and best > 0.3:
                                used.add(bi)
                                line_pairs.append((bi, jj))
                for ii, jj in line_pairs:
                    pieces = extract_mask_pieces(s_lines[ii], o_lines[jj])
                    if pieces is None:
                        pieces = extract_mask_pieces(norm_links(s_lines[ii]), norm_links(o_lines[jj]))
                    if pieces is None:
                        if MASK_RE.search(o_lines[jj]):
                            res["unaligned"].append((rel, jj + 1, [s_lines[ii]], [o_lines[jj]]))
                        continue
                    for label, piece in pieces:
                        if MASK_RE.fullmatch(piece.strip() or "-"):
                            continue  # kaynakta zaten maskeli
                        kind = mask_kind(label)
                        res["over"].append((rel, jj + 1, label, piece, analysis_flags(piece)))
                        if is_numbered(label):
                            nv = norm_value(kind, piece)
                            # TCKN: checksum'ı tutmayan 11 haneli değerler OCR bozulmasıdır; bilinen TCKN'ye
                            # bulanık eşleşip aynı etikete bağlanması tasarım gereğidir, çelişki değildir.
                            if nv and kind == "TCKN" and not is_valid_tckn(nv):
                                nv = None
                            if nv:
                                val_to_labels[(kind, nv)].add(label)
                                label_to_vals[label].add(nv)
                if leftover:
                    paired_i = {ii for ii, _ in line_pairs}
                    rest_src = [s_lines[ii] for ii in range(i1, i2) if ii not in paired_i]
                    if rest_src:
                        res["unaligned"].append((rel, j1 + 1, rest_src, o_lines[j1:j2]))
    finally:
        for tmp_d in archive_cache.values():
            shutil.rmtree(tmp_d, ignore_errors=True)

    res["consistency_value_multi_label"] = {k: v for k, v in val_to_labels.items() if len(v) > 1}
    res["consistency_label_multi_value"] = {k: v for k, v in label_to_vals.items() if len(v) > 1}

    # D) Bağlantılar ve INDEX
    link_re = re.compile(r'!?\[[^\]\n]*\]\((?:<([^>\n]+)>|([^)\s\n]+))\)')
    for rel, p, _s, o, orig_rel in pairs:
        if not rel.endswith(".md"):
            continue
        base_dir = os.path.dirname(p)
        o_nocode = re.sub(r'`[^`\n]*`', '', o)  # kod içindeki örnek bağlantılar sayılmaz
        for m in link_re.finditer(o_nocode):
            target = m.group(1) or m.group(2) or ""
            if re.match(r'(?i)^(?:[a-z]+:|#)', target):
                continue
            target = target.split("#", 1)[0]
            if not target:
                continue
            if not exists_nfc_nfd(base_dir, target):
                src_dir = os.path.dirname(os.path.join(src, orig_rel))
                if (target.lower().endswith((".md", ".txt", ".json"))
                        and os.path.isdir(src_dir) and not exists_nfc_nfd(src_dir, target)):
                    res["source_broken_links"].append((rel, target))
                else:
                    res["broken_links"].append((rel, target))
        if os.path.basename(rel) == "INDEX.md":
            for m in re.finditer(r'\[↗\]\(<([^>]+)>\)\s*\(([\d.]+)\s*karakter\)', o):
                target, cnt = m.group(1), int(m.group(2).replace(".", ""))
                for form in ("NFC", "NFD"):
                    fp = os.path.join(base_dir, unicodedata.normalize(form, target))
                    if os.path.isfile(fp):
                        actual = len(read_text(fp) or "")
                        if actual != cnt:
                            res["index_mismatch"].append((rel, target, cnt, actual))
                        break
    return res


def summarize(res: Dict) -> Tuple[List[str], List[str], bool]:
    L = res["leaks"]
    out_lines, det = [], []
    leak = bool(L["tckn"] or L["tckn_known"] or L["iban"] or L["iban_known"] or L["iban_multiline"]
                or L["phone"] or L["addr_kisi"])

    out_lines.append(f"Taranan dosya: {res['files_scanned']} (kaynağı bulunan: {res['files_with_source']})")
    out_lines.append("== A) SIZINTI ==")
    for key, name in [("tckn", "Geçerli TCKN (bitişik)"), ("tckn_known", "Kaynak TCKN'si çıktıda"),
                      ("tckn_possible", "Olası bölünmüş/OCR TCKN"), ("iban", "Ham IBAN"),
                      ("iban_known", "Kaynak IBAN'ı çıktıda"), ("iban_multiline", "Satırlara bölünmüş IBAN"),
                      ("phone", "Maskesiz cep telefonu"),
                      ("addr_kisi", "Maskesiz adres (kişi)"), ("addr_kurum", "Maskesiz adres (kurum)"),
                      ("addr_olay", "Maskesiz adres (olay yeri)")]:
        items = L[key]
        files = sorted({x[0] for x in items})
        out_lines.append(f"  {name}: {len(items)}" + (f"  dosyalar: {', '.join(files[:8])}" + (" ..." if len(files) > 8 else "") if files else ""))
        for x in items:
            det.append(f"A\t{key}\t" + "\t".join(str(v) for v in x))

    out_lines.append("== B) FAZLA MASKELEME / MASKE DÖKÜMÜ ==")
    by_kind = Counter(mask_kind(x[2]) for x in res["over"])
    flagged = [x for x in res["over"] if x[4]]
    out_lines.append(f"  Yeni maske toplamı: {len(res['over'])}  türlere göre: " + ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items())))
    fl_c = Counter(f for x in flagged for f in x[4])
    out_lines.append(f"  ANALİZ VERİSİ MASKELENMİŞ: {len(flagged)}  " + ", ".join(f"{k}={v}" for k, v in sorted(fl_c.items())))
    out_lines.append(f"  Hizalanamayan / çok satırlı yutulma: {len(res['unaligned'])}")
    for rel, ln, label, piece, flags in res["over"]:
        det.append(f"B\t{rel}:{ln}\t{label}\t{piece!r}\t{'ANALİZ VERİSİ MASKELENMİŞ:' + ','.join(flags) if flags else ''}")
    for rel, ln, sl, ol in res["unaligned"]:
        det.append(f"B-UNALIGNED\t{rel}:{ln}\tSRC={sl!r}\tOUT={ol!r}")

    out_lines.append("== C) TUTARLILIK ==")
    vm, lm = res["consistency_value_multi_label"], res["consistency_label_multi_value"]
    out_lines.append(f"  Bir değer >1 etiket: {len(vm)}   Bir etiket >1 değer: {len(lm)}")
    for k, v in vm.items():
        det.append(f"C\tdeger-cok-etiket\t{k}\t{sorted(v)}")
    for k, v in lm.items():
        det.append(f"C\tetiket-cok-deger\t{k}\t{sorted(v)}")

    out_lines.append("== D) YAPI ==")
    out_lines.append(f"  İkili dosya: {len(res['binary_files'])}   Kopuk bağlantı: {len(res['broken_links'])}   "
                     f"INDEX karakter uyuşmazlığı: {len(res['index_mismatch'])}   "
                     f"Eşleme/değer sızdıran dosya: {len(res['mapping_leak'])}   "
                     f"Kaynakta da kopuk metin bağlantısı (sayılmaz): {len(res['source_broken_links'])}   "
                     f"Kaynağı olmayan beklenmedik dosya: {len(res['unexpected_files'])}   "
                     f"Eşleşmeyen maskeli yol (bilgi): {len(res['masked_name_unmatched'])}")
    for x in res["binary_files"]:
        det.append(f"D\tikili\t{x}")
    for x in res["broken_links"]:
        det.append(f"D\tkopuk\t{x[0]}\t{x[1]}")
    for x in res["source_broken_links"]:
        det.append(f"D\tkaynakta-kopuk\t{x[0]}\t{x[1]}")
    for x in res["index_mismatch"]:
        det.append(f"D\tindex\t{x}")
    for x in res["mapping_leak"]:
        det.append(f"D\tesleme\t{x}")
    for x in res["unexpected_files"]:
        det.append(f"D\tbeklenmedik\t{x}")
    for x in res["masked_name_unmatched"]:
        det.append(f"D\tmaskeli-eslesmeyen\t{x}")
    if res["unexpected_files"]:
        out_lines.append(f"    beklenmedik: {', '.join(res['unexpected_files'][:8])}")

    out_lines.append("== E) KORUMA ==")
    for kind in PRESERVE_RE:
        tot = res["preserve_total"][kind]
        lost = sum(x[2] for x in res["preserve_lost"][kind])
        rate = 100.0 * (tot - lost) / tot if tot else 100.0
        out_lines.append(f"  {kind}: kaynakta {tot}, kayıp {lost} (korunma %{rate:.2f})")
        for x in res["preserve_lost"][kind]:
            det.append(f"E\t{kind}\t{x[0]}\t{x[1]!r}\tx{x[2]}")

    out_lines.append(f"SONUÇ: {'SIZINTI VAR' if leak else 'sızıntı bulunmadı (A ölçütleri)'}")
    return out_lines, det, leak


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Maskeli UYAP çıktı klasörü denetimi")
    ap.add_argument("source")
    ap.add_argument("output")
    ap.add_argument("--ocr-cache", default=None)
    ap.add_argument("--details", default=None, help="Ham değerli ayrıntı dosyası (paylaşmayın)")
    a = ap.parse_args(argv)
    res = audit(a.source, a.output, a.ocr_cache)
    lines, det, leak = summarize(res)
    print("\n".join(lines))
    if a.details:
        with open(a.details, "w", encoding="utf-8") as f:
            f.write("\n".join(det) + "\n")
    return 1 if leak else 0


if __name__ == "__main__":
    sys.exit(main())
