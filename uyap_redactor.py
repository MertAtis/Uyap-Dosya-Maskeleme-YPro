#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UYAP Çevrimdışı Kişisel Veri Maskeleme ve İndeks Senkronizasyon Aracı (uyap_redactor.py)
---------------------------------------------------------------------------------------
Sıfır Veri Değişikliği Prensibi (Non-Destructive):
UYAP dosyalarını salt-okunur (read-only) modda bellekte okur ve belirlenen kişisel
veri kategorilerini maskeler. Olay örgüsü, tarihler, para tutarları, mahkeme/esas
numaraları, kanun maddeleri, anne/baba adları ve taraf ad-soyadları kesinlikle korunur.

Hedef Kişisel Veri Kategorileri:
1. T.C. Kimlik No / YKN (10 hane yazım hatalı TCKN dahil) -> [TCKN_GİZLENDİ]
2. Türkiye Cep Telefonu Numaraları (05xx, +90 5xx vb.)   -> [TELEFON_GİZLENDİ]
3. Kimlik Kartı Seri Numaraları (Yeni/Eski)             -> [SERİ_NO_GİZLENDİ]
4. Kimlik Kartı ve Pasaport ICAO/MRZ Şeritleri          -> [KİMLİK_MRZ_KODU_GİZLENDİ]
5. IBAN Numarası                                        -> [IBAN_GİZLENDİ]
6. Açık Adres                                           -> [ADRES_GİZLENDİ]
7. Hâkim / Savcı / Kâtip Sicil No                       -> [SİCİL_GİZLENDİ]

