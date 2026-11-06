#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UYAP Çevrimdışı Kişisel Veri Maskeleme Aracı (uyap_redactor.py)
--------------------------------------------------------------
Sıfır Veri Değişikliği Prensibi (Non-Destructive):
UYAP dosyalarını salt-okunur (read-only) modda bellekte okur ve yalnızca
belirlenen 4 kişisel veri kategorisini maskeler. Olay örgüsü, tarihler,
para tutarları, mahkeme/esas numaraları, kanun maddeleri ve taraf ad-soyadları
kesinlikle korunur.

Hedef 4 Veri Kategorisi:
1. T.C. Kimlik No / YKN -> [TCKN_GİZLENDİ]
2. IBAN -> [IBAN_GİZLENDİ]
3. Açık Adres -> [ADRES_GİZLENDİ]
4. Hâkim / Savcı / Kâtip Sicil No -> [SİCİL_GİZLENDİ]
"""

import os
import re
import sys
from typing import Dict, Tuple


class UyapRedactor:
    """UYAP metinleri için çevrimdışı, kural tabanlı kişisel veri maskeleme sınıfı."""

    MASK_TCKN = "[TCKN_GİZLENDİ]"
    MASK_IBAN = "[IBAN_GİZLENDİ]"
    MASK_ADRES = "[ADRES_GİZLENDİ]"
    MASK_SICIL = "[SİCİL_GİZLENDİ]"

    # Adli/İdari Unvan listesi (Hâkim, Savcı, Kâtip, Müdür varyasyonları)
    TITLES_REGEX = (
        r'(?:Başkan|Üye|H[aâ]kim|'
        r'(?:(?:Cumhuriyet|Soruşturma|Nöbetçi|Bilişim\s+Suçlar[ıi])\s+)?(?:Baş)?savc[ıi](?:s[ıi])?(?:\s+Vekili)?|'
        r'C\.\s*Savc[ıi]s[ıi]|K[aâ]tip|Z\.?\s*K[aâ]tibi|Zab[ıi]t\s+K[aâ]tibi|'
        r'Yaz[ıi]\s+İşleri\s+Müdürü)'
    )

    @staticmethod
    def _normalize_ocr_digits(val: str) -> str:
        """OCR kaynaklı l/I -> 1, O/o -> 0 dönüşümünü yapar."""
        return (
            val.replace('l', '1')
            .replace('I', '1')
            .replace('O', '0')
            .replace('o', '0')
        )

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
    def redact_iban(cls, text: str) -> Tuple[str, int]:
        """
        Katman 1: TR ile başlayan IBAN numaralarını maskeler.
        Boşluklu, bitişik veya OCR kaynaklı (l/I/O/^) bozulmalı 24 haneli IBAN'ları yakalar.
        """
        count = 0
        pattern = re.compile(
            r'(?i)(?:^|(?<=[\s\*\_\(\[\"\'\:\-\^]))TR[\s\^]*(?:[0-9lIOo][\s\^]*){24}(?![0-9a-zA-ZçğıöşüÇĞİÖŞÜ])'
        )

        def repl(m: re.Match) -> str:
            nonlocal count
            raw = m.group(0)
            # Gerçek rakam sayısı en az 15 olmalı (normal Türkçe kelimeleri korumak için)
            digit_count = sum(c.isdigit() for c in raw)
            if digit_count >= 15:
                count += 1
                return cls.MASK_IBAN
            return raw

        redacted = pattern.sub(repl, text)
        return redacted, count

    @classmethod
    def redact_tckn(cls, text: str) -> Tuple[str, int]:
        """
        Katman 2: TCKN ve YKN numaralarını maskeler.
        1) Açık etiketli (TC Kimlik No:, TCKN:, T.C.123...) ifadeleri (OCR bozulmaları dahil)
        2) Harfe bitişik olsa dahi (?<!\\d)[1-9]\\d{10}(?!\\d) kalıbında algoritmik doğrulamadan geçenleri
        maskeler.
        Telefon numaraları (0 ile başlayan), tarihler ve PTT barkodları (13 hane) korunur.
        """
        count = 0

        # 1. Açık Etiketli TCKN (OCR l/I/O ve 'TC:23236----50' gibi kısmi/bozuk formatlar dahil)
        p_labeled = re.compile(
            r'(?i)(?P<label>\b(?:T\.?\s*C\.?(?:\s*Kimlik)?(?:\s*No(?:su|\.lu|marası)?)?|TCKN|KİMLİK\s+NUMARASI)\s*[:\t\.]?\s*)(?P<num>[0-9lIO\-\^]{11,15})(?!\d)'
        )

        def repl_labeled(m: re.Match) -> str:
            nonlocal count
            raw_num = m.group('num')
            #En az 5 rakam içermeli (tarih vb. olmasın)
            if sum(c.isdigit() for c in raw_num) >= 5:
                count += 1
                return f"{m.group('label')}{cls.MASK_TCKN}"
            return m.group(0)

        text = p_labeled.sub(repl_labeled, text)

        # 1b. Sayı önce, etiket sonra gelen durumlar (örn: "13886414592 T.C'nolu", "12345678901 TC")
        p_num_first = re.compile(
            r'(?i)(?P<num>\b[0-9]{11}\b)(?P<mid>\s*(?:[,\'\-]\s*)?)(?P<label>T\.?\s*C\.?(?:\'?n[uo]l[uo]|\'?de|\'?ye|\.nolu)?|TCKN)',
        )

        def repl_num_first(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{cls.MASK_TCKN}{m.group('mid')}{m.group('label')}"

        text = p_num_first.sub(repl_num_first, text)

        # 2. Rakam olmayan karakterlerle çevrili 11 haneli sayılar (Algoritmik kontrol)
        p_standalone = re.compile(r'(?<!\d)[1-9]\d{10}(?!\d)')

        def repl_standalone(m: re.Match) -> str:
            nonlocal count
            val = m.group(0)
            if cls.is_valid_tckn(val):
                count += 1
                return cls.MASK_TCKN
            return val

        text = p_standalone.sub(repl_standalone, text)
        return text, count

    @classmethod
    def redact_sicil(cls, text: str) -> Tuple[str, int]:
        """
        Katman 3: Hâkim, Savcı, Kâtip ve Müdür sicil numaralarını maskeler.
        Unvan bitişikleri, tutanak başlıkları, imza tabloları, iddianame savcı bloğu
        ve Adli Sicil düzenleyen kişi satırlarındaki 5–6 haneli sicil kodlarını hedefler.
        Para tutarları (örn. 200.000 TL), tarihler ve dosya esas numaraları korunur.
        """
        count = 0
        titles = cls.TITLES_REGEX

        # 1a. Unvan doğrudan önünde olan sicil (örn. "Başkan 211094", "Cumhuriyet Savcısı-234878", "C.Savcısı:194250^")
        p1 = re.compile(rf'(?i)(?P<title>{titles})(?P<mid>[\s\*\-_|:\t]+)(?P<sicil>(?<!\d)\d{{5,6}}(?!\d))')

        def repl1(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('title')}{m.group('mid')}{cls.MASK_SICIL}"

        text = p1.sub(repl1, text)

        # 1b. Unvan doğrudan arkasında olan sicil (örn. "36101 Cumhuriyet Savcısı", "AHMET KABADAYI 123456 Soruşturma Savcısı")
        p2 = re.compile(rf'(?i)(?P<sicil>(?<!\d)\d{{5,6}}(?!\d))(?P<mid>[\s\*\-_|:\t]+)(?P<title>{titles}\b)')

        def repl2(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{cls.MASK_SICIL}{m.group('mid')}{m.group('title')}"

        text = p2.sub(repl2, text)

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

        # 5. Açık etiketli sicil ("Sicil No: 123456", "Sicili : 123456")
        p6 = re.compile(r'(?i)(?P<lead>\bSicil(?:i| No| Numaras[ıi])?[\s\*]*[:\t\-][\s\*]*)(?<!\d)(?P<sicil>\d{4,7})(?!\d)')

        def repl6(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{m.group('lead')}{cls.MASK_SICIL}"

        text = p6.sub(repl6, text)

        return text, count

    @classmethod
    def redact_address(cls, text: str) -> Tuple[str, int]:
        """
        Katman 4: Açık Adres bilgilerini maskeler.
        UYAP standart şablonundaki (Mah./Mh., Cad./Sk., No:, İç Kapı No:, İlçe/İl)
        açık ikametgah, işyeri ve tebligat adreslerini hedefler.
        Nüfus kayıt yerleri (cilt/aile sıra no), doğum yerleri ve taraf ad-soyadları korunur.
        """
        count = 0

        # 1. Açık etiketli adres satırları ("**İkametgah Adresi** **:** ...", "İşyeri Adresi:", "Adres:")
        p1 = re.compile(
            r'(?i)(?P<label>(?:(?:İkam[ae]t(?:g[aâ]h)?|İş\s*yeri|Tebligat)\s*)?Adres(?:i)?[\s\*]*[:\t]+[\s\*]*)'
            r'(?P<addr>[^\r\n]+?)'
            r'(?=(?:\s*(?:Tel\b|ARANMIYOR|TC\s*Kimlik|T\.C\.|SUÇUN\s+TARİHİ|$|\r?\n)))'
        )

        def repl1(m: re.Match) -> str:
            nonlocal count
            addr_val = m.group('addr').strip()
            # "E-Tebligat Adresidir" gibi cümle sonu ibarelerini yanlışlıkla etiket sanma
            if not addr_val or len(addr_val) < 5:
                return m.group(0)
            count += 1
            return f"{m.group('label')}{cls.MASK_ADRES}"

        text = p1.sub(repl1, text)

        # 2. Önceden sınırlandırılmış UYAP adres cümleleri
        # Örn: "... doğumlu ve halen <Mah. Sk. No ...> adresinde oturur."
        # Örn: "... nüfusa kayıtlı <Mah. Sk. No ...> ikamet eder."
        # Örn: "... belirtilen <Mah. Sk. No ...> adresine gidildiğinde"
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

        # 3. Genel Yapısal Açık Adres Kalıbı (Tebligat zarfı, Nüfus Kayıt Örneği, Talimat, BTK tablosu vb.):
        # A) (Mah./Mh./Mahallesi) + (Sk./Sok./Cad./Cd./Bulv./Apt.) + (No / İç Kapı No / Kat / Daire)
        # B) (Cad./Cd./Cadde/Sk./Sok./Sokak/Bulv./Blv.) + (No / Daire / Kat) + (İlçe/İl veya adres ibaresi)
        p3 = re.compile(
            r'(?i)(?P<lead>(?:^|(?<=[\s\|\#\:;\,\.\^\(])))'
            r'(?P<addr>'
            r'(?:[A-ZÇĞİÖŞÜa-zçğıöşü0-9\.\-\/]+\s+){0,4}?'
            r'\b(?:Mahallesi|Mah\.?|Mh\.?|Cadde(?:si)?|Cad\.?|Cd\.?|Sokak|Sokağ[ıi]|Sok\.?|Sk\.?|Bulvar[ıi]|Bulv\.?|Blv\.?|Küme\s*Evler[i]?)[\s\,\.\^\-]+'
            r'[^\r\n\|]{0,60}?'
            r'\b(?:No|[İiIıl]ç\s*Kap[ıi]\s*No|Kat|Daire)[\s\.\-\:\^]*[0-9X][^\r\n\|]{0,60}?'
            r'(?:[A-ZÇĞİÖŞÜa-zçğıöşü\s]{2,25}/\s*[A-ZÇĞİÖŞÜa-zçğıöşü]{2,25})?'
            r')'
            r'(?P<tail>(?=\s+(?:adresinde\s+oturur|ikamet\s+eder|adresinde|adresine|SUÇUN\s+TARİHİ|Tel\b|TC\s*Kimlik|\d{2}\.\d{2}\.\d{4}\b|\d\s+5\d{9}\b)|\s*[\|\r\n]|$))'
        )

        def repl3(m: re.Match) -> str:
            nonlocal count
            if cls.MASK_ADRES in m.group('addr'):
                return m.group(0)
            count += 1
            return f"{m.group('lead')}{cls.MASK_ADRES}"

        text = p3.sub(repl3, text)

        # 4. Kapalı Tebligat çok satırlı devam eden İlçe/İl kuyruk temizliği:
        # "## [ADRES_GİZLENDİ]\n\n## Burdur Merkez/ BURDUR" gibi bölünmüş tebligat adres başlıkları
        p4 = re.compile(
            r'(?P<masked>\[ADRES_GİZLENDİ\])(?P<Ws>\s*\r?\n(?:\s*\r?\n)?[\s\#\*]*)(?P<city>[A-ZÇĞİÖŞÜa-zçğıöşü\s]{2,30}/\s*[A-ZÇĞİÖŞÜa-zçğıöşü]{2,20})(?=\s*\r?\n|$)'
        )
        text = p4.sub(r'\g<masked>', text)

        return text, count

    @classmethod
    def redact_text(cls, text: str) -> Tuple[str, Dict[str, int]]:
        """
        Tüm katmanları sırasıyla uygulayarak metni maskeler.
        Dönüş: (maskelenmiş_metin, istatistik_sözlüğü)
        """
        stats = {
            "iban": 0,
            "tckn": 0,
            "sicil": 0,
            "adres": 0,
            "total": 0,
        }

        # Katman 1: IBAN
        t1, stats["iban"] = cls.redact_iban(text)

        # Katman 2: TCKN
        t2, stats["tckn"] = cls.redact_tckn(t1)

        # Katman 3: Sicil
        t3, stats["sicil"] = cls.redact_sicil(t2)

        # Katman 4: Açık Adres
        t4, stats["adres"] = cls.redact_address(t3)

        stats["total"] = stats["iban"] + stats["tckn"] + stats["sicil"] + stats["adres"]
        return t4, stats

    @classmethod
    def redact_file_to_memory(cls, file_path: str, encoding: str = "utf-8") -> Tuple[str, Dict[str, int]]:
        """
        Dosyayı salt-okunur (read-only) modda belleğe okur ve maskeler.
        Orijinal dosyaya KESİNLİKLE yazma işlemi yapmaz.
        """
        with open(file_path, "r", encoding=encoding) as f:
            content = f.read()
        return cls.redact_text(content)

    @classmethod
    def extract_and_redact_pdf(cls, pdf_path: str, max_pages: int = 150) -> Tuple[str, Dict[str, int]]:
        """
        PDF belgesini çevrimdışı olarak metne dönüştürür ve maskeler.
        1. fitz ile dijital metin katmanı varsa doğrudan alır.
        2. Taranmış fotokopi/resim sayfalarında macOS yerel Apple Vision OCR motorunu kullanır.
        3. Metni UyapRedactor filtrelerinden geçirerek maskeler.
        """
        import tempfile
        try:
            import fitz
        except ImportError:
            return "", {"iban": 0, "tckn": 0, "sicil": 0, "adres": 0, "total": 0}

        try:
            import Vision
            from Cocoa import NSURL
            has_vision = True
        except ImportError:
            has_vision = False

        try:
            doc = fitz.open(pdf_path)
        except Exception:
            return "", {"iban": 0, "tckn": 0, "sicil": 0, "adres": 0, "total": 0}

        page_count = min(len(doc), max_pages)
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

        full_raw = f"# {os.path.basename(pdf_path)}\n\n" + "\n\n---\n\n".join(pages_content)
        return cls.redact_text(full_raw)


def main():
    """CLI giriş noktası (Salt-okunur doğrulama / Dry-run ve izole çıktı)."""
    import argparse

    parser = argparse.ArgumentParser(
        description="UYAP Kişisel Veri Maskeleme Aracı (Pure Python, Varsayılan Salt-Okunur)"
    )
    parser.add_argument("path", help="Hedef dosya veya UYAP dava klasörü yolu")
    parser.add_argument("--out", help="Maskelenmiş dosyaların yazılacağı izole hedef klasör", default=None)
    parser.add_argument(
        "--in-place",
        action="store_true",
        default=False,
        help="Belirtilirse .md dosyalarını yerinde (in-place) maskeler (varsayılan: Kapalı / Salt-Okunur)",
    )
    parser.add_argument("--dry-run", action="store_true", default=True, help="Disk yazımı yapmadan istatistik gösterir (Varsayılan)")

    args = parser.parse_args()

    if not os.path.exists(args.path):
        print(f"Hata: Yol bulunamadı: {args.path}", file=sys.stderr)
        sys.exit(1)

    files_to_process = []
    if os.path.isfile(args.path):
        files_to_process.append(args.path)
    else:
        for root, _, files in os.walk(args.path):
            if "_kaynak" in root or ".git" in root:
                continue
            for file in files:
                if file.endswith((".md", ".txt")):
                    files_to_process.append(os.path.join(root, file))

    total_stats = {"iban": 0, "tckn": 0, "sicil": 0, "adres": 0, "total": 0}
    print(f"Toplam {len(files_to_process)} dosya taranıyor...")

    for fp in files_to_process:
        redacted, stats = UyapRedactor.redact_file_to_memory(fp)
        for k in total_stats:
            total_stats[k] += stats[k]

        if stats["total"] > 0:
            rel = os.path.basename(fp)
            print(f"[{rel}] IBAN: {stats['iban']}, TCKN: {stats['tckn']}, Sicil: {stats['sicil']}, Adres: {stats['adres']}")

        if args.out:
            rel_path = os.path.relpath(fp, args.path if os.path.isdir(args.path) else os.path.dirname(args.path))
            dest_path = os.path.join(args.out, rel_path)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, "w", encoding="utf-8") as f:
                f.write(redacted)
        elif args.in_place and stats["total"] > 0:
            with open(fp, "w", encoding="utf-8") as f:
                f.write(redacted)

    print("\n--- ÖZET İSTATİSTİK ---")
    print(f"Maskelenen IBAN      : {total_stats['iban']}")
    print(f"Maskelenen TCKN      : {total_stats['tckn']}")
    print(f"Maskelenen Sicil     : {total_stats['sicil']}")
    print(f"Maskelenen Adres     : {total_stats['adres']}")
    print(f"Toplam Maskeleme     : {total_stats['total']}")


if __name__ == "__main__":
    main()
