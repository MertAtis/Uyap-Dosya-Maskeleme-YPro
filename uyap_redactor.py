#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UYAP Çevrimdışı Kişisel Veri Maskeleme ve İndeks Senkronizasyon Aracı (uyap_redactor.py)
---------------------------------------------------------------------------------------
Orijinale dokunmama ilkesi (Non-Destructive):
UYAP dosyalarını salt-okunur modda bellekte okur ve belirlenen kişisel veri kategorilerini
maskeler. Olay örgüsü, tarihler, para tutarları, mahkeme/esas numaraları, kanun maddeleri,
anne/baba adları ve taraf ad-soyadları korunur.

Hedef kişisel veri kategorileri (export'ta tutarlı numaralı etiket; registry'siz çağrıda eski etiket):
1. T.C. Kimlik No / YKN (10 hane yazım hatalı TCKN dahil) -> [TCKN_n]     / [TCKN_GİZLENDİ]
2. Türkiye cep telefonu (05xx, +90 5xx vb.)                -> [TEL_n]      / [TELEFON_GİZLENDİ]
3. Kimlik kartı seri no (yeni/eski)                        -> [SERİ_NO_n]  / [SERİ_NO_GİZLENDİ]
4. Kimlik kartı ve pasaport ICAO/MRZ şeritleri             -> [MRZ_n]      / [KİMLİK_MRZ_KODU_GİZLENDİ]
5. IBAN                                                    -> [IBAN_n]     / [IBAN_GİZLENDİ]
6. Banka kartı no                                          -> [KART_n]     / [KART_NO_GİZLENDİ]
7. Banka hesap / müşteri no (hesap bağlamında)             -> [HESAP_n]    / [HESAP_NO_GİZLENDİ]
8. Kişiye ait açık adres                                   -> [ADRES_n]    / [ADRES_GİZLENDİ]
9. Sicil no (hâkim/savcı/kâtip/bilirkişi/baro/ticaret)     -> [SİCİL_n]    / [SİCİL_GİZLENDİ]