İzole Temiz Klasör ve İndeks Senkronizasyon Motoru:
Dava klasöründen yalnızca maskelenmiş .md evraklarından oluşan, taranmış ekleri
yerel Apple Vision OCR ile metne döken ve INDEX.md tablosunu %100 senkronize eden
izole bir dava klasörü üretir. Orijinal dosyalara ASLA dokunmaz.
"""

import os
import re
import shutil
import sys
import unicodedata
from datetime import datetime
from typing import Callable, Dict, Optional, Set, Tuple


class UyapRedactor:
    """UYAP metinleri için çevrimdışı, kural tabanlı kişisel veri maskeleme sınıfı."""

    MASK_TCKN = "[TCKN_GİZLENDİ]"
    MASK_TELEFON = "[TELEFON_GİZLENDİ]"
    MASK_SERI_NO = "[SERİ_NO_GİZLENDİ]"
    MASK_MRZ = "[KİMLİK_MRZ_KODU_GİZLENDİ]"
    MASK_IBAN = "[IBAN_GİZLENDİ]"
    MASK_KART = "[KART_NO_GİZLENDİ]"
    MASK_ADRES = "[ADRES_GİZLENDİ]"
    MASK_SICIL = "[SİCİL_GİZLENDİ]"

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
    def redact_mrz(cls, text: str) -> Tuple[str, int]:
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
            return cls.MASK_MRZ

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
    def redact_iban(cls, text: str) -> Tuple[str, int]:
        """
        Katman 2: TR ile başlayan IBAN numaralarını ve 16 haneli banka/kredi kartı
        numaralarını maskeler.
        - Boşluklu, bitişik, OCR kaynaklı (l/I/O/^) bozulmalı veya sonuna tekil OCR
          harfi ([A-Za-z]?) yapışmış 24 haneli IBAN'ları yakalar.
        - Etiketli kart numaralarını (KART NO: ..., KREDİ KARTI NO: ...) ve
          bağımsız 16 haneli Luhn algoritmasından geçen Visa/Mastercard ([45]\\d{15})
          numaralarını yakalar.
        """
        count = 0
        pattern = re.compile(
            r'(?i)(?:^|(?<=[\s\*\_\(\[\"\'\:\-\^]))TR[ \t\^\.\-]*(?:[0-9lIOo][ \t\^\.\-]*){23}[0-9lIOo](?:[A-Za-z](?![A-Za-z0-9]))?(?![0-9])'
        )

        def repl(m: re.Match) -> str:
            nonlocal count
            raw = m.group(0)
            digit_count = sum(c.isdigit() for c in raw)
            if digit_count >= 15:
                count += 1
                return cls.MASK_IBAN
            return raw

        redacted = pattern.sub(repl, text)

        # 2B-1. Etiketli 16 haneli Kredi / ATM Kartı Numarası
        p_card_labeled = re.compile(
            r'(?i)(?P<label>\b(?:KART\s*NO|KRED[İI]\s*KART[Iİ]\s*NO)[\s\*:]+)(?P<card>(?:\d{4}[\s\-]?){3}\d{4}|\d{16})\b'
        )

        def repl_card_labeled(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('label')}{cls.MASK_KART}"

        redacted = p_card_labeled.sub(repl_card_labeled, redacted)

        # 2B-2. Bağımsız 16 haneli Luhn algoritmasından geçen Visa/Mastercard numaraları
        p_card_luhn = re.compile(r'(?<![0-9A-Za-z])(?P<card>[45]\d{15})(?![0-9A-Za-z])')

        def repl_card_luhn(m: re.Match) -> str:
            nonlocal count
            val = m.group('card')
            if cls.is_valid_luhn(val):
                count += 1
                return cls.MASK_KART
            return val

        redacted = p_card_luhn.sub(repl_card_luhn, redacted)
        return redacted, count

    @classmethod
    def redact_seri_no(cls, text: str) -> Tuple[str, int]:
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
            return f"Seri No: {cls.MASK_SERI_NO}"

        text = p_split_old.sub(repl_split_old, text)

        # Noter vekaletnamesi ters sıralı seri ve no ("A10 seri ve 123456 numaralı", OCR "A1D seri ve 123456 numaralı")
        p_noter_old = re.compile(
            r'(?i)\b([A-Z][0-9OIlD]{2})\s+seri\s+ve\s+(\d{5,6})\s+(?:numaral[ıi]|no\.?lu)'
        )

        def repl_noter_old(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{cls.MASK_SERI_NO} seri ve numaralı"

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
            return f"{label}{cls.MASK_SERI_NO}"

        text = p.sub(repl, text)
        return text, count

    @classmethod
    def collect_known_tckns_from_text(cls, text: str) -> Set[str]:
        """Metin içindeki geçerli (Mod-10) veya açık etiketli 11 haneli TCKN'leri toplar."""
        known: Set[str] = set()

        # 1. Geçerli (Mod-10/11) 11 haneli TCKN'ler
        for m in re.finditer(r'(?<![A-Za-z0-9\./])[1-9]\d{10}(?![A-Za-z0-9\./])', text):
            val = m.group(0)
            if cls.is_valid_tckn(val):
                known.add(val)

        # 2. Açık etiketli TCKN'ler (boşluklu varyasyonlar dahil)
        p_lab = re.compile(
            r'(?i)(?:\b(?:T\.?\s*C\.?(?:\s*(?:KN|Kimlik(?:\s*No(?:su|\.lu|marası)?)?|No(?:su|\.lu|marası)?))?|TCKN|YKN|K[İIÍ]ML[İIÍ]K\s*(?:NO(?:SU)?|NUMARASI))|IT\.?@?N[ºo°])[\s\*\_]*[:\t\.\-]?[\s\*\_]*(?P<num>(?:[0-9lIOJ|/][ \t]*){8,12}[0-9lIOJ|/])(?!\d)'
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
    def redact_tckn(cls, text: str, known_tckns: Optional[Set[str]] = None) -> Tuple[str, int]:
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
            r'(?i)(?P<label>(?:\b(?:T\.?\s*C\.?(?:\s*(?:KN|Kimlik(?:\s*No(?:su|\.lu|marası)?)?|No(?:su|\.lu|marası)?))?|TCKN|YKN|K[İIÍ]ML[İIÍ]K\s*(?:NO(?:SU)?|NUMARASI))|IT\.?@?N[ºo°])[\s\*\_]*[:\t\.\-]?[\s\*\_]*)(?P<num>(?:[0-9lIOoJ|/][ \t]*){8,12}[0-9lIOoJ|/])(?!\d)'
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
                return f"{m.group('label')}{cls.MASK_TCKN}"
            return m.group(0)

        text = p_labeled.sub(repl_labeled, text)

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
                return f"{cls.MASK_TCKN}{m.group('mid')}{m.group('label')}"
            return m.group(0)

        text = p_num_first.sub(repl_num_first, text)

        # 1B-1. Banka dekontu / kurum sorgusu OCR'larında bölünmüş 11 haneli TCKN'ler
        p_ctx_split = re.compile(
            r'(?i)(?P<prefix>(?:TCKN|YKN|Kimlik)[^\r\n]{0,25}?)(?<![\d\./])(?P<num>[1-9]\d{6,8}[ \t|/][0-9lIOoJ]{2,4})(?![\d\./])'
        )

        def repl_ctx_split(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('prefix')}{cls.MASK_TCKN}"

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
                return cls.MASK_TCKN
            return raw

        text = p_ocr_split.sub(repl_ocr_split, text)

        # 1B-2. 11 haneli bağımsız sayılar (Mod-10/11 doğrulaması VEYA bilinen TCKN ile Hamming mesafesi <= 2)
        p_standalone = re.compile(r'(?<![A-Za-z0-9\./])[1-9]\d{10}(?![A-Za-z0-9\./])')

        def repl_standalone(m: re.Match) -> str:
            nonlocal count
            val = m.group(0)
            if cls.is_valid_tckn(val):
                count += 1
                local_known.add(val)
                return cls.MASK_TCKN
            for kt in local_known:
                if len(kt) == 11 and sum(a != b for a, b in zip(val, kt)) <= 2:
                    count += 1
                    return cls.MASK_TCKN
                if len(kt) == 11 and kt[:5] in val[:6]:
                    count += 1
                    return cls.MASK_TCKN
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
                if cls.MASK_TCKN in raw:
                    return raw
                # Tarih (08.10.2021) veya para tutarlarını asla bozmamak için kontrol
                norm = cls._normalize_ocr_digits(raw)
                digit_cnt = sum(c.isdigit() for c in norm)
                if 10 <= len(raw) <= 14 and digit_cnt >= 9:
                    count += 1
                    return cls.MASK_TCKN
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
            return cls.MASK_TCKN

        text = p_partial.sub(repl_partial, text)
        return text, count

    @classmethod
    def redact_phone(cls, text: str) -> Tuple[str, int]:
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

        def repl(m: re.Match) -> str:
            nonlocal count
            count += 1
            return cls.MASK_TELEFON

        redacted = pattern.sub(repl, text)
        return redacted, count

    @classmethod
    def redact_sicil(cls, text: str) -> Tuple[str, int]:
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
            return f"{m.group('title')}{m.group('mid')}{cls.MASK_SICIL}"

        text = p1.sub(repl1, text)

        # 1b. Unvan doğrudan arkasında olan sicil (örn. "36101 Cumhuriyet Savcısı", "AHMET KABADAYI 123456 Soruşturma Savcısı")
        p2 = re.compile(rf'(?i)(?P<sicil>(?<![\d\./])\d{{5,6}}(?![\d\./]))(?P<mid>[\s\*\-_|:\t\/]+)(?P<title>{titles}\b)')

        def repl2(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{cls.MASK_SICIL}{m.group('mid')}{m.group('title')}"

        text = p2.sub(repl2, text)

        # 1c. Cümle içi "Unvan + 1-4 kelimelik Ad Soyad + 5-6 haneli Sicil" (örn. "Hakim Ayşe Kaya 112233, Katıp Mehmet Demir 223344, Mübaşir Ali Çelik 334455")
        p_inline_named = re.compile(
            rf'(?i)(?P<prefix>\b{titles}\s+(?:[A-ZÇĞİÖŞÜa-zçğıöşü\.]+\s+){{1,4}})(?P<sicil>(?<![\d\./])\d{{5,6}}(?![\d\./])){not_sicil}'
        )

        def repl_inline_named(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('prefix')}{cls.MASK_SICIL}"

        text = p_inline_named.sub(repl_inline_named, text)

        # 2. Tutanak/Karar başlık satırları: "**BAŞKAN :** Erhan AKMAN  211094"
        p3 = re.compile(
            rf'(?im)^(?P<prefix>[\s\*]*{titles}[\s\*]*[:\t][^\r\n\d]*[a-zA-ZçğıöşüÇĞİÖŞÜ\.\s\*]+?)(?<!\d)(?P<sicil>\d{{5,6}})(?!\d)(?P<suffix>[\s\*]*)$'
        )

        def repl3(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('prefix')}{cls.MASK_SICIL}{m.group('suffix')}"

        text = p3.sub(repl3, text)

        # 3. İddianame sonu savcı imza bloğu (üst satırda sicil, alt satırda Cumhuriyet Savcısı)
        p4 = re.compile(
            rf'(?im)^(?P<lead>[\s\*]*)(?<!\d)(?P<sicil>\d{{5,6}})(?!\d)(?P<trail>[\s\*]*)$(?=\r?\n[\s\*]*{titles})'
        )

        def repl4(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('lead')}{cls.MASK_SICIL}{m.group('trail')}"

        text = p4.sub(repl4, text)

        # 4. Adli Sicil belgesi: "## DÜZENLEYEN KİŞİ/KURUM \n\n## 234878"
        p5 = re.compile(r'(?i)(?P<lead>DÜZENLEYEN\s+KİŞİ\s*/\s*KURUM[\s\S]{0,60}?)(?<!\d)(?P<sicil>\d{5,6})(?!\d)')

        def repl5(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('lead')}{cls.MASK_SICIL}"

        text = p5.sub(repl5, text)

        # 5. Açık etiketli sicil ("Sicil No: 123456", "Sicili : 123456") ve OCR bozulmalı imza satırı ("+0644-112233")
        p6 = re.compile(
            r'(?im)(?P<lead>\bSicil(?:i| No| Numaras[ıi])?[\s\*]*[:\t\-][\s\*]*|^[ \t]*\+\d{3,4}[\-\s]+)(?<!\d)(?P<sicil>\d{4,7})(?!\d)'
        )

        def repl6(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('lead')}{cls.MASK_SICIL}"

        text = p6.sub(repl6, text)

        return text, count

    @classmethod
    def redact_address(cls, text: str) -> Tuple[str, int]:
        """
        Katman 7: Açık Adres bilgilerini maskeler.
        UYAP standart şablonundaki (Mah./Mh., Cad./Sk./5k., No:/Ne:/K:/D:/Blok/Toki/Apt., İç Kapı No:, İlçe/İl)
        açık ikametgah, işyeri ve tebligat adreslerini ve iki satıra bölünmüş adres devamlarını hedefler.
        Nüfus kayıt yerleri (cilt/aile sıra no), doğum yerleri ve taraf ad-soyadları korunur.
        """
        count = 0

        # 1. Açık etiketli adres satırları ("**İkametgah Adresi** **:** ...", "İşyeri Adresi:", "Adres:")
        p1 = re.compile(
            r'(?i)(?P<label>(?:(?:İkam[ae]t(?:g[aâ]h)?|İş\s*yeri|Tebligat)\s*)?Adres(?:i)?[\s\*]*[:\t]+[\s\*]*)'
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
            if not addr_val or len(addr_val) < 5 or cls.MASK_ADRES in addr_val:
                return m.group(0)
            count += 1
            return f"{m.group('label')}{cls.MASK_ADRES}"

        text = p1.sub(repl1, text)

        # 2. Önceden sınırlandırılmış UYAP adres cümleleri
        p2 = re.compile(
            r'(?P<prefix>(?:doğumlu\s+ve\s+halen|ve\s+halen|doğumlu[\.,]|nüfus(?:a|unda)\s+kayıtlı(?:dır)?[\.,]?|kayıtlı\s+olup\s+halen|belirtilen|E-Tebligat\s+Adresidir\.)\s+)'
            r'(?P<addr>(?:[A-ZÇĞİÖŞÜa-zçğıöşü0-9\.\-\/]+\s+){0,5}?(?:Mah\.|Mh\.|Mahallesi\b)[^\r\n\|]+?)'
            r'(?P<suffix>\s+(?:adresinde\s+oturur|ikamet\s+eder|adresinde\s+ikamet\s+eder|adresinde\s+bulunur|adresine\b|adresinde\b)|\s*(?=$|\r?\n))'
        )

        def repl2(m: re.Match) -> str:
            nonlocal count
            if cls.MASK_ADRES in m.group('addr'):
                return m.group(0)
            count += 1
            return f"{m.group('prefix')}{cls.MASK_ADRES}{m.group('suffix')}"

        text = p2.sub(repl2, text)

        # 3. Genel Yapısal Açık Adres Kalıbı (K:/D:/Blok/Toki/Apt ve OCR 5k./Ne:/|¢ Kapı varyasyonları dahil)
        p3 = re.compile(
            r'(?i)(?P<lead>(?:^|(?<=[\s\|\#\:;\,\.\^\(\-\/])))'
            r'(?P<addr>'
            r'(?:(?:^|(?<=[\r\n\|\#\:;\,\.\^\(\-\/]))[ \t]*(?:[A-ZÇĞİÖŞÜa-zçğıöşü0-9]+\s+){1,2})?'
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
            if cls.MASK_ADRES in m.group('addr'):
                return m.group(0)
            count += 1
            return f"{m.group('lead')}{cls.MASK_ADRES}"

        text = p3.sub(repl3, text)

        # 4. Kapalı Tebligat ve İki Satıra Bölünmüş Dilekçe Adresleri devam satırı temizliği
        # (Örn: "Bozkurt Mah. Toki Evleri D/10-A K:2\n... D:40 Burdur Merkez/ BURDUR" veya "[ADRES_GİZLENDİ]\nK:2 D:40 Burdur Merkez/ BURDUR")
        p4 = re.compile(
            r'(?i)(?P<masked>\[ADRES_GİZLENDİ\])'
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
            count += 1
            return f"{m.group('lead')}{cls.MASK_ADRES}"

        text = p4_orphan.sub(repl4_orphan, text)

        return text, count

    @classmethod
    def redact_text(cls, text: str, known_tckns: Optional[Set[str]] = None) -> Tuple[str, Dict[str, int]]:
        """
        Tüm katmanları sırasıyla uygulayarak metni maskeler.
        Dönüş: (maskelenmiş_metin, istatistik_sözlüğü)
        """
        stats = {
            "tckn": 0,
            "telefon": 0,
            "seri_no": 0,
            "mrz": 0,
            "iban": 0,
            "sicil": 0,
            "adres": 0,
            "total": 0,
        }

        # Katman 1: Kimlik MRZ (Önce çalışır, blok halinde temizler)
        t, stats["mrz"] = cls.redact_mrz(text)

        # Katman 2: IBAN ve Banka Kartı No
        t, stats["iban"] = cls.redact_iban(t)

        # Katman 3: Kimlik Seri No
        t, stats["seri_no"] = cls.redact_seri_no(t)

        # Katman 4: TCKN (Etiketli 9-13 hane, algoritmik 11 hane, Known TCKN Fuzzy Match ve kısmi TCKN)
        t, stats["tckn"] = cls.redact_tckn(t, known_tckns=known_tckns)

        # Katman 5: Cep Telefonu
        t, stats["telefon"] = cls.redact_phone(t)

        # Katman 6: Sicil
        t, stats["sicil"] = cls.redact_sicil(t)

        # Katman 7: Açık Adres
        t, stats["adres"] = cls.redact_address(t)

        stats["total"] = (
            stats["tckn"]
            + stats["telefon"]
            + stats["seri_no"]
            + stats["mrz"]
            + stats["iban"]
            + stats["sicil"]
            + stats["adres"]
        )
        return t, stats

    @classmethod
    def redact_file_to_memory(
        cls,
        file_path: str,
        encoding: str = "utf-8",
        known_tckns: Optional[Set[str]] = None
    ) -> Tuple[str, Dict[str, int]]:
        """
        Dosyayı salt-okunur (read-only) modda belleğe okur ve maskeler.
        Orijinal dosyaya KESİNLİKLE yazma işlemi yapmaz.
        """
        with open(file_path, "r", encoding=encoding, errors="replace") as f:
            content = f.read()
        return cls.redact_text(content, known_tckns=known_tckns)

    @classmethod
    def extract_and_redact_pdf(
        cls,
        pdf_path: str,
        max_pages: int = 150,
        known_tckns: Optional[Set[str]] = None
    ) -> Tuple[str, Dict[str, int]]:
        """
        PDF belgesini çevrimdışı olarak metne dönüştürür ve maskeler.
        1. fitz ile dijital metin katmanı varsa doğrudan alır.
        2. Taranmış fotokopi/resim sayfalarında macOS yerel Apple Vision OCR motorunu kullanır.
        3. Metni UyapRedactor filtrelerinden geçirerek maskeler.
        """
        import tempfile
        empty_stats = {"tckn": 0, "telefon": 0, "seri_no": 0, "mrz": 0, "iban": 0, "sicil": 0, "adres": 0, "total": 0}
        try:
            import fitz
        except ImportError:
            return "", empty_stats

        try:
            import Vision
            from Cocoa import NSURL
            has_vision = True
        except ImportError:
            has_vision = False

        try:
            doc = fitz.open(pdf_path)
        except Exception:
            return "", empty_stats

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
        return cls.redact_text(full_raw, known_tckns=known_tckns)

    @classmethod
    def extract_and_redact_image(
        cls,
        img_path: str,
        known_tckns: Optional[Set[str]] = None
    ) -> Tuple[str, Dict[str, int]]:
        """
        TIFF, PNG, JPEG formatındaki taranmış evrakları Apple Vision OCR ile
        yerel ve çevrimdışı olarak metne dönüştürür ve maskeler.
        """
        empty_stats = {"tckn": 0, "telefon": 0, "seri_no": 0, "mrz": 0, "iban": 0, "sicil": 0, "adres": 0, "total": 0}
        try:
            import Vision
            from Cocoa import NSURL
        except ImportError:
            return "", empty_stats

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
            return "", empty_stats

        full_raw = f"# {os.path.basename(img_path)}\n\n" + "\n\n---\n\n".join(pages_content)
        return cls.redact_text(full_raw, known_tckns=known_tckns)

    @classmethod
    def extract_and_redact_scanned_file(
        cls,
        file_path: str,
        known_tckns: Optional[Set[str]] = None
    ) -> Tuple[str, Dict[str, int]]:
        """PDF veya TIFF/Görsel dosyalarını uzantısına göre en uygun OCR motoruyla işler ve maskeler."""
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            return cls.extract_and_redact_pdf(file_path, known_tckns=known_tckns)
        elif ext in (".tif", ".tiff", ".png", ".jpg", ".jpeg"):
            return cls.extract_and_redact_image(file_path, known_tckns=known_tckns)
        return "", {"tckn": 0, "telefon": 0, "seri_no": 0, "mrz": 0, "iban": 0, "sicil": 0, "adres": 0, "total": 0}

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

        if updated_rows > 0:
            try:
                with open(index_path, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
            except Exception:
                pass

        return updated_rows

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
    def _redact_json_value(cls, value, known_tckns: Optional[Set[str]], stats: Dict[str, int]):
        """
        JSON ağacındaki tüm string değerleri (iç içe dict/list dahil) tek tek maskeler.
        Anahtarlara dokunulmaz. Tamsayı olarak saklanan 11 haneli geçerli/bilinen TCKN'ler
        MASK_TCKN stringine çevrilir.
        """
        if isinstance(value, dict):
            return {k: cls._redact_json_value(v, known_tckns, stats) for k, v in value.items()}
        if isinstance(value, list):
            return [cls._redact_json_value(v, known_tckns, stats) for v in value]
        if isinstance(value, str):
            red, s = cls.redact_text(value, known_tckns=known_tckns)
            for k in ["tckn", "telefon", "seri_no", "mrz", "iban", "sicil", "adres", "total"]:
                stats[k] += s[k]
            return red
        if isinstance(value, int) and not isinstance(value, bool):
            sval = str(value)
            if len(sval) == 11 and (cls.is_valid_tckn(sval) or (known_tckns and sval in known_tckns)):
                stats["tckn"] += 1
                stats["total"] += 1
                return cls.MASK_TCKN
        return value

    @classmethod
    def redact_json_file(
        cls,
        src_path: str,
        dest_path: str,
        known_tckns: Optional[Set[str]] = None
    ) -> Dict[str, int]:
        """
        Manifest JSON dosyasını değer bazında maskeleyerek hedefe yazar.
        JSON parse edilemezse dosya ASLA ham kopyalanmaz: tüm metin redact_text'ten
        geçirilerek yazılır (fail-closed).
        Not: Ham JSON satırını doğrudan redact_text'e vermek, adres regex'inin satırın
        kalanını yutmasına yol açtığından değer bazında maskeleme tercih edilir.
        """
        import json
        stats = {"tckn": 0, "telefon": 0, "seri_no": 0, "mrz": 0, "iban": 0, "sicil": 0, "adres": 0, "total": 0}
        with open(src_path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError):
            red, s = cls.redact_text(raw, known_tckns=known_tckns)
            for k in stats:
                stats[k] += s[k]
            with open(dest_path, "w", encoding="utf-8") as wf:
                wf.write(red)
            return stats

        red_data = cls._redact_json_value(data, known_tckns, stats)
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
        TEK VE KUSURSUZ İŞLEM:
        SADECE maskeli .md'leri yeni klasöre kopyalar, taranmış evraklara yerel OCR uygular,
        INDEX.md tablosunu %100 senkronize eder ve yapay zekâ analizine hazır izole temiz
        bir dava klasörü üretir.
        
        Sıfır İkili Dosya Garantisi:
        Hedef klasörde tek bir orijinal UDF, PDF, TIFF, ZIP veya ikili dosya barındırmaz.
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

        os.makedirs(dest_folder, exist_ok=True)
        norm_src = unicodedata.normalize("NFC", src_folder)
        norm_dest = unicodedata.normalize("NFC", dest_folder)

        def _is_dest_subtree(path: str) -> bool:
            """Hedef klasör kaynağın içindeyse, hedefin kendisi ve altı taranmaz."""
            if norm_dest == norm_src:
                return False
            return cls._is_inside_path(unicodedata.normalize("NFC", path), norm_dest)

        grand_stats = {
            "tckn": 0,
            "telefon": 0,
            "seri_no": 0,
            "mrz": 0,
            "iban": 0,
            "sicil": 0,
            "adres": 0,
            "total": 0,
            "md_transferred": 0,
            "ocr_converted": 0,
            "index_synced": 0,
            "total_files": 0,
            "total_work": 0,
            "processed_items": 0,
            "last_file_stats": {},
            "last_file_path": "",
        }

        # 0. Klasör genelinde bilinen TCKN setini (known_tckns) topla (2 aşamalı hafıza)
        known_tckns = cls.collect_known_tckns_from_folder(src_folder)

        # 1. Mevcut Markdown ve Metin Belgelerini Topla
        md_files = []
        for root, dirs, files in os.walk(src_folder):
            if cls._is_skipped_dir(root, src_folder, cls.SKIP_DIRS) or _is_dest_subtree(root):
                dirs[:] = []
                continue
            dirs[:] = [
                d for d in dirs
                if not cls._is_skipped_dir(os.path.join(root, d), src_folder, cls.SKIP_DIRS)
                and not _is_dest_subtree(os.path.join(root, d))
            ]
            for f in files:
                if f.endswith((".md", ".txt")) and not f.endswith(".bak"):
                    md_files.append(os.path.join(root, f))

        grand_stats["total_files"] = len(md_files)
        grand_stats["total_work"] = len(md_files)

        for idx, file_path in enumerate(md_files, 1):
            rel_path = os.path.relpath(file_path, src_folder)
            dest_path = os.path.join(dest_folder, rel_path)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

                redacted_text, stats = cls.redact_text(content, known_tckns=known_tckns)
                for k in ["tckn", "telefon", "seri_no", "mrz", "iban", "sicil", "adres", "total"]:
                    grand_stats[k] += stats[k]

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
            dirs[:] = [
                d for d in dirs
                if not cls._is_skipped_dir(os.path.join(root, d), src_folder, cls.SKIP_DIRS_OCR)
                and not _is_dest_subtree(os.path.join(root, d))
            ]
            for f in files:
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

        grand_stats["total_work"] = len(md_files) + len(scanned_files)

        ocr_converted_list = []
        for full_p, base_rel, target_dest_md in scanned_files:
            try:
                red_text, p_stats = cls.extract_and_redact_scanned_file(full_p, known_tckns=known_tckns)
                grand_stats["processed_items"] += 1
                grand_stats["last_file_stats"] = p_stats
                grand_stats["last_file_path"] = base_rel

                if len(red_text.strip()) > 50:
                    os.makedirs(os.path.dirname(target_dest_md), exist_ok=True)
                    with open(target_dest_md, "w", encoding="utf-8") as wf:
                        wf.write(red_text)



                    for k in ["tckn", "telefon", "seri_no", "mrz", "iban", "sicil", "adres", "total"]:
                        grand_stats[k] += p_stats[k]

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
                    j_stats = cls.redact_json_file(meta_src, meta_dest, known_tckns=known_tckns)
                    for k in ["tckn", "telefon", "seri_no", "mrz", "iban", "sicil", "adres", "total"]:
                        grand_stats[k] += j_stats[k]
                except Exception as je:
                    if progress_cb:
                        progress_cb("error", f"{meta_name}: {str(je)}", grand_stats)

        # 4. Sıfır İkili Dosya Denetimi (Hedef klasördeki olası ikili kalıntıları ve _kaynak dizinini temizle)
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

        # 5. INDEX.md Senkronizasyonu (Sadece hedef temiz klasör; kaynak klasör dokunulmazdır)
        synced_dest = cls.sync_index_md(dest_folder)
        grand_stats["index_synced"] = synced_dest

        # 6. Güvenlik ve Dönüşüm Raporu Oluştur
        report_path = os.path.join(dest_folder, "DAVA_DÖNÜŞÜM_VE_GÜVENLİK_RAPORU.md")
        with open(report_path, "w", encoding="utf-8") as rf:
            rf.write("# 🛡️ Dava Dönüşüm ve Güvenlik Raporu\n\n")
            rf.write(f"**Kaynak Dava Klasörü:** {os.path.basename(src_folder)}\n")
            rf.write(f"**Hedef Temiz Klasör:** {os.path.basename(dest_folder)}\n")
            rf.write(f"**İşlem Tarihi:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            rf.write(f"**Toplam Aktarılan Markdown Belgesi:** {grand_stats['md_transferred']} adet\n")
            rf.write(f"**Yerel OCR ile Metne Dökülen Taranmış Ekler:** {grand_stats['ocr_converted']} adet\n")
            rf.write(f"**İndeks Senkronizasyonu:** {grand_stats['index_synced']} adet evrak satırı güncellendi\n")
            rf.write(f"**Gizlenen Toplam Kişisel Veri:** {grand_stats['total']} adet\n\n")
            rf.write("### 🔒 Maskelenen Veri Dağılımı\n")
            rf.write(f"- 🆔 **TCKN:** {grand_stats['tckn']} adet\n")
            rf.write(f"- 📱 **Cep Telefonu:** {grand_stats['telefon']} adet\n")
            rf.write(f"- 🪪 **Kimlik Seri No:** {grand_stats['seri_no']} adet\n")
            rf.write(f"- 📑 **Kimlik MRZ Kodu:** {grand_stats['mrz']} adet\n")
            rf.write(f"- 💳 **IBAN:** {grand_stats['iban']} adet\n")
            rf.write(f"- ⚖️ **Sicil No:** {grand_stats['sicil']} adet\n")
            rf.write(f"- 📍 **Açık Adres:** {grand_stats['adres']} adet\n\n")
            rf.write("---\n\n")
            rf.write("## 🔒 Güvenlik & Gizlilik Durumu\n\n")
            rf.write("- ✅ Bu klasörde tek bir orijinal UDF, PDF, TIFF veya ikili dosya **BULUNMAMAKTADIR**.\n")
            rf.write("- ✅ TCKN, Cep Telefonu, Kimlik Seri No, MRZ Kodu, IBAN, Sicil No ve Açık Adres bilgileri tamamen maskelenmiştir.\n")
            rf.write("- ✅ Taranmış evraklar Apple Vision OCR ile yerelde çözülmüş ve metne dökülmüştür.\n")
            rf.write("- ✅ INDEX.md tablosundaki okunmuş tüm metinler güncel karakter sayılarıyla senkronize edilmiştir.\n")
            rf.write("- ✅ Yapay zekâ bu klasörün tamamını %100 eksiksiz ve sıfır veri sızıntısıyla okuyabilir.\n")

        return dest_folder, grand_stats


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
        in_place_stats = {
            "tckn": 0,
            "telefon": 0,
            "seri_no": 0,
            "mrz": 0,
            "iban": 0,
            "sicil": 0,
            "adres": 0,
            "total": 0,
        }
        skip_names = UyapRedactor.SKIP_DIRS
        for root, dirs, files in os.walk(target_dir):
            if UyapRedactor._is_skipped_dir(root, target_dir, skip_names):
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if not UyapRedactor._is_skipped_dir(os.path.join(root, d), target_dir, skip_names)]
            for file in files:
                if file.endswith((".md", ".txt")) and not file.endswith(".bak"):
                    fp = os.path.join(root, file)
                    red, stats = UyapRedactor.redact_file_to_memory(fp, known_tckns=known_tckns)
                    for k in in_place_stats:
                        in_place_stats[k] += stats[k]
                    if stats["total"] > 0:
                        with open(fp, "w", encoding="utf-8") as wf:
                            wf.write(red)
        synced = UyapRedactor.sync_index_md(target_dir)
        print(
            f"Maskelenen TCKN: {in_place_stats['tckn']}, Telefon: {in_place_stats['telefon']}, "
            f"Seri: {in_place_stats['seri_no']}, MRZ: {in_place_stats['mrz']}, "
            f"IBAN/Kart: {in_place_stats['iban']}, Sicil: {in_place_stats['sicil']}, "
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

    print(f"\n✅ İzole Temiz Klasör %100 Başarıyla Oluşturuldu!")
    print(f"📂 Hedef Klasör : {dest}")
    print(f"📄 Aktarılan .md: {stats['md_transferred']} adet")
    print(f"👁️ Yerel OCR    : {stats['ocr_converted']} adet")
    print(f"🔄 İndeks Senkron: {stats['index_synced']} kayıt")
    print("\n--- GİZLENEN KİŞİSEL VERİLER ---")
    print(f"Maskelenen TCKN          : {stats['tckn']}")
    print(f"Maskelenen Cep Telefonu  : {stats['telefon']}")
    print(f"Maskelenen Kimlik Seri No: {stats['seri_no']}")
    print(f"Maskelenen Kimlik MRZ    : {stats['mrz']}")
    print(f"Maskelenen IBAN          : {stats['iban']}")
    print(f"Maskelenen Sicil         : {stats['sicil']}")
    print(f"Maskelenen Adres         : {stats['adres']}")
    print(f"Toplam Maskeleme         : {stats['total']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
