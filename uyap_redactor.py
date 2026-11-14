#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UYAP Çevrimdışı Kişisel Veri Maskeleme ve İndeks Senkronizasyon Aracı (uyap_redactor.py)
---------------------------------------------------------------------------------------
Orijinale dokunmama ilkesi (Non-Destructive):
UYAP dosyalarını salt-okunur modda bellekte okur ve belirlenen kişisel veri kategorilerini
maskeler. Olay örgüsü, tarihler, para tutarları, mahkeme/esas numaraları, kanun maddeleri,
anne/baba adları, kurum/şirket adları, Ticaret Sicil numaraları, kurum adresleri ve
avukat/vekil/bilirkişi adları korunur. Varsayılan olarak hem taraf/tanık ad-soyadları
([DAVACI_n], [TANIK_n], [KİŞİ_n] …) hem de yargı görevlilerinin (hâkim/savcı/kâtip)
ad-soyadları ([HAKİM_n], [SAVCI_n], [KÂTİP_n]) tutarlı takma adlarla maskelenir. İsteğe bağlı
olarak --taraf-isimlerini-koru (veya eski --isimleri-koru) ile taraf/tanık adları,
--yargi-isimlerini-koru ile yargı görevlisi adları açık bırakılabilir.

Hedef kişisel veri kategorileri (export'ta tutarlı numaralı etiket; registry'siz çağrıda eski etiket):
1. T.C. Kimlik No / YKN (10 hane yazım hatalı TCKN dahil) -> [TCKN_n]     / [TCKN_GİZLENDİ]
2. Türkiye cep telefonu (05xx, +90 5xx vb.)                -> [TEL_n]      / [TELEFON_GİZLENDİ]
3. Kimlik kartı seri no (yeni/eski)                        -> [SERİ_NO_n]  / [SERİ_NO_GİZLENDİ]
4. Kimlik kartı ve pasaport ICAO/MRZ şeritleri             -> [MRZ_n]      / [KİMLİK_MRZ_KODU_GİZLENDİ]
5. IBAN                                                    -> [IBAN_n]     / [IBAN_GİZLENDİ]
6. Banka kartı no                                          -> [KART_n]     / [KART_NO_GİZLENDİ]
7. Banka hesap / müşteri no (hesap bağlamında)             -> [HESAP_n]    / [HESAP_NO_GİZLENDİ]
8. Kişiye ait açık adres                                   -> [ADRES_n]    / [ADRES_GİZLENDİ]
9. Sicil no (hâkim/savcı/kâtip/kolluk/bilirkişi/baro/SGK)  -> [SİCİL_n]    / [SİCİL_GİZLENDİ]
10. Yargı görevlisi ad-soyadı (varsayılan maskeli)         -> [HAKİM_n] / [SAVCI_n] / [KÂTİP_n]
    Taraf/tanık ad-soyadı (varsayılan maskeli)             -> [DAVACI_n], [TANIK_n], [KİŞİ_n] ...