İzole temiz klasör: dava klasöründen yalnızca maskelenmiş .md evraklarından oluşan, taranmış
ekleri yerel Apple Vision OCR ile metne döken ve INDEX.md karakter sayılarını güncelleyen ayrı
bir klasör üretir. Orijinal dosyalara dokunmaz. Kural tabanlı maskeleme hatasız değildir.
"""

import os
import re
import shutil
import sys
import unicodedata
import urllib.parse
from datetime import datetime
from collections import Counter
from typing import Callable, Dict, List, Optional, Set, Tuple


def _ocr_digits(val: str) -> str:
    """OCR kaynaklı l/I/| -> 1, O/o -> 0, J -> 3 dönüşümü."""
    return (
        val.replace('l', '1').replace('I', '1').replace('|', '1')
        .replace('O', '0').replace('o', '0').replace('J', '3')
    )


def _tr_lower(x: str) -> str:
    return x.replace("I", "ı").replace("İ", "i").lower()


class MaskRegistry:
    """
    Tutarlı numaralı maske etiketleri üretir: aynı değer her belgede aynı etikete
    ([TCKN_1], [IBAN_2], [ADRES_3] ...) dönüşür; farklı değerler farklı numara alır.
    Numara, değerin ilk görülme sırasına göre verilir.

    GÜVENLİK: Eşleme (değer -> etiket) YALNIZCA bellekte tutulur. Bu sınıfın diske
    yazma / dışa aktarma metodu yoktur ve bilerek eklenmemelidir; aksi halde maskeli
    klasörün yanında ham değerler dağıtılmış olur.
    """

    PREFIX = {
        "tckn": "TCKN", "iban": "IBAN", "kart": "KART", "hesap": "HESAP",
        "telefon": "TEL", "seri_no": "SERİ_NO", "mrz": "MRZ", "sicil": "SİCİL", "adres": "ADRES",
    }

    _ADDR_ABBR = {
        "mahallesi": "mah", "mahalle": "mah", "mah": "mah", "mh": "mah",
        "caddesi": "cad", "cadde": "cad", "cad": "cad", "cd": "cad",
        "sokağı": "sk", "sokagi": "sk", "sokak": "sk", "sok": "sk", "sk": "sk", "5k": "sk",
        "numara": "no", "numaralı": "no", "no": "no", "ne": "no",
        "daire": "d", "d": "d", "da": "d", "kat": "k", "k": "k",
    }

    def __init__(self, known_tckns: Optional[Set[str]] = None):
        self._labels: Dict[Tuple[str, str], str] = {}
        self._next: Counter = Counter()
        self._known_tckns: Set[str] = {t for t in (known_tckns or ()) if len(t) == 11 and t.isdigit()}
        self._addr_keys: List[Tuple[str, str]] = []  # (normalize anahtar, etiket)
        self.occurrences: Counter = Counter()          # tür -> maskelenen yer sayısı
        self._seed: Dict[str, Set[str]] = {}            # ön taramada öğrenilen değerler (bellek içi)

    # -- Normalize anahtarlar -------------------------------------------------
    def _tckn_key(self, raw: str) -> str:
        norm = re.sub(r'\D', '', _ocr_digits(raw))
        pool = self._known_tckns
        if len(norm) == 11 and UyapRedactor.is_valid_tckn(norm):
            self._known_tckns.add(norm)
            return norm
        # Kısmi maskeli ("212*****428", "382---566"): ilk3 + son3
        if re.search(r'[\*\-"]', raw) and 6 <= len(norm) <= 8:
            f3, l3 = norm[:3], norm[-3:]
            cands = [t for t in pool if t[:3] == f3 and t[-3:] == l3]
            if len(cands) == 1:
                return cands[0]
            return f"P:{f3}*{l3}"
        cands: Set[str] = set()
        if len(norm) == 11:
            cands = {t for t in pool if sum(a != b for a, b in zip(norm, t)) <= 2}
        elif len(norm) >= 12:
            cands = {t for t in pool if t in norm}
        if not cands and len(norm) >= 9:
            cands = {t for t in pool if t[:5] == norm[:5]} or {t for t in pool if t[-4:] == norm[-4:]}
        if len(cands) == 1:
            return next(iter(cands))
        if len(norm) == 11:
            self._known_tckns.add(norm)
        return f"R:{norm}"

    @staticmethod
    def _iban_key(raw: str) -> str:
        m = re.search(r'(?i)TR', raw)
        rest = raw[m.end():] if m else raw
        digits = re.sub(r'\D', '', _ocr_digits(rest).replace('S', '5').replace('B', '8'))
        return "TR" + digits[:24]

    @classmethod
    def _addr_key(cls, raw: str) -> str:
        toks = re.findall(r'[a-zçğıöşüâîû0-9]+', _tr_lower(raw))
        toks = [cls._ADDR_ABBR.get(t, t) for t in toks]
        # İl/ilçe kuyruğunu at: son sayısal belirteçte (kapı/daire/kat no) kes
        last_num = -1
        for i, t in enumerate(toks):
            if any(c.isdigit() for c in t):
                last_num = i
        if last_num >= 1:
            toks = toks[:last_num + 1]
        return "".join(toks)

    def key(self, kind: str, raw: str) -> str:
        if kind == "tckn":
            return self._tckn_key(raw)
        if kind == "iban":
            return self._iban_key(raw)
        if kind == "telefon":
            d = re.sub(r'\D', '', raw)
            return d[-10:]
        if kind in ("sicil", "hesap"):
            return re.sub(r'\D', '', raw) or raw.strip()
        if kind == "kart":
            return re.sub(r'[^\d\*xX]', '', raw)
        if kind == "seri_no":
            return re.sub(r'[^A-Z0-9]', '', raw.upper())
        if kind == "mrz":
            return re.sub(r'\s', '', raw)
        if kind == "adres":
            return self._addr_key(raw)
        return raw

    # -- Etiket ---------------------------------------------------------------
    def label(self, kind: str, raw: str) -> str:
        self.occurrences[kind] += 1
        k = self.key(kind, raw)
        if kind == "adres" and k:
            for ek, lab in self._addr_keys:
                if ek == k or (len(ek) >= 12 and k.startswith(ek)) or (len(k) >= 12 and ek.startswith(k)):
                    return lab
        lab = self._labels.get((kind, k))
        if lab is None:
            self._next[kind] += 1
            lab = f"[{self.PREFIX[kind]}_{self._next[kind]}]"
            self._labels[(kind, k)] = lab
            if kind == "adres" and k:
                self._addr_keys.append((k, lab))
        return lab

    def known_values(self, kind: str, min_len: int = 1) -> Set[str]:
        """Bu türde etiketlenmiş normalize değerler (yalnızca bellek içi eşleştirme için)."""
        vals = {k for (kd, k) in self._labels if kd == kind and k.isdigit()}
        vals |= self._seed.get(kind, set())
        return {v for v in vals if len(v) >= min_len}

    def seed(self, kind: str, values: Set[str]) -> None:
        """Ön taramada (bağlamıyla) tespit edilmiş değerleri, bağlamsız geçtikleri yerde de tanımak için ekler."""
        self._seed.setdefault(kind, set()).update(values)

    def distinct(self, kind: str) -> int:
        """Bu türde kaç farklı etiket üretildi."""
        return self._next[kind]


class UyapRedactor:
    """UYAP metinleri için çevrimdışı, kural tabanlı kişisel veri maskeleme sınıfı."""

    MASK_TCKN = "[TCKN_GİZLENDİ]"
    MASK_TELEFON = "[TELEFON_GİZLENDİ]"
    MASK_SERI_NO = "[SERİ_NO_GİZLENDİ]"
    MASK_MRZ = "[KİMLİK_MRZ_KODU_GİZLENDİ]"
    MASK_IBAN = "[IBAN_GİZLENDİ]"
    MASK_KART = "[KART_NO_GİZLENDİ]"
    MASK_HESAP = "[HESAP_NO_GİZLENDİ]"
    MASK_ADRES = "[ADRES_GİZLENDİ]"
    MASK_SICIL = "[SİCİL_GİZLENDİ]"

    _LEGACY_MASK = {
        "tckn": MASK_TCKN, "telefon": MASK_TELEFON, "seri_no": MASK_SERI_NO, "mrz": MASK_MRZ,
        "iban": MASK_IBAN, "kart": MASK_KART, "hesap": MASK_HESAP, "adres": MASK_ADRES,
        "sicil": MASK_SICIL,
    }

    # Hem eski sabit hem numaralı etiketleri tanıyan kalıplar
    MASK_ADRES_RE = r'\[ADRES_(?:GİZLENDİ|\d+)\]'
    MASK_TCKN_RE = r'\[TCKN_(?:GİZLENDİ|\d+)\]'
    MASK_ANY_RE = (
        r'\[(?:[A-ZÇĞİÖŞÜ_]+_GİZLENDİ|(?:TCKN|IBAN|KART|HESAP|TEL|SERİ_NO|MRZ|SİCİL|ADRES)_\d+)\]'
    )

    @classmethod
    def _mask(cls, kind: str, raw: str, registry: Optional[MaskRegistry]) -> str:
        """registry yoksa eski sabit etiketi, varsa tutarlı numaralı etiketi döndürür."""
        if registry is None:
            return cls._LEGACY_MASK[kind]
        return registry.label(kind, raw)

    @classmethod
    def _has_mask(cls, s: str, kind_re: Optional[str] = None) -> bool:
        return bool(re.search(kind_re or cls.MASK_ANY_RE, s))

    # Adli/İdari Unvan listesi (Hâkim, Savcı, Kâtip, Mübaşir, Müdür ve OCR varyasyonları)
    TITLES_REGEX = (
        r'(?:Başkan|Üye|H[aâ]k[ıi]m|Mak[ıi][nml]|'
        r'(?:(?:Cumhuriyet|Soruşturma|Nöbetçi|Bilişim\s+Suçlar[ıi])\s+)?(?:Baş)?savc[ıi](?:s[ıi])?(?:\s+Vekili)?|'
        r'C\.\s*Savc[ıi]s[ıi]|K[aâ]t[ıi]p|Kal[ıi]p|Z\.?\s*K[aâ]t[ıi]bi|Zab[ıi]t\s+K[aâ]t[ıi]bi|'
        r'Mübaş[ıi]r|Müb\.?|Yaz[ıi]\s+İşleri\s+Müdürü)(?!\w)'
    )

    # Sicil sanılmaması gereken sayı sonekleri (para birimi, "sayılı" kanun/karar, Esas/Karar no)
    NOT_SICIL_SUFFIX = r'(?!\s*(?:TL|Türk\s*Liras[ıi]|USD|EUR|say[ıi]l[ıi]|Esas|Karar)\b)'

    # Klasör taramalarında atlanacak dizin adları (yalnızca tam ad eşleşmesi)
    SKIP_DIRS = ("_kaynak", ".git", "node_modules")
    SKIP_DIRS_OCR = (".git", "node_modules")

    # Yargı PRO manifest JSON dosyaları (değer bazında maskelenerek aktarılır)
    META_JSON_NAMES = ("uyap-project.json", "uyap-evrak-listesi.json")

    STAT_KEYS = ("tckn", "telefon", "seri_no", "mrz", "iban", "hesap", "sicil", "adres", "total")

    @classmethod
    def _empty_stats(cls) -> Dict[str, int]:
        return {k: 0 for k in cls.STAT_KEYS}

    @staticmethod
    def _is_skipped_dir(root: str, base: str, skip_names) -> bool:
        """
        'root' dizininin, 'base' klasörüne göre göreli yol bileşenlerinden herhangi biri
        'skip_names' içindeki bir adla TAM eşleşiyorsa True döner.
        Kaynak klasörün ÜST yolunda geçen '.git' / '_kaynak' alt dizeleri (örn. 'my.gitrepo',
        '.github') dikkate alınmaz.
        """
        rel = os.path.relpath(root, base)
        if rel in (".", ""):
            return False
        return any(part in skip_names for part in rel.split(os.sep))

    @staticmethod
    def _is_inside_path(path: str, parent: str) -> bool:
        """'path', 'parent' ile aynı veya onun alt dizini mi? (alt-dize değil, yol-öneki karşılaştırması)"""
        parent = parent.rstrip(os.sep)
        return path == parent or path.startswith(parent + os.sep)

    @staticmethod
    def _is_date_or_esas_number(raw: str) -> bool:
        """
        Sayı dizisi içinde eğik çizgili tarih (g/a/yyyy) veya yıl/esas (19xx|20xx/...) biçiminde
        bir parça varsa True döner. Bu biçimler TCKN sanılarak maskelenmemelidir.
        """
        compact = re.sub(r'[ \t]*/[ \t]*', '/', raw)
        for token in compact.split():
            if re.fullmatch(r'\d{1,2}/\d{1,2}/\d{4}', token):
                return True
            if re.fullmatch(r'(?:19|20)\d{2}/[^/\s]+', token):
                return True
        return False

    @staticmethod
    def _normalize_ocr_digits(val: str) -> str:
        """OCR kaynaklı l/I/| -> 1, O/o -> 0, J -> 3 dönüşümünü yapar."""
        return (
            val.replace('l', '1')
            .replace('I', '1')
            .replace('|', '1')
            .replace('O', '0')
            .replace('o', '0')
            .replace('J', '3')
        )

    @staticmethod
    def is_valid_luhn(card_no: str) -> bool:
        """16 haneli banka/kredi kartı numaraları için Luhn algoritması doğrulaması."""
        digits_str = re.sub(r'[\s\-]', '', card_no)
        if len(digits_str) != 16 or not digits_str.isdigit():
            return False
        if len(set(digits_str)) == 1:
            return False
        digits = [int(d) for d in digits_str]
        total = 0
        for i, d in enumerate(reversed(digits)):
            if i % 2 == 1:
                d *= 2
                if d > 9:
                    d -= 9
            total += d
        return total % 10 == 0

    @staticmethod
    def is_valid_tckn(tckn: str) -> bool:
        """
        T.C. Kimlik Numarası (ve Yabancı Kimlik Numarası) Mod-10/Mod-11
        algoritma doğrulama fonksiyonu.

        Kural:
        1. 11 haneli ve tamamen rakamlardan oluşmalı.
        2. İlk hane 0 olamaz.
        3. 10. Hane = ((1, 3, 5, 7, 9. haneler toplamı * 7) - (2, 4, 6, 8. haneler toplamı)) % 10
        4. 11. Hane = İlk 10 hanenin toplamı % 10
        """
        if not isinstance(tckn, str) or len(tckn) != 11 or not tckn.isdigit():
            return False
        if tckn[0] == '0':
            return False
        # Tüm haneleri aynı olan sayıları (11111111110 vb.) ele
        if len(set(tckn[:10])) == 1:
            return False

        digits = [int(c) for c in tckn]
        odd_sum = digits[0] + digits[2] + digits[4] + digits[6] + digits[8]
        even_sum = digits[1] + digits[3] + digits[5] + digits[7]

        tenth = ((odd_sum * 7) - even_sum) % 10
        if tenth != digits[9]:
            return False

        eleventh = sum(digits[:10]) % 10
        if eleventh != digits[10]:
            return False

        return True

    @classmethod
    def redact_mrz(cls, text: str, registry: Optional[MaskRegistry] = None) -> Tuple[str, int]:
        """
        Katman 1: Kimlik kartları ve pasaportların altındaki ICAO/MRZ kodlarını maskeler.
        - Kimlik kartı 3 satırlı TD1 MRZ şeridi (I<TUR..., 6301101M..., SOYAD<<AD...)
        - Pasaport 2 satırlı TD3 MRZ şeridi (P<TUR...)
        - Bağımsız veya parçalanmış tekil MRZ satırları (Fallback)
        """
        count = 0

        # 1. 3 Satırlı TD1 Kimlik Kartı MRZ bloğu
        p_block_3 = re.compile(
            r'(?m)^[ \t]*(?:I[<D][A-Z0-9< ]{10,}|P<[A-Z0-9< ]{10,})[ \t]*\r?\n[ \t]*[\d<]{6,}[A-Z0-9< ]{10,}[ \t]*\r?\n[ \t]*[A-Z0-9< ]+<+[A-Z0-9< ]+[ \t]*$'
        )

        def repl_block(m: re.Match) -> str:
            nonlocal count
            count += 1
            return cls._mask("mrz", m.group(0), registry)

        text = p_block_3.sub(repl_block, text)

        # 2. 2 Satırlı TD3 Pasaport MRZ bloğu
        p_block_2 = re.compile(
            r'(?m)^[ \t]*P<[A-Z0-9< ]{15,}[ \t]*\r?\n[ \t]*[A-Z0-9< ]{20,}[ \t]*$'
        )
        text = p_block_2.sub(repl_block, text)

        # 3. Bağımsız / Parçalanmış tekil MRZ satırları (Fallback)
        p_single_mrz = re.compile(
            r'(?m)^[ \t]*(?:(?:I<TUR|IDTUR|P<TUR|P<)[A-Z0-9< ]{10,}|[0-9]{6,7}[MFmf<][0-9< ]{6,}[A-Z<]{3}[A-Z0-9< ]*|[A-Z0-9< ]+<{2,}[A-Z0-9< ]{8,})[ \t]*$'
        )
        text = p_single_mrz.sub(repl_block, text)

        return text, count

    @classmethod
    def redact_iban(cls, text: str, registry: Optional[MaskRegistry] = None) -> Tuple[str, int]:
        """
        Katman 2: TR ile başlayan IBAN numaralarını ve 16 haneli banka/kredi kartı
        numaralarını maskeler.
        - Boşluklu, bitişik, OCR kaynaklı (l/I/O/^) bozulmalı veya sonuna tekil OCR
          harfi ([A-Za-z]?) yapışmış 24 haneli IBAN'ları yakalar; OCR'ın eklediği 1-2 fazla
          bitişik hane (24-26 rakam) de IBAN sayılır.
        - Etiketli kart numaralarını (KART NO: ..., KREDİ KARTI NO: ...) ve
          bağımsız 16 haneli Luhn algoritmasından geçen Visa/Mastercard ([45]\\d{15})
          numaralarını yakalar.
        """
        count = 0
        pattern = re.compile(
            r'(?im)(?:^|(?<=[\s\*\_\(\[\"\'\:\-\^\|])|(?<=^[Il1\|])|(?<=[\s\(\:][Il1\|]))[Tİ][RA][ \t\^\.\-]*(?:[0-9lIOoSB][ \t\^\.\-]*){23}[0-9lIOoSB](?:[0-9]{1,2})?(?:[A-Za-z](?![A-Za-z0-9]))?(?![0-9])'
        )

        def repl(m: re.Match) -> str:
            nonlocal count
            raw = m.group(0)
            digit_count = sum(c.isdigit() for c in raw)
            if digit_count >= 15:
                count += 1
                return cls._mask("iban", raw, registry)
            return raw

        redacted = pattern.sub(repl, text)

        # 2A-2. Dörtlü gruplarla yazılmış IBAN: satır sonunda bölünmüş veya OCR'ın 1-4 hane
        # eksik okuduğu biçimler ("TR12 3456 7890 1234\n5678 9012", "TR12 ... 9012 3:")
        p_grouped = re.compile(
            r'(?<![A-Za-z0-9])TR\d{2}(?:[ \t]+\d{4}){2}(?:(?:[ \t]+|[ \t]*\r?\n[ \t]*)\d{1,4}(?![\d.]))+'
        )

        def repl_grouped(m: re.Match) -> str:
            nonlocal count
            raw = m.group(0)
            if sum(c.isdigit() for c in raw) < 18:
                return raw
            count += 1
            return cls._mask("iban", raw, registry)

        redacted = p_grouped.sub(repl_grouped, redacted)

        # 2A-3. OCR'ın hane düşürdüğü/eklediği IBAN: "TR" + 18-26 rakam, en çok 2 tek boşlukla
        p_ocr_len = re.compile(r'(?<![A-Za-z0-9])TR\d{2}\d+(?: \d+){0,2}(?![\d.,]\d)')

        def repl_ocr_len(m: re.Match) -> str:
            nonlocal count
            raw = m.group(0)
            if not 18 <= sum(c.isdigit() for c in raw) <= 26:
                return raw
            count += 1
            return cls._mask("iban", raw, registry)

        redacted = p_ocr_len.sub(repl_ocr_len, redacted)

        # 2B-1. Etiketli 16 haneli Kredi / ATM Kartı Numarası
        p_card_labeled = re.compile(
            r'(?i)(?P<label>\b(?:KART\s*NO|KRED[İI]\s*KART[Iİ]\s*NO)[\s\*:]+)(?P<card>(?:\d{4}[\s\-]?){3}\d{4}|\d{16})\b'
        )

        def repl_card_labeled(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('label')}{cls._mask('kart', m.group('card'), registry)}"

        redacted = p_card_labeled.sub(repl_card_labeled, redacted)

        # 2B-2. Bağımsız 16 haneli Luhn algoritmasından geçen Visa/Mastercard numaraları
        p_card_luhn = re.compile(r'(?<![0-9A-Za-z])(?P<card>[45]\d{15})(?![0-9A-Za-z])')

        def repl_card_luhn(m: re.Match) -> str:
            nonlocal count
            val = m.group('card')
            if cls.is_valid_luhn(val):
                count += 1
                return cls._mask("kart", val, registry)
            return val

        redacted = p_card_luhn.sub(repl_card_luhn, redacted)

        # 2B-3. 4-4-4-4 boşluklu/tireli kart numarası: kart ağı öneki (3-6) + Luhn şartı
        # (Mersis "0929 0810 0339 0757" gibi 0 ile başlayan kurum numaraları korunur)
        p_card_spaced = re.compile(r'(?<![\d\w])(?P<card>[3-6]\d{3}(?:[ \-]\d{4}){3})(?![\d\w])')

        def repl_card_spaced(m: re.Match) -> str:
            nonlocal count
            val = m.group('card')
            before = m.string[max(0, m.start() - 30):m.start()]
            if re.search(r'(?i)mersis|ref|bpm|barkod|evrak|dekont', before):
                return val
            if cls.is_valid_luhn(val):
                count += 1
                return cls._mask("kart", val, registry)
            return val

        redacted = p_card_spaced.sub(repl_card_spaced, redacted)

        # 2B-4. Banka tarafından kısmen maskelenmiş kart no ("5406 67** **** 1234", "540667******1234")
        p_card_partial = re.compile(
            r'(?<![\d\w])(?P<card>\d{4}[ \-]?\d{2}[\*xX]{2}[ \-]?[\*xX]{4}[ \-]?\d{4}|\d{6}[\*xX]{6}\d{4})(?![\d\w])'
        )

        def repl_card_partial(m: re.Match) -> str:
            nonlocal count
            count += 1
            return cls._mask("kart", m.group('card'), registry)

        redacted = p_card_partial.sub(repl_card_partial, redacted)

        # 2C. Satırlara/başlıklara bölünmüş IBAN ("### 34019161 4610 TR4100\n\n### 010000\n\n### 413246 ...")
        p_iban_ml = re.compile(
            r'TR(?=\d{2})(?:(?:[ \t\.\-]|[ \t]*\r?\n(?:[ \t]*\r?\n)?[ \t#\*\|]*)*[0-9]){24}(?![0-9])'
        )

        def repl_iban_ml(m: re.Match) -> str:
            nonlocal count
            raw = m.group(0)
            if '\n' not in raw:
                return raw
            count += 1
            return cls._mask("iban", raw, registry)

        redacted = p_iban_ml.sub(repl_iban_ml, redacted)
        return redacted, count

    # Hesap/müşteri/kart numarası sütun başlıkları (tablo hücresi tam eşleşmesi, ascii-katlanmış)
    _ACCOUNT_HEADER_RE = re.compile(
        r'^(?:hesap|eski hesap|hesap ?(?:no|numarasi)|hesapno|musteri ?(?:no|numarasi)|musterino|mbb ?no|'
        r'mars(?: ?no)?|hesap ?no ?\(?ek\)?)$'
    )
    _CARD_HEADER_RE = re.compile(r'^(?:kart ?(?:no|numarasi)|kartno)$')

    @staticmethod
    def _fold(x: str) -> str:
        x = _tr_lower(x.strip().strip('*').strip())
        for a, b in (("ç", "c"), ("ğ", "g"), ("ı", "i"), ("ö", "o"), ("ş", "s"), ("ü", "u"), ("i̇", "i")):
            x = x.replace(a, b)
        return re.sub(r'[\s\.:_/]+', ' ', x).strip()

    @classmethod
    def redact_account(cls, text: str, registry: Optional[MaskRegistry] = None) -> Tuple[str, int]:
        """
        Katman 2b: Banka hesap ve müşteri numaraları (yalnızca hesap bağlamında).
        - "4653104 numaralı hesap", "Hesap No: 12345678", "hesap numarası 1234-5678901", "Müşteri No : 3693612"
        - Markdown tablolarında (ör. *.xlsx.md) "Hesap No / Hesap Numarası / Müşteri No / MBB No" sütunları
          altındaki hücreler (kart no sütunu kart olarak)
        - "01014015 TL Vadesiz" biçimindeki dökümde hesap numarası
        Tutar, tarih, esas no, şube kodu, dekont/referans no korunur (sütun başlığına göre karar verilir).
        """
        count = 0

        # 1. Tablo sütunları
        lines = text.split('\n')
        acc_cols: Set[int] = set()
        card_cols: Set[int] = set()
        for i, line in enumerate(lines):
            st = line.strip()
            if not (st.startswith('|') and st.endswith('|') and st.count('|') >= 3):
                acc_cols, card_cols = set(), set()
                continue
            cells = st[1:-1].split('|')
            folded = [cls._fold(c) for c in cells]
            hdr_acc = {j for j, c in enumerate(folded) if cls._ACCOUNT_HEADER_RE.match(c)}
            hdr_card = {j for j, c in enumerate(folded) if cls._CARD_HEADER_RE.match(c)}
            if hdr_acc or hdr_card:
                acc_cols, card_cols = hdr_acc, hdr_card
                continue
            if not (acc_cols or card_cols) or re.fullmatch(r'[\s\-:|]+', st):
                continue
            changed = False
            for j in sorted(acc_cols | card_cols):
                if j >= len(cells):
                    continue
                cell = cells[j]
                val = cell.strip()
                if not val or re.search(cls.MASK_ANY_RE, val) or sum(c.isdigit() for c in val) < 4:
                    continue
                kind = "kart" if j in card_cols else "hesap"
                lead = cell[:len(cell) - len(cell.lstrip())]
                trail = cell[len(cell.rstrip()):]
                cells[j] = f"{lead}{cls._mask(kind, val, registry)}{trail}"
                count += 1
                changed = True
            if changed:
                indent = line[:len(line) - len(line.lstrip())]
                tail = line[len(line.rstrip()):]
                lines[i] = f"{indent}|{'|'.join(cells)}|{tail}"
        text = '\n'.join(lines)

        def repl_num(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('pre')}{cls._mask('hesap', m.group('num'), registry)}{m.group('post')}"

        # 2. "4653104 numaralı hesap(ı)", "20278199 nolu hesabı"
        p_num_first = re.compile(
            r'(?i)(?P<pre>)(?<![\d\w/\.])(?P<num>\d[\d\-]{4,22}\d)(?P<post>\s+(?:numaral[ıi]|no\.?lu|no\'lu|nolu)\s+'
            r'(?:\w+\s+){0,2}?(?:hesa[bp]|mevduat|kredi\s+kart))'
        )
        text = p_num_first.sub(repl_num, text)

        # 3. Etiketli: "Hesap No: 12345678", "hesap numarası 1234-5678901", "Müşteri No : 3693612"
        p_labeled = re.compile(
            r'(?i)(?P<pre>\b(?:hesap|m[uü]şteri|musteri)\s*(?:no|numaras[ıi]|numara)\b\.?[ \t\*]*[:\-]?[ \t\*]*)'
            r'(?P<num>\d[\d\- ]{3,22}\d)(?![\d/\.,])(?P<post>)'
        )

        def repl_labeled(m: re.Match) -> str:
            num = m.group('num').strip()
            if re.fullmatch(r'(?:19|20)\d{2}', num):
                return m.group(0)
            return repl_num(m)

        text = p_labeled.sub(repl_labeled, text)

        # 4. Döküm satırı: "01014015 TL Vadesiz 0.00"
        p_dump = re.compile(
            r'(?im)(?P<pre>^[ \t#\*]*)(?P<num>(?=[0-9A-Z]*\d[0-9A-Z]*\d[0-9A-Z]*\d[0-9A-Z]*\d)[0-9A-Z]{6,14})'
            r'(?P<post>\s+(?:TL|TRY|USD|EUR|GBP|ALT[İI]N)\s+(?:Vadesiz|Vadeli|Yat[ıi]r[ıi]m|Kredi|Mevduat|Kart))'
        )
        text = p_dump.sub(repl_num, text)

        # 5. IBAN maskesinden hemen önce gelen "müşteri no + ek no" ("### 34019161 4610 [IBAN_1]")
        p_before_iban = re.compile(
            r'(?P<pre>(?:^|(?<=[\s#\|])))(?P<num>\d{6,10})(?P<post>[ \t]+\d{3,5}[ \t]+)(?=' + cls.MASK_ANY_RE + r')'
        )

        def repl_before_iban(m: re.Match) -> str:
            nonlocal count
            if not re.match(r'\[IBAN_', m.string[m.end():m.end() + 6]):
                return m.group(0)
            count += 1
            # Yalnızca müşteri no maskelenir; ek no (5001, 5002 ...) tek başına tanımlayıcı değildir
            return f"{cls._mask('hesap', m.group('num'), registry)}{m.group('post')}"

        text = p_before_iban.sub(repl_before_iban, text)

        # 6. Klasörde hesap bağlamında tespit edilmiş hesap numarası başka yerde çıplak geçerse
        if registry is not None:
            known = registry.known_values("hesap", min_len=7)
        else:
            known = set()
        if known:
            alt = "|".join(sorted((re.escape(k) for k in known), key=len, reverse=True))
            p_known = re.compile(r'(?<!\d)(?P<pre>)(?P<num>' + alt + r')(?!\d)(?P<post>)')
            text = p_known.sub(repl_num, text)
        # 7. Banka döküm biçimi "2450-61231007-728" (şube-hesap-ek)
        p_dashed = re.compile(r'(?<![\d\w-])(?P<pre>)(?P<num>\d{4}-\d{7,9}-\d{3})(?![\d\w-])(?P<post>)')
        text = p_dashed.sub(repl_num, text)

        return text, count

    @classmethod
    def redact_seri_no(cls, text: str, registry: Optional[MaskRegistry] = None) -> Tuple[str, int]:
        r"""
        Katman 3: Kimlik kartı seri numaralarını maskeler.
        - Yeni çipli kimlik kartı seri no: [A-Z]\d{2}[A-Z]\d{5} veya [A-Z]\d{2}[\s-]?[A-Z]\d{5} (Örn: A12B34567, A12 B34567)
        - Eski nüfus cüzdanı seri no: [A-Z]\d{2}[\s-]?[0-9]{6} (Örn: A01 123456, A01123456, A01-123456)
        - Açık etiketli seri no kalıpları (Seri No: ..., Belge No: ..., Cüzdan No: ...)
        - 'Seri: A01 No: 123456' formatındaki bölünmüş eski nüfus cüzdanı kalıpları
        - Noter vekaletnamelerindeki ters sıralı 'A10 seri ve 123456 numaralı' kalıpları
        Plakalar (34 ABC 123) ve dosya esas numaraları (2024/623) korunur.
        """
        count = 0

        # Bölünmüş eski nüfus cüzdanı ("Seri: A01 No: 123456")
        p_split_old = re.compile(
            r'(?i)\bSeri[\s\*:]+([A-Z]\d{2})[\s\*]+No[\s\*:]+(\d{6})\b'
        )

        def repl_split_old(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"Seri No: {cls._mask('seri_no', m.group(1) + m.group(2), registry)}"

        text = p_split_old.sub(repl_split_old, text)

        # Noter vekaletnamesi ters sıralı seri ve no ("A10 seri ve 123456 numaralı", OCR "A1D seri ve 123456 numaralı")
        p_noter_old = re.compile(
            r'(?i)\b([A-Z][0-9OIlD]{2})\s+seri\s+ve\s+(\d{5,6})\s+(?:numaral[ıi]|no\.?lu)'
        )

        def repl_noter_old(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{cls._mask('seri_no', m.group(1) + m.group(2), registry)} seri ve numaralı"

        text = p_noter_old.sub(repl_noter_old, text)

        # Yeni çipli ve standart eski seri no kalıbı
        p = re.compile(
            r'(?i)(?P<label>\b(?:Seri\s*(?:No|Numaras[ıi])?|Belge\s*No|Cüzdan\s*(?:Seri)?\s*No)[\s\*:]+)?'
            r'(?P<val>(?<![A-Za-z0-9])(?:[A-Z]\d{2}[\s-]?[A-Z]\d{5}|[A-Z]\d{2}[\s-]?[0-9]{6})(?![A-Za-z0-9]))'
        )

        def repl(m: re.Match) -> str:
            nonlocal count
            count += 1
            label = m.group('label') or ""
            return f"{label}{cls._mask('seri_no', m.group('val'), registry)}"

        text = p.sub(repl, text)
        return text, count

    # Bağımsız 11 haneli sayı: harf/rakam bitişikliği ve "rakam.rakam" / "rakam/rakam" (tarih, ondalık,
    # yıl/esas) biçimleri dışlanır; cümle sonu noktası ("NUMARASI:123....") veya "123.../Ad" izin verilir.
    _TCKN_STANDALONE_RE = re.compile(
        r'(?<![A-Za-z0-9])(?<!\d[\./])[1-9]\d{10}(?![A-Za-z0-9])(?![\./]\d)'
    )

    @classmethod
    def collect_known_tckns_from_text(cls, text: str) -> Set[str]:
        """Metin içindeki geçerli (Mod-10) veya açık etiketli 11 haneli TCKN'leri toplar."""
        known: Set[str] = set()

        # 1. Geçerli (Mod-10/11) 11 haneli TCKN'ler
        for m in re.finditer(cls._TCKN_STANDALONE_RE, text):
            val = m.group(0)
            if cls.is_valid_tckn(val):
                known.add(val)

        # 2. Açık etiketli TCKN'ler (boşluklu varyasyonlar dahil)
        p_lab = re.compile(
            r'(?i)(?:\b(?:T\.?\s*C\.?(?:\s*(?:KN|Kimlik(?:\s*No(?:su|\.lu|marası)?)?|No(?:su|\.lu|marası)?))?|TCKN|YKN|K[İIÍ]ML[İIÍ]K\s*(?:NO(?:SU)?|NUMARASI))|IT\.?@?N[ºo°])[\s\*\_]*[:\t\.\-]?[\s\*\_]*(?P<num>(?:[0-9lIOJ|/][ \t]*){8,12}[0-9lIOJ|/])(?!\d)(?![A-Za-zÇĞİÖŞÜçğıöşü])'
        )
        for m in p_lab.finditer(text):
            norm = re.sub(r'\D', '', cls._normalize_ocr_digits(m.group('num')))
            if len(norm) == 11 and norm[0] != '0':
                known.add(norm)
            elif len(norm) == 12 and norm[1] != '0':
                known.add(norm[:11])
                known.add(norm[1:12])

        # 3. Sayı önce, etiket sonra gelenler (OCR bozulmalı TCKN + te nolu / T.C. ndu dahil)
        # Etiketten sonra harf gelmemeli (TCK, TCMB, TCDD gibi kısaltmalar etiket sayılmaz)
        p_nf = re.compile(
            r'(?i)(?P<num>(?<!\d)[1-9][0-9lIOoJ|/ ]{8,12}[0-9lIOo]\b)[ \t]*(?:[,\'\-][ \t]*)?(?:(?:T\.?\s*C\.?(?:\'?n[uo]l[uo]|\'?de|\'?ye|\.?nolu|\s*ndu)?|TCKN)(?![^\W\d_])|te\s+nolu\b)'
        )
        for m in p_nf.finditer(text):
            # Tarih (12/03/2015) ve yıl/esas (2021/123456) biçimleri TCKN değildir
            if cls._is_date_or_esas_number(m.group('num')):
                continue
            norm = re.sub(r'\D', '', cls._normalize_ocr_digits(m.group('num')))
            if len(norm) == 11 and norm[0] != '0':
                known.add(norm)

        return known

    @classmethod
    def collect_known_tckns_from_folder(cls, folder: str) -> Set[str]:
        """
        Klasördeki tüm metin dosyalarını tarayarak bilinen TCKN setini (known_tckns) çıkarır.
        Eğer hedef klasör '(Maskelenmis AI)' uzantılıysa ve aynı dizinde kaynak klasörü varsa,
        kök TCKN hafızasını zenginleştirmek için kaynak klasördeki .md dosyalarını da salt-okunur tarar.
        """
        known: Set[str] = set()
        folders_to_scan = [folder]

        norm_folder = unicodedata.normalize("NFC", os.path.abspath(folder).rstrip(os.sep))
        if norm_folder.endswith("(Maskelenmis AI)"):
            orig_cand = re.sub(r'\s*\(Maskelenmis AI\)\s*$', '', norm_folder)
            if os.path.isdir(orig_cand) and orig_cand not in folders_to_scan:
                folders_to_scan.append(orig_cand)

        for scan_dir in folders_to_scan:
            if not os.path.isdir(scan_dir):
                continue
            for root, dirs, files in os.walk(scan_dir):
                if cls._is_skipped_dir(root, scan_dir, cls.SKIP_DIRS):
                    dirs[:] = []
                    continue
                dirs[:] = [d for d in dirs if not cls._is_skipped_dir(os.path.join(root, d), scan_dir, cls.SKIP_DIRS)]
                for f in files:
                    if (f.endswith((".md", ".txt")) and not f.endswith(".bak")) or f in cls.META_JSON_NAMES:
                        fp = os.path.join(root, f)
                        try:
                            with open(fp, "r", encoding="utf-8", errors="replace") as rf:
                                known.update(cls.collect_known_tckns_from_text(rf.read()))
                        except Exception:
                            pass
        return known

    @classmethod
    def redact_tckn(
        cls, text: str, known_tckns: Optional[Set[str]] = None, registry: Optional[MaskRegistry] = None
    ) -> Tuple[str, int]:
        """
        Katman 4: TCKN ve YKN numaralarını maskeler.
        1A) Açık etiketli (TC Kimlik No:, TCKN:, T.C., Kimlik No vb., Markdown kalın/italik dahil)
            ön ekli veya son ekli 9-13 haneli sayılar (10 ve 12 haneli yazım hataları dahil).
        1B) İki Aşamalı Bilinen TCKN Kök Eşleştirmesi (Known TCKN Fuzzy Match):
            - Standart 11 haneli Mod-10/11 doğrulamasından geçen TCKN'ler.
            - Bilinen bir TCKN ile Hamming mesafesi <= 2 olan 11 haneli OCR bozulmalı sayılar.
            - Bilinen bir TCKN'nin ilk 5 hanesi (prefix5) veya son 4 hanesi (suffix4) ile eşleşen
              10-14 karakterlik OCR gürültülü diziler.
            - Banka dekontu OCR'larında boşluk veya |// ile bölünmüş 11 haneli TCKN'ler.
        1C) Tebligatlardaki yıldızlı/tireli kısmi TCKN'ler (TC:123*****890 vb.).
        """
        count = 0
        local_known: Set[str] = set(known_tckns) if known_tckns else set()
        local_known.update(cls.collect_known_tckns_from_text(text))

        # 1A-1. Açık Etiketli TCKN (9-13 hane, boşluklu varyasyonlar, OCR l/I/O/J/|// bozulmaları ve markdown ** bold desteği dahil)
        p_labeled = re.compile(
            r'(?i)(?P<label>(?:\b(?:T\.?\s*C\.?(?:\s*(?:KN|Kimlik(?:\s*No(?:su|\.lu|marası)?)?|No(?:su|\.lu|marası)?))?|TCKN|YKN|K[İIÍ]ML[İIÍ]K\s*(?:NO(?:SU)?|NUMARASI))|IT\.?@?N[ºo°])[\s\*\_]*[:\t\.\-]?[\s\*\_]*)(?P<num>(?:[0-9lIOoJ|/][ \t]*){8,12}[0-9lIOoJ|/])(?!\d)(?![A-Za-zÇĞİÖŞÜçğıöşü])'
        )

        def repl_labeled(m: re.Match) -> str:
            nonlocal count
            raw_num = m.group('num')
            norm_num = re.sub(r'[ \t]', '', raw_num)
            # Eğer numara tarih (12/03/2015) veya yıl/esas formatındaysa (2021/12345678) koru
            if '/' in norm_num and cls._is_date_or_esas_number(raw_num):
                return m.group(0)
            if sum(c.isdigit() for c in norm_num) >= 5:
                count += 1
                return f"{m.group('label')}{cls._mask('tckn', raw_num, registry)}"
            return m.group(0)

        text = p_labeled.sub(repl_labeled, text)

        # 1A-1b. OCR bozulmalı etiket ve/veya ayırıcılı rakamlar (tam 11 hane):
        #  - 'T.C.' yerine 'I.C.' / 'Q.C.' / 'G.c.' / '1.C.' gibi okunan etiketler (numara noktaya bitişik),
        #  - 'TC Kiırılik No.' / 'Krmlik No;' gibi bozulmuş 'Kimlik No' etiketleri,
        #  - 'TC KİMLİK NO......:' gibi nokta dizili etiketler, rakamlar arasında boşluk/nokta/^ bulunan değerler.
        p_labeled_ocr = re.compile(
            r'(?i)(?P<label>(?:(?<![A-Za-z0-9])[A-Za-z0-9]\.[ \t]?C\.'
            r'|\bT\.?\s*C\.?\s*(?:\(\^\)\s*)?K[^\W\d_]{1,8}(?:\s*\(\^\)\s*)?\s*No(?:su|\.lu)?'
            r'|\b(?:TCKN|YKN|K[İIÍ]ML[İIÍ]K\s*(?:NO(?:SU)?|NUMARASI))'
            r'|\bT\.?\s*(?:\(\^\)\s*)?C\.?(?:\s*(?:KN|Kimlik(?:\s*No(?:su|\.lu|marası)?)?))?)'
            r'[\s\*\_\.\-:;,]*)'
            r'(?P<num>[0-9lIOoJ|](?:[ \t\.\^]*[0-9lIOoJ|]){10})(?![0-9A-Za-z])'
        )

        def repl_labeled_ocr(m: re.Match) -> str:
            nonlocal count
            raw_num = m.group('num')
            if re.match(r'\d{1,2}[./]\d{1,2}[./]\d{4}', raw_num) or cls._is_date_or_esas_number(raw_num):
                return m.group(0)
            norm = re.sub(r'\D', '', cls._normalize_ocr_digits(raw_num))
            if len(norm) != 11 or norm[0] == '0':
                return m.group(0)
            count += 1
            return f"{m.group('label')}{cls._mask('tckn', raw_num, registry)}"

        text = p_labeled_ocr.sub(repl_labeled_ocr, text)

        # 1A-2. Sayı önce, etiket sonra gelen durumlar (9-13 hane; örn: "12345678901 T.C'nolu")
        # Etiketten sonra harf gelmemeli: "TCK 141", "TCMB kuru", "TCDD" etiket sayılmaz.
        p_num_first = re.compile(
            r'(?i)(?P<num>(?<!\d)[1-9][0-9lIOoJ|/ ]{8,12}[0-9lIOo]\b)(?P<mid>[ \t]*(?:[,\'\-][ \t]*)?)(?P<label>(?:T\.?\s*C\.?(?:\'?n[uo]l[uo]|\'?de|\'?ye|\.?nolu|\s*ndu)?|TCKN)(?![^\W\d_])|te\s+nolu\b)',
        )
        p_bare_tc = re.compile(r'(?i)T\.?\s*C\.?')

        def repl_num_first(m: re.Match) -> str:
            nonlocal count
            raw_num = m.group('num')
            # Tarih (12/03/2015 T.C. ...) ve yıl/esas (2021/123456 T.C. ...) korunur
            if cls._is_date_or_esas_number(raw_num):
                return m.group(0)
            # Ek almamış çıplak "T.C." (mahkeme başlığı olabilir) için 10-12 hane şartı
            if p_bare_tc.fullmatch(m.group('label')):
                norm_digits = re.sub(r'\D', '', cls._normalize_ocr_digits(raw_num))
                if not 10 <= len(norm_digits) <= 12:
                    return m.group(0)
            if sum(c.isdigit() for c in raw_num) >= 7:
                count += 1
                return f"{cls._mask('tckn', raw_num, registry)}{m.group('mid')}{m.group('label')}"
            return m.group(0)

        text = p_num_first.sub(repl_num_first, text)

        # 1B-1. Banka dekontu / kurum sorgusu OCR'larında bölünmüş 11 haneli TCKN'ler
        p_ctx_split = re.compile(
            r'(?i)(?P<prefix>(?:TCKN|YKN|Kimlik)[^\r\n]{0,25}?)(?<![\d\./])(?P<num>[1-9]\d{6,8}[ \t|/][0-9lIOoJ]{2,4})(?![\d\./])'
        )

        def repl_ctx_split(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('prefix')}{cls._mask('tckn', m.group('num'), registry)}"

        text = p_ctx_split.sub(repl_ctx_split, text)

        # Bağımsız veya "sc" sonekli OCR bölünmüş TCKN
        p_ocr_split = re.compile(
            r'(?<![A-Za-z0-9\./])(?P<num>[1-9]\d{5,7}[ \t|/][0-9lIOoJ]{3,4})(?![A-Za-z0-9\./])'
        )

        def repl_ocr_split(m: re.Match) -> str:
            nonlocal count
            raw = m.group('num')
            norm_digits = re.sub(r'[ \t|/]', '', cls._normalize_ocr_digits(raw))
            # 1) Boşluk/ayırıcı kaldırıldığında tam 11 hane olanlar
            # 2) '|' veya '/' karakteri 1 rakamının OCR bozulması olup 6+4=10 rakam olanlar
            if len(norm_digits) == 11 or ('|' in raw and len(norm_digits) == 10):
                count += 1
                return cls._mask("tckn", raw, registry)
            return raw

        text = p_ocr_split.sub(repl_ocr_split, text)

        # 1B-2. 11 haneli bağımsız sayılar (Mod-10/11 doğrulaması VEYA bilinen TCKN ile Hamming mesafesi <= 2)
        p_standalone = cls._TCKN_STANDALONE_RE

        def repl_standalone(m: re.Match) -> str:
            nonlocal count
            val = m.group(0)
            if cls.is_valid_tckn(val):
                count += 1
                local_known.add(val)
                return cls._mask("tckn", val, registry)
            for kt in local_known:
                if len(kt) == 11 and sum(a != b for a, b in zip(val, kt)) <= 2:
                    count += 1
                    return cls._mask("tckn", val, registry)
                if len(kt) == 11 and kt[:5] in val[:6]:
                    count += 1
                    return cls._mask("tckn", val, registry)
            return val

        text = p_standalone.sub(repl_standalone, text)

        # 1B-3. Bilinen TCKN'ler için İlk 5 Hane (prefix5) veya Son 4 Hane (suffix4) Bulanık Eşleştirmesi (Known TCKN Fuzzy Match)
        if local_known:
            prefixes = sorted({kt[:5] for kt in local_known if len(kt) == 11})
            suffixes = sorted({kt[-4:] for kt in local_known if len(kt) == 11})
            pref_union = "|".join(re.escape(p) for p in prefixes)
            suff_union = "|".join(re.escape(s) for s in suffixes)

            p_fuzzy = re.compile(
                rf'(?<![A-Za-z0-9\./])(?P<num>'
                rf'(?:[1-9]?(?:{pref_union})[0-9lIOoJ|/ ]{{4,8}}[0-9lIOoJ])|'
                rf'(?:[1-9][0-9lIOoJ|/ ]{{5,8}}(?:{suff_union}))'
                rf')(?![A-Za-z0-9\./])'
            )

            def repl_fuzzy(m: re.Match) -> str:
                nonlocal count
                raw = m.group('num')
                if cls._has_mask(raw):
                    return raw
                # Yıl/esas ("2023/12345") ve tarih biçimleri bilinen TCKN soneki/öneki ile tesadüfen çakışabilir
                if cls._is_date_or_esas_number(raw):
                    return raw
                # Tarih (08.10.2021) veya para tutarlarını asla bozmamak için kontrol
                norm = cls._normalize_ocr_digits(raw)
                digit_cnt = sum(c.isdigit() for c in norm)
                if 10 <= len(raw) <= 14 and digit_cnt >= 9:
                    count += 1
                    return cls._mask("tckn", raw, registry)
                return raw

            text = p_fuzzy.sub(repl_fuzzy, text)

        # 1C. Tebligatlardaki Yıldızlı/Tireli Kısmi TCKN'ler (TC:226*****874, TC:309*****704, TC:382---"566)
        p_partial = re.compile(
            r'(?i)(?P<label>\bT\.?C\.?[:\s]*)?\b[1-9]\d{2}(?P<sep>(?=[\*\-\"\s]*[\*\-\"])[\*\-\"\s]{3,7})\d{3}\b'
        )

        def repl_partial(m: re.Match) -> str:
            nonlocal count
            # "TC:" etiketi yoksa ayırıcıda en az 3 maske karakteri (*, -, ") aranır;
            # böylece "150 - 200 TL", "madde 141 - 142", "sayfa 120 -- 135" korunur.
            if not m.group('label'):
                mask_chars = sum(c in '*-"' for c in m.group('sep'))
                if mask_chars < 3:
                    return m.group(0)
            count += 1
            raw_part = m.group(0)[len(m.group('label') or ''):]
            return cls._mask("tckn", raw_part, registry)

        text = p_partial.sub(repl_partial, text)
        return text, count

    @classmethod
    def redact_phone(cls, text: str, registry: Optional[MaskRegistry] = None) -> Tuple[str, int]:
        r"""
        Katman 5: Türkiye cep telefonu numaralarının tüm varyasyonlarını maskeler:
        - Başında 0 olan / olmayan (0536..., 536...)
        - Uluslararası alan kodlu (+90, 90)
        - Boşluklu, tireli, noktalı, parantezli varyasyonlar
          (0536 260 33 99, 0 (536) 260-33-99, +90 536 260 33 99, (0536) 260 33 99, (536) 260 3399 vb.)
        Tarihler (05.06.2024), kanun maddeleri (5237), para tutarları (500.000 TL) ve dosya esas numaraları korunur.
        """
        count = 0
        pattern = re.compile(
            r'(?<!\d)(?:(?:\+?90[\s.-]?)?(?:\(0\)|0)[\s.-]?|\+?90[\s.-]?)?(?:\(?5\d{2}\)?|\(05\d{2}\))[\s.-]?\d{3}[\s.-]?(?:\d{2}[\s.-]?\d{2}|\d{4})(?!\d)'
        )

        phone_ctx = re.compile(r'(?i)(?:tel|gsm|cep|telefon|irtibat|ileti[şs]im|mobil|hat)\w*[^\r\n\d]{0,25}$')
        doc_ctx = re.compile(
            r'(?i)(?:barkod|evrak|belge|dosya|say[ıi]|ref(?:erans)?|takip|işlem|kay[ıi]t|sorgu|dekont|fatura|'
            r'po[lI]i[cç]e|seri|sipariş|mersis|vergi|vkn|bpm|uets|kep)\w*[^\r\n\d]{0,20}$'
        )

        def repl(m: re.Match) -> str:
            nonlocal count
            raw = m.group(0)
            # Ayırıcısız, ön eksiz çıplak 10 hane (5xxxxxxxxx): yalnızca operatör kodu (50x-56x, 59x)
            # uygunsa ve önünde evrak/barkod/dosya no etiketi yoksa telefon sayılır.
            if re.fullmatch(r'5\d{9}', raw):
                before = m.string[max(0, m.start() - 40):m.start()]
                # "...tespit edilen\n5xxxxxxxxx numaralı telefondan": numaranın hemen ardından
                # 'telefon/GSM/hat' geliyorsa önceki satırdaki 'kayıt/evrak' sözcüğü etiket sayılmaz.
                after_phone = re.match(r'(?i)\s*(?:numaral[ıi]|nolu|no\'lu)?\s*(?:cep\s*)?(?:telefon|gsm|hat)', m.string[m.end():m.end() + 40])
                if after_phone:
                    count += 1
                    return cls._mask("telefon", raw, registry)
                if not phone_ctx.search(before):
                    if raw[1] not in "0123456" and raw[1] != "9":
                        return raw
                    if doc_ctx.search(before):
                        return raw
            count += 1
            return cls._mask("telefon", raw, registry)

        redacted = pattern.sub(repl, text)
        return redacted, count

    @classmethod
    def redact_sicil(cls, text: str, registry: Optional[MaskRegistry] = None) -> Tuple[str, int]:
        """
        Katman 6: Hâkim, Savcı, Kâtip, Mübaşir ve Müdür sicil numaralarını maskeler.
        Unvan bitişikleri, tutanak başlıkları, cümle içi 'Unvan + Ad Soyad + Sicil' dizilimleri,
        imza tabloları, iddianame savcı bloğu ve Adli Sicil düzenleyen kişi satırlarındaki
        5–6 haneli sicil kodlarını hedefler.
        Para tutarları (örn. 200.000 TL), tarihler, kanun maddeleri ve dosya esas numaraları korunur.
        """
        count = 0
        titles = cls.TITLES_REGEX
        not_sicil = cls.NOT_SICIL_SUFFIX

        # 1a. Unvan doğrudan önünde olan sicil (örn. "Başkan 211094", "Kalip/123456", "Mübaşir 234567", "Makin 112233")
        # Para tutarı / "sayılı" / Esas / Karar sonekli sayılar sicil sayılmaz ("Hakim 150000 TL", "Başkan 20245 sayılı")
        p1 = re.compile(rf'(?i)(?P<title>\b{titles})(?P<mid>[\s\*\-_|:\t\/]+)(?P<sicil>(?<![\d\.])\d{{5,6}}(?![\d\./])){not_sicil}')

        def repl1(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('title')}{m.group('mid')}{cls._mask('sicil', m.group('sicil'), registry)}"

        text = p1.sub(repl1, text)

        # 1b. Unvan doğrudan arkasında olan sicil (örn. "36101 Cumhuriyet Savcısı", "AHMET KABADAYI 123456 Soruşturma Savcısı")
        p2 = re.compile(rf'(?i)(?P<sicil>(?<![\d\./])\d{{5,6}}(?![\d\./]))(?P<mid>[\s\*\-_|:\t\/]+)(?P<title>{titles}\b)')

        def repl2(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{cls._mask('sicil', m.group('sicil'), registry)}{m.group('mid')}{m.group('title')}"

        text = p2.sub(repl2, text)

        # 1c. Cümle içi "Unvan + 1-4 kelimelik Ad Soyad + 5-6 haneli Sicil" (örn. "Hakim Ayşe Kaya 112233, Katıp Mehmet Demir 223344, Mübaşir Ali Çelik 334455")
        p_inline_named = re.compile(
            rf'(?i)(?P<prefix>\b{titles}\s+(?:[A-ZÇĞİÖŞÜa-zçğıöşü\.]+\s+){{1,4}})(?P<sicil>(?<![\d\./])\d{{5,6}}(?![\d\./])){not_sicil}'
        )

        def repl_inline_named(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('prefix')}{cls._mask('sicil', m.group('sicil'), registry)}"

        text = p_inline_named.sub(repl_inline_named, text)

        # 2. Tutanak/Karar başlık satırları: "**BAŞKAN :** Ayşe ÖRNEK  123456"
        p3 = re.compile(
            rf'(?im)^(?P<prefix>[\s\*]*{titles}[\s\*]*[:\t][^\r\n\d]*[a-zA-ZçğıöşüÇĞİÖŞÜ\.\s\*]+?)(?<!\d)(?P<sicil>\d{{5,6}})(?!\d)(?P<suffix>[\s\*]*)$'
        )

        def repl3(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('prefix')}{cls._mask('sicil', m.group('sicil'), registry)}{m.group('suffix')}"

        text = p3.sub(repl3, text)

        # 3. İddianame sonu savcı imza bloğu (üst satırda sicil, alt satırda Cumhuriyet Savcısı)
        p4 = re.compile(
            rf'(?im)^(?P<lead>[\s\*]*)(?<!\d)(?P<sicil>\d{{5,6}})(?!\d)(?P<trail>[\s\*]*)$(?=\r?\n[\s\*]*{titles})'
        )

        def repl4(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('lead')}{cls._mask('sicil', m.group('sicil'), registry)}{m.group('trail')}"

        text = p4.sub(repl4, text)

        # 4. Adli Sicil belgesi: "## DÜZENLEYEN KİŞİ/KURUM \n\n## 234878"
        p5 = re.compile(r'(?i)(?P<lead>DÜZENLEYEN\s+KİŞİ\s*/\s*KURUM[\s\S]{0,60}?)(?<!\d)(?P<sicil>\d{5,6})(?!\d)')

        def repl5(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('lead')}{cls._mask('sicil', m.group('sicil'), registry)}"

        text = p5.sub(repl5, text)

        # 5. Açık etiketli sicil ("Sicil No: 123456", "Sicili : 123456") ve OCR bozulmalı imza satırı ("+0644-112233")
        p6 = re.compile(
            r'(?im)(?P<lead>\bSicil(?:i| No| Numaras[ıi])?[\s\*]*[:\t\-][\s\*]*|^[ \t]*\+\d{3,4}[\-\s]+)(?<!\d)(?P<sicil>\d{4,7})(?!\d)'
        )

        def repl6(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('lead')}{cls._mask('sicil', m.group('sicil'), registry)}"

        text = p6.sub(repl6, text)

        # 5b. Antetteki ticaret sicil no ("Tic. Sicil No: 123456", OCR "Tc. Sici No. 233076 6619 345")
        p6b = re.compile(
            r'(?i)(?P<lead>\bT[iı]?c\.?\s*Sic[iı]l?\s*(?:No|Numaras[ıi])\.?[ \t]*:?[ \t]*)(?P<sicil>\d[\d ]{3,18}\d)(?![\d])'
        )
        text = p6b.sub(repl6, text)

        # 6. Eşittir / boşlukla yazılmış sicil ("(Sicil=234408)", "Sicili 476175")
        p7 = re.compile(
            r'(?i)(?P<lead>\bSicil(?:i|\s*No)?[ \t\*]*=?[ \t\*]*)(?<![\d])(?P<sicil>\d{4,7})(?![\d\./])'
            r'(?!\s*(?:TL|yıl|sayılı|tarih|Esas|Karar)\b)'
        )
        text = p7.sub(repl6, text)

        # 7. Baro sicil no ("Baro Sicil No : Burdur Barosu , 490" / "İzmir Barosu- 20763")
        p8 = re.compile(
            r'(?i)(?P<lead>Baro\s*Sicil\s*(?:No|Numaras[ıi])?[^\r\n\d]{0,60}?Barosu[ \t]*[,\-–:]?[ \t]*)(?P<sicil>\d{2,6})(?!\d)'
        )
        text = p8.sub(repl6, text)

        # 8. Avukat adından sonra parantez içindeki baro sicil no ("Av. Ayşe YILMAZ (12345)")
        p9 = re.compile(
            r'(?P<lead>\bAv\.\s+(?:[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü\.\-]*\s+){1,4}\()(?P<sicil>\d{3,6})(?=\))'
        )
        text = p9.sub(repl6, text)

        # 8b. Ticaret sicil memurluğu no (OCR: "Ticaret Sidi Memurtugu, 366587/3 616")
        p8b = re.compile(
            r'(?i)(?P<lead>Ticaret\s+Si[cd][iı]l?\s+Memur\w*[ \t,:]*)(?P<sicil>\d[\d/ ]{3,16}\d)'
        )
        text = p8b.sub(repl6, text)

        # 8c. OCR formlarında tek başına satırdaki sicil: üstteki 1-3 satırda "SİCİL" etiketi veya
        # "Doktor/Hekim + ad" bulunan ya da altındaki satırda "SİCİL" geçen "123456-AD SOYAD"
        p8c = re.compile(
            r'(?im)(?P<lead>(?:^[^\r\n]*S[İIi]C[İIi]L[^\r\n]*\r?\n(?:[^\r\n]{0,40}\r?\n){0,2}'
            r'|^[ \t]*(?:Doktor|Dr\.|Hekim|Tabip)[ \t]*\r?\n[^\r\n\d]{3,40}\r?\n)[ \t]*)'
            r'(?P<sicil>\d{5,7})(?=[ \t]*$)'
        )
        text = p8c.sub(repl6, text)
        p8d = re.compile(
            r'(?m)^(?P<lead>[ \t]*)(?P<sicil>\d{5,7})(?=[ \t]*-[ \t]*[A-ZÇĞİÖŞÜ]{2,}(?:[ \t]+[A-ZÇĞİÖŞÜ]{2,}){1,3}[ \t]*\r?\n'
            r'[^\r\n]*S[İI]C[İI]L)'
        )
        text = p8d.sub(repl6, text)

        # 9. Klasörde unvan/etiketle tespit edilmiş sicil no başka yerde geçerse: 6-7 hane her yerde
        # (bağımsız sayı olarak), 5 hane yalnızca tek başına bir satırda
        if registry is not None:
            known = registry.known_values("sicil", min_len=5)
            k6 = sorted((k for k in known if len(k) >= 6), key=len, reverse=True)
            k5 = sorted(k for k in known if len(k) == 5)
            if k6:
                p_k6 = re.compile(
                    r'(?P<lead>)(?<![\d\.,/])(?P<sicil>' + "|".join(map(re.escape, k6)) + r')(?![\d\.,/])'
                    + not_sicil
                )
                text = p_k6.sub(repl6, text)
            if k5:
                p_k5 = re.compile(r'(?m)^(?P<lead>[ \t#\*]*)(?P<sicil>' + "|".join(map(re.escape, k5)) + r')(?=[ \t\*]*$)')
                text = p_k5.sub(repl6, text)

        return text, count

    @staticmethod
    def _looks_like_url_or_email(val: str) -> bool:
        """Değer bir web adresi, e-posta veya KEP adresi mi? (kişisel ikamet adresi değildir)"""
        v = val.strip().lower()
        return bool(re.search(r'https?://|www\.|@|\.(?:com|gov|org|edu|bel|av|k12)\.tr\b|\bhs0\d\.', v))

    # Adres bağlamı: kurum / olay yeri / kişi ayrımı
    _ADDR_PERSON_RE = re.compile(
        r'(?i)(?:\b(?:davac[ıi]|daval[ıi]|vekil\s+eden|müvekkil|k[ıi]s[ıi]tl[ıi]|vasi(?:si)?|tan[ıi]k|'
        r'şüpheli|san[ıi]k|müşteki|mağdur|muhatap|al[ıi]c[ıi]|ikamet|oturur|yakalama|müşteri|hükümlü|'
        r'borçlu|alacakl[ıi]|avukat|kişi|isimli|yükümlü\w*|adresini|şah[ıi]s(?:[ıi]n?|a)?)(?![a-zçğıöşü])|'
        r'\bAv\.|belirtilen\s+\*\*)'
    )
    _ADDR_INST_RE = re.compile(
        r'(?i)bankas[ıi]|\bbanka\b|bankac[ıi]l[ıi]k|\bA\.\s?Ş\b|\bT\.A\.Ş|genel\s+müdürlü|'
        r'operasyon\s+merkezi|adalet\s+saray|adliye|mahkemesi|noterli|barosu|icra\s+dairesi|'
        r'başkanl[ıi]ğ|\bPTT\b|belediye|ticaret\s+sicil|mersis|valili|kaymakaml|müdürlüğü|şubesi|'
        r'ltd\.?\s*şti|holding|sigorta|hastane|üniversite|polis\s+merkezi|karakol|jandarma|'
        r'menkul\s+k[ıi]ymet|katılım\s+bankas|iş\s+merkezi|towers|plaza|\bcenter\b'
    )
    _ADDR_OLAY_RE = re.compile(
        r'(?i)suçun\s+yeri|olay\s+yeri|kaza\s+yeri|olay(?:ın)?\s+meydana|meydana\s+gel|'
        r'\bönünde\b|kavşağ|sıralarında|trafik\s+kazas'
    )
    # Nüfus kayıt şablonu / mahkeme kısaltması / esas no: kişi adresi değildir
    _ADDR_NOT_ADDRESS_RE = re.compile(
        r'(?i)nüfus|\bcilt\b|aile\s*s[ıi]ra|\bnk\.?\s*lu\b|\bBSN\b|doğumlu|oğlu/k[ıi]z[ıi]|'
        r'Mah\./Köy|kay[ıi]tl[ıi]\b|'
        r'(?:Hukuk|Ceza|İcra|Asliye|Sulh|Aile|Tüketici|Ticaret|İdare|Vergi)\s+Mah\.?(?=\s|$)|'
        r'\b(?:19|20)\d{2}\s*/\s*\d+\s*(?:E\b|E\.|Esas|K\.|Karar)'
    )

    _ADDR_LEGAL_RE = re.compile(
        r"(?i)\b(?:HMK|TMK|TBK|İİK|IIK|TCK|CMK)\b|\bmadde(?:si|leri|ler)?\b|\bhüküm(?:leri|ler)?\b|"
        r"\bsaklı\b|\bgereğince\b"
    )

    _TABLE_DATE_RE = re.compile(
        r'\d{1,2}[./]\d{1,2}[./]\d{4}(?:[ \t]*(?:\(\^\)[ \t]*)?\d{1,2}[:.]\d{2})?'
    )

    @classmethod
    def _split_after_last_date(cls, val: str) -> Optional[Tuple[str, str]]:
        """
        OCR tablo satırı ("AD SOYAD : 12345678 : 12.03.2025 10:30 : 1234 SK. XYZ MAH.5/6"): son tarih/saatten
        sonraki adres kısmını ayırır. (korunacak_baş, maskelenecek_adres); tarih yoksa None,
        tarihten sonra adres kalmadıysa ("", "") döner.
        """
        dates = list(cls._TABLE_DATE_RE.finditer(val))
        if not dates:
            return None
        rest = val[dates[-1].end():]
        rest_clean = rest.lstrip(' \t:')
        if len(rest_clean) < 5:
            return "", ""
        return val[:dates[-1].end()] + rest[:len(rest) - len(rest_clean)], rest_clean

    @classmethod
    def _address_owner(cls, text: str, start: int, end: int) -> str:
        """
        Eşleşen adresin bağlamını sınıflandırır: 'kisi' (maskelenir), 'kurum' veya 'olay'
        (korunur). Şüphede 'kisi' döner (sızıntı, fazla maskelemeden daha kötüdür).
        """
        ls = text.rfind('\n', 0, start) + 1
        le = text.find('\n', end)
        if le == -1:
            le = len(text)
        line = text[ls:le]
        prev: List[str] = []
        pos = ls - 1
        while pos > 0 and len(prev) < 2:
            ps = text.rfind('\n', 0, pos) + 1
            pl = text[ps:pos].strip()
            if pl:
                prev.append(pl)
            pos = ps - 1
        if cls._ADDR_OLAY_RE.search(line):
            return "olay"
        if cls._ADDR_PERSON_RE.search(line):
            return "kisi"
        if cls._ADDR_INST_RE.search(line):
            return "kurum"
        if any(cls._ADDR_PERSON_RE.search(x) for x in prev):
            return "kisi"
        if prev and cls._ADDR_OLAY_RE.search(prev[0]):
            return "olay"
        if prev and cls._ADDR_INST_RE.search(prev[0]):
            return "kurum"
        return "kisi"

    @classmethod
    def _skip_address(cls, text: str, start: int, end: int, addr: str) -> bool:
        """Adres maskelenmemeli mi? (kurum/olay yeri, nüfus şablonu, URL, mahkeme kısaltması)"""
        if cls._looks_like_url_or_email(addr):
            return True
        if cls._ADDR_NOT_ADDRESS_RE.search(addr):
            return True
        # Kanun/madde atıfı içeren hukuki ifade adres değildir ("Tebligat Adresi: HMK'nın 100. maddeleri ...")
        if cls._ADDR_LEGAL_RE.search(addr):
            return True
        # "Asliye Hukuk Mah." gibi kısaltmada "Mah." öncesi kelime eşleşmeye girmemiş olabilir
        before = text[max(0, start - 30):start]
        if re.search(r'(?i)(?:Hukuk|Ceza|İcra|Asliye|Sulh|Aile|Tüketici|Ticaret)\s*$', before) and \
                re.match(r'(?i)\s*Mah\b', addr):
            return True
        return cls._address_owner(text, start, end) != "kisi"

    @classmethod
    def redact_address(cls, text: str, registry: Optional[MaskRegistry] = None) -> Tuple[str, int]:
        """
        Katman 7: Kişilere ait açık adres bilgilerini maskeler.
        UYAP standart şablonundaki (Mah./Mh., Cad./Sk./5k., No:/Ne:/K:/D:/Blok/Toki/Apt., İç Kapı No:, İlçe/İl)
        açık ikametgah, işyeri ve tebligat adreslerini ve iki satıra bölünmüş adres devamlarını hedefler.
        Korunanlar: kurum adresleri (banka, adliye, noter, baro, PTT, şirket antedi vb.), olay yeri,
        nüfus kayıt yerleri (cilt/aile sıra no), doğum yerleri, mahkeme adı kısaltmaları ("Hukuk Mah.")
        ve web/KEP/e-posta adresleri. Bağlam belirsizse adres kişi adresi sayılıp maskelenir.
        Bölünmüş adresin devam satırı yeni etiket almaz: silinir ya da aynı etiket tekrarlanır.
        """
        count = 0
        mask_adres_re = cls.MASK_ADRES_RE

        # 1. Açık etiketli adres satırları ("**İkametgah Adresi** **:** ...", "İşyeri Adresi:", "Adres:")
        p1 = re.compile(
            r'(?i)(?P<pre>\b(?:Doğrulama|Dogrulama|Takip|İnternet|Internet|Web|KEP|E-?\s*Posta|Mail|yeni)\s+)?'
            r'(?P<label>(?:(?:İkam[ae]t(?:g[aâ]h)?|İş\s*yeri|Tebligat)\s*)?Adres(?:i)?[ \t\*]*[:\t]+[ \t\*]*)'
            r'(?P<addr>[^\r\n]+?)'
            r'(?=(?:\s*(?:'
            r'(?:Anne|Baba)\s*Ad[ıi]|'
            r'Doğum\s*(?:Yeri|Tarihi)|'
            r'Nüfus[a-z]*|Cilt\s*No|Aile\s*Sıra|'
            r'GSM\b|Cep\b|Tel(?:efon)?\b|Faks\b|'
            r'E-?\s*posta|Email\b|KEP\b|'
            r'Vekil(?:i)?\b|Müdafi(?:i)?\b|Baro|Meslek|'
            r'Tel\b|ARANMIYOR|TC\s*Kimlik|T\.C\.|SUÇUN\s+TARİHİ|$|\r?\n)))'
        )

        def repl1(m: re.Match) -> str:
            nonlocal count
            addr_val = m.group('addr').strip()
            # "E-Tebligat Adresidir" gibi cümle sonu ibarelerini yanlışlıkla etiket sanma
            if not addr_val or len(addr_val) < 5 or re.search(mask_adres_re, addr_val):
                return m.group(0)
            # Belge doğrulama / internet / KEP / e-posta adresleri kişisel adres değildir
            if m.group('pre') and not re.search(r'(?i)yeni', m.group('pre')):
                return m.group(0)
            if cls._skip_address(m.string, m.start('addr'), m.end('addr'), addr_val):
                return m.group(0)
            # Tablo satırı ("Adres : AD SOYAD : 12345678 : 12.03.2025 10:30 : 1234 SK. XYZ MAH.5/6"):
            # tarih/saat ve önceki sütunlar korunur, yalnızca son tarihten sonraki kısım maskelenir.
            head = ""
            split = cls._split_after_last_date(addr_val)
            if split is not None:
                if not split[1]:
                    return m.group(0)
                head, addr_val = split
            count += 1
            return f"{m.group('pre') or ''}{m.group('label')}{head}{cls._mask('adres', addr_val, registry)}"

        text = p1.sub(repl1, text)

        # 1b. Etiket ile değer ayrı satırdaysa: yalnızca sonraki satır gerçekten adres gibiyse maskele
        # ("tespit edilen yeni adresi:" altındaki tebliğ açıklaması gibi metinler korunur)
        p1b = re.compile(
            r'(?im)(?P<label>^[^\r\n]{0,40}?\b(?:(?:İkam[ae]t(?:g[aâ]h)?|İş\s*yeri|Tebligat|Açık|Yakalama)\s*)?Adres(?:i)?[ \t\*]*:?[ \t\*]*\r?\n(?:[ \t]*\r?\n)?)'
            r'(?P<addr>[ \t#\*]*[^\r\n]*?(?:\b(?:Mah\.|Mh\.|Mahallesi|Cad\.|Cd\.|Caddesi|Sk\.|Sok\.|Sokak|Bulvar[ıi])(?![A-Za-zçğıöşüÇĞİÖŞÜ])|\bNo\s*[:\.]\s*\d)[^\r\n]*)$'
        )

        def repl1b(m: re.Match) -> str:
            nonlocal count
            addr = m.group('addr')
            if re.search(mask_adres_re, addr) or cls._looks_like_url_or_email(addr):
                return m.group(0)
            if cls._ADDR_NOT_ADDRESS_RE.search(addr):
                return m.group(0)
            if cls._address_owner(m.string, m.start('addr'), m.end('addr')) != "kisi":
                return m.group(0)
            lead = re.match(r'[ \t#\*]*', addr).group(0)
            body = addr[len(lead):]
            head = ""
            split = cls._split_after_last_date(body)
            if split is not None:
                if not split[1]:
                    return m.group(0)
                head, body = split
            count += 1
            return f"{m.group('label')}{lead}{head}{cls._mask('adres', body, registry)}"

        text = p1b.sub(repl1b, text)

        # 2. Önceden sınırlandırılmış UYAP adres cümleleri
        p2 = re.compile(
            r'(?P<prefix>(?:doğumlu\s+ve\s+halen|ve\s+halen|doğumlu[\.,]|nüfus(?:a|unda)\s+kayıtlı(?:dır)?[\.,]?|kayıtlı\s+olup\s+halen|belirtilen|E-Tebligat\s+Adresidir\.)\s+)'
            r'(?P<addr>(?:[A-ZÇĞİÖŞÜa-zçğıöşü0-9\.\-\/]+\s+){0,5}?(?:Mah\.|Mh\.|Mahallesi\b)[^\r\n\|]+?)'
            r'(?P<suffix>\s+(?:adresinde\s+oturur|ikamet\s+eder|adresinde\s+ikamet\s+eder|adresinde\s+bulunur|adresine\b|adresinde\b)|\s*(?=$|\r?\n))'
        )

        def repl2(m: re.Match) -> str:
            nonlocal count
            addr = m.group('addr')
            if re.search(mask_adres_re, addr) or cls._looks_like_url_or_email(addr):
                return m.group(0)
            # Adresin kendisi nüfus şablonuysa koru (önek "nüfusa kayıtlı" olabilir; adres kişiseldir)
            if re.search(r'(?i)\bcilt\b|aile\s*s[ıi]ra|\bBSN\b', addr):
                return m.group(0)
            count += 1
            return f"{m.group('prefix')}{cls._mask('adres', addr, registry)}{m.group('suffix')}"

        text = p2.sub(repl2, text)

        # 3d. MERNİS tablo satırı: "Mahalle :XXX MAH. Cd./Sk./Bul./Mev :YYY CAD. Kapı No :12/3 İlçe :ZZZ İl :ANTALYA"
        p3d = re.compile(
            r'(?i)(?P<label>\bMahalle[ \t]*:[ \t]*)'
            r'(?P<addr>[^\r\n:]{2,60}?[ \t]+Cd\.?[ \t]*/[ \t]*Sk\.?[ \t]*/[ \t]*Bul\.?[ \t]*/[ \t]*Mev[ \t]*:[^\r\n:]{1,100}?'
            r'[ \t]+Kap[ıi][ \t]*No[ \t]*:[ \t]*\S+(?:[ \t]+İlçe[ \t]*:[ \t]*[^\r\n:]+?)?'
            r'(?:[ \t]+İl[ \t]*:[ \t]*[A-ZÇĞİÖŞÜa-zçğıöşü]+)?)'
            r'(?=[ \t]+(?:Beyan|Tescil|Taşınma)|[ \t]*(?:\r|\n|$))'
        )

        def repl3d(m: re.Match) -> str:
            nonlocal count
            if re.search(cls.MASK_ANY_RE, m.group('addr')):
                return m.group(0)
            count += 1
            return f"{m.group('label')}{cls._mask('adres', m.group('addr'), registry)}"

        text = p3d.sub(repl3d, text)

        # 3. Genel Yapısal Açık Adres Kalıbı (K:/D:/Blok/Toki/Apt ve OCR 5k./Ne:/|¢ Kapı varyasyonları dahil)
        p3 = re.compile(
            r'(?i)(?P<lead>(?:^|(?<=[\s\|\#\:;\,\.\^\(\-\/\*"“”])))'
            r'(?P<addr>'
            r'(?:(?:^|(?<=[\r\n\|\#\:;\,\.\^\(\-\/\*"“”]))[ \t]*(?:[A-ZÇĞİÖŞÜa-zçğıöşü0-9]+[ \t]+){1,2})?'
            r'\b(?:Mahallesi|Mah\.?|Mh\.?|Cadde(?:si)?|Cad\.?|Cd\.?|Sokak|Sokağ[ıi]|Sok\.?|Sk\.?|5k\.?|Bulvar[ıi]|Bulv\.?|Blv\.?|Küme\s*Evler[i]?|Toki\s+Evleri)[\s\,\.\^\-]+'
            r'(?:\|¢|[^\r\n\|]){0,100}?'
            r'(?:\b(?:No|Ne|[İiIıl]ç\s*Kap[ıi](?:\s*No)?|Kat|K|Daire|D|Blok|Blk|Apt|Apartman[ıi]|Sitesi|Evleri)|\|¢\s*Kap[ıi](?:\s*No)?)(?:[\s\.\-\:\^\/]*[0-9A-Za-z]|\s+No\b)'
            r'(?:\|¢|[^\r\n\|]){0,100}?'
            r'(?:[A-ZÇĞİÖŞÜa-zçğıöşü\s]{2,25}[\/J]\s*[A-ZÇĞİÖŞÜa-zçğıöşü0-9\s\,\.]{2,25})?'
            r')'
            r'(?P<tail>(?=\s+(?:adresinde\s+oturur|ikamet\s+eder|adresinde|adresine|SUÇUN\s+TARİHİ|Tel\b|TC\s*Kimlik|\d{2}\.\d{2}\.\d{4}\b|\d\s+5\d{9}\b)|\s*(?:\|(?!¢)|\r|\n)|$))'
        )

        def repl3(m: re.Match) -> str:
            nonlocal count
            addr = m.group('addr')
            if re.search(cls.MASK_ANY_RE, addr):
                return m.group(0)
            if cls._skip_address(m.string, m.start('addr'), m.end('addr'), addr):
                return m.group(0)
            # "12.03.2025YENİ MAH. ..." / "12.03.2025 YENİ MAH. ...": tarihin yılı adrese dahil edilmez
            keep = ""
            if re.search(r'\d{1,2}[./]\d{1,2}[./]$', m.string[max(0, m.start('addr') - 8):m.start('addr')]):
                ym = re.match(r'(?:19|20)\d{2}(?:[ \t]+)?', addr)
                if ym:
                    keep, addr = ym.group(0), addr[ym.end():]
                    if not addr.strip():
                        return m.group(0)
            count += 1
            return f"{m.group('lead')}{keep}{cls._mask('adres', addr, registry)}"

        text = p3.sub(repl3, text)

        # 3b. Mah. + Sk./Cad. + kapı "5 / 6" biçimi ("No:" etiketsiz) ve ters sıra ("1234 SK. TESTTEPE MAH. 5/6")
        _W = r'[A-ZÇĞİÖŞÜa-zçğıöşü0-9\.]'
        _STREET = r'(?:Sk|Sok|Sokak|Sokağ[ıi]|Cad|Cd|Cadde|Caddesi|Bulv|Blv|Bulvar[ıi])'
        _MAH = r'(?:Mah|Mh|Mahallesi)'
        _GAP = r'[ \t\^]'
        p3b = re.compile(
            r'(?i)(?<![A-ZÇĞİÖŞÜa-zçğıöşü0-9])(?P<addr>'
            rf'(?:{_W}+{_GAP}+){{1,2}}{_MAH}\.?{_GAP}*(?:{_W}+{_GAP}+){{0,3}}?{_STREET}\.?{_GAP}*\d{{1,4}}(?:{_GAP}*/{_GAP}*\d{{1,3}})?'
            rf'(?:{_GAP}+[A-ZÇĞİÖŞÜa-zçğıöşü]+(?:{_GAP}*[-/]{_GAP}*[A-ZÇĞİÖŞÜa-zçğıöşü]+)?)?'
            r'|'
            rf'(?:\d{{1,5}}[,\.]?{_GAP}+)?(?:{_W}+{_GAP}+){{0,1}}{_STREET}\.?{_GAP}+(?:[A-ZÇĞİÖŞÜa-zçğıöşü]+{_GAP}+){{1,2}}{_MAH}\.?[ \t\.\^]*\d{{1,4}}(?:{_GAP}*/{_GAP}*\d{{1,3}})?'
            r')'
        )

        def repl3b(m: re.Match) -> str:
            nonlocal count
            addr = m.group('addr')
            if re.search(cls.MASK_ANY_RE, addr):
                return m.group(0)
            if cls._skip_address(m.string, m.start('addr'), m.end('addr'), addr):
                return m.group(0)
            count += 1
            return cls._mask('adres', addr, registry)

        text = p3b.sub(repl3b, text)

        # 3c. İki satıra (başlık/paragraf) bölünmüş adres: ilk satırda Mah.+Sk./Cad. (numarasız), devam satırında "No:"
        # ("## Testtepe Mahallesi Şehit Kuzey Sokak Lale\n\n## Sitesi Köşkleri No.12 Ac Merkez/ BURDUR").
        # Her iki satır da aynı etiketle maskelenir.
        p3c = re.compile(
            r'(?im)(?:^|(?<=["“”:;]))(?P<lead1>[ \t#\*]*)(?P<a1>(?=[^\r\n]*\b(?:Mahallesi|Mah\.?|Mh\.?)(?![A-Za-zçğıöşü]))'
            r'[^\r\n"“”:;\d]*?\b(?:Sokak|Sokağ[ıi]|Sok\.?|Sk\.?|Cadde(?:si)?|Cad\.?|Bulvar[ıi])(?![A-Za-zçğıöşü])[^\r\n\d]*)[ \t]*\r?\n'
            r'(?P<gap>(?:[ \t]*\r?\n){0,2})'
            r'(?P<lead2>[ \t#\*]*)(?P<a2>[^\r\n]*?\b(?:No|[NVMW][oea])[ \t]*[:.][ \t]*[0-9A-Za-z][^\r\n]*?)'
            r'(?=[ \t]+(?:adres\w*|ikamet|oturur|Tel\b|GSM\b)|[ \t]*$)'
        )

        def repl3c(m: re.Match) -> str:
            nonlocal count
            joined_addr = m.group('a1') + " " + m.group('a2')
            if re.search(cls.MASK_ANY_RE, joined_addr):
                return m.group(0)
            if cls._skip_address(m.string, m.start('a1'), m.end('a2'), joined_addr):
                return m.group(0)
            count += 1
            lab = cls._mask('adres', joined_addr, registry)
            return f"{m.group('lead1')}{lab}\n{m.group('gap')}{m.group('lead2')}{lab}"

        text = p3c.sub(repl3c, text)

        # 4. Kapalı Tebligat ve İki Satıra Bölünmüş Dilekçe Adresleri devam satırı temizliği
        # (Örn: "[ADRES_1]\nK:2 D:40 Burdur Merkez/ BURDUR" -> devam satırı silinir, aynı etiket kalır)
        p4 = re.compile(
            r'(?i)(?P<masked>' + mask_adres_re + r')'
            r'(?P<ws>\s*\r?\n(?:\s*\r?\n)?[\s\#\*]*(?:\.\.\.\s*)?)'
            r'(?P<city>(?:(?:K|Kat|No|Blok|D|Daire)[\s\:\.\-]*[0-9A-Za-z][0-9A-Za-z\s\:\.\-]*\s+)?[A-ZÇĞİÖŞÜa-zçğıöşü\s]{2,30}/\s*[A-ZÇĞİÖŞÜa-zçğıöşü]{2,20})'
            r'(?=\s*\r?\n|$)'
        )
        text = p4.sub(r'\g<masked>', text)

        # 4b. Araya 1 satır girmiş veya tek başına kalmış "D:40 Burdur Merkez/ BURDUR" / "Daire: 3 Burdur Merkez/ BURDUR" devam satırları
        p4_orphan = re.compile(
            r'(?im)^(?P<lead>[ \t]*(?:\.\.\.[ \t]*)?)(?P<cont>(?:(?:K|Kat)[ \t\:\.]*\d+[ \t]+)?(?:D|Daire)[ \t\:\.]*\d[0-9 \t]*[ \t]+[A-ZÇĞİÖŞÜa-zçğıöşü ]{2,30}/[ \t]*[A-ZÇĞİÖŞÜa-zçğıöşü]{2,20})[ \t]*$'
        )

        def repl4_orphan(m: re.Match) -> str:
            nonlocal count
            if cls._address_owner(m.string, m.start('cont'), m.end('cont')) != "kisi":
                return m.group(0)
            # Yakın üst satırlarda maskelenmiş bir adres varsa onun devamıdır: aynı etiket
            above = m.string[max(0, m.start() - 300):m.start()]
            prev_labels = re.findall(mask_adres_re, above)
            count += 1
            if prev_labels:
                return f"{m.group('lead')}{prev_labels[-1]}"
            return f"{m.group('lead')}{cls._mask('adres', m.group('cont'), registry)}"

        text = p4_orphan.sub(repl4_orphan, text)

        # 4b2. Tek başına kalmış "No:9 İç Kapı No:3 Bucak/BURDUR" devam satırı (üstte maske olmasa da adrestir)
        p4_orphan2 = re.compile(
            r'(?im)^(?P<lead>[ \t]*)(?P<cont>(?:No|Kap[ıi]\s*No)[ \t:.]*\d+[ \t]+[İiIıl]ç\s*Kap[ıi](?:\s*No)?[ \t:.]*\d+'
            r'[ \t]+[A-ZÇĞİÖŞÜa-zçğıöşü ]{2,30}/[ \t]*[A-ZÇĞİÖŞÜa-zçğıöşü]{2,20})[ \t]*$'
        )
        text = p4_orphan2.sub(repl4_orphan, text)

        # 4c. "[ADRES_1]\nİç Kapı No: 2 Örnekçay / Antalya Tel: ..." — devam satırı aynı etiketle maskelenir
        p4_cont = re.compile(
            r'(?im)(?P<masked>(?P<mlabel>' + mask_adres_re + r')[ \t]*\r?\n)(?P<lead>[ \t]*)'
            r'(?P<cont>(?:[İiIıl]ç\s*Kap[ıi](?:\s*No)?|Kap[ıi]\s*No|Kat|K|Daire|D|No|Blok)[ \t\.:]*[0-9][^\r\n]*?)'
            r'(?=[ \t,;]+(?:Tel|GSM|Cep|Telefon)\b|[ \t]*$)'
        )

        def repl4_cont(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('masked')}{m.group('lead')}{m.group('mlabel')}"

        text = p4_cont.sub(repl4_cont, text)

        # 4c2. OCR'ın "No"yu "Vo/Ne" okuduğu devam satırı: "[ADRES_1]\nVo:19 AC Silivri /ISTANBUL" olarak ... — aynı etiket
        p4_cont2 = re.compile(
            r'(?im)(?P<masked>(?P<mlabel>' + mask_adres_re + r')[ \t]*\r?\n)(?P<lead>[ \t]*)'
            r'(?P<cont>[NVMW][oea][ \t]*[:.][ \t]*[0-9A-Za-z]{1,4}(?:[ \t]+[A-Za-zÇĞİÖŞÜçğıöşü]{1,5})?'
            r'[ \t]+[A-ZÇĞİÖŞÜa-zçğıöşü ]{2,30}[ \t]*/[ \t]*[A-ZÇĞİÖŞÜa-zçğıöşü]{2,20})(?=["”\)\.,;]|[ \t]|$)'
        )
        text = p4_cont2.sub(repl4_cont, text)

        # 4d. OCR tablosundan dağılmış adres: "[ADRES_1] / iç Kapı No / DENEME SK. / 28" — aynı etiket
        p4_ocr = re.compile(
            r'(?m)(?P<head>(?P<mlabel>' + mask_adres_re + r')[ \t]*\r?\n(?:[ \t]*[İiIıl]ç\s*Kap[ıi](?:\s*No)?[ \t:]*\r?\n)?)'
            r'[ \t]*[A-ZÇĞİÖŞÜ0-9][A-ZÇĞİÖŞÜa-zçğıöşü0-9 \.]{0,40}?\b(?:SK|SOK|CAD|CD|MAH|MH|Sk|Sok|Cad|Cd|Mah|Mh)\.?[ \t]*'
            r'(?:\r?\n[ \t]*\d{1,4}(?:/[0-9A-Za-z]{1,3})?[ \t]*)?$'
        )

        def repl4_ocr(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('head')}{m.group('mlabel')}"

        text = p4_ocr.sub(repl4_ocr, text)

        # 4e. Maskeli adres satırından sonra (arada en çok 1 boş satır) gelen ve kapı numarası +
        # "İlçe/İL" taşıyan devam satırı: "[ADRES_1]\n\n## Sitesi Köşkleri No.12 Ac Merkez/ BURDUR" — aynı etiket
        p4_tail = re.compile(
            r'(?m)(?P<head>(?P<mlabel>' + mask_adres_re + r')[ \t]*\r?\n(?:[ \t]*\r?\n)?)(?P<lead>[ \t#\*]*)'
            r'(?P<cont>(?![^\r\n]*' + mask_adres_re + r')[^\r\n]{0,60}?\b(?:No|[NVMW][oea])[ \t]*[:.][ \t]*\d[^\r\n]{0,40}?'
            r'[A-ZÇĞİÖŞÜa-zçğıöşü]{2,25}[ \t]*/[ \t]*[A-ZÇĞİÖŞÜa-zçğıöşü]{2,20})[ \t\.]*$'
        )

        def repl4_tail(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('head')}{m.group('lead')}{m.group('mlabel')}"

        text = p4_tail.sub(repl4_tail, text)

        return text, count

    @classmethod
    def redact_text(
        cls,
        text: str,
        known_tckns: Optional[Set[str]] = None,
        registry: Optional[MaskRegistry] = None,
    ) -> Tuple[str, Dict[str, int]]:
        """
        Tüm katmanları sırasıyla uygulayarak metni maskeler.
        registry verilirse tutarlı numaralı etiketler ([TCKN_1] ...), verilmezse eski sabit
        etiketler ([TCKN_GİZLENDİ] ...) kullanılır.
        Dönüş: (maskelenmiş_metin, istatistik_sözlüğü)
        """
        stats = cls._empty_stats()

        # Katman 1: Kimlik MRZ (Önce çalışır, blok halinde temizler)
        t, stats["mrz"] = cls.redact_mrz(text, registry=registry)

        # Katman 2: IBAN ve Banka Kartı No
        t, stats["iban"] = cls.redact_iban(t, registry=registry)

        # Katman 2b: Banka hesap / müşteri numarası (yalnızca hesap bağlamında)
        t, stats["hesap"] = cls.redact_account(t, registry=registry)

        # Katman 3: Kimlik Seri No
        t, stats["seri_no"] = cls.redact_seri_no(t, registry=registry)

        # Katman 4: TCKN (Etiketli 9-13 hane, algoritmik 11 hane, Known TCKN Fuzzy Match ve kısmi TCKN)
        t, stats["tckn"] = cls.redact_tckn(t, known_tckns=known_tckns, registry=registry)

        # Katman 5: Cep Telefonu
        t, stats["telefon"] = cls.redact_phone(t, registry=registry)

        # Katman 6: Sicil
        t, stats["sicil"] = cls.redact_sicil(t, registry=registry)

        # Katman 7: Açık Adres
        t, stats["adres"] = cls.redact_address(t, registry=registry)

        stats["total"] = sum(v for k, v in stats.items() if k != "total")
        return t, stats

    @classmethod
    def redact_file_to_memory(
        cls,
        file_path: str,
        encoding: str = "utf-8",
        known_tckns: Optional[Set[str]] = None,
        registry: Optional[MaskRegistry] = None,
    ) -> Tuple[str, Dict[str, int]]:
        """
        Dosyayı salt-okunur (read-only) modda belleğe okur ve maskeler.
        Orijinal dosyaya KESİNLİKLE yazma işlemi yapmaz.
        """
        with open(file_path, "r", encoding=encoding, errors="replace") as f:
            content = f.read()
        return cls.redact_text(content, known_tckns=known_tckns, registry=registry)

    @classmethod
    def extract_pdf_raw(cls, pdf_path: str, max_pages: int = 150) -> str:
        """PDF'i çevrimdışı olarak HAM (maskesiz) metne dönüştürür; yalnızca bellekte kullanılmalıdır."""
        import tempfile
        try:
            import fitz
        except ImportError:
            return ""

        try:
            import Vision
            from Cocoa import NSURL
            has_vision = True
        except ImportError:
            has_vision = False

        try:
            doc = fitz.open(pdf_path)
        except Exception:
            return ""

        try:
            total_pages = len(doc)
            page_count = min(total_pages, max_pages)
            pages_content = []

            with tempfile.TemporaryDirectory() as tmpdir:
                for pno in range(page_count):
                    page = doc[pno]
                    text = page.get_text().strip()

                    if len(text) > 50:
                        pages_content.append(f"### Sayfa {pno + 1}\n\n{text}")
                    elif has_vision:
                        try:
                            pix = page.get_pixmap(dpi=150)
                            img_path = os.path.join(tmpdir, f"page_{pno}.png")
                            pix.save(img_path)
                            url = NSURL.fileURLWithPath_(img_path)
                            req_h = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
                            req = Vision.VNRecognizeTextRequest.alloc().init()
                            req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
                            req.setUsesLanguageCorrection_(True)
                            req.setRecognitionLanguages_(['tr-TR', 'en-US'])
                            succ, _ = req_h.performRequests_error_([req], None)
                            if succ:
                                lines = [r.topCandidates_(1)[0].string() for r in req.results()]
                                pages_content.append(f"### Sayfa {pno + 1} (Yerel OCR)\n\n" + "\n".join(lines))
                        except Exception:
                            pass
        finally:
            doc.close()

        full_raw = f"# {os.path.basename(pdf_path)}\n\n" + "\n\n---\n\n".join(pages_content)
        # Sayfa sınırı aşıldıysa kalan sayfaların sessizce atılmaması için görünür uyarı ekle
        if total_pages > page_count:
            full_raw += (
                f"\n\n---\n\n> ⚠️ Bu belge {total_pages} sayfadır; "
                f"yalnızca ilk {page_count} sayfa işlenmiştir.\n"
            )
        return full_raw

    @classmethod
    def extract_and_redact_pdf(
        cls,
        pdf_path: str,
        max_pages: int = 150,
        known_tckns: Optional[Set[str]] = None,
        registry: Optional["MaskRegistry"] = None,
    ) -> Tuple[str, Dict[str, int]]:
        """
        PDF belgesini çevrimdışı olarak metne dönüştürür ve maskeler.
        1. fitz ile dijital metin katmanı varsa doğrudan alır.
        2. Taranmış fotokopi/resim sayfalarında macOS yerel Apple Vision OCR motorunu kullanır.
        3. Metni UyapRedactor filtrelerinden geçirerek maskeler.
        """
        full_raw = cls.extract_pdf_raw(pdf_path, max_pages=max_pages)
        if not full_raw:
            return "", cls._empty_stats()
        return cls.redact_text(full_raw, known_tckns=known_tckns, registry=registry)

    @classmethod
    def extract_image_raw(cls, img_path: str) -> str:
        """Taranmış görseli Apple Vision OCR ile HAM (maskesiz) metne dönüştürür; yalnızca bellekte kullanılmalıdır."""
        try:
            import Vision
            from Cocoa import NSURL
        except ImportError:
            return ""

        pages_content = []

        # Çok sayfalı TIFF kontrolü
        try:
            from PIL import Image, ImageSequence
            import tempfile
            with Image.open(img_path) as im:
                frames = [f.copy() for f in ImageSequence.Iterator(im)]
                if len(frames) > 1:
                    with tempfile.TemporaryDirectory() as tmpdir:
                        for pno, frame in enumerate(frames[:60]):
                            frame_path = os.path.join(tmpdir, f"frame_{pno}.png")
                            frame.convert("RGB").save(frame_path, "PNG")
                            url = NSURL.fileURLWithPath_(frame_path)
                            req_h = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
                            req = Vision.VNRecognizeTextRequest.alloc().init()
                            req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
                            req.setUsesLanguageCorrection_(True)
                            req.setRecognitionLanguages_(['tr-TR', 'en-US'])
                            succ, _ = req_h.performRequests_error_([req], None)
                            if succ:
                                lines = [r.topCandidates_(1)[0].string() for r in req.results()]
                                if lines:
                                    pages_content.append(f"### Sayfa {pno + 1} (Yerel OCR)\n\n" + "\n".join(lines))
        except Exception:
            pass

        # Tek sayfa doğrudan Vision OCR
        if not pages_content:
            try:
                url = NSURL.fileURLWithPath_(img_path)
                req_h = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
                req = Vision.VNRecognizeTextRequest.alloc().init()
                req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
                req.setUsesLanguageCorrection_(True)
                req.setRecognitionLanguages_(['tr-TR', 'en-US'])
                succ, _ = req_h.performRequests_error_([req], None)
                if succ:
                    lines = [r.topCandidates_(1)[0].string() for r in req.results()]
                    if lines:
                        pages_content.append("### Taranmış Belge (Yerel OCR)\n\n" + "\n".join(lines))
            except Exception:
                pass

        if not pages_content:
            return ""

        full_raw = f"# {os.path.basename(img_path)}\n\n" + "\n\n---\n\n".join(pages_content)
        return full_raw

    @classmethod
    def extract_and_redact_image(
        cls,
        img_path: str,
        known_tckns: Optional[Set[str]] = None,
        registry: Optional["MaskRegistry"] = None,
    ) -> Tuple[str, Dict[str, int]]:
        """
        TIFF, PNG, JPEG formatındaki taranmış evrakları Apple Vision OCR ile
        yerel ve çevrimdışı olarak metne dönüştürür ve maskeler.
        """
        full_raw = cls.extract_image_raw(img_path)
        if not full_raw:
            return "", cls._empty_stats()
        return cls.redact_text(full_raw, known_tckns=known_tckns, registry=registry)

    @classmethod
    def extract_scanned_raw(cls, file_path: str) -> str:
        """PDF veya TIFF/görsel dosyasının HAM metnini döndürür (uzantıya göre)."""
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            return cls.extract_pdf_raw(file_path)
        if ext in (".tif", ".tiff", ".png", ".jpg", ".jpeg"):
            return cls.extract_image_raw(file_path)
        return ""

    @classmethod
    def extract_and_redact_scanned_file(
        cls,
        file_path: str,
        known_tckns: Optional[Set[str]] = None,
        registry: Optional["MaskRegistry"] = None,
        raw_cache_path: Optional[str] = None,
    ) -> Tuple[str, Dict[str, int]]:
        """
        PDF veya TIFF/Görsel dosyalarını uzantısına göre en uygun OCR motoruyla işler ve maskeler.
        raw_cache_path yalnızca geliştirme/denetim içindir (UYAP_OCR_CACHE_DIR): ham OCR metni
        oradan okunur / oraya yazılır. Normal kullanımda None'dır ve ham metin diske yazılmaz.
        """
        raw = ""
        if raw_cache_path and os.path.isfile(raw_cache_path):
            with open(raw_cache_path, "r", encoding="utf-8", errors="replace") as cf:
                raw = cf.read()
        else:
            raw = cls.extract_scanned_raw(file_path)
            if raw_cache_path and raw:
                os.makedirs(os.path.dirname(raw_cache_path), exist_ok=True)
                with open(raw_cache_path, "w", encoding="utf-8") as cf:
                    cf.write(raw)
        if not raw:
            return "", cls._empty_stats()
        return cls.redact_text(raw, known_tckns=known_tckns, registry=registry)

    @classmethod
    def sync_index_file(cls, index_path: str) -> int:
        """
        Belirtilen tek bir INDEX.md dosyasını tarayarak 'Metin' sütununu diskteki
        güncel .md dosyaları ve karakter sayılarıyla senkronize eder.
        Dönüş: Güncellenen satır sayısı.
        """
        if not os.path.isfile(index_path):
            return 0

        index_dir = os.path.dirname(index_path)
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return 0

        lines = content.splitlines(keepends=True)
        new_lines = []
        updated_rows = 0
        in_table = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("| Tarih |") and "Dosya" in stripped and "Metin" in stripped:
                in_table = True
                new_lines.append(line)
                continue
            if in_table and stripped.startswith("|---"):
                new_lines.append(line)
                continue
            if in_table and stripped.startswith("|") and stripped.endswith("|"):
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 8:
                    dosya_col = parts[6]
                    metin_col = parts[7]

                    m_dosya = re.search(r"\[↗\]\((?:<([^>]+)>|([^\)]+))\)", dosya_col)
                    if m_dosya:
                        raw_dosya_path = m_dosya.group(1) or m_dosya.group(2)
                        base_candidates = []

                        # 1) _kaynak/ önekini kaldırarak .md ve .udf.md adayları
                        clean_path = raw_dosya_path
                        if clean_path.startswith("_kaynak/"):
                            clean_path = clean_path[len("_kaynak/"):]
                        base_no_ext, _ = os.path.splitext(clean_path)
                        base_candidates.append(base_no_ext + ".md")
                        if not clean_path.lower().endswith(".md"):
                            base_candidates.append(clean_path + ".md")

                        # 2) _kaynak/ önekini kaldırmadan .md ve .udf.md adayları
                        base_orig, _ = os.path.splitext(raw_dosya_path)
                        base_candidates.append(base_orig + ".md")
                        if not raw_dosya_path.lower().endswith(".md"):
                            base_candidates.append(raw_dosya_path + ".md")

                        # macOS APFS NFD ve NFC dosya adı varyasyonları
                        candidates = []
                        for c in base_candidates:
                            for form in ("NFC", "NFD"):
                                norm_c = unicodedata.normalize(form, c)
                                if norm_c not in candidates:
                                    candidates.append(norm_c)

                        found_md_rel = None
                        found_md_abs = None
                        for cand in candidates:
                            cand_abs = os.path.join(index_dir, cand)
                            if os.path.isfile(cand_abs):
                                found_md_rel = unicodedata.normalize("NFC", cand)
                                found_md_abs = cand_abs
                                break

                        if found_md_abs and os.path.isfile(found_md_abs):
                            try:
                                with open(found_md_abs, "r", encoding="utf-8", errors="replace") as mf:
                                    char_cnt = len(mf.read())
                                formatted_cnt = f"{char_cnt:,}".replace(",", ".")
                                new_metin = f"[↗](<{found_md_rel}>) ({formatted_cnt} karakter)"

                                if unicodedata.normalize("NFC", metin_col) != unicodedata.normalize("NFC", new_metin):
                                    parts[7] = new_metin
                                    line = "| " + " | ".join(parts[1:-1]) + " |\n"
                                    updated_rows += 1
                            except Exception:
                                pass
                new_lines.append(line)
            else:
                if in_table and stripped.startswith("#"):
                    in_table = False
                new_lines.append(line)

        # Genel geçiş: tablo biçiminden bağımsız olarak (ör. arşiv alt INDEX.md'leri)
        # "[↗](<göreli.md>) (N karakter)" sayaçlarını diskteki gerçek uzunlukla güncelle
        joined = "".join(new_lines)

        def repl_count(m: re.Match) -> str:
            nonlocal updated_rows
            rel = m.group(1)
            for form in ("NFC", "NFD"):
                fp = os.path.join(index_dir, unicodedata.normalize(form, rel))
                if os.path.isfile(fp):
                    try:
                        with open(fp, "r", encoding="utf-8", errors="replace") as mf:
                            cnt = len(mf.read())
                    except Exception:
                        return m.group(0)
                    formatted = f"{cnt:,}".replace(",", ".")
                    if formatted != m.group(2):
                        updated_rows += 1
                        return f"[↗](<{rel}>) ({formatted} karakter)"
                    return m.group(0)
            return m.group(0)

        joined = re.sub(r'\[↗\]\(<([^>\n]+)>\) \(([\d.]+) karakter\)', repl_count, joined)

        if updated_rows > 0:
            try:
                with open(index_path, "w", encoding="utf-8") as f:
                    f.write(joined)
            except Exception:
                pass

        return updated_rows

    # ------------------------------------------------------------------
    # Temiz klasör son işlemleri: kopuk görsel/ikili bağlantılar ve OCR kalite denetimi
    # ------------------------------------------------------------------
    BINARY_LINK_EXTS = (".pdf", ".udf", ".tif", ".tiff", ".png", ".jpg", ".jpeg", ".gif", ".bmp",
                        ".xlsx", ".xls", ".docx", ".doc", ".html", ".htm", ".eml", ".eyp", ".zip", ".rar",
                        # e-yazışma paketi iç dosyaları (imza/mühür/üstveri): temiz klasöre aktarılmaz
                        ".imz", ".xml", ".psmdcp", ".p7s", ".cer", ".sig")
    IMAGE_LINK_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff")
    OCR_MARKER = "Taranmış Belge (Yerel OCR)"
    OCR_WARNING = (
        "> ⚠️ **OCR UYARISI:** Bu taranmış evrak (muhtemelen el yazısı veya düşük kaliteli tarama) "
        "yerel OCR ile güvenilir biçimde okunamadı; aşağıdaki metin büyük ölçüde hatalıdır. "
        "İçerik için belgenin aslına başvurulmalıdır.\n\n"
    )
    _COMMON_TR_WORDS = set("""
        ve ile için olarak olan bu bir da de ki gibi daha sonra önce tarihli tarihinde sayılı esas karar
        mahkemesi mahkemesine mahkeme dosya dosyası dava davacı davalı vekili vekil talep talebi edilmesine
        hakkında ilişkin gereğince madde maddesi kanun kanunu hukuk asliye sulh ceza icra tebligat tebliğ
        müzekkere cevap cevabı dilekçe dilekçesi yazı yazınız ilgi konu sayın başkanlığı başkanlığına
        müdürlüğü müdürlüğüne genel bilgi banka bankası hesap hesabı adına ait kayıtlı bulunan bulunmaktadır
        tespit edilmiştir edilen yapılan arz olunur saygılarımla saygılarımızla rica tarih imza mühür
        türkiye cumhuriyeti adalet bakanlığı noterliği noter vekaletname adres adresi telefon kimlik
        nüfus doğum doğumlu oğlu kızı adı soyadı sanık şüpheli müşteki tanık bilirkişi rapor raporu
    """.split())

    @staticmethod
    def _tr_lower(x: str) -> str:
        return x.replace("I", "ı").replace("İ", "i").lower()

    @classmethod
    def _ocr_word_hit_ratio(cls, text: str, vocab: Set[str]) -> Tuple[float, int]:
        body = text.split(cls.OCR_MARKER, 1)[-1]
        body = re.sub(cls.MASK_ANY_RE, ' ', body)
        words = [cls._tr_lower(w) for w in re.findall(r'[A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛû]{3,}', body)]
        if not words:
            return 1.0, 0
        hits = sum(1 for w in words if w in vocab or w in cls._COMMON_TR_WORDS)
        return hits / len(words), len(words)

    @classmethod
    def flag_low_quality_ocr(cls, dest_folder: str, threshold: float = 0.35, min_words: int = 20) -> list:
        """
        Klasördeki OCR'lı .md'leri, aynı dava klasörünün düzgün metinlerinden çıkarılan kelime
        dağarcığıyla karşılaştırır. Tanınan kelime oranı eşik altındaysa (el yazısı / bozuk OCR)
        belgenin başına uyarı ekler. Dönüş: işaretlenen göreli yollar.
        """
        vocab: Set[str] = set()
        ocr_docs = []
        for root, _dirs, files in os.walk(dest_folder):
            for f in files:
                if not f.endswith(".md"):
                    continue
                p = os.path.join(root, f)
                try:
                    with open(p, "r", encoding="utf-8", errors="replace") as fh:
                        t = fh.read()
                except Exception:
                    continue
                if cls.OCR_MARKER in t:
                    ocr_docs.append((p, t))
                else:
                    vocab.update(cls._tr_lower(w) for w in re.findall(r'[A-Za-zÇĞİÖŞÜçğıöşü]{3,}', t))
        flagged = []
        for p, t in ocr_docs:
            ratio, n = cls._ocr_word_hit_ratio(t, vocab)
            if n >= min_words and ratio < threshold:
                if "OCR UYARISI" not in t:
                    lines = t.split("\n", 1)
                    if lines and lines[0].startswith("# "):
                        new_t = lines[0] + "\n\n" + cls.OCR_WARNING + (lines[1].lstrip("\n") if len(lines) > 1 else "")
                    else:
                        new_t = cls.OCR_WARNING + t
                    with open(p, "w", encoding="utf-8") as fh:
                        fh.write(new_t)
                flagged.append(os.path.relpath(p, dest_folder))
        return sorted(flagged)

    @classmethod
    def rewrite_dropped_links(cls, md_path: str) -> bool:
        """
        Temiz klasöre aktarılmayan görsel/ikili dosyalara giden Markdown bağlantılarını düzeltir:
        - OCR metni varsa bağlantıyı o .md'ye çevirir,
        - yoksa kopuk bağlantıyı düz metne indirger ("görsel aktarılmadı").
        """
        try:
            with open(md_path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except Exception:
            return False
        base_dir = os.path.dirname(md_path)

        def exists_rel(rel: str) -> bool:
            for form in ("NFC", "NFD"):
                if os.path.exists(os.path.join(base_dir, unicodedata.normalize(form, rel))):
                    return True
            return False

        link_re = re.compile(r'(?P<img>!?)\[(?P<alt>[^\]\n]*)\]\((?:<(?P<t1>[^>\n]+)>|(?P<t2>[^)\n]+?))\)')

        def repl(m: re.Match) -> str:
            target = m.group('t1') or m.group('t2') or ""
            if re.match(r'(?i)^(?:https?|mailto|file):', target) or target.startswith("#"):
                return m.group(0)
            low = target.lower()
            if exists_rel(target) or exists_rel(urllib.parse.unquote(target)):
                return m.group(0)
            if low.endswith(".md"):
                # Kaynakta da bulunmayan/aktarılmayan .md hedefi (ör. dava-analiz.md içindeki ölü bağlantı)
                return "—" if m.group('alt') == "↗" else (m.group('alt') or os.path.basename(target))
            if not low.endswith(cls.BINARY_LINK_EXTS):
                return m.group(0)
            alt = m.group('alt')
            if alt == "↗":  # INDEX tablosundaki "Dosya" sütunu: orijinal aktarılmadı (metin "Metin" sütununda)
                return "—"
            for cand in (os.path.splitext(target)[0] + ".md", target + ".md"):
                if exists_rel(cand):
                    label = alt if alt and alt != "↗" else os.path.basename(target)
                    return f"[{label} (OCR metni)](<{cand}>)"
            if m.group('img') or low.endswith(cls.IMAGE_LINK_EXTS):
                return f"[görsel aktarılmadı: {alt or os.path.basename(target)}]"
            if alt == "↗":
                return "—"
            return alt or os.path.basename(target)

        new_text = link_re.sub(repl, text)
        new_text = re.sub(
            r'(?m)^> \*\*Görseller:\*\*.*$',
            "> **Görseller:** Bu belgedeki görseller (imza/mühür simgeleri vb.) güvenlik gereği temiz "
            "klasöre aktarılmadı; metin içeren görseller varsa OCR metni ayrı .md olarak eklenmiştir.",
            new_text,
        )
        if new_text != text:
            with open(md_path, "w", encoding="utf-8") as fh:
                fh.write(new_text)
            return True
        return False

    @classmethod
    def sync_index_md(cls, folder: str) -> int:
        """
        Verilen dava klasörü altındaki tüm INDEX.md dosyalarını bularak
        otomatik olarak diskteki .md türevleri ve karakter sayılarıyla senkronize eder.
        Dönüş: Toplam güncellenen satır sayısı.
        """
        if not os.path.isdir(folder):
            return 0

        total_updated = 0
        for root, dirs, files in os.walk(folder):
            if cls._is_skipped_dir(root, folder, cls.SKIP_DIRS):
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if not cls._is_skipped_dir(os.path.join(root, d), folder, cls.SKIP_DIRS)]
            for f in files:
                if f == "INDEX.md":
                    full_index_path = os.path.join(root, f)
                    total_updated += cls.sync_index_file(full_index_path)

        return total_updated

    @classmethod
    def _redact_json_value(
        cls, value, known_tckns: Optional[Set[str]], stats: Dict[str, int],
        registry: Optional[MaskRegistry] = None,
    ):
        """
        JSON ağacındaki tüm string değerleri (iç içe dict/list dahil) tek tek maskeler.
        Anahtarlara dokunulmaz. Tamsayı olarak saklanan 11 haneli geçerli/bilinen TCKN'ler
        MASK_TCKN stringine çevrilir.
        """
        if isinstance(value, dict):
            return {k: cls._redact_json_value(v, known_tckns, stats, registry) for k, v in value.items()}
        if isinstance(value, list):
            return [cls._redact_json_value(v, known_tckns, stats, registry) for v in value]
        if isinstance(value, str):
            red, s = cls.redact_text(value, known_tckns=known_tckns, registry=registry)
            for k in cls.STAT_KEYS:
                stats[k] += s[k]
            return red
        if isinstance(value, int) and not isinstance(value, bool):
            sval = str(value)
            if len(sval) == 11 and (cls.is_valid_tckn(sval) or (known_tckns and sval in known_tckns)):
                stats["tckn"] += 1
                stats["total"] += 1
                return cls._mask("tckn", sval, registry)
        return value

    @classmethod
    def redact_json_file(
        cls,
        src_path: str,
        dest_path: str,
        known_tckns: Optional[Set[str]] = None,
        registry: Optional[MaskRegistry] = None,
    ) -> Dict[str, int]:
        """
        Manifest JSON dosyasını değer bazında maskeleyerek hedefe yazar.
        JSON parse edilemezse dosya ASLA ham kopyalanmaz: tüm metin redact_text'ten
        geçirilerek yazılır (fail-closed).
        Not: Ham JSON satırını doğrudan redact_text'e vermek, adres regex'inin satırın
        kalanını yutmasına yol açtığından değer bazında maskeleme tercih edilir.
        """
        import json
        stats = cls._empty_stats()
        with open(src_path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError):
            red, s = cls.redact_text(raw, known_tckns=known_tckns, registry=registry)
            for k in stats:
                stats[k] += s[k]
            with open(dest_path, "w", encoding="utf-8") as wf:
                wf.write(red)
            return stats

        red_data = cls._redact_json_value(data, known_tckns, stats, registry)
        with open(dest_path, "w", encoding="utf-8") as wf:
            json.dump(red_data, wf, ensure_ascii=False, indent=2)
        return stats

    @classmethod
    def export_isolated_clean_folder(
        cls,
        src_folder: str,
        dest_folder: Optional[str] = None,
        progress_cb: Optional[Callable[[str, str, Dict], None]] = None
    ) -> Tuple[str, Dict]:
        """
        İzole temiz klasör üretimi:
        Maskeli .md'leri yeni klasöre yazar, metni olmayan taranmış evraklara yerel OCR uygular,
        INDEX.md karakter sayılarını günceller ve yapay zekâ analizine hazırlanmış ayrı bir
        dava klasörü üretir. Orijinal klasöre yazmaz.

        Maskeler tutarlı ve numaralıdır ([TCKN_1], [ADRES_2] ...): aynı değer tüm belgelerde
        aynı etiketi alır. Değer-etiket eşlemesi yalnızca bellekte tutulur, hiçbir dosyaya yazılmaz.

        Hedef klasöre orijinal UDF, PDF, TIFF veya ZIP gibi ikili dosyalar aktarılmaz.
        Otomatik maskeleme hatasız değildir; özellikle OCR'lı belgeler gözden geçirilmelidir.
        """
        src_folder = os.path.abspath(src_folder)
        clean_src = src_folder.rstrip(os.sep)
        if not dest_folder:
            if unicodedata.normalize("NFC", clean_src).endswith("(Maskelenmis AI)"):
                dest_folder = clean_src
            else:
                dest_folder = clean_src + " (Maskelenmis AI)"
        else:
            dest_folder = os.path.abspath(dest_folder)

        # Veri kaybı koruması: Hedef, kaynak klasörün kendisiyse (ör. --out kaynakla aynı)
        # temizlik adımı orijinal _kaynak/ dizinini ve UDF/PDF/TIFF'leri silerdi.
        # Yalnızca zaten '(Maskelenmis AI)' adlı çıktı klasörünün kendi üzerine yeniden çalıştırılmasına izin ver.
        real_src = unicodedata.normalize("NFC", os.path.realpath(src_folder))
        real_dest = unicodedata.normalize("NFC", os.path.realpath(dest_folder))
        if real_src == real_dest and not real_src.rstrip(os.sep).endswith("(Maskelenmis AI)"):
            raise ValueError(
                "Hedef klasör kaynak dava klasörüyle aynı olamaz: bu işlem orijinal UDF/PDF/TIFF "
                "dosyalarını silerdi. Lütfen farklı bir hedef klasör seçin "
                "(varsayılan: '<klasör> (Maskelenmis AI)')."
            )

        # Yalnızca geliştirme/denetim: ham OCR metni önbelleği (varsayılan kapalı)
        ocr_cache_dir = os.environ.get("UYAP_OCR_CACHE_DIR") or None
        if ocr_cache_dir:
            ocr_cache_dir = os.path.abspath(ocr_cache_dir)
            real_cache = unicodedata.normalize("NFC", os.path.realpath(ocr_cache_dir))
            if cls._is_inside_path(real_cache, real_dest.rstrip(os.sep)):
                raise ValueError(
                    "UYAP_OCR_CACHE_DIR hedef (maskeli) klasörün içinde olamaz: "
                    "ham OCR metni maskeli çıktıya karışırdı."
                )
            if real_src != real_dest and cls._is_inside_path(real_cache, real_src.rstrip(os.sep)):
                raise ValueError(
                    "UYAP_OCR_CACHE_DIR kaynak dava klasörünün içinde olamaz: kaynak klasöre yazılmaz."
                )

        os.makedirs(dest_folder, exist_ok=True)
        norm_src = unicodedata.normalize("NFC", src_folder)
        norm_dest = unicodedata.normalize("NFC", dest_folder)

        def _is_dest_subtree(path: str) -> bool:
            """Hedef klasör kaynağın içindeyse, hedefin kendisi ve altı taranmaz."""
            if norm_dest == norm_src:
                return False
            return cls._is_inside_path(unicodedata.normalize("NFC", path), norm_dest)

        grand_stats: Dict = cls._empty_stats()
        grand_stats.update({
            "md_transferred": 0,
            "ocr_converted": 0,
            "index_synced": 0,
            "total_files": 0,
            "total_work": 0,
            "processed_items": 0,
            "last_file_stats": {},
            "last_file_path": "",
        })

        def _add(st: Dict[str, int]) -> None:
            for k in cls.STAT_KEYS:
                grand_stats[k] += st.get(k, 0)

        # 0. Klasör genelinde bilinen TCKN setini (known_tckns) topla (2 aşamalı hafıza)
        known_tckns = cls.collect_known_tckns_from_folder(src_folder)
        # Tek, yalnızca bellekte tutulan etiket kaydı: tüm belgelerde aynı değer = aynı etiket
        registry = MaskRegistry(known_tckns)

        # 1. Mevcut Markdown ve Metin Belgelerini Topla (determinizm için sıralı)
        md_files = []
        for root, dirs, files in os.walk(src_folder):
            if cls._is_skipped_dir(root, src_folder, cls.SKIP_DIRS) or _is_dest_subtree(root):
                dirs[:] = []
                continue
            dirs[:] = sorted(
                d for d in dirs
                if not cls._is_skipped_dir(os.path.join(root, d), src_folder, cls.SKIP_DIRS)
                and not _is_dest_subtree(os.path.join(root, d))
            )
            for f in sorted(files):
                if f.endswith((".md", ".txt")) and not f.endswith(".bak"):
                    md_files.append(os.path.join(root, f))
        md_files.sort(key=lambda p: unicodedata.normalize("NFC", os.path.relpath(p, src_folder)))

        grand_stats["total_files"] = len(md_files)
        grand_stats["total_work"] = len(md_files)

        # 1a. Ön tarama (yalnızca bellekte): bağlamıyla tespit edilen hesap/sicil numaralarını öğren;
        # böylece aynı numara başka belgede bağlamsız geçtiğinde de aynı etiketle maskelenir.
        learn = MaskRegistry(known_tckns)
        for file_path in md_files:
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    cls.redact_text(f.read(), known_tckns=known_tckns, registry=learn)
            except Exception:
                pass
        registry.seed("hesap", learn.known_values("hesap", min_len=7))
        registry.seed("sicil", learn.known_values("sicil", min_len=5))
        del learn

        for file_path in md_files:
            rel_path = os.path.relpath(file_path, src_folder)
            dest_path = os.path.join(dest_folder, rel_path)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

                redacted_text, stats = cls.redact_text(content, known_tckns=known_tckns, registry=registry)
                _add(stats)

                with open(dest_path, "w", encoding="utf-8") as wf:
                    wf.write(redacted_text)

                grand_stats["md_transferred"] += 1
                grand_stats["processed_items"] += 1
                grand_stats["last_file_stats"] = stats
                grand_stats["last_file_path"] = rel_path
                if progress_cb:
                    progress_cb("md", rel_path, grand_stats)
            except Exception as e:
                if progress_cb:
                    progress_cb("error", f"{rel_path}: {str(e)}", grand_stats)

        # 2. Taranmış Evrakları (PDF ve TIFF) Tara ve Gerekirse Apple Vision OCR ile Çöz
        scanned_files = []
        # Not: Bu tarama _kaynak/ dizinini BİLEREK tarar (orijinal PDF/TIFF'ler oradadır)
        for root, dirs, files in os.walk(src_folder):
            if cls._is_skipped_dir(root, src_folder, cls.SKIP_DIRS_OCR) or _is_dest_subtree(root):
                dirs[:] = []
                continue
            dirs[:] = sorted(
                d for d in dirs
                if not cls._is_skipped_dir(os.path.join(root, d), src_folder, cls.SKIP_DIRS_OCR)
                and not _is_dest_subtree(os.path.join(root, d))
            )
            for f in sorted(files):
                ext = os.path.splitext(f)[1].lower()
                if ext in (".pdf", ".tif", ".tiff", ".png", ".jpg", ".jpeg"):
                    full_p = os.path.join(root, f)
                    rel_p = os.path.relpath(full_p, src_folder)
                    clean_rel = rel_p
                    if clean_rel.startswith("_kaynak/"):
                        clean_rel = clean_rel[len("_kaynak/"):]
                    base_rel = os.path.splitext(clean_rel)[0] + ".md"
                    target_dest_md = os.path.join(dest_folder, base_rel)

                    # Eğer hedef klasörde bu evrakın .md metni henüz yoksa veya 50 karakterden kısaysa
                    if not os.path.exists(target_dest_md) or os.path.getsize(target_dest_md) < 50:
                        scanned_files.append((full_p, base_rel, target_dest_md))
        scanned_files.sort(key=lambda x: unicodedata.normalize("NFC", x[1]))

        grand_stats["total_work"] = len(md_files) + len(scanned_files)

        ocr_converted_list = []
        for full_p, base_rel, target_dest_md in scanned_files:
            try:
                raw_cache_path = os.path.join(ocr_cache_dir, base_rel) if ocr_cache_dir else None
                red_text, p_stats = cls.extract_and_redact_scanned_file(
                    full_p, known_tckns=known_tckns, registry=registry, raw_cache_path=raw_cache_path
                )
                grand_stats["processed_items"] += 1
                grand_stats["last_file_stats"] = p_stats
                grand_stats["last_file_path"] = base_rel

                if len(red_text.strip()) > 50:
                    os.makedirs(os.path.dirname(target_dest_md), exist_ok=True)
                    with open(target_dest_md, "w", encoding="utf-8") as wf:
                        wf.write(red_text)
                    _add(p_stats)
                    grand_stats["ocr_converted"] += 1
                    grand_stats["md_transferred"] += 1
                    ocr_converted_list.append(base_rel)
                    if progress_cb:
                        progress_cb("ocr", base_rel, grand_stats)
            except Exception as oe:
                grand_stats["processed_items"] += 1
                if progress_cb:
                    progress_cb("error", f"OCR Hatası ({os.path.basename(full_p)}): {str(oe)}", grand_stats)

        # 3. Yargı PRO Manifest JSON Dosyalarını Değer Bazında Maskeleyerek Aktar
        # (AGENTS.md ve kök seviyedeki dosya-bilgileri.md / safahat.md / dava-analiz.md
        #  1. adımda zaten maskelenerek aktarılır; burada maskesiz kopyalanmaz / çift sayılmaz.)
        for meta_name in cls.META_JSON_NAMES:
            meta_src = os.path.join(src_folder, meta_name)
            meta_dest = os.path.join(dest_folder, meta_name)
            if os.path.isfile(meta_src):
                try:
                    j_stats = cls.redact_json_file(meta_src, meta_dest, known_tckns=known_tckns, registry=registry)
                    _add(j_stats)
                except Exception as je:
                    if progress_cb:
                        progress_cb("error", f"{meta_name}: {str(je)}", grand_stats)

        # 4. İkili dosya temizliği (hedef klasördeki olası ikili kalıntıları ve _kaynak dizinini temizle)
        clean_kaynak = os.path.join(dest_folder, "_kaynak")
        if os.path.isdir(clean_kaynak):
            shutil.rmtree(clean_kaynak, ignore_errors=True)

        for root, dirs, files in os.walk(dest_folder, topdown=False):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in (".udf", ".pdf", ".tif", ".tiff", ".eyp", ".zip", ".bak"):
                    try:
                        os.remove(os.path.join(root, f))
                    except Exception:
                        pass
            # Boş kalan alt dizinleri temizle
            for d in dirs:
                dir_path = os.path.join(root, d)
                try:
                    if os.path.isdir(dir_path) and not os.listdir(dir_path):
                        os.rmdir(dir_path)
                except Exception:
                    pass

        # 4b. OCR kalite denetimi (el yazısı / bozuk OCR belgelerine uyarı) ve OCR'lı evrak listesi
        low_quality = cls.flag_low_quality_ocr(dest_folder)
        grand_stats["low_quality_ocr"] = low_quality
        md_paths = []
        for root, _dirs, files in os.walk(dest_folder):
            for f in sorted(files):
                if f.endswith(".md"):
                    md_paths.append(os.path.join(root, f))
        ocr_docs = []
        for p in md_paths:
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    t = fh.read()
                if cls.OCR_MARKER in t or "(Yerel OCR)" in t:
                    ocr_docs.append(unicodedata.normalize("NFC", os.path.relpath(p, dest_folder)))
            except Exception:
                pass
        grand_stats["ocr_present"] = len(ocr_docs)
        grand_stats["ocr_docs"] = sorted(ocr_docs)

        # 4c. Belgelerdeki kopuk görsel/ikili bağlantıları düzelt (INDEX.md'ler hariç) —
        # dosya uzunluğunu değiştiren tüm yeniden yazımlar INDEX senkronundan ÖNCE yapılır.
        for p in md_paths:
            if os.path.basename(p) != "INDEX.md":
                cls.rewrite_dropped_links(p)

        # 5. INDEX.md karakter sayısı senkronizasyonu (Dosya sütunundaki orijinal bağlantıyı kullanır),
        # ardından INDEX.md'deki aktarılmayan orijinal bağlantıları düz metne çevir (diğer
        # dosyaların uzunluğunu değiştirmez).
        synced_dest = cls.sync_index_md(dest_folder)
        grand_stats["index_synced"] = synced_dest
        for p in md_paths:
            if os.path.basename(p) == "INDEX.md":
                cls.rewrite_dropped_links(p)

        # 6. Dönüşüm ve maskeleme raporu (ham değer içermez)
        grand_stats["mask_occurrences"] = dict(registry.occurrences)
        grand_stats["mask_distinct"] = {k: registry.distinct(k) for k in MaskRegistry.PREFIX}
        cls._write_report(src_folder, dest_folder, grand_stats)

        return dest_folder, grand_stats

    REPORT_NAME = "DAVA_DÖNÜŞÜM_VE_GÜVENLİK_RAPORU.md"

    @classmethod
    def _write_report(cls, src_folder: str, dest_folder: str, gs: Dict) -> None:
        """Çıktı klasörüne dürüst bir dönüşüm raporu yazar. Ham kişisel değer YAZMAZ."""
        occ = gs.get("mask_occurrences", {})
        dist = gs.get("mask_distinct", {})
        names = [
            ("tckn", "T.C. Kimlik No / YKN", "kişi"), ("iban", "IBAN", "farklı IBAN"),
            ("hesap", "Banka hesap / müşteri no", "farklı numara"), ("kart", "Banka kartı no", "farklı kart"),
            ("telefon", "Cep telefonu", "farklı numara"), ("seri_no", "Kimlik seri no", "farklı seri no"),
            ("mrz", "Kimlik MRZ şeridi", "farklı şerit"), ("sicil", "Sicil no (hâkim/kâtip/bilirkişi/baro/ticaret)",
                                                          "farklı sicil"),
            ("adres", "Açık kişi adresi", "farklı adres (yaklaşık)"),
        ]
        report_path = os.path.join(dest_folder, cls.REPORT_NAME)
        with open(report_path, "w", encoding="utf-8") as rf:
            w = rf.write
            w("# Dava Dönüşüm ve Maskeleme Raporu\n\n")
            w(f"**Kaynak dava klasörü:** {os.path.basename(src_folder)}\n")
            w(f"**Maskeli klasör:** {os.path.basename(dest_folder)}\n")
            w(f"**İşlem tarihi:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            w(f"**Aktarılan metin belgesi (.md):** {gs['md_transferred']} adet\n")
            w(f"**Bu çalıştırmada yerel OCR ile metne dökülen taranmış ek:** {gs['ocr_converted']} adet\n")
            w(f"**OCR'lı (taranmış) evrak:** {gs.get('ocr_present', 0)} adet\n")
            w(f"**INDEX.md'de güncellenen karakter sayısı:** {gs['index_synced']} satır\n\n")

            w("## Maskelenen bilgiler\n\n")
            w("| Tür | Maskelenen yer | Farklı değer |\n|---|---:|---:|\n")
            for k, label, unit in names:
                w(f"| {label} | {occ.get(k, 0)} | {dist.get(k, 0)} {unit} |\n")
            w(f"\nToplam maskelenen yer: {sum(occ.values())}\n\n")

            w("## Etiketlerin anlamı\n\n")
            w("- Maskeler numaralıdır: `[TCKN_1]`, `[IBAN_2]`, `[ADRES_3]`, `[TEL_1]`, `[SİCİL_4]`, `[HESAP_1]`, "
              "`[KART_1]`, `[SERİ_NO_1]`, `[MRZ_1]`.\n")
            w("- **Aynı numara = aynı değer.** Aynı kişinin TCKN'si tüm belgelerde aynı etiketi taşır; farklı "
              "numaralar farklı değerlerdir. Böylece yapay zekâ kimin hangi hesaba/adrese sahip olduğunu "
              "değeri görmeden izleyebilir.\n")
            w("- Değer-etiket eşleme tablosu **bilerek hiçbir yere yazılmadı**; yalnızca işlem sırasında bellekte "
              "tutuldu. Numaralar her çalıştırmada yeniden üretilir.\n")
            w("- Adreslerde eşleştirme yaklaşıktır: kısaltmalar (Mah./Mahallesi, Sk./Sokak, No:) ve il/ilçe "
              "kuyruğu yok sayılır; yine de aynı adresin farklı yazımları (ör. '28/3' ile '28 İç Kapı No:3') "
              "farklı numara alabilir.\n")
            w("- Kaynakta zaten bulunan eski biçim etiketler (`[ADRES_GİZLENDİ]` vb.) olduğu gibi bırakıldı.\n\n")

            w("## Bilerek korunanlar (maskelenmedi)\n\n")
            w("- Ad-soyad ve taraf sıfatları, olay anlatımı, tarihler, esas/karar numaraları, para tutarları, "
              "kanun maddeleri ve süreler.\n")
            w("- Plaka, olay yeri (ör. 'SUÇUN YERİ', kaza yeri), mahkeme/kurum adları.\n")
            w("- Kurum adresleri: banka genel müdürlüğü/şube, adliye/mahkeme, noter, baro, icra dairesi, kamu "
              "kurumu, PTT, şirket antedi. Bağlam belirsizse adres kişi adresi sayılıp maskelendi.\n")
            w("- Sabit hat (ör. 0232/0850 ile başlayan kurum telefonları); yalnızca cep telefonları maskelenir.\n")
            w("- Belge doğrulama kodları, KEP / e-posta / web adresleri, Mersis no, banka referans/BPM no.\n\n")

            ocr_docs = gs.get("ocr_docs") or []
            w("## OCR'lı belgeler\n\n")
            if ocr_docs:
                w("Aşağıdaki belgelerin metni taramadan OCR ile elde edildi; OCR hataları nedeniyle "
                  "bozulmuş numaralar maskeden kaçabilir veya metin hatalı olabilir:\n\n")
                for rel in ocr_docs:
                    w(f"- `{rel}`\n")
            else:
                w("OCR'lı belge yok.\n")
            low_q = gs.get("low_quality_ocr") or []
            if low_q:
                w("\n### Güvenilmez OCR (uyarı eklendi)\n\n")
                w("Bu belgelerin OCR metni büyük ölçüde hatalıdır (muhtemelen el yazısı). Yapay zekâ içeriği "
                  "doğru anlayamaz; asıllarına başvurun:\n\n")
                for rel in low_q:
                    w(f"- `{rel}`\n")

            w("\n## Bilinen sınırlar\n\n")
            w("- Maskeleme kural tabanlıdır ve hatasız değildir. Özellikle OCR'lı belgelerde bozulmuş, satırlara "
              "bölünmüş veya alışılmadık biçimdeki numaralar ve adresler gözden kaçabilir. Paylaşmadan önce "
              "göz atın.\n")
            w("- Ad-soyad, doğum tarihi, anne/baba adı ve nüfus kayıt yeri maskelenmez (dava analizi için "
              "gereklidir).\n")
            w("- Vergi kimlik no (VKN), plaka, e-posta adresi maskelenmez.\n")
            w("- Bu klasörde orijinal UDF/PDF/TIFF/görsel dosyası yoktur; yalnızca .md metinleri ve maskeli "
              "JSON manifestleri vardır. Aktarılmayan dosyalara giden bağlantılar düz metne çevrildi.\n")


def main():
    """CLI giriş noktası (Varsayılan olarak İzole Temiz Klasör Üretir)."""
    import argparse

    parser = argparse.ArgumentParser(
        description="UYAP Kişisel Veri Maskeleme ve AI Hazırlık Aracı (Sadece İzole Temiz Klasör Üretimi)"
    )
    parser.add_argument("path", help="Hedef UYAP dava klasörü yolu")
    parser.add_argument("--out", help="İzole temiz klasörün oluşturulacağı hedef dizin (Varsayılan: '<path> (Maskelenmis AI)')", default=None)
    parser.add_argument(
        "--in-place",
        action="store_true",
        default=False,
        help="Yalnızca geliştirme/test için: .md dosyalarını yerinde maskeler",
    )
    parser.add_argument(
        "--sync-index",
        action="store_true",
        default=False,
        help="Yalnızca INDEX.md dosyasını senkronize eder",
    )

    args = parser.parse_args()

    if not os.path.exists(args.path):
        print(f"Hata: Yol bulunamadı: {args.path}", file=sys.stderr)
        sys.exit(1)

    if args.sync_index:
        target_dir = args.path if os.path.isdir(args.path) else os.path.dirname(args.path)
        updated = UyapRedactor.sync_index_md(target_dir)
        print(f"İndeks Senkronizasyonu Tamamlandı: {updated} adet evrak satırı güncellendi.")
        return

    if args.in_place:
        print("Yerinde (in-place) maskeleme çalıştırılıyor...")
        target_dir = args.path if os.path.isdir(args.path) else os.path.dirname(args.path)
        known_tckns = UyapRedactor.collect_known_tckns_from_folder(target_dir)
        registry = MaskRegistry(known_tckns)
        in_place_stats = UyapRedactor._empty_stats()
        skip_names = UyapRedactor.SKIP_DIRS
        for root, dirs, files in os.walk(target_dir):
            if UyapRedactor._is_skipped_dir(root, target_dir, skip_names):
                dirs[:] = []
                continue
            dirs[:] = sorted(d for d in dirs if not UyapRedactor._is_skipped_dir(os.path.join(root, d), target_dir, skip_names))
            for file in sorted(files):
                if file.endswith((".md", ".txt")) and not file.endswith(".bak"):
                    fp = os.path.join(root, file)
                    red, stats = UyapRedactor.redact_file_to_memory(fp, known_tckns=known_tckns, registry=registry)
                    for k in in_place_stats:
                        in_place_stats[k] += stats[k]
                    if stats["total"] > 0:
                        with open(fp, "w", encoding="utf-8") as wf:
                            wf.write(red)
        synced = UyapRedactor.sync_index_md(target_dir)
        print(
            f"Maskelenen TCKN: {in_place_stats['tckn']}, Telefon: {in_place_stats['telefon']}, "
            f"Seri: {in_place_stats['seri_no']}, MRZ: {in_place_stats['mrz']}, "
            f"IBAN/Kart: {in_place_stats['iban']}, Hesap: {in_place_stats['hesap']}, Sicil: {in_place_stats['sicil']}, "
            f"Adres: {in_place_stats['adres']}, Toplam: {in_place_stats['total']}, "
            f"İndeks Senkron: {synced}"
        )
        print("Yerinde maskeleme ve indeks senkronizasyonu tamamlandı.")
        return

    # VARSAYILAN TEK VE ANA İŞLEM: İzole Temiz Klasör Üretimi
    print("=" * 60)
    print("🛡️ UYAP İZOLE TEMİZ DAVA KLASÖRÜ ÜRETİMİ (AI EXPORT)")
    print("=" * 60)
    try:
        dest, stats = UyapRedactor.export_isolated_clean_folder(args.path, args.out)
    except ValueError as ve:
        print(f"Hata: {ve}", file=sys.stderr)
        sys.exit(1)

    print("\n✅ Maskeli klasör oluşturuldu. Otomatik maskeleme hatasız değildir; paylaşmadan önce raporu ve OCR'lı belgeleri gözden geçirin.")
    print(f"📂 Hedef Klasör : {dest}")
    print(f"📄 Aktarılan .md: {stats['md_transferred']} adet")
    print(f"👁️ Yerel OCR    : {stats['ocr_converted']} adet")
    print(f"🔄 İndeks Senkron: {stats['index_synced']} kayıt")
    print("\n--- GİZLENEN KİŞİSEL VERİLER ---")
    print(f"Maskelenen TCKN          : {stats['tckn']}")
    print(f"Maskelenen Cep Telefonu  : {stats['telefon']}")
    print(f"Maskelenen Kimlik Seri No: {stats['seri_no']}")
    print(f"Maskelenen Kimlik MRZ    : {stats['mrz']}")
    print(f"Maskelenen IBAN / Kart   : {stats['iban']}")
    print(f"Maskelenen Hesap/Müşteri : {stats['hesap']}")
    print(f"Maskelenen Sicil         : {stats['sicil']}")
    print(f"Maskelenen Adres         : {stats['adres']}")
    print(f"Toplam Maskeleme         : {stats['total']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