İzole temiz klasör: dava klasöründen yalnızca maskelenmiş .md evraklarından oluşan, taranmış
ekleri yerel Apple Vision OCR ile metne döken ve INDEX.md karakter sayılarını güncelleyen ayrı
bir klasör üretir. Orijinal dosyalara dokunmaz. Kural tabanlı maskeleme hatasız değildir.
"""

import os
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
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


_FOLD_TR_TABLE = str.maketrans({
    "ı": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c",
    "â": "a", "î": "i", "û": "u",
})


def _fold_tr(x: str) -> str:
    """Türkçe-küçük harf ve aksan katlamalı normalizasyon (ı->i, ş->s, ğ->g, ü->u, ö->o, ç->c, â->a, î->i, û->u)."""
    return _tr_lower(unicodedata.normalize("NFC", x)).translate(_FOLD_TR_TABLE)


class MaskRegistry:
    """
    Tutarlı numaralı maske etiketleri üretir: aynı değer her belgede aynı etikete
    ([TCKN_1], [IBAN_2], [ADRES_3], [DAVACI_1], [TANIK_2] ...) dönüşür; farklı değerler
    farklı numara alır. Numara, değerin ilk görülme sırasına göre verilir.

    GÜVENLİK: TCKN, IBAN, telefon, adres, sicil ve kişi ad-soyad dahil HİÇBİR
    değer-etiket eşlemesi asla diske/dosyaya yazılmaz; yalnızca işlem sırasında
    bellekte tutulur. `person_map()` yalnızca bellek içi bir sözlük döndürür.
    """

    JUDICIAL_ROLES = frozenset({"HAKİM", "SAVCI", "KÂTİP"})

    PERSON_ROLES = (
        "DAVACI", "DAVALI", "MÜŞTEKİ", "ŞÜPHELİ", "SANIK", "ASÇ",
        "KATILAN", "MAĞDUR", "TANIK", "ALACAKLI", "BORÇLU",
        "HAKİM", "SAVCI", "KÂTİP",
        "KİŞİ",
    )

    _ROLE_ALIAS_MAP = {
        "davaci": "DAVACI", "davacilar": "DAVACI", "karsi davaci": "DAVACI", "karsi davacilar": "DAVACI",
        "asil davaci": "DAVACI",
        "davali": "DAVALI", "davalilar": "DAVALI", "karsi davali": "DAVALI", "karsi davalilar": "DAVALI",
        "asil davali": "DAVALI",
        "musteki": "MÜŞTEKİ", "mustekiler": "MÜŞTEKİ",
        "sikayetci": "MÜŞTEKİ", "sikayetciler": "MÜŞTEKİ",
        "muracaatci": "MÜŞTEKİ", "muracaatcilar": "MÜŞTEKİ",
        "supheli": "ŞÜPHELİ", "supheliler": "ŞÜPHELİ",
        "sanik": "SANIK", "saniklar": "SANIK",
        "asc": "ASÇ", "a s c": "ASÇ", "adli surecteki cocuk": "ASÇ", "adli surecteki cocuklar": "ASÇ",
        "ssc": "ASÇ", "s s c": "ASÇ", "suca suruklenen cocuk": "ASÇ", "suca suruklenen cocuklar": "ASÇ",
        "katilan": "KATILAN", "katilanlar": "KATILAN",
        "mudahil": "KATILAN", "mudahiller": "KATILAN",
        "asli mudahil": "KATILAN", "feri mudahil": "KATILAN",
        "magdur": "MAĞDUR", "magdurlar": "MAĞDUR",
        "suctan zarar goren": "MAĞDUR", "suctan zarar gorenler": "MAĞDUR",
        "tanik": "TANIK", "taniklar": "TANIK",
        "alacakli": "ALACAKLI", "alacaklilar": "ALACAKLI",
        "borclu": "BORÇLU", "borclular": "BORÇLU",
        "hakim": "HAKİM", "hakimi": "HAKİM", "hakimler": "HAKİM",
        "uye hakim": "HAKİM", "hakim uye": "HAKİM",
        "baskan hakim": "HAKİM", "hakim baskan": "HAKİM",
        "savci": "SAVCI", "savcisi": "SAVCI",
        "cumhuriyet savcisi": "SAVCI", "c savcisi": "SAVCI",
        "sorusturma savcisi": "SAVCI", "nobetci savci": "SAVCI",
        "nobetci cumhuriyet savcisi": "SAVCI", "bilisim suclari savcisi": "SAVCI",
        "bassavci": "SAVCI", "bassavcisi": "SAVCI",
        "cumhuriyet bassavcisi": "SAVCI",
        "savci vekili": "SAVCI", "cumhuriyet savci vekili": "SAVCI",
        "bassavci vekili": "SAVCI", "cumhuriyet bassavci vekili": "SAVCI",
        "katip": "KÂTİP", "katibi": "KÂTİP",
        "zabit katibi": "KÂTİP", "z katibi": "KÂTİP", "durusma katibi": "KÂTİP",
        "kisi": "KİŞİ", "diger": "KİŞİ", "kucuk": "KİŞİ", "kisitli": "KİŞİ",
        "kisitli adayi": "KİŞİ", "kayyim": "KİŞİ", "kayyim adayi": "KİŞİ",
        "vasi": "KİŞİ", "vasi adayi": "KİŞİ", "mirasci": "KİŞİ", "mirascilar": "KİŞİ",
    }

    # "BAŞKAN" / "ÜYE" genel metinde şirket/dernek başkanı olabileceği için yalnızca başlık ve imza bağlamında yargı sayılır.
    _JUDICIAL_HEADER_ALIASES = {
        "baskan": "HAKİM",
        "mahkeme baskani": "HAKİM",
        "heyet baskani": "HAKİM",
        "uye": "HAKİM",
    }

    _UPPER_CHAR_MAP = {
        "a": "AÂ", "c": "CÇ", "g": "GĞ", "i": "IİÎ", "o": "OÖ", "s": "SŞ", "u": "UÜÛ",
    }
    _LOWER_CHAR_MAP = {
        "a": "aâ", "c": "cç", "g": "gğ", "i": "iıî", "o": "oö", "s": "sş", "u": "uüû",
    }

    PREFIX = {
        "tckn": "TCKN", "iban": "IBAN", "kart": "KART", "hesap": "HESAP",
        "telefon": "TEL", "seri_no": "SERİ_NO", "mrz": "MRZ", "sicil": "SİCİL", "adres": "ADRES",
        "kisi": "KİŞİ",
    }

    _ADDR_ABBR = {
        "mahallesi": "mah", "mahalle": "mah", "mah": "mah", "mh": "mah",
        "caddesi": "cad", "cadde": "cad", "cad": "cad", "cd": "cad",
        "sokağı": "sk", "sokagi": "sk", "sokak": "sk", "sok": "sk", "sk": "sk", "5k": "sk",
        "numara": "no", "numaralı": "no", "no": "no", "ne": "no", "nu": "no",
        "daire": "d", "d": "d", "da": "d", "kat": "k", "k": "k",
    }

    def __init__(self, known_tckns: Optional[Set[str]] = None):
        self._labels: Dict[Tuple[str, str], str] = {}
        self._next: Counter = Counter()
        self._known_tckns: Set[str] = {t for t in (known_tckns or ()) if len(t) == 11 and t.isdigit()}
        self._addr_keys: List[Tuple[str, str]] = []  # (normalize anahtar, etiket)
        self.occurrences: Counter = Counter()          # tür -> maskelenen yer sayısı
        self._seed: Dict[str, Set[str]] = {}            # ön taramada öğrenilen değerler (bellek içi)
        # Kişi ad-soyad kaydı (ön taramada toplanır, freeze_persons() sonrası sabitlenir)
        self._person_roles: Dict[str, Counter] = {}
        self._person_display: Dict[str, str] = {}
        self._person_tokens: Dict[str, Tuple[str, ...]] = {}
        self._person_given_last: Dict[str, Tuple[str, str]] = {}
        self._person_order: List[str] = []
        self._person_labels: Dict[str, str] = {}
        self._person_final_role: Dict[str, str] = {}
        self._person_role_counts: Counter = Counter()
        self._persons_frozen: bool = False
        self._compiled_name_re: Optional[re.Pattern] = None
        self._compiled_path_name_re: Optional[re.Pattern] = None
        self._person_all_caps: Set[str] = set()
        self._person_strong: Set[str] = set()
        self._person_tckns: Dict[str, Set[str]] = {}
        self._person_aliases: Dict[str, Set[Tuple[str, ...]]] = {}
        self._variant_to_label: Dict[Tuple[str, ...], str] = {}
        self._abbrev_to_label: Dict[Tuple[str, str], str] = {}
        self._honorific_to_label: Dict[str, str] = {}

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
        norm_toks: List[str] = []
        for idx, t in enumerate(toks):
            if t == "n" and idx + 1 < len(toks) and toks[idx + 1].isdigit():
                norm_toks.append("no")
            else:
                norm_toks.append(cls._ADDR_ABBR.get(t, t))
        toks = norm_toks
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
        if kind == "kisi":
            return len(self._person_labels)
        return self._next[kind]

    # -- Kişi (Ad-Soyad) kaydı ------------------------------------------------
    @staticmethod
    def person_key(full_name: str) -> str:
        """Kişi anahtarı: Türkçe-küçük harf + aksan katlamalı; 2 belirteçte ters sıra aynı kişi sayılır."""
        toks = _fold_tr(full_name).split()
        if len(toks) == 2:
            toks = sorted(toks)
        return " ".join(toks)

    @classmethod
    def normalize_person_role(cls, role: Optional[str], include_judicial_headers: bool = False) -> Optional[str]:
        """Belgedeki taraf veya yargı sıfatını kanonik rol etiketine eşler; bilinmiyorsa None."""
        if not role:
            return None
        cleaned = re.sub(r'[\s\-_/.]+', ' ', _fold_tr(role)).strip()
        if not cleaned:
            return None
        if cleaned in cls._ROLE_ALIAS_MAP:
            return cls._ROLE_ALIAS_MAP[cleaned]
        if include_judicial_headers and cleaned in cls._JUDICIAL_HEADER_ALIASES:
            return cls._JUDICIAL_HEADER_ALIASES[cleaned]
        upper = unicodedata.normalize("NFC", role.strip()).upper()
        if upper in cls.PERSON_ROLES:
            return upper
        return None

    @classmethod
    def is_judicial_label(cls, label: Optional[str]) -> bool:
        """Etiketin yargı personeli rolüne ([HAKİM_n], [SAVCI_n], [KÂTİP_n]) ait olup olmadığını döner."""
        return bool(label and (label.startswith("[HAKİM_") or label.startswith("[SAVCI_") or label.startswith("[KÂTİP_")))

    def is_person_registered(self, full_name: str) -> bool:
        """Aday ad-soyadın zaten kayıtlı bir kişiyle (aksan/büyük-küçük/SOYAD-Ad duyarsız) eşleşip eşleşmediğini döner."""
        clean = " ".join(unicodedata.normalize("NFC", full_name).strip().split())
        if not clean:
            return False
        ftoks = tuple(_fold_tr(t) for t in clean.split())
        if not (2 <= len(ftoks) <= 4):
            return False
        if len(ftoks) == 2:
            return " ".join(sorted(ftoks)) in self._person_roles
        direct_k = " ".join(ftoks)
        if direct_k in self._person_roles:
            return True
        fwd_k = " ".join(ftoks[1:] + (ftoks[0],))
        if fwd_k in self._person_roles:
            return True
        rot_k = " ".join((ftoks[-1],) + ftoks[:-1])
        return rot_k in self._person_all_caps

    def add_person(
        self,
        full_name: str,
        role: Optional[str] = None,
        strong: bool = False,
        tckn: Optional[str] = None,
    ) -> None:
        """Ön taramada keşfedilen kişiyi ve rolünü kaydeder. freeze_persons() sonrası etkisizdir."""
        if self._persons_frozen:
            return
        clean = " ".join(unicodedata.normalize("NFC", full_name).strip().split())
        if not clean:
            return
        raw_toks = clean.split()
        ftoks = tuple(_fold_tr(t) for t in raw_toks)
        if not (2 <= len(ftoks) <= 4):
            return
        all_caps = all(t.isupper() for t in raw_toks)
        canon_toks = ftoks
        is_surname_first = False
        if len(ftoks) == 2:
            k = " ".join(sorted(ftoks))
        else:
            direct_k = " ".join(ftoks)
            fwd_toks = ftoks[1:] + (ftoks[0],)
            fwd_k = " ".join(fwd_toks)
            rot_prev_k = " ".join((ftoks[-1],) + ftoks[:-1])
            first_all_upper = (
                len(raw_toks[0]) >= 2 and raw_toks[0].isupper()
                and any(not t.isupper() for t in raw_toks[1:])
            )
            if direct_k in self._person_roles:
                k = direct_k
                canon_toks = self._person_tokens[k]
                if not all_caps:
                    self._person_all_caps.discard(k)
            elif fwd_k in self._person_roles:
                k = fwd_k
                canon_toks = self._person_tokens[k]
                is_surname_first = True
            elif first_all_upper:
                k = fwd_k
                canon_toks = fwd_toks
                is_surname_first = True
            elif not all_caps and rot_prev_k in self._person_all_caps and direct_k not in self._person_roles:
                # Daha önce TÜMÜ BÜYÜK "SOYAD AD1 AD2" gelmişse normal sıraya ("Ad1 Ad2 Soyad") taşı
                idx_old = self._person_order.index(rot_prev_k)
                self._person_order[idx_old] = direct_k
                self._person_roles[direct_k] = self._person_roles.pop(rot_prev_k)
                self._person_display[direct_k] = clean
                self._person_tokens[direct_k] = ftoks
                self._person_given_last[direct_k] = (ftoks[0], ftoks[-1])
                self._person_all_caps.discard(rot_prev_k)
                if rot_prev_k in self._person_strong:
                    self._person_strong.discard(rot_prev_k)
                    self._person_strong.add(direct_k)
                if rot_prev_k in self._person_tckns:
                    self._person_tckns[direct_k] = self._person_tckns.pop(rot_prev_k)
                k = direct_k
            else:
                k = direct_k
                if all_caps:
                    self._person_all_caps.add(k)

        if k not in self._person_roles:
            self._person_roles[k] = Counter()
            self._person_display[k] = clean
            self._person_tokens[k] = canon_toks
            self._person_order.append(k)
        elif not is_surname_first and not all_caps:
            # İlk kayıt "SOYAD Ad1 Ad2" idiyse ve şimdi normal yazım geldiyse gösterimi normalleştir
            prev_toks = self._person_display[k].split()
            if len(prev_toks) >= 3 and prev_toks[0].isupper() and not raw_toks[0].isupper():
                self._person_display[k] = clean

        # "SOYAD Ad" / "SOYAD Ad1 Ad2" biçimini ayırt et
        if len(raw_toks) == 2 and raw_toks[0].isupper() and not raw_toks[1].isupper():
            self._person_given_last.setdefault(k, (ftoks[1], ftoks[0]))
        elif len(raw_toks) == 2 and not raw_toks[0].isupper():
            self._person_given_last[k] = (ftoks[0], ftoks[1])
        else:
            self._person_given_last.setdefault(k, (canon_toks[0], canon_toks[-1]))

        if strong:
            self._person_strong.add(k)
        if tckn:
            self._person_tckns.setdefault(k, set()).add(tckn)

        norm_role = self.normalize_person_role(role)
        if norm_role and norm_role != "KİŞİ":
            self._person_roles[k][norm_role] += 1

    def remove_person(self, key: str) -> None:
        """freeze_persons() öncesinde yanlış ad adayını (ör. tüzel kişilik) kayıttan çıkarır."""
        if self._persons_frozen or key not in self._person_roles:
            return
        self._person_roles.pop(key, None)
        self._person_display.pop(key, None)
        self._person_tokens.pop(key, None)
        self._person_given_last.pop(key, None)
        self._person_all_caps.discard(key)
        self._person_strong.discard(key)
        self._person_tckns.pop(key, None)
        self._person_aliases.pop(key, None)
        if key in self._person_order:
            self._person_order.remove(key)

    def keep_only_roles(self, roles: Set[str]) -> None:
        """freeze_persons() öncesinde yalnızca izin verilen rollerde oyu bulunan kişileri tutar."""
        if self._persons_frozen:
            return
        allowed = set(roles)
        for k in list(self._person_order):
            counts = self._person_roles.get(k)
            if not counts:
                self.remove_person(k)
                continue
            filtered = Counter({r: c for r, c in counts.items() if r in allowed and c > 0})
            if not filtered:
                self.remove_person(k)
            else:
                self._person_roles[k] = filtered

    def remove_roles(self, roles: Set[str]) -> None:
        """freeze_persons() öncesinde verilen rollerdeki oyları siler; başka oyu kalmayan kişiyi kayıttan çıkarır."""
        if self._persons_frozen:
            return
        blocked = set(roles)
        for k in list(self._person_order):
            counts = self._person_roles.get(k)
            if not counts:
                continue
            if any(r in blocked for r in counts):
                filtered = Counter({r: c for r, c in counts.items() if r not in blocked and c > 0})
                if not filtered:
                    self.remove_person(k)
                else:
                    self._person_roles[k] = filtered

    @classmethod
    def _upper_char_cls(cls, ch: str) -> str:
        return "[" + cls._UPPER_CHAR_MAP.get(ch, ch.upper()) + "]"

    @classmethod
    def _lower_char_cls(cls, ch: str) -> str:
        return "[" + cls._LOWER_CHAR_MAP.get(ch, ch.lower()) + "]"

    @classmethod
    def _token_rx(cls, ftok: str) -> str:
        head = cls._upper_char_cls(ftok[0])
        if len(ftok) == 1:
            return head
        tail_l = "".join(cls._lower_char_cls(c) for c in ftok[1:])
        tail_u = "".join(cls._upper_char_cls(c) for c in ftok[1:])
        return f"{head}(?:{tail_l}|{tail_u})"

    def _build_name_matcher(self) -> None:
        """Kayıtlı kişiler için derlenmiş regexleri (metin ve yol parçası) ve O(1) eşleme tablolarını oluşturur."""
        self._variant_to_label = {}
        self._abbrev_to_label = {}
        self._honorific_to_label = {}
        self._compiled_name_re = None
        self._compiled_path_name_re = None
        if not self._person_labels:
            return

        # 1. Tam adlar
        for k in self._person_order:
            lab = self._person_labels[k]
            ftoks = self._person_tokens[k]
            self._variant_to_label.setdefault(ftoks, lab)

        # 1b. Birleştirilen kısa takma adlar (ör. Nüfus'ta 3 kelimeli çocukla birleşen 2 ön ad)
        for k in self._person_order:
            lab = self._person_labels[k]
            for atoks in self._person_aliases.get(k, ()):
                self._variant_to_label.setdefault(atoks, lab)

        # 2. 2 belirteçli adlarda ters sıra ("YILMAZ Ahmet")
        for k in self._person_order:
            lab = self._person_labels[k]
            ftoks = self._person_tokens[k]
            if len(ftoks) == 2:
                rev = (ftoks[1], ftoks[0])
                self._variant_to_label.setdefault(rev, lab)

        # 2b. 3-4 belirteçli adlarda tekil "SOYAD Ad1 Ad2" dönüşü (rastgele permütasyon yok, çakışma yoksa)
        rot_counts: Counter = Counter()
        rot_map: Dict[Tuple[str, ...], str] = {}
        for k in self._person_order:
            ftoks = self._person_tokens[k]
            if 3 <= len(ftoks) <= 4:
                rot = (ftoks[-1],) + ftoks[:-1]
                rot_counts[rot] += 1
                rot_map[rot] = self._person_labels[k]
        for rot, cnt in rot_counts.items():
            if cnt == 1 and rot not in self._variant_to_label:
                self._variant_to_label[rot] = rot_map[rot]

        # 3. Orta ad düşmüş biçim (3+ belirteçli kişide ilk + son ve ters sıra, yalnızca tekilse)
        mid_counts: Counter = Counter()
        mid_map: Dict[Tuple[str, str], str] = {}
        for k in self._person_order:
            ftoks = self._person_tokens[k]
            if len(ftoks) >= 3:
                pair = (ftoks[0], ftoks[-1])
                mid_counts[pair] += 1
                mid_map[pair] = self._person_labels[k]
        for pair, cnt in mid_counts.items():
            if cnt == 1:
                if pair not in self._variant_to_label:
                    self._variant_to_label[pair] = mid_map[pair]
                rev_pair = (pair[1], pair[0])
                if rev_pair not in self._variant_to_label and mid_counts.get(rev_pair, 0) == 0:
                    self._variant_to_label[rev_pair] = mid_map[pair]

        # 4. Kısaltılmış ön ad ("A. Yılmaz"): yalnızca baş harf + soyad tek kişiye denk geliyorsa
        abbr_counts: Counter = Counter()
        abbr_map: Dict[Tuple[str, str], str] = {}
        for k in self._person_order:
            given, last = self._person_given_last[k]
            abbr_key = (given[0], last)
            abbr_counts[abbr_key] += 1
            abbr_map[abbr_key] = self._person_labels[k]
        for abbr_key, cnt in abbr_counts.items():
            if cnt == 1:
                self._abbrev_to_label[abbr_key] = abbr_map[abbr_key]

        # 5. Ön ad + Bey/Hanım ("Orhan Bey", "Selin Hanım"): ilk belirteç tekilse
        first_counts: Counter = Counter()
        first_map: Dict[str, str] = {}
        for k in self._person_order:
            given, _ = self._person_given_last[k]
            if len(given) >= 2:
                first_counts[given] += 1
                first_map[given] = self._person_labels[k]
        for first_tok, cnt in first_counts.items():
            if cnt == 1:
                self._honorific_to_label[first_tok] = first_map[first_tok]

        # Uzun adlar önce eşleştirilir (iç içe eşleşme olmasın)
        sorted_variants = sorted(
            self._variant_to_label.keys(),
            key=lambda vt: (-len(vt), -sum(len(t) for t in vt), vt),
        )
        sorted_abbrs = sorted(
            self._abbrev_to_label.keys(),
            key=lambda ak: (-len(ak[1]), ak[1], ak[0]),
        )
        sorted_honorifics = sorted(
            self._honorific_to_label.keys(),
            key=lambda ft: (-len(ft), ft),
        )
        boundary_chars = "A-Za-zÇĞİÖŞÜçğıöşüâîûÂÎÛ0-9"

        def _compile_for_sep(
            tok_sep: str,
            abbr_sep: str,
            include_honorifics: bool = False,
            hon_sep: str = r"[ \t]+",
        ) -> Optional[re.Pattern]:
            pats: List[str] = [tok_sep.join(self._token_rx(t) for t in vt) for vt in sorted_variants]
            for first_ch, last_ftok in sorted_abbrs:
                pats.append(rf"{self._upper_char_cls(first_ch)}\.{abbr_sep}{self._token_rx(last_ftok)}")
            if include_honorifics:
                for first_ftok in sorted_honorifics:
                    pats.append(rf"{self._token_rx(first_ftok)}{hon_sep}(?:[Bb][Ee][Yy]|[Hh][Aa][Nn][Iİıi][Mm])")
            if not pats:
                return None
            return re.compile(rf"(?<![{boundary_chars}])(?:{'|'.join(pats)})(?![{boundary_chars}])")

        self._compiled_name_re = _compile_for_sep(
            r"(?:[ \t]+|[ \t]*\r?\n[ \t]*)",
            r"[ \t]*",
            include_honorifics=True,
            hon_sep=r"[ \t]+",
        )
        self._compiled_path_name_re = _compile_for_sep(r"[ \t_.\-]+", r"[ \t_.\-]*", include_honorifics=False)

    def _merge_two_token_persons(self) -> None:
        """
        2 belirteçli aday X, kayıtlı 3-4 belirteçli TAM OLARAK BİR kişinin (ilk, son)
        belirteçlerine (düz veya ters sıra) eşitse X'i o kişiye birleştirir.
        Her ikisi de C kalıbıyla farklı TCKN'lere bağlıysa ya da birden çok uzun ad
        eşleşiyorsa birleştirme yapılmaz.
        """
        long_by_pair: Dict[Tuple[str, str], List[str]] = {}
        for lk in self._person_order:
            ftoks = self._person_tokens.get(lk, ())
            if 3 <= len(ftoks) <= 4:
                pair = tuple(sorted((ftoks[0], ftoks[-1])))
                long_by_pair.setdefault(pair, []).append(lk)
                pref_pair = tuple(sorted((ftoks[0], ftoks[1])))
                if pref_pair != pair:
                    long_by_pair.setdefault(pref_pair, []).append(lk)

        if not long_by_pair:
            return

        for xk in list(self._person_order):
            xtoks = self._person_tokens.get(xk, ())
            if len(xtoks) != 2:
                continue
            pair = tuple(sorted(xtoks))
            cands = long_by_pair.get(pair, [])
            if len(cands) != 1:
                continue
            lk = cands[0]
            # Farklı açık taraf rollerine sahip kişiler (örn. DAVACI vs TANIK) birleştirilmez
            x_roles = {r for r in self._person_roles.get(xk, ()) if r != "KİŞİ"}
            l_roles = {r for r in self._person_roles.get(lk, ()) if r != "KİŞİ"}
            if x_roles and l_roles and x_roles.isdisjoint(l_roles):
                continue
            x_tckns = self._person_tckns.get(xk)
            l_tckns = self._person_tckns.get(lk)
            if x_tckns and l_tckns and x_tckns.isdisjoint(l_tckns):
                continue

            # Rol oyları, güçlü kanıt, TCKN ve en erken görülme sırasını aktar
            self._person_roles[lk].update(self._person_roles[xk])
            if xk in self._person_strong:
                self._person_strong.add(lk)
            if x_tckns:
                self._person_tckns.setdefault(lk, set()).update(x_tckns)
            aliases = self._person_aliases.setdefault(lk, set())
            aliases.add(xtoks)
            aliases.update(self._person_aliases.get(xk, ()))
            idx_x = self._person_order.index(xk)
            idx_l = self._person_order.index(lk)
            if idx_x < idx_l:
                self._person_order.remove(lk)
                self._person_order.insert(idx_x, lk)
            self.remove_person(xk)

    def freeze_persons(self) -> None:
        """Kişi etiketlerini yargı rolü önceliği, rol çoğunluğu ve ilk görülme sırasına göre sabitler."""
        if self._persons_frozen:
            return
        self._merge_two_token_persons()
        role_prio = {r: idx for idx, r in enumerate(self.PERSON_ROLES)}
        for k in self._person_order:
            counts = self._person_roles[k]
            role = (
                max(
                    counts.keys(),
                    key=lambda r: (1 if r in self.JUDICIAL_ROLES else 0, counts[r], -role_prio.get(r, 999)),
                )
                if counts else "KİŞİ"
            )
            self._person_role_counts[role] += 1
            lab = f"[{role}_{self._person_role_counts[role]}]"
            self._person_labels[k] = lab
            self._person_final_role[k] = role
        self._persons_frozen = True
        self._build_name_matcher()

    def person_label(self, key: str) -> Optional[str]:
        """Kişi anahtarı veya ham ad-soyad için atanmış etiketi döndürür."""
        if key in self._person_labels:
            return self._person_labels[key]
        lab = self._person_labels.get(self.person_key(key))
        if lab is not None:
            return lab
        toks = tuple(_fold_tr(key).split())
        return self._variant_to_label.get(toks)

    def has_persons(self) -> bool:
        """Sabitlenmiş en az bir kişi kaydı var mı?"""
        return bool(self._person_labels)

    def person_count_by_role(self) -> Dict[str, int]:
        """Rol -> takma ad verilen kişi sayısı."""
        return dict(self._person_role_counts)

    _KISI_LIST_ROLE_ORDER = {
        r: idx for idx, r in enumerate((
            "DAVACI", "DAVALI", "MÜŞTEKİ", "KATILAN", "MAĞDUR",
            "ŞÜPHELİ", "SANIK", "ALACAKLI", "BORÇLU", "TANIK", "KİŞİ",
            "HAKİM", "SAVCI", "KÂTİP",
        ))
    }

    def person_map(self) -> Dict[str, str]:
        """Yalnızca bellek içi kişi eşlemesini ({etiket: ilk görülen yazımıyla Ad Soyad}) rol sırasına göre döndürür."""
        def _sort_key(k: str) -> Tuple[int, int]:
            role = self._person_final_role.get(k, "KİŞİ")
            lab = self._person_labels[k]
            try:
                num = int(lab.rsplit("_", 1)[1][:-1])
            except (IndexError, ValueError):
                num = 0
            return (self._KISI_LIST_ROLE_ORDER.get(role, 999), num)

        ordered_keys = sorted((k for k in self._person_order if k in self._person_labels), key=_sort_key)
        return {self._person_labels[k]: self._person_display[k] for k in ordered_keys}


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

    PERSON_ROLES = MaskRegistry.PERSON_ROLES
    _PERSON_ROLES_RE_ALT = "|".join(PERSON_ROLES)

    # Hem eski sabit hem numaralı etiketleri tanıyan kalıplar
    MASK_ADRES_RE = r'\[ADRES_(?:GİZLENDİ|\d+)\]'
    MASK_TCKN_RE = r'\[TCKN_(?:GİZLENDİ|\d+)\]'
    PERSON_LABEL_RE = r'\[(?:' + _PERSON_ROLES_RE_ALT + r')_\d+\]'
    MASK_ANY_RE = (
        r'\[(?:[A-ZÇĞİÖŞÜ_]+_GİZLENDİ|(?:TCKN|IBAN|KART|HESAP|TEL|SERİ_NO|MRZ|SİCİL|ADRES|'
        + _PERSON_ROLES_RE_ALT
        + r')_\d+)\]'
    )

    # Türkiye'nin 81 ili (kanonik Türkçe yazım) ve eski/alternatif yazımlar
    _IL_ADLARI: Tuple[str, ...] = (
        "Adana", "Adıyaman", "Afyonkarahisar", "Ağrı", "Aksaray", "Amasya", "Ankara",
        "Antalya", "Ardahan", "Artvin", "Aydın", "Balıkesir", "Bartın", "Batman",
        "Bayburt", "Bilecik", "Bingöl", "Bitlis", "Bolu", "Burdur", "Bursa",
        "Çanakkale", "Çankırı", "Çorum", "Denizli", "Diyarbakır", "Düzce", "Edirne",
        "Elazığ", "Erzincan", "Erzurum", "Eskişehir", "Gaziantep", "Giresun",
        "Gümüşhane", "Hakkari", "Hatay", "Iğdır", "Isparta", "İstanbul", "İzmir",
        "Kahramanmaraş", "Karabük", "Karaman", "Kars", "Kastamonu", "Kayseri",
        "Kırıkkale", "Kırklareli", "Kırşehir", "Kilis", "Kocaeli", "Konya",
        "Kütahya", "Malatya", "Manisa", "Mardin", "Mersin", "Muğla", "Muş",
        "Nevşehir", "Niğde", "Ordu", "Osmaniye", "Rize", "Sakarya", "Samsun",
        "Siirt", "Sinop", "Sivas", "Şanlıurfa", "Şırnak", "Tekirdağ", "Tokat",
        "Trabzon", "Tunceli", "Uşak", "Van", "Yalova", "Yozgat", "Zonguldak",
    )
    _IL_ES_ANLAM: Dict[str, str] = {
        "afyon": "Afyonkarahisar",
        "urfa": "Şanlıurfa",
        "maraş": "Kahramanmaraş",
        "antep": "Gaziantep",
        "içel": "Mersin",
        "izmit": "Kocaeli",
        "adapazarı": "Sakarya",
    }
    _IL_CANON_MAP: Dict[str, str] = {
        **{_fold_tr(il): il for il in _IL_ADLARI},
        **{_fold_tr(k): v for k, v in _IL_ES_ANLAM.items()},
        **{_tr_lower(il).replace("i", "ı", 1): il for il in _IL_ADLARI if _tr_lower(il).startswith("i")},
        **{_tr_lower(il): il for il in _IL_ADLARI},
        **_IL_ES_ANLAM,
    }
    _IL_CANON_SET = frozenset(_IL_ADLARI)
    _IL_RE = re.compile(
        r'(?<![a-zçğıöşüâîû0-9])('
        + "|".join(re.escape(k) for k in sorted(_IL_CANON_MAP, key=len, reverse=True))
        + r')(?![a-zçğıöşüâîû0-9])'
    )
    _IL_FOLLOW_STREET_WORDS = frozenset({
        "cad", "cd", "cadde", "caddesi",
        "sok", "sk", "sokak", "sokağı", "sokagi", "5k",
        "blv", "bulv", "bulvar", "bulvarı", "bulvari",
        "mah", "mh", "mahalle", "mahallesi",
        "apt", "apartman", "apartmanı", "apartmani",
        "site", "sitesi", "blok",
        "köy", "köyü", "koyu",
        "yol", "yolu",
        "mevkii", "mevki", "meydan", "meydanı", "meydani", "evleri",
    })
    _ILCE_EXCLUDE_WORDS = frozenset({
        # adres türü / yapı sözcükleri
        "mah", "mh", "mahalle", "mahallesi",
        "cad", "cd", "cadde", "caddesi",
        "sok", "sk", "sokak", "sokağı", "sokagi",
        "blv", "bulv", "bulvar", "bulvarı", "bulvari",
        "no", "nu", "ne", "numara", "numaralı", "numarali",
        "daire", "kat", "apt", "apartman", "apartmanı", "apartmani",
        "blok", "blk", "site", "sitesi", "evleri", "küme", "kume",
        "köy", "köyü", "koyu", "mevki", "mevkii", "mezra", "mezrası",
        "kapı", "kapi", "iç", "ic", "dış", "dis", "d", "k", "yol", "yolu",
        # bağlam sözcükleri
        "adres", "adresi", "adresinde", "adresine", "adresini", "adresidir",
        "ikamet", "ikametgah", "ikametgâh", "tebligat", "yeni", "açık", "acik", "işyeri", "isyeri",
        "il", "ilçe", "ilce", "ili", "ilçesi", "ilcesi",
        "ve", "ile", "veya", "ya", "da", "de", "halen", "kayıtlı", "kayitli",
        "olup", "olan", "oturur", "bulunan", "belirtilen",
    })

    @staticmethod
    def _tr_title_word(w: str) -> str:
        """Türkçe kurallarına göre tek sözcüğün baş harfini büyütür (i->İ, ı->I)."""
        if not w:
            return w
        first = w[0]
        if first in ("i", "İ"):
            head = "İ"
        elif first in ("ı", "I"):
            head = "I"
        else:
            head = first.upper()
        return head + _tr_lower(w[1:])

    @classmethod
    def _find_province_match(cls, seg: str) -> Optional[Tuple[re.Match, str]]:
        """Verilen küçük harfli parçadaki SON geçerli il eşleşmesini ve kanonik adını döndürür."""
        for m in reversed(list(cls._IL_RE.finditer(seg))):
            after = seg[m.end():].lstrip(" \t")
            m_next = re.match(r'[a-zçğıöşüâîû]+', after)
            if m_next and m_next.group(0) in cls._IL_FOLLOW_STREET_WORDS:
                continue
            return m, cls._IL_CANON_MAP[m.group(1)]
        return None

    @classmethod
    def _address_locality(cls, raw: str) -> str:
        """Maskelenen ham adresten yalnızca 'İlçe/İl' veya 'İl' ipucunu çıkarır; bulamazsa ''."""
        if not raw or not raw.strip():
            return ""
        low_full = _tr_lower(raw)
        last_num = None
        for m in re.finditer(r'\d+', low_full):
            last_num = m
        has_digit = last_num is not None
        tail = low_full[last_num.end():] if has_digit else low_full

        search_seg = tail
        found = cls._find_province_match(search_seg)
        if found is None and has_digit:
            search_seg = low_full
            found = cls._find_province_match(search_seg)
        if found is None:
            return ""

        m_prov, prov_canon = found
        pre = search_seg[:m_prov.start()]

        # "İlçe :MERKEZ İl :ANTALYA" gibi MERNİS tablo biçimi
        m_mernis = re.search(
            r'(?:^|[\s/,;\-])il[cç]e(?:s[iı])?[ \t]*[:\-][ \t]*([a-zçğıöşüâîû]+)'
            r'[ \t/,;\-]+il(?:[iı])?[ \t]*[:\-][ \t]*$',
            pre,
        )
        district_cand = ""
        if m_mernis:
            district_cand = m_mernis.group(1)
        else:
            # "Akseki İlçesi Antalya İli" -> "İlçesi" ekini atla
            pre_clean = re.sub(r'(?:^|(?<=[\s/,\-]))il[cç]e(?:s[iı])?[\s/,\-]+$', '', pre)
            m_dist = re.search(r'(?:^|(?<=[\s/,\-:\(\[]))([a-zçğıöşüâîû0-9]+)[\s/,\-]+$', pre_clean)
            if m_dist:
                district_cand = m_dist.group(1)

        if district_cand:
            if (
                any(c.isdigit() for c in district_cand)
                or len(district_cand) < 2
                or district_cand in cls._ILCE_EXCLUDE_WORDS
                or district_cand == m_prov.group(1)
                or cls._IL_CANON_MAP.get(district_cand) == prov_canon
            ):
                district_cand = ""

        if district_cand:
            return f"{cls._tr_title_word(district_cand)}/{prov_canon}"
        return prov_canon

    @classmethod
    def _format_adres_label(cls, label: str, raw: str, registry: Optional[MaskRegistry]) -> str:
        """Registry modunda adres etiketinin dışına varsa '(İlçe/İl)' ipucunu ekler."""
        if registry is None or not raw:
            return label
        loc = cls._address_locality(raw)
        return f"{label} ({loc})" if loc else label

    @classmethod
    def _mask(cls, kind: str, raw: str, registry: Optional[MaskRegistry]) -> str:
        """registry yoksa eski sabit etiketi, varsa tutarlı numaralı etiketi döndürür."""
        if registry is None:
            return cls._LEGACY_MASK[kind]
        lab = registry.label(kind, raw)
        if kind == "adres":
            return cls._format_adres_label(lab, raw, registry)
        return lab

    _SPACE_TRANS = {cp: " " for cp in (0x00A0, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006,
                                         0x2007, 0x2008, 0x2009, 0x200A, 0x202F, 0x205F, 0x3000)}
    _SPACE_TRANS.update({cp: None for cp in (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF)})

    _PCT_LINK_RE = re.compile(
        r'(\]\()(?:<([^>\n]*%[0-9A-Fa-f]{2}[^>\n]*)>|(?!<)([^)\s<>]*%[0-9A-Fa-f]{2}[^)\s<>]*))(\))'
    )

    @classmethod
    def _decode_link_targets(cls, text: str) -> str:
        """Yerel (http olmayan) %-kodlu Markdown bağlantı hedeflerini <çözülmüş yol> biçimine çevirir."""
        if not text or "%" not in text:
            return text

        def repl(m: re.Match) -> str:
            target = m.group(2) if m.group(2) is not None else m.group(3)
            if re.match(r'(?i)^(?:https?|mailto|file):', target):
                return m.group(0)
            dec = urllib.parse.unquote(target)
            if any(c in dec for c in "<>\n\r"):
                return m.group(0)
            return f"{m.group(1)}<{dec}>{m.group(4)}"

        return cls._PCT_LINK_RE.sub(repl, text)

    @classmethod
    def normalize_spaces(cls, text: str) -> str:
        """NBSP ve diğer Unicode boşlukları düz boşluğa çevirir, sıfır genişlikli karakterleri siler ve NFC normalize eder."""
        if not text:
            return text
        return unicodedata.normalize("NFC", text.translate(cls._SPACE_TRANS))

    _BASE_TR_VOCAB = frozenset(['ad', 'adet', 'adli', 'adres', 'adresi', 'adı', 'aile', 'ait', 'alacak', 'alacaklı', 'alıcı', 'alınması', 'ancak', 'anne', 'apartman', 'ara', 'aralık', 'araç', 'arz', 'asliye', 'aslı', 'asıl', 'avans', 'avukat', 'ayrıca', 'ayı', 'açıklama', 'ağustos', 'baba', 'banka', 'bankası', 'baro', 'barosu', 'başkanlığı', 'başsavcılığı', 'bedel', 'bedeli', 'bekar', 'belediye', 'belge', 'belgesi', 'bildirilmesi', 'bilgi', 'bilgileri', 'bilgilerinize', 'bilirkişi', 'bir', 'borç', 'borçlu', 'bu', 'bulvar', 'cadde', 'caddesi', 'celse', 'cevabı', 'cevap', 'ceza', 'cuma', 'cumartesi', 'cumhuriyet', 'cumhuriyeti', 'daha', 'dair', 'daire', 'dairesi', 'dava', 'davacı', 'davalı', 'dekont', 'dekontu', 'devlet', 'dilekçe', 'dilekçesi', 'diğer', 'doktor', 'dosya', 'doğum', 'durum', 'durumu', 'duruşma', 'ederim', 'edilmesi', 'ehliyet', 'ek', 'ekim', 'ekli', 'ekte', 'erkek', 'esas', 'evli', 'evrak', 'eylül', 'faiz', 'fatura', 'gelen', 'gerekçeli', 'gereği', 'gereğince', 'gereğini', 'gibi', 'gibidir', 'giden', 'gider', 'gönderen', 'gönderilmesi', 'göre', 'günü', 'haciz', 'hakim', 'hakkında', 'hali', 'harç', 'hasar', 'hastane', 'hastanesi', 'haziran', 'her', 'hesabı', 'hesap', 'hukuk', 'hususu', 'hususunda', 'hâkim', 'hükmü', 'hüküm', 'iban', 'icra', 'idare', 'ifade', 'ifadesi', 'ihale', 'ikamet', 'il', 'ilamlı', 'ilamsız', 'ile', 'ilgi', 'ilişkin', 'ilçe', 'imza', 'imzası', 'istenmesi', 'istinaf', 'itiraz', 'için', 'işlem', 'işlemi', 'kadar', 'kadın', 'kanun', 'kanunu', 'kapı', 'karar', 'kararı', 'kasım', 'kat', 'katibi', 'katip', 'kavşak', 'kavşağı', 'kaydı', 'kaymakamlığı', 'kayıt', 'kayıtlı', 'kaza', 'kazası', 'kesinleşme', 'kimlik', 'kira', 'kiracı', 'kiraya', 'kişi', 'kişinin', 'konu', 'kurumu', 'kâtip', 'madde', 'maddesi', 'mahalle', 'mahallesi', 'mahkeme', 'mahkemenizin', 'mahkemesi', 'makbuz', 'makbuzu', 'mart', 'masraf', 'mayıs', 'mazbata', 'mağdur', 'medeni', 'miktar', 'muayene', 'müdürlüğü', 'müdürlüğüne', 'mühür', 'müzekkere', 'müzekkeresi', 'müşteki', 'nisan', 'no', 'noter', 'noterliği', 'numara', 'numarası', 'nüfus', 'ocak', 'olan', 'olarak', 'olay', 'olayı', 'olunması', 'olunur', 'olup', 'onay', 'onaylı', 'oran', 'pazar', 'pazartesi', 'perşembe', 'plaka', 'plakası', 'poliçe', 'rapor', 'raporu', 'reddiyat', 'referans', 'rica', 'saat', 'salı', 'sanık', 'satış', 'savcı', 'savcılığı', 'saygılarımla', 'sayı', 'sayılı', 'sayın', 'sigorta', 'sokak', 'sokağı', 'sonra', 'sonucu', 'sonuç', 'soyad', 'soyadı', 'sulh', 'suret', 'sözleşme', 'sözleşmesi', 'sürücü', 'sınıfı', 'tahsilat', 'takibi', 'takip', 'talebi', 'talep', 'talimat', 'tanık', 'tarafına', 'tarafından', 'tarih', 'tarihinde', 'tarihli', 'tebligat', 'tebliğ', 'tedavi', 'tel', 'telefon', 'temmuz', 'temyiz', 'tensip', 'tespit', 'tespiti', 'teşhis', 'ticaret', 'toplam', 'trafik', 'tutanak', 'tutanağı', 'tutar', 'tutarı', 'tüketici', 'tüm', 'türkiye', 'tıp', 'uyarınca', 'uyruğu', 'valiliği', 've', 'vekalet', 'vekaletname', 'vekil', 'vekili', 'veren', 'verilmesi', 'veya', 'yapılması', 'yaralı', 'yasa', 'yazı', 'yazısı', 'yer', 'yeri', 'yevmiye', 'yolu', 'yolun', 'yönetmelik', 'yılı', 'zabıt', 'zaptı', 'çarşamba', 'çok', 'ödeme', 'ölü', 'önce', 'örnek', 'üzere', 'şahsın', 'şahıs', 'şu', 'şubat', 'şube', 'şüpheli'])

    SMALL_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".heic")

    @staticmethod
    def _is_small_image(path: str, max_area: int = 150_000, min_side: int = 100) -> bool:
        """Simge/logo/imza boyutundaki görseller (ör. 16×17, 94×29, 375×32) için True."""
        try:
            from PIL import Image
            with Image.open(path) as im:
                w, h = im.size
            return w * h < max_area or min(w, h) < min_side
        except Exception:
            return False

    @staticmethod
    def _source_has_md_derivative(full_p: str, src_folder: str) -> bool:
        """Kaynakta <ad>.md / <ad>.<uzantı>.md türevi (aynı dizinde veya _kaynak/ öneki
        kaldırılmış karşılığında, ≥50 bayt) varsa True."""
        rel = os.path.relpath(full_p, src_folder)
        rels = [rel]
        if rel.startswith("_kaynak" + os.sep):
            rels.append(rel[len("_kaynak" + os.sep):])
        for r in rels:
            for cand in (os.path.splitext(r)[0] + ".md", r + ".md"):
                for form in ("NFC", "NFD"):
                    p = os.path.join(src_folder, unicodedata.normalize(form, cand))
                    try:
                        if os.path.isfile(p) and os.path.getsize(p) >= 50:
                            return True
                    except OSError:
                        pass
        return False

    @classmethod
    def _has_mask(cls, s: str, kind_re: Optional[str] = None) -> bool:
        return bool(re.search(kind_re or cls.MASK_ANY_RE, s))

    # Adli/İdari Unvan listesi (Hâkim, Savcı, Kâtip, Mübaşir, Müdür ve OCR varyasyonları)
    TITLES_REGEX = (
        r'(?:Başkan|Üye|H[aâ]k[ıi]m[iı]?|Mak[ıi][nml]|'
        r'(?:(?:Cumhuriyet|Soruşturma|Nöbetçi|Bilişim\s+Suçlar[ıi])\s+)?(?:Baş)?savc[ıi](?:s[ıi])?(?:\s+Vekili?)?|'
        r'C\.\s*Savc[ıi]s[ıi]|(?:(?:Zab[ıi]t|Duru[şs]ma)\s+|Z\.\s*)?K[aâ]t[ıi][bp][iı]?|Kal[ıi]p|'
        r'Mübaş[ıi]r|Müb\.?|Yaz[ıi]\s+İşleri\s+Müdürü)(?!\w)'
    )

    # Sicil sanılmaması gereken sayı sonekleri (para birimi, "sayılı" kanun/karar, Esas/Karar no)
    NOT_SICIL_SUFFIX = r'(?!\s*(?:TL|Türk\s*Liras[ıi]|USD|EUR|say[ıi]l[ıi]|Esas|Karar)\b)'

    # Klasör taramalarında atlanacak dizin adları (yalnızca tam ad eşleşmesi)
    SKIP_DIRS = ("_kaynak", ".git", "node_modules")
    SKIP_DIRS_OCR = (".git", "node_modules")

    # Desteklenen belge / arşiv türleri ve arşiv güvenlik sınırları
    TEXT_DOC_EXTS = (".udf", ".docx", ".doc", ".xlsx")
    OFFICE_DOC_EXTS = (".docx", ".doc", ".xlsx")
    OCR_DOC_EXTS = (".pdf", ".tif", ".tiff", ".png", ".jpg", ".jpeg", ".heic")
    OCR_PRESCAN_MAX_MEM_BYTES = 200 * 1024 * 1024  # Ön tarama ham OCR bellek tavanı (200 MB)
    ARCHIVE_EXTS = (".eyp", ".zip")
    EYP_META_EXTS = (".rels", ".xml", ".psmdcp")
    IGNORED_SIG_EXTS = (".imz", ".p7s", ".sig", ".cer")
    IGNORED_BASENAMES = (".DS_Store", "Thumbs.db", "thumbs.db")
    ARCHIVE_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
    ARCHIVE_MAX_FILE_BYTES = 500 * 1024 * 1024
    ARCHIVE_MAX_MEMBERS = 5000

    # Yargı PRO manifest JSON dosyaları (değer bazında maskelenerek aktarılır)
    META_JSON_NAMES = ("uyap-project.json", "uyap-evrak-listesi.json")

    STAT_KEYS = ("tckn", "telefon", "seri_no", "mrz", "iban", "hesap", "sicil", "adres", "kisi", "total")

    _FOLDED_BASE_TR_VOCAB = frozenset(_fold_tr(w) for w in _BASE_TR_VOCAB)

    _MONTH_DAY_WORDS = frozenset({
        "ocak", "subat", "mart", "nisan", "mayis", "haziran",
        "temmuz", "agustos", "eylul", "ekim", "kasim", "aralik",
        "pazartesi", "sali", "carsamba", "persembe", "cuma", "cumartesi", "pazar",
    })

    _LEADING_DESCRIPTOR_BIGRAMS = frozenset({
        ("kiraya", "veren"), ("isveren", "vekili"), ("kayyim", "adayi"), ("kisitli", "adayi"), ("vasi", "adayi"),
        ("santiye", "sefi"), ("arac", "maliki"), ("arac", "sahibi"), ("arac", "surucusu"),
        ("genel", "mudur"), ("genel", "muduru"), ("sirket", "yetkilisi"), ("sirket", "muduru"),
    })
    _LEADING_DESCRIPTOR_WORDS = frozenset({
        "muris", "muteveffa", "merhum", "merhume", "kucuk", "muvekkil", "muvekkilim", "muvekkilimiz",
        "muvekkile", "sayin", "bay", "bayan", "esi", "kardesi", "oglu", "kizi", "annesi", "babasi",
        "hissedar", "malik", "maliki", "kiraci", "isci", "isveren", "mirasci", "kisitli", "velisi", "vasisi", "kayyimi",
        "surucu", "yetkili", "yetkilisi", "isleten", "isleteni", "kefil", "kefili", "borclusu",
    })

    _PERSON_STOP_WORDS = frozenset({
        "davaci", "davacilar", "davali", "davalilar", "vekili", "vekil", "vekilleri",
        "mudafii", "mudafileri", "mudafi", "adina", "asil", "mudahil", "mudahiller",
        "tanik", "taniklar", "sanik", "saniklar", "supheli", "supheliler",
        "musteki", "mustekiler", "sikayetci", "sikayetciler", "muracaatci", "muracaatcilar",
        "magdur", "magdurlar", "katilan", "katilanlar", "alacakli", "alacaklilar",
        "borclu", "borclular", "mirasci", "mirascilari", "mirascilar", "vasi", "kayyim",
        "kucuk", "kisitli", "digerleri", "diger", "vd", "vs", "hasimsiz", "sifatiyla",
        "asc", "ssc", "adli", "surecteki", "suca", "suruklenen", "cocuk",
        "muris", "muteveffa", "merhum", "merhume", "muvekkile", "bay", "bayan", "bey", "hanim",
        "esi", "kardesi", "oglu", "kizi", "annesi", "babasi",
        "agabeyi", "ablasi", "torunu", "kayinvalidesi", "kayinpederi", "komsusu", "arkadasi", "cocugu", "musterek",
        "hissedar", "hissedari", "ortak", "ortagi", "ortaklari", "ortakligi", "paydas", "malik", "kiraci", "kiraya", "veren", "isci", "isveren",
        "kimlik", "bilgileri", "bilgisi", "adres", "adresi", "tebligat", "ikamet", "ikametgah",
        "mahkemesi", "mahkeme", "mahkememize", "mahkemesine", "mahkemeye", "mahkememiz", "mahkemeniz",
        "dosya", "esas", "karar", "karari", "tarih", "tarihi", "konu", "talep", "talebi",
        "aciklama", "aciklamalar", "hukuki", "deliller", "sonuc", "sonuclar", "istem", "sayin",
        "turkiye", "cumhuriyeti", "cumhuriyet", "kamu", "hukuku", "maliye", "hazinesi", "hazine",
        "bilinmiyor", "belirsiz", "mechul", "yok", "sayili", "bolum", "madde", "fikra", "bent",
        "geregi", "geregince", "iliskin", "hakkinda", "nedeniyle", "olarak", "tarafindan",
        "karsilik", "uzerine", "belgesi", "belge", "evrak", "tutanak", "tutanagi",
        "dilekce", "dilekcesi", "rapor", "raporu", "ilam", "ilami", "muzekkere", "muzekkeresi",
        "ptt", "teslimat", "gonderi", "barkod", "kargo", "mazbata", "mazbatasi",
        "cevap", "cevabi", "itiraz", "istinaf", "temyiz", "durusma", "celse", "tensip",
        "tedbir", "haciz", "icra", "ifade", "ifadesi", "sahsin", "sahis", "kisi", "kisinin",
        "kisiler", "taraflar", "taraf", "muvekkil", "muvekkilim", "muvekkilimiz",
        "alacak", "tazminat", "davasi", "dava", "haksiz", "fiil", "hukuk", "ceza",
        "asliye", "sulh", "agir", "bolge", "adliye", "yargitay", "danistay", "anayasa",
        "klasor", "klasoru", "proje", "uyap", "ad", "adi", "soyad", "soyadi", "isim", "soyisim",
        "baba", "anne", "ana", "dogum", "yeri", "nufus", "medeni", "hali", "uyrugu",
        "ve", "veya", "ile", "icin", "uzere", "gibi", "gore", "not", "notu", "layiha", "layihasi",
        "savunma", "savunmasi", "beyan", "beyani", "beyanlari", "ifadesi", "ifadeleri", "listesi", "metni",
    })

    _LEGAL_ENTITY_WORDS = frozenset({
        # Tüzel kişi / kurum işaretleri
        "as", "ltd", "sti", "inc", "corp", "llc", "banka", "bankasi", "sigorta",
        "holding", "kooperatif", "kooperatifi", "belediye", "belediyesi",
        "bakanlik", "bakanligi", "mudurluk", "mudurlugu", "baskanlik", "baskanligi",
        "kurum", "kurumu", "kurulus", "kurulusu", "universite", "universitesi",
        "fakulte", "fakultesi", "enstitu", "enstitusu", "vakif", "vakfi",
        "dernek", "dernegi", "sendika", "sendikasi", "hazine", "hazinesi", "maliye",
        "idare", "idaresi", "valilik", "valiligi", "kaymakamlik", "kaymakamligi",
        "oda", "odasi", "baro", "barosu", "hastane", "hastanesi", "poliklinigi", "klinigi",
        "saglik", "merkezi", "merkez", "insaat", "ticaret", "sanayi", "turizm",
        "nakliyat", "lojistik", "otomotiv", "gida", "tekstil", "yazilim", "teknoloji",
        "enerji", "elektrik", "muhendislik", "danismanlik", "musavirlik", "emlak",
        "gayrimenkul", "yatirim", "finans", "ithalat", "ihracat", "pazarlama", "dagitim",
        "uretim", "petrol", "akaryakit", "kimya", "maden", "madencilik", "tarim",
        "hayvancilik", "mobilya", "iletisim", "telekomunikasyon", "medya", "yayincilik",
        "matbaa", "egitim", "ogretim", "koleji", "okullari", "okulu", "lisesi", "lise",
        "okul", "sirket", "sirketi", "ortakligi", "komandit", "kollektif", "anonim", "limited",
        "komutanligi", "emniyet", "jandarma", "karakolu", "bassavciligi", "savciligi",
        "mahkemesi", "mahkeme", "adliyesi", "adliye", "dairesi", "daire", "icra",
        "noterligi", "noter", "genel", "subesi", "sube", "tesisi", "tesisleri",
        "fabrikasi", "fabrika", "muteahhitlik", "taahhut", "reklam", "guvenlik",
        "temizlik", "bakim", "hizmetleri", "hizmet",
    })

    _PERSON_CORP_TITLE_WORDS = _LEGAL_ENTITY_WORDS | frozenset({
        # Görevli / avukat unvanları
        "av", "avukat", "avukati", "stj", "stajyer", "vekil", "vekili", "vekilleri",
        "mudafii", "mudafileri", "mudafi", "hakim", "hakimi", "savci", "savcisi",
        "katip", "katibi", "zabit", "mubasir", "bilirkisi", "arabulucu", "uzlastirmaci",
        "mudur", "muduru", "memur", "memuru", "kolluk", "polis", "komiser", "bekci",
        "subay", "astsubay", "doktor", "dr", "uzm", "hekim", "uzman",
        "profesor", "prof", "docent", "doc", "tercuman", "kaymakam", "vali",
        "baskan", "baskani", "mufettis", "raportor", "uye", "uyesi",
    })

    _PLACE_STRUCTURE_WORDS = frozenset({
        "mahalle", "mahallesi", "mah", "mh", "cadde", "caddesi", "cad", "cd",
        "sokak", "sokagi", "sok", "sk", "bulvar", "bulvari", "blv", "bulv",
        "koyu", "koprusu", "kavsagi", "stadi", "stadyumu",
        "ilkokul", "ilkokulu", "ortaokul", "ortaokulu", "lise", "lisesi",
        "universite", "universitesi", "fakulte", "fakultesi", "hastane", "hastanesi",
        "cami", "camii", "camisi", "meydani", "merkezi", "kultur", "kulturu",
        "tesisi", "tesisleri", "sitesi", "apartman", "apartmani", "apt",
        "ishani", "plaza", "konutlari", "evleri",
    })

    _MASK_AFTER_PLACE_CORP_WORDS = frozenset({
        "cadde", "caddesi", "cad", "cd", "sokak", "sokagi", "sok", "sk",
        "bulvar", "bulvari", "blv", "bulv", "mahalle", "mahallesi", "mah", "mh",
        "koy", "koyu", "kopru", "koprusu", "kavsak", "kavsagi", "stadi", "stadyumu",
        "okul", "okulu", "ilkokul", "ilkokulu", "ortaokul", "ortaokulu", "lise", "lisesi",
        "universite", "universitesi", "fakulte", "fakultesi", "hastane", "hastanesi",
        "cami", "camii", "camisi", "park", "parki", "meydan", "meydani",
        "merkez", "merkezi", "tesisi", "tesisleri",
        "vakif", "vakfi", "dernek", "dernegi", "insaat", "ticaret", "sanayi", "turizm",
        "nakliyat", "lojistik", "otomotiv", "gida", "tekstil", "holding", "site", "sitesi",
        "apartman", "apartmani", "apt", "ishani", "plaza", "konutlari", "evleri",
        "ltd", "sti", "as", "anonim", "limited", "sirketi", "bankasi", "banka",
        "sigorta", "kooperatifi", "kooperatif", "belediyesi", "belediye",
        "mudurlugu", "baskanligi", "kurumu", "kurulusu", "barosu", "odasi",
        "genel", "subesi", "komutanligi", "adliyesi", "mahkemesi", "bakanligi",
        "valiligi", "kaymakamligi", "enstitusu",
    })

    _CAP_TOK_RE_STR = r'(?:[A-ZÇĞİÖŞÜÂÎÛ][a-zçğıöşüâîû]+|[A-ZÇĞİÖŞÜÂÎÛ]{2,})'
    _NON_JUDICIAL_PRE_TITLE_RE = re.compile(
        r'(?:^|[\s(\["\'*:,;\-/])'
        r'(?:Stj\.?[ \t]*Av\.?|Uzm\.?[ \t]*Dr\.?|Prof\.?(?:[ \t]*Dr\.?)?|Doç\.?(?:[ \t]*Dr\.?)?|'
        r'Av\.?|Dr\.?|Avukat|M[uü]ba[şs]ir|'
        r'Bilirki[şs]i|Arabulucu|Uzla[şs]t[ıi]rmac[ıi]|Noter|[İI]cra[ \t]+M[uü]d[uü]r[uü]?|'
        r'Tebli[ğg][ \t]+Memuru|Kolluk[ \t]+G[öo]revlisi|Memur[u]?|Komiser|Polis|Terc[uü]man|'
        r'Vekil[i]?|Vekilleri|M[uü]dafi[i]?|M[uü]dafileri)[ \t]*$',
        re.IGNORECASE,
    )
    _JUDICIAL_PRE_TITLE_RE = re.compile(
        r'(?:^|[\s(\["\'*:,;\-/])'
        r'(?:(?:(?:Ba[şs]kan|[Üü]ye)[ \t]+)?H[aâ]kim[iı]?|H[aâ]kim[ \t]+[Üü]ye|'
        r'(?:(?:Cumhuriyet|Soru[şs]turma|N[öo]bet[çc]i|Bili[şs]im[ \t]+Su[çc]lar[ıi])[ \t]+)?'
        r'(?:Ba[şs])?savc[ıi](?:s[ıi])?(?:[ \t]+Vekil[iı]?)?|'
        r'C\.[ \t]*Savc[ıi]s[ıi]?|'
        r'(?:(?:Zab[ıi]t|Duru[şs]ma)[ \t]+|Z\.[ \t]*)?K[aâ]t[iı][bp][iı]?)'
        r'(?:[ \t]*[:*]+)?[ \t]*$',
        re.IGNORECASE,
    )
    _PRE_TITLE_RE = re.compile(
        r'(?:^|[\s(\["\'*:,;\-/])'
        r'(?:Stj\.?[ \t]*Av\.?|Uzm\.?[ \t]*Dr\.?|Prof\.?(?:[ \t]*Dr\.?)?|Doç\.?(?:[ \t]*Dr\.?)?|'
        r'Av\.?|Dr\.?|Avukat|H[aâ]kim|Savc[ıi]|Zab[ıi]t[ \t]+K[aâ]tib[ıi]|K[aâ]t[ıi]p|M[uü]ba[şs]ir|'
        r'Bilirki[şs]i|Arabulucu|Uzla[şs]t[ıi]rmac[ıi]|Noter|[İI]cra[ \t]+M[uü]d[uü]r[uü]?|'
        r'Tebli[ğg][ \t]+Memuru|Kolluk[ \t]+G[öo]revlisi|Memur[u]?|Komiser|Polis|Terc[uü]man|'
        r'Vekil[i]?|Vekilleri|M[uü]dafi[i]?|M[uü]dafileri)[ \t]*$',
        re.IGNORECASE,
    )
    _AFTER_CORP_TITLE_RE = re.compile(
        r'^[ \t]*(?:'
        r'A\.?[ \t]*Ş\.?|Ltd\.?(?:[ \t]*Şti\.?)?|Şti\.?|A\.?[ \t]*O\.?|Koop\.?|Inc\.?|Corp\.?|LLC|'
        r'\([ \t]*(?:Avukat|Vekil[i]?|M[uü]dafi[i]?|Bilirki[şs]i|Noter|Terc[uü]man|Doktor|Arabulucu|Uzla[şs]t[ıi]rmac[ıi])[ \t]*\)|'
        r',[ \t]*(?:Av\.?|Avukat|Bilirki[şs]i|Doktor|Dr\.?|Noter|Terc[uü]man)\b'
        r')',
        re.IGNORECASE,
    )
    _AFTER_JUDICIAL_TITLE_RE = re.compile(
        r'^[ \t]*(?:'
        r'\([ \t]*(?:H[aâ]kim|Savc[ıi]|K[aâ]t[ıi]p)[ \t]*\)|'
        r',[ \t]*(?:H[aâ]kim|Savc[ıi]|K[aâ]t[ıi]p)\b'
        r')',
        re.IGNORECASE,
    )
    _NON_JUDICIAL_OFFICIAL_LINE_RE = re.compile(
        r'(?<![A-Za-zÇĞİÖŞÜçğıöşüâîû])(?:'
        r'memur\w*|polis\w*|komiser\w*|'
        r'avukat\w*|stj\.?\s*av\.?|av\.|bilirki[şs]i\w*|m[uü]ba[şs]ir\w*|noter\w*|'
        r'doktor\w*|uzm\.?\s*dr\.?|dr\.|prof\.|do[çc]\.|hekim\w*|terc[uü]man\w*|'
        r'arabulucu\w*|uzla[şs]t[ıi]rmac[ıi]\w*|vekil\w*|m[uü]dafi\w*'
        r')(?![A-Za-zÇĞİÖŞÜçğıöşüâîû])',
        re.IGNORECASE,
    )
    _OFFICIAL_LINE_RE = re.compile(
        r'(?<![A-Za-zÇĞİÖŞÜçğıöşüâîû])(?:'
        r'h[aâ]kim\w*|savc[ıi]\w*|k[aâ]ti[pb]\w*|memur\w*|polis\w*|komiser\w*|'
        r'avukat\w*|stj\.?\s*av\.?|av\.|bilirki[şs]i\w*|m[uü]ba[şs]ir\w*|noter\w*|'
        r'doktor\w*|uzm\.?\s*dr\.?|dr\.|prof\.|do[çc]\.|hekim\w*|terc[uü]man\w*|'
        r'arabulucu\w*|uzla[şs]t[ıi]rmac[ıi]\w*|vekil\w*|m[uü]dafi\w*'
        r')(?![A-Za-zÇĞİÖŞÜçğıöşüâîû])',
        re.IGNORECASE,
    )

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

    @classmethod
    def _is_safe_src_path(cls, path: str, real_root: str) -> bool:
        """Sembolik bağların kaynak klasör dışına taşmasını engeller."""
        if not os.path.islink(path):
            return True
        return cls._is_inside_path(
            unicodedata.normalize("NFC", os.path.realpath(path)),
            unicodedata.normalize("NFC", real_root).rstrip(os.sep),
        )

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
            r'(?<![A-Za-z0-9])TR\d{2}(?:[ \t]+\d{4}){2}(?:(?:[ \t]+|[ \t]*\r?\n[ \t]*(?:[/\-][ \t]*)?)\d{1,4}(?![\d.]))+'
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
            r'(?i)(?P<label>\b(?:KART\s*NO|(?:KRED[İI]|BANKA)\s*KART[Iİ](?:\s*NO)?)[\s\*:]+)(?P<card>(?:\d{4}[\s\-]?){3}\d{4}|\d{16})\b'
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

        # 2B-4. Banka tarafından kısmen maskelenmiş kart no ("5406 67** **** 1234", "4532 **** **** 3337", "540667******1234")
        p_card_partial = re.compile(
            r'(?<![\d\w])(?P<card>\d{4}[ \-]?\d{2}[\*xX]{2}[ \-]?[\*xX]{4}[ \-]?\d{4}|\d{4}[ \-]?[\*xX]{4}[ \-]?[\*xX]{4}[ \-]\d{4}|\d{6}[\*xX]{6}\d{4})(?![\d\w])'
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
            r'(?P<num>\d[\d\- ]{3,22}\d)(?![\d/]|[.,]\d)(?P<post>)'
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
        text = cls.normalize_spaces(text)

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
    def _extract_non_ocr_text(cls, fp: str, ext: str) -> str:
        """Metin tabanlı (.udf/.docx/.doc/.xlsx) veya düz metin (.md/.txt) belgeden ham metin okur."""
        if ext == ".udf":
            return cls.extract_udf_raw(fp)
        if ext in (".docx", ".doc"):
            return cls.extract_word_raw(fp)
        if ext == ".xlsx":
            return cls.extract_xlsx_raw(fp)
        if ext in (".md", ".txt") or os.path.basename(fp) in cls.META_JSON_NAMES:
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as rf:
                    return rf.read()
            except Exception:
                return ""
        return ""

    @classmethod
    def _collect_tckns_from_archive(cls, arc_path: str, known: Set[str], allow_nested_zip: bool = False) -> None:
        """Arşivi geçici dizine güvenli açarak içindeki metin belgelerinden TCKN toplar ve temizler."""
        tmp_dir = os.path.realpath(tempfile.mkdtemp(prefix="uyap_arsiv_"))
        try:
            extracted = cls._extract_archive_safely(arc_path, tmp_dir)
            for ef in extracted:
                ef_base = os.path.basename(ef)
                ef_ext = os.path.splitext(ef_base)[1].lower()
                rel_parts = os.path.relpath(ef, tmp_dir).split(os.sep)
                if "__MACOSX" in rel_parts or ef_base in cls.IGNORED_BASENAMES or ef_base.startswith("._"):
                    continue
                if allow_nested_zip and ef_ext == ".zip":
                    cls._collect_tckns_from_archive(ef, known, allow_nested_zip=False)
                elif ef_ext in (".md", ".txt") or ef_ext in cls.TEXT_DOC_EXTS:
                    txt = cls._extract_non_ocr_text(ef, ef_ext)
                    if txt:
                        known.update(cls.collect_known_tckns_from_text(txt))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @classmethod
    def collect_known_tckns_from_folder(cls, folder: str, include_archives: bool = True) -> Set[str]:
        """
        Klasördeki tüm metin dosyalarını (.md/.txt/manifest JSON/.udf/.doc/.docx/.xlsx ve arşiv içi metinler)
        tarayarak bilinen TCKN setini (known_tckns) çıkarır.
        Eğer hedef klasör '(Maskelenmis AI)' uzantılıysa ve aynı dizinde kaynak klasörü varsa,
        kök TCKN hafızasını zenginleştirmek için kaynak klasörü de salt-okunur tarar.
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
            real_scan = os.path.realpath(scan_dir)
            for root, dirs, files in os.walk(scan_dir):
                if cls._is_skipped_dir(root, scan_dir, cls.SKIP_DIRS_OCR) or not cls._is_safe_src_path(root, real_scan):
                    dirs[:] = []
                    continue
                dirs[:] = [
                    d for d in dirs
                    if not cls._is_skipped_dir(os.path.join(root, d), scan_dir, cls.SKIP_DIRS_OCR)
                    and cls._is_safe_src_path(os.path.join(root, d), real_scan)
                ]
                in_kaynak = cls._is_skipped_dir(root, scan_dir, ("_kaynak",))
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    fp = os.path.join(root, f)
                    if not cls._is_safe_src_path(fp, real_scan):
                        continue
                    if not in_kaynak and ((f.endswith((".md", ".txt")) and not f.endswith(".bak")) or f in cls.META_JSON_NAMES):
                        txt = cls._extract_non_ocr_text(fp, ext)
                        if txt:
                            known.update(cls.collect_known_tckns_from_text(txt))
                    elif ext in cls.TEXT_DOC_EXTS:
                        txt = cls._extract_non_ocr_text(fp, ext)
                        if txt:
                            known.update(cls.collect_known_tckns_from_text(txt))
                    elif include_archives and ext in cls.ARCHIVE_EXTS:
                        cls._collect_tckns_from_archive(fp, known, allow_nested_zip=(ext == ".eyp"))
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

        # 1A-1. Açık Etiketli TCKN (9-13 hane, boşluk/tire/soft-hyphen varyasyonları, OCR l/I/O/J/|// bozulmaları ve markdown ** bold desteği dahil)
        p_labeled = re.compile(
            r'(?i)(?P<label>(?:\b(?:T\.?\s*C\.?(?:\s*(?:KN|Kimlik(?:\s*No(?:su|\.lu|marası)?)?|No(?:su|\.lu|marası)?))?|TCKN|YKN|K[İIÍ]ML[İIÍ]K\s*(?:NO(?:SU)?|NUMARASI))|IT\.?@?N[ºo°])[\s\*\_]*[:\t\.\-]?[\s\*\_]*)(?P<num>(?:[0-9lIOoJ|/][ \t\-\u00ad]*){8,12}[0-9lIOoJ|/])(?!\d)(?![A-Za-zÇĞİÖŞÜçğıöşü])'
        )

        def repl_labeled(m: re.Match) -> str:
            nonlocal count
            raw_num = m.group('num')
            norm_num = re.sub(r'[ \t\-\u00ad]', '', raw_num)
            # Eğer numara tarih (12/03/2015, 14-03-2024) veya yıl/esas formatındaysa (2021/12345678) koru
            if ('/' in raw_num or '-' in raw_num) and cls._is_date_or_esas_number(raw_num):
                return m.group(0)
            if '-' in raw_num and (
                re.fullmatch(r'\d{1,2}-\d{1,2}-\d{2,4}', raw_num.strip())
                or re.fullmatch(r'(?:19|20)\d{2}-\d+', raw_num.strip())
                or sum(c.isdigit() for c in norm_num) < 9
            ):
                return m.group(0)
            # "Vergi Kimlik No: 1234567890": 10 haneli VKN tüzel kişiye aittir, TCKN değildir.
            # (Gerçek kişinin VKN'si 11 haneli TCKN'sidir; o maskelenmeye devam eder.)
            if re.search(r'(?i)vergi[\s\*\_]*$', m.string[max(0, m.start() - 15):m.start()]) and \
                    re.fullmatch(r'\d{10}', norm_num):
                return m.group(0)
            if sum(c.isdigit() for c in norm_num) >= 5:
                count += 1
                return f"{m.group('label')}{cls._mask('tckn', raw_num, registry)}"
            return m.group(0)

        # 1A-0. Etiketli ve satır sonunda bölünmüş TCKN ("T.C. Kimlik No: 234567⏎89138",
        # "T.C. Kimlik No:\n12345\n690280", OCR "I.C. Kimlik N0: 2345 6789 138"): ilk satırdaki
        # <11 hane + alt satır başındaki eksik haneler tam 11 eder ve ilk hane 0 değilse maskelenir.
        p_split = re.compile(
            r'(?i)(?P<label>(?:\b[TI1]\.?[ \t]*C\.?[ \t]*(?:Kimlik[ \t]*N[o0][a-zçğıöşü\.]*|N[o0][a-zçğıöşü\.]*|KN)?'
            r'|\bTCKN|\bK[İIÍ]ML[İIÍ]K[ \t]*N[O0][A-Za-zÇĞİÖŞÜçğıöşü\.]*)(?:[ \t\*\_]*[:\.\-][ \t\*\_]*(?:\r?\n[ \t]*)?|[ \t\*\_]+))'
            r'(?P<a>\d(?:[ \t\u00ad]?\d)*)(?:(?P<sep>[ \t]*\r?\n[ \t]*)(?P<b>\d(?:[ \t\u00ad]?\d)*))?(?![\d])'
        )

        def repl_split(m: re.Match) -> str:
            nonlocal count
            a = re.sub(r'\D', '', m.group('a'))
            if m.group('b') is None:
                # Tek satırda boşlukla gruplu 11 hane VEYA etiket sonrası yeni satırda tam 11 hane
                if len(a) != 11 or a[0] == '0':
                    return m.group(0)
                if not ('\n' in m.group('label') or re.search(r'\d[ \t\u00ad]\d', m.group('a'))):
                    return m.group(0)
                count += 1
                return f"{m.group('label')}{cls._mask('tckn', m.group('a'), registry)}"
            b = re.sub(r'\D', '', m.group('b'))
            if len(a) >= 11 or len(a) + len(b) != 11 or a[0] == '0':
                return m.group(0)
            raw = m.group('a') + m.group('sep') + m.group('b')
            count += 1
            return f"{m.group('label')}{cls._mask('tckn', raw, registry)}"

        text = p_split.sub(repl_split, text)

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
                # Açıkça VKN/vergi/MERSİS/poliçe vb. etiketli bitişik 10 hane tüzel kişi numarasıdır;
                # bilinen bir TCKN'nin önekiyle tesadüfen çakışsa bile TCKN sayılmaz.
                before = m.string[max(0, m.start() - 30):m.start()]
                if re.fullmatch(r'\d{10}', raw) and re.search(
                        r'(?i)(?:vergi(?:\s+kimlik)?(?:\s+no(?:su)?)?|\bVKN|V\.\s?D\.?(?:\s*No)?|mersis|poliçe|'
                        r'abone|sipariş|fatura|barkod)\W{0,6}$', before):
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
        Başında 0/+90 olmayan 10 haneli adaylarda bağlam, liste, satır yalnızlığı ve registry doğrulaması yapar.
        Tarihler (05.06.2024), kanun maddeleri (5237), para tutarları (500.000 TL) ve dosya esas numaraları korunur.
        """
        pattern = re.compile(
            r'(?<!\d)(?:(?:\+?90[\s.-]?)?(?:\(0\)|0)[\s.-]?|\+?90[\s.-]?)?(?:\(?5\d{2}\)?|\(05\d{2}\))[\s.-]?\d{3}[\s.-]?(?:\d{2}[\s.-]?\d{2}|\d{4})(?!\d)'
        )
        matches = list(pattern.finditer(text))
        if not matches:
            return text, 0

        # ASLA telefon sayılmayacak önekler (0–40 karakter önce; "abone no/numarası" hariç tutulur,
        # yalın "abone" telefon bağlamıdır)
        excl_re = re.compile(
            r'(?i)(?:\b(?:vergi(?:\s+no)?|vkn|v\.?\s?d\.?|mersis|esas|karar|dosya|evrak|barkod|'
            r'sicil|iban|hesap|müşteri|po[lI]i[cç]e|sipariş|takip|fatura(?:\s+no)?|seri|'
            r'abone\s+no|abone\s+numara\w*|belge|say[ıi]|ref(?:erans)?|işlem|sorgu|dekont|'
            r'bpm|uets|kep|kay[ıi]t\s+no)\b)'
            r'(?:(?!(?:tel(?:efon)?|gsm|cep|irtibat|ileti[şs]im)\w*)[^\r\n\d]){0,40}$'
        )
        phone_before_re = re.compile(
            r'(?i)\b(?:kay[ıi]tl[ıi]\w*|tel(?:efon)?\w*|gsm|cep|hat(?:t[ıi]\w*)?|numara\w*|irtibat\w*|'
            r'ileti[şs]im\w*|arayan\w*|aranan\w*|hts|abone\w*|mobil)\b'
        )
        phone_after_re = re.compile(
            r'(?i)\b(?:numaral[ıi]|nolu|no\'lu|numaras[ıi]|numaralar[ıi]|hat(?:t[ıi](?:n[ıi]?|n|m|nd[ae])?)?|'
            r'gsm|telefon\w*|abone\w*|ile\s+görüş\w*|ar[aı]d\w*|mesaj\w*|sms)\b'
        )
        known_phones = registry.known_values("telefon", min_len=10) if registry is not None else set()

        n = len(matches)
        excluded = [False] * n
        confirmed = [False] * n
        standalone_bare = [False] * n

        for i, m in enumerate(matches):
            raw = m.group(0)
            s, e = m.start(), m.end()
            # "/" ile bitişik (ör. Esas No: 2025/5321234567) asla telefon değildir
            if (s > 0 and text[s - 1] == "/") or (e < len(text) and text[e] == "/"):
                excluded[i] = True
                continue
            digits = re.sub(r'\D', '', raw)
            is_bare10 = (
                len(digits) == 10
                and digits.startswith("5")
                and not raw.lstrip().startswith(("0", "+", "90", "("))
            )
            if not is_bare10:
                confirmed[i] = True
                continue

            before40 = text[max(0, s - 40):s]
            if excl_re.search(before40) or re.match(r'^,\d{2}(?!\d)', text[e:e + 4]):
                excluded[i] = True
                continue

            # a) Ardından 0–40 karakter içinde numara/telefon/abone/görüşme bağlamı
            if phone_after_re.search(text[e:e + 40]):
                confirmed[i] = True
                continue

            # b) Önünde 0–60 karakter içinde (aynı satır veya bir önceki satır sonu) kayıtlı/tel bağlamı
            before60 = text[max(0, s - 60):s]
            before_ctx = "\n".join(before60.split("\n")[-2:])
            if phone_before_re.search(before_ctx):
                confirmed[i] = True
                continue

            # d) Normalize 10 hane registry'de zaten telefon olarak kayıtlı
            if digits in known_phones:
                confirmed[i] = True
                continue

            # c) Satırda tek başına (yalnız boşluk/|/sekme) — diğer telefon varsa veya valid GSM öneki
            ls = text.rfind("\n", 0, s) + 1
            le = text.find("\n", e)
            if le == -1:
                le = len(text)
            if re.fullmatch(r'[ \t|\r]*', text[ls:s]) and re.fullmatch(r'[ \t|\r]*', text[e:le]):
                standalone_bare[i] = True

            # Kesintisiz 10 haneli geçerli operatör kodu (50x-56x, 59x) önek yasağı yoksa kabul edilir
            if re.fullmatch(r'5\d{9}', raw) and raw[1] in "01234569":
                confirmed[i] = True

        # e) Virgül veya "ve" ile ayrılmış listede başka eleman telefon olarak maskelendiyse
        list_sep_re = re.compile(r'^(?:\s*,\s*|\s+ve\s+)$', re.IGNORECASE)
        changed = True
        while changed:
            changed = False
            for i in range(n - 1):
                if excluded[i] or excluded[i + 1]:
                    continue
                if confirmed[i] != confirmed[i + 1]:
                    gap = text[matches[i].end():matches[i + 1].start()]
                    if list_sep_re.match(gap):
                        confirmed[i] = True
                        confirmed[i + 1] = True
                        changed = True

        # c) Satırda tek başına ve aynı belgede en az bir başka telefon maskesi varsa maskele
        other_confirmed_cnt = sum(1 for c in confirmed if c)
        if other_confirmed_cnt >= 1:
            for i in range(n):
                if standalone_bare[i] and not excluded[i] and not confirmed[i]:
                    confirmed[i] = True

        out_parts: List[str] = []
        last_pos = 0
        count = 0
        for i, m in enumerate(matches):
            if not confirmed[i]:
                continue
            out_parts.append(text[last_pos:m.start()])
            out_parts.append(cls._mask("telefon", m.group(0), registry))
            last_pos = m.end()
            count += 1
        out_parts.append(text[last_pos:])
        return "".join(out_parts), count

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
        p1 = re.compile(rf'(?i)(?P<title>\b{titles})(?P<mid>[\s\*\-_|:\t\/]+(?:\([ \t]*)?)(?P<sicil>(?<![\d\.])\d{{5,6}}(?![\d\./])){not_sicil}')

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

        # 1c. Cümle içi "Unvan + 1-4 kelimelik Ad Soyad + 5-6 haneli Sicil"
        # Örn: "Hakim Ayşe Kaya 112233", "Hâkim:Ayşe Kaya 112233", "Hâkim\tAyşe Kaya 112233",
        # "Hâkim Ayşe Kaya\n112233", "Hâkim : Murat Sönmez (34567)", "- **Zabıt Kâtibi:** Seda Ak (223344)"
        p_inline_named = re.compile(
            rf'(?i)(?P<prefix>\b{titles}(?:[ \t\*_]*[:|][\s\*_]*|\s+)'
            rf'(?:\[(?:HAKİM|SAVCI|KÂTİP)_\d+\](?:[ \t]*\|)?\s*|'
            rf'(?:[A-ZÇĞİÖŞÜÂÎÛa-zçğıöşüâîû\.]+(?:\s*\|\s*|\s+)){{1,4}})'
            rf'(?:\(\s*)?)(?P<sicil>(?<![\d\./])\d{{5,6}}(?![\d\./])){not_sicil}'
        )

        def repl_inline_named(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('prefix')}{cls._mask('sicil', m.group('sicil'), registry)}"

        text = p_inline_named.sub(repl_inline_named, text)

        # 2. Tutanak/Karar başlık satırları: "**BAŞKAN :** Ayşe ÖRNEK  123456", "- **Zabıt Kâtibi:** Seda Ak (223344)" veya "HÂKİM : [HAKİM_1] (34567)"
        # Örtüşmeyen ayrık sınıflar + satır içi ayırıcı (?:[ \*]*\t|[ \t\*]*:) ile doğrusal (O(n)) tarama; ReDoS riski yok.
        p3 = re.compile(
            rf'(?im)^(?P<prefix>[ \t\*\-•]*{titles}(?:[ \*]*\t|[ \t\*]*:)'
            rf'(?=[^\r\n]*(?:[a-zA-ZçğıöşüÇĞİÖŞÜ]|\[(?:HAKİM|SAVCI|KÂTİP)_\d+\]))'
            rf'[^\r\n\d\[]*(?:\[(?:(?:HAKİM|SAVCI|KÂTİP)_\d+\]|(?!(?:HAKİM|SAVCI|KÂTİP)_\d+\]))[^\r\n\d\[]*)*)'
            rf'(?<!\d)(?P<sicil>\d{{5,6}})(?!\d)(?P<suffix>[ \t\)\]\*]*)$'
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

        _TRADE_SICIL_PRE_RE = re.compile(
            r'(?i)\b(?:ticaret(?:\s+(?:ve\s+sanayi\s+)?odas[ıi]|(?:\s+sicil(?:i|[\s]+memurluğu)?))?|'
            r't[iı]c\.?|sanayi\s+odas[ıi]|esnaf(?:\s+ve\s+sanatk[aâ]rlar)?\s+(?:odas[ıi]|sicil(?:i)?)|'
            r'meslek\s+odas[ıi]|[iı]şyeri)\s*$'
        )

        # 5. Açık etiketli sicil ("Sicil No: 123456", "Sicili : 123456") ve OCR bozulmalı imza satırı ("+0644-112233")
        # Ticaret sicil / oda sicil / işyeri sicil numaraları tüzel kişiye ait olup açık bırakılır.
        p6 = re.compile(
            r'(?im)(?P<lead>\bSicil(?:i| No| Numaras[ıi])?[\s\*]*[:\t\-][\s\*]*|^[ \t]*\+\d{3,4}[\-\s]+)(?<!\d)(?P<sicil>\d{4,7})(?!\d)'
        )

        def repl6(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('lead')}{cls._mask('sicil', m.group('sicil'), registry)}"

        def repl6_if_not_trade(m: re.Match) -> str:
            pre = m.string[max(0, m.start() - 60):m.start()]
            if _TRADE_SICIL_PRE_RE.search(pre):
                return m.group(0)
            return repl6(m)

        text = p6.sub(repl6_if_not_trade, text)

        # 5a. Kişiye ait SGK/sigortalı sicil no (8-13 hane) ve hekim diploma tescil no.
        # "İşyeri Sicil No" (işverene ait, 20+ hane) bilerek dışarıda bırakılır.
        p6s = re.compile(
            r'(?i)(?P<lead>(?<!İşyeri )(?<!işyeri )\b(?:SGK|SSK|Sigortal[ıi]|Sosyal\s+Güvenlik)[\s\*]*(?:Sicil|Kimlik|Sigorta)?[\s\*]*(?:No|Numaras[ıi])?[\s\*]*[:\t\-][\s\*]*'
            r'|\bDiploma\s+Tescil\s*(?:No|Numaras[ıi])?[\s\*]*[:\t\-]?[\s\*]*)'
            r'(?<!\d)(?P<sicil>\d{4,13})(?![\d/])'
        )

        def repl6s(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('lead')}{cls._mask('sicil', m.group('sicil'), registry)}"

        text = p6s.sub(repl6s, text)

        # 6. Eşittir / boşlukla yazılmış sicil ("(Sicil=234408)", "Sicili 476175")
        p7 = re.compile(
            r'(?i)(?P<lead>\bSicil(?:i|\s*No)?[ \t\*]*=?[ \t\*]*)(?<![\d])(?P<sicil>\d{4,7})(?![\d\./])'
            r'(?!\s*(?:TL|yıl|sayılı|tarih|Esas|Karar)\b)'
        )
        text = p7.sub(repl6_if_not_trade, text)

        # 7. Baro sicil no ("Baro Sicil No : Burdur Barosu , 490" / "İzmir Barosu- 20763")
        p8 = re.compile(
            r'(?i)(?P<lead>Baro\s*Sicil\s*(?:No|Numaras[ıi])?[^\r\n\d]{0,60}?Barosu[ \t]*[,\-–:]?[ \t]*)(?P<sicil>\d{2,6})(?!\d)'
        )
        text = p8.sub(repl6, text)

        # 7b. "<İl> Barosu" + isteğe bağlı (Sicil|Sicil No|No|:|-) + 3-6 hane ("Ankara Barosu 23456")
        p8_baro = re.compile(
            r'(?i)(?P<lead>\b[A-Za-zÇĞİÖŞÜçğıöşü\-]{2,25}[ \t]+Barosu\b'
            r'(?:[ \t]*[,\-–:]?[ \t]*(?:Sicil(?:[ \t]+(?:No|Numaras[ıi]))?|No))?[ \t]*[,\-–:]?[ \t]*)'
            r'(?<![\d\./])(?P<sicil>\d{3,6})(?![\d\./])'
            r'(?!\s*(?:y[ıi]l[ıi]?|tarih\w*|Bölge|TL|Türk\s*Liras[ıi]|USD|EUR|say[ıi]l[ıi]|Esas|Karar|Nolu|No\'lu)\b)'
        )
        text = p8_baro.sub(repl6, text)

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
        r'borçlu|alacakl[ıi]|avukat|kişi|isimli|yükümlü\w*|adresini|şah[ıi]s(?:[ıi]n?|a)?|'
        r'küçü(?:k|ğün)|kayy[ıi]m(?:\s+aday[ıi])?|ihbar\s+olunan|veli(?:si)?|anne(?:si)?|baba(?:s[ıi])?)(?![a-zçğıöşü])|'
        r'\bAv\.|belirtilen\s+\*\*)'
    )
    _ADDR_INST_RE = re.compile(
        r'(?i)bankas[ıi]|\bbanka\b|bankac[ıi]l[ıi]k|\bA\.\s?Ş\b|\bT\.A\.Ş|genel\s+müdürlü|'
        r'operasyon\s+merkezi|adalet\s+saray|adliye|mahkemesi|noter(?:i|li(?:ği|gi)?)?|barosu|icra\s+dairesi|'
        r'başkanl[ıi]ğ|\bPTT\b|belediye|ticaret\s+sicil|mersis|valili|kaymakaml|müdürlüğü|şubesi|'
        r'(?:ticaret(?:\s+ve\s+sanayi)?|sanayi|esnaf(?:\s+ve\s+sanatk[aâ]rlar)?|meslek)\s+odas[ıi]|borsas[ıi]|'
        r'organize\s+sanayi\s+bölgesi|\(\s*antet[i]?\s*\)|'
        r'ltd\.?\s*şti|holding|sigorta|hastane|üniversite|polis\s+merkezi|karakol|jandarma|'
        r'menkul\s+k[ıi]ymet|katılım\s+bankas|iş\s+merkezi|towers|plaza|\bcenter\b'
    )
    _ADDR_OLAY_RE = re.compile(
        r'(?i)suçun\s+yeri|olay\s+yeri|kaza\s+yeri|keşif\s+yeri|(?:suç|olay|kaza|keşif)\s+mahalli|'
        r'olay(?:ın)?\s+meydana|meydana\s+gel|\bönünde\b|kavşağ|sıralarında|trafik\s+kazas|Yer\s*\(Cadde'
    )
    # Tüzel kişi biçimi: taraf satırında geçerse alttaki adres kurum adresidir
    _ADDR_STRONG_INST_RE = re.compile(
        r'(?i)\bA\.\s?Ş\b|\bT\.A\.Ş|ltd\.?\s*şti|bankas[ıi]|sigorta|holding|kooperatif|'
        r'belediye|müdürlü|başkanl[ıi]ğ|vakf[ıi]|derneği'
    )
    # Kaza tespit tutanağı lejantı ("1 Cadde", "4 Devlet yolu", "2 Sokak"): ad içermeyen yol türü satırı
    _ADDR_FORM_LEGEND_RE = re.compile(
        r'(?i)^\s*\d{0,2}\s*(?:Cadde(?:si)?|Cad\.?|Sokak|Sok\.?|Sk\.?|Bulvar[ıi]?|Mahalle(?:si)?|Mah\.?)\s*(?:\r?\n|$)'
    )
    # HTS baz istasyonu ve koordinat bağlamı (olay yeri gibi korunur)
    _ADDR_HTS_RE = re.compile(
        r'(?i)(?:\bopr\s*:|\b(?:operat[öo]r|baz(?:\s+istasyon\w*)?|BTS|CGI|hücre\w*|LAC)\b)'
    )
    _ADDR_COORD_RE = re.compile(r'\b\d{2}\.\d{4,}\s*[-,;]?\s*\d{2}\.\d{4,}\b')
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
        while pos > 0 and len(prev) < 3:
            ps = text.rfind('\n', 0, pos) + 1
            pl = text[ps:pos].strip()
            if pl:
                prev.append(pl)
            pos = ps - 1
        # Adresin hemen önünde açık kişi adresi ifadesi ("mernis adresinin", "açık adresinin",
        # "yerleşim yeri", "küçüğün ... adresi") varsa kişi adresidir; satırın başka yerindeki kurum adı
        # (aynı cümlede geçen "Sulh Hukuk Mahkemesi" gibi) bunu kurum adresi yapmaz.
        before = text[max(ls, start - 80):start]
        before_on_line = text[ls:start]
        _personal_qual_rx = r'(?i)\b(?:ikamet\w*|yerleşim|yetkili\w*|müdür[ü]?|ortağ[ıi]\w*|çalışan[ıi]\w*|personel\w*)\b'
        _corp_addr_label_rx = (
            r'(?i)\b(?:şirket(?:i|in|inin|imiz|imizin)|holding(?:i|in)|banka(?:s[ıi]|n[ıi]n)|'
            r'kooperatif(?:i|in)|kurum(?:u|un)|derne(?:ği|ğin)|vakf(?:[ıi]|[ıi]n))\s+(?:tebligat\s+|resm[îi]\s+|merkez\s+)?adres'
        )
        has_personal_qual_on_line = bool(re.search(_personal_qual_rx, before_on_line))
        # Aynı cümlede/satırda adresin hemen öncesinde tüzel kişi adı + şirket merkezi/şubesi/genel müdürlüğü/
        # fabrikası/işyeri adresi ifadesi varsa (ardında kişi-adresi/oturma bağlamı yoksa) kurum adresidir.
        # Not: "A.Ş. şubesi Barbaros Mah." gibi yapılarda "şubesi/merkezi/..." öbeği addr başlangıcına
        # dahil edilebildiği için adres başından hemen sonraki kısa ön-bağlam da taranır.
        cue_win_start = max(ls, start - 90)
        cue_win = text[cue_win_start:min(end, start + 35)]
        m_corp_cue = re.search(
            r'(?i)\b(?:şirket[ \t]+merkezi|(?<!iş[ \t])(?<!ticaret[ \t])(?<!alışveriş[ \t])(?<!kültür[ \t])merkezi|şubesi|genel[ \t]+müdürlüğü|fabrikas[ıi]|iş[ \t]*yeri[ \t]+adresi)\b',
            cue_win,
        )
        if m_corp_cue:
            cue_abs = cue_win_start + m_corp_cue.start()
            if (cue_abs < start or not (text[cue_abs:cue_abs + 7] == "Merkezi")) and cls._ADDR_STRONG_INST_RE.search(text[ls:cue_abs]):
                tail_win = text[cue_abs:min(le, end + 40)]
                if not cls._ADDR_PERSON_RE.search(tail_win) and not re.search(
                    r'\[TCKN_(?:\d+|GİZLENDİ)\]|\bTCKN\b|T\.?\s?C\.?\s*(?:Kimlik\s*)?No',
                    text[cue_abs:le],
                ):
                    return "kurum"
        # "Davalı şirketin adresi: ... (Anteti)" / "Davalı şirketin tebligat adresi:" gibi tüzel kişi
        # adresi kalıpları gerçek kişi ikametgahı, yetkilisi veya ortağı belirtilmedikçe kurum adresidir.
        if (
            not has_personal_qual_on_line
            and not re.search(r'(?i)\bmernis\b', before_on_line)
            and (
                re.search(r'(?i)\(\s*antet[i]?\s*\)', line)
                or re.search(_corp_addr_label_rx, before_on_line)
            )
        ):
            return "kurum"
        # Şirket yetkilisi / ortağı / çalışanı adres bağlamı (kurum/şirket aynı satırda geçse de kişi adresidir)
        if re.search(
            r'(?i)\b(?:yetkili(?:si|sinin)?|ortağ[ıi](?:n|n[ıi]n)?|çalışan[ıi](?:n|n[ıi]n)?)\b[^.\n]{0,60}\badres\w*',
            before_on_line,
        ):
            return "kisi"
        # Adresin hemen önünde açık kişi adresi ifadesi ("mernis adresinin", "açık adresinin",
        # "yerleşim yeri", "küçüğün ... adresi") varsa kişi adresidir; satırın başka yerindeki kurum adı
        # (aynı cümlede geçen "Sulh Hukuk Mahkemesi" gibi) bunu kurum adresi yapmaz.
        if re.search(r'(?i)mernis|(?:açık|ikamet\w*|tebligat|yerleşim)\s+(?:yeri\s+)?adres\w*|yerleşim\s+yeri|'
                     r'(?:küçüğün|çocuğun|davalının|davacının|sanığın|şüphelinin|müvekkilin|borçlunun|tanığın)\b[^.\n]{0,40}adres\w*\s*["“]?\s*$',
                     before):
            return "kisi"
        # Uzun düzyazı satırında (birden çok cümle) yalnız adresin çevresine bakılır; üst satırlar ve
        # satırın uzak kısımları (başka kurumların adları) bağlam sayılmaz.
        if len(line) > 200:
            win = text[max(ls, start - 80):min(le, end + 40)]
            if cls._ADDR_OLAY_RE.search(win) or cls._ADDR_HTS_RE.search(win) or cls._ADDR_COORD_RE.search(win):
                return "olay"
            if cls._ADDR_PERSON_RE.search(win):
                return "kisi"
            if cls._ADDR_INST_RE.search(win):
                return "kurum"
            return "kisi"
        if cls._ADDR_OLAY_RE.search(line) or cls._ADDR_HTS_RE.search(line) or cls._ADDR_COORD_RE.search(line):
            return "olay"
        # Aynı satırda kişi kimlik numarası (maskeli ya da etiketli) varsa satır bir kişiye aittir;
        # üst satırdaki kurum adı ("İHBAR EDEN: ... MAHKEMESİ") bunu kurum adresi yapmaz.
        if re.search(r'\[TCKN_(?:\d+|GİZLENDİ)\]|\bTCKN\b|T\.?\s?C\.?\s*(?:Kimlik\s*)?No', line):
            return "kisi"
        if cls._ADDR_PERSON_RE.search(line):
            return "kisi"
        if cls._ADDR_INST_RE.search(line):
            return "kurum"
        if prev and cls._ADDR_HTS_RE.search(prev[0]):
            return "olay"
        # Yakından uzağa (prev[0] -> prev[1] -> prev[2]) bağlam önceliği:
        # ilk açık kişi kimliği/rolü (şirket olmayan) -> 'kisi'; ilk kurum/noter/şirket/mersis -> 'kurum'.
        _no_person_id = r'(?i)T\.?\s?C\.?\s*(?:Kimlik|No)|TCKN|\[TCKN_'
        for idx, p_line in enumerate(prev):
            if idx == 0 and cls._ADDR_OLAY_RE.search(p_line):
                return "olay"
            has_pid = bool(re.search(_no_person_id, p_line))
            is_strong_inst = bool(cls._ADDR_STRONG_INST_RE.search(p_line)) and not has_pid
            if has_pid or (cls._ADDR_PERSON_RE.search(p_line) and not is_strong_inst):
                return "kisi"
            if is_strong_inst or cls._ADDR_INST_RE.search(p_line):
                return "kurum"
        return "kisi"

    _CLASSIFY_LOC_SPAN_RE = re.compile(
        r'(?i)(?:'
        r'\b(?:mah\.?|mh\.?|mahallesi|cad\.?|cd\.?|caddesi|sk\.?|sok\.?|soka[gğ][ıi]|sokak|'
        r'bulvar[ıi]?|blv\.?|mevkii?|mevki[i]?|sites[i]?|apt\.?|apartman[ıi]|plaza|towers?|center|'
        r'k[öo]y[üu]?|beldes[i]?|buca[gğ][ıi]|osb|sanayi\s+b[öo]lgesi)\b|'
        r'\b[a-zçğıöşüA-ZÇĞİÖŞÜ0-9\-]+\s+(?:mah\.?|mh\.?|mahallesi|cad\.?|cd\.?|caddesi|sk\.?|sokak|bulvar[ıi]?)\b'
        r')'
    )
    _CLASSIFY_KUNYE_RE = re.compile(
        r'(?i)vergi|\bVKN\b|V\.\s?D\.|mersis|ticaret\s+sicil|\btel\b|telefon|faks|\bKEP\b|e-?posta|web'
    )

    @classmethod
    def classify_address_line(cls, lines: List[str], i: int, scan_line: str) -> str:
        """
        Redaktör ve audit_output için tek kaynaklı satır-bazlı adres bağlam sınıflandırıcısı.
        Temelde UyapRedactor._address_owner'ı çağırır; satırda açık kişi ipucu yoksa bir sonraki
        boş olmayan satırdaki kurum adını ve 6 satıra kadar şirket künye bloğunu da dikkate alır.
        """
        if not scan_line:
            return "kisi"
        m_loc = cls._CLASSIFY_LOC_SPAN_RE.search(scan_line)
        if m_loc:
            # Cadde/Mahalle tokeninin önündeki yer adını ("Maslak Mahallesi", "Atatürk Bulvarı", "Ostim OSB 1234. Cad.")
            # span başlangıcında yakala ki şirket adresi / ortak / yetkili ön-bağlamı ':' öncesinde kalsın.
            s_rel = m_loc.start()
            m_colon = re.search(r'\badres\w*\s*[:：]\s*', scan_line[:s_rel], re.I)
            if m_colon:
                s_rel = m_colon.end()
            else:
                ls_tok = scan_line.rfind(':', 0, s_rel)
                if ls_tok != -1 and not re.search(r'(?i)\b(?:no|kap[ıi]|daire|kat|blok)\s*$', scan_line[:ls_tok]):
                    s_rel = ls_tok + 1
                    while s_rel < len(scan_line) and scan_line[s_rel] in ' \t*"“':
                        s_rel += 1
        else:
            s_rel = 0
        e_rel = min(len(scan_line), max(s_rel + 40, len(scan_line)))
        ctx_start = max(0, i - 3)
        prefix_lines = lines[ctx_start:i]
        joined = "\n".join(prefix_lines + [scan_line])
        line_off = sum(len(pl) + 1 for pl in prefix_lines)
        owner = cls._address_owner(joined, line_off + s_rel, line_off + e_rel)
        if owner != "kisi":
            return owner
        # Satırda açık kişi ipucu yoksa, hemen sonraki satırdaki kurum adını ve şirket künyesini kontrol et
        has_person_cue = bool(
            cls._ADDR_PERSON_RE.search(scan_line)
            or re.search(r'(?i)T\.?\s?C\.?\s*(?:Kimlik|No)|TCKN|\[TCKN_|mernis|ikamet|tebligat|yerleşim', scan_line)
        )
        if not has_person_cue:
            next_line = next((lines[j] for j in range(i + 1, min(len(lines), i + 3)) if lines[j].strip()), "")
            if next_line and cls._ADDR_INST_RE.search(next_line) and not cls._ADDR_PERSON_RE.search(next_line):
                return "kurum"
            seen = 0
            for j in range(i - 1, -1, -1):
                s = lines[j].strip()
                if not s:
                    continue
                seen += 1
                if seen > 6 or re.search(r'(?i)T\.?\s?C\.?\s*(?:Kimlik|No)|TCKN|\[TCKN_', s):
                    break
                if cls._ADDR_STRONG_INST_RE.search(s) or cls._ADDR_INST_RE.search(s):
                    return "kurum"
                if not cls._CLASSIFY_KUNYE_RE.search(s):
                    break
        return "kisi"

    @classmethod
    def _skip_address(cls, text: str, start: int, end: int, addr: str) -> bool:
        """Adres maskelenmemeli mi? (kurum/olay yeri/baz istasyonu, nüfus şablonu, URL, mahkeme kısaltması)"""
        if cls._looks_like_url_or_email(addr):
            return True
        if cls._ADDR_COORD_RE.search(addr):
            return True
        # Form lejantı: ilk satır yalnız "<rakam> Cadde/Sokak" ve hiçbir yerde "No: <rakam>" yok
        if cls._ADDR_FORM_LEGEND_RE.match(addr) and not re.search(r'(?i)\bNo\s*[:.]?\s*\d', addr):
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
            r'(?P<addr>[^\r\n]+?(?:/[ \t]*\r?\n[ \t]*[A-ZÇĞİÖŞÜa-zçğıöşü]{2,25}(?=[ \t]*\r?\n|$))?)'
            r'(?=(?:\s*(?:'
            r'(?:Anne|Baba)\s*Ad[ıi]|'
            r'Doğum\s*(?:Yeri|Tarihi)|'
            r'Nüfus[a-z]*|Cilt\s*No|Aile\s*Sıra|'
            r'GSM\b|Cep\b|Tel(?:efon)?\b|Faks\b|'
            r'E-?\s*posta|Email\b|KEP\b|'
            r'Vekil(?:i)?\b|Müdafi(?:i)?\b|Baro|Meslek|'
            r'Tel\b|ARANMIYOR|TC\s*Kimlik|T\.C\.|SUÇUN\s+TARİHİ|'
            r'[,;]?\s*(?:[EK][ \t]*[:.][ \t]*(?:19|20)\d{2}[ \t]*/|(?:Esas|Karar)(?:[ \t]*No)?[ \t]*[:.]?[ \t]*(?:19|20)\d{2}[ \t]*/|(?:19|20)\d{2}[ \t]*/[ \t]*\d+[ \t]*(?:E|K)\b)|'
            r'\|(?!¢)|$|\r?\n)))'
        )

        def repl1(m: re.Match) -> str:
            nonlocal count
            addr_val = m.group('addr').strip()
            trail_line = ""
            if "\n" in addr_val:
                first_l, second_l = addr_val.split("\n", 1)
                if _fold_tr(second_l.strip()) in cls._IL_CANON_MAP:
                    addr_val = f"{first_l.rstrip()} {second_l.strip()}"
                else:
                    trail_line = "\n" + second_l
                    addr_val = first_l.rstrip()
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
            return f"{m.group('pre') or ''}{m.group('label')}{head}{cls._mask('adres', addr_val, registry)}{trail_line}"

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
            r'(?P<prefix>(?:doğumlu\s+ve\s+halen|ve\s+halen|(?<![A-Za-zÇĞİÖŞÜçğıöşü])halen|doğumlu[\.,]|nüfus(?:a|unda)\s+kayıtlı(?:dır)?[\.,]?|kayıtlı\s+olup\s+halen|belirtilen|E-Tebligat\s+Adresidir\.)\s+)'
            r'(?P<addr>(?:[A-ZÇĞİÖŞÜa-zçğıöşü0-9\.\-\/]+\s+){0,5}?(?:Mah\.|Mh\.|Mahallesi\b)[^\r\n\|]+?)'
            r'(?P<suffix>\s+(?:adresinde\s+oturur|ikamet\s+eder|adresinde\s+ikamet\s+eder|adresinde\s+bulunur|adresine\b|adresinde\b)|'
            r'(?=[,;]?[ \t]*(?:[EK][ \t]*[:.][ \t]*(?:19|20)\d{2}[ \t]*/|(?:Esas|Karar)(?:[ \t]*No)?[ \t]*[:.]?[ \t]*(?:19|20)\d{2}[ \t]*/|(?:19|20)\d{2}[ \t]*/[ \t]*\d+[ \t]*(?:E|K)\b))|'
            r'\s*(?=$|\r?\n))'
        )

        def repl2(m: re.Match) -> str:
            nonlocal count
            addr = m.group('addr')
            if re.search(mask_adres_re, addr) or cls._looks_like_url_or_email(addr):
                return m.group(0)
            # Tek başına "halen" ön eki: devamı gerçekten açık adres değilse ("halen devam eden ... Mah.
            # sakinleri") dokunma; sokak/cadde veya kapı numarası şart.
            if re.fullmatch(r'(?i)halen\s+', m.group('prefix')) and not re.search(
                    r'(?i)\b(?:Sok\w*|Sk\.?|Cad\w*|Cd\.?|Bulvar\w*|Blv\.?)(?![A-Za-zçğıöşü])|\bNo\s*[:.]?\s*\d|\d+\s*/\s*\d',
                    addr):
                return m.group(0)
            if cls._ADDR_COORD_RE.search(addr) or cls._address_owner(m.string, m.start('addr'), m.end('addr')) == "olay":
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
            r'(?:(?:^|(?<=[\r\n\|\#\:;\,\.\^\(\-\/\*"“”]))[ \t]*(?:[A-ZÇĞİÖŞÜa-zçğıöşü0-9]+[ \t]+){1,2}'
            r'|[A-ZÇĞİÖŞÜ0-9][A-Za-zÇĞİÖŞÜçğıöşü0-9]*[ \t]+(?=(?:Mahallesi|Mah\.?|Mh\.?)(?:[\s\,\.\^\-]|(?<=\.)[A-ZÇĞİÖŞÜa-zçğıöşü]))'
            r'|[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü]*\s+(?=Köy(?:ü)?[ \t]))?'
            r'\b(?:Mahallesi|Mah\.?|Mh\.?|Köy(?:ü)?|Cadde(?:si)?|Cad\.?|Cd\.?|Sokak|Sokağ[ıi]|Sok\.?|Sk\.?|5k\.?|Bulvar[ıi]|Bulv\.?|Blv\.?|Küme\s*Evler[i]?|Toki\s+Evleri)(?:[\s\,\.\^\-]+|(?<=\.)(?=[A-ZÇĞİÖŞÜa-zçğıöşü]))'
            r'(?:\|¢|[^\r\n\|]){0,100}?'
            r'(?:'
            r'\b(?:No|Nu|Ne)(?:[ \t]*[:.\-\^\/]+[ \t]*[0-9A-Za-z]|[ \t]+\d)'
            r'|\bN(?=[ \t]*[:.][ \t]*\d)'
            r'|(?:[İiIıl]ç[ \t]*Kap[ıi](?:[ \t]*No)?|\|¢[ \t]*Kap[ıi](?:[ \t]*No)?)(?:[ \t]*[:.\-\^\/]*[ \t]*[0-9A-Za-z]|[ \t]+\d|\b[ \t]*No\b)'
            r'|\b(?:Kat|Daire)(?:[ \t]*[:.\-\^\/]+[ \t]*[0-9A-Za-z]|[ \t]+\d)'
            r'|\b(?:D|K(?![ \t]*[:.][ \t]*(?:19|20)\d{2}[ \t]*/))(?:[ \t]*[:.][ \t]*[0-9A-Za-z]|[ \t]+\d)'
            r'|\b(?:Blok|Blk|Apt\.?|Apartman[ıi]|Sitesi|Evleri)(?:[ \t]*[:.\-\^\/]*[ \t]*\d|[ \t]+\d|[ \t]+(?:No\b|(?-i:[A-ZÇĞİÖŞÜ0-9]{1,3})[ \t]*(?:Blok|Daire|K|D)\b|[A-ZÇĞİÖŞÜa-zçğıöşü]*\b[ \t]*No\b))'
            r')'
            r'(?:\|¢|[^\r\n\|]){0,100}?'
            r'(?:[A-ZÇĞİÖŞÜa-zçğıöşü\s]{2,25}[\/J]\s*[A-ZÇĞİÖŞÜa-zçğıöşü0-9\s\,\.]{2,25})?'
            r')'
            r'(?P<tail>(?=\s+(?:adresinde\s+oturur|ikamet\s+eder|adresinde|adresine|SUÇUN\s+TARİHİ|Tel\b|TC\s*Kimlik|\d{2}\.\d{2}\.\d{4}\b|\d\s+5\d{9}\b)|\s*(?:\|(?!¢)|\r|\n|[\"“”])|$))'
        )

        _p3_unit_split_re = re.compile(
            r'(?i)(?:'
            r'\b(?:No|Nu|Ne|Kat|Daire)(?:[ \t]*[:.\-\^\/]+[ \t]*\d|[ \t]+\d)'
            r'|\b[NDK][ \t]*[:.][ \t]*\d'
            r'|\b[İiIıl]ç[ \t]*Kap[ıi](?:[ \t]*No)?[ \t]*[:.\-]?\s*\d'
            r')'
        )
        _p3_pre_strip_re = re.compile(
            r'(?i)[ \t]*(?:'
            r'(?:nüfusa\s+)?kay[ıi]tl[ıi]|doğumlu,?|halen|ve|olup|ikamet\s+eden|'
            r'davac[ıi]|daval[ıi]|m[uü][şs]teki|[şs][uü]pheli|san[ıi]k|kat[ıi]lan|ma[ğg]dur|tan[ıi]k|'
            r'alacakl[ıi]|bor[çc]lu|m[uü]vekkil|avukat|olay|kaza|ara[çc]'
            r')[ \t]+(?=(?:[^\s]+[ \t]+)+(?:Mahallesi|Mah\.?|Mh\.?|Köy(?:ü)?|Cadde(?:si)?|Cad\.?|Cd\.?|Sokak|Sokağ[ıi]|Sok\.?|Sk\.?|5k\.?|Bulvar[ıi]|Bulv\.?|Blv\.?|Küme|Toki)\b)'
        )
        _p3_prose_break_re = re.compile(
            r'(?i)\b(?:üzerinde(?:ki)?|civarında(?:ki)?|önünde(?:ki)?|yakınında(?:ki)?|karşısında(?:ki)?|kesişiminde(?:ki)?)\b'
            r'|(?<!Mah)(?<!Mh)(?<!Cad)(?<!Cd)(?<!Sk)(?<!Sok)(?<!Bulv)(?<!Blv)(?<!Apt)(?<!Dr)(?<!Av)(?<!No)\.\s+(?-i:[A-ZÇĞİÖŞÜ])'
        )

        def repl3(m: re.Match) -> str:
            nonlocal count
            addr = m.group('addr')
            if re.search(cls.MASK_ANY_RE, addr):
                return m.group(0)
            # Baştaki bağlam/taraf sözcükleri ("davalı ", "kayıtlı ", "olay ") adres değildir; dışarıda kalır
            lead_extra = ""
            while True:
                pre_kw = _p3_pre_strip_re.match(addr)
                if not pre_kw:
                    break
                lead_extra += pre_kw.group(0)
                addr = addr[pre_kw.end():]
            # Adres biriminden önce düzyazı edatı ("üzerinde", "önünde") veya cümle noktası varsa kesip koru
            m_u = _p3_unit_split_re.search(addr)
            if _p3_prose_break_re.search(addr[:m_u.start()] if m_u else addr):
                return m.group(0)
            # Adres cümle içinde geçiyorsa eşleşme satır sonuna kadar uzayabilir ("... İncirliova/AYDIN olup
            # mahkememizin ... TMK 411. madde gereğince"). Kapı no + daire/kat + "İlçe/İL" sonrasında kes:
            # kalan cümle korunur ve hukuki ifadeler adresin tamamını "adres değil" saydırmaz.
            rest = ""
            core = re.search(
                r'(?i)(?:\b(?:No|Nu|Ne|[İiIıl]ç[ \t]*Kap[ıi](?:[ \t]*No)?)\s*[:.]?\s*\d+[A-Za-z0-9]*(?:\s*/\s*[0-9A-Za-z]+)?'
                r'|\b(?:Kat|Daire|D|K(?![ \t]*[:.]?[ \t]*(?:19|20)\d{2}[ \t]*/))\s*[:.]?\s*\d+[A-Za-z0-9]*\b)'
                r'(?:\s*(?:[İiIıl]ç\s*Kap[ıi](?:\s*No)?|Daire|Kat|D|K(?![ \t]*[:.]?[ \t]*(?:19|20)\d{2}[ \t]*/)|Blok)\s*[:.]?\s*[0-9A-Za-z]{1,4}\b)*'
                r'(?:\s*,?\s*(?:(?-i:[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü]+)[ \t]+)?(?-i:[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü]+)\s*/\s*(?-i:[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü]+)'
                r'|\s+(?-i:[A-ZÇĞİÖŞÜ][a-zçğıöşü]+)\s+(?-i:[A-ZÇĞİÖŞÜ]{3,})\b)?',
                addr,
            )
            if core and addr[core.end():].strip():
                m_il = re.match(r'^([ \t]*,?[ \t]*(?-i:[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü]{2,20})\b)', addr[core.end():])
                cand_il = _fold_tr(m_il.group(1).strip(" ,")) if m_il else ""
                il_cut = m_il.end() if (cand_il and any(_fold_tr(il) == cand_il for il in cls._IL_ADLARI)) else 0
                if addr[core.end() + il_cut:].strip():
                    rest = addr[core.end() + il_cut:]
                    addr = addr[:core.end() + il_cut]
            a_start = m.start('addr') + len(lead_extra)
            if cls._skip_address(m.string, a_start, a_start + len(addr), addr):
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
            return f"{m.group('lead')}{lead_extra}{keep}{cls._mask('adres', addr, registry)}{rest}"

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
            r'(?P<lead2>[ \t#\*]*)(?P<a2>[^\r\n"”]*?\b(?:No|[NVMW][oea])[ \t]*[:.][ \t]*[0-9A-Za-z][^\r\n"”]*?)'
            r'(?=[ \t]+(?:adres\w*|ikamet|oturur|Tel\b|GSM\b)|["”\)]|[ \t]*$)'
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
        # (Örn: "[ADRES_1]\nK:2 D:40 Burdur Merkez/ BURDUR" -> devam satırı silinir, varsa ilçe/il ipucu etikete eklenir)
        opt_hint_re = r'(?:[ \t]+\([^)\r\n]+\))?'
        p4 = re.compile(
            r'(?i)(?P<masked>' + mask_adres_re + r')(?P<hint>' + opt_hint_re + r')'
            r'(?P<ws>\s*\r?\n(?:\s*\r?\n)?[\s\#\*]*(?:\.\.\.\s*)?)'
            r'(?P<city>(?:\b(?:K(?:at)?|No|Blok|D(?:aire)?)\b[\s\:\.\-]*\d+[0-9A-Za-z\s\:\.\-/]*\s+)?[A-ZÇĞİÖŞÜa-zçğıöşü\s]{2,30}/\s*[A-ZÇĞİÖŞÜa-zçğıöşü]{2,20})'
            r'(?=\s*\r?\n|$)'
        )

        def repl4(m: re.Match) -> str:
            if m.group('hint'):
                return f"{m.group('masked')}{m.group('hint')}"
            city_txt = m.group('city')
            if cls._ADDR_OLAY_RE.search(city_txt):
                return m.group(0)
            if cls._address_owner(m.string, m.start('city'), m.end('city')) != "kisi":
                return m.group(0)
            return cls._format_adres_label(m.group('masked'), city_txt, registry)

        text = p4.sub(repl4, text)

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
                return f"{m.group('lead')}{cls._format_adres_label(prev_labels[-1], m.group('cont'), registry)}"
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
            r'(?im)(?P<masked>(?P<mlabel>' + mask_adres_re + r')' + opt_hint_re + r'[ \t]*\r?\n)(?P<lead>[ \t]*)'
            r'(?P<cont>(?:[İiIıl]ç\s*Kap[ıi](?:\s*No)?|Kap[ıi]\s*No|Kat|K|Daire|D|No|Blok)[ \t\.:]*[0-9][^\r\n]*?)'
            r'(?=[ \t,;]+(?:Tel|GSM|Cep|Telefon)\b|[ \t]*$)'
        )

        def repl4_cont(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('masked')}{m.group('lead')}{cls._format_adres_label(m.group('mlabel'), m.group('cont'), registry)}"

        text = p4_cont.sub(repl4_cont, text)

        # 4c2. OCR'ın "No"yu "Vo/Ne" okuduğu devam satırı: "[ADRES_1]\nVo:19 AC Silivri /ISTANBUL" olarak ... — aynı etiket
        p4_cont2 = re.compile(
            r'(?im)(?P<masked>(?P<mlabel>' + mask_adres_re + r')' + opt_hint_re + r'[ \t]*\r?\n)(?P<lead>[ \t]*)'
            r'(?P<cont>[NVMW][oea][ \t]*[:.][ \t]*[0-9A-Za-z]{1,4}(?:[ \t]+[A-Za-zÇĞİÖŞÜçğıöşü]{1,5})?'
            r'[ \t]+[A-ZÇĞİÖŞÜa-zçğıöşü ]{2,30}[ \t]*/[ \t]*[A-ZÇĞİÖŞÜa-zçğıöşü]{2,20})(?=["”\)\.,;]|[ \t]|$)'
        )
        text = p4_cont2.sub(repl4_cont, text)

        # 4d. OCR tablosundan dağılmış adres: "[ADRES_1] / iç Kapı No / DENEME SK. / 28" — aynı etiket
        p4_ocr = re.compile(
            r'(?m)(?P<head>(?P<mlabel>' + mask_adres_re + r')' + opt_hint_re + r'[ \t]*\r?\n(?:[ \t]*[İiIıl]ç\s*Kap[ıi](?:\s*No)?[ \t:]*\r?\n)?)'
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
            r'(?m)(?P<head>(?P<mlabel>' + mask_adres_re + r')' + opt_hint_re + r'[ \t]*\r?\n(?:[ \t]*\r?\n)?)(?P<lead>[ \t#\*]*)'
            r'(?P<cont>(?![^\r\n]*' + mask_adres_re + r')[^\r\n]{0,60}?\b(?:No|[NVMW][oea])[ \t]*[:.][ \t]*\d[^\r\n]{0,40}?'
            r'[A-ZÇĞİÖŞÜa-zçğıöşü]{2,25}[ \t]*/[ \t]*[A-ZÇĞİÖŞÜa-zçğıöşü]{2,20})[ \t\.]*$'
        )

        def repl4_tail(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('head')}{m.group('lead')}{cls._format_adres_label(m.group('mlabel'), m.group('cont'), registry)}"

        text = p4_tail.sub(repl4_tail, text)

        text, net_count = cls.redact_address_safety_net(text, registry=registry)
        count += net_count

        return text, count

    # Katman 7z (Son güvenlik ağı): yapısal adres kalıpları ve bağlam koruma kümeleri
    _SN_LOC_RE = re.compile(
        r'(?i)(?<![A-Za-zÇĞİÖŞÜçğıöşü])(?:'
        r'Mahalle(?:s[iİıI])?|Mah\.?|Mh\.?|'
        r'Köy(?:[üÜ])?|'
        r'Mevk[iİıI]{1,2}|'
        r'Mezra(?:s[ıiIİ])?|'
        r'S[iİıI]tes[iİıI]|'
        r'Apartman[ıiIİ]?|Apt\.?|'
        r'Blok|'
        r'Küme[ \t]+Evler[iİıI]|'
        r'Tok[iİıI][ \t]+Evler[iİıI]|'
        r'Bulvar[ıiIİ]?|Bulv\.?|Blv\.?|'
        r'Cadde(?:s[iİıI])?|Cad\.?|Cd\.?|'
        r'Sokak|Sokağ[ıiIİ]|Sok\.?|Sk\.?|5k\.?'
        r')(?![A-Za-zÇĞİÖŞÜçğıöşü])'
    )
    _SN_NUM_RE = re.compile(
        r'(?i)(?:'
        r'(?<![A-Za-zÇĞİÖŞÜçğıöşü])(?:'
        r'(?:No|Nu|Numara|(?:[İiIıl]ç[ \t]*)?Kap[ıiIİ](?:[ \t]*No)?|Daire|Kat)[ \t]*[:.]?[ \t]*\d+[A-Za-z]?(?:[ \t]*/[ \t]*[0-9A-Za-z]+)?'
        r'|[ND][ \t]*[:.][ \t]*\d+[A-Za-z]?(?:[ \t]*/[ \t]*[0-9A-Za-z]+)?'
        r'|K(?![ \t]*[:.][ \t]*(?:19|20)\d{2}[ \t]*/)[ \t]*[:.][ \t]*\d+[A-Za-z]?(?:[ \t]*/[ \t]*[0-9A-Za-z]+)?'
        r')(?![A-Za-zÇĞİÖŞÜçğıöşü])'
        r'|'
        r'(?<![\d/])\d{1,4}[ \t]*/[ \t]*\d{1,3}(?![\d/])'
        r'(?![ \t]*(?:E\b|E\.|Esas|K\.|Karar|say[ıiIİ]l[ıiIİ]\b|oran\w*|hisse\w*|pay\w*))'
        r')'
    )
    _SN_NON_DOOR_PRE_RE = re.compile(
        r'(?i)(?:evrak|dosya|esas|karar|say[ıiIİ]|dava|belge|protokol|takip|talimat|soruşturma|'
        r'hazırlık|poliçe|acente|cilt|aile[ \t]*s[ıiIİ]ra|birey[ \t]*s[ıiIİ]ra|s[ıiIİ]ra|hane|'
        r'sicil|vergi|kimlik|pasaport|ruhsat|plaka|fatura|makbuz|yevmiye|tutanak|rapor|'
        r'sayfa|madde|f[ıiIİ]kra|bent|(?:^|[\s,;(\|])[EK][ \t]*[:.]?)[ \t]*$'
    )
    _SN_NUFUS_SPAN_RE = re.compile(
        r'(?i)\bcilt\b|aile[ \t]*s[ıiIİ]ra|\bnk\.?[ \t]*lu\b|\bBSN\b|mah\.?[ \t]*/[ \t]*köy|köy[ \t]*/[ \t]*mahalles[iİıI]'
    )
    _SN_EXPLICIT_DOOR_RE = re.compile(
        r'(?i)(?<![A-Za-zÇĞİÖŞÜçğıöşü])(?:'
        r'(?:No|Nu|Numara|(?:[İiIıl]ç[ \t]*)?Kap[ıiIİ](?:[ \t]*No)?|Daire|Kat)[ \t]*[:.]?[ \t]*\d'
        r'|[NDK][ \t]*[:.][ \t]*\d'
        r')'
    )
    _SN_CTX_WORDS = frozenset({
        "adres", "adresi", "adresinin", "adresinde", "adresine", "adresini", "adresleri", "adresler",
        "ikamet", "ikametgah", "ikametgâh", "tebligat", "yakalama", "işyeri", "açık", "mernis",
        "nüfus", "nüfusa", "nüfusunda", "nüfusuna",
        "kayıtlı", "kayıtlıdır", "doğumlu", "halen", "ve", "ile", "veya", "ya", "da", "de",
        "olup", "olan", "olduğu", "olması", "eden", "oturan", "oturur", "bulunan", "belirtilen",
        "yazılı", "bildirilen", "tespit", "edilen", "gösterilen", "geçen", "bulunulan",
        "küçüğün", "çocuğun", "davacı", "davacının", "davalı", "davalının",
        "sanık", "sanığın", "şüpheli", "şüphelinin", "müşteki", "müştekinin", "mağdur", "mağdurun",
        "tanık", "tanığın", "borçlu", "borçlunun", "alacaklı", "alacaklının", "muhatap", "muhatabın",
        "müvekkil", "müvekkilin", "vekil", "vekili", "avukat", "vasi", "vasisi", "kısıtlı", "kısıtlının",
        "kayyım", "kayyımın", "şahıs", "şahsın", "kişi", "kişinin", "isimli", "adlı", "taraf",
        "tarafından", "oğlu", "kızı", "anne", "baba", "doğum", "tarih", "tarihli", "sayılı",
        "mahkeme", "mahkemesi", "mahkememizin", "mahkemesine", "adliye", "müdürlüğü", "başkanlığı",
        "karar", "esas", "dosya", "evrak", "tutanak", "rapor", "bilgi", "bilgisi", "il", "ili",
        "ilçe", "ilçesi", "mahalle", "mahallesi", "köy", "köyü", "sokak", "cadde", "bulvar",
        "kat", "daire", "blok", "no", "sgk", "ptt", "tc", "tckn", "iban", "hmk", "tmk", "tck",
        "cmk", "tbk", "iik", "tel", "telefon", "gsm", "cep", "faks", "verildi", "oldu",
        "mail", "kep", "ek", "sayfa", "saat", "madde", "tl", "eur", "usd", "adet",
    })
    _SN_CLAUSE_STOP_WORDS = frozenset({
        "adresinde", "adresine", "adresinden", "adresini", "adresleri", "ikamet", "oturur",
        "oturduğu", "olup", "olduğu", "olması", "olduğundan", "bulunduğu", "bulunan",
        "yaşamadığı", "yaşadığı", "denilerek", "gereğince", "nedeniyle", "sebebiyle",
        "hakkında", "üzerine", "tarafından", "madde", "maddesi", "maddeleri", "kanun",
        "hüküm", "hükümleri", "saklı", "muhtarlık", "muhtarlığı", "muhtarlığından",
        "alınan", "aldığı", "gönderilen", "tarihli", "sayılı", "mahkememiz", "mahkememizin",
        "mahkemesine", "mahkemesi", "dosyası", "anne", "baba", "doğum", "nüfus", "tc",
        "tckn", "tel", "telefon", "gsm", "cep", "faks", "mail", "kep", "vekil", "vekili",
        "müdafi", "müdafii", "baro", "meslek", "suçun", "aranmıyor", "beyan", "tescil",
        "taşınma", "hmk", "tmk", "tbk", "iik", "tck", "cmk",
    })
    _SN_ADDR_KEEP_LOWER = frozenset({"ve", "ile", "mah", "mh", "sk", "sok", "cad", "cd", "blv", "bulv", "apt", "no", "nu", "d", "k", "iç"})
    _SN_LINK_DEST_RE = re.compile(r'\]\((?:<[^>\n]*>|[^)\n]*)\)')
    _SN_TAIL_SLASH_RE = re.compile(
        r'^(?:[ \t]*[,-])?[ \t]*(?:[A-ZÇĞİÖŞÜ][a-zçğıöşü]+[ \t]+)?'
        r'[A-ZÇĞİÖŞÜa-zçğıöşü]{2,25}[ \t]*/[ \t]*[A-ZÇĞİÖŞÜa-zçğıöşü]{2,25}(?![A-Za-zÇĞİÖŞÜçğıöşü])'
    )
    _SN_TAIL_SPACE_RE = re.compile(
        r'^(?:[ \t]*[,-])?[ \t]*[A-ZÇĞİÖŞÜ][a-zçğıöşü]{2,20}[ \t]+[A-ZÇĞİÖŞÜ]{3,20}(?![A-Za-zÇĞİÖŞÜçğıöşü])'
    )
    _SN_TAIL_CITY_RE = re.compile(
        r'^(?:[ \t]*[,-])?[ \t]*(?P<city>[A-ZÇĞİÖŞÜ][a-zçğıöşü]{2,20}|[A-ZÇĞİÖŞÜ]{3,20})'
        r'(?=[ \t]+(?:adres\w*|ikamet|oturur|olup|olduğu|olması)\b|[ \t]*(?:["”\)\.,;\-:]|\r?\n|$))'
    )
    _SN_NEXTLINE_TAIL_RE = re.compile(
        r'^[ \t]*\r?\n[ \t]*(?:(?:K|Kat|D|Daire|Blok|İç[ \t]*Kap[ıi](?:[ \t]*No)?)[ \t:.]*[0-9A-Za-z]{1,4}[ \t]+)*'
        r'(?:[A-ZÇĞİÖŞÜ][a-zçğıöşü]+[ \t]+)?[A-ZÇĞİÖŞÜa-zçğıöşü]{2,25}[ \t]*/[ \t]*[A-ZÇĞİÖŞÜa-zçğıöşü]{2,25}'
        r'(?=[ \t]+(?:adres\w*|ikamet|oturur|olup|olduğu|olması)\b|[ \t]*(?:["”\)\.,;]|\r?\n|$))'
    )

    @classmethod
    def _sn_is_stop_word(cls, tok: str) -> bool:
        low = _tr_lower(tok.strip(".,;:!?\"'“”()[]"))
        return low in cls._SN_CLAUSE_STOP_WORDS or low in cls._SN_CTX_WORDS

    @classmethod
    def _sn_expand_start(cls, text: str, ls: int, anchor_pos: int, min_pos: int) -> int:
        """(A) belirtecinden önceki en çok 2 yer adı sözcüğünü aralığa alır; bağlam sözcükleri ve
        noktalama/tırnak/parantez açılışında durur. Satır başında 0 sözcük varsa önceki satır sonuna
        düşen tek sözcüklü yer adını da bağlar."""
        pos = anchor_pos
        words = 0
        stop_chars = set('":;|/“”()[]*#\r\n!?')
        while words < 2 and pos > min_pos:
            j = pos
            while j > min_pos and text[j - 1] in " \t":
                j -= 1
            if j <= min_pos or text[j - 1] in stop_chars or text[j - 1] == ",":
                break
            if j > min_pos and text[j - 1] == "-":
                # "ALİ VELİ - Deneme Mah." gibi ayırıcı tirede dur; bitişik "A-1" içinde devam et
                if j - 2 >= min_pos and text[j - 2] in " \t":
                    break
            k = j
            while k > min_pos and text[k - 1] not in " \t" and text[k - 1] not in stop_chars and text[k - 1] != ",":
                k -= 1
            tok = text[k:j]
            if not tok:
                break
            # Sözcük sonu nokta yalnızca "5." / "123." gibi cadde/sokak numarasıysa adrese dahildir
            if tok.endswith(".") and not tok[:-1].isdigit():
                break
            if re.fullmatch(r'\d{1,2}[./]\d{1,2}[./]\d{2,4}', tok):
                break
            low = _tr_lower(tok.rstrip(".,"))
            if low in cls._SN_CTX_WORDS or low in cls._SN_CLAUSE_STOP_WORDS:
                break
            pos = k
            words += 1

        # Satır başında (önünde hiç sözcük yoksa) önceki satır sonuna taşan tek sözcüklü yer adı
        if words == 0 and re.fullmatch(r'[ \t#*]*', text[ls:anchor_pos]) and ls > 0:
            prev_end = ls - 1
            if prev_end > 0 and text[prev_end - 1] == "\r":
                prev_end -= 1
            prev_ls = text.rfind("\n", 0, prev_end) + 1
            prev_line = text[prev_ls:prev_end]
            m = re.search(r'(?P<pre>.*?)(?P<w>[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü]+)[ \t]*$', prev_line)
            if m:
                w = m.group("w")
                low_w = _tr_lower(w)
                if low_w not in cls._SN_CTX_WORDS and low_w not in cls._SN_CLAUSE_STOP_WORDS:
                    # Önceki sözcük de büyük harfli bağlam-dışı sözcükse ("ALİ VELİ\n...") kişi adıdır
                    pre_m = re.search(r'([A-Za-zÇĞİÖŞÜçğıöşü]+)[ \t]*$', m.group("pre"))
                    if not (pre_m and pre_m.group(1)[0].isupper() and _tr_lower(pre_m.group(1)) not in cls._SN_CTX_WORDS):
                        return prev_ls + m.start("w")
        return pos

    @classmethod
    def _sn_extend_tail(cls, text: str, pos: int, le: int) -> int:
        """(B) sonrasında en çok D:/K:/Daire/Kat/İç Kapı No + İlçe/İL ve varsa satır sonu devamını alır."""
        cur = pos
        # Ek daire/kat/blok parçaları
        extra_re = re.compile(
            r'(?i)^(?:[ \t]*[,/]?[ \t]*(?:'
            r'(?:[İiIıl]ç[ \t]*Kap[ıi](?:[ \t]*No)?|Kap[ıi][ \t]*No|Daire|Kat|Blok)[ \t]*[:.]?[ \t]*[0-9A-Za-z]{1,4}'
            r'|[DK][ \t]*[:.][ \t]*[0-9A-Za-z]{1,4}'
            r')(?:[ \t]*/[ \t]*[0-9A-Za-z]+)?)+'
        )
        m_ext = extra_re.match(text[cur:le])
        if m_ext:
            cur += m_ext.end()

        seg = text[cur:le]
        m_tail = cls._SN_TAIL_SLASH_RE.match(seg) or cls._SN_TAIL_SPACE_RE.match(seg)
        if m_tail:
            # Yakalanan kelimeler durak sözcüğü değilse ekle
            tail_words = re.findall(r'[A-Za-zÇĞİÖŞÜçğıöşü]+', m_tail.group(0))
            if tail_words and not any(_tr_lower(w) in cls._SN_CLAUSE_STOP_WORDS or _tr_lower(w) in cls._SN_CTX_WORDS for w in tail_words):
                cur += m_tail.end()
        else:
            m_city = cls._SN_TAIL_CITY_RE.match(seg)
            if m_city:
                c_low = _tr_lower(m_city.group("city"))
                if c_low not in cls._SN_CLAUSE_STOP_WORDS and c_low not in cls._SN_CTX_WORDS:
                    cur += m_city.end()

        # Satır sonu devamı ("Burdur\nMerkez/ BURDUR")
        m_nl = cls._SN_NEXTLINE_TAIL_RE.match(text[cur:])
        if m_nl and not re.search(cls.MASK_ANY_RE, m_nl.group(0)):
            cur += m_nl.end()
        return cur

    @classmethod
    def _sn_scan_forward(cls, text: str, anchor_start: int, anchor_end: int, le: int, anchor_is_num: bool) -> Optional[int]:
        """Çapadan satır sonuna dek tarar; (A)+(B) çifti oluşursa güvenli bitiş konumunu döndürür."""
        saw_num = anchor_is_num
        saw_loc = not anchor_is_num
        last_addr_end = anchor_end
        cur = anchor_end
        paren_depth = 0
        lower_run = 0
        hard_stops = set('"\u201d;!?[\r\n')

        while cur < le:
            ch = text[cur]
            if ch in hard_stops:
                break
            if ch == "|" and not text.startswith("|¢", cur):
                break
            if ch == "(":
                paren_depth += 1
                if paren_depth > 1:
                    return None
                cur += 1
                continue
            if ch == ")":
                if paren_depth == 0:
                    break
                paren_depth -= 1
                cur += 1
                continue
            if ch in " \t":
                cur += 1
                continue
            if ch == ":":
                # Bir adres belirteci hemen ":" ile bitiyorsa ("Apartmanı: ...") çapa etikettir
                if not saw_num:
                    return None
                break
            if ch == ",":
                rest_after = text[cur + 1:le].lstrip(" \t")
                if not rest_after:
                    break
                if re.match(r'(?i)^(?:[EK][ \t]*[:.]|Esas|Karar|(?:19|20)\d{2}[ \t]*/[ \t]*\d+[ \t]*(?:E|K)\b)', rest_after):
                    break
                first_w_m = re.match(r'[A-Za-zÇĞİÖŞÜçğıöşü]+', rest_after)
                if first_w_m:
                    fw = first_w_m.group(0)
                    if _tr_lower(fw) in cls._SN_CLAUSE_STOP_WORDS or _tr_lower(fw) in cls._SN_CTX_WORDS:
                        break
                    if fw[0].islower() and not (cls._SN_LOC_RE.match(rest_after) or cls._SN_NUM_RE.match(rest_after)):
                        break
                # Virgülden sonra yeni bir (A)/(B) bileşeni yoksa ve saw_num zaten True ise kuyruk kontrolüne geç
                if saw_num and saw_loc:
                    ahead = rest_after[:80]
                    has_more_struct = bool(cls._SN_LOC_RE.search(ahead) or cls._SN_NUM_RE.search(ahead))
                    if not has_more_struct:
                        break
                cur += 1
                continue

            # Önce (B) veya (A) eşleşmesi kontrolü
            m_num = cls._SN_NUM_RE.match(text, cur, le)
            if m_num and not cls._SN_NON_DOOR_PRE_RE.search(text[anchor_start:cur]):
                saw_num = True
                cur = m_num.end()
                last_addr_end = cur
                lower_run = 0
                continue

            m_loc = cls._SN_LOC_RE.match(text, cur, le)
            if m_loc:
                # "Apartmanı:" gibi etiket başlığıysa dur
                if cur > anchor_start and text[m_loc.end():m_loc.end() + 1] == ":":
                    break
                saw_loc = True
                cur = m_loc.end()
                last_addr_end = cur
                lower_run = 0
                continue

            # Zaten hem (A) hem (B) görüldüyse: devamında bir (A)/(B) daha yoksa kuyruk uzantısında kes
            if saw_num and saw_loc and paren_depth == 0:
                rest_seg = text[cur:le]
                # Küçük bir ek bileşen veya sonraki (A)/(B) varsa en çok 40 karakter içinde ara
                m_tail_cand = cls._SN_TAIL_SLASH_RE.match(rest_seg) or cls._SN_TAIL_SPACE_RE.match(rest_seg) or cls._SN_TAIL_CITY_RE.match(rest_seg)
                if m_tail_cand:
                    break
                ahead_chunk = rest_seg.split(",", 1)[0]
                if not (len(ahead_chunk) <= 45 and (cls._SN_LOC_RE.search(ahead_chunk) or cls._SN_NUM_RE.search(ahead_chunk))):
                    break

            # Normal sözcük / noktalama adımı
            m_tok = re.match(r'[^\s,;:"\u201d!?()\[\]|]+', text[cur:le])
            if not m_tok:
                cur += 1
                continue
            tok = m_tok.group(0)
            low_tok = _tr_lower(tok.rstrip("."))
            if paren_depth == 0 and (low_tok in cls._SN_CLAUSE_STOP_WORDS):
                break
            if tok.endswith(".") and not tok[:-1].isdigit():
                if low_tok not in cls._SN_ADDR_KEEP_LOWER:
                    # Cümle sonu noktası
                    break
            if re.fullmatch(r'[a-zçğıöşü]+', tok) and low_tok not in cls._SN_ADDR_KEEP_LOWER:
                lower_run += 1
                if not (saw_num and saw_loc) and lower_run >= 3:
                    return None
            else:
                lower_run = 0
            if not (saw_num and saw_loc) and (cur - anchor_start) > 120:
                return None
            cur += len(tok)

        if not (saw_num and saw_loc):
            return None
        return cls._sn_extend_tail(text, last_addr_end, le)

    @classmethod
    def redact_address_safety_net(cls, text: str, registry: Optional[MaskRegistry] = None) -> Tuple[str, int]:
        """
        Katman 7z (Son güvenlik ağı): Önceki adres katmanlarından sızan, yapısal olarak açık adrese
        benzeyen (yerleşim/yol belirteci + kapı/konum numarası içeren) parçaları ve mevcut [ADRES_n]
        etiketlerinin hemen önündeki/ardındaki açık yer adı artıklarını maskeler.
        Kurum, olay yeri, HTS/koordinat, nüfus kayıt şablonu ve kaza lejantına dokunmaz.
        """
        if not text:
            return text, 0
        count = 0

        # 1. Mevcut [ADRES_...] etiketlerinin hemen arkasındaki "/ İL" veya satır-sonu "İlçe/İL" artığı
        non_city = {"tel", "gsm", "cep", "faks", "tc", "tckn", "iban", "tarih", "saat",
                    "esas", "karar", "madde", "tl", "eur", "usd", "adet", "no", "sayfa", "ek", "ve", "veya"}
        after_slash_re = re.compile(
            r'(?P<lab>' + cls.MASK_ADRES_RE + r')(?P<hint>[ \t]+\([^)\r\n]+\))?[ \t]*/[ \t]*(?P<city>[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü]{1,24})'
            r'(?![A-Za-zÇĞİÖŞÜçğıöşü]|[ \t]*:)'
        )

        def repl_after_slash(m: re.Match) -> str:
            nonlocal count
            if _tr_lower(m.group("city")) in non_city:
                return m.group(0)
            count += 1
            if m.group("hint"):
                return f"{m.group('lab')}{m.group('hint')}"
            return m.group("lab")

        text = after_slash_re.sub(repl_after_slash, text)

        after_nl_re = re.compile(
            r'(?P<lab>' + cls.MASK_ADRES_RE + r')(?P<hint>[ \t]+\([^)\r\n]+\))?[ \t]*\r?\n[ \t]*'
            r'(?:(?:K|Kat|D|Daire|Blok|İç[ \t]*Kap[ıi](?:[ \t]*No)?)[ \t:.]*[0-9A-Za-z]{1,4}[ \t]+)*'
            r'(?:[A-ZÇĞİÖŞÜ][a-zçğıöşü]+[ \t]+)?[A-ZÇĞİÖŞÜa-zçğıöşü]{2,25}[ \t]*/[ \t]*[A-ZÇĞİÖŞÜa-zçğıöşü]{2,25}'
            r'(?=[ \t]+(?:adres\w*|ikamet|oturur|olup|olduğu|olması)\b|[ \t]*(?:["”\)\.,;]|\r?\n|$))'
        )

        def repl_after_nl(m: re.Match) -> str:
            nonlocal count
            hint = m.group("hint") or ""
            tail_part = m.group(0)[len(m.group("lab")) + len(hint):]
            if re.search(cls.MASK_ANY_RE, tail_part):
                return m.group(0)
            count += 1
            if hint:
                return f"{m.group('lab')}{hint}"
            return cls._format_adres_label(m.group("lab"), tail_part, registry)

        text = after_nl_re.sub(repl_after_nl, text)

        # 2. Mevcut [ADRES_...] etiketinin hemen önündeki tek büyük-harf başlangıçlı yer adı ("Taşoluk [ADRES_3]")
        pre_place_re = re.compile(
            r'(?P<word>(?:[A-ZÇĞİÖŞÜ][a-zçğıöşü]+|[A-ZÇĞİÖŞÜ]{3,}))[ \t]+(?P<lab>' + cls.MASK_ADRES_RE + r')'
        )

        def repl_pre_place(m: re.Match) -> str:
            nonlocal count
            word = m.group("word")
            if _tr_lower(word) in cls._SN_CTX_WORDS or _tr_lower(word) in cls._SN_CLAUSE_STOP_WORDS:
                return m.group(0)
            ls = text.rfind("\n", 0, m.start("word")) + 1
            before = text[ls:m.start("word")]
            prev_m = re.search(r'([A-Za-zÇĞİÖŞÜçğıöşü]+)[ \t]+$', before)
            if prev_m:
                pw = prev_m.group(1)
                if pw[0].isupper() and _tr_lower(pw) not in cls._SN_CTX_WORDS and _tr_lower(pw) not in cls._SN_CLAUSE_STOP_WORDS:
                    return m.group(0)
            count += 1
            return m.group("lab")

        text = pre_place_re.sub(repl_pre_place, text)

        # 3. Yapısal (A)+(B) güvenlik ağı geçişi
        protected_spans = [(m.start(), m.end()) for m in re.finditer(cls.MASK_ANY_RE, text)]
        protected_spans.extend(
            (m.start(), m.end()) for m in re.finditer(r'\[ADRES_\d+\][ \t]+\([^)\r\n]+\)', text)
        )
        protected_spans.extend((m.start(), m.end()) for m in cls._SN_LINK_DEST_RE.finditer(text))

        def _in_protected(s: int, e: int) -> bool:
            return any(s < pe and e > ps for ps, pe in protected_spans)

        replacements: List[Tuple[int, int, str]] = []
        pos = 0
        n = len(text)
        last_claimed_end = 0

        while pos < n:
            le = text.find("\n", pos)
            if le == -1:
                le = n
            line_end = le - 1 if (le > pos and text[le - 1] == "\r") else le
            line = text[pos:line_end]

            if cls._SN_LOC_RE.search(line) and cls._SN_NUM_RE.search(line):
                anchors: List[Tuple[int, int, bool]] = []
                for m in cls._SN_LOC_RE.finditer(line):
                    s, e = pos + m.start(), pos + m.end()
                    if not _in_protected(s, e):
                        anchors.append((s, e, False))
                for m in cls._SN_NUM_RE.finditer(line):
                    s, e = pos + m.start(), pos + m.end()
                    if not _in_protected(s, e) and not cls._SN_NON_DOOR_PRE_RE.search(text[pos:s]):
                        anchors.append((s, e, True))
                anchors.sort(key=lambda x: x[0])

                cursor = max(pos, last_claimed_end)
                for a_s, a_e, is_num in anchors:
                    if a_s < cursor:
                        continue
                    cand_end = cls._sn_scan_forward(text, a_s, a_e, line_end, is_num)
                    if cand_end is None:
                        continue
                    cand_start = cls._sn_expand_start(text, pos, a_s, cursor)
                    cand = text[cand_start:cand_end].strip()
                    if not cand or _in_protected(cand_start, cand_end) or re.search(cls.MASK_ANY_RE, cand):
                        continue
                    # Nüfus kayıt şablonu aralık içindeyse veya satırda şablon olup kapı numarası yoksa koru
                    if cls._SN_NUFUS_SPAN_RE.search(cand):
                        continue
                    if cls._SN_NUFUS_SPAN_RE.search(line) and not cls._SN_EXPLICIT_DOOR_RE.search(cand):
                        continue
                    if cls._skip_address(text, cand_start, cand_end, cand):
                        continue
                    replacements.append((cand_start, cand_end, cls._mask("adres", cand, registry)))
                    count += 1
                    cursor = cand_end
                    last_claimed_end = max(last_claimed_end, cand_end)

            pos = le + 1

        if replacements:
            out_parts: List[str] = []
            prev_i = 0
            for rs, re_end, lab in replacements:
                if rs < prev_i:
                    continue
                out_parts.append(text[prev_i:rs])
                out_parts.append(lab)
                prev_i = re_end
            out_parts.append(text[prev_i:])
            text = "".join(out_parts)

        return text, count

    # -----------------------------------------------------------------------
    # Katman 8: Gerçek kişi ad-soyad keşfi (ön tarama) ve rol etiketli takma ad
    # -----------------------------------------------------------------------

    _ID_FULL_RE = re.compile(
        r'^[*#>\-\s|]*(?:Ad[ıi][ \t]*(?:ve[ \t]*)?Soyad[ıi]|Ad[ \t]*Soyad|Ad[ıi][ \t]*-[ \t]*Soyad[ıi]|'
        r'[İI]sim[ \t]*Soyisim|Tam[ \t]*Ad[ıi])[ \t]*[:|][ \t]*(?P<rest>.+)$',
        re.IGNORECASE,
    )
    _ID_FIRST_RE = re.compile(
        r'^[*#>\-\s|]*(?:Ad[ıi]|[İI]lk[ \t]*Ad[ıi])[ \t]*[:|][ \t]*(?P<rest>.+)$',
        re.IGNORECASE,
    )
    _ID_LAST_RE = re.compile(
        r'^[*#>\-\s|]*Soyad[ıi][ \t]*[:|][ \t]*(?P<rest>.+)$',
        re.IGNORECASE,
    )
    _ID_SAME_LINE_SPLIT_RE = re.compile(
        r'(?<![A-Za-zÇĞİÖŞÜçğıöşüâîû])(?:Ad[ıi]|[İI]lk[ \t]*Ad[ıi])[ \t]*[:|][ \t]*'
        r'(?P<fn>' + _CAP_TOK_RE_STR + r'(?:[ \t]+' + _CAP_TOK_RE_STR + r')?)[ \t]+'
        r'Soyad[ıi][ \t]*[:|][ \t]*(?P<ln>' + _CAP_TOK_RE_STR + r'(?:[ \t]+' + _CAP_TOK_RE_STR + r')?)',
        re.IGNORECASE,
    )
    _HEADER_COLON_RE = re.compile(
        r'^(?:[#>*\-\s]|\d{1,2}[.\)])*(?:\*\*|__)?(?P<hdr>[A-Za-zÇĞİÖŞÜçğıöşüâîûÂÎÛ/\-\s().]{2,50}?)(?:\*\*|__)?[ \t]*:[ \t]*(?:\*\*|__)?(?P<rest>.*)$'
    )
    _LIST_ITEM_START_RE = re.compile(r'^[ \t]*(?:\*\*)?\d{1,2}[ \t]*[.\-\)]+[ \t]*(?:\*\*)?(?P<rest>.+)$')
    _INLINE_SPLIT_RE = re.compile(r'(?:^|[ \t]+)(?:\*\*)?\d{1,2}[ \t]*[.\-\)]+[ \t]*(?:\*\*)?')
    _PROSE_ROLE_RE = re.compile(
        r'(?<![A-Za-zÇĞİÖŞÜçğıöşüâîûÂÎÛ])'
        r'(?i:(?P<role>(?:kar[şs][ıiı][ \t]+)?(?:davac[ıiIİ]|daval[ıiIİ])|m[uü][şs]tek[iıİ]|[şs][iıİ]k[aâ]yet[çc][iıİ]|m[uü]racaat[çc][ıiIİ]|'
        r'[şs][uü]phel[iıİ]|san[ıiIİ]k|kat[ıiIİ]lan|m[uü]dah[iıİ]l|ma[ğg]dur|tan[ıiIİ]k|alacakl[ıiIİ]|bor[çc]lu|'
        r'a\.?s\.?[cç]\.?|adli[ \t]+s[uü]re[cç]teki[ \t]+[çc]ocuk|s\.?s\.?[cç]\.?|su[çc]a[ \t]+s[uü]r[uü]klenen[ \t]+[çc]ocuk)'
        r'(?:[ \t]+s[ıiIİ]fat[ıiIİ]yla)?)'
        r'(?:[ \t]+(?i:m[uü]vekk[iıİ]l(?:e|im|imiz)?|k[uü][çc][uü]k|muris|merhum[e]?|m[uü]teveffa))?'
        r'[ \t]+(?P<name>' + _CAP_TOK_RE_STR + r'(?:[ \t]+' + _CAP_TOK_RE_STR + r'){1,3})'
    )
    _PROSE_KIN_RE = re.compile(
        r'(?<![A-Za-zÇĞİÖŞÜçğıöşüâîûÂÎÛ])'
        r'(?i:(?:m[uü][şs]terek|ortak)[ \t]+[çc]ocuk(?:lar[ıiIİ])?(?:[ \t]+olan)?|'
        r'[çc]ocu[ğg]u|k[uü][çc][uü]k|o[ğg]lu|k[ıiIİ]z[ıiIİ]|e[şs]i|annesi|babas[ıiIİ]|karde[şs]i|'
        r'a[ğg]abeyi|ablas[ıiIİ]|torunu|kay[ıiIİ]nvalidesi|kay[ıiIİ]npederi|kom[şs]usu|(?:i[şs][ \t]+)?arkada[şs][ıiIİ])'
        r'[ \t]+(?P<name>' + _CAP_TOK_RE_STR + r'(?:[ \t]+' + _CAP_TOK_RE_STR + r'){1,3})'
    )
    _PROSE_ISIMLI_RE = re.compile(
        r'(?<![A-Za-zÇĞİÖŞÜçğıöşüâîûÂÎÛ])'
        r'(?P<name>' + _CAP_TOK_RE_STR + r'(?:[ \t]+' + _CAP_TOK_RE_STR + r'){1,3})'
        r'(?=[ \t]+(?i:(?:isimli|adl[ıiIİ]|ad[ıiIİ]nda)[ \t]+(?:(?:bir[ \t]+adet[ \t]+)?(?:m[uü][şs]terek[ \t]+[çc]ocuk|ortak[ \t]+[çc]ocuk|kom[şs]u|şah[ıiIİ]s|şahs|ki[şs]i)[A-Za-zÇĞİÖŞÜçğıöşüâîûÂÎÛ]*))(?![A-Za-zÇĞİÖŞÜçğıöşüâîûÂÎÛ]))'
    )
    _JUDICIAL_PROSE_RE = re.compile(
        r'(?<![A-Za-zÇĞİÖŞÜçğıöşüâîûÂÎÛ])'
        r'(?P<role>(?i:'
        r'(?:(?:ba[şs]kan|[üu]ye)[ \t]+)?h[aâ]k[iı]m[iı]?|h[aâ]k[iı]m[ \t]+[üu]ye|'
        r'(?:(?:cumhuriyet|soru[şs]turma|n[öo]bet[çc]i|bili[şs]im[ \t]+su[çc]lar[ıi])[ \t]+)?'
        r'(?:ba[şs])?savc[ıi](?:s[ıi])?(?:[ \t]+vekil[iı])?|'
        r'c\.[ \t]*savc[ıi]s[ıi]?|'
        r'(?:(?:zab[ıi]t|duru[şs]ma)[ \t]+|z\.[ \t]*)?k[aâ]t[iı][bp][iı]?'
        r'))'
        r'(?:[ \t\*_]*:[ \t\*_]*|[ \t]+)'
        r'(?P<name>' + _CAP_TOK_RE_STR + r'(?:[ \t]+' + _CAP_TOK_RE_STR + r'){1,3})'
        r'(?P<after>(?:[ \t]*\((?:(?i:sicil)[ \t]*[:=]?\s*)?\d{4,7}\)|[ \t]+\d{4,7}(?![\d/\.])|[ \t]*\[SİCİL_(?:\d+|GİZLENDİ)\])?)',
    )
    _JUDICIAL_LEADING_STRIP_RE = re.compile(
        r'^(?:ba[şs]kan[ \t]+|[üu]ye[ \t]+|'
        r'h[aâ]k[iı]m[iı]?[ \t]+|'
        r'(?:(?:cumhuriyet|soru[şs]turma|n[öo]bet[çc]i|bili[şs]im[ \t]+su[çc]lar[ıi])[ \t]+)?'
        r'(?:ba[şs])?savc[ıi](?:s[ıi])?(?:[ \t]+vekil[iı])?[ \t]+|'
        r'c\.[ \t]*savc[ıi]s[ıi]?[ \t]+|'
        r'(?:(?:zab[ıi]t|duru[şs]ma)[ \t]+|z\.[ \t]*)?k[aâ]t[iı][bp][iı]?[ \t]+)+',
        re.IGNORECASE,
    )
    _TCKN_ANCHOR_RE = re.compile(
        r'(?:[,;\-\u2013\u2014(/]?[ \t]*)'
        r'(?:T\.?[ \t]*C\.?[ \t]*(?:Kimlik[ \t]*)?(?:No|Numaras[ıi])?|TCKN|T\.?C\.?K\.?N\.?|YKN|Kimlik[ \t]*No)'
        r'[ \t]*[:.]?[ \t]*(?:(?P<tckn>[0-9lIOo|\*\-]{6,})|\[TCKN_)'
    )

    _JSON_NAME_KEYS = frozenset({
        "ad", "adsoyad", "adisoyadi", "adi_soyadi", "ad_soyad", "isim", "tarafadi", "taraf_adi", "taraf",
    })
    _JSON_ROLE_KEYS = frozenset({
        "sifat", "sifati", "rol", "tarafsifati", "taraf_sifati",
    })
    _JSON_SURNAME_KEYS = frozenset({"soyad", "soyadi"})

    @classmethod
    def _passes_ocr_name_filter(cls, candidate: str, after_ctx: str = "", allow_short_last: bool = False) -> bool:
        """OCR gürültüsüne karşı ek kesinlik süzgeci: >=3 harf/belirteç, 3+ harf tekrarı ve rakam karışımı reddi."""
        clean = " ".join(unicodedata.normalize("NFC", candidate).strip().split())
        toks = clean.split()
        if not toks:
            return False
        for idx, t in enumerate(toks):
            min_len = 2 if (allow_short_last and idx == len(toks) - 1 and len(toks) >= 2 and any(len(p) >= 3 for p in toks[:-1])) else 3
            if len(t) < min_len:
                return False
            if re.search(r'(.)\1\1', _tr_lower(t)):
                return False
        if after_ctx and re.match(r'^\d+[A-Za-zÇĞİÖŞÜçğıöşüâîûÂÎÛ]', after_ctx):
            return False
        return True

    @classmethod
    def _is_person_name(
        cls,
        candidate: str,
        before_ctx: str = "",
        after_ctx: str = "",
        ocr: bool = False,
        allow_judicial_pre_title: bool = False,
    ) -> bool:
        """Aday ad-soyad dizisinin tüm kesinlik kurallarına uyup uymadığını denetler."""
        if not candidate:
            return False
        clean = " ".join(unicodedata.normalize("NFC", candidate).strip().split())
        toks = clean.split()
        if not (2 <= len(toks) <= 4):
            return False
        for t in toks:
            if not re.fullmatch(r'(?:[A-ZÇĞİÖŞÜÂÎÛ][a-zçğıöşüâîû]+|[A-ZÇĞİÖŞÜÂÎÛ]{2,})', t):
                return False
        ftoks = [_fold_tr(t) for t in toks]
        if any(
            ft in cls._PERSON_STOP_WORDS
            or ft in cls._PERSON_CORP_TITLE_WORDS
            or ft in cls._PLACE_STRUCTURE_WORDS
            for ft in ftoks
        ):
            return False
        if len(ftoks) == 2 and all(ft in cls._MONTH_DAY_WORDS for ft in ftoks):
            return False
        if all((_tr_lower(t) in cls._BASE_TR_VOCAB or ft in cls._FOLDED_BASE_TR_VOCAB) for t, ft in zip(toks, ftoks)):
            return False

        if cls._has_blocking_pre_title(before_ctx, allow_judicial=allow_judicial_pre_title):
            return False
        if after_ctx:
            if cls._AFTER_CORP_TITLE_RE.match(after_ctx):
                return False
            if not allow_judicial_pre_title and cls._AFTER_JUDICIAL_TITLE_RE.match(after_ctx):
                return False
            m_aw = re.match(r'^[ \t]+([A-Za-zÇĞİÖŞÜçğıöşüâîûÂÎÛ]+)', after_ctx)
            if m_aw:
                aw = _fold_tr(m_aw.group(1))
                ignored_after_titles = {"vekil", "vekili", "vekilleri"}
                if allow_judicial_pre_title:
                    ignored_after_titles |= {
                        "hakim", "hakimi", "savci", "savcisi", "katip", "katibi", "baskan", "uye",
                    }
                if aw in cls._MASK_AFTER_PLACE_CORP_WORDS or (
                    aw in cls._PERSON_CORP_TITLE_WORDS and aw not in ignored_after_titles
                ):
                    return False
        if ocr and not cls._passes_ocr_name_filter(clean, after_ctx=after_ctx):
            return False
        return True

    @classmethod
    def _has_blocking_pre_title(cls, before_ctx: str, allow_judicial: bool = False) -> bool:
        """Av./Hâkim/Vekil vb. sıfat öbeğini denetler; 'işveren vekili' istisnasını ve yargı izin modunu uygular."""
        if not before_ctx:
            return False
        if re.search(r'(?:^|[\s(\["\'*:,;\-/])isveren[ \t]+vekil(?:i|leri)?[ \t]*$', _fold_tr(before_ctx)):
            return False
        m_jud = cls._JUDICIAL_PRE_TITLE_RE.search(before_ctx)
        m_non = cls._NON_JUDICIAL_PRE_TITLE_RE.search(before_ctx)
        if m_jud and (m_non is None or m_jud.start() <= m_non.start()):
            return not allow_judicial
        return bool(m_non)

    _NON_PERSON_HEADER_WORDS = frozenset({
        "beyan", "beyani", "beyanlari", "ifade", "ifadesi", "savunma", "savunmasi",
        "dilekce", "dilekcesi", "rapor", "raporu", "tutanak", "tutanagi",
        "konu", "karar", "karari", "ozet", "ozeti", "aciklama", "aciklamalar",
        "talep", "talebi", "sonuc", "itiraz", "delil", "deliller",
    })
    _NON_JUDICIAL_HEADER_EXCL_WORDS = frozenset({
        "divan", "komisyon", "komisyonu", "yonetim", "denetim", "toplanti", "ihale",
        "juri", "secim", "dernek", "vakif", "oda", "odasi", "sendika", "kulup",
        "okul", "fakulte", "belediye", "encumen", "meclis", "sirket", "kooperatif",
        "apartman", "site",
    })
    _DOC_JUDICIAL_CTX_RE = re.compile(
        r'(?i)(?:'
        r'\bmahkeme(?:si|miz|mize|sine|ye|de|den|ce)?\b|'
        r'\b(?:cumhuriyet\s+)?(?:ba[sş])?savc[ıi](?:l[ıi][gğ][ıi](?:na|nca|nda)?|s[ıi]\b)|'
        r'\bsoru[sş]turma\s+savc[ıi]s[ıi]\b|'
        r'(?:\b(?:zab[ıi]t|duru[sş]ma|mahkeme)\s+k[aâ]tib[iı]?|\bk[aâ]ti[bp][ \t]*[:：])|'
        r'\bh[aâ]kimli[gğ][ıi]\b|'
        r'\bh[aâ]kim(?:i?\s*[:：]|[ \t]+\(?\d{4,7}\)?(?![\d./]))|'
        r'\byarg[ıi]tay\b|\bdan[ıi][sş]tay\b|\banayasa\s+mahkemesi\b|'
        r'\badli(?:ye|yesi|yarg[ıi])\b|\badalet\s+saray[ıi]\b|'
        r'\bb[öo]lge\s+(?:adliye|idare)\b|\b(?:ceza|hukuk|idari\s+dava)\s+dairesi\b|'
        r'\bduru[sş]ma\b|\btensip\b|\biddianame\b|\btefhim\b|'
        r'\besas\s*(?:no|numaras[ıi]|say[ıi]s[ıi]|[:=]\s*(?:19|20)\d{2}\s*/\s*\d+)\b|'
        r'\b(?:19|20)\d{2}\s*/\s*\d+\s*(?:E\.?|Esas|K\.?|Karar)\b'
        r')'
    )

    @classmethod
    def _is_non_judicial_header_phrase(cls, cleaned_text: str) -> bool:
        toks = set(re.findall(r'[a-z]+', _fold_tr(cleaned_text)))
        return bool(toks & cls._NON_JUDICIAL_HEADER_EXCL_WORDS)

    @classmethod
    def _extract_header_role(
        cls, header_label: str, include_judicial_headers: bool = False
    ) -> Optional[str]:
        """Başlık etiketinden taraf veya yargı rolünü çıkarır; VEKİLİ/MÜDAFİİ vb. için None döner."""
        cleaned = re.sub(r'[*_#>`"\']', '', header_label)
        folded = re.sub(r'\s+', ' ', _fold_tr(cleaned)).strip()
        if not folded:
            return None
        allow_hdr_jud = include_judicial_headers and not cls._is_non_judicial_header_phrase(folded)
        j_role = MaskRegistry.normalize_person_role(folded, include_judicial_headers=allow_hdr_jud)
        if j_role in MaskRegistry.JUDICIAL_ROLES:
            return j_role
        j_sig_role, _ = cls._parse_judicial_sig_title_line(
            cleaned, include_judicial_headers=include_judicial_headers
        )
        if j_sig_role in MaskRegistry.JUDICIAL_ROLES:
            return j_sig_role
        if any(w in folded for w in ("vekil", "mudafi", "adres", "tckn", "kimlik", "sicil", "telefon", "iban", "hesap")):
            return None
        role = MaskRegistry.normalize_person_role(folded)
        if role:
            return role
        if "davaci" in folded and "karsi davali" in folded:
            return "DAVACI"
        if "davali" in folded and "karsi davaci" in folded:
            return "DAVALI"
        if any(sep in folded for sep in ("/", "(", ")")):
            all_toks = set(re.findall(r'[a-z]+', folded))
            if all_toks & cls._NON_PERSON_HEADER_WORDS:
                return None
            for part in re.split(r'[/(),\-]+', folded):
                p = part.strip()
                if not p:
                    continue
                r_part = MaskRegistry.normalize_person_role(p)
                if r_part:
                    return r_part
                for tok in p.split():
                    r_tok = MaskRegistry.normalize_person_role(tok)
                    if r_tok:
                        return r_tok
        return None

    @classmethod
    def _strip_leading_judicial_titles(cls, text: str) -> str:
        """Yargı rolü bilinen aday metnin başındaki tekrarlı unvanı (ör. 'C. Savcısı', 'Başkan Hâkim') kırpar."""
        if not text:
            return text
        return cls._JUDICIAL_LEADING_STRIP_RE.sub("", text.lstrip(" \t*_")).strip()

    @classmethod
    def _strip_leading_descriptors(
        cls, candidate: str, initial_role: Optional[str] = None, strip_judicial: bool = False
    ) -> Tuple[str, Optional[str]]:
        """Aday adın başındaki sıfat, hitap, yakınlık ve rol belirteçlerini kırpar."""
        if strip_judicial:
            candidate = cls._strip_leading_judicial_titles(candidate)
        toks = candidate.split()
        role = initial_role
        while len(toks) >= 2:
            f0 = _fold_tr(toks[0])
            if len(toks) >= 3:
                f1 = _fold_tr(toks[1])
                if (f0, f1) in cls._LEADING_DESCRIPTOR_BIGRAMS:
                    toks = toks[2:]
                    continue
            if f0 in cls._PERSON_CORP_TITLE_WORDS:
                break
            r_lead = MaskRegistry.normalize_person_role(toks[0])
            if r_lead or f0 in cls._LEADING_DESCRIPTOR_WORDS:
                if r_lead and role is None:
                    role = r_lead
                toks = toks[1:]
            else:
                break
        return " ".join(toks), role

    @classmethod
    def _extend_after_ctx(cls, lines: List[str], idx: int, after_ctx: str) -> str:
        """Aday satır sonunda bittiyse sonraki ilk boş olmayan satırın başını after_ctx'e ekler."""
        if after_ctx and after_ctx.strip():
            return after_ctx
        for j in range(idx + 1, min(len(lines), idx + 3)):
            nxt = lines[j].strip()
            if nxt:
                if cls._HEADER_COLON_RE.match(nxt):
                    return after_ctx
                return (after_ctx or "") + " " + nxt[:120]
        return after_ctx

    @classmethod
    def _prune_corp_candidates(cls, texts: List[str], registry: MaskRegistry) -> None:
        """
        Güvenlik ağı: freeze_persons() öncesinde klasördeki herhangi bir belgede hemen
        ardından tüzel kişilik/şirket işaretiyle (ör. İthalat, Ltd., Şti., A.Ş.) geçen
        ad adaylarını kişi kaydından çıkarır.
        """
        if registry._persons_frozen or not texts or not registry._person_order:
            return
        full_corpus = "\n".join(t for t in texts if t)
        if not full_corpus:
            return
        boundary_chars = "A-Za-zÇĞİÖŞÜçğıöşüâîûÂÎÛ0-9"
        corp_abbr_rx = re.compile(
            r'^(?:A\.?[ \t]*Ş\.?|Ltd\.?(?:[ \t]*Şti\.?)?|Şti\.?|A\.?[ \t]*O\.?|Koop\.?|Inc\.?|Corp\.?|LLC)'
            r'(?![A-Za-zÇĞİÖŞÜçğıöşü])',
            re.IGNORECASE,
        )
        corp_word_rx = re.compile(r'^([A-ZÇĞİÖŞÜÂÎÛ][A-Za-zÇĞİÖŞÜçğıöşüâîûÂÎÛ]*)')
        to_remove: List[str] = []
        for k in list(registry._person_order):
            # Tüzel kişi güvenlik ağı yalnızca güçlü kanıtı (A/C/D/D2/E) olmayan adayları çıkarır
            if k in registry._person_strong:
                continue
            ftoks = registry._person_tokens.get(k)
            if not ftoks:
                continue
            cand_pat = r"\s+".join(registry._token_rx(t) for t in ftoks)
            probe_rx = re.compile(
                rf"(?<![{boundary_chars}])(?:{cand_pat})\s+([^\r\n]{{1,40}})"
            )
            for m in probe_rx.finditer(full_corpus):
                follow = m.group(1)
                if corp_abbr_rx.match(follow):
                    to_remove.append(k)
                    break
                mw = corp_word_rx.match(follow)
                if mw and _fold_tr(mw.group(1)) in cls._LEGAL_ENTITY_WORDS:
                    to_remove.append(k)
                    break
        for k in to_remove:
            registry.remove_person(k)

    @classmethod
    def _extract_corp_probe_lines(cls, text: str) -> str:
        """Bellek tavanı aşıldığında yalnızca şirket unvanı güvenlik ağının ihtiyaç duyduğu satırları çıkarır."""
        lines = text.splitlines()
        keep: Set[int] = set()
        corp_abbr_hint = re.compile(r'(?:a\.?\s*ş|ltd|şti|koop|a\.?\s*o|inc|corp|llc)\b', re.IGNORECASE)
        for idx, ln in enumerate(lines):
            fl = _fold_tr(ln)
            if (
                corp_abbr_hint.search(fl)
                or cls._AFTER_CORP_TITLE_RE.search(ln)
                or any(w in fl for w in cls._LEGAL_ENTITY_WORDS)
            ):
                if idx > 0:
                    keep.add(idx - 1)
                keep.add(idx)
        return "\n".join(lines[idx] for idx in sorted(keep))

    @classmethod
    def _extract_name_from_segment(cls, seg: str) -> Tuple[str, str]:
        """Taraf/kimlik satırı parçasından durdurma işaretine kadar aday adı ve kalan bağlamı ayırır."""
        s = seg.lstrip(" \t*_")
        stop_rx = re.compile(
            r'(?:'
            r'[(\[,;|:\.\r\n]|'
            r'\*\*|'
            r'[ \t]+-[ \t]+|'
            r'-(?=\d)|'
            r'\d|'
            r'(?<![A-Za-zÇĞİÖŞÜçğıöşü])(?:T\.?[ \t]*C\.?(?:[ \t]*Kimlik)?(?:[ \t]*No)?|TCKN|T\.?C\.?K\.?N\.?)(?![A-Za-zÇĞİÖŞÜçğıöşü])|'
            r'(?<![A-Za-zÇĞİÖŞÜçğıöşü])(?:vek[iî]l\w*|m[uü]daf[iî]\w*|ad[ıi]na|asil|olup|olduğu)(?![A-Za-zÇĞİÖŞÜçğıöşü])'
            r')',
            re.IGNORECASE,
        )
        m = stop_rx.search(s)
        if m:
            cand = s[:m.start()].strip(" \t*_/-")
            after_ctx = s[m.start():]
        else:
            cand = s.strip(" \t*_/-")
            after_ctx = ""
        return cand, after_ctx

    @classmethod
    def _find_role_above(
        cls, lines: List[str], idx: int, include_judicial_headers: bool = False
    ) -> Optional[str]:
        """
        D ve D2 kalıbı için yalnızca hemen önceki boş olmayan satıra bakar.
        O satır başka hiçbir içerik taşımayan tek başına rol başlığıysa
        ('ŞÜPHELİ', '## TANIK', 'MÜŞTEKİ:', 'HÂKİM:') rolü döndürür; aksi halde None (-> [KİŞİ_n]).
        """
        for j in range(idx - 1, -1, -1):
            ln = lines[j].strip()
            if not ln:
                continue
            # İlk boş olmayan satır bulundu; tek başına rol başlığı mı denetle
            if ":" in ln:
                m_h = cls._HEADER_COLON_RE.match(ln)
                if not m_h:
                    return None
                hdr = m_h.group("hdr")
                rest = re.sub(r'[*_#>`"\'\s]+', '', m_h.group("rest") or "")
                if rest:
                    return None
                j_role = cls._extract_header_role(hdr, include_judicial_headers=include_judicial_headers)
                if j_role in MaskRegistry.JUDICIAL_ROLES:
                    return j_role
                hf = _fold_tr(hdr)
                if any(w in hf for w in ("vekil", "mudafi", "bilirkisi", "avukat")):
                    return "__OFFICIAL__"
                return j_role
            cleaned = re.sub(r'[*_#>`"\':|\-\s]+', ' ', _fold_tr(ln)).strip()
            if not cleaned:
                return None
            allow_hdr_jud = include_judicial_headers and not cls._is_non_judicial_header_phrase(cleaned)
            j_role = MaskRegistry.normalize_person_role(cleaned, include_judicial_headers=allow_hdr_jud)
            if j_role in MaskRegistry.JUDICIAL_ROLES:
                return j_role
            if any(w in cleaned for w in ("vekil", "mudafi", "bilirkisi", "avukat")):
                return "__OFFICIAL__"
            if len(cleaned.split()) > 3:
                return None
            role = MaskRegistry.normalize_person_role(cleaned)
            if role:
                return role
            stripped_suffix = re.sub(r'\b(?:kimlik|bilgileri|bilgisi)\b', '', cleaned).strip()
            return MaskRegistry.normalize_person_role(stripped_suffix)
        return None

    @classmethod
    def _parse_judicial_sig_title_line(
        cls, raw_line: str, include_judicial_headers: bool = False
    ) -> Tuple[Optional[str], bool]:
        """Tek başına yargı imza/unvan satırını ('Hâkim 112233', 'BAŞKAN 123456', 'Cumhuriyet Savcısı 223344') ayrıştırır."""
        if not raw_line:
            return None, False
        s = re.sub(r'[*_#>`"\']+', ' ', raw_line).strip()
        if not s:
            return None, False
        s_no_esig, n_esig = re.subn(
            r'(?i)\(?\b(?:e[\s\-]?imzal[ıi](?:d[ıi]r)?|imzal[ıi](?:d[ıi]r)?)\b\)?',
            ' ',
            s,
        )
        s_no_sicil, n_sicil1 = re.subn(
            r'(?i)\bSicil(?:[ \t]*(?:No|Numaras[ıi]|i))?[ \t]*[:=]?[ \t]*\(?\d{4,7}\)?',
            ' ',
            s_no_esig,
        )
        s_no_sicil, n_sicil2 = re.subn(r'\[SİCİL_(?:\d+|GİZLENDİ)\]', ' ', s_no_sicil)
        s_no_sicil, n_sicil3 = re.subn(r'(?<!\d)\(?\d{4,7}\)?(?!\d)', ' ', s_no_sicil)
        cleaned = re.sub(r'[:\-–|/.\s]+', ' ', s_no_sicil).strip()
        if not cleaned or len(cleaned.split()) > 4:
            return None, False
        if cls._is_non_judicial_header_phrase(cleaned):
            return None, False
        role = MaskRegistry.normalize_person_role(
            cleaned, include_judicial_headers=include_judicial_headers
        )
        if role not in MaskRegistry.JUDICIAL_ROLES:
            return None, False
        has_sicil = (n_sicil1 + n_sicil2 + n_sicil3) > 0
        has_esig = n_esig > 0
        is_header_only = _fold_tr(cleaned) in MaskRegistry._JUDICIAL_HEADER_ALIASES
        return role, (has_sicil or has_esig or not is_header_only)

    @staticmethod
    def _is_sig_meta_line(raw_line: str) -> bool:
        """İmza bloğundaki 'e-imzalıdır' veya tek başına sicil satırlarını tanır."""
        cleaned = re.sub(r'[*_#>`"\'()\s]+', ' ', raw_line).strip()
        if not cleaned:
            return False
        if re.fullmatch(r'(?i)(?:e[\s\-]?imzal[ıi](?:d[ıi]r)?|imzal[ıi](?:d[ıi]r)?)', cleaned):
            return True
        if re.fullmatch(r'\[SİCİL_(?:\d+|GİZLENDİ)\]|\d{4,7}', cleaned):
            return True
        return False

    @classmethod
    def _finalize_ocr_weak_persons(
        cls, weak_ocr_acc: Optional[Dict], registry: MaskRegistry
    ) -> None:
        """OCR zayıf (B) adaylarını en az 2 farklı satırda geçme (veya zaten kayıtlı olma) şartıyla registry'ye ekler."""
        if not weak_ocr_acc or registry._persons_frozen:
            return
        for entry in weak_ocr_acc.get("entries", {}).values():
            hits = entry.get("hits") or []
            if not hits:
                continue
            if len(entry.get("lines", ())) >= 2 or registry.is_person_registered(hits[0][0]):
                for cand_name, b_role in hits:
                    registry.add_person(cand_name, b_role)

    @classmethod
    def collect_persons_from_text(
        cls,
        text: str,
        registry: MaskRegistry,
        ocr: bool = False,
        weak_ocr_acc: Optional[Dict] = None,
    ) -> None:
        """
        Yalnızca yüksek kesinlikli (A-D) kalıplardan gerçek kişi ad-soyadlarını çıkarır ve
        registry'ye kaydeder. Avukat, görevli, tüzel kişi ve kurum adlarını dışlar.
        ocr=True iken zayıf (B) kalıp en az 2 farklı satır (veya zaten kayıtlı kişi) şartına bağlıdır.
        """
        if not text or registry._persons_frozen:
            return
        local_acc: Optional[Dict] = None
        acc: Optional[Dict] = None
        doc_seq = 0
        if ocr:
            if weak_ocr_acc is None:
                local_acc = {"_seq": 0, "entries": {}}
                acc = local_acc
            else:
                acc = weak_ocr_acc
            doc_seq = acc.get("_seq", 0) + 1
            acc["_seq"] = doc_seq
            acc.setdefault("entries", {})

        def _valid_person(
            cand_str: str,
            before_c: str = "",
            after_c: str = "",
            allow_short_last: bool = False,
            allow_judicial: bool = False,
        ) -> bool:
            if not cls._is_person_name(
                cand_str,
                before_ctx=before_c,
                after_ctx=after_c,
                ocr=False,
                allow_judicial_pre_title=allow_judicial,
            ):
                return False
            if not ocr:
                return True
            if registry.is_person_registered(cand_str):
                return True
            return cls._passes_ocr_name_filter(cand_str, after_ctx=after_c, allow_short_last=allow_short_last)

        def _extract_sig_name(line_txt: str) -> str:
            s_sig = re.sub(
                r'(?i)\(?\b(?:e[\s\-]?imzal[ıi](?:d[ıi]r)?|imzal[ıi](?:d[ıi]r)?)\b\)?',
                ' ',
                line_txt,
            )
            s_sig = re.sub(r'\[SİCİL_(?:\d+|GİZLENDİ)\]', ' ', s_sig).strip()
            if not s_sig or ":" in s_sig:
                return ""
            s_sig = cls._strip_leading_judicial_titles(s_sig)
            cand_s, tail_s = cls._extract_name_from_segment(s_sig)
            tail_rem = re.sub(r'(?i)\b(?:sicil|no|numaras[ıi])\b', ' ', tail_s or '')
            if re.search(r'[A-Za-zÇĞİÖŞÜçğıöşü]', tail_rem):
                return ""
            return cand_s

        text = cls.normalize_spaces(text)
        doc_has_judicial_ctx = bool(cls._DOC_JUDICIAL_CTX_RE.search(text))
        lines = text.splitlines()
        active_role: Optional[str] = None
        table_col_roles: Dict[int, str] = {}
        claimed_sig_lines: Set[int] = set()

        def _parse_header_line(seg_line: str) -> Tuple[Optional[str], str]:
            """Tek bir başlık segmentinden taraf rolü ve kalan metni çıkarır (ön etiketleri soyar)."""
            cur = seg_line
            for _ in range(3):
                m_h = cls._HEADER_COLON_RE.match(cur)
                if m_h:
                    h_raw = m_h.group("hdr")
                    r_rest = m_h.group("rest")
                    found_role = cls._extract_header_role(
                        h_raw, include_judicial_headers=doc_has_judicial_ctx
                    )
                    if found_role:
                        return found_role, r_rest
                    if ":" not in r_rest:
                        return None, ""
                    cur = r_rest
                    continue
                m_pre = re.match(r'^[^:|\r\n]{1,40}:[ \t]*(?P<rest>.+)$', cur)
                if m_pre and ":" in m_pre.group("rest"):
                    cur = m_pre.group("rest")
                    continue
                return None, ""
            return None, ""

        for i, raw_line in enumerate(lines):
            stripped = raw_line.strip()
            if not stripped:
                active_role = None
                table_col_roles = {}
                continue

            if "|" in raw_line:
                raw_cells = raw_line.strip().split("|")
                if raw_line.lstrip().startswith("|") and raw_cells:
                    raw_cells = raw_cells[1:]
                if raw_line.rstrip().endswith("|") and raw_cells:
                    raw_cells = raw_cells[:-1]
                cells = [c.strip() for c in raw_cells]

                # A0. Dikey Markdown / XLSX tablo başlığı ve satırları ("| DAVACI | TCKN |")
                if cells and all((not c or re.fullmatch(r'[-:\s]+', c)) for c in cells):
                    # Ayraç satırı (| --- | --- |): sütun rollerini koru
                    continue
                if cells and not any(":" in c for c in cells):
                    row_key_role = (
                        cls._extract_header_role(cells[0], include_judicial_headers=doc_has_judicial_ctx)
                        if len(cells) >= 2 and cells[0]
                        else None
                    )
                    next_is_sep = (
                        i + 1 < len(lines)
                        and "|" in lines[i + 1]
                        and all(
                            (not c or re.fullmatch(r'[-:\s]+', c))
                            for c in [x.strip() for x in lines[i + 1].strip().strip("|").split("|")]
                        )
                    )
                    if row_key_role and not table_col_roles and not next_is_sep:
                        is_jud_row = row_key_role in MaskRegistry.JUDICIAL_ROLES
                        kv_matched = False
                        for part in [p for p in cls._INLINE_SPLIT_RE.split(cells[1]) if p.strip()] or [cells[1]]:
                            part_c = cls._strip_leading_judicial_titles(part) if is_jud_row else part
                            cand_kv, after_kv = cls._extract_name_from_segment(part_c)
                            cand_kv, _ = cls._strip_leading_descriptors(cand_kv, strip_judicial=is_jud_row)
                            after_kv = cls._extend_after_ctx(lines, i, after_kv)
                            if _valid_person(cand_kv, after_c=after_kv, allow_short_last=True, allow_judicial=is_jud_row):
                                registry.add_person(cand_kv, row_key_role, strong=True)
                                kv_matched = True
                        if kv_matched:
                            continue
                    hdr_roles = {
                        idx: cls._extract_header_role(c, include_judicial_headers=doc_has_judicial_ctx)
                        for idx, c in enumerate(cells)
                    }
                    hdr_roles = {idx: r for idx, r in hdr_roles.items() if r}
                    if hdr_roles:
                        table_col_roles = hdr_roles
                        active_role = None
                        continue
                    if table_col_roles:
                        for idx, role_col in table_col_roles.items():
                            if idx < len(cells) and cells[idx]:
                                is_jud_col = role_col in MaskRegistry.JUDICIAL_ROLES
                                for part in [p for p in cls._INLINE_SPLIT_RE.split(cells[idx]) if p.strip()] or [cells[idx]]:
                                    part_c = cls._strip_leading_judicial_titles(part) if is_jud_col else part
                                    cand_t, after_t = cls._extract_name_from_segment(part_c)
                                    cand_t, _ = cls._strip_leading_descriptors(cand_t, strip_judicial=is_jud_col)
                                    after_t = cls._extend_after_ctx(lines, i, after_t)
                                    if _valid_person(cand_t, after_c=after_t, allow_short_last=True, allow_judicial=is_jud_col):
                                        registry.add_person(cand_t, role_col, strong=True)
                        continue
                else:
                    table_col_roles = {}
            else:
                table_col_roles = {}

            # A. Taraf başlık satırı, boru (|) ayraçlı satırlar ve çok satırlı numaralı liste
            hdr_segments = [s.strip() for s in raw_line.split("|") if s.strip()] if "|" in raw_line else [raw_line]
            matched_hdr_seg = False
            for seg in hdr_segments:
                role, rest = _parse_header_line(seg)
                if role:
                    matched_hdr_seg = True
                    active_role = role if len(hdr_segments) == 1 else None
                    is_jud_role = role in MaskRegistry.JUDICIAL_ROLES
                    parts = [p for p in cls._INLINE_SPLIT_RE.split(rest) if p.strip()]
                    if not parts and rest.strip():
                        parts = [rest]
                    for part in parts:
                        part_c = cls._strip_leading_judicial_titles(part) if is_jud_role else part
                        cand, raw_after_ctx = cls._extract_name_from_segment(part_c)
                        cand, _ = cls._strip_leading_descriptors(cand, strip_judicial=is_jud_role)
                        if (
                            len(hdr_segments) == 1
                            and len(parts) == 1
                            and cand
                            and len(cand.split()) == 1
                            and not raw_after_ctx.strip()
                            and i + 1 < len(lines)
                        ):
                            nxt_line = lines[i + 1].strip()
                            if nxt_line and ":" not in nxt_line and not re.search(r'\d', nxt_line):
                                nxt_cand, nxt_after = cls._extract_name_from_segment(nxt_line)
                                if nxt_cand and len(nxt_cand.split()) == 1:
                                    joined = f"{cand} {nxt_cand}"
                                    joined_after = cls._extend_after_ctx(lines, i + 1, nxt_after)
                                    if _valid_person(joined, after_c=joined_after, allow_short_last=True, allow_judicial=is_jud_role):
                                        registry.add_person(joined, role, strong=True)
                                        continue
                        after_ctx = cls._extend_after_ctx(lines, i, raw_after_ctx)
                        if _valid_person(cand, after_c=after_ctx, allow_short_last=True, allow_judicial=is_jud_role):
                            registry.add_person(cand, role, strong=True)
            if matched_hdr_seg:
                pass
            elif cls._HEADER_COLON_RE.match(raw_line):
                active_role = None
            elif active_role:
                m_item = cls._LIST_ITEM_START_RE.match(raw_line)
                if m_item:
                    is_jud_active = active_role in MaskRegistry.JUDICIAL_ROLES
                    parts = [p for p in cls._INLINE_SPLIT_RE.split(raw_line) if p.strip()]
                    for part in parts:
                        part_c = cls._strip_leading_judicial_titles(part) if is_jud_active else part
                        cand, after_ctx = cls._extract_name_from_segment(part_c)
                        cand, _ = cls._strip_leading_descriptors(cand, strip_judicial=is_jud_active)
                        after_ctx = cls._extend_after_ctx(lines, i, after_ctx)
                        if _valid_person(cand, after_c=after_ctx, allow_short_last=True, allow_judicial=is_jud_active):
                            registry.add_person(cand, active_role, strong=True)
                else:
                    # Liste dışı satır (adres devamı değilse bloğu kapat)
                    if not re.match(r'^[ \t]{2,}', raw_line):
                        active_role = None

            # B. Cümle içi rol / yakınlık + ad ("davacı Ahmet Yılmaz", "müşterek çocuk Defne Aktaş", "Hâkim Ayşe Kaya")
            if not stripped.startswith("#"):
                def _register_prose_match(
                    cand_name: str,
                    b_role: Optional[str],
                    before_b: str,
                    after_b: str,
                    allow_judicial: bool = False,
                    strong: bool = False,
                ) -> None:
                    # 3-4 belirteçte sonda saygı/mahkeme eki ("Mahkememize", "Bey", "Hanım") varsa kırp
                    b_toks = cand_name.split()
                    if len(b_toks) >= 3 and _fold_tr(b_toks[-1]) in {
                        "mahkememize", "mahkemenize", "mahkemesine", "mahkemeye", "mahkememiz",
                        "bey", "hanim",
                    }:
                        cand_name = " ".join(b_toks[:-1])
                        after_b = " " + b_toks[-1] + after_b
                    cand_name, _ = cls._strip_leading_descriptors(cand_name, b_role, strip_judicial=allow_judicial)
                    after_b = cls._extend_after_ctx(lines, i, after_b)
                    if _valid_person(cand_name, before_c=before_b, after_c=after_b, allow_judicial=allow_judicial):
                        if not ocr or strong or registry.is_person_registered(cand_name):
                            registry.add_person(cand_name, b_role, strong=strong)
                        else:
                            raw_t = cand_name.split()
                            ftoks = tuple(_fold_tr(t) for t in raw_t)
                            if len(ftoks) == 2:
                                ck = " ".join(sorted(ftoks))
                            elif (
                                len(raw_t[0]) >= 2
                                and raw_t[0].isupper()
                                and any(not t.isupper() for t in raw_t[1:])
                            ):
                                ck = " ".join(ftoks[1:] + (ftoks[0],))
                            else:
                                ck = " ".join(ftoks)
                            entry = acc["entries"].setdefault(ck, {"lines": set(), "hits": []})
                            entry["lines"].add((doc_seq, i))
                            entry["hits"].append((cand_name, b_role))

                for m_b in cls._PROSE_ROLE_RE.finditer(raw_line):
                    _register_prose_match(
                        m_b.group("name"),
                        MaskRegistry.normalize_person_role(m_b.group("role")),
                        raw_line[:m_b.start("name")],
                        raw_line[m_b.end("name"):],
                    )
                for m_k in cls._PROSE_KIN_RE.finditer(raw_line):
                    _register_prose_match(
                        m_k.group("name"),
                        None,
                        raw_line[:m_k.start("name")],
                        raw_line[m_k.end("name"):],
                    )
                for m_is in cls._PROSE_ISIMLI_RE.finditer(raw_line):
                    _register_prose_match(
                        m_is.group("name"),
                        None,
                        raw_line[:m_is.start("name")],
                        raw_line[m_is.end("name"):],
                    )
                for m_j in cls._JUDICIAL_PROSE_RE.finditer(raw_line):
                    j_role = MaskRegistry.normalize_person_role(m_j.group("role"), include_judicial_headers=False)
                    j_after = m_j.group("after") or ""
                    _register_prose_match(
                        m_j.group("name"),
                        j_role,
                        raw_line[:m_j.start("name")],
                        j_after + raw_line[m_j.end("after"):],
                        allow_judicial=True,
                        strong=bool(j_after.strip()),
                    )

            # C. TCKN'ye bitişik ad ("Ahmet Yılmaz (T.C. Kimlik No: ...)")
            for m_c in cls._TCKN_ANCHOR_RE.finditer(raw_line):
                prefix = raw_line[:m_c.start()]
                m_pre = re.search(
                    r'(?P<name>' + cls._CAP_TOK_RE_STR + r'(?:[ \t]+' + cls._CAP_TOK_RE_STR + r'){1,4})[ \t]*$',
                    prefix,
                )
                if not m_pre:
                    continue
                cand_c = m_pre.group("name")
                before_c = prefix[:m_pre.start("name")]
                cand_c, c_role = cls._strip_leading_descriptors(cand_c, None)
                tckn_raw = m_c.group("tckn") or ""
                tckn_digits = re.sub(r'\D', '', _ocr_digits(tckn_raw))
                tckn_val = tckn_digits if len(tckn_digits) >= 9 else None
                if _valid_person(cand_c, before_c=before_c, after_c=raw_line[m_c.start():], allow_short_last=True):
                    registry.add_person(cand_c, c_role, strong=True, tckn=tckn_val)

            # D. Kimlik tablosu: Adı Soyadı / Adı + Soyadı
            has_official_near = bool(cls._NON_JUDICIAL_OFFICIAL_LINE_RE.search("\n".join(lines[max(0, i - 2):i + 1])))
            m_dfull = cls._ID_FULL_RE.match(raw_line)
            if m_dfull and not has_official_near:
                role_d = cls._find_role_above(lines, i, include_judicial_headers=doc_has_judicial_ctx)
                is_jud_d = role_d in MaskRegistry.JUDICIAL_ROLES
                rest_d = cls._strip_leading_judicial_titles(m_dfull.group("rest")) if is_jud_d else m_dfull.group("rest")
                cand_d, after_d = cls._extract_name_from_segment(rest_d)
                cand_d, _ = cls._strip_leading_descriptors(cand_d, strip_judicial=is_jud_d)
                after_d = cls._extend_after_ctx(lines, i, after_d)
                if role_d != "__OFFICIAL__" and _valid_person(cand_d, after_c=after_d, allow_judicial=is_jud_d):
                    registry.add_person(cand_d, role_d, strong=True)

            m_dsame = cls._ID_SAME_LINE_SPLIT_RE.search(raw_line)
            if m_dsame and not has_official_near:
                role_d = cls._find_role_above(lines, i, include_judicial_headers=doc_has_judicial_ctx)
                is_jud_d = role_d in MaskRegistry.JUDICIAL_ROLES
                cand_d = f"{m_dsame.group('fn')} {m_dsame.group('ln')}"
                cand_d, _ = cls._strip_leading_descriptors(cand_d, strip_judicial=is_jud_d)
                if role_d != "__OFFICIAL__" and _valid_person(cand_d, allow_judicial=is_jud_d):
                    registry.add_person(cand_d, role_d, strong=True)

            m_dfirst = cls._ID_FIRST_RE.match(raw_line)
            if m_dfirst:
                fn_cand, _ = cls._extract_name_from_segment(m_dfirst.group("rest"))
                if fn_cand:
                    for j in range(i + 1, min(len(lines), i + 3)):
                        if not lines[j].strip():
                            continue
                        if cls._ID_FIRST_RE.match(lines[j]):
                            break
                        m_dlast = cls._ID_LAST_RE.match(lines[j])
                        if m_dlast:
                            ln_cand, after_ln = cls._extract_name_from_segment(m_dlast.group("rest"))
                            near_off = bool(cls._NON_JUDICIAL_OFFICIAL_LINE_RE.search("\n".join(lines[max(0, i - 2):j + 1])))
                            role_d = cls._find_role_above(lines, i, include_judicial_headers=doc_has_judicial_ctx)
                            is_jud_d = role_d in MaskRegistry.JUDICIAL_ROLES
                            combined, _ = cls._strip_leading_descriptors(f"{fn_cand} {ln_cand}".strip(), strip_judicial=is_jud_d)
                            after_ln = cls._extend_after_ctx(lines, j, after_ln)
                            if not near_off and role_d != "__OFFICIAL__" and _valid_person(combined, after_c=after_ln, allow_judicial=is_jud_d):
                                registry.add_person(combined, role_d, strong=True)
                            break

            # E. Nüfus kayıt örneği dikey satır yapısı: "Kendisi / Eşi / Oğlu / Kızı" -> "<11 haneli TCKN>" -> "<ADI>" -> "<SOYADI>"
            if i + 3 < len(lines) and _fold_tr(stripped) in {"kendisi", "esi", "oglu", "kizi"}:
                tckn_ln = re.sub(r'\D', '', _ocr_digits(lines[i + 1].strip()))
                if len(tckn_ln) == 11 or lines[i + 1].strip().startswith("[TCKN_"):
                    fn_e, _ = cls._extract_name_from_segment(lines[i + 2].strip())
                    ln_e, _ = cls._extract_name_from_segment(lines[i + 3].strip())
                    if fn_e and ln_e:
                        cand_e = f"{fn_e} {ln_e}"
                        tckn_e = tckn_ln if len(tckn_ln) == 11 else None
                        if _valid_person(cand_e, allow_short_last=True):
                            registry.add_person(cand_e, "KİŞİ", strong=True, tckn=tckn_e)

            # D2. İmza bloğu: hemen önceki satır tek başına rol başlığıysa ("## Davacı", "TANIK:", "HÂKİM:")
            sig_clean = re.sub(r'[*_#>`"\':|\s]+', ' ', stripped).strip()
            allow_sig_jud = doc_has_judicial_ctx and not cls._is_non_judicial_header_phrase(sig_clean)
            sig_role = MaskRegistry.normalize_person_role(sig_clean, include_judicial_headers=allow_sig_jud)
            if (
                sig_role and sig_role != "KİŞİ"
                and not any(w in _fold_tr(sig_clean) for w in ("vekil", "mudafi", "bilirkisi"))
                and i + 1 < len(lines)
                and _fold_tr(cls._find_role_above(lines, i + 1, include_judicial_headers=doc_has_judicial_ctx) or "") == _fold_tr(sig_role)
            ):
                nxt = lines[i + 1].strip()
                is_jud_sig = sig_role in MaskRegistry.JUDICIAL_ROLES
                nxt_cand = _extract_sig_name(nxt) if is_jud_sig else nxt
                if nxt_cand and _valid_person(nxt_cand, allow_judicial=is_jud_sig):
                    registry.add_person(nxt_cand, sig_role, strong=True)
                    claimed_sig_lines.add(i + 1)

            # D3. Yargı imza bloğu: unvan/sicil satırı üstte veya altta ("Hâkim 112233 / Ayşe Yılmaz", "BAŞKAN 123456 / e-imzalıdır / Mehmet Öz")
            sig_j_role, sig_j_strong = cls._parse_judicial_sig_title_line(
                raw_line, include_judicial_headers=doc_has_judicial_ctx
            )
            if sig_j_role:
                has_nearby_sig_cue = sig_j_strong or any(
                    cls._is_sig_meta_line(lines[k])
                    or (k != i and cls._parse_judicial_sig_title_line(lines[k], include_judicial_headers=doc_has_judicial_ctx)[0] is not None)
                    or re.search(r'(?i)e[\s\-]?imzal[ıi]|\bsicil\b', lines[k])
                    for k in range(max(0, i - 2), min(len(lines), i + 4))
                )
                if has_nearby_sig_cue:
                    matched_sig = False
                    for j in range(i + 1, min(len(lines), i + 4)):
                        ln_j = lines[j].strip()
                        if not ln_j or cls._is_sig_meta_line(ln_j):
                            continue
                        if cls._parse_judicial_sig_title_line(ln_j, include_judicial_headers=doc_has_judicial_ctx)[0] is not None or ":" in ln_j:
                            break
                        cand_s = _extract_sig_name(ln_j)
                        if cand_s and _valid_person(cand_s, allow_judicial=True):
                            registry.add_person(cand_s, sig_j_role, strong=True)
                            claimed_sig_lines.add(j)
                            matched_sig = True
                        break
                    if not matched_sig:
                        for j in range(i - 1, max(-1, i - 4), -1):
                            if j in claimed_sig_lines:
                                break
                            ln_j = lines[j].strip()
                            if not ln_j or cls._is_sig_meta_line(ln_j):
                                continue
                            if cls._parse_judicial_sig_title_line(ln_j, include_judicial_headers=doc_has_judicial_ctx)[0] is not None or ":" in ln_j:
                                break
                            cand_s = _extract_sig_name(ln_j)
                            if cand_s and _valid_person(cand_s, allow_judicial=True):
                                registry.add_person(cand_s, sig_j_role, strong=True)
                                claimed_sig_lines.add(j)
                            break
            else:
                # Çok sütunlu yatay imza bloğu ("BAŞKAN 123456    ÜYE 234567" / "Mehmet Öz    Fatma Demir")
                cols = [c.strip() for c in re.split(r'(?:\t|[ ]{3,})', raw_line) if c.strip()]
                if len(cols) >= 2:
                    col_parsed = [
                        cls._parse_judicial_sig_title_line(c, include_judicial_headers=doc_has_judicial_ctx)
                        for c in cols
                    ]
                    if all(r is not None for r, _ in col_parsed):
                        for neighbor_idx in (i + 1, i - 1):
                            if 0 <= neighbor_idx < len(lines) and neighbor_idx not in claimed_sig_lines:
                                n_cols = [c.strip() for c in re.split(r'(?:\t|[ ]{3,})', lines[neighbor_idx]) if c.strip()]
                                if len(n_cols) == len(cols):
                                    any_added = False
                                    for (c_role, _), n_cell in zip(col_parsed, n_cols):
                                        cand_s = _extract_sig_name(n_cell)
                                        if cand_s and _valid_person(cand_s, allow_judicial=True):
                                            registry.add_person(cand_s, c_role, strong=True)
                                            any_added = True
                                    if any_added:
                                        claimed_sig_lines.add(neighbor_idx)
                                        break

        if local_acc is not None:
            cls._finalize_ocr_weak_persons(local_acc, registry)

    @classmethod
    def collect_persons_from_json(cls, data, registry: MaskRegistry) -> None:
        """Manifest JSON ağacından yüksek kesinlikli taraf/kişi adlarını çıkarır."""
        if registry._persons_frozen:
            return
        if isinstance(data, list):
            for item in data:
                cls.collect_persons_from_json(item, registry)
            return
        if not isinstance(data, dict):
            return

        lower_map = {_fold_tr(str(k)): v for k, v in data.items()}
        raw_role: Optional[str] = None
        for rk in cls._JSON_ROLE_KEYS:
            rv = lower_map.get(rk)
            if isinstance(rv, str) and rv.strip():
                raw_role = rv.strip()
                break

        mapped_role: Optional[str] = None
        if raw_role:
            rf = _fold_tr(raw_role)
            if any(
                w in rf for w in (
                    "vekil", "mudafi", "avukat", "bilirkisi",
                    "arabulucu", "uzlastirmaci", "noter", "memur", "mubasir", "doktor",
                    "tercuman", "kurum", "tuzel", "sirket",
                )
            ) and not any(jw in rf for jw in ("hakim", "savci", "katip")):
                # Görevli/avukat/tüzel kişi kaydının alt alanlarında da kişi kaydı açma
                for v in data.values():
                    if isinstance(v, (dict, list)):
                        cls.collect_persons_from_json(v, registry)
                return
            mapped_role = MaskRegistry.normalize_person_role(raw_role)

        surname_str = ""
        for sk in cls._JSON_SURNAME_KEYS:
            sv = lower_map.get(sk)
            if isinstance(sv, str) and sv.strip():
                surname_str = sv.strip()
                break

        is_jud_json = mapped_role in MaskRegistry.JUDICIAL_ROLES
        for nk in cls._JSON_NAME_KEYS:
            nv = lower_map.get(nk)
            if isinstance(nv, str) and nv.strip():
                cand = nv.strip()
                if len(cand.split()) == 1 and nk in ("ad", "isim") and surname_str:
                    cand = f"{cand} {surname_str}"
                if is_jud_json:
                    cand = cls._strip_leading_judicial_titles(cand)
                cand, mapped_role = cls._strip_leading_descriptors(cand, mapped_role, strip_judicial=is_jud_json)
                if cls._is_person_name(cand, allow_judicial_pre_title=mapped_role in MaskRegistry.JUDICIAL_ROLES):
                    registry.add_person(cand, mapped_role, strong=True)

        for v in data.values():
            if isinstance(v, (dict, list)):
                cls.collect_persons_from_json(v, registry)

    @classmethod
    def _is_person_match_blocked(
        cls,
        text: str,
        s: int,
        e: int,
        protected_spans: List[Tuple[int, int]],
        path_mode: bool = False,
        label: Optional[str] = None,
    ) -> bool:
        """Eşleşen kişi adının korunan aralıkta veya engelleyici ön/art bağlamda olup olmadığını denetler."""
        if any(s < pe and e > ps for ps, pe in protected_spans):
            return True
        ls = text.rfind("\n", 0, s) + 1
        le = text.find("\n", e)
        if le == -1:
            le = len(text)
        before_line = text[ls:s]
        after_line = text[e:le]
        is_judicial = MaskRegistry.is_judicial_label(label)
        if cls._has_blocking_pre_title(before_line, allow_judicial=is_judicial):
            return True
        sep_head = r'[ \t_.\-]+' if path_mode else r'[ \t]+'
        if re.match(
            rf'^{sep_head}(?:A\.?[ \t]*Ş\.?|Ltd\.?(?:[ \t]*Şti\.?)?|Şti\.?|A\.?[ \t]*O\.?|Koop\.?)',
            after_line,
            re.IGNORECASE,
        ):
            return True
        m_aw = re.match(rf'^{sep_head}([A-Za-zÇĞİÖŞÜçğıöşüâîûÂÎÛ]+)', after_line)
        if m_aw and _fold_tr(m_aw.group(1)) in cls._MASK_AFTER_PLACE_CORP_WORDS:
            return True
        return False

    @classmethod
    def redact_names(
        cls,
        text: str,
        registry: Optional[MaskRegistry] = None,
        path_mode: bool = False,
    ) -> Tuple[str, int]:
        """
        Ön taramada keşfedilmiş (freeze_persons sonrası sabitlenmiş) kişi ad-soyadlarını
        tutarlı rol etiketlerine ([DAVACI_1], [HAKİM_1], [TANIK_2] ...) çevirir.
        `path_mode=True` yalnızca dosya/klasör yolları ve Markdown bağlantı hedeflerinde
        `_`, `-`, `.` ayırıcılarını eşler; düz metinde kullanılmaz.
        """
        if not text or registry is None or not registry.has_persons():
            return text, 0
        rx = registry._compiled_path_name_re if path_mode else registry._compiled_name_re
        if rx is None:
            return text, 0
        if not rx.search(text):
            return text, 0

        protected_spans: List[Tuple[int, int]] = [
            (m.start(), m.end()) for m in re.finditer(cls.MASK_ANY_RE, text)
        ]
        protected_spans.extend(
            (m.start(), m.end()) for m in re.finditer(r'\[ADRES_\d+\][ \t]+\([^)\r\n]+\)', text)
        )
        protected_spans.extend((m.start(), m.end()) for m in re.finditer(r'https?://\S+|\S+@\S+', text))

        count = 0

        def repl(m: re.Match) -> str:
            nonlocal count
            s, e = m.start(), m.end()
            if any(s < pe and e > ps for ps, pe in protected_spans):
                return m.group(0)

            matched = m.group(0)
            label: Optional[str] = None
            honorific_tail = ""
            if path_mode:
                parts_list = [p for p in re.split(r'[ \t_.\-]+', _fold_tr(matched)) if p]
                if len(parts_list) >= 2 and len(parts_list[0]) == 1 and "." in matched:
                    label = registry._abbrev_to_label.get((parts_list[0], parts_list[-1]))
                else:
                    label = registry._variant_to_label.get(tuple(parts_list))
            elif "." in matched:
                parts = _fold_tr(matched).replace(".", " ").split()
                if len(parts) < 2:
                    return matched
                label = registry._abbrev_to_label.get((parts[0][0], parts[-1]))
            else:
                parts = tuple(_fold_tr(matched).split())
                label = registry._variant_to_label.get(parts)
                if not label and len(parts) == 2 and parts[1] in ("bey", "hanim"):
                    h_label = registry._honorific_to_label.get(parts[0])
                    if h_label:
                        m_hon = re.match(r'^(\S+)([ \t]+\S+)$', matched)
                        if m_hon:
                            label = h_label
                            honorific_tail = m_hon.group(2)

            if not label:
                return matched
            if cls._is_person_match_blocked(
                text, s, e, protected_spans, path_mode=path_mode, label=label
            ):
                return matched
            count += 1
            registry.occurrences["kisi"] += 1
            return f"{label}{honorific_tail}" if honorific_tail else label

        return rx.sub(repl, text), count

    @classmethod
    def _redact_md_link_targets(
        cls,
        text: str,
        registry: Optional[MaskRegistry] = None,
    ) -> Tuple[str, int]:
        """Yerel Markdown bağlantı hedeflerindeki yol parçalarında `_`/`-`/`.` ayırıcılı kişi adlarını maskeler."""
        if not text or registry is None or not registry.has_persons() or "](" not in text:
            return text, 0
        link_rx = re.compile(
            r'(?P<pre>!?\[[^\[\]\n]*(?:\[[^\]\n]*\][^\[\]\n]*)*\]\()(?:<(?P<t1>[^>\n]+)>|(?P<t2>[^)\s\n]+))(?P<post>\))'
        )
        added = 0

        def _mask_link(m: re.Match) -> str:
            nonlocal added
            had_angle = m.group("t1") is not None
            raw_target = m.group("t1") if had_angle else (m.group("t2") or "")
            if not raw_target or raw_target.startswith("#") or re.match(r'(?i)^(?:https?|mailto|file):', raw_target):
                return m.group(0)
            path_part, sep, frag = raw_target.partition("#")
            segs = path_part.split("/")
            new_segs: List[str] = []
            changed = False
            for idx, seg in enumerate(segs):
                if not seg or seg in (".", ".."):
                    new_segs.append(seg)
                    continue
                is_leaf = (idx == len(segs) - 1) and not path_part.endswith("/")
                body, ext = seg, ""
                if is_leaf:
                    stem, raw_ext = os.path.splitext(seg)
                    if stem and raw_ext:
                        body, ext = stem, raw_ext
                masked_body, cnt = cls.redact_names(
                    unicodedata.normalize("NFC", body),
                    registry=registry,
                    path_mode=True,
                )
                if cnt:
                    added += cnt
                    changed = True
                new_segs.append(f"{masked_body}{ext}")
            if not changed:
                return m.group(0)
            new_target = "/".join(new_segs) + (sep + frag if sep else "")
            wrapped = f"<{new_target}>" if (had_angle or " " in new_target or "\t" in new_target) else new_target
            return f"{m.group('pre')}{wrapped}{m.group('post')}"

        return link_rx.sub(_mask_link, text), added

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

        # Katman 0: Unicode boşluk normalizasyonu. PDF/Word metinlerinde sık görülen bölünmez boşluk
        # (NBSP) ve dar boşluklar kuralların [ \t] beklentisini bozup sicil/adres/TCKN sızıntısına
        # yol açar; hepsi düz boşluğa, sıfır genişlikli karakterler kaldırılır.
        text = cls.normalize_spaces(text)
        # %-kodlu Markdown bağlantı hedeflerini çöz ("Şüpheli%200532%20..."): aksi halde hedefteki
        # telefon/TCKN maskelenmez ve bağlantı maskeli dosya yoluna eşlenemez.
        text = cls._decode_link_targets(text)

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

        if registry is not None:
            def _dedup_adres_hint(m: re.Match) -> str:
                norm_hint = re.sub(r'[\s/,\-]+', ' ', _tr_lower(m.group(2))).strip()
                norm_after = re.sub(r'[\s/,\-]+', ' ', _tr_lower(m.group(3))).strip()
                return m.group(1) if norm_hint == norm_after else m.group(0)

            t = re.sub(
                r'(\[ADRES_\d+\] \(([^)\r\n]+)\))[ \t,/\-]+'
                r'([A-Za-zÇĞİÖŞÜçğıöşü]+(?:[ \t,/\-]+[A-Za-zÇĞİÖŞÜçğıöşü]+)?)(?![A-Za-zÇĞİÖŞÜçğıöşü\'])',
                _dedup_adres_hint,
                t,
            )

        # Katman 8: Gerçek kişi ad-soyadları (en son çalışır: adres/sicil bağlamları korunur)
        t, stats["kisi"] = cls.redact_names(t, registry=registry)
        t, link_kisi = cls._redact_md_link_targets(t, registry=registry)
        stats["kisi"] += link_kisi

        stats["total"] = sum(v for k, v in stats.items() if k != "total")
        return t, stats

    @classmethod
    def redact_path_segment(
        cls,
        segment: str,
        known_tckns: Optional[Set[str]] = None,
        registry: Optional[MaskRegistry] = None,
        is_file: bool = False,
    ) -> str:
        """
        Dosya veya klasör adı parçasındaki TCKN, telefon, IBAN/kart, hesap, seri no ve
        kişi ad-soyad bilgilerini maskeler (adres kuralı uygulanmaz). Dosya adında son uzantı
        korunur; '/' ve ':' yerine '-' konur.
        """
        if not segment:
            return segment
        ext = ""
        body = segment
        if is_file:
            stem, raw_ext = os.path.splitext(segment)
            if stem and raw_ext:
                body, ext = stem, raw_ext

        t, _ = cls.redact_iban(body, registry=registry)
        t, _ = cls.redact_account(t, registry=registry)
        t, _ = cls.redact_seri_no(t, registry=registry)
        t, _ = cls.redact_tckn(t, known_tckns=known_tckns, registry=registry)
        t, _ = cls.redact_phone(t, registry=registry)
        if registry is not None and registry.has_persons():
            t = unicodedata.normalize("NFC", t)
            t, _ = cls.redact_names(t, registry=registry, path_mode=True)
        t = t.replace("/", "-").replace(":", "-")
        return f"{t}{ext}"

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
    def extract_pdf_raw(cls, pdf_path: str, max_pages: int = 2000) -> str:
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
                    # PyMuPDF bazı yazı tiplerinde '-' karakterini U+00AD (yumuşak tire) olarak döndürür
                    text = page.get_text()
                    text = re.sub(r'(?<=\d)\u00ad(?=\d)', '', text).replace("\u00ad", "-").strip()

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
        max_pages: int = 2000,
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
        """Taranmış görseli (.tif/.png/.jpg/.heic) Apple Vision OCR ile HAM (maskesiz) metne dönüştürür; yalnızca bellekte kullanılmalıdır."""
        try:
            import Vision
            from Cocoa import NSURL
        except ImportError:
            return ""

        pages_content = []
        ext = os.path.splitext(img_path)[1].lower()

        # Çok sayfalı TIFF kontrolü (.heic doğrudan Vision'a gönderilir, PIL ile açılmaz)
        if ext != ".heic":
            try:
                from PIL import Image, ImageSequence
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

        # Tek sayfa (veya .heic) doğrudan Vision OCR
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
        TIFF, PNG, JPEG, HEIC formatındaki taranmış evrakları Apple Vision OCR ile
        yerel ve çevrimdışı olarak metne dönüştürür ve maskeler.
        """
        full_raw = cls.extract_image_raw(img_path)
        if not full_raw:
            return "", cls._empty_stats()
        return cls.redact_text(full_raw, known_tckns=known_tckns, registry=registry)

    @classmethod
    def extract_udf_raw(cls, file_path: str) -> str:
        """
        UYAP .udf (ZIP arşivi) dosyasındaki content.xml içinden HAM düz metni çıkarır.
        Geçersiz ZIP, eksik content.xml veya okuma hatasında istisna fırlatmaz, "" döndürür.
        """
        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                if "content.xml" not in zf.namelist():
                    return ""
                xml_bytes = zf.read("content.xml")
        except Exception:
            return ""

        xml_text = xml_bytes.decode("utf-8", errors="replace")
        text = ""
        try:
            root = ET.fromstring(xml_text)
            content_el = root.find("content")
            if content_el is not None and content_el.text is not None:
                text = content_el.text
        except Exception:
            m = re.search(r"<!\[CDATA\[(.*?)\]\]>", xml_text, re.DOTALL)
            if m:
                text = m.group(1)

        if not text:
            return ""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return text.strip()

    @classmethod
    def extract_word_raw(cls, file_path: str) -> str:
        """
        Word (.docx / .doc) belgesinden HAM (maskesiz) düz metin çıkarır; hata durumunda "" döndürür.
        Önce macOS yerleşik textutil aracını dener; .docx için başarısız olursa zipfile + XML yedeğini kullanır.
        """
        ext = os.path.splitext(file_path)[1].lower()
        if os.path.isfile("/usr/bin/textutil"):
            try:
                proc = subprocess.run(
                    ["/usr/bin/textutil", "-convert", "txt", "-stdout", file_path],
                    capture_output=True,
                    timeout=120,
                )
                if proc.returncode == 0 and proc.stdout:
                    text = proc.stdout.decode("utf-8", errors="replace")
                    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
                    if text:
                        return text
            except Exception:
                pass

        if ext != ".docx":
            return ""

        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                if "word/document.xml" not in zf.namelist():
                    return ""
                xml_bytes = zf.read("word/document.xml")
            root = ET.fromstring(xml_bytes)
        except Exception:
            return ""

        lines: List[str] = []

        def _collect_inline(node: ET.Element, parts: List[str]) -> None:
            for child in node:
                local = child.tag.split("}")[-1]
                if local == "p":
                    _flush_paragraph(child)
                elif local == "t":
                    if child.text:
                        parts.append(child.text)
                elif local == "tab":
                    parts.append("\t")
                elif local in ("br", "cr"):
                    parts.append("\n")
                else:
                    _collect_inline(child, parts)

        def _flush_paragraph(p_el: ET.Element) -> None:
            parts: List[str] = []
            _collect_inline(p_el, parts)
            line = "".join(parts).replace("\r\n", "\n").replace("\r", "\n")
            if line:
                lines.append(line)

        def _walk(node: ET.Element) -> None:
            for child in node:
                local = child.tag.split("}")[-1]
                if local == "p":
                    _flush_paragraph(child)
                else:
                    _walk(child)

        _walk(root)
        return "\n".join(lines).strip()

    @classmethod
    def extract_xlsx_raw(cls, file_path: str) -> str:
        """
        Excel (.xlsx) dosyasından yalnız standart kütüphane (zipfile + ElementTree) ile
        HAM (maskesiz) Markdown tabloları çıkarır. Sayıları bilimsel gösterime çevirmeden
        XML'deki ham dizeyle korur. Hata durumunda "" döndürür.
        """
        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                names = set(zf.namelist())

                shared_strings: List[str] = []
                if "xl/sharedStrings.xml" in names:
                    ss_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                    for si in ss_root:
                        if si.tag.split("}")[-1] != "si":
                            continue
                        parts: List[str] = []
                        for ch in si:
                            clocal = ch.tag.split("}")[-1]
                            if clocal == "t" and ch.text:
                                parts.append(ch.text)
                            elif clocal == "r":
                                for rch in ch:
                                    if rch.tag.split("}")[-1] == "t" and rch.text:
                                        parts.append(rch.text)
                        shared_strings.append("".join(parts))

                rels: Dict[str, str] = {}
                if "xl/_rels/workbook.xml.rels" in names:
                    rels_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
                    for rel in rels_root:
                        if rel.tag.split("}")[-1] != "Relationship":
                            continue
                        rid = rel.attrib.get("Id", "")
                        target = rel.attrib.get("Target", "")
                        if rid and target:
                            if target.startswith("/"):
                                tpath = target.lstrip("/")
                            else:
                                tpath = posixpath.normpath(posixpath.join("xl", target))
                            rels[rid] = tpath

                sheets: List[Tuple[str, str]] = []
                if "xl/workbook.xml" in names:
                    wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
                    for el in wb_root.iter():
                        if el.tag.split("}")[-1] != "sheet":
                            continue
                        sname = el.attrib.get("name") or "Sayfa"
                        rid = ""
                        for ak, av in el.attrib.items():
                            if ak == "r:id" or ak.endswith("}id"):
                                rid = av
                                break
                        spath = rels.get(rid, "")
                        if spath and spath in names:
                            sheets.append((sname, spath))

                if not sheets:
                    for nm in sorted(names):
                        if nm.startswith("xl/worksheets/sheet") and nm.endswith(".xml"):
                            sheets.append((os.path.splitext(os.path.basename(nm))[0], nm))

                if not sheets:
                    return ""

                def _col_index(ref: str) -> Optional[int]:
                    letters = ""
                    for ch in ref:
                        if ch.isalpha():
                            letters += ch.upper()
                        else:
                            break
                    if not letters:
                        return None
                    idx = 0
                    for ch in letters:
                        idx = idx * 26 + (ord(ch) - ord("A") + 1)
                    return idx - 1

                def _clean_cell(val: str) -> str:
                    s = val.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
                    s = s.replace("|", "\\|")
                    return s.strip()

                sheet_blocks: List[str] = []
                for sname, spath in sheets:
                    try:
                        s_root = ET.fromstring(zf.read(spath))
                    except Exception:
                        continue
                    rows: List[Dict[int, str]] = []
                    max_col = -1
                    for row_el in s_root.iter():
                        if row_el.tag.split("}")[-1] != "row":
                            continue
                        row_cells: Dict[int, str] = {}
                        next_col = 0
                        for c_el in row_el:
                            if c_el.tag.split("}")[-1] != "c":
                                continue
                            c_idx = _col_index(c_el.attrib.get("r", ""))
                            if c_idx is None:
                                c_idx = next_col
                            next_col = c_idx + 1
                            ctype = c_el.attrib.get("t", "")
                            v_el = None
                            is_el = None
                            for child in c_el:
                                clocal = child.tag.split("}")[-1]
                                if clocal == "v":
                                    v_el = child
                                elif clocal == "is":
                                    is_el = child
                            raw_val = ""
                            if ctype == "s":
                                if v_el is not None and v_el.text is not None:
                                    try:
                                        si_idx = int(v_el.text.strip())
                                        if 0 <= si_idx < len(shared_strings):
                                            raw_val = shared_strings[si_idx]
                                    except Exception:
                                        raw_val = ""
                            elif ctype == "inlineStr":
                                if is_el is not None:
                                    iparts: List[str] = []
                                    for sub in is_el.iter():
                                        if sub.tag.split("}")[-1] == "t" and sub.text:
                                            iparts.append(sub.text)
                                    raw_val = "".join(iparts)
                            elif ctype == "b":
                                if v_el is not None and v_el.text is not None:
                                    raw_val = "TRUE" if v_el.text.strip() == "1" else "FALSE"
                            else:
                                if v_el is not None and v_el.text is not None:
                                    raw_val = v_el.text

                            cleaned = _clean_cell(raw_val)
                            if cleaned:
                                row_cells[c_idx] = cleaned
                                if c_idx > max_col:
                                    max_col = c_idx
                        if row_cells:
                            rows.append(row_cells)
                            if len(rows) >= 20000:
                                break

                    if not rows or max_col < 0:
                        continue

                    ncols = max_col + 1
                    md_lines = [f"## {sname}", ""]
                    hdr = [rows[0].get(j, "") for j in range(ncols)]
                    md_lines.append("| " + " | ".join(hdr) + " |")
                    md_lines.append("| " + " | ".join("---" for _ in range(ncols)) + " |")
                    for r in rows[1:]:
                        vals = [r.get(j, "") for j in range(ncols)]
                        md_lines.append("| " + " | ".join(vals) + " |")
                    sheet_blocks.append("\n".join(md_lines))

                if not sheet_blocks:
                    return ""
                return f"# {os.path.basename(file_path)}\n\n" + "\n\n".join(sheet_blocks)
        except Exception:
            return ""

    @classmethod
    def _extract_archive_safely(
        cls,
        archive_path: str,
        tmp_dir: str,
        issues: Optional[List[Tuple[str, str]]] = None,
    ) -> List[str]:
        """
        ZIP / EYP arşivini zip-slip, sembolik bağ, şifreli üye ve zip-bomb korumalarıyla
        yalnız verilen geçici dizin (tmp_dir) altına çıkarır; çıkarılan dosya yollarını döndürür.
        """
        extracted: List[str] = []
        try:
            os.makedirs(tmp_dir, exist_ok=True)
            real_tmp = os.path.realpath(tmp_dir)
        except Exception:
            if issues is not None:
                issues.append(("bozuk", ""))
            return []

        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                total_bytes = 0
                member_count = 0
                for info in zf.infolist():
                    member_count += 1
                    if member_count > cls.ARCHIVE_MAX_MEMBERS:
                        if issues is not None:
                            issues.append(("çok büyük", ""))
                        break

                    raw_name = info.filename
                    if not (info.flag_bits & 0x800):
                        try:
                            raw_name = raw_name.encode("cp437").decode("cp857")
                        except Exception:
                            pass
                    raw_name = unicodedata.normalize("NFC", raw_name)

                    if info.is_dir() or raw_name.endswith(("/", "\\")):
                        continue

                    mode = (info.external_attr >> 16) & 0o170000
                    if stat.S_ISLNK(mode):
                        continue

                    if info.flag_bits & 0x1:
                        if issues is not None:
                            issues.append(("şifreli", raw_name))
                        continue

                    norm_slash = raw_name.replace("\\", "/")
                    if norm_slash.startswith("/") or (
                        len(norm_slash) >= 2 and norm_slash[1] == ":" and norm_slash[0].isalpha()
                    ):
                        continue
                    parts = [p for p in norm_slash.split("/") if p and p != "."]
                    if not parts or any(p == ".." for p in parts):
                        if issues is not None:
                            issues.append(("güvensiz ad", raw_name))
                        continue

                    dest_candidate = os.path.join(real_tmp, *parts)
                    real_dest = os.path.realpath(dest_candidate)
                    if real_dest == real_tmp or not cls._is_inside_path(real_dest, real_tmp):
                        continue

                    if (
                        info.file_size > cls.ARCHIVE_MAX_FILE_BYTES
                        or (total_bytes + info.file_size) > cls.ARCHIVE_MAX_TOTAL_BYTES
                    ):
                        if issues is not None:
                            issues.append(("çok büyük", raw_name))
                        break

                    os.makedirs(os.path.dirname(real_dest), exist_ok=True)
                    if os.path.islink(os.path.dirname(real_dest)):
                        continue

                    written = 0
                    exceeded = False
                    try:
                        with zf.open(info, "r") as src_f, open(real_dest, "wb") as out_f:
                            while True:
                                chunk = src_f.read(1024 * 1024)
                                if not chunk:
                                    break
                                written += len(chunk)
                                if (
                                    written > cls.ARCHIVE_MAX_FILE_BYTES
                                    or (total_bytes + written) > cls.ARCHIVE_MAX_TOTAL_BYTES
                                ):
                                    exceeded = True
                                    break
                                out_f.write(chunk)
                    except RuntimeError:
                        try:
                            if os.path.exists(real_dest):
                                os.remove(real_dest)
                        except Exception:
                            pass
                        if issues is not None:
                            issues.append(("şifreli", raw_name))
                        continue
                    except Exception:
                        try:
                            if os.path.exists(real_dest):
                                os.remove(real_dest)
                        except Exception:
                            pass
                        continue

                    if exceeded:
                        try:
                            if os.path.exists(real_dest):
                                os.remove(real_dest)
                        except Exception:
                            pass
                        if issues is not None:
                            issues.append(("çok büyük", raw_name))
                        break

                    total_bytes += written
                    extracted.append(real_dest)
        except Exception:
            if issues is not None:
                issues.append(("bozuk", ""))
            return []

        return extracted

    @classmethod
    def extract_scanned_raw(cls, file_path: str) -> str:
        """PDF, TIFF/görsel, Word/Excel veya UDF dosyasının HAM metnini döndürür (uzantıya göre)."""
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".udf":
            return cls.extract_udf_raw(file_path)
        if ext == ".pdf":
            return cls.extract_pdf_raw(file_path)
        if ext in (".tif", ".tiff", ".png", ".jpg", ".jpeg", ".heic"):
            return cls.extract_image_raw(file_path)
        if ext in (".docx", ".doc"):
            return cls.extract_word_raw(file_path)
        if ext == ".xlsx":
            return cls.extract_xlsx_raw(file_path)
        return ""

    @classmethod
    def _read_scanned_raw_cached(
        cls,
        file_path: str,
        raw_cache_path: Optional[str] = None,
    ) -> str:
        """raw_cache_path varsa oradan okur; yoksa extract_scanned_raw çağırıp önbelleğe yazar."""
        if raw_cache_path and os.path.isfile(raw_cache_path):
            with open(raw_cache_path, "r", encoding="utf-8", errors="replace") as cf:
                return cf.read()
        raw = cls.extract_scanned_raw(file_path)
        if raw_cache_path and raw:
            os.makedirs(os.path.dirname(raw_cache_path), exist_ok=True)
            with open(raw_cache_path, "w", encoding="utf-8") as cf:
                cf.write(raw)
        return raw

    @classmethod
    def extract_and_redact_scanned_file(
        cls,
        file_path: str,
        known_tckns: Optional[Set[str]] = None,
        registry: Optional["MaskRegistry"] = None,
        raw_cache_path: Optional[str] = None,
        raw_override: Optional[str] = None,
    ) -> Tuple[str, Dict[str, int]]:
        """
        PDF veya TIFF/Görsel dosyalarını uzantısına göre en uygun OCR motoruyla işler ve maskeler.
        raw_cache_path yalnızca geliştirme/denetim içindir (UYAP_OCR_CACHE_DIR): ham OCR metni
        oradan okunur / oraya yazılır. Normal kullanımda None'dır ve ham metin diske yazılmaz.
        raw_override verildiğinde dosya/önbellek okunmadan doğrudan o ham metin maskelenir.
        """
        if raw_override is not None:
            raw = raw_override
        else:
            raw = cls._read_scanned_raw_cached(file_path, raw_cache_path=raw_cache_path)
        if not raw:
            return "", cls._empty_stats()
        return cls.redact_text(raw, known_tckns=known_tckns, registry=registry)

    @classmethod
    def _resolve_mapped_rel(
        cls,
        raw_rel: str,
        base_dir: str,
        dest_root: Optional[str] = None,
        path_map: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """
        Maskeleme nedeniyle adı değişmiş hedef dosya/klasör yolunu (doğrudan eşleme veya
        etiket joker eşleşmesiyle) diskteki gerçek göreli yola çözer. Bulunamazsa None döner.
        """
        if not path_map and not dest_root:
            return None
        root_dir = dest_root or base_dir
        raw_norm = unicodedata.normalize("NFC", urllib.parse.unquote(raw_rel).replace("\\", "/"))
        probe_keys = [raw_norm]
        try:
            rel_from_root = unicodedata.normalize(
                "NFC",
                os.path.relpath(os.path.normpath(os.path.join(base_dir, raw_norm)), root_dir).replace("\\", "/"),
            )
            if not rel_from_root.startswith("../") and rel_from_root not in probe_keys:
                probe_keys.append(rel_from_root)
        except Exception:
            pass
        if path_map:
            for k in probe_keys:
                mapped = path_map.get(k)
                if mapped:
                    abs_p = os.path.join(root_dir, mapped)
                    if os.path.isfile(abs_p):
                        return unicodedata.normalize("NFC", os.path.relpath(abs_p, base_dir).replace("\\", "/"))

        # Maske etiketi ([TEL_1], [TCKN_1], ...) taşıyan adayda joker eşleşme dene
        if re.search(cls.MASK_ANY_RE, raw_norm):
            cand_pool: Set[str] = set()
            if path_map:
                cand_pool.update(unicodedata.normalize("NFC", v.replace("\\", "/")) for v in path_map.values())
            for probe in probe_keys:
                if not re.search(cls.MASK_ANY_RE, probe):
                    continue
                parts = [p for p in probe.split("/") if p and p != "."]
                pat_parts = []
                for p in parts:
                    chunks = re.split(cls.MASK_ANY_RE, p)
                    masks = re.findall(cls.MASK_ANY_RE, p)
                    if not masks:
                        pat_parts.append(re.escape(p))
                    else:
                        seg_pat = re.escape(chunks[0])
                        for j, ch in enumerate(chunks[1:]):
                            seg_pat += r'[^/]+' + re.escape(ch)
                        pat_parts.append(seg_pat)
                rx = re.compile("^" + "/".join(pat_parts) + "$")
                matches = [
                    c for c in cand_pool
                    if rx.match(c) and os.path.isfile(os.path.join(root_dir, c))
                ]
                if len(matches) == 1:
                    abs_p = os.path.join(root_dir, matches[0])
                    return unicodedata.normalize("NFC", os.path.relpath(abs_p, base_dir).replace("\\", "/"))
        return None

    @classmethod
    def sync_index_file(
        cls,
        index_path: str,
        path_map: Optional[Dict[str, str]] = None,
        dest_root: Optional[str] = None,
    ) -> int:
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

                        if not found_md_abs and (path_map or dest_root):
                            for cand in base_candidates:
                                resolved = cls._resolve_mapped_rel(cand, index_dir, dest_root=dest_root, path_map=path_map)
                                if resolved:
                                    cand_abs = os.path.join(index_dir, resolved)
                                    if os.path.isfile(cand_abs):
                                        found_md_rel = resolved
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
            if path_map or dest_root:
                resolved = cls._resolve_mapped_rel(rel, index_dir, dest_root=dest_root, path_map=path_map)
                if resolved:
                    fp = os.path.join(index_dir, resolved)
                    try:
                        with open(fp, "r", encoding="utf-8", errors="replace") as mf:
                            cnt = len(mf.read())
                    except Exception:
                        return m.group(0)
                    formatted = f"{cnt:,}".replace(",", ".")
                    updated_rows += 1
                    return f"[↗](<{resolved}>) ({formatted} karakter)"
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
    BINARY_LINK_EXTS = (".pdf", ".udf", ".tif", ".tiff", ".png", ".jpg", ".jpeg", ".heic", ".gif", ".bmp",
                        ".xlsx", ".xls", ".docx", ".doc", ".html", ".htm", ".eml", ".eyp", ".zip", ".rar",
                        # e-yazışma paketi iç dosyaları (imza/mühür/üstveri): temiz klasöre aktarılmaz
                        ".imz", ".xml", ".psmdcp", ".p7s", ".cer", ".sig")
    IMAGE_LINK_EXTS = (".png", ".jpg", ".jpeg", ".heic", ".gif", ".bmp", ".tif", ".tiff")
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
        if len(vocab) < 300:
            # Klasörde karşılaştırılacak yeterli düzgün metin yoksa (ör. yalnız taranmış evrak),
            # yerleşik Türkçe/hukuk sözcük listesiyle desteklenir; aksi halde temiz taramalar da işaretlenir.
            vocab = vocab | cls._BASE_TR_VOCAB
        for p, t in ocr_docs:
            ratio, n = cls._ocr_word_hit_ratio(t, vocab)
            threshold_eff = threshold
            if n >= min_words and ratio < threshold_eff:
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
    def rewrite_dropped_links(
        cls,
        md_path: str,
        path_map: Optional[Dict[str, str]] = None,
        dest_root: Optional[str] = None,
    ) -> bool:
        """
        Temiz klasöre aktarılmayan görsel/ikili dosyalara giden Markdown bağlantılarını düzeltir:
        - OCR metni varsa bağlantıyı o .md'ye çevirir,
        - dosya/klasör adı maskelemesiyle taşınmış hedefleri günceller,
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

        link_re = re.compile(
            r'(?P<img>!?)\[(?P<alt>[^\[\]\n]*(?:\[[^\]\n]*\][^\[\]\n]*)*)\]\((?:<(?P<t1>[^>\n]+)>|(?P<t2>[^)\n]+?))\)'
        )

        def repl(m: re.Match) -> str:
            target = m.group('t1') or m.group('t2') or ""
            if re.match(r'(?i)^(?:https?|mailto|file):', target) or target.startswith("#"):
                return m.group(0)
            path_part, frag_sep, frag = target.partition("#")
            low = path_part.lower()
            if exists_rel(path_part) or exists_rel(urllib.parse.unquote(path_part)):
                return m.group(0)
            if path_map or dest_root:
                resolved = cls._resolve_mapped_rel(path_part, base_dir, dest_root=dest_root, path_map=path_map)
                if resolved:
                    full_resolved = f"{resolved}{frag_sep}{frag}" if frag_sep else resolved
                    wrapped = f"<{full_resolved}>" if (" " in full_resolved or "\t" in full_resolved or m.group('t1') is not None) else full_resolved
                    return f"{m.group('img')}[{m.group('alt')}]({wrapped})"
            if low.endswith(".md"):
                # Kaynakta da bulunmayan/aktarılmayan .md hedefi (ör. dava-analiz.md içindeki ölü bağlantı)
                return "—" if m.group('alt') == "↗" else (m.group('alt') or os.path.basename(path_part))
            if not low.endswith(cls.BINARY_LINK_EXTS):
                return m.group(0)
            alt = m.group('alt')
            if alt == "↗":  # INDEX tablosundaki "Dosya" sütunu: orijinal aktarılmadı (metin "Metin" sütununda)
                return "—"
            for cand in (os.path.splitext(path_part)[0] + ".md", path_part + ".md"):
                if exists_rel(cand):
                    label = alt if alt and alt != "↗" else os.path.basename(path_part)
                    return f"[{label} (OCR metni)](<{cand}>)"
                if path_map or dest_root:
                    resolved = cls._resolve_mapped_rel(cand, base_dir, dest_root=dest_root, path_map=path_map)
                    if resolved:
                        label = alt if alt and alt != "↗" else os.path.basename(path_part)
                        return f"[{label} (OCR metni)](<{resolved}>)"
            if m.group('img') or low.endswith(cls.IMAGE_LINK_EXTS):
                return f"[görsel aktarılmadı: {alt or os.path.basename(path_part)}]"
            if alt == "↗":
                return "—"
            return alt or os.path.basename(path_part)

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
    def sync_index_md(cls, folder: str, path_map: Optional[Dict[str, str]] = None) -> int:
        """
        Verilen dava klasörü altındaki tüm INDEX.md dosyalarını bularak
        otomatik olarak diskteki .md türevleri ve karakter sayılarıyla senkronize eder.
        Dönüş: Toplam güncellenen satır sayısı.
        """
        if not os.path.isdir(folder):
            return 0

        total_updated = 0
        real_folder = os.path.realpath(folder)
        for root, dirs, files in os.walk(folder):
            if cls._is_skipped_dir(root, folder, cls.SKIP_DIRS) or not cls._is_safe_src_path(root, real_folder):
                dirs[:] = []
                continue
            dirs[:] = [
                d for d in dirs
                if not cls._is_skipped_dir(os.path.join(root, d), folder, cls.SKIP_DIRS)
                and cls._is_safe_src_path(os.path.join(root, d), real_folder)
            ]
            for f in files:
                if f == "INDEX.md":
                    full_index_path = os.path.join(root, f)
                    if not cls._is_safe_src_path(full_index_path, real_folder):
                        continue
                    total_updated += cls.sync_index_file(full_index_path, path_map=path_map, dest_root=folder)

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
        progress_cb: Optional[Callable[[str, str, Dict], None]] = None,
        mask_names: bool = True,
        mask_judicial_names: bool = True,
    ) -> Tuple[str, Dict]:
        """
        İzole temiz klasör üretimi:
        Maskeli .md'leri yeni klasöre yazar, metni olmayan taranmış evraklara yerel OCR uygular,
        INDEX.md karakter sayılarını günceller ve yapay zekâ analizine hazırlanmış ayrı bir
        dava klasörü üretir. Orijinal klasöre yazmaz.

        Maskeler tutarlı ve numaralıdır ([TCKN_1], [ADRES_2], [DAVACI_1] ...): aynı değer tüm
        belgelerde aynı etiketi alır. TCKN/IBAN/adres eşlemeleri yalnızca bellekte tutulur;
        yalnızca kişi ad-soyad eşlemesi geri çevirme için maskeli klasörün dışındaki yerel
        uygulama dizinine kaydedilir.

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
            "udf_converted": 0,
            "office_converted": 0,
            "small_images_skipped": 0,
            "pdf_text_converted": 0,
            "archive_count": 0,
            "unprocessed": [],
            "index_synced": 0,
            "total_files": 0,
            "total_work": 0,
            "processed_items": 0,
            "last_file_stats": {},
            "last_file_path": "",
            "warning_no_documents": False,
            "kisi_sayisi": 0,
            "kisi_listesi": [],
            "mask_names": bool(mask_names),
            "mask_judicial_names": bool(mask_judicial_names),
        })

        def _add(st: Dict[str, int]) -> None:
            for k in cls.STAT_KEYS:
                grand_stats[k] += st.get(k, 0)

        unprocessed_items: List[Tuple[str, str]] = []
        archive_doc_items: List[Tuple[str, str, str, str, str]] = []
        archive_tmp_root = os.path.realpath(tempfile.mkdtemp(prefix="uyap_arsiv_"))

        try:
            # 0a. Arşivleri (.eyp / .zip) güvenli şekilde geçici dizine aç
            archive_sources: List[Tuple[str, str, str]] = []
            for root, dirs, files in os.walk(src_folder):
                if cls._is_skipped_dir(root, src_folder, cls.SKIP_DIRS_OCR) or _is_dest_subtree(root) or not cls._is_safe_src_path(root, real_src):
                    dirs[:] = []
                    continue
                dirs[:] = sorted(
                    d for d in dirs
                    if not cls._is_skipped_dir(os.path.join(root, d), src_folder, cls.SKIP_DIRS_OCR)
                    and not _is_dest_subtree(os.path.join(root, d))
                    and cls._is_safe_src_path(os.path.join(root, d), real_src)
                )
                for f in sorted(files):
                    ext = os.path.splitext(f)[1].lower()
                    if ext in cls.ARCHIVE_EXTS:
                        full_p = os.path.join(root, f)
                        if not cls._is_safe_src_path(full_p, real_src):
                            continue
                        rel_p = os.path.relpath(full_p, src_folder)
                        archive_sources.append((full_p, rel_p, ext))
            archive_sources.sort(key=lambda x: unicodedata.normalize("NFC", x[1]))

            def _record_archive_issues(
                arc_rel: str, arc_issues: List[Tuple[str, str]], has_extracted: bool
            ) -> bool:
                """Arşiv sorunlarını unprocessed_items'a yazar; arşiv geçersiz/tümüyle şifreli ise False döner."""
                if any(k == "bozuk" for k, _ in arc_issues):
                    unprocessed_items.append((arc_rel, "metin çıkarılamadı"))
                    return False
                enc_members = [m for k, m in arc_issues if k == "şifreli"]
                if enc_members:
                    if not has_extracted:
                        unprocessed_items.append((arc_rel, "işlenemedi (şifreli)"))
                        return False
                    for m in enc_members:
                        unprocessed_items.append((f"{arc_rel}/{m}" if m else arc_rel, "işlenemedi (şifreli)"))
                if any(k == "çok büyük" for k, _ in arc_issues):
                    unprocessed_items.append((arc_rel, "işlenemedi (çok büyük)"))
                for k, m in arc_issues:
                    if k == "güvensiz ad":
                        unprocessed_items.append((f"{arc_rel}/{m}", "güvensiz arşiv üye adı (atlandı)"))
                return True

            def _collect_extracted_archive_items(
                arc_tmp: str,
                arc_rel: str,
                arc_dest_rel: str,
                is_eyp: bool,
                allow_nested_zip: bool,
            ) -> None:
                for ef_path in sorted(
                    extracted_map[arc_tmp],
                    key=lambda p: unicodedata.normalize("NFC", os.path.relpath(p, arc_tmp)),
                ):
                    inner_rel = unicodedata.normalize("NFC", os.path.relpath(ef_path, arc_tmp))
                    inner_base = os.path.basename(inner_rel)
                    inner_ext = os.path.splitext(inner_base)[1].lower()
                    inner_parts = inner_rel.split(os.sep)

                    if (
                        "__MACOSX" in inner_parts
                        or inner_base in cls.IGNORED_BASENAMES
                        or inner_base.startswith("._")
                        or inner_ext == ".bak"
                        or inner_ext in cls.IGNORED_SIG_EXTS
                    ):
                        continue

                    if is_eyp and (
                        inner_base == "[Content_Types].xml"
                        or "_rels" in inner_parts
                        or inner_ext in cls.EYP_META_EXTS
                    ):
                        continue

                    if inner_ext in cls.ARCHIVE_EXTS:
                        if allow_nested_zip and inner_ext == ".zip":
                            n_tmp = os.path.realpath(tempfile.mkdtemp(prefix="narc_", dir=archive_tmp_root))
                            n_issues: List[Tuple[str, str]] = []
                            n_extracted = cls._extract_archive_safely(ef_path, n_tmp, issues=n_issues)
                            n_rel = f"{arc_rel}/{inner_rel}"
                            if _record_archive_issues(n_rel, n_issues, bool(n_extracted)):
                                grand_stats["archive_count"] += 1
                                extracted_map[n_tmp] = n_extracted
                                n_dest_rel = os.path.join(
                                    arc_dest_rel, f"{os.path.splitext(inner_rel)[0]} (ZIP)"
                                )
                                _collect_extracted_archive_items(
                                    n_tmp, n_rel, n_dest_rel, is_eyp=False, allow_nested_zip=False
                                )
                        else:
                            unprocessed_items.append((f"{arc_rel}/{inner_rel}", "iç içe arşiv"))
                        continue

                    if (
                        inner_ext in (".md", ".txt")
                        or inner_ext in cls.TEXT_DOC_EXTS
                        or inner_ext in cls.OCR_DOC_EXTS
                    ):
                        out_rel = (
                            inner_rel
                            if inner_ext in (".md", ".txt")
                            else os.path.splitext(inner_rel)[0] + ".md"
                        )
                        disp_rel = os.path.join(arc_dest_rel, out_rel)
                        archive_doc_items.append(
                            (ef_path, disp_rel, "", inner_ext, f"{arc_rel}/{inner_rel}")
                        )
                    else:
                        reason = (
                            f"desteklenmeyen tür ({inner_ext})"
                            if inner_ext
                            else "desteklenmeyen tür (uzantısız)"
                        )
                        unprocessed_items.append((f"{arc_rel}/{inner_rel}", reason))

            extracted_map: Dict[str, List[str]] = {}
            for full_p, rel_p, ext in archive_sources:
                clean_rel = rel_p[len("_kaynak/"):] if rel_p.startswith("_kaynak/") else rel_p
                arc_tag = "(EYP)" if ext == ".eyp" else "(ZIP)"
                arc_dest_rel = f"{os.path.splitext(clean_rel)[0]} {arc_tag}"
                arc_sub_tmp = os.path.realpath(tempfile.mkdtemp(prefix="arc_", dir=archive_tmp_root))
                arc_issues: List[Tuple[str, str]] = []
                extracted = cls._extract_archive_safely(full_p, arc_sub_tmp, issues=arc_issues)
                if _record_archive_issues(rel_p, arc_issues, bool(extracted)):
                    grand_stats["archive_count"] += 1
                    extracted_map[arc_sub_tmp] = extracted
                    _collect_extracted_archive_items(
                        arc_sub_tmp,
                        rel_p,
                        arc_dest_rel,
                        is_eyp=(ext == ".eyp"),
                        allow_nested_zip=(ext == ".eyp"),
                    )

            # 0. Klasör genelinde bilinen TCKN setini (known_tckns) topla (2 aşamalı hafıza)
            known_tckns = cls.collect_known_tckns_from_folder(src_folder, include_archives=False)
            for ef_path, _, _, inner_ext, _ in archive_doc_items:
                if inner_ext in (".md", ".txt") or inner_ext in cls.TEXT_DOC_EXTS:
                    txt = cls._extract_non_ocr_text(ef_path, inner_ext)
                    if txt:
                        known_tckns.update(cls.collect_known_tckns_from_text(txt))

            # Tek, yalnızca bellekte tutulan etiket kaydı: tüm belgelerde aynı değer = aynı etiket
            registry = MaskRegistry(known_tckns)

            # 1. Mevcut Markdown ve Metin Belgelerini Topla (determinizm için sıralı)
            md_files = []
            for root, dirs, files in os.walk(src_folder):
                if cls._is_skipped_dir(root, src_folder, cls.SKIP_DIRS) or _is_dest_subtree(root) or not cls._is_safe_src_path(root, real_src):
                    dirs[:] = []
                    continue
                dirs[:] = sorted(
                    d for d in dirs
                    if not cls._is_skipped_dir(os.path.join(root, d), src_folder, cls.SKIP_DIRS)
                    and not _is_dest_subtree(os.path.join(root, d))
                    and cls._is_safe_src_path(os.path.join(root, d), real_src)
                )
                for f in sorted(files):
                    if f.endswith((".md", ".txt")) and not f.endswith(".bak"):
                        full_p = os.path.join(root, f)
                        if cls._is_safe_src_path(full_p, real_src):
                            md_files.append(full_p)
            md_files.sort(key=lambda p: unicodedata.normalize("NFC", os.path.relpath(p, src_folder)))

            grand_stats["total_files"] = len(md_files)
            grand_stats["total_work"] = len(md_files)

            dir_seg_cache: Dict[Tuple[str, str], str] = {}
            used_dir_names: Dict[str, Dict[str, str]] = {}
            rel_path_cache: Dict[str, str] = {}
            used_file_names: Dict[str, Dict[str, str]] = {}
            path_map: Dict[str, str] = {}

            def _sanitize_seg(seg: str) -> str:
                seg = seg.replace("/", "-").replace(":", "-").strip()
                return seg or "belge"

            def _masked_rel_path(rel: str, is_dir: bool = False) -> str:
                """Göreli klasör/dosya yolundaki kişisel verileri (adres hariç) tutarlı ve çakışmasız maskeler."""
                rel_nfc = unicodedata.normalize("NFC", rel.replace("\\", "/")).strip("/")
                if not rel_nfc or rel_nfc == ".":
                    return ""
                cache_key = ("D:" if is_dir else "F:") + rel_nfc
                if cache_key in rel_path_cache:
                    return rel_path_cache[cache_key]

                parts = [p for p in rel_nfc.split("/") if p and p != "."]
                masked_parts: List[str] = []
                parent_key = ""
                for idx, seg in enumerate(parts):
                    leaf_file = (not is_dir) and (idx == len(parts) - 1)
                    if not leaf_file:
                        d_key = (parent_key, seg)
                        if d_key in dir_seg_cache:
                            m_seg = dir_seg_cache[d_key]
                        else:
                            cand = _sanitize_seg(
                                cls.redact_path_segment(seg, known_tckns=known_tckns, registry=registry, is_file=False)
                            )
                            used = used_dir_names.setdefault(parent_key, {})
                            m_seg = cand
                            n_idx = 2
                            while m_seg.lower() in used and used[m_seg.lower()] != seg:
                                m_seg = f"{cand} ({n_idx})"
                                n_idx += 1
                            used[m_seg.lower()] = seg
                            dir_seg_cache[d_key] = m_seg
                        masked_parts.append(m_seg)
                        parent_key = "/".join(masked_parts)
                    else:
                        cand = _sanitize_seg(
                            cls.redact_path_segment(seg, known_tckns=known_tckns, registry=registry, is_file=True)
                        )
                        stem, ext = os.path.splitext(cand)
                        if not stem and ext.startswith("."):
                            stem, ext = ext, ""
                        used = used_file_names.setdefault(parent_key, {})
                        m_seg = cand
                        n_idx = 2
                        while m_seg.lower() in used and used[m_seg.lower()] != rel_nfc:
                            m_seg = f"{stem} ({n_idx}){ext}"
                            n_idx += 1
                        used[m_seg.lower()] = rel_nfc
                        masked_parts.append(m_seg)

                result = os.path.join(*masked_parts) if masked_parts else ""
                rel_path_cache[cache_key] = result
                path_map[rel_nfc] = result
                return result

            def _udf_has_derivative(
                full_p: str, clean_rel: str, target_dest_md: str, check_clean_src: bool = False
            ) -> bool:
                """Metin tabanlı (.udf/.docx/.doc/.xlsx) belgenin .md/.<ext>.md türevinin (>=50 bayt) varlığını kontrol eder."""
                clean_md_nfc = unicodedata.normalize("NFC", (clean_rel + ".md").replace("\\", "/"))
                mapped_clean_md = rel_path_cache.get("F:" + clean_md_nfc, clean_rel + ".md")
                candidates = [
                    target_dest_md,
                    os.path.join(dest_folder, mapped_clean_md),
                    os.path.join(dest_folder, clean_rel + ".md"),
                    os.path.splitext(full_p)[0] + ".md",
                    full_p + ".md",
                ]
                if check_clean_src:
                    clean_no_ext = os.path.splitext(clean_rel)[0]
                    candidates.append(os.path.join(src_folder, clean_no_ext + ".md"))
                    candidates.append(os.path.join(src_folder, clean_rel + ".md"))
                return any(os.path.exists(c) and os.path.getsize(c) >= 50 for c in candidates)

            def _collect_step2_files(
                exts: Tuple[str, ...], check_clean_src: bool = False, use_masked_dest: bool = False
            ) -> List[Tuple[str, str, str, str]]:
                """Adım 2 (ve ön tarama) için taranacak PDF/TIFF/görsel/UDF/Office listesini deterministik sırayla toplar."""
                items: List[Tuple[str, str, str, str]] = []
                # Not: Bu tarama _kaynak/ dizinini BİLEREK tarar (orijinal belgeler oradadır)
                for root, dirs, files in os.walk(src_folder):
                    if cls._is_skipped_dir(root, src_folder, cls.SKIP_DIRS_OCR) or _is_dest_subtree(root) or not cls._is_safe_src_path(root, real_src):
                        dirs[:] = []
                        continue
                    dirs[:] = sorted(
                        d for d in dirs
                        if not cls._is_skipped_dir(os.path.join(root, d), src_folder, cls.SKIP_DIRS_OCR)
                        and not _is_dest_subtree(os.path.join(root, d))
                        and cls._is_safe_src_path(os.path.join(root, d), real_src)
                    )
                    for f in sorted(files):
                        ext = os.path.splitext(f)[1].lower()
                        if ext not in exts:
                            continue
                        full_p = os.path.join(root, f)
                        if not cls._is_safe_src_path(full_p, real_src):
                            continue
                        rel_p = os.path.relpath(full_p, src_folder)
                        clean_rel = rel_p[len("_kaynak/"):] if rel_p.startswith("_kaynak/") else rel_p
                        base_rel = os.path.splitext(clean_rel)[0] + ".md"
                        out_rel = _masked_rel_path(base_rel) if use_masked_dest else base_rel
                        if use_masked_dest:
                            path_map[unicodedata.normalize("NFC", clean_rel.replace("\\", "/"))] = out_rel
                            if rel_p != clean_rel:
                                path_map[unicodedata.normalize("NFC", rel_p.replace("\\", "/"))] = out_rel
                        target_dest_md = os.path.join(dest_folder, out_rel)

                        if ext in cls.TEXT_DOC_EXTS:
                            if not _udf_has_derivative(full_p, clean_rel, target_dest_md, check_clean_src=check_clean_src):
                                items.append((full_p, base_rel, target_dest_md, ext))
                        else:
                            # Eğer hedef klasörde bu evrakın .md metni henüz yoksa veya 50 karakterden kısaysa
                            if not os.path.exists(target_dest_md) or os.path.getsize(target_dest_md) < 50:
                                items.append((full_p, base_rel, target_dest_md, ext))
                items.sort(key=lambda x: unicodedata.normalize("NFC", x[1]))
                return items

            pre_text_files = _collect_step2_files(cls.TEXT_DOC_EXTS, check_clean_src=True)

            # 1a. Ön tarama (yalnızca bellekte): bağlamıyla tespit edilen hesap/sicil numaralarını öğren
            # ve yargı/taraf kişi ad-soyad maskelemesi açıksa belgelerle manifest JSON'lardan kişileri keşfet.
            need_person_prescan = bool(mask_names or mask_judicial_names)
            learn = MaskRegistry(known_tckns)
            prescan_texts: List[str] = []
            ocr_raw_cache: Dict[str, str] = {}
            ocr_raw_bytes = 0
            for file_path in md_files:
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        raw_md = f.read()
                    cls.redact_text(raw_md, known_tckns=known_tckns, registry=learn)
                    if need_person_prescan:
                        prescan_texts.append(raw_md)
                        cls.collect_persons_from_text(raw_md, registry)
                except Exception:
                    pass
            for doc_path, _, _, doc_ext in pre_text_files:
                try:
                    raw_doc = cls._extract_non_ocr_text(doc_path, doc_ext)
                    if raw_doc:
                        cls.redact_text(raw_doc, known_tckns=known_tckns, registry=learn)
                        if need_person_prescan:
                            prescan_texts.append(raw_doc)
                            cls.collect_persons_from_text(raw_doc, registry)
                except Exception:
                    pass
            for ef_path, _, _, inner_ext, _ in archive_doc_items:
                if inner_ext in (".md", ".txt") or inner_ext in cls.TEXT_DOC_EXTS:
                    try:
                        raw_arc = cls._extract_non_ocr_text(ef_path, inner_ext)
                        if raw_arc:
                            cls.redact_text(raw_arc, known_tckns=known_tckns, registry=learn)
                            if need_person_prescan:
                                prescan_texts.append(raw_arc)
                                cls.collect_persons_from_text(raw_arc, registry)
                    except Exception:
                        pass
            if need_person_prescan:
                import json
                for meta_name in cls.META_JSON_NAMES:
                    meta_src = os.path.join(src_folder, meta_name)
                    if os.path.isfile(meta_src) and cls._is_safe_src_path(meta_src, real_src):
                        try:
                            with open(meta_src, "r", encoding="utf-8", errors="replace") as mf:
                                meta_raw = mf.read()
                            prescan_texts.append(meta_raw)
                            meta_data = json.loads(meta_raw)
                            cls.collect_persons_from_json(meta_data, registry)
                        except Exception:
                            pass

                pre_ocr_files = _collect_step2_files(cls.OCR_DOC_EXTS)
                ocr_prescan_targets: List[Tuple[str, str]] = []
                for ocr_p, base_rel, _, ocr_ext in pre_ocr_files:
                    if ocr_ext in cls.SMALL_IMAGE_EXTS and cls._is_small_image(ocr_p):
                        continue
                    ocr_prescan_targets.append((ocr_p, base_rel))
                for ef_path, disp_rel, _, inner_ext, _ in archive_doc_items:
                    if inner_ext not in cls.OCR_DOC_EXTS:
                        continue
                    if inner_ext in cls.SMALL_IMAGE_EXTS and cls._is_small_image(ef_path):
                        continue
                    ocr_prescan_targets.append((ef_path, disp_rel))

                weak_ocr_acc: Dict = {}
                ocr_prescan_total = len(ocr_prescan_targets)
                for ocr_idx, (ocr_p, cache_rel) in enumerate(ocr_prescan_targets, 1):
                    if progress_cb:
                        progress_cb(
                            "sync",
                            f"Ön tarama (OCR): {ocr_idx}/{ocr_prescan_total} belge taranıyor",
                            grand_stats,
                        )
                    raw_cache_path = os.path.join(ocr_cache_dir, cache_rel) if ocr_cache_dir else None
                    try:
                        raw_ocr = cls._read_scanned_raw_cached(ocr_p, raw_cache_path=raw_cache_path)
                    except Exception:
                        continue
                    raw_bytes = len(raw_ocr.encode("utf-8")) if raw_ocr else 0
                    if ocr_raw_bytes + raw_bytes <= cls.OCR_PRESCAN_MAX_MEM_BYTES:
                        ocr_raw_cache[ocr_p] = raw_ocr
                        ocr_raw_bytes += raw_bytes
                        if raw_ocr:
                            prescan_texts.append(raw_ocr)
                    elif raw_ocr:
                        corp_snippet = cls._extract_corp_probe_lines(raw_ocr)
                        if corp_snippet:
                            prescan_texts.append(corp_snippet)
                    if raw_ocr:
                        try:
                            cls.redact_text(raw_ocr, known_tckns=known_tckns, registry=learn)
                            cls.collect_persons_from_text(
                                raw_ocr, registry, ocr=True, weak_ocr_acc=weak_ocr_acc
                            )
                        except Exception:
                            pass

                cls._finalize_ocr_weak_persons(weak_ocr_acc, registry)
                cls._prune_corp_candidates(prescan_texts, registry)
                prescan_texts.clear()
                if not mask_names and mask_judicial_names:
                    registry.keep_only_roles(MaskRegistry.JUDICIAL_ROLES)
                elif mask_names and not mask_judicial_names:
                    registry.remove_roles(MaskRegistry.JUDICIAL_ROLES)
                registry.freeze_persons()
            registry.seed("hesap", learn.known_values("hesap", min_len=7))
            registry.seed("sicil", learn.known_values("sicil", min_len=5))
            del learn

            for file_path in md_files:
                rel_path = os.path.relpath(file_path, src_folder)
                masked_rel = _masked_rel_path(rel_path)
                dest_path = os.path.join(dest_folder, masked_rel)
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
                    grand_stats["last_file_path"] = masked_rel
                    if progress_cb:
                        progress_cb("md", masked_rel, grand_stats)
                except Exception as e:
                    if progress_cb:
                        progress_cb("error", f"{masked_rel}: {str(e)}", grand_stats)

            # 2. Taranmış Evrakları (PDF/TIFF/HEIC) ve Çıplak UDF/Word/Excel Belgelerini İşle
            scanned_files = _collect_step2_files(cls.OCR_DOC_EXTS + cls.TEXT_DOC_EXTS, use_masked_dest=True)

            grand_stats["total_work"] = len(md_files) + len(scanned_files) + len(archive_doc_items)

            ocr_converted_list = []
            for full_p, base_rel, target_dest_md, ext in scanned_files:
                rel_p = os.path.relpath(full_p, src_folder)
                masked_base_rel = _masked_rel_path(base_rel)
                try:
                    if ext in cls.TEXT_DOC_EXTS:
                        raw = cls._extract_non_ocr_text(full_p, ext)
                        if raw:
                            red_text, p_stats = cls.redact_text(raw, known_tckns=known_tckns, registry=registry)
                        else:
                            red_text, p_stats = "", cls._empty_stats()
                    else:
                        raw_cache_path = os.path.join(ocr_cache_dir, base_rel) if ocr_cache_dir else None
                        cached_raw = ocr_raw_cache.pop(full_p, None)
                        red_text, p_stats = cls.extract_and_redact_scanned_file(
                            full_p,
                            known_tckns=known_tckns,
                            registry=registry,
                            raw_cache_path=raw_cache_path,
                            raw_override=cached_raw,
                        )
                    grand_stats["processed_items"] += 1
                    grand_stats["last_file_stats"] = p_stats
                    grand_stats["last_file_path"] = masked_base_rel

                    # Metin belgelerinde (UDF/Word/Excel) kısa ama geçerli evrak da aktarılır; 50 karakter
                    # eşiği yalnızca OCR türleri için (logo/boş tarama gürültüsünü elemek amacıyla) geçerlidir.
                    if len(red_text.strip()) > (0 if ext in cls.TEXT_DOC_EXTS else 50):
                        os.makedirs(os.path.dirname(target_dest_md), exist_ok=True)
                        with open(target_dest_md, "w", encoding="utf-8") as wf:
                            wf.write(red_text)
                        _add(p_stats)
                        grand_stats["md_transferred"] += 1
                        if ext == ".udf":
                            grand_stats["udf_converted"] += 1
                            if progress_cb:
                                progress_cb("md", masked_base_rel, grand_stats)
                        elif ext in cls.OFFICE_DOC_EXTS:
                            grand_stats["office_converted"] += 1
                            if progress_cb:
                                progress_cb("md", masked_base_rel, grand_stats)
                        elif ext == ".pdf" and "(Yerel OCR)" not in red_text:
                            # Metin katmanlı PDF: OCR yapılmadı, doğrudan metin çıkarıldı
                            grand_stats["pdf_text_converted"] += 1
                            if progress_cb:
                                progress_cb("md", masked_base_rel, grand_stats)
                        else:
                            grand_stats["ocr_converted"] += 1
                            ocr_converted_list.append(masked_base_rel)
                            if progress_cb:
                                progress_cb("ocr", masked_base_rel, grand_stats)
                    elif ext in cls.SMALL_IMAGE_EXTS and cls._is_small_image(full_p):
                        # Belgeye gömülü simge/logo/imza görseli: metin beklenmez, listeyi kirletmesin
                        grand_stats["small_images_skipped"] += 1
                    else:
                        unprocessed_items.append((_masked_rel_path(rel_p), "metin çıkarılamadı"))
                except Exception as oe:
                    grand_stats["processed_items"] += 1
                    unprocessed_items.append((_masked_rel_path(rel_p), "metin çıkarılamadı"))
                    if progress_cb:
                        err_label = (
                            "UDF Hatası"
                            if ext == ".udf"
                            else ("Office Hatası" if ext in cls.OFFICE_DOC_EXTS else "OCR Hatası")
                        )
                        progress_cb("error", f"{err_label} ({os.path.basename(masked_base_rel)}): {str(oe)}", grand_stats)

            # 2b. Arşiv içi belgeleri işle
            for ef_path, disp_rel, _unused_target, inner_ext, src_disp_rel in archive_doc_items:
                masked_disp_rel = _masked_rel_path(disp_rel)
                target_dest = os.path.join(dest_folder, masked_disp_rel)
                masked_src_disp_rel = _masked_rel_path(src_disp_rel)
                try:
                    if inner_ext in (".md", ".txt"):
                        with open(ef_path, "r", encoding="utf-8", errors="replace") as rf:
                            raw_txt = rf.read()
                        red_text, p_stats = cls.redact_text(raw_txt, known_tckns=known_tckns, registry=registry)
                        os.makedirs(os.path.dirname(target_dest), exist_ok=True)
                        with open(target_dest, "w", encoding="utf-8") as wf:
                            wf.write(red_text)
                        _add(p_stats)
                        grand_stats["md_transferred"] += 1
                        grand_stats["processed_items"] += 1
                        grand_stats["last_file_stats"] = p_stats
                        grand_stats["last_file_path"] = masked_disp_rel
                        if progress_cb:
                            progress_cb("md", masked_disp_rel, grand_stats)
                        continue

                    if os.path.exists(target_dest) and os.path.getsize(target_dest) >= 50:
                        grand_stats["processed_items"] += 1
                        continue

                    if inner_ext in cls.TEXT_DOC_EXTS:
                        raw = cls._extract_non_ocr_text(ef_path, inner_ext)
                        if raw:
                            red_text, p_stats = cls.redact_text(raw, known_tckns=known_tckns, registry=registry)
                        else:
                            red_text, p_stats = "", cls._empty_stats()
                    else:
                        raw_cache_path = os.path.join(ocr_cache_dir, disp_rel) if ocr_cache_dir else None
                        cached_raw = ocr_raw_cache.pop(ef_path, None)
                        red_text, p_stats = cls.extract_and_redact_scanned_file(
                            ef_path,
                            known_tckns=known_tckns,
                            registry=registry,
                            raw_cache_path=raw_cache_path,
                            raw_override=cached_raw,
                        )

                    grand_stats["processed_items"] += 1
                    grand_stats["last_file_stats"] = p_stats
                    grand_stats["last_file_path"] = masked_disp_rel

                    if len(red_text.strip()) > (0 if inner_ext in cls.TEXT_DOC_EXTS else 50):
                        os.makedirs(os.path.dirname(target_dest), exist_ok=True)
                        with open(target_dest, "w", encoding="utf-8") as wf:
                            wf.write(red_text)
                        _add(p_stats)
                        grand_stats["md_transferred"] += 1
                        if inner_ext == ".udf":
                            grand_stats["udf_converted"] += 1
                            if progress_cb:
                                progress_cb("md", masked_disp_rel, grand_stats)
                        elif inner_ext in cls.OFFICE_DOC_EXTS:
                            grand_stats["office_converted"] += 1
                            if progress_cb:
                                progress_cb("md", masked_disp_rel, grand_stats)
                        else:
                            grand_stats["ocr_converted"] += 1
                            ocr_converted_list.append(masked_disp_rel)
                            if progress_cb:
                                progress_cb("ocr", masked_disp_rel, grand_stats)
                    else:
                        unprocessed_items.append((masked_src_disp_rel, "metin çıkarılamadı"))
                except Exception as ae:
                    grand_stats["processed_items"] += 1
                    unprocessed_items.append((masked_src_disp_rel, "metin çıkarılamadı"))
                    if progress_cb:
                        progress_cb("error", f"Arşiv belgesi ({masked_src_disp_rel}): {str(ae)}", grand_stats)

            # 3. Yargı PRO Manifest JSON Dosyalarını Değer Bazında Maskeleyerek Aktar
            # (AGENTS.md ve kök seviyedeki dosya-bilgileri.md / safahat.md / dava-analiz.md
            #  1. adımda zaten maskelenerek aktarılır; burada maskesiz kopyalanmaz / çift sayılmaz.)
            for meta_name in cls.META_JSON_NAMES:
                meta_src = os.path.join(src_folder, meta_name)
                masked_meta_name = _masked_rel_path(meta_name)
                meta_dest = os.path.join(dest_folder, masked_meta_name)
                if os.path.isfile(meta_src) and cls._is_safe_src_path(meta_src, real_src):
                    try:
                        j_stats = cls.redact_json_file(meta_src, meta_dest, known_tckns=known_tckns, registry=registry)
                        _add(j_stats)
                    except Exception as je:
                        if progress_cb:
                            progress_cb("error", f"{masked_meta_name}: {str(je)}", grand_stats)

            # 3b. Kaynak klasörde hiçbir adımda işlenmeyen desteklenmeyen dosyaları topla
            handled_exts = (".md", ".txt") + cls.TEXT_DOC_EXTS + cls.OCR_DOC_EXTS + cls.ARCHIVE_EXTS
            for root, dirs, files in os.walk(src_folder):
                if cls._is_skipped_dir(root, src_folder, cls.SKIP_DIRS_OCR) or _is_dest_subtree(root) or not cls._is_safe_src_path(root, real_src):
                    dirs[:] = []
                    continue
                dirs[:] = sorted(
                    d for d in dirs
                    if not cls._is_skipped_dir(os.path.join(root, d), src_folder, cls.SKIP_DIRS_OCR)
                    and not _is_dest_subtree(os.path.join(root, d))
                    and cls._is_safe_src_path(os.path.join(root, d), real_src)
                )
                for f in sorted(files):
                    ext = os.path.splitext(f)[1].lower()
                    if (
                        f in cls.IGNORED_BASENAMES
                        or f.startswith("._")
                        or ext == ".bak"
                        or ext in cls.IGNORED_SIG_EXTS
                        or f in cls.META_JSON_NAMES
                        or ext in handled_exts
                    ):
                        continue
                    full_p = os.path.join(root, f)
                    if not cls._is_safe_src_path(full_p, real_src):
                        continue
                    rel_p = os.path.relpath(full_p, src_folder)
                    # Yargı PRO bu dosyanın .md türevini üretmişse (ör. HTML makbuz → .md) içerik
                    # zaten aktarılmıştır; "işlenemedi" listesine yazmak yanlış alarm olur.
                    if cls._source_has_md_derivative(full_p, src_folder):
                        continue
                    reason = f"desteklenmeyen tür ({ext})" if ext else "desteklenmeyen tür (uzantısız)"
                    unprocessed_items.append((rel_p, reason))

            seen_unproc: Set[Tuple[str, str]] = set()
            dedup_unproc: List[Tuple[str, str]] = []
            for u_rel, u_reason in unprocessed_items:
                masked_u = _masked_rel_path(u_rel)
                item = (unicodedata.normalize("NFC", masked_u), u_reason)
                if item not in seen_unproc:
                    seen_unproc.add(item)
                    dedup_unproc.append(item)
            dedup_unproc.sort(key=lambda x: x[0])
            grand_stats["unprocessed"] = dedup_unproc
        finally:
            shutil.rmtree(archive_tmp_root, ignore_errors=True)

        # 4. İkili dosya temizliği (hedef klasördeki olası ikili kalıntıları ve _kaynak dizinini temizle)
        clean_kaynak = os.path.join(dest_folder, "_kaynak")
        if os.path.isdir(clean_kaynak):
            shutil.rmtree(clean_kaynak, ignore_errors=True)

        for root, dirs, files in os.walk(dest_folder, topdown=False):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in (
                    ".udf", ".pdf", ".tif", ".tiff", ".png", ".jpg", ".jpeg", ".heic",
                    ".doc", ".docx", ".xlsx", ".eyp", ".zip", ".bak",
                ):
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
                cls.rewrite_dropped_links(p, path_map=path_map, dest_root=dest_folder)

        # 5. INDEX.md karakter sayısı senkronizasyonu (Dosya sütunundaki orijinal bağlantıyı kullanır),
        # ardından INDEX.md'deki aktarılmayan orijinal bağlantıları düz metne çevir (diğer
        # dosyaların uzunluğunu değiştirmez).
        synced_dest = cls.sync_index_md(dest_folder, path_map=path_map)
        grand_stats["index_synced"] = synced_dest
        for p in md_paths:
            if os.path.basename(p) == "INDEX.md":
                cls.rewrite_dropped_links(p, path_map=path_map, dest_root=dest_folder)

        # 6. Dönüşüm ve maskeleme raporu (ham değer içermez; kişi listesi yalnızca bellek içi döndürülür)
        grand_stats["mask_occurrences"] = dict(registry.occurrences)
        grand_stats["mask_distinct"] = {k: registry.distinct(k) for k in MaskRegistry.PREFIX}
        grand_stats["kisi_sayisi"] = registry.distinct("kisi")
        grand_stats["person_role_counts"] = registry.person_count_by_role()
        grand_stats["kisi_listesi"] = list(registry.person_map().items()) if (need_person_prescan and registry.has_persons()) else []

        if grand_stats["md_transferred"] == 0:
            grand_stats["warning_no_documents"] = True
        cls._write_report(src_folder, dest_folder, grand_stats, known_tckns=known_tckns, registry=registry)

        if grand_stats["md_transferred"] == 0:
            grand_stats["warning_no_documents"] = True
            if progress_cb:
                progress_cb(
                    "error",
                    "Kaynak klasörde işlenebilir belge bulunamadı (.md/.txt/.udf/.doc/.docx/.xlsx/.eyp/.zip/.pdf/.tif/.heic). Klasörü kontrol edin.",
                    grand_stats,
                )

        return dest_folder, grand_stats

    REPORT_NAME = "DAVA_DÖNÜŞÜM_VE_GÜVENLİK_RAPORU.md"

    @classmethod
    def _write_report(
        cls,
        src_folder: str,
        dest_folder: str,
        gs: Dict,
        known_tckns: Optional[Set[str]] = None,
        registry: Optional[MaskRegistry] = None,
    ) -> None:
        """Çıktı klasörüne dürüst bir dönüşüm raporu yazar. Ham kişisel değer YAZMAZ."""
        occ = gs.get("mask_occurrences", {})
        dist = gs.get("mask_distinct", {})
        mask_names = gs.get("mask_names", True)
        mask_judicial_names = gs.get("mask_judicial_names", True)
        show_person_labels = bool(mask_names or mask_judicial_names)
        role_counts = gs.get("person_role_counts") or {}
        names = [
            ("tckn", "T.C. Kimlik No / YKN", "kişi"), ("iban", "IBAN", "farklı IBAN"),
            ("hesap", "Banka hesap / müşteri no", "farklı numara"), ("kart", "Banka kartı no", "farklı kart"),
            ("telefon", "Cep telefonu", "farklı numara"), ("seri_no", "Kimlik seri no", "farklı seri no"),
            ("mrz", "Kimlik MRZ şeridi", "farklı şerit"), ("sicil", "Sicil no (hâkim/savcı/kâtip/bilirkişi/baro)",
                                                          "farklı sicil"),
            ("adres", "Açık kişi adresi", "farklı adres (yaklaşık)"),
            ("kisi", "Ad-soyad (yargı/taraf takma adı)", "farklı kişi"),
        ]
        safe_src_name = cls.redact_path_segment(os.path.basename(src_folder), known_tckns=known_tckns, registry=registry)
        safe_dest_name = cls.redact_path_segment(os.path.basename(dest_folder), known_tckns=known_tckns, registry=registry)
        report_path = os.path.join(dest_folder, cls.REPORT_NAME)
        with open(report_path, "w", encoding="utf-8") as rf:
            w = rf.write
            w("# Dava Dönüşüm ve Maskeleme Raporu\n\n")
            w(f"**Kaynak dava klasörü:** {safe_src_name}\n")
            w(f"**Maskeli klasör:** {safe_dest_name}\n")
            w(f"**İşlem tarihi:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            w(f"**Aktarılan metin belgesi (.md):** {gs['md_transferred']} adet\n")
            w(f"**Metne dökülen UYAP UDF belgesi (.udf → .md):** {gs.get('udf_converted', 0)} adet\n")
            w(f"**Office (Word/Excel) belgesi:** {gs.get('office_converted', 0)} adet\n")
            w(f"**Metin katmanlı PDF (OCR'sız):** {gs.get('pdf_text_converted', 0)} adet\n")
            w(f"**Metin içermeyen küçük görsel (simge/logo/imza, atlandı):** {gs.get('small_images_skipped', 0)} adet\n")
            w(f"**Açılan EYP/ZIP arşivi:** {gs.get('archive_count', 0)} adet\n")
            w(f"**Bu çalıştırmada yerel OCR ile metne dökülen taranmış ek:** {gs['ocr_converted']} adet\n")
            if gs.get("warning_no_documents"):
                w("\n> ⚠️ **Kaynak klasörde işlenebilir belge bulunamadı.** Doğru dava klasörünü seçtiğinizden emin olun.\n\n")
            w(f"**OCR'lı (taranmış) evrak:** {gs.get('ocr_present', 0)} adet\n")
            w(f"**INDEX.md'de güncellenen karakter sayısı:** {gs['index_synced']} satır\n\n")

            w("## Maskelenen bilgiler\n\n")
            w("| Tür | Maskelenen yer | Farklı değer |\n|---|---:|---:|\n")
            for k, label, unit in names:
                w(f"| {label} | {occ.get(k, 0)} | {dist.get(k, 0)} {unit} |\n")
            w(f"\nToplam maskelenen yer: {sum(occ.values())}\n")
            if role_counts:
                role_summary = ", ".join(f"{r}: {role_counts[r]}" for r in MaskRegistry.PERSON_ROLES if role_counts.get(r))
                if role_summary:
                    w(f"Takma ad verilen kişi sayıları (role göre): {role_summary}\n")
            w("\n")

            if show_person_labels and registry is not None and registry.has_persons():
                labels_by_role: Dict[str, List[str]] = {}
                for lab in registry.person_map().keys():
                    role_part = lab.strip("[]").rsplit("_", 1)[0]
                    labels_by_role.setdefault(role_part, []).append(lab)
                if labels_by_role:
                    w("## Dosyadaki anonim yargı ve taraf etiketleri (gerçek ad içermez)\n\n")
                    w("Yapay zekâ incelemesi için dosyada geçen tutarlı kişi takma adları (gerçek ad-soyad içermez):\n\n")
                    for role_name in MaskRegistry.PERSON_ROLES:
                        labs = labels_by_role.get(role_name)
                        if labs:
                            w(f"- **{role_name}:** " + ", ".join(f"`{lb}`" for lb in labs) + "\n")
                    w("\n")

            w("## Etiketlerin anlamı\n\n")
            w("- Maskeler numaralıdır: `[TCKN_1]`, `[IBAN_2]`, `[ADRES_3]`, `[TEL_1]`, `[SİCİL_4]`, `[HESAP_1]`, "
              "`[KART_1]`, `[SERİ_NO_1]`, `[MRZ_1]`.\n")
            w("- **Kişi takma adları:** `[HAKİM_1]`, `[SAVCI_1]`, `[KÂTİP_1]`, `[DAVACI_1]`, `[DAVALI_1]`, "
              "`[MÜŞTEKİ_1]`, `[ŞÜPHELİ_1]`, `[SANIK_1]`, `[KATILAN_1]`, `[MAĞDUR_1]`, `[TANIK_1]`, "
              "`[ALACAKLI_1]`, `[BORÇLU_1]`, `[KİŞİ_1]`. "
              "Aynı etiket tüm belgelerde aynı kişiyi gösterir; etiket adı kişinin rolünü belirtir "
              "(rol, kişinin dosyada en sık geçen sıfatıdır).\n")
            w("- **Aynı numara = aynı değer.** Aynı kişinin TCKN'si ve adı tüm belgelerde aynı etiketi taşır; farklı "
              "numaralar farklı değerlerdir. Böylece yapay zekâ kimin hangi hesaba/adrese sahip olduğunu "
              "değeri görmeden izleyebilir.\n")
            w("- TCKN, IBAN, telefon, adres, sicil ve kişi ad-soyad eşleme tablosu **bilerek hiçbir yere yazılmadı**; "
              "yalnızca işlem sırasında bellekte tutuldu.\n")
            w("- Adreslerde eşleştirme yaklaşıktır: kısaltmalar (Mah./Mahallesi, Sk./Sokak, No:) ve il/ilçe "
              "kuyruğu yok sayılır; yine de aynı adresin farklı yazımları (ör. '28/3' ile '28 İç Kapı No:3') "
              "farklı numara alabilir.\n")
            w("- Kişi adreslerinde açık adres gizlenir, yalnızca ilçe/il `[ADRES_1] (Kadıköy/İstanbul)` "
              "biçiminde korunur (yetkili mahkeme / tebligat analizi için).\n")
            w("- Kaynakta zaten bulunan eski biçim etiketler (`[ADRES_GİZLENDİ]` vb.) olduğu gibi bırakıldı.\n\n")

            w("## Bilerek korunanlar (maskelenmedi)\n\n")
            if mask_names and mask_judicial_names:
                w("- Taraf sıfatları, avukat/bilirkişi/arabulucu/uzlaştırmacı/noter/kolluk/doktor "
                  "adları, kurum ve şirket adları, anne/baba adı, tek başına geçen ön ad ya da soyad.\n")
                w("- Olay anlatımı, tarihler, esas/karar numaraları, para tutarları, kanun maddeleri ve süreler.\n")
            elif mask_judicial_names and not mask_names:
                w("- Taraf, tanık, avukat, bilirkişi, noter ve kurum ad-soyadları (taraf/tanık adları kullanıcı "
                  "tercihiyle açık bırakıldı; yargı görevlileri — hâkim, savcı, kâtip — adları gizlenir), taraf sıfatları, "
                  "olay anlatımı, tarihler, esas/karar numaraları, para tutarları, kanun maddeleri ve süreler.\n")
            elif mask_names and not mask_judicial_names:
                w("- Taraf sıfatları, hâkim/savcı/kâtip (kullanıcı tercihiyle korundu) ve avukat/bilirkişi/"
                  "arabulucu/uzlaştırmacı/noter/kolluk/doktor adları, kurum ve şirket adları, anne/baba adı, "
                  "tek başına geçen ön ad ya da soyad.\n")
                w("- Olay anlatımı, tarihler, esas/karar numaraları, para tutarları, kanun maddeleri ve süreler.\n")
            else:
                w("- Tüm kişi ad-soyadları (yargı personeli ve taraflar kullanıcı tercihiyle korundu), taraf sıfatları, "
                  "olay anlatımı, tarihler, esas/karar numaraları, para tutarları, kanun maddeleri ve süreler.\n")
            w("- Plaka, olay yeri (ör. 'SUÇUN YERİ', kaza yeri), mahkeme/kurum adları.\n")
            w("- Kurum adresleri: banka genel müdürlüğü/şube, adliye/mahkeme, noter, baro, icra dairesi, kamu "
              "kurumu, PTT, şirket antedi/ticaret odası. Bağlam belirsizse adres kişi adresi sayılıp maskelendi.\n")
            w("- Sabit hat (ör. 0232/0850 ile başlayan kurum telefonları); yalnızca cep telefonları maskelenir.\n")
            w("- Ticaret sicil numaraları, belge doğrulama kodları, KEP / e-posta / web adresleri, Mersis no, banka referans/BPM no.\n\n")

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
            if mask_names:
                w("- Kişi ad-soyadlarında metinli belgeler ile taranmış (OCR) belgelerde yargı/taraf/tanık/imza olarak "
                  "geçen kişiler tanınır; bağlamsız üçüncü kişiler, OCR'ın bozduğu yazımlar ve tek başına geçen ön ad/soyad "
                  "açık kalabilir.\n")
                w("- Doğum tarihi, anne/baba adı ve nüfus kayıt yeri maskelenmez (dava analizi için gereklidir).\n")
            elif mask_judicial_names:
                w("- Taraf/tanık ad-soyadları kullanıcı tercihiyle (--taraf-isimlerini-koru) açık bırakıldı; "
                  "hâkim/savcı/kâtip ad-soyadları gizlenmeye devam eder.\n")
                w("- Doğum tarihi, anne/baba adı ve nüfus kayıt yeri maskelenmez (dava analizi için gereklidir).\n")
            else:
                w("- Ad-soyad (kullanıcı tercihiyle kapatıldı), doğum tarihi, anne/baba adı ve nüfus kayıt yeri "
                  "maskelenmez (dava analizi için gereklidir).\n")
            w("- Vergi kimlik no (VKN), plaka, e-posta adresi maskelenmez.\n")
            w("- Bu klasörde orijinal UDF/PDF/TIFF/görsel dosyası yoktur; yalnızca .md metinleri ve maskeli "
              "JSON manifestleri vardır. Aktarılmayan dosyalara giden bağlantılar düz metne çevrildi.\n")

            w("\n## İşlenemeyen dosyalar\n\n")
            unprocessed = gs.get("unprocessed") or []
            if unprocessed:
                for rel_p, reason in unprocessed:
                    w(f"- {rel_p} — {reason}\n")
            else:
                w("Yok.\n")


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
    parser.add_argument(
        "--taraf-isimlerini-koru",
        action="store_true",
        default=False,
        help="Taraf ve tanık ad-soyadlarını maskelemeden açık bırak (hâkim/savcı/kâtip adları yine maskelenir)",
    )
    parser.add_argument(
        "--isimleri-koru",
        action="store_true",
        default=False,
        help="Eski bayrak (geriye dönük uyumluluk): --taraf-isimlerini-koru ile aynı anlama gelir; taraf/tanık adlarını açık bırakır",
    )
    parser.add_argument(
        "--yargi-isimlerini-koru",
        action="store_true",
        default=False,
        help="Hâkim, savcı ve kâtip adlarını da maskelemeden açık bırak",
    )
    parser.add_argument(
        "--taraf-isimlerini-maskele",
        action="store_true",
        default=False,
        help="Eski bayrak (geriye dönük uyumluluk): taraf/tanık adları artık varsayılan olarak maskelendiği için etkisizdir",
    )

    args = parser.parse_args()
    mask_names = not (bool(args.taraf_isimlerini_koru) or bool(args.isimleri_koru))
    mask_judicial_names = not bool(args.yargi_isimlerini_koru)

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
        real_target = os.path.realpath(target_dir)
        in_place_files: List[str] = []
        for root, dirs, files in os.walk(target_dir):
            if UyapRedactor._is_skipped_dir(root, target_dir, skip_names) or not UyapRedactor._is_safe_src_path(root, real_target):
                dirs[:] = []
                continue
            dirs[:] = sorted(
                d for d in dirs
                if not UyapRedactor._is_skipped_dir(os.path.join(root, d), target_dir, skip_names)
                and UyapRedactor._is_safe_src_path(os.path.join(root, d), real_target)
            )
            for file in sorted(files):
                if file.endswith((".md", ".txt")) and not file.endswith(".bak"):
                    fp_in = os.path.join(root, file)
                    if UyapRedactor._is_safe_src_path(fp_in, real_target):
                        in_place_files.append(fp_in)
        if mask_names or mask_judicial_names:
            prescan_texts: List[str] = []
            for fp in in_place_files:
                try:
                    with open(fp, "r", encoding="utf-8", errors="replace") as rf:
                        raw_t = rf.read()
                    prescan_texts.append(raw_t)
                    UyapRedactor.collect_persons_from_text(raw_t, registry)
                except Exception:
                    pass
            UyapRedactor._prune_corp_candidates(prescan_texts, registry)
            if not mask_names and mask_judicial_names:
                registry.keep_only_roles(MaskRegistry.JUDICIAL_ROLES)
            elif mask_names and not mask_judicial_names:
                registry.remove_roles(MaskRegistry.JUDICIAL_ROLES)
            registry.freeze_persons()
        for fp in in_place_files:
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
            f"Adres: {in_place_stats['adres']}, Kişi: {in_place_stats['kisi']}, Toplam: {in_place_stats['total']}, "
            f"İndeks Senkron: {synced}"
        )
        print("Yerinde maskeleme ve indeks senkronizasyonu tamamlandı.")
        return

    # VARSAYILAN TEK VE ANA İŞLEM: İzole Temiz Klasör Üretimi
    print("=" * 60)
    print("🛡️ UYAP İZOLE TEMİZ DAVA KLASÖRÜ ÜRETİMİ (AI EXPORT)")
    print("=" * 60)
    stage_root = None
    try:
        src_target = args.path
        out_target = args.out
        if os.path.isfile(args.path):
            abs_file = os.path.abspath(args.path)
            stem = os.path.splitext(os.path.basename(abs_file))[0] or "Belge"
            stage_root = tempfile.mkdtemp(prefix="uyap_cli_stage_")
            staged_dir = os.path.join(stage_root, stem)
            os.makedirs(staged_dir, exist_ok=True)
            shutil.copy2(abs_file, os.path.join(staged_dir, os.path.basename(abs_file)))
            src_target = staged_dir
            if not out_target:
                out_target = os.path.join(os.path.dirname(abs_file), f"{stem} (Maskelenmis AI)")
        dest, stats = UyapRedactor.export_isolated_clean_folder(
            src_target,
            out_target,
            mask_names=mask_names,
            mask_judicial_names=mask_judicial_names,
        )
    except ValueError as ve:
        print(f"Hata: {ve}", file=sys.stderr)
        sys.exit(1)
    finally:
        if stage_root:
            shutil.rmtree(stage_root, ignore_errors=True)

    print("\n✅ Maskeli klasör oluşturuldu. Otomatik maskeleme hatasız değildir; paylaşmadan önce raporu ve OCR'lı belgeleri gözden geçirin.")
    if stats.get("warning_no_documents"):
        print("⚠️ Kaynak klasörde işlenebilir belge bulunamadı (.md/.txt/.udf/.doc/.docx/.xlsx/.eyp/.zip/.pdf/.tif/.heic). Klasörü kontrol edin.")
    print(f"📂 Hedef Klasör : {dest}")
    print(f"📄 Aktarılan .md: {stats['md_transferred']} adet")
    print(f"📝 UDF → metin : {stats.get('udf_converted', 0)} adet")
    print(f"💼 Word/Excel  : {stats.get('office_converted', 0)} adet")
    print(f"📑 Metinli PDF : {stats.get('pdf_text_converted', 0)} adet")
    print(f"🖼️ Küçük görsel: {stats.get('small_images_skipped', 0)} adet (simge/logo, atlandı)")
    print(f"📦 EYP/ZIP     : {stats.get('archive_count', 0)} arşiv")
    print(f"👁️ Yerel OCR    : {stats['ocr_converted']} adet")
    print(f"🔄 İndeks Senkron: {stats['index_synced']} kayıt")
    print(f"⚠️ İşlenemeyen : {len(stats.get('unprocessed') or [])} dosya (raporda)")
    print("\n--- GİZLENEN KİŞİSEL VERİLER ---")
    print(f"Maskelenen TCKN          : {stats['tckn']}")
    print(f"Maskelenen Cep Telefonu  : {stats['telefon']}")
    print(f"Maskelenen Kimlik Seri No: {stats['seri_no']}")
    print(f"Maskelenen Kimlik MRZ    : {stats['mrz']}")
    print(f"Maskelenen IBAN / Kart   : {stats['iban']}")
    print(f"Maskelenen Hesap/Müşteri : {stats['hesap']}")
    print(f"Maskelenen Sicil         : {stats['sicil']}")
    print(f"Maskelenen Adres         : {stats['adres']}")
    print(f"Maskelenen Ad-Soyad      : {stats['kisi']} ({stats.get('kisi_sayisi', 0)} kişi)")
    print(f"Toplam Maskeleme         : {stats['total']}")
    print("=" * 60)
    kisi_listesi = stats.get("kisi_listesi") or []
    if kisi_listesi:
        print("\n👤 KİŞİ ETİKETLERİ (yalnızca bu ekranda gösterilir, hiçbir dosyaya kaydedilmez)")
        for lab, real_name in kisi_listesi:
            print(f"  {lab} = {real_name}")


if __name__ == "__main__":
    main()
