#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UYAP Maskeleme ve İndeks Senkronizasyon Test Paketi (Adversarial Güvenlik & Doğrulama)
"""

import os
import re
import sys
import tempfile
import unicodedata
import unittest
import zipfile
from unittest.mock import patch

# Modülü içeri aktar
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from uyap_redactor import UyapRedactor, MaskRegistry


class TestUyapRedactor(unittest.TestCase):

    def test_phone_variations(self):
        """1. Cep telefonu numaralarının tüm varyasyonlarının maskelenmesi."""
        test_cases = [
            ("Müvekkil tel: 05321112233", "Müvekkil tel: [TELEFON_GİZLENDİ]"),
            ("İletişim: 5321112233", "İletişim: [TELEFON_GİZLENDİ]"),
            ("GSM: +90 532 111 22 33", "GSM: [TELEFON_GİZLENDİ]"),
            ("Telefon: 0 (532) 111 22 33", "Telefon: [TELEFON_GİZLENDİ]"),
            ("Tel: (532) 111 22 33", "Tel: [TELEFON_GİZLENDİ]"),
            ("0532-111-22-33", "[TELEFON_GİZLENDİ]"),
            ("0532.111.22.33", "[TELEFON_GİZLENDİ]"),
            ("0 532 111 22 33", "[TELEFON_GİZLENDİ]"),
            ("+905321112233", "[TELEFON_GİZLENDİ]"),
            ("0532 111 2233", "[TELEFON_GİZLENDİ]"),
            ("0532 1112233", "[TELEFON_GİZLENDİ]"),
            ("(0532) 111 22 33", "[TELEFON_GİZLENDİ]"),
            # Şartnamede belirtilen ekstra varyasyonlar
            ("05321234567", "[TELEFON_GİZLENDİ]"),
            ("5321234567", "[TELEFON_GİZLENDİ]"),
            ("+90 532 123 45 67", "[TELEFON_GİZLENDİ]"),
            ("0 (532) 123 45 67", "[TELEFON_GİZLENDİ]"),
            ("(0532) 123 45 67", "[TELEFON_GİZLENDİ]"),
            ("0532-123-45-67", "[TELEFON_GİZLENDİ]"),
            ("0532.123.45.67", "[TELEFON_GİZLENDİ]"),
            ("Tel: 532 1234567", "Tel: [TELEFON_GİZLENDİ]"),
        ]
        for inp, expected in test_cases:
            redacted, count = UyapRedactor.redact_phone(inp)
            self.assertEqual(redacted, expected, f"Failed for: {inp}")
            self.assertEqual(count, 1, f"Count should be 1 for: {inp}")

    def test_phone_negatives(self):
        """1b. Negatif Doğrulama (False-Positive Koruması): Tarih, saat, para, kanun ve esas numaraları korunmalı."""
        negatives = [
            "Tarih: 05.06.2024",
            "Tarih: 15.05.2024",
            "Saat: 15:30:45",
            "Dosya Esas: 2024/532 Esas",
            "2024/536 Esas",
            "5237 sayılı TCK m. 53",
            "532.000 TL",
            "1.532,50 TL",
            "500.000 TL alacak",
            "TCK 53. madde",
        ]
        for neg in negatives:
            redacted, count = UyapRedactor.redact_phone(neg)
            self.assertEqual(redacted, neg, f"False positive for: {neg}")
            self.assertEqual(count, 0)

    def test_kimlik_seri_no(self):
        """2a. Kimlik kartı seri numaralarının maskelenmesi (Yeni çipli ve eski cüzdan)."""
        test_cases = [
            ("Yeni seri: A12B34567", "Yeni seri: [SERİ_NO_GİZLENDİ]"),
            ("A12 B34567", "[SERİ_NO_GİZLENDİ]"),
            ("A12-B34567", "[SERİ_NO_GİZLENDİ]"),
            ("Eski cüzdan: A01123456", "Eski cüzdan: [SERİ_NO_GİZLENDİ]"),
            ("A01 123456", "[SERİ_NO_GİZLENDİ]"),
            ("Seri No: A12B34567", "Seri No: [SERİ_NO_GİZLENDİ]"),
            ("Belge No: A12B34567", "Belge No: [SERİ_NO_GİZLENDİ]"),
            ("Seri: A01 No: 123456", "Seri No: [SERİ_NO_GİZLENDİ]"),
        ]
        for inp, expected in test_cases:
            redacted, count = UyapRedactor.redact_seri_no(inp)
            self.assertEqual(redacted, expected, f"Failed for: {inp}")
            self.assertGreaterEqual(count, 1)

    def test_kimlik_seri_negatives(self):
        """2a-neg. Plaka ve esas numaralarının seri no sayılmaması."""
        negatives = [
            "34 ABC 123",
            "06 A 1234",
            "2024/623",
            "TCK 158/1",
            "2026/731 Esas",
        ]
        for neg in negatives:
            redacted, count = UyapRedactor.redact_seri_no(neg)
            self.assertEqual(redacted, neg, f"False positive for: {neg}")
            self.assertEqual(count, 0)

    def test_mrz_strip(self):
        """2b. 3 satırlı ICAO/MRZ şeritlerinin maskelenmesi."""
        mrz_sample = (
            "I<TUR1234567897<<<<<<<<<<<<<<<\n"
            "8501014M3001018TUR<<<<<<<<<<<4\n"
            "YILMAZ<<AHMET<<<<<<<<<<<<<<<<<"
        )
        redacted, count = UyapRedactor.redact_mrz(mrz_sample)
        self.assertEqual(redacted.strip(), UyapRedactor.MASK_MRZ)
        self.assertEqual(count, 1)

    def test_tckn_10_digits_and_labeled(self):
        """2c. 9-11 haneli açık etiketli TCKN (ve 10 haneli yazım hatası) maskelemesi."""
        test_cases = [
            ("TC Kimlik No: 1234567890", "TC Kimlik No: [TCKN_GİZLENDİ]"),
            ("TC: 1234567890", "TC: [TCKN_GİZLENDİ]"),
            ("TCKN: 1234567890", "TCKN: [TCKN_GİZLENDİ]"),
            ("Kimlik No: 1234567890", "Kimlik No: [TCKN_GİZLENDİ]"),
            ("T.C. No: 12345678901", "T.C. No: [TCKN_GİZLENDİ]"),
            ("TCKN 123456789", "TCKN [TCKN_GİZLENDİ]"),
            ("1234567890 TC", "[TCKN_GİZLENDİ] TC"),
            ("**T.C. Kimlik No:** 1234567890", "**T.C. Kimlik No:** [TCKN_GİZLENDİ]"),
            ("**TCKN:** 1234567890", "**TCKN:** [TCKN_GİZLENDİ]"),
            ("T.C. Kimlik No: 1234567890", "T.C. Kimlik No: [TCKN_GİZLENDİ]"),
        ]
        for inp, expected in test_cases:
            redacted, count = UyapRedactor.redact_tckn(inp)
            self.assertEqual(redacted, expected, f"Failed for: {inp}")
            self.assertGreaterEqual(count, 1)

    def test_preservation_parents_and_partial_tckn_masking(self):
        """Önemli kural: PTT yıldızlı/tireli kısmi TCKN maskelenmeli, Anne/Baba adları KORUNMALI."""
        text = (
            "PTT Tebliğ Mazbatası TC:226*****874, TC:309*****704, TC:382---\"566 ve 123*****890 "
            "Anne Adı: AYŞE Baba Adı: ALİ ve doğum yeri Burdur."
        )
        redacted, stats = UyapRedactor.redact_text(text)
        self.assertNotIn("226*****874", redacted)
        self.assertNotIn("309*****704", redacted)
        self.assertNotIn('382---"566', redacted)
        self.assertNotIn("123*****890", redacted)
        self.assertIn("Anne Adı: AYŞE", redacted, "Anne Adı maskelenmemelidir!")
        self.assertIn("Baba Adı: ALİ", redacted, "Baba Adı maskelenmemelidir!")
        self.assertEqual(stats["tckn"], 4)

    def test_real_case_ocr_leaks_and_strict_immunity(self):
        """
        6 teknik problemdeki tüm OCR kaçak kalıplarının %100 yakalanması ve hukuki analiz
        verilerinin (taraf/hâkim/kâtip/mübaşir adları, plakalar, tarihler, esas/karar no,
        tutarlar) ASLA bozulmaması testi (anonimleştirilmiş sentetik verilerle).
        """
        known = {"12345678950", "10000000146"}
        sample_doc = (
            "Mahkeme: Örnek Aile Mahkemesi Esas No: 2021/542, Tarih: 08.10.2021 ve 22.09.2026\n"
            "Yargıtay 2. HD E. 2022/10035, K. 2024/171, HMK 324, TMK 236, Tutar: 200.000 TL\n"
            "Araç Plakaları: 06 AB 123, 34 XY 78, 35 CD 456, 07 EF 789, 16 GH 281\n"
            "1A) Tanık Ahmet Yılmaz T.C: 123456789012\n"
            "1B) OCR Bozuk TCKN'ler: 10500000146, 123456|8950, 1234567 J9l0, 12345678 950 sc, 11234567895, IT.@Nº 123456789/82\n"
            "1C) Kısmi TCKN'ler: TC:123*****890, TC:309*****100, TC:382---\"500\n"
            "2A) Yapışık OCR IBAN: 931 00729 DAN TR330006 100511123456789012A\n"
            "2B) ATM PARA ÇEKME KART NO:4532015112830366\n"
            "3A) AYŞE ÖRNEK. Cumhuriyet Mah. Toki Evleri D/10-A K:2 D:40 Merkez/ ANKARA\n"
            "3A-2) AYŞE ÖRNEK- Cumhuriyet Mah. Toki Evleri D/10-A K:2 D:4 0 Merkez/ ANKARA\n"
            "3B-1) Yenimahalle Mah, Atatürk 5k. Ne:17 |¢ Kapı No:4 Ankara\n"
            "3B-2) Cumhuriyet Mah. Toki Evleri D/10-A K:2\n"
            "... D:40 Merkez/ ANKARA\n"
            "4A) Hakim Ayşe Kaya 112233, Katıp Mehmet Demir 223344, Mübaşir Ali Çelik 334455\n"
            "4B) Kalip/223344 ve Mübaşir 334455 ve Makin 112233\n"
            "5) 1540 kayıt, A10 seri ve 123456 numaralı fotoğraflı Nüfus Cüzdanına\n"
        )

        redacted, stats = UyapRedactor.redact_text(sample_doc, known_tckns=known)

        # 1. Tüm kaçak kalıplarının %100 maskelendiğini doğrula
        must_be_redacted = [
            "123456789012",
            "10500000146",
            "123456|8950",
            "1234567 J9l0",
            "12345678 950",
            "11234567895",
            "123456789/82",
            "123*****890",
            "309*****100",
            '382---"500',
            "TR330006 100511123456789012A",
            "4532015112830366",
            "Toki Evleri D/10-A K:2 D:40",
            "Toki Evleri D/10-A K:2 D:4 0",
            "Atatürk 5k. Ne:17 |¢ Kapı No:4",
            "D:40 Merkez/ ANKARA",
            "112233",
            "223344",
            "334455",
            "A10 seri ve 123456 numaralı",
        ]
        for leak in must_be_redacted:
            self.assertNotIn(leak, redacted, f"Kaçak veri maskelenemedi: {leak}\nÇıktı:\n{redacted}")

        # 2. Kesin Dokunulmazlık (Hukuki Analizi Bozmama) doğrulaması
        must_be_preserved = [
            "2021/542",
            "08.10.2021",
            "22.09.2026",
            "E. 2022/10035, K. 2024/171",
            "HMK 324",
            "TMK 236",
            "200.000 TL",
            "06 AB 123",
            "34 XY 78",
            "35 CD 456",
            "07 EF 789",
            "16 GH 281",
            "Ahmet Yılmaz",
            "AYŞE ÖRNEK",
            "Hakim Ayşe Kaya",
            "Katıp Mehmet Demir",
            "Mübaşir Ali Çelik",
        ]
        for safe_item in must_be_preserved:
            self.assertIn(safe_item, redacted, f"Korunması gereken veri bozuldu: {safe_item}\nÇıktı:\n{redacted}")

    def test_iban_variations(self):
        """2d-1. Tüm IBAN varyasyonlarının maskelenmesi (boşluklu, bitişik, tireli, noktalı)."""
        iban_cases = [
            ("TR330006100511123456789012", "[IBAN_GİZLENDİ]"),
            ("TR33 0006 1005 1112 3456 7890 12", "[IBAN_GİZLENDİ]"),
            ("IBAN: TR33 0006 1005 1112 3456 7890 12", "IBAN: [IBAN_GİZLENDİ]"),
            ("TR33-0006-1005-1112-3456-7890-12", "[IBAN_GİZLENDİ]"),
            ("TR33.0006.1005.1112.3456.7890.12", "[IBAN_GİZLENDİ]"),
        ]
        for inp, expected in iban_cases:
            redacted, count = UyapRedactor.redact_iban(inp)
            self.assertEqual(redacted, expected, f"IBAN test failed for: {inp}")
            self.assertEqual(count, 1)

    def test_sicil_and_address(self):
        """2d-2. Sicil numaraları ve açık adres maskelemesi ile idempotence kontrolü."""
        sicil_cases = [
            ("Başkan 211094", "Başkan [SİCİL_GİZLENDİ]"),
            ("Cumhuriyet Savcısı-234878", "Cumhuriyet Savcısı-[SİCİL_GİZLENDİ]"),
            ("C. Savcısı 194250", "C. Savcısı [SİCİL_GİZLENDİ]"),
            ("Zabıt Kâtibi: 245678", "Zabıt Kâtibi: [SİCİL_GİZLENDİ]"),
            ("Sicil No: 123456", "Sicil No: [SİCİL_GİZLENDİ]"),
        ]
        for inp, expected in sicil_cases:
            red, count = UyapRedactor.redact_sicil(inp)
            self.assertEqual(red, expected)
            self.assertEqual(count, 1)

        addr_cases = [
            "İkametgah Adresi: Atatürk Mah. İnönü Cad. No: 15 Daire: 4 Burdur",
            "ve halen Bahçelievler Mah. 23034 Sok. No: 10 Merkez/Burdur adresinde ikamet eder",
        ]
        for ac in addr_cases:
            red, count = UyapRedactor.redact_address(ac)
            self.assertIn("[ADRES_GİZLENDİ]", red)
            self.assertEqual(count, 1)
            # Idempotence: Tekrar maskelendiğinde adres sayacı artmamalı
            red2, count2 = UyapRedactor.redact_address(red)
            self.assertEqual(red, red2)
            self.assertEqual(count2, 0)

    def test_index_md_sync(self):
        """3. INDEX.md senkronizasyon motorunun doğrulanması."""
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = os.path.join(tmpdir, "INDEX.md")
            doc_dir = os.path.join(tmpdir, "02-Dilekceler")
            os.makedirs(doc_dir, exist_ok=True)

            # Bir adet taranmış evrakın türev .md dosyasını simüle et
            md_file = os.path.join(doc_dir, "2024-01-01_Dilekce_100.md")
            with open(md_file, "w", encoding="utf-8") as f:
                f.write("Bu bir test dilekçesidir." * 100)  # 2500 karakter

            # INDEX.md tablosunu '—' (tire) ile oluştur
            sample_index_content = (
                "# Dava Belge Dizini\n\n"
                "## Kronoloji\n\n"
                "| Tarih | Tür | Yön | Gönderen | No | Dosya | Metin |\n"
                "|---|---|---|---|---|---|---|\n"
                "| 2024-01-01 | Dilekçe | Gelen | Davacı | 100 | [↗](<_kaynak/02-Dilekceler/2024-01-01_Dilekce_100.pdf>) | — |\n"
            )
            with open(index_path, "w", encoding="utf-8") as f:
                f.write(sample_index_content)

            # Senkronizasyonu çalıştır
            updated = UyapRedactor.sync_index_md(tmpdir)
            self.assertEqual(updated, 1)

            # Güncellenen içeriği oku
            with open(index_path, "r", encoding="utf-8") as f:
                updated_content = f.read()

            self.assertNotIn("—", updated_content)
            self.assertIn("[↗](<02-Dilekceler/2024-01-01_Dilekce_100.md>)", updated_content)
            self.assertIn("2.500 karakter", updated_content)

    def test_export_isolated_clean_folder(self):
        """4. İzole Temiz Klasör Üretiminin (AI Export) uçtan uca testi."""
        with tempfile.TemporaryDirectory() as src_dir:
            # 1. Klasör yapısını kur
            tutanak_dir = os.path.join(src_dir, "01-Tutanak")
            kaynak_dir = os.path.join(src_dir, "_kaynak", "01-Tutanak")
            os.makedirs(tutanak_dir, exist_ok=True)
            os.makedirs(kaynak_dir, exist_ok=True)

            # Markdown dosyası (Kişisel verili)
            md_path = os.path.join(tutanak_dir, "2024-01-15_Duruşma_Tutanağı.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(
                    "# Duruşma Tutanağı\n\n"
                    "Davacı Vekili Av. Örnek, Davacı TCKN: 12345678901, "
                    "İletişim Tel: 05321112233, Seri No: A12B34567, "
                    "IBAN: TR330006100511123456789012, "
                    "Sicil No: 123456, Adres: Atatürk Mah. Gül Sok. No:5 Burdur\n"
                )

            # Orijinal UDF ve diğer ikili dosyaları simüle et (.udf, .pdf, .tif, .tiff, .eyp, .zip, .bak)
            for b_name in [
                "2024-01-15_Duruşma_Tutanağı.udf",
                "ek_evrak.pdf",
                "tarama.tif",
                "resim.tiff",
                "paket.eyp",
                "arsiv.zip",
                "yedek.bak",
            ]:
                b_path = os.path.join(kaynak_dir, b_name)
                with open(b_path, "wb") as f:
                    f.write(b"BINARY_DATA_DO_NOT_LEAK")

            # Manifest ve INDEX.md
            with open(os.path.join(src_dir, "uyap-project.json"), "w", encoding="utf-8") as f:
                f.write('{"case": "2024/100 Esas"}')

            with open(os.path.join(src_dir, "INDEX.md"), "w", encoding="utf-8") as f:
                f.write(
                    "| Tarih | Tür | Yön | Gönderen | No | Dosya | Metin |\n"
                    "|---|---|---|---|---|---|---|\n"
                    "| 2024-01-15 | Tutanak | — | Mahkeme | 1 | [↗](<_kaynak/01-Tutanak/2024-01-15_Duruşma_Tutanağı.udf>) | — |\n"
                )

            # İzole temiz klasör üretimi fonksiyonunu çalıştır
            dest_dir, stats = UyapRedactor.export_isolated_clean_folder(src_dir)

            # Doğrulamalar:
            self.assertTrue(os.path.isdir(dest_dir))
            self.assertTrue(dest_dir.endswith("(Maskelenmis AI)"))

            # 1. Maskelenmiş md içeriği kontrolü
            dest_md = os.path.join(dest_dir, "01-Tutanak", "2024-01-15_Duruşma_Tutanağı.md")
            self.assertTrue(os.path.isfile(dest_md))
            with open(dest_md, "r", encoding="utf-8") as f:
                dest_md_content = f.read()

            # Not: export artık tutarlı numaralı etiketler üretir ([TCKN_1] ...); eski sabit
            # etiketler yalnızca registry'siz redact_* çağrılarında kullanılır.
            self.assertNotIn("12345678901", dest_md_content)
            self.assertIn("[TCKN_1]", dest_md_content)
            self.assertNotIn("05321112233", dest_md_content)
            self.assertIn("[TEL_1]", dest_md_content)
            self.assertNotIn("A12B34567", dest_md_content)
            self.assertIn("[SERİ_NO_1]", dest_md_content)
            self.assertNotIn("TR330006100511123456789012", dest_md_content)
            self.assertIn("[IBAN_1]", dest_md_content)

            # 2. Sıfır İkili Dosya Garantisi: Hedef klasörde tek bir UDF/PDF/TIF/TIFF/EYP/ZIP/BAK veya _kaynak olmamalı
            self.assertFalse(os.path.exists(os.path.join(dest_dir, "_kaynak")), "_kaynak dizini temiz klasörde bulunmamalı!")
            for root, dirs, files in os.walk(dest_dir):
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    self.assertNotIn(
                        ext,
                        [".udf", ".pdf", ".tif", ".tiff", ".eyp", ".zip", ".bak"],
                        f"İkili dosya sızıntısı tespit edildi: {os.path.join(root, f)}"
                    )

            # 3. İndeks senkronizasyonu kontrolü
            dest_index = os.path.join(dest_dir, "INDEX.md")
            self.assertTrue(os.path.isfile(dest_index))
            with open(dest_index, "r", encoding="utf-8") as f:
                dest_index_content = f.read()
            self.assertNotIn("| — |\n", dest_index_content)
            self.assertIn("01-Tutanak/2024-01-15_Duruşma_Tutanağı.md", dest_index_content)

            # 4. Güvenlik raporu oluşturulmalı
            report_path = os.path.join(dest_dir, "DAVA_DÖNÜŞÜM_VE_GÜVENLİK_RAPORU.md")
            self.assertTrue(os.path.isfile(report_path))

            # 5. Manifest kopyalanmalı
            self.assertTrue(os.path.isfile(os.path.join(dest_dir, "uyap-project.json")))

    def test_iban_does_not_swallow_next_line_title(self):
        """5a. IBAN maskelemesinin alt satırdaki unvanın ilk harfini yutmamasını doğrulama."""
        text = (
            "IBAN: TR33 0006 1005 1112 3456 7890 12\n"
            "Hakim Ayşe Kaya 112233"
        )
        red, stats = UyapRedactor.redact_text(text)
        self.assertIn("Hakim Ayşe Kaya [SİCİL_GİZLENDİ]", red)
        self.assertEqual(stats["iban"], 1)
        self.assertEqual(stats["sicil"], 1)

    def test_address_preserves_surnames_and_parent_names(self):
        """5b. Adres maskelemesinde taraf soyadlarının ve Anne/Baba adlarının korunması."""
        # 1. Taraf soyadının korunması
        addr_case = "Sanık Ali Veli, Cumhuriyet Mah. No: 5 Kadıköy/İstanbul"
        red, _ = UyapRedactor.redact_address(addr_case)
        self.assertIn("Sanık Ali Veli", red, "Taraf soyadı silinmemelidir!")

        # 2. Tek satırlı sorgularda Anne/Baba Adı ve Doğum Yeri gibi alanların korunması
        parents_case = "Adres: Atatürk Mah. No: 12 Burdur, Anne Adı: Emine, Baba Adı: Hüseyin, Doğum Yeri: BURDUR"
        red_p, _ = UyapRedactor.redact_address(parents_case)
        self.assertIn("Anne Adı: Emine", red_p)
        self.assertIn("Baba Adı: Hüseyin", red_p)
        self.assertIn("Doğum Yeri: BURDUR", red_p)
        self.assertIn("[ADRES_GİZLENDİ]", red_p)

    def test_spaced_tckn_variations(self):
        """5c. Boşluklu etiketli TCKN varyasyonlarının başarıyla maskelenmesi."""
        spaced_cases = [
            "TCKN: 123 456 789 50",
            "T.C. Kimlik No: 12345 678950",
            "TC Kimlik No: 123 45678950",
        ]
        for c in spaced_cases:
            red, count = UyapRedactor.redact_tckn(c)
            self.assertEqual(count, 1, f"Failed to redact spaced TCKN: {c}")
            self.assertIn("[TCKN_GİZLENDİ]", red)

    def test_source_folder_immutability(self):
        """5d. Sıfır Veri Değişikliği Prensibi: export_isolated_clean_folder kaynak klasörü asla değiştirmemelidir."""
        with tempfile.TemporaryDirectory() as src_dir:
            tutanak_dir = os.path.join(src_dir, "01-Tutanak")
            os.makedirs(tutanak_dir, exist_ok=True)
            md_path = os.path.join(tutanak_dir, "duruşma.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write("TCKN: 12345678901")
            index_path = os.path.join(src_dir, "INDEX.md")
            initial_index = "| Tarih | Tür | Yön | Gönderen | No | Dosya | Metin |\n|---|---|---|---|---|---|---|\n| 2024-01-15 | T | — | M | 1 | [↗](<01-Tutanak/duruşma.md>) | — |\n"
            with open(index_path, "w", encoding="utf-8") as f:
                f.write(initial_index)

            initial_files = {}
            for root, _, files in os.walk(src_dir):
                for f in files:
                    fp = os.path.join(root, f)
                    with open(fp, "rb") as rf:
                        initial_files[fp] = rf.read()

            dest_dir, stats = UyapRedactor.export_isolated_clean_folder(src_dir)

            # Kaynak klasördeki hiçbir dosya silinmemiş, değiştirilmemiş ve yeni dosya eklenmemiş olmalı
            current_files = {}
            for root, _, files in os.walk(src_dir):
                for f in files:
                    fp = os.path.join(root, f)
                    with open(fp, "rb") as rf:
                        current_files[fp] = rf.read()

            self.assertEqual(initial_files, current_files, "Kaynak klasördeki dosyalar mutasyona uğradı!")


class TestRegressionFixes(unittest.TestCase):
    """Analizde deneyle doğrulanan sızıntı / veri kaybı / yanlış pozitif hatalarının regresyon testleri."""

    VALID_TCKN = "10000000146"
    PHONE = "05321112233"

    def _make_case(self, parent: str, name: str = "Dava 2024-100") -> str:
        src = os.path.join(parent, name)
        os.makedirs(src, exist_ok=True)
        return src

    # --- A) export_isolated_clean_folder ---

    def test_agents_md_is_not_overwritten_with_unmasked_original(self):
        """1. AGENTS.md maskelendikten sonra maskesiz orijinalle üzerine yazılmamalı."""
        with tempfile.TemporaryDirectory() as tmp:
            src = self._make_case(tmp)
            with open(os.path.join(src, "AGENTS.md"), "w", encoding="utf-8") as f:
                f.write(f"# Ajan Notları\n\nMüvekkil TCKN: {self.VALID_TCKN}, Tel: {self.PHONE}\n")
            dest, _ = UyapRedactor.export_isolated_clean_folder(src)
            with open(os.path.join(dest, "AGENTS.md"), "r", encoding="utf-8") as f:
                content = f.read()
            self.assertNotIn(self.VALID_TCKN, content)
            self.assertNotIn(self.PHONE, content)
            self.assertIn("[TCKN_1]", content)  # export numaralı etiket üretir

    def test_manifest_json_files_are_redacted_and_stay_valid(self):
        """2. uyap-project.json ve uyap-evrak-listesi.json değer bazında maskelenmeli, geçerli JSON kalmalı."""
        import json
        with tempfile.TemporaryDirectory() as tmp:
            src = self._make_case(tmp)
            project = {
                "case": "2024/100 Esas",
                "taraflar": [
                    {"ad": "Örnek Kişi", "tckn": self.VALID_TCKN, "telefon": self.PHONE},
                    {"ad": "Diğer Kişi", "tckn_int": int(self.VALID_TCKN)},
                ],
                "adres": "Atatürk Mah. Gül Sok. No:5 Burdur",
                "sayfa": 12,
            }
            evrak = [{"no": 1, "aciklama": f"Dilekçe ({self.VALID_TCKN})", "tarih": "2024-01-15"}]
            with open(os.path.join(src, "uyap-project.json"), "w", encoding="utf-8") as f:
                json.dump(project, f, ensure_ascii=False)
            with open(os.path.join(src, "uyap-evrak-listesi.json"), "w", encoding="utf-8") as f:
                json.dump(evrak, f, ensure_ascii=False)

            dest, stats = UyapRedactor.export_isolated_clean_folder(src)

            for name in ("uyap-project.json", "uyap-evrak-listesi.json"):
                with open(os.path.join(dest, name), "r", encoding="utf-8") as f:
                    raw = f.read()
                self.assertNotIn(self.VALID_TCKN, raw, f"{name} içinde TCKN sızdı")
                self.assertNotIn(self.PHONE, raw, f"{name} içinde telefon sızdı")
                json.loads(raw)  # Hâlâ geçerli JSON olmalı

            with open(os.path.join(dest, "uyap-project.json"), "r", encoding="utf-8") as f:
                red_project = json.load(f)
            # Anahtarlar ve hassas olmayan değerler korunur
            self.assertEqual(red_project["case"], "2024/100 Esas")
            self.assertEqual(red_project["sayfa"], 12)
            self.assertEqual(red_project["taraflar"][0]["ad"], "Örnek Kişi")
            # Aynı TCKN hem metin hem tamsayı alanında aynı numaralı etiketi almalı
            self.assertRegex(red_project["taraflar"][0]["tckn"], r'^\[TCKN_\d+\]$')
            self.assertEqual(red_project["taraflar"][1]["tckn_int"], red_project["taraflar"][0]["tckn"])
            self.assertRegex(red_project["adres"], r'\[ADRES_\d+\]')
            self.assertGreaterEqual(stats["tckn"], 3)
            self.assertGreaterEqual(stats["telefon"], 1)

    def test_invalid_manifest_json_is_redacted_fail_closed(self):
        """2. Parse edilemeyen JSON ham kopyalanmamalı; metin maskelenerek yazılmalı."""
        with tempfile.TemporaryDirectory() as tmp:
            src = self._make_case(tmp)
            with open(os.path.join(src, "uyap-project.json"), "w", encoding="utf-8") as f:
                f.write('{"tckn": "' + self.VALID_TCKN + '", bozuk json\n')
            dest, _ = UyapRedactor.export_isolated_clean_folder(src)
            with open(os.path.join(dest, "uyap-project.json"), "r", encoding="utf-8") as f:
                raw = f.read()
            self.assertNotIn(self.VALID_TCKN, raw)

    def test_known_tckns_collected_from_manifest_json(self):
        """2. collect_known_tckns_from_folder manifest JSON'larını da taramalı."""
        with tempfile.TemporaryDirectory() as tmp:
            src = self._make_case(tmp)
            with open(os.path.join(src, "uyap-evrak-listesi.json"), "w", encoding="utf-8") as f:
                f.write('[{"tckn": "' + self.VALID_TCKN + '"}]')
            known = UyapRedactor.collect_known_tckns_from_folder(src)
            self.assertIn(self.VALID_TCKN, known)

    def test_dest_equal_to_src_raises_and_keeps_originals(self):
        """3. Hedef == kaynak ise ValueError fırlatılmalı ve _kaynak/ altındaki orijinaller silinmemeli."""
        with tempfile.TemporaryDirectory() as tmp:
            src = self._make_case(tmp)
            kaynak = os.path.join(src, "_kaynak")
            os.makedirs(kaynak)
            udf = os.path.join(kaynak, "x.udf")
            with open(udf, "wb") as f:
                f.write(b"ORIJINAL_UDF")
            with open(os.path.join(src, "not.md"), "w", encoding="utf-8") as f:
                f.write(f"TCKN: {self.VALID_TCKN}\n")

            with self.assertRaises(ValueError):
                UyapRedactor.export_isolated_clean_folder(src, src)
            # Sondaki ayraçlı yazım da aynı klasör sayılmalı
            with self.assertRaises(ValueError):
                UyapRedactor.export_isolated_clean_folder(src, src + os.sep)

            self.assertTrue(os.path.isfile(udf), "_kaynak/x.udf silindi!")
            with open(os.path.join(src, "not.md"), "r", encoding="utf-8") as f:
                self.assertIn(self.VALID_TCKN, f.read(), "Kaynak .md değiştirildi!")

    def test_rerun_on_masked_folder_itself_is_allowed(self):
        """3. '(Maskelenmis AI)' ile biten klasörün kendi üzerine yeniden çalıştırılması desteklenmeye devam etmeli."""
        with tempfile.TemporaryDirectory() as tmp:
            masked = self._make_case(tmp, "Dava (Maskelenmis AI)")
            with open(os.path.join(masked, "not.md"), "w", encoding="utf-8") as f:
                f.write(f"TCKN: {self.VALID_TCKN}\n")
            dest, _ = UyapRedactor.export_isolated_clean_folder(masked, masked)
            self.assertEqual(os.path.realpath(dest), os.path.realpath(masked))
            with open(os.path.join(masked, "not.md"), "r", encoding="utf-8") as f:
                self.assertNotIn(self.VALID_TCKN, f.read())

    def test_parent_path_containing_git_or_kaynak_does_not_skip_files(self):
        """4. Kaynağın üst yolunda '.git' / '_kaynak' geçmesi dosyaların atlanmasına yol açmamalı."""
        for parent_name in ("my.gitrepo", ".github", "eski_kaynak_arsiv", "node_modules_yedek"):
            with self.subTest(parent=parent_name), tempfile.TemporaryDirectory() as tmp:
                parent = os.path.join(tmp, parent_name)
                src = self._make_case(parent)
                sub = os.path.join(src, "01-Tutanak")
                os.makedirs(sub)
                with open(os.path.join(sub, "tutanak.md"), "w", encoding="utf-8") as f:
                    f.write(f"# Tutanak\n\nTCKN: {self.VALID_TCKN}\n")
                # Gerçek .git ve _kaynak alt dizinleri yine de atlanmalı
                os.makedirs(os.path.join(src, ".git"))
                with open(os.path.join(src, ".git", "HEAD.md"), "w", encoding="utf-8") as f:
                    f.write("git iç dosyası")

                dest, stats = UyapRedactor.export_isolated_clean_folder(src)
                self.assertEqual(stats["md_transferred"], 1)
                self.assertTrue(os.path.isfile(os.path.join(dest, "01-Tutanak", "tutanak.md")))
                self.assertFalse(os.path.exists(os.path.join(dest, ".git")))
                self.assertIn(self.VALID_TCKN, UyapRedactor.collect_known_tckns_from_folder(src))

    def test_is_skipped_dir_uses_exact_component_names(self):
        """4. _is_skipped_dir yalnızca göreli yol bileşenlerinde tam ad eşleşmesine bakmalı."""
        base = os.path.join(os.sep, "Users", "x", "my.gitrepo", "dava")
        skip = UyapRedactor.SKIP_DIRS
        self.assertFalse(UyapRedactor._is_skipped_dir(base, base, skip))
        self.assertFalse(UyapRedactor._is_skipped_dir(os.path.join(base, ".github"), base, skip))
        self.assertFalse(UyapRedactor._is_skipped_dir(os.path.join(base, "eski_kaynak"), base, skip))
        self.assertTrue(UyapRedactor._is_skipped_dir(os.path.join(base, "_kaynak", "01"), base, skip))
        self.assertTrue(UyapRedactor._is_skipped_dir(os.path.join(base, "a", ".git"), base, skip))

    def test_root_summary_files_counted_once(self):
        """5. dosya-bilgileri.md içindeki tek TCKN bir kez sayılmalı (çift sayım yok)."""
        with tempfile.TemporaryDirectory() as tmp:
            src = self._make_case(tmp)
            with open(os.path.join(src, "dosya-bilgileri.md"), "w", encoding="utf-8") as f:
                f.write(f"# Dosya Bilgileri\n\nDavacı TCKN: {self.VALID_TCKN}\n")
            dest, stats = UyapRedactor.export_isolated_clean_folder(src)
            self.assertEqual(stats["tckn"], 1)
            with open(os.path.join(dest, "dosya-bilgileri.md"), "r", encoding="utf-8") as f:
                self.assertNotIn(self.VALID_TCKN, f.read())

    def test_collect_known_tckns_from_masked_folder_with_nfd_name(self):
        """6. NFD yazılmış '(Maskelenmis AI)' yolunda da kaynak klasör taranmalı (NFC tutarlılığı)."""
        import unicodedata
        with tempfile.TemporaryDirectory() as tmp:
            src = self._make_case(tmp, "Dava Şükrü")
            with open(os.path.join(src, "not.md"), "w", encoding="utf-8") as f:
                f.write(f"TCKN: {self.VALID_TCKN}\n")
            masked = os.path.join(tmp, "Dava Şükrü (Maskelenmis AI)")
            os.makedirs(masked)
            known = UyapRedactor.collect_known_tckns_from_folder(unicodedata.normalize("NFD", masked))
            self.assertIn(self.VALID_TCKN, known)

    # --- B) Yanlış pozitifler ---

    def test_partial_tckn_does_not_mask_unlabeled_number_ranges(self):
        """7. Etiketsiz 3 haneli sayı aralıkları kısmi TCKN sanılmamalı."""
        for text in (
            "Kira bedeli 150 - 200 TL arasındadır.",
            "TCK madde 141 - 142 uyarınca",
            "sayfa 120 -- 135",
        ):
            red, stats = UyapRedactor.redact_text(text)
            self.assertEqual(red, text)
            self.assertEqual(stats["tckn"], 0)

        for text in ("TC:226*****874", "TC:309*****704", 'TC:382---"566', "226*****874"):
            red, count = UyapRedactor.redact_tckn(text)
            self.assertEqual(red, UyapRedactor.MASK_TCKN, f"Kısmi TCKN maskelenmedi: {text}")
            self.assertEqual(count, 1)

    def test_num_first_does_not_mask_dates_esas_and_abbreviations(self):
        """8. Tarih / esas no / TCK / TCMB öncesindeki sayılar 'sayı önce etiket sonra' TCKN sanılmamalı."""
        for text in (
            "Karar Tarihi: 12/03/2015 T.C. ANKARA 3. ASLİYE HUKUK MAHKEMESİ",
            "Esas No: 2021/123456 T.C. İSTANBUL",
            "Dosya 2021/1234567 TCK 141",
            "Tutar 1 250 000 00 TCMB kuru",
        ):
            red, stats = UyapRedactor.redact_text(text)
            self.assertEqual(red, text)
            self.assertEqual(stats["tckn"], 0)
            self.assertEqual(UyapRedactor.collect_known_tckns_from_text(text), set())

        for text, expected in (
            ("12345678901 T.C'nolu", "[TCKN_GİZLENDİ] T.C'nolu"),
            ("12345678901 TCKN", "[TCKN_GİZLENDİ] TCKN"),
            ("12345678901 TC nolu", "[TCKN_GİZLENDİ] TC nolu"),
            ("1234567890 T.C. ndu", "[TCKN_GİZLENDİ] T.C. ndu"),
            ("1234567890 te nolu", "[TCKN_GİZLENDİ] te nolu"),
        ):
            red, count = UyapRedactor.redact_tckn(text)
            self.assertEqual(red, expected)
            self.assertEqual(count, 1)
        self.assertIn("12345678901", UyapRedactor.collect_known_tckns_from_text("12345678901 T.C'nolu"))

    def test_sicil_does_not_mask_amounts_and_sayili(self):
        """9. Unvan + sayı kalıbında para tutarı ve 'sayılı' ifadeleri sicil sanılmamalı."""
        for text in ("Hakim 150000 TL ödenmesine", "Başkan 20245 sayılı"):
            red, count = UyapRedactor.redact_sicil(text)
            self.assertEqual(red, text)
            self.assertEqual(count, 0)
        for text, expected in (
            ("Başkan 211094", "Başkan [SİCİL_GİZLENDİ]"),
            ("Mübaşir 234567", "Mübaşir [SİCİL_GİZLENDİ]"),
            ("Kalip/123456", "Kalip/[SİCİL_GİZLENDİ]"),
        ):
            red, count = UyapRedactor.redact_sicil(text)
            self.assertEqual(red, expected)
            self.assertEqual(count, 1)

    # --- D) PDF sayfa sınırı ---

    def test_pdf_truncation_adds_visible_warning(self):
        """11. max_pages aşıldığında çıktıya görünür bir kesilme uyarısı eklenmeli."""
        try:
            import fitz
        except ImportError:
            self.skipTest("PyMuPDF (fitz) kurulu değil")
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = os.path.join(tmp, "uzun.pdf")
            doc = fitz.open()
            for i in range(3):
                page = doc.new_page()
                page.insert_text((72, 72), f"Sayfa {i + 1} icin yeterince uzun bir dijital metin satiri burada yer aliyor.")
            doc.save(pdf_path)
            doc.close()

            red, _ = UyapRedactor.extract_and_redact_pdf(pdf_path, max_pages=2)
            self.assertIn("Bu belge 3 sayfadır; yalnızca ilk 2 sayfa işlenmiştir.", red)

            red_full, _ = UyapRedactor.extract_and_redact_pdf(pdf_path, max_pages=150)
            self.assertNotIn("yalnızca ilk", red_full)


class TestRealCaseFolderFixes(unittest.TestCase):
    """İzmir 6. AHM 2025/69 dosyası karşılaştırmasında bulunan sızıntı ve yanlış maskeler."""

    def red(self, t):
        return UyapRedactor.redact_text(t)[0]

    def test_tebligat_new_address_label_keeps_notice_text(self):
        t = ("Muhatap adresini değiştirmişse tebliğ memuru tarafından tespit edilen yeni adresi: \n\n"
             "## Bilirkişi raporuna HMK 281. maddesi gereğince tebliğ tarihinden itibaren iki hafta \n")
        out = self.red(t)
        self.assertIn("HMK 281. maddesi", out)
        self.assertNotIn("[ADRES_GİZLENDİ]", out)

    def test_url_kep_and_verification_addresses_not_masked(self):
        for t in ("Belge Doğrulama Adresi : https://izmirdogrulama.barobirlik.com/",
                  "İnternet Adresi: http://www.izmirbarosu.org.tr Kep Adresi: izmirbarosu@hs01.kep.tr",
                  "KEP Adresi: adaletbakanligi@hs01.kep.tr ve ileti detay alanına"):
            self.assertEqual(self.red(t), t)

    def test_ocr_garbled_iban_prefix_is_masked(self):
        out = self.red("VELİ\n|TR330000100519786457841326\n-2000\nITR120000100519786457841328\n")
        self.assertNotIn("0000100519786457841326", out)
        self.assertNotIn("0000100519786457841328", out)
        self.assertEqual(out.count("[IBAN_GİZLENDİ]"), 2)

    def test_address_continuation_line_masked_until_phone(self):
        out = self.red("Yakalama Adresi: Papatyalı Mah. 3740 Sk. Menekşe Apt No:9\n"
                       "İç Kapı No: 2 Örnekçay / Antalya Tel: (90)5321234567, İlköğretim,\n")
        self.assertNotIn("Örnekçay", out)
        self.assertIn("İlköğretim", out)

    def test_ocr_table_scattered_street_masked(self):
        out = self.red("Açık Adres\n[ADRES_GİZLENDİ]\niç Kapı No\nDENEME SK.\n28\nSonraki\n")
        self.assertNotIn("TARIM", out)
        self.assertIn("Sonraki", out)

    def test_label_on_own_line_masks_next_address_line(self):
        out = self.red("Adres:\nÖrnekköy Mah. 8009 Sk. No:42 Denemeli/ Antalya\n")
        self.assertNotIn("Bayat", out)

    def test_mernis_template_line_not_swallowed(self):
        t = ("MERNİS ADRESİ \n   ili,  ilçesi,  mah/köy,  Cilt,  Aile sıra no,  sırada nüfusa kayıtlı, "
             "İSMAİL ve DİLEK oğlu/kızı, 01/01/1983 dogumlu,\n")
        self.assertIn("oğlu/kızı", self.red(t))

    def test_low_quality_ocr_flag_and_dropped_links(self):
        import tempfile, shutil
        d = tempfile.mkdtemp()
        try:
            good = "Mahkeme dosya dava davacı davalı vekili talep tebligat müzekkere cevap banka hesap " * 5
            with open(os.path.join(d, "iyi.md"), "w", encoding="utf-8") as f:
                f.write("# iyi\n\n" + good)
            bad = "# kotu.tif\n\n### Taranmış Belge (Yerel OCR)\n\n" + "ECMAL TiDI KARAC COZA INIRL RURUMU MIMARLiTE " * 6
            with open(os.path.join(d, "kotu.md"), "w", encoding="utf-8") as f:
                f.write(bad)
            ok = "# ok.tif\n\n### Taranmış Belge (Yerel OCR)\n\n" + good
            with open(os.path.join(d, "ok.md"), "w", encoding="utf-8") as f:
                f.write(ok)
            flagged = UyapRedactor.flag_low_quality_ocr(d)
            self.assertEqual(flagged, ["kotu.md"])
            with open(os.path.join(d, "kotu.md"), encoding="utf-8") as f:
                self.assertIn("OCR UYARISI", f.read())

            os.makedirs(os.path.join(d, "belge"))
            with open(os.path.join(d, "belge", "gorsel-1.md"), "w", encoding="utf-8") as f:
                f.write("ocr")
            doc = os.path.join(d, "belge.md")
            with open(doc, "w", encoding="utf-8") as f:
                f.write("> **Görseller:** 2 görsel `belge/` klasörüne çıkarıldı.\n"
                        "![gorsel-1.png](belge/gorsel-1.png) ![gorsel-2.png](belge/gorsel-2.png) ![g3](Genel Müzekkere_1/gorsel-3.png) [↗](<_kaynak/x.udf>) "
                        "[ana_evrak.pdf](<ana_evrak.pdf>) [site](https://x.gov.tr/a.pdf)\n")
            UyapRedactor.rewrite_dropped_links(doc)
            with open(doc, encoding="utf-8") as f:
                out = f.read()
            self.assertIn("(<belge/gorsel-1.md>)", out)
            self.assertIn("[görsel aktarılmadı: gorsel-2.png]", out)
            self.assertIn("[görsel aktarılmadı: g3]", out)
            self.assertNotIn("_kaynak/x.udf", out)
            self.assertNotIn("(<ana_evrak.pdf>)", out)
            self.assertIn("https://x.gov.tr/a.pdf", out)
            self.assertNotIn("klasörüne çıkarıldı", out)
        finally:
            shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tutarlı numaralı maske (MaskRegistry), fazla maskeleme ve kaçan veri testleri.
# Tüm değerler UYDURMADIR (geçerli checksum'lı sahte TCKN, sahte IBAN/ad/adres).
# ---------------------------------------------------------------------------
from uyap_redactor import MaskRegistry  # noqa: E402


def fake_tckn(first9: str) -> str:
    """İlk 9 haneden geçerli checksum'lı sahte TCKN üretir."""
    d = [int(c) for c in first9]
    d10 = ((d[0] + d[2] + d[4] + d[6] + d[8]) * 7 - (d[1] + d[3] + d[5] + d[7])) % 10
    d11 = (sum(d) + d10) % 10
    return first9 + str(d10) + str(d11)


T1 = fake_tckn("123456789")
T2 = fake_tckn("234567891")
IBAN1 = "TR120006400000112345678901"
IBAN1_SPACED = "TR12 0006 4000 0011 2345 6789 01"


def red(text, registry=None, known=None):
    return UyapRedactor.redact_text(text, known_tckns=known, registry=registry)[0]


class TestMaskRegistry(unittest.TestCase):

    def test_fake_tckn_is_valid(self):
        self.assertTrue(UyapRedactor.is_valid_tckn(T1))
        self.assertTrue(UyapRedactor.is_valid_tckn(T2))

    def test_same_value_same_label_different_value_different_label(self):
        reg = MaskRegistry()
        a = red(f"Davacı TCKN: {T1}", reg)
        b = red(f"Kimlik No: {T1} ve diğer kişi T.C. Kimlik No: {T2}", reg)
        self.assertIn("[TCKN_1]", a)
        self.assertIn("[TCKN_1]", b)
        self.assertIn("[TCKN_2]", b)
        self.assertNotIn(T1, a + b)

    def test_spaced_and_ocr_iban_get_same_label(self):
        reg = MaskRegistry()
        a = red(f"IBAN: {IBAN1}", reg)
        b = red(f"IBAN: {IBAN1_SPACED}", reg)
        c = red("IBAN: |" + IBAN1.replace("0", "O", 3), reg)
        self.assertIn("[IBAN_1]", a)
        self.assertIn("[IBAN_1]", b)
        self.assertIn("[IBAN_1]", c)

    def test_partial_tckn_maps_to_known_label(self):
        reg = MaskRegistry({T1})
        a = red(f"TCKN: {T1}", reg)
        b = red(f"TC:{T1[:3]}*****{T1[-3:]}", reg)
        self.assertIn("[TCKN_1]", a)
        self.assertEqual(b, "[TCKN_1]")

    def test_registry_none_keeps_legacy_labels(self):
        out = red(f"TCKN: {T1} Tel: 05321112233 IBAN: {IBAN1}")
        self.assertIn("[TCKN_GİZLENDİ]", out)
        self.assertIn("[TELEFON_GİZLENDİ]", out)
        self.assertIn("[IBAN_GİZLENDİ]", out)

    def test_registry_has_no_disk_export(self):
        for name in ("to_file", "dump", "save", "export", "to_json"):
            self.assertFalse(hasattr(MaskRegistry, name), name)

    def test_numbered_labels_not_rematched_by_later_layers(self):
        reg = MaskRegistry()
        text = "[TEL_12] Hakim [TCKN_3] Katip [SİCİL_4] [ADRES_2] No:5 [IBAN_7]"
        self.assertEqual(red(text, reg), text)

    def test_address_split_and_single_line_same_label(self):
        reg = MaskRegistry()
        a = red("**DAVALI :** Ali VELİ - Lale Mah. Gül Sk. No:12 İç Kapı No:3 Merkez/ BURDUR", reg)
        b = red("Adres: Lale Mahallesi Gül Sokak No:12 İç Kapı No:3 Burdur Merkez/BURDUR", reg)
        self.assertIn("[ADRES_1]", a)
        self.assertIn("[ADRES_1]", b)

    def test_address_continuation_line_gets_same_label(self):
        reg = MaskRegistry()
        out = red("Yakalama Adresi: Lale Mah. Gül Sk. No:12\nİç Kapı No: 2 Örnekçay / Antalya Tel: 0242 111 22 33", reg)
        self.assertEqual(out.count("[ADRES_1]"), 2)
        self.assertNotIn("[ADRES_2]", out)

    def test_export_consistent_labels_and_no_mapping_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "Dava 2024-1")
            os.makedirs(os.path.join(src, "a"))
            with open(os.path.join(src, "a", "1.md"), "w", encoding="utf-8") as f:
                f.write(f"# Bir\n\nDavacı TCKN: {T1}\nIBAN: {IBAN1}\n")
            with open(os.path.join(src, "a", "2.md"), "w", encoding="utf-8") as f:
                f.write(f"# İki\n\nDavalı TCKN: {T2}\nTekrar: {T1}\nIBAN: {IBAN1_SPACED}\n")
            dest, stats = UyapRedactor.export_isolated_clean_folder(src, os.path.join(tmp, "out"))
            t1 = open(os.path.join(dest, "a", "1.md"), encoding="utf-8").read()
            t2 = open(os.path.join(dest, "a", "2.md"), encoding="utf-8").read()
            self.assertIn("[TCKN_1]", t1)
            self.assertIn("[TCKN_1]", t2)
            self.assertIn("[TCKN_2]", t2)
            self.assertIn("[IBAN_1]", t2)
            # Hiçbir çıktı dosyasında ham değer / eşleme tablosu yok
            for root, _d, files in os.walk(dest):
                for fn in files:
                    content = open(os.path.join(root, fn), encoding="utf-8", errors="replace").read()
                    compact = content.replace(" ", "")
                    for raw in (T1, T2, IBAN1):
                        self.assertNotIn(raw, compact, fn)
            report = open(os.path.join(dest, UyapRedactor.REPORT_NAME), encoding="utf-8").read()
            self.assertIn("Aynı numara = aynı değer", report)
            for word in ("%100", "kusursuz", "Kusursuz", "garanti", "sıfır sızıntı"):
                self.assertNotIn(word, report)
            self.assertEqual(stats["mask_distinct"]["tckn"], 2)


class TestOverMaskingFixes(unittest.TestCase):

    def test_institution_addresses_not_masked(self):
        for line in (
            "Adres : Örnek Bankası A.Ş. Operasyon Merkezi / Adres: Çam Mah. Tersane Cad.No:15 Pendik/ İstanbul",
            "Mersis Numarası:0123456789000017 Finans Mahallesi Finans Caddesi No:40/1 34760 Ümraniye/İSTANBUL",
            "Adres\t: İzmir Adalet Sarayı 35170 Konak/İZMİR",
        ):
            self.assertEqual(red(line, MaskRegistry()), line)

    def test_person_address_still_masked(self):
        out = red("Av. Ayşe ÖRNEK ADRES: Lale Mah. Gül Cad. NO.97 D.5 Buca/İZMİR", MaskRegistry())
        self.assertIn("[ADRES_1]", out)

    def test_mahkeme_abbreviation_and_esas_not_address(self):
        line = "İzmir 6. Asliye Hukuk Mah. 2025/69 E. sayılı dosyanın duruşmalarına katılmak üzere yetki verilmiştir."
        self.assertEqual(red(line), line)

    def test_nufus_template_not_address(self):
        line = (f"vasi olarak atanan Antalya ili, Örnek ilçesi, Örnekköy Mahallesi. Nk.lu. C: 10 , H:83, BSN: 1'da "
                f"nüfusa kayıtlı, 20/07/1956 doğumlu,TC: {T1} kimlik nolu ALİ ÖRNEK'in")
        out = red(line)
        self.assertIn("Örnekköy Mahallesi. Nk.lu. C: 10", out)
        self.assertIn("20/07/1956", out)
        self.assertNotIn(T1, out)
        line2 = "İli: BURDUR İlçesi: MERKEZ Mah./Köy:DEĞİRMENLER"
        self.assertEqual(red(line2), line2)

    def test_olay_yeri_not_masked(self):
        line = "27.07.2020 günü Burdur İli, Merkez, Kardelen Mahallesi, Zambak Caddesi, No:58 önünde trafik kazası meydana gelmiştir."
        self.assertEqual(red(line), line)

    def test_labeled_tckn_does_not_eat_following_word(self):
        out = red(f"T.C. KİMLİK NO:{T1} OLAN, ALİ ÖRNEK ADLI BABASI")
        self.assertIn("[TCKN_GİZLENDİ] OLAN, ALİ", out)

    def test_document_numbers_not_phone(self):
        for line in ("Evrak No: 5321234567", "Barkod 5551234567", "Ref No : 5591234567"):
            self.assertEqual(red(line), line)
        self.assertIn("[TELEFON_GİZLENDİ]", red("Telefon Numarası :5877893287"))

    def test_fixed_line_not_masked(self):
        line = "Tel: 0 217 421 80 96 Faks: (0212) 542 07 61"
        self.assertEqual(red(line), line)

    def test_mersis_and_bank_ref_kept(self):
        for line in ("MERSİS No: 0929 0810 0339 0757", "BANKA REF. NO : 8383470174681453"):
            self.assertEqual(red(line), line)


class TestLeakFixes(unittest.TestCase):

    def test_multiline_iban_masked(self):
        text = "### 34019161 4610 TR4100 \n\n### 010000 \n\n### 413246 \n\n### 204750 \n\n### 01 \n\n### VADESİZ"
        out = red(text, MaskRegistry())
        self.assertIn("[IBAN_1]", out)
        self.assertIn("[HESAP_1] 4610", out)
        self.assertNotIn("413246", out)
        self.assertIn("VADESİZ", out)

    def test_ocr_ta_and_s_iban_masked(self):
        reg = MaskRegistry()
        a = red("|TA120006400000112345678901", reg)
        b = red("TR12000640000011234S678901", reg)
        self.assertIn("[IBAN_1]", a)
        self.assertIn("[IBAN_1]", b)

    def test_account_numbers(self):
        cases = [
            ("Şubemiz nezdinde 4513494 numaralı hesabının olduğu", "4513494"),
            ("Hesap No: 12345678 olarak", "12345678"),
            ("hesap numarası 1234-5678901 olan", "1234-5678901"),
            ("## Müşteri No : 3693612", "3693612"),
            ("01014015 TL Vadesiz 0.00", "01014015"),
        ]
        for text, raw in cases:
            out = red(text)
            self.assertNotIn(raw, out, text)
            self.assertIn("[HESAP_NO_GİZLENDİ]", out, text)
        self.assertIn("0.00", red("01014015 TL Vadesiz 0.00"))

    def test_account_table_columns(self):
        table = (
            "| MUSTERINO | MUSTERIADI | HESAPNO | SUBEKODU | BAKIYE | ACILIS |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| 10500001 | ALİ ÖRNEK | 20600002 | 00072 | 1.250,50 | 20031031 |\n"
        )
        out = red(table, MaskRegistry())
        self.assertNotIn("10500001", out)
        self.assertNotIn("20600002", out)
        for kept in ("00072", "1.250,50", "20031031", "ALİ ÖRNEK"):
            self.assertIn(kept, out)

    def test_dashed_account_reuses_known_label(self):
        reg = MaskRegistry()
        out = red("ALİ ÖRNEK 30400005 numaralı hesabı mevcut\n2000-30400005-351 VDSZMVD", reg)
        self.assertEqual(out.count("[HESAP_1]"), 2)

    def test_card_numbers(self):
        out = red("Kart: 4111 1111 1111 1111 ve 5406 67** **** 1234")
        self.assertNotIn("4111 1111", out)
        self.assertNotIn("67**", out)
        self.assertEqual(out.count("[KART_NO_GİZLENDİ]"), 2)

    def test_sicil_variants(self):
        cases = [
            "SEVAL ÖRNEK (Sicil=234408)",
            "Sicili 476175",
            "Baro Sicil No : Burdur Barosu , 490",
            "Av. Ayşe ÖRNEK (16475) ADRES:",
        ]
        for c in cases:
            out = red(c)
            self.assertIn("[SİCİL_GİZLENDİ]", out, c)
        self.assertNotIn("476175", red("Sicili 476175"))
        # Ticaret sicil numaraları tüzel kişiye ait olup açık bırakılır
        for trade_line in (
            "Ticaret Sicil No: 862070",
            "Tic. Sicil No: 233076",
        ):
            self.assertEqual(red(trade_line), trade_line)

    def test_ocr_form_sicil_lines(self):
        out = red("DOLDURAN ADLİ KOLLUK\n231336-ALİ ÖRNEK\nGÖREVLİSİNİN ADI-SOYADI SİCİLİ,")
        self.assertNotIn("231336", out)
        self.assertIn("ALİ ÖRNEK", out)
        out2 = red("Doktor\nVELİ ÖRNEK\n196931\n")
        self.assertNotIn("196931", out2)
        out3 = red("(X.5) ONAYLAYAN SICIL-İMZA\nM-\n280908\n")
        self.assertNotIn("280908", out3)

    def test_known_sicil_reused_on_ocr_line(self):
        reg = MaskRegistry()
        a = red("**HAKİM\t:** Ayşe ÖRNEK  285669", reg)
        b = red(": Ayşe ÖRNEK 285669", reg)
        self.assertIn("[SİCİL_1]", a)
        self.assertIn("[SİCİL_1]", b)


class TestOcrCacheAndIndex(unittest.TestCase):

    def test_ocr_cache_inside_dest_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "Dava")
            os.makedirs(src)
            dest = os.path.join(tmp, "out")
            old = os.environ.get("UYAP_OCR_CACHE_DIR")
            os.environ["UYAP_OCR_CACHE_DIR"] = os.path.join(dest, "cache")
            try:
                with self.assertRaises(ValueError):
                    UyapRedactor.export_isolated_clean_folder(src, dest)
            finally:
                if old is None:
                    os.environ.pop("UYAP_OCR_CACHE_DIR", None)
                else:
                    os.environ["UYAP_OCR_CACHE_DIR"] = old

    def test_ocr_cache_read_instead_of_ocr(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, "c.md")
            with open(cache, "w", encoding="utf-8") as f:
                f.write(f"# x.pdf\n\n### Sayfa 1 (Yerel OCR)\n\nTCKN: {T1}\n")
            out, st = UyapRedactor.extract_and_redact_scanned_file(
                os.path.join(tmp, "yok.pdf"), raw_cache_path=cache)
            self.assertNotIn(T1, out)
            self.assertEqual(st["tckn"], 1)

    def test_archive_index_counts_synced(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "ana_evrak.md"), "w", encoding="utf-8") as f:
                f.write("x" * 1234)
            idx = os.path.join(tmp, "INDEX.md")
            with open(idx, "w", encoding="utf-8") as f:
                f.write("| Dosya | Metin |\n|---|---|\n| a | [↗](<ana_evrak.md>) (9 karakter) |\n")
            UyapRedactor.sync_index_md(tmp)
            self.assertIn("(1.234 karakter)", open(idx, encoding="utf-8").read())


# ---------------------------------------------------------------------------
# Toplu gerçek-klasör denetiminden çıkan kalıplar (tüm değerler UYDURMADIR)
# ---------------------------------------------------------------------------
class TestBatchAuditFixes(unittest.TestCase):

    def test_iban_with_extra_ocr_digit_masked(self):
        reg = MaskRegistry()
        out = red("EFT HESAP-TR1200064000001123456789012 ALAC AD: Ali Veli", reg)
        self.assertNotIn("1200064000001123456789012", out)
        self.assertIn("[IBAN_1]", out)
        out2 = red("Hesap/K.Kart No\nTR1200064000001123456789012\nAlici : Ali", reg)
        self.assertIn("[IBAN_1]", out2)
        # 27 haneli uzun sayı IBAN sayılmaz (tamamen bitişik)
        self.assertIn("120006400000112345678901234", red("TR120006400000112345678901234"))

    def test_tckn_ocr_ic_label_adjacent(self):
        for text in (f"Ali VELI (I.C.{T1}) isimli", f"Ali (Q.C.{T1}) x", f"X (G.c.{T1[0]} {T1[1:5]} {T1[5:]}) y",
                     f"B (T.C.{T1[:8]}^ {T1[8:]}) ve", f"Y (1.C.{T1})"):
            out = red(text, MaskRegistry())
            self.assertNotIn(T1, out, text)
            self.assertNotIn(T1[:8], out, text)
            self.assertIn("[TCKN_1]", out, text)

    def test_standalone_tckn_next_to_period_or_slash(self):
        cases = [
            f"## NUMARASI:{T1}.\n\n## ILGILI",
            f"okuryazar bildiren {T1}.T.C. kimlik SEDA ÖRNEK",
            f"Konu : {T1}/Deniz ÖRNEK",
            f"Ad/TCKN: Deniz ÖRNEK/{T1}",
        ]
        for text in cases:
            out = red(text, MaskRegistry())
            self.assertNotIn(T1, out, text)
        # Ondalık/tarih benzeri: önünde rakam+nokta varsa korunur
        self.assertIn(T1, red(f"tutar 3.{T1} TL benzeri"))

    def test_labeled_tckn_dots_and_single_spaced_digits(self):
        spaced = " ".join(T1)
        dotted = f"{T1[0]}.{T1[1:4]}.{T1[4:6]}.{T1[6:9]}.{T1[9]}.{T1[10]}."
        for text in (f"## TC KİMLİK NO......: {spaced}\n## ADI", f"kimlik bilgilerinden (TC: {dotted})"):
            out = red(text, MaskRegistry())
            self.assertIn("[TCKN_1]", out, text)
            self.assertNotIn(T1[:5], out.replace(" ", "").replace(".", ""), text)

    def test_labeled_tckn_ocr_garbled_label(self):
        cases = [
            f"oturur. TC (^) Kiırılik No.{T1[:2]} {T1[2:]} : Av. X",
            f"oturur, TC Kinılik No.{T1} : Av. X",
            f"oturur. TC Krmlik No;{T1} : Av. X",
            f"oturur, TC Kırnlik (^) No:{T1} ı Av. X",
        ]
        for text in cases:
            out = red(text, MaskRegistry())
            self.assertIn("[TCKN_1]", out, text)
            self.assertNotIn(T1[2:], out, text)

    def test_ocr_ir_prefix_iban_and_caret_between_t_and_c(self):
        out = red("size İR12 0006 4000 0011 2345 6789 01 Ben", MaskRegistry())
        self.assertIn("[IBAN_1]", out)
        out = red(f"Emre Ç ELİK T. (^) C. {' '.join(T1[:3])} {T1[3:7]} {T1[7:10]} {T1[10]}) Tutanağın", MaskRegistry())
        self.assertIn("[TCKN_1]", out)
        self.assertNotIn(T1[3:7], out)

    def test_fuzzy_known_tckn_does_not_mask_esas_number(self):
        text = f"Kocaeli Cumhuriyet Başsavcılığı 2023/1{T1[-4:]} Sor. Silifke 2022/345 Sor."
        out = red(text, MaskRegistry(), known={T1})
        self.assertIn(f"2023/1{T1[-4:]}", out)
        self.assertNotIn("[TCKN_", out)

    def test_phone_after_newline_with_telefon_after(self):
        text = "Sistem ve kayıtlarımızdan tespit edilen\n5321234567 numaralı telefondan şahsın babası ile"
        out = red(text)
        self.assertNotIn("5321234567", out)

    def test_address_does_not_swallow_date_year(self):
        cases = [
            "## 12.03.2025YENİ MAH. DENEME SK. NO:5 İÇ KAPI NO:3 ÖRNEKÇAY / İSTANBUL",
            ": Adapazari → 12.03.2025\nGöktepe mah. no.5 Adapcre/Solanga\n: 12",
            "Tarih 12.03.2025 Test Mah. Deneme Sk. No:5 Merkez/Burdur",
        ]
        for text in cases:
            out = red(text, MaskRegistry())
            self.assertIn("12.03.2025", out, text)

    def test_legal_boilerplate_after_tebligat_adresi_is_kept(self):
        text = ("Muhatap Adı, Soyadı ve Elektronik Tebligat Adresi: HMK'nın 100, 101, 102. "
                "maddeleri hükümleri saklı kalmak şartıyla,")
        out = red(text, MaskRegistry())
        self.assertIn("HMK'nın 100, 101, 102.", out)
        self.assertNotIn("[ADRES_", out)

    def test_hospital_row_keeps_dates_and_masks_address(self):
        text = ("Hasta Ad Protokol No Taburcu Tarihi Adres : ALİ VELİ : 12345678 : 12.03.2025 10:30 : "
                "1234 SK. TESTTEPE MAH.5/6 Telefon")
        out = red(text, MaskRegistry())
        self.assertIn("12.03.2025", out)
        self.assertNotIn("TESTTEPE", out)
        self.assertIn("[ADRES_", out)

    def test_hospital_label_on_previous_line_keeps_dates(self):
        text = ("Hasta Ad\nProtokol No\nTaburcu Tarihi\nAdres\n"
                ": ALİ VELİ : 12345678 : 12.03.2025 10:30 : 1234 SK. TESTTEPE MAH.5/6\nTelefon")
        out = red(text, MaskRegistry())
        self.assertIn("12.03.2025 10:30", out)
        self.assertIn("12345678", out)
        self.assertNotIn("TESTTEPE", out)
        self.assertIn("[ADRES_", out)

    def test_address_split_across_heading_lines_masked(self):
        cases = [
            "## Testtepe Mahallesi Şehit Kuzey Sokak Lale\n\n## Sitesi Köşkleri No.12 Ac Merkez/ BURDUR\n",
            "Testtepe Mahallesi Şehit Kuzey Sokak Lale\nSitesi Köşkleri No: 12 Ac Merkez/ Burdur\n12.03.2025\n",
            'sundugu 12/03/2025 tarihli dilekçesi ile "Şehit Kuzey Sok. Testtepe Mah. Gül\n'
            'Sitesi Köşkleri No:12 AC Örnekçay /İSTANBUL adresinde ikamet edecegini beyan etmiş olup.\n',
        ]
        for text in cases:
            out = red(text, MaskRegistry())
            self.assertNotIn("Testtepe", out, text)
            self.assertNotIn("Köşkleri", out, text)
            self.assertIn("[ADRES_1]", out, text)

    def test_split_address_second_line_ocr_no_variant(self):
        text = ('dilekçesinde: adresini "Şehit Kuzey Sok. Testtepe Mah. Lale Sitesi Köşkleri\n'
                'Vo:f9 AC Silivri /ISTANBUL" olarak değiştirdiğini belirterek')
        out = red(text, MaskRegistry())
        self.assertNotIn("Testtepe", out)
        self.assertNotIn("Vo:f9", out)
        self.assertIn("(Silivri/İstanbul)", out)
        self.assertIn("olarak değiştirdiğini belirterek", out)
        out_legacy = red(text)
        self.assertNotIn("Testtepe", out_legacy)
        self.assertNotIn("Silivri", out_legacy)

    def test_split_address_keeps_surrounding_sentence(self):
        text = ('sundugu 12/03/2025 tarihli dilekçesi ile "Şehit Kuzey Sok. Testtepe Mah. Gül\n'
                'Sitesi Köşkleri No:12 AC Örnekçay /İSTANBUL adresinde ikamet edecegini beyan etmiş olup.\n')
        out = red(text, MaskRegistry())
        self.assertIn("sundugu 12/03/2025 tarihli dilekçesi ile", out)
        self.assertIn("adresinde ikamet edecegini beyan etmiş olup.", out)

    def test_mernis_table_address_masked(self):
        text = ("**MERNİS (Yurtiçi) Adres Bilgisi** Mahalle :TESTTEPE MAH. Cd./Sk./Bul./Mev :DENEME CAD. "
                "Kapı No :12/3 İlçe :MERKEZ İl :ANTALYA Beyan Tarihi:01/02/2020,Tescil Tarihi:01/02/2020")
        out = red(text, MaskRegistry())
        self.assertNotIn("TESTTEPE", out)
        self.assertNotIn("DENEME", out)
        self.assertIn("[ADRES_1]", out)
        self.assertIn("Beyan Tarihi:01/02/2020", out)

    def test_person_address_next_to_institution_words_is_masked(self):
        cases = [
            ('Yükümlünün Silivri Denetimli Serbestlik Müdürlüğü aracılığıyla sunduğu 12.03.2025 tarihli '
             'dilekçesinde; adresini "Şehit Kuzey Sok. Testtepe Mah. Gül\nSitesi No:12 AC Örnekçay /İSTANBUL '
             'adresinde ikamet edeceğini beyan etmiş olup.\n', "Testtepe"),
            ("İlgi sayılı yazı gereği evrakta belirtilen ** Testtepe Mah. Şehit Kuzey Sk. No:9A  Silivri/ İSTANBUL "
             "**adresleri jandarma komutanlığımız sorumluluk alanında bulunmadığı", "Testtepe"),
        ]
        for text, raw in cases:
            out = red(text, MaskRegistry())
            self.assertNotIn(raw, out, text)

    def test_orphan_ic_kapi_continuation_masked(self):
        text = "ALİ VELİ, MEHMET Oğlu\nNo:9 Iç Kapı No:3 Bucak/BURDUR\nSuç tarihi"
        out = red(text, MaskRegistry())
        self.assertNotIn("Bucak/BURDUR", out)
        self.assertIn("[ADRES_", out)

    def test_mah_sk_with_slash_door_number_masked(self):
        for text in ("TESTTEPE MAH. 1234 SK. 5 / 6 BUCAK - BURDUR", ": 1234 SK. TESTTEPE MAH. 5/6 Telefon"):
            out = red(text, MaskRegistry())
            self.assertNotIn("TESTTEPE", out, text)
            self.assertIn("[ADRES_", out, text)

    def test_workplace_address_in_tutanak_with_court_two_lines_above(self):
        text = ("TUTANAK\nBurdur 2. Ağır Ceza Mahkemesinin 2025/211 sayılı yazılarına istinaden tebligata\n"
                "yarar açık adresinin araştırılması istenen ALİ VELİ isimli şahsa, idaremiz Testtepe Mah.\n"
                "Deneme Cad. No: 12 Örnek Okey Salonu Merkez/SAKARYA iş yeri adresinden ulaşılamamıştır.\n")
        out = red(text, MaskRegistry())
        self.assertNotIn("Deneme Cad", out)
        self.assertIn("[ADRES_", out)

    def test_dead_md_link_becomes_plain_text_but_live_links_stay(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "b.md"), "w", encoding="utf-8") as f:
                f.write("x")
            with open(os.path.join(tmp, "dava-analiz.md"), "w", encoding="utf-8") as f:
                f.write("[Tensip Zaptı](<01/yok.md>) ve [var](<b.md>) ve [web](https://example.org/a.md)\n")
            UyapRedactor.rewrite_dropped_links(os.path.join(tmp, "dava-analiz.md"))
            out = open(os.path.join(tmp, "dava-analiz.md"), encoding="utf-8").read()
            self.assertNotIn("yok.md", out)
            self.assertIn("Tensip Zaptı", out)
            self.assertIn("[var](<b.md>)", out)
            self.assertIn("https://example.org/a.md", out)

    def test_archive_signature_and_xml_links_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            idx = os.path.join(tmp, "INDEX.md")
            with open(os.path.join(tmp, "Ustveri.md"), "w", encoding="utf-8") as f:
                f.write("x")
            with open(idx, "w", encoding="utf-8") as f:
                f.write("| Dosya | Metin |\n|---|---|\n"
                        "| [a/ImzaCades.imz](<a/ImzaCades.imz>) | — |\n"
                        "| [a/Ustveri.xml](<a/Ustveri.xml>) | [↗](<Ustveri.md>) |\n"
                        "| [a/x.psmdcp](<a/x.psmdcp>) | — |\n")
            UyapRedactor.rewrite_dropped_links(idx)
            out = open(idx, encoding="utf-8").read()
            self.assertNotIn("](<a/ImzaCades.imz>)", out)
            self.assertNotIn("](<a/x.psmdcp>)", out)
            self.assertNotIn("](<a/Ustveri.xml>)", out)


class TestUdfExtractionAndExport(unittest.TestCase):
    """Çıplak .udf dosyalarının metne dökülüp maskelenmesi ve boş klasör uyarısı."""

    @staticmethod
    def _write_fake_udf(path: str, content_text: str, malformed_xml: bool = False) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if malformed_xml:
            xml_body = (
                '<?xml version="1.0" encoding="UTF-8" ?>'
                f'<template format_id="1.8"><content><![CDATA[{content_text}]]></content>'  # kapanış etiketi eksik
            )
        else:
            xml_body = (
                '<?xml version="1.0" encoding="UTF-8" ?>'
                f'<template format_id="1.8"><content><![CDATA[{content_text}]]></content></template>'
            )
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("content.xml", xml_body.encode("utf-8"))

    def test_a_extract_udf_raw_and_invalid_files(self):
        """Test A: extract_udf_raw metni döndürür; bozuk/ZIP olmayan dosyada '' döner."""
        with tempfile.TemporaryDirectory() as tmp:
            udf_ok = os.path.join(tmp, "tutanak.udf")
            self._write_fake_udf(
                udf_ok,
                f"  \r\nDOSYA NO: 2026/123\r\nDavacı\tTCKN: {T1}\r\nTel: 0532 000 00 00\r\n  ",
            )
            extracted = UyapRedactor.extract_udf_raw(udf_ok)
            self.assertIn("DOSYA NO: 2026/123", extracted)
            self.assertIn("Davacı\tTCKN:", extracted)  # satır içi sekme korunmalı
            self.assertNotIn("\r", extracted)
            self.assertEqual(extracted, extracted.strip())

            # Bozuk XML'de CDATA fallback çalışmalı
            udf_bad_xml = os.path.join(tmp, "bozuk_xml.udf")
            self._write_fake_udf(udf_bad_xml, "DOSYA NO: 2026/123\nFallback metni", malformed_xml=True)
            self.assertEqual(UyapRedactor.extract_udf_raw(udf_bad_xml), "DOSYA NO: 2026/123\nFallback metni")

            # ZIP olmayan dosya -> ""
            not_zip = os.path.join(tmp, "sahte.udf")
            with open(not_zip, "wb") as f:
                f.write(b"NOT_A_ZIP_FILE")
            self.assertEqual(UyapRedactor.extract_udf_raw(not_zip), "")

            # content.xml içermeyen ZIP -> ""
            no_content = os.path.join(tmp, "bos.udf")
            with zipfile.ZipFile(no_content, "w") as zf:
                zf.writestr("other.txt", "merhaba")
            self.assertEqual(UyapRedactor.extract_udf_raw(no_content), "")

    def test_b_export_folder_with_only_two_udfs(self):
        """Test B: Yalnızca 2 UDF içeren klasör -> 2 maskeli .md, .udf yok, udf_converted==2, ocr_converted==0."""
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "Dava_UDF")
            os.makedirs(src)
            self._write_fake_udf(
                os.path.join(src, "01_Dilekce.udf"),
                f"DOSYA NO: 2026/123\nDavacı TCKN: {T1}\nCep Telefonu: 0532 000 00 00\n"
                "Mahkemenize sunulan işbu dilekçe ile taleplerimizi arz ederiz.",
            )
            self._write_fake_udf(
                os.path.join(src, "02_Tutanak.udf"),
                f"DOSYA NO: 2026/123\nDavalı TCKN: {T2}\nTekrar TCKN: {T1}\n"
                "İletişim: 0532 000 00 00\nDuruşma tutanağı metni burada yer almaktadır.",
            )

            events = []
            dest, stats = UyapRedactor.export_isolated_clean_folder(
                src, progress_cb=lambda evt, msg, st: events.append((evt, msg))
            )

            self.assertEqual(stats["udf_converted"], 2)
            self.assertEqual(stats["ocr_converted"], 0)
            self.assertEqual(stats["md_transferred"], 2)
            self.assertEqual(stats["ocr_present"], 0)
            self.assertEqual(stats["low_quality_ocr"], [])
            self.assertFalse(stats["warning_no_documents"])

            doc_mds = []
            for root, _dirs, files in os.walk(dest):
                for f in files:
                    self.assertFalse(f.lower().endswith(".udf"), f"Hedefte .udf bulundu: {f}")
                    if f.endswith(".md") and f != UyapRedactor.REPORT_NAME:
                        doc_mds.append(os.path.join(root, f))
            self.assertEqual(len(doc_mds), 2)

            combined = ""
            for p in doc_mds:
                with open(p, "r", encoding="utf-8") as fh:
                    txt = fh.read()
                self.assertNotIn(UyapRedactor.OCR_MARKER, txt)
                self.assertNotIn("(Yerel OCR)", txt)
                self.assertNotIn(T1, txt)
                self.assertNotIn(T2, txt)
                self.assertNotIn("0532 000 00 00", txt)
                self.assertIn("DOSYA NO: 2026/123", txt)
                combined += txt

            self.assertIn("[TCKN_", combined)
            self.assertIn("[TEL_", combined)
            self.assertTrue(all(evt == "md" for evt, _ in events))

    def test_c_skip_udf_when_md_derivative_exists(self):
        """Test C: Aynı dizinde x.udf + x.udf.md (veya x.md) varsa UDF ikinci kez işlenmez."""
        for md_name in ("x.udf.md", "x.md"):
            with self.subTest(md_name=md_name), tempfile.TemporaryDirectory() as tmp:
                src = os.path.join(tmp, "Dava_Cift")
                os.makedirs(src)
                self._write_fake_udf(
                    os.path.join(src, "x.udf"),
                    f"UDF_KAYNAK_ISARETI DOSYA NO: 2026/123 TCKN: {T1} Cep: 0532 000 00 00 ekstra metin satırı.",
                )
                with open(os.path.join(src, md_name), "w", encoding="utf-8") as f:
                    f.write(
                        f"# Örnek Belge\n\nMD_KAYNAK_ISARETI DOSYA NO: 2026/123 TCKN: {T1} "
                        "Bu belge Yargı PRO tarafından oluşturulmuştur."
                    )

                dest, stats = UyapRedactor.export_isolated_clean_folder(src)
                self.assertEqual(stats["udf_converted"], 0)
                self.assertEqual(stats["md_transferred"], 1)

                doc_mds = [
                    os.path.join(r, fn)
                    for r, _d, fs in os.walk(dest)
                    for fn in fs
                    if fn.endswith(".md") and fn != UyapRedactor.REPORT_NAME
                ]
                self.assertEqual(len(doc_mds), 1)
                with open(doc_mds[0], "r", encoding="utf-8") as fh:
                    content = fh.read()
                self.assertIn("MD_KAYNAK_ISARETI", content)
                self.assertNotIn("UDF_KAYNAK_ISARETI", content)
                self.assertNotIn(T1, content)

    def test_d_empty_folder_sets_warning_and_calls_error_cb(self):
        """Test D: Boş klasörde warning_no_documents=True olur ve progress_cb 'error' alır."""
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "Bos_Dava")
            os.makedirs(src)
            events = []
            _dest, stats = UyapRedactor.export_isolated_clean_folder(
                src, progress_cb=lambda evt, msg, st: events.append((evt, msg, dict(st)))
            )
            self.assertTrue(stats.get("warning_no_documents"))
            self.assertEqual(stats["md_transferred"], 0)
            error_events = [(e, m) for e, m, _ in events if e == "error"]
            self.assertTrue(error_events, "Boş klasörde progress_cb('error', ...) çağrılmalıydı")
            self.assertIn("işlenebilir belge bulunamadı", error_events[0][1])

    def test_e_mixed_yargipro_folder_and_audit(self):
        """Karışık Yargı PRO düzeni: INDEX.md + _kaynak/a.udf + a.md + _kaynak/b.udf -> uçtan uca ve audit."""
        import audit_output

        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "Dava_Karisik")
            os.makedirs(src)

            self._write_fake_udf(
                os.path.join(src, "_kaynak", "a.udf"),
                f"YARGI_PRO_UDF_HAM_ICERIK DOSYA NO: 2026/301\nDavacı TCKN: {T1}\n"
                "Bu metin yalnızca ham UDF içindedir ve türev varken kullanılmamalıdır.",
            )
            a_md_text = (
                f"# Belge A\n\nYARGI_PRO_TUREV_MD_ICERIK DOSYA NO: 2026/301\nDavacı TCKN: {T1}\n"
                "Bu belge Yargı PRO tarafından hazırlanmış en az elli baytlık türev metindir.\n"
            )
            with open(os.path.join(src, "a.md"), "w", encoding="utf-8") as f:
                f.write(a_md_text)

            self._write_fake_udf(
                os.path.join(src, "_kaynak", "b.udf"),
                f"B_UDF_HAM_METIN DOSYA NO: 2026/301\nDavalı TCKN: {T2}\n"
                "Türevi bulunmayan bu UDF belgesi doğrudan metne dökülüp maskelenmelidir.",
            )

            with open(os.path.join(src, "INDEX.md"), "w", encoding="utf-8") as f:
                f.write(
                    "# Dava Belge Dizini\n\n"
                    "| Tarih | Tür | Yön | Gönderen | No | Dosya | Metin |\n"
                    "|---|---|---|---|---|---|---|\n"
                    "| 2026-01-10 | Dilekçe | Gelen | Davacı | 1 | [↗](<_kaynak/a.udf>) | [↗](<a.md>) (10 karakter) |\n"
                    "| 2026-01-12 | Tutanak | — | Mahkeme | 2 | [↗](<_kaynak/b.udf>) | — |\n"
                )

            dest, stats = UyapRedactor.export_isolated_clean_folder(src)

            self.assertEqual(stats["udf_converted"], 1)
            self.assertFalse(os.path.exists(os.path.join(dest, "_kaynak")))
            for root, _dirs, files in os.walk(dest):
                for fn in files:
                    self.assertFalse(fn.lower().endswith(".udf"), f"Hedefte .udf bulundu: {fn}")

            dest_a = os.path.join(dest, "a.md")
            dest_b = os.path.join(dest, "b.md")
            self.assertTrue(os.path.isfile(dest_a))
            self.assertTrue(os.path.isfile(dest_b))

            with open(dest_a, "r", encoding="utf-8") as f:
                a_out = f.read()
            self.assertIn("YARGI_PRO_TUREV_MD_ICERIK", a_out)
            self.assertNotIn("YARGI_PRO_UDF_HAM_ICERIK", a_out)
            self.assertNotIn(T1, a_out)

            with open(dest_b, "r", encoding="utf-8") as f:
                b_out = f.read()
            self.assertIn("B_UDF_HAM_METIN", b_out)
            self.assertNotIn(T2, b_out)

            with open(os.path.join(dest, "INDEX.md"), "r", encoding="utf-8") as f:
                idx_out = f.read()
            self.assertIn("[↗](<a.md>)", idx_out)

            res = audit_output.audit(src, dest)
            _lines, _det, leak = audit_output.summarize(res)
            self.assertFalse(leak)
            self.assertEqual(res["unexpected_files"], [])
            self.assertEqual(res["broken_links"], [])
            self.assertEqual(res["files_with_source"], 3)


if __name__ == "__main__":
    unittest.main()


class TestGroupedIbanOcr(unittest.TestCase):
    """Gruplu yazılmış IBAN satır sonunda bölünmüş veya OCR bir hane eksik okumuş olabilir."""

    def test_grouped_iban_split_across_lines_masked(self):
        red, _ = UyapRedactor.redact_text("Örnek Bankası TR12 3456 7890 1234\n5678 9012, 34 nolu hesaba gönderdi")
        self.assertNotIn("7890 1234", red)
        self.assertNotIn("5678 9012", red)
        self.assertIn("nolu hesaba", red)

    def test_grouped_iban_missing_one_digit_masked(self):
        red, _ = UyapRedactor.redact_text("adına Örnek Bankası TR12 3456 7890 1234 5678 9012 3:\nnolu hesaptan 01.02.2025")
        self.assertNotIn("3456", red)
        self.assertIn("01.02.2025", red)

    def test_web_address_ending_tr_not_masked(self):
        t = "www.ornekbanka.com.tr\n1234567890123\n4 5 6"
        self.assertEqual(UyapRedactor.redact_iban(t)[0], t)

    def test_iban_with_dropped_digits_masked(self):
        for t in ("sube kodu 1234 TR1234567890123 4567890,12 tl hesaba",
                  "DAN TR12345678901234567890123| A\n1.234,56"):
            red, _ = UyapRedactor.redact_text(t)
            self.assertNotIn("TR12", red, t)
        self.assertIn("1.234,56", UyapRedactor.redact_text("DAN TR12345678901234567890123| A\n1.234,56")[0])


class TestOfficeArchivesAndNewFormats(unittest.TestCase):
    """Word (.docx/.doc), Excel (.xlsx), HEIC, EYP/ZIP arşivleri ve işlenemeyen dosya raporu testleri."""

    @staticmethod
    def _write_minimal_docx(path: str, paragraphs: list) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        content_types = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>'
        )
        p_xml = "".join(
            f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs
        )
        doc_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{p_xml}</w:body></w:document>"
        )
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", content_types.encode("utf-8"))
            zf.writestr("word/document.xml", doc_xml.encode("utf-8"))

    @staticmethod
    def _write_minimal_xlsx(path: str, sheet_name: str, shared: list, rows: list) -> None:
        """rows: [(cell_ref, cell_type, value), ...] listesi her satır için."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        si_xml = "".join(f"<si><t>{s}</t></si>" for s in shared)
        shared_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"{si_xml}</sst>"
        )
        wb_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets><sheet name="{sheet_name}" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>"
        )
        rels_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        )
        rows_xml = []
        for idx, r in enumerate(rows, start=1):
            cells = []
            for ref, ctype, val in r:
                t_attr = f' t="{ctype}"' if ctype else ""
                if ctype == "inlineStr":
                    cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{val}</t></is></c>')
                else:
                    cells.append(f'<c r="{ref}"{t_attr}><v>{val}</v></c>')
            rows_xml.append(f'<row r="{idx}">{"".join(cells)}</row>')
        sheet_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(rows_xml)}</sheetData></worksheet>'
        )
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("xl/sharedStrings.xml", shared_xml.encode("utf-8"))
            zf.writestr("xl/workbook.xml", wb_xml.encode("utf-8"))
            zf.writestr("xl/_rels/workbook.xml.rels", rels_xml.encode("utf-8"))
            zf.writestr("xl/worksheets/sheet1.xml", sheet_xml.encode("utf-8"))

    @staticmethod
    def _write_fake_udf(path: str, content_text: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        xml_body = (
            '<?xml version="1.0" encoding="UTF-8" ?>'
            f'<template format_id="1.8"><content><![CDATA[{content_text}]]></content></template>'
        )
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("content.xml", xml_body.encode("utf-8"))

    def test_docx_extraction_and_redaction(self):
        """Minimal .docx dosyası okunur, TCKN ve telefon maskelenir, hedefe .docx kopyalanmaz."""
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "Dava_DOCX")
            os.makedirs(src)
            self._write_minimal_docx(
                os.path.join(src, "dilekce.docx"),
                [
                    "DOSYA NO: 2026/400",
                    f"Davacı TCKN: {T1}",
                    "Cep Telefonu: 0532 111 22 33 — Mahkemenize arz olunur.",
                ],
            )
            dest, stats = UyapRedactor.export_isolated_clean_folder(src)
            self.assertEqual(stats["office_converted"], 1)
            self.assertEqual(stats["md_transferred"], 1)
            out_md = os.path.join(dest, "dilekce.md")
            self.assertTrue(os.path.isfile(out_md))
            self.assertFalse(os.path.exists(os.path.join(dest, "dilekce.docx")))
            content = open(out_md, encoding="utf-8").read()
            self.assertNotIn(T1, content)
            self.assertNotIn("0532 111 22 33", content)
            self.assertIn("[TCKN_", content)
            self.assertIn("[TEL_", content)

    def test_doc_extraction_via_textutil(self):
        """macOS textutil ile üretilen .doc dosyası metne dökülür ve maskelenir."""
        import subprocess
        if not os.path.isfile("/usr/bin/textutil"):
            self.skipTest("textutil mevcut değil")
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "Dava_DOC")
            os.makedirs(src)
            txt_p = os.path.join(tmp, "kaynak.txt")
            doc_p = os.path.join(src, "eski_dilekce.doc")
            with open(txt_p, "w", encoding="utf-8") as f:
                f.write(
                    f"DOSYA NO: 2026/401\nDavacı TCKN: {T1}\n"
                    "Cep Telefonu: 0532 222 33 44\nTalep dilekçesi metni yeterince uzundur."
                )
            proc = subprocess.run(
                ["/usr/bin/textutil", "-convert", "doc", "-output", doc_p, txt_p],
                capture_output=True,
                timeout=30,
            )
            if proc.returncode != 0 or not os.path.isfile(doc_p):
                self.skipTest("textutil .doc üretemedi")

            dest, stats = UyapRedactor.export_isolated_clean_folder(src)
            self.assertEqual(stats["office_converted"], 1)
            out_md = os.path.join(dest, "eski_dilekce.md")
            self.assertTrue(os.path.isfile(out_md))
            self.assertFalse(os.path.exists(os.path.join(dest, "eski_dilekce.doc")))
            content = open(out_md, encoding="utf-8").read()
            self.assertNotIn(T1, content)
            self.assertIn("[TCKN_", content)
            self.assertIn("[TEL_", content)

    def test_xlsx_extraction_table_hesap_tckn_and_amount_preserved(self):
        """Excel .xlsx: Hesap No sütunu [HESAP_, 11 haneli TCKN bilimsel gösterimsiz maskelenir, tutar korunur."""
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "Dava_XLSX")
            os.makedirs(src)
            xlsx_p = os.path.join(src, "dokum.xlsx")
            shared = ["Hesap No", "TCKN", "Tutar", "1.250,00 TL"]
            rows = [
                [("A1", "s", "0"), ("B1", "s", "1"), ("C1", "s", "2")],
                [("A2", "", "987654321"), ("B2", "", T1), ("C2", "s", "3")],
            ]
            self._write_minimal_xlsx(xlsx_p, "Hareketler", shared, rows)

            dest, stats = UyapRedactor.export_isolated_clean_folder(src)
            self.assertEqual(stats["office_converted"], 1)
            out_md = os.path.join(dest, "dokum.md")
            self.assertTrue(os.path.isfile(out_md))
            content = open(out_md, encoding="utf-8").read()
            self.assertIn("## Hareketler", content)
            self.assertIn("[HESAP_", content)
            self.assertIn("[TCKN_", content)
            self.assertNotIn("987654321", content)
            self.assertNotIn(T1, content)
            self.assertIn("1.250,00 TL", content)

    def test_eyp_extraction_skips_metadata_and_counts_archive(self):
        """EYP arşivi: içteki .udf/.docx çıkarılır, XML üstverileri unprocessed'a girmez, archive_count==1."""
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "Dava_EYP")
            os.makedirs(src)
            ust_udf = os.path.join(tmp, "ust.udf")
            ek_docx = os.path.join(tmp, "ek1.docx")
            self._write_fake_udf(
                ust_udf,
                f"ÜST YAZI\nDOSYA NO: 2026/500\nDavacı TCKN: {T1}\n"
                "Mahkemenize sunulan elektronik yazışma paketi üst yazısıdır.",
            )
            self._write_minimal_docx(
                ek_docx,
                [
                    "EK-1 BELGE",
                    f"İlgili TCKN: {T1}",
                    "İletişim: 0532 333 44 55 — İşbu ek belge yeterli uzunluktadır.",
                ],
            )
            eyp_p = os.path.join(src, "X.eyp")
            with zipfile.ZipFile(eyp_p, "w") as zf:
                zf.write(ust_udf, "UstYazi/ust.udf")
                zf.write(ek_docx, "Ekler/ek1.docx")
                zf.writestr("PaketOzeti.xml", b"<ozet/>")
                zf.writestr("[Content_Types].xml", b"<Types/>")
                zf.writestr("_rels/.rels", b"<Relationships/>")

            dest, stats = UyapRedactor.export_isolated_clean_folder(src)
            self.assertEqual(stats["archive_count"], 1)
            self.assertEqual(stats["udf_converted"], 1)
            self.assertEqual(stats["office_converted"], 1)
            self.assertEqual(stats["unprocessed"], [])
            self.assertTrue(os.path.isfile(os.path.join(dest, "X (EYP)", "UstYazi", "ust.md")))
            self.assertTrue(os.path.isfile(os.path.join(dest, "X (EYP)", "Ekler", "ek1.md")))

            for root, _d, files in os.walk(dest):
                for fn in files:
                    self.assertFalse(fn.lower().endswith((".eyp", ".udf", ".docx")))

    def test_zip_slip_prevented(self):
        """../kotu.md üyeli zip-slip arşivi kaynak ve hedef dışına dosya yazmaz."""
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "Dava_ZipSlip")
            os.makedirs(src)
            zip_p = os.path.join(src, "tehlike.zip")
            with zipfile.ZipFile(zip_p, "w") as zf:
                zf.writestr("../kotu.md", "ZARARLI_ICERIK")
                zf.writestr("normal.txt", f"DOSYA NO: 2026/600\nTCKN: {T1}\nNormal belge metni burada.")

            dest, stats = UyapRedactor.export_isolated_clean_folder(src)
            self.assertFalse(os.path.exists(os.path.join(tmp, "kotu.md")))
            self.assertFalse(os.path.exists(os.path.join(src, "kotu.md")))
            self.assertFalse(os.path.exists(os.path.join(dest, "kotu.md")))
            self.assertTrue(os.path.isfile(os.path.join(dest, "tehlike (ZIP)", "normal.txt")))

    def test_encrypted_zip_and_nested_zip_in_unprocessed(self):
        """Şifreli üye bayraklı zip ve iç içe zip unprocessed listesine doğru nedenlerle eklenir."""
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "Dava_ArsivSorun")
            os.makedirs(src)

            enc_zip = os.path.join(src, "sifreli.zip")
            import io
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("gizli.txt", b"encrypted-bytes")
            zbytes = bytearray(buf.getvalue())
            zbytes[6] |= 0x1
            cd_idx = zbytes.find(b"PK\x01\x02")
            zbytes[cd_idx + 8] |= 0x1
            with open(enc_zip, "wb") as f:
                f.write(zbytes)

            inner_zip = os.path.join(tmp, "ic.zip")
            with zipfile.ZipFile(inner_zip, "w") as zf:
                zf.writestr("ic_dosya.txt", "Bu içteki dosya açılmamalıdır.")
            outer_zip = os.path.join(src, "dis.zip")
            with zipfile.ZipFile(outer_zip, "w") as zf:
                zf.write(inner_zip, "ic.zip")
                zf.writestr("dis_not.txt", f"TCKN: {T1}\nDış arşivdeki normal metin dosyası.")

            dest, stats = UyapRedactor.export_isolated_clean_folder(src)
            unproc = dict(stats["unprocessed"])
            self.assertEqual(unproc.get("sifreli.zip"), "işlenemedi (şifreli)")
            self.assertEqual(unproc.get("dis.zip/ic.zip"), "iç içe arşiv")
            self.assertTrue(os.path.isfile(os.path.join(dest, "dis (ZIP)", "dis_not.txt")))

    def test_unsupported_type_and_ds_store_filtering(self):
        """not.html unprocessed'a girer, .DS_Store girmez; raporda listelenir."""
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "Dava_Desteklenmeyen")
            os.makedirs(src)
            with open(os.path.join(src, "belge.md"), "w", encoding="utf-8") as f:
                f.write(f"DOSYA NO: 2026/700\nTCKN: {T1}\nGeçerli markdown belgesi.")
            with open(os.path.join(src, "not.html"), "w", encoding="utf-8") as f:
                f.write("<html><body>Merhaba</body></html>")
            with open(os.path.join(src, ".DS_Store"), "wb") as f:
                f.write(b"\x00\x00\x00\x01Bud1")

            dest, stats = UyapRedactor.export_isolated_clean_folder(src)
            unproc = dict(stats["unprocessed"])
            self.assertEqual(unproc.get("not.html"), "desteklenmeyen tür (.html)")
            self.assertNotIn(".DS_Store", unproc)
            report = open(os.path.join(dest, UyapRedactor.REPORT_NAME), encoding="utf-8").read()
            self.assertIn("## İşlenemeyen dosyalar", report)
            self.assertIn("- not.html — desteklenmeyen tür (.html)", report)

    def test_yargipro_derivative_skips_xlsx(self):
        """a.xlsx + a.xlsx.md (>=50 bayt) varsa a.xlsx ikinci kez işlenmez."""
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "Dava_XlsxTurev")
            os.makedirs(src)
            self._write_minimal_xlsx(
                os.path.join(src, "a.xlsx"),
                "Sayfa1",
                ["XLSX_HAM_ISARETI"],
                [[("A1", "s", "0")]],
            )
            with open(os.path.join(src, "a.xlsx.md"), "w", encoding="utf-8") as f:
                f.write(
                    f"# Türev\n\nMD_TUREV_ISARETI TCKN: {T1} "
                    "Yargı PRO tarafından hazırlanmış en az elli baytlık türev."
                )
            dest, stats = UyapRedactor.export_isolated_clean_folder(src)
            self.assertEqual(stats["office_converted"], 0)
            self.assertEqual(stats["md_transferred"], 1)
            self.assertEqual(stats["unprocessed"], [])
            out_md = open(os.path.join(dest, "a.xlsx.md"), encoding="utf-8").read()
            self.assertIn("MD_TUREV_ISARETI", out_md)
            self.assertNotIn("XLSX_HAM_ISARETI", out_md)

    def test_archive_temp_dirs_cleaned_after_export(self):
        """Export sonrası tempfile.gettempdir() altında yeni 'uyap_arsiv_' dizini kalmaz."""
        tmp_root = tempfile.gettempdir()
        before = {d for d in os.listdir(tmp_root) if d.startswith("uyap_arsiv_")}
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "Dava_TmpTemizlik")
            os.makedirs(src)
            with zipfile.ZipFile(os.path.join(src, "paket.zip"), "w") as zf:
                zf.writestr("ek.txt", f"TCKN: {T1}\nGeçici dizin temizlik testi metni.")
            UyapRedactor.export_isolated_clean_folder(src)
        after = {d for d in os.listdir(tmp_root) if d.startswith("uyap_arsiv_")}
        self.assertEqual(after - before, set())

    def test_heic_extraction_via_vision(self):
        """sips ile üretilen .heic dosyası Vision OCR ile çökmeden işlenir."""
        import subprocess
        try:
            import Vision  # noqa: F401
        except ImportError:
            self.skipTest("Apple Vision mevcut değil")
        if not os.path.isfile("/usr/bin/sips"):
            self.skipTest("sips mevcut değil")

        with tempfile.TemporaryDirectory() as tmp:
            png_p = os.path.join(tmp, "ornek.png")
            heic_p = os.path.join(tmp, "ornek.heic")
            try:
                from PIL import Image
                Image.new("RGB", (200, 100), "white").save(png_p, "PNG")
            except Exception:
                self.skipTest("PIL örnek PNG üretemedi")

            proc = subprocess.run(
                ["/usr/bin/sips", "-s", "format", "heic", png_p, "--out", heic_p],
                capture_output=True,
                timeout=30,
            )
            if proc.returncode != 0 or not os.path.isfile(heic_p):
                self.skipTest("sips .heic üretemedi")

            out = UyapRedactor.extract_image_raw(heic_p)
            self.assertIsInstance(out, str)
            out2 = UyapRedactor.extract_scanned_raw(heic_p)
            self.assertIsInstance(out2, str)

    def test_pdf_default_max_pages_is_2000(self):
        import inspect
        sig1 = inspect.signature(UyapRedactor.extract_pdf_raw)
        sig2 = inspect.signature(UyapRedactor.extract_and_redact_pdf)
        self.assertEqual(sig1.parameters["max_pages"].default, 2000)
        self.assertEqual(sig2.parameters["max_pages"].default, 2000)


class TestFixRound2D1D2D3(unittest.TestCase):
    """DÜZELTME TURU 2 (D1: çıplak 10 haneli telefon, D2: HTS baz/koordinat, D3: dosya adları)."""

    def test_d1_bare_10digit_phones_masked_and_negatives_preserved(self):
        """D1: 10 haneli cep numaraları bağlam/liste/satırda yakalanır; VKN/esas/hesap/tutar korunur."""
        cases = [
            "Kendi adıma kayıtlı olan 5321234567, 05321234568 numaraları",
            "(şüpheli X adına kayıtlı),  5329876543 numaralı (Şüpheli Y adına kayıtlı)",
            "Refik ÖRNEK 5321112233 İlişki Grafiği",
            "| 5871112233 |\nTel: 05320000001",
            "Abone görüşmesi 5872223344 ile yapılmıştır.",
            "5873334455 ve 05320001122 numaraları arandı.",
        ]
        for txt in cases:
            out, cnt = UyapRedactor.redact_phone(txt, MaskRegistry())
            self.assertGreaterEqual(cnt, 1, f"Maskelenmedi: {txt}")
            for raw_num in ("5321234567", "05321234568", "5329876543", "5321112233", "5871112233", "5872223344", "5873334455"):
                self.assertNotIn(raw_num, out, f"Sızıntı ({raw_num}): {out}")

        # Aynı numaranın 3 farklı yazımı aynı registry etiketini almalı
        reg = MaskRegistry()
        o1, _ = UyapRedactor.redact_phone("Tel: 5321234567", reg)
        o2, _ = UyapRedactor.redact_phone("Tel: 05321234567", reg)
        o3, _ = UyapRedactor.redact_phone("Tel: +90 532 123 45 67", reg)
        self.assertEqual(o1, "Tel: [TEL_1]")
        self.assertEqual(o2, "Tel: [TEL_1]")
        self.assertEqual(o3, "Tel: [TEL_1]")

        # D1(d): registry'de kayıtlı numara bağlamsız 587... olsa da yakalanır
        reg2 = MaskRegistry()
        UyapRedactor.redact_phone("Tel: 05874445566", reg2)
        o_known, c_known = UyapRedactor.redact_phone("Kayıt satırı 5874445566 detay.", reg2)
        self.assertEqual(c_known, 1)
        self.assertIn("[TEL_1]", o_known)

        # Negatifler (ASLA telefon sayılmaz)
        for neg in (
            "Vergi No: 5321234567",
            "VKN 5321234567",
            "Esas No: 2025/5321234567",
            "evrak no 5321234567",
            "abone no: 5321234567",
            "5.321.234.567,00 TL",
        ):
            out_n, cnt_n = UyapRedactor.redact_phone(neg, MaskRegistry())
            self.assertEqual(out_n, neg, f"Yanlış pozitif: {neg}")
            self.assertEqual(cnt_n, 0)

        # Hesap No: redact_text içinde [HESAP_] olabilir ama ASLA [TEL_] olmamalı
        out_acc, _ = UyapRedactor.redact_text("Hesap No: 5321234567", registry=MaskRegistry())
        self.assertNotIn("[TEL_", out_acc)

    def test_d2_hts_base_station_and_coordinates_preserved_but_ikamet_masked(self):
        """D2: HTS baz istasyonu satırı ve koordinatlar korunur; aynı belgedeki ikamet adresi maskelenir."""
        doc = (
            "420037031084 - opr:Vodafone(LA412745O207031084) - ÖRNEK\n"
            "MAH. FATIH CAD. NO:124 DENIZLI,DENIZLI, 37.771667- 29.072219\n\n"
            "İkamet adresi: Örnek Mah. Deneme Sok. No:5 D:3 Merkez/ANKARA\n"
        )
        out, _ = UyapRedactor.redact_text(doc, registry=MaskRegistry())
        self.assertIn("opr:Vodafone", out)
        self.assertIn("MAH. FATIH CAD. NO:124 DENIZLI,DENIZLI, 37.771667- 29.072219", out)
        self.assertIn("İkamet adresi: [ADRES_1]", out)
        self.assertNotIn("Deneme Sok.", out)

    def test_d3_filename_and_dirname_pii_masked_with_valid_index_links(self):
        """D3: Klasör/dosya adındaki telefon ve TCKN maskelenir; INDEX bağlantısı, rapor ve callback temizdir."""
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            src = os.path.join(tmp, "DavaD3")
            sub = os.path.join(src, "Satıcı 0532 000 00 01 - not")
            os.makedirs(sub)

            target_md = os.path.join(sub, "a.md")
            target_text = "Satıcı ile yapılan görüşme tutanağı metni.\nTelefon: 0532 000 00 01\n"
            with open(target_md, "w", encoding="utf-8") as f:
                f.write(target_text)

            tckn_md = os.path.join(src, f"{T1} dilekçe.md")
            with open(tckn_md, "w", encoding="utf-8") as f:
                f.write(f"Davacı TCKN: {T1}\nTalep dilekçesi içeriği.\n")

            # Aynı maskeli ada düşen çarpışma dosyaları
            with open(os.path.join(src, "0532 000 00 01.md"), "w", encoding="utf-8") as f:
                f.write("İlk numara belgesi.\n")
            with open(os.path.join(src, "+90 532 000 00 01.md"), "w", encoding="utf-8") as f:
                f.write("İkinci numara belgesi.\n")

            # İşlenemeyen dosya (dosya yolu rapor/logda maskeli görünmeli)
            with open(os.path.join(sub, "ek.xyz"), "wb") as f:
                f.write(b"raw")

            idx_content = (
                "# Dava İndeksi\n\n"
                "| Tarih | Tür | Kurum | Ek | Kişi | Dosya | Metin |\n"
                "|---|---|---|---|---|---|---|\n"
                "| 01.02.2026 | Not | — | — | — | — | [↗](<Satıcı 0532 000 00 01 - not/a.md>) (10 karakter) |\n"
                f"| 02.02.2026 | Dilekçe | — | — | — | — | [↗](<{T1} dilekçe.md>) (10 karakter) |\n"
            )
            with open(os.path.join(src, "INDEX.md"), "w", encoding="utf-8") as f:
                f.write(idx_content)

            cb_events = []
            dest, stats = UyapRedactor.export_isolated_clean_folder(
                src, progress_cb=lambda k, msg, _gs: cb_events.append((k, msg))
            )

            # Hiçbir dosya/klasör adında ham telefon veya TCKN kalmamalı
            all_rels = []
            for root, dirs, files in os.walk(dest):
                for name in dirs + files:
                    p = os.path.join(root, name)
                    rel = unicodedata.normalize("NFC", os.path.relpath(p, dest))
                    all_rels.append(rel)
                    self.assertNotIn("0532 000 00 01", rel)
                    self.assertNotIn("05320000001", rel)
                    self.assertNotIn(T1, rel)

            # Beklenen maskeli klasör ve dosyalar diskte mevcut olmalı
            self.assertTrue(any(re.match(r'^Satıcı \[TEL_\d+\] - not/a\.md$', r) for r in all_rels), all_rels)
            self.assertTrue(any(re.match(r'^\[TCKN_\d+\] dilekçe\.md$', r) for r in all_rels), all_rels)
            self.assertTrue(any(re.match(r'^\[TEL_\d+\] \(2\)\.md$', r) for r in all_rels), all_rels)

            # INDEX bağlantısı kopuk olmamalı ve gerçek hedefe işaret etmeli
            idx_out = open(os.path.join(dest, "INDEX.md"), encoding="utf-8").read()
            self.assertNotIn("0532 000 00 01", idx_out)
            self.assertNotIn(T1, idx_out)
            targets = re.findall(r'\[↗\]\(<([^>]+)>\)', idx_out)
            self.assertEqual(len(targets), 2)
            for tgt in targets:
                self.assertTrue(os.path.isfile(os.path.join(dest, tgt)), f"Kopuk hedef: {tgt}")

            # Rapor, unprocessed ve progress_cb ham PII içermemeli
            report_out = open(os.path.join(dest, UyapRedactor.REPORT_NAME), encoding="utf-8").read()
            self.assertNotIn("0532 000 00 01", report_out)
            self.assertNotIn(T1, report_out)
            for u_rel, _reason in stats["unprocessed"]:
                self.assertNotIn("0532 000 00 01", u_rel)
                self.assertNotIn(T1, u_rel)
            for _k, msg in cb_events:
                self.assertNotIn("0532 000 00 01", msg)
                self.assertNotIn(T1, msg)


if __name__ == "__main__":
    unittest.main()


class TestMaskedPathLinkRegression(unittest.TestCase):
    """v1.4.0 çökmesi: maskeli klasör adına giden bağlantılarda 'str' object has no attribute 'search'."""

    def test_links_into_masked_folder_do_not_crash(self):
        import tempfile, shutil
        root = tempfile.mkdtemp(prefix="uyap_link_reg_")
        try:
            src = os.path.join(root, "Dava")
            sub = os.path.join(src, "Talimat 0532 000 00 01")
            os.makedirs(sub)
            with open(os.path.join(sub, "a.md"), "w", encoding="utf-8") as f:
                f.write("Deneme belgesi içeriği, yeterince uzun bir metin satırı burada yer alıyor.\n")
            with open(os.path.join(src, "safahat.md"), "w", encoding="utf-8") as f:
                f.write("Bkz. [ek](Talimat 0532 000 00 01/a.md) ve [eksik]([TEL_9] yok/b.md)\n")
            with open(os.path.join(src, "INDEX.md"), "w", encoding="utf-8") as f:
                f.write("# INDEX\n\n| Dosya | Metin |\n|---|---|\n| [a](Talimat 0532 000 00 01/a.md) | 10 |\n")
            dest, _stats = UyapRedactor.export_isolated_clean_folder(src, os.path.join(root, "out"))
            with open(os.path.join(dest, "safahat.md"), encoding="utf-8") as f:
                saf = f.read()
            self.assertNotIn("0532", saf)
            self.assertIn("[TEL_1]/a.md", saf)
            self.assertTrue(os.path.isfile(os.path.join(dest, "Talimat [TEL_1]", "a.md")))
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TestFiltrelemeTestFindings(unittest.TestCase):
    """Gerçek dava klasörü testinde bulunan fazla maskeleme ve yanlış alarm düzeltmeleri (uydurma veri)."""

    def test_kaza_tutanagi_lejanti_adres_degil(self):
        t = "YOLUN SINIFI\n4\n1 Cadde\n4 Devlet yolu\n2 Sokak\n"
        self.assertEqual(UyapRedactor.redact_text(t)[0], t)

    def test_sirket_tarafin_adresi_korunur_kisi_maskelenir(self):
        t = ("**DAVALILAR\t:  1.- **Örnek Sigorta A.Ş, (V.D. No:4567012398); \n"
             "\t\t İçerenköy Umut Sokak No:10/12 Ataşehir / İstanbul\n"
             "\t\t   **2.- **Ali Veli (T.C. No: 12345678950),\n"
             "\t\t Yazır Köyü Küme Evleri No: 382/1 Ağlasun / Burdur\n")
        out = UyapRedactor.redact_text(t)[0]
        self.assertIn("İçerenköy Umut Sokak No:10/12", out)
        self.assertNotIn("Küme Evleri No: 382/1", out)
        self.assertIn("V.D. No:4567012398", out)

    def test_vergi_kimlik_no_10_hane_korunur_11_hane_maskelenir(self):
        self.assertIn("1234567890", UyapRedactor.redact_text("**Vergi Kimlik No:** 1234567890")[0])
        self.assertNotIn("12345678950", UyapRedactor.redact_text("**Vergi Kimlik No:** 12345678950")[0])
        self.assertNotIn("1234567890", UyapRedactor.redact_text("Kimlik No: 1234567890")[0])

    def test_turevi_olan_html_ve_kucuk_gorsel_islenemeyen_listesinde_degil(self):
        import tempfile, shutil
        from PIL import Image
        root = tempfile.mkdtemp(prefix="uyap_ft_")
        try:
            src = os.path.join(root, "Dava")
            os.makedirs(os.path.join(src, "_kaynak", "06-Mali"))
            os.makedirs(os.path.join(src, "06-Mali"))
            os.makedirs(os.path.join(src, "01", "Belge_1"))
            with open(os.path.join(src, "_kaynak", "06-Mali", "makbuz.html"), "w", encoding="utf-8") as f:
                f.write("<html><body>makbuz</body></html>")
            with open(os.path.join(src, "06-Mali", "makbuz.md"), "w", encoding="utf-8") as f:
                f.write("Vekalet pulu makbuzu metni, yeterince uzun bir deneme satırı burada.\n")
            with open(os.path.join(src, "01", "Belge_1.md"), "w", encoding="utf-8") as f:
                f.write("Belge metni ![](Belge_1/gorsel-1.png) yeterince uzun bir deneme satırı burada.\n")
            Image.new("RGB", (16, 17), "white").save(os.path.join(src, "01", "Belge_1", "gorsel-1.png"))
            with open(os.path.join(src, "not.html"), "w", encoding="utf-8") as f:
                f.write("<html>turevsiz</html>")
            _dest, st = UyapRedactor.export_isolated_clean_folder(src, os.path.join(root, "out"))
            listed = [p for p, _r in st["unprocessed"]]
            self.assertFalse(any("makbuz" in p for p in listed), listed)
            self.assertFalse(any("gorsel-1" in p for p in listed), listed)
            self.assertTrue(any(p.endswith("not.html") for p in listed), listed)
            self.assertEqual(st["small_images_skipped"], 1)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TestSenaryoQAFindings(unittest.TestCase):
    """Sonnet senaryo testlerinde bulunan sızıntı/fazla maskeleme düzeltmeleri (uydurma veri)."""

    R = staticmethod(lambda t: UyapRedactor.redact_text(t)[0])

    def test_nbsp_bosluklu_sicil_ve_adres(self):
        out = self.R("Bilirkişi\xa0Sicil\xa0No:\xa0784512\nAdres\xa0:\xa0Mamak\xa0Mah.\xa0Gazi\xa0Cad.\xa0No:58/4\xa0Mamak/ANKARA")
        self.assertNotIn("784512", out)
        self.assertNotIn("Mamak Mah", out)
        self.assertNotIn("Gazi", out)

    def test_halen_adresinde_oturur_mahalle_adi_maskelenir(self):
        out = self.R("Şüpheli halen Bağbaşı Mah. Gül Sok. No:5 D:3 Merkezefendi/DENİZLİ adresinde oturur.\n\nŞÜPHELİ İFADESİ")
        self.assertNotIn("Bağbaşı", out)
        self.assertIn("adresinde oturur.\n\nŞÜPHELİ İFADESİ", out)
        self.assertIn("Örnek Mah. sakinleri", self.R("halen devam eden davada Örnek Mah. sakinleri"))

    def test_satira_bolunmus_iban_ikinci_satir(self):
        self.assertNotIn("6789", self.R("IBAN: TR12 0006 4000 0011 2345\n/ 6789 01"))

    def test_sgk_ve_diploma_tescil(self):
        self.assertNotIn("1234567890123", self.R("SGK Sicil No: 1234567890123"))
        self.assertNotIn("123456", self.R("Uzm. Dr. Ali Veli Diploma Tescil No: 123456"))
        self.assertIn("2019/12345", self.R("Marka Tescil No: 2019/12345"))

    def test_bolunmus_ve_bosluklu_tckn(self):
        self.assertNotIn("89138", self.R("T.C. Kimlik No: 234567\n89138 olan"))
        self.assertNotIn("6789 138", self.R("I.C. Kimlik N0: 2345 6789 138"))
        self.assertIn("2025 yılında", self.R("TCKN: 12345678950\n2025 yılında"))
        self.assertIn("2025/123 Esas", self.R("T.C. No: 12345\n2025/123 Esas"))

    def test_isveren_adresi_kunye_satiri_arada(self):
        t = ("**İŞVEREN:** Örnek Yazılım A.Ş.\nVergi Kimlik No: 9876543210\n"
             "Adres: Teknokent Mah. Bilişim Cad. No:5 Kat:3 Çankaya/ANKARA")
        self.assertIn("Teknokent Mah.", self.R(t))
        t2 = "DAVALI 1: Örnek Sigorta A.Ş.\nDAVALI 2: Ali Veli\nAdres: Gül Mah. Lale Sok. No:5 Merkez/BURDUR"
        self.assertNotIn("Lale Sok", self.R(t2))

    def test_vkn_bilinen_tckn_onekiyle_cakisinca_korunur(self):
        out = self.R("Ali Veli TC: 12345678950\nŞirket VKN: 1234567890 (10 haneli)")
        self.assertIn("1234567890 (10 haneli)", out)

    def test_yuzde_kodlu_baglanti_hedefi_cozulur_ve_maskelenir(self):
        out = self.R("- [K](Şüpheli%200532%20000%2011%2022%20-%20ifadeler/a.md) [w](https://x.gov.tr/a%20b.pdf)")
        self.assertNotIn("0532", out)
        self.assertNotIn("%20", out.split("https")[0])
        self.assertIn("https://x.gov.tr/a%20b.pdf", out)

    def test_kisa_udf_belgesi_atilmaz(self):
        import tempfile, shutil, zipfile
        root = tempfile.mkdtemp(prefix="uyap_kisa_")
        try:
            src = os.path.join(root, "Dava")
            os.makedirs(src)
            with zipfile.ZipFile(os.path.join(src, "kisa.udf"), "w") as z:
                z.writestr("content.xml", '<?xml version="1.0" encoding="UTF-8" ?><template format_id="1.8">'
                           '<content><![CDATA[CEVAP\nDavalı TC: 12345678950]]></content></template>')
            dest, st = UyapRedactor.export_isolated_clean_folder(src, os.path.join(root, "out"))
            self.assertTrue(os.path.isfile(os.path.join(dest, "kisa.md")))
            self.assertEqual(st["unprocessed"], [])
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TestAileKlasoruBulgulari(unittest.TestCase):
    """Aile mahkemesi klasör testinde bulunan tırnaklı/düzyazı adres sızıntıları (uydurma veri)."""

    R = staticmethod(lambda t: UyapRedactor.redact_text(t)[0])

    def test_tirnakli_adres_ve_cumle_korunur(self):
        out = self.R('küçüğün belirtilen "Örnek Mahallesi Merkez (Örnek) Sokak No:6 Çine/AYDIN" adresinde yaşamadığı, '
                     'açık adresinin "Deneme Mahallesi 328 Sok. No:9 İncirliova /AYDIN" olduğu ve mahkememizin yetki '
                     'alanı dışında bulunduğu anlaşıldığından hüküm kurulmuştur.')
        self.assertNotIn("Örnek Mahallesi", out)
        self.assertNotIn("Deneme Mahallesi", out)
        self.assertIn('" adresinde yaşamadığı', out)
        self.assertIn('" olduğu ve mahkememizin', out)

    def test_adres_sonrasi_hukuki_ifade_adresi_acik_birakmaz(self):
        out = self.R("açık adresi Deneme Mahallesi 328 Sok. No:9 İncirliova/AYDIN olup mahkememizin yetki alanı "
                     "dışında kaldığından TMK 411. madde gereğince hüküm kurulmuştur.")
        self.assertNotIn("Deneme", out)
        self.assertIn("olup mahkememizin", out)
        self.assertIn("TMK 411. madde", out)

    def test_uzun_satirda_uzak_kurum_adi_kisi_adresini_korumaz(self):
        line = ("Küçük Ali Veli'yi temsil etmek üzere temsil kayyımı atanması için Aydın Sulh Hukuk Mahkemesine "
                "ihbarda bulunulduğu, Aydın 1. Sulh Hukuk Mahkemesi'nin 2022/2665 Esas 2022/2991 Karar sayılı kararı "
                'ile küçüğün mernis adresinin " Örnek Mah.Merkez (Örnek) Sokak No:6 Çine /Aydın " olması nedeniyle '
                "yetkisizlik kararı verildiği anlaşılmıştır.")
        out = self.R(line)
        self.assertNotIn("Örnek Mah", out)
        self.assertIn("Aydın 1. Sulh Hukuk Mahkemesi", out)

    def test_ust_satirdaki_kurum_duzyazi_adresini_korumaz(self):
        t = ("İncirliova İlçe Jandarma Komutanlığı'na müzekkere yazılarak küçüğün annesinin araştırılması istenmiştir.\n"
             'Bu bağlamda kayyım atanması talep edilen küçüğün belirtilen "Örnek Mahallesi Merkez Sokak No:6 '
             'Çine/AYDIN" adresinde yaşamadığı, açık adresinin "Deneme Mahallesi 328 Sok. No:9 İncirliova /AYDIN" '
             "olduğu ve mahkememizin yetki alanı dışında bulunduğu anlaşıldığından dosyanın gönderilmesine karar verilmiştir.")
        out = self.R(t)
        self.assertNotIn("Örnek Mahallesi", out)
        self.assertNotIn("Deneme Mahallesi", out)
        self.assertIn("Jandarma Komutanlığı", out)

    def test_duzyazida_banka_adresi_korunur(self):
        t = ("Örnek Bankası A.Ş. Genel Müdürlüğü, Levent Mah. Büyükdere Cad. No:201 Şişli/İSTANBUL adresinde faaliyet "
             "göstermekte olup bu husus dosyaya sunulan ticaret sicil gazetesi ve diğer belgelerle sabit olup davalı "
             "bankanın sorumluluğu bulunmaktadır.")
        self.assertIn("Büyükdere Cad. No:201", self.R(t))


class TestAileKlasoruBulgulari2(unittest.TestCase):
    """v1.4.3 arayüz testinde bulunan: 'N:' kapı no kısaltması ve üst satırda kurum adı olan taraf satırı."""

    R = staticmethod(lambda t: UyapRedactor.redact_text(t)[0])

    def test_N_kisaltmali_kapi_no(self):
        out = self.R("**DAVALI\t:** ALİ VELİ-12345678950 - Deneme Mah 328 Sk N:9 İncirliova /Aydın")
        self.assertNotIn("Deneme Mah", out)
        self.assertIn("Formül: N: 5 adet", self.R("Formül: N: 5 adet"))

    def test_ust_satirda_mahkeme_olan_taraf_satiri_kisi_adresidir(self):
        t = ("**İHBAR EDEN\t:** AYDIN 1 AİLE MAHKEMESİ \n\n"
             "**KÜÇÜK\t:** ALİ VELİ - 12345678950 -Deneme Mah 328 Sk N:9  İncirliova/ AYDIN\n"
             "**KAYYIM ADAYI\t:** VELİ ALİ - 10000000146 -Örnek Mah. Merkez(Örnek) Sk. No:6  Çine/ AYDIN")
        out = self.R(t)
        self.assertNotIn("Deneme Mah", out)
        self.assertNotIn("Örnek Mah", out)
        self.assertIn("AYDIN 1 AİLE MAHKEMESİ", out)

    def test_adliye_adresi_korunur(self):
        t = "**İHBAR EDEN\t:** AYDIN 1 AİLE MAHKEMESİ\n**Adres:** Adliye Sarayı Hasanefendi Mah. Adnan Menderes Blv. No:1 Efeler/AYDIN"
        self.assertIn("Hasanefendi Mah.", self.R(t))


class TestKoyAdresi(unittest.TestCase):
    """Ceza dosyası testinde bulunan: 'X Köyü X Küme Evleri No:' adresinde köy adının açık kalması."""

    R = staticmethod(lambda t: UyapRedactor.redact_text(t)[0])

    def test_kayitli_onekli_koy_adresi(self):
        t = ("doğumlu, ili, ilçesi, köy/mahallesi, cilt, aile sıra no, sıra no'da nüfusa\n"
             "kayıtlı Örnekyayla Köyü Örnekyayla Küme Evleri No: 128 Burdur\nMerkez/ BURDUR ikamet eder.")
        out = self.R(t)
        self.assertNotIn("Örnekyayla", out)
        self.assertIn("kayıtlı [ADRES_", out)

    def test_satir_sonuna_dusen_koy_adi(self):
        t = ("SANIK: ALİ VELİ, 13/05/1997 BURDUR doğumlu, Örnekyayla\n"
             "Köyü Örnekyayla Küme Evleri No: 128 Burdur Merkez/ BURDUR adresinde oturur.")
        out = self.R(t)
        self.assertNotIn("Örnekyayla", out)
        self.assertIn("adresinde oturur.", out)

    def test_nufus_kayit_koyu_ve_muhtarlik_korunur(self):
        t1 = "Burdur ili, Merkez ilçesi, Örnekyayla köyü, cilt 12, aile sıra no 34'te nüfusa kayıtlı"
        self.assertEqual(self.R(t1), t1)
        t2 = "Örnekyayla Köyü muhtarlığından alınan yazıda"
        self.assertEqual(self.R(t2), t2)


class TestAdresGuvenlikAgi(unittest.TestCase):
    """Katman 7z (Son güvenlik ağı): yapısal adres kalıpları ve korunacak bağlamlar (uydurma veri)."""

    def test_yapisal_adresler_maskelenir(self):
        cases = [
            ("Örnek Mah 12 Sk N:5 Merkez/ANKARA", ["Örnek", "ANKARA"], []),
            (
                "Deneme Köyü Deneme Küme Evleri No: 7 Burdur Merkez/ BURDUR adresinde oturur.",
                ["Deneme", "Küme Evleri", "BURDUR"],
                ["adresinde oturur."],
            ),
            (
                'küçüğün "Gül Mahallesi Lale (Gül) Sokak No:6 Çine/AYDIN" olduğu, TMK 411. madde gereğince',
                ["Gül Mahallesi", "AYDIN"],
                ['(Çine/Aydın)', '" olduğu, TMK 411. madde'],
            ),
            ("Çamlık Mevkii Kavak Sitesi B Blok D:4 Pamukkale/DENİZLİ", ["Çamlık", "Kavak", "DENİZLİ"], ["(Pamukkale/Denizli)"]),
            ("Yeni Mahallesi 1234 Sokak 28/3 Efeler/AYDIN", ["Yeni", "28/3", "AYDIN"], ["(Efeler/Aydın)"]),
            ("Kurtuluş Mh. Atatürk Cd. Nu:15 İzmir", ["Kurtuluş", "Atatürk", "Nu:15"], ["(İzmir)"]),
            (
                "doğumlu, Güneyyayla\nKöyü Güneyyayla Küme Evleri No: 128 Burdur\nMerkez/ BURDUR ikamet eder.",
                ["Güneyyayla", "128", "BURDUR"],
                ["doğumlu,", "ikamet eder."],
            ),
            (
                "Apartmanı: Güneş Apt. Kat:3 Daire:7, Bahar Mah. 5. Sok.",
                ["Güneş", "Daire:7", "Bahar"],
                ["Apartmanı:"],
            ),
        ]
        for raw, leaks, keeps in cases:
            out, stats = UyapRedactor.redact_text(raw, registry=MaskRegistry())
            self.assertGreaterEqual(stats["adres"], 1, raw)
            self.assertIn("[ADRES_1]", out, raw)
            for lk in leaks:
                self.assertNotIn(lk, out, raw)
            for kp in keeps:
                self.assertIn(kp, out, raw)

            # Güvenlik ağı tek başına da aynı yapısal adayları yakalamalı ve idempotent olmalı
            direct_out, direct_cnt = UyapRedactor.redact_address_safety_net(raw, registry=MaskRegistry())
            self.assertGreaterEqual(direct_cnt, 1, raw)
            for lk in leaks:
                self.assertNotIn(lk, direct_out, raw)
            for kp in keeps:
                self.assertIn(kp, direct_out, raw)
            idem_out, idem_cnt = UyapRedactor.redact_address_safety_net(direct_out, registry=MaskRegistry())
            self.assertEqual(idem_out, direct_out, raw)
            self.assertEqual(idem_cnt, 0, raw)

    def test_etiket_onunde_kalan_yer_adi_birlestirilir(self):
        reg = MaskRegistry()
        out, _ = UyapRedactor.redact_text("Taşoluk [ADRES_3] / AYDIN", registry=reg)
        self.assertNotIn("Taşoluk", out)
        self.assertNotIn("AYDIN", out)
        self.assertIn("[ADRES_3]", out)
        # Kişi adı satırı etiketle birleştirilmez
        out_person, _ = UyapRedactor.redact_text("ALİ VELİ [ADRES_3]", registry=MaskRegistry())
        self.assertIn("ALİ VELİ [ADRES_3]", out_person)

    def test_korunacak_baglamlar_aynen_kalir(self):
        preserved = [
            "Burdur Adliyesi, Cumhuriyet Mah. 1234 Sok. No:1 Merkez/BURDUR",
            "Örnek Bankası A.Ş. Genel Müdürlüğü Levent Mah. Büyükdere Cad. No:201 Şişli/İSTANBUL",
            "Kaza, Atatürk Cad. No:45 önünde meydana gelmiştir.",
            "KONYA ili, EMİRGAZİ ilçesi, IŞIKLAR köy/mahallesi, 32 cilt, 19 aile sıra no, 120 sıra no'da nüfusa kayıtlı",
            "Konya, Emirgazi, Işıklar mah/köy nüfusunda kayıtlı.",
            "YOLUN SINIFI\n4\n1 Cadde\n4 Devlet yolu\n2 Sokak",
            "Burdur 3. Asliye Hukuk Mah. 2025/133 E.",
            "HMK 107. madde gereğince 12/03/2024 tarihinde 5.000,00 TL ödenmiştir.",
            "420037031084 - opr:Vodafone(LA41) - ÖRNEK MAH. FATIH CAD. NO:124 DENIZLI, 37.771667- 29.072219",
            "Örnek Köyü muhtarlığından alınan yazıda",
        ]
        for text in preserved:
            out, _ = UyapRedactor.redact_text(text, registry=MaskRegistry())
            self.assertEqual(out, text, text)
            direct_out, direct_cnt = UyapRedactor.redact_address_safety_net(text, registry=MaskRegistry())
            self.assertEqual(direct_out, text, text)
            self.assertEqual(direct_cnt, 0, text)

    def test_guvenlik_agi_etiket_tutarliligi(self):
        reg = MaskRegistry()
        a, _ = UyapRedactor.redact_text("Çamlık Mevkii Kavak Sitesi B Blok D:4 Pamukkale/DENİZLİ", registry=reg)
        b, _ = UyapRedactor.redact_text("Çamlık Mevkii Kavak Sitesi B Blok D:4 DENİZLİ", registry=reg)
        self.assertEqual(a, "[ADRES_1] (Pamukkale/Denizli)")
        self.assertEqual(b, "[ADRES_1] (Denizli)")

        reg2 = MaskRegistry()
        c, _ = UyapRedactor.redact_text("Kurtuluş Mh. Atatürk Cd. No:15 İzmir", registry=reg2)
        d, _ = UyapRedactor.redact_text("Kurtuluş Mh. Atatürk Cd. Nu:15 İzmir", registry=reg2)
        self.assertEqual(c, "[ADRES_1] (İzmir)")
        self.assertEqual(d, "[ADRES_1] (İzmir)")


class TestAdresIlIlceIpucu(unittest.TestCase):
    """Adres etiketlerinin dışına eklenen ilçe/il ipucu ve kenar durumları (sentetik veri)."""

    def test_il_listesi_81_il(self):
        self.assertEqual(len(UyapRedactor._IL_ADLARI), 81)
        self.assertEqual(len(set(UyapRedactor._IL_ADLARI)), 81)

    def test_bitti_olcutu_tablosu(self):
        reg1 = MaskRegistry()
        out1, _ = UyapRedactor.redact_text(
            "Adres: Caferağa Mah. Moda Cad. No:12 D:3 Kadıköy/İstanbul Tel: 0532 111 22 33",
            registry=reg1,
        )
        self.assertEqual(out1, "Adres: [ADRES_1] (Kadıköy/İstanbul) Tel: [TEL_1]")

        out2, _ = UyapRedactor.redact_text(
            "Tebligat adresi: Caferağa Mahallesi Moda Caddesi No 12 Daire 3 KADIKÖY İSTANBUL",
            registry=reg1,
        )
        self.assertEqual(out2, "Tebligat adresi: [ADRES_1] (Kadıköy/İstanbul)")

        cases = [
            (
                "İkametgah Adresi: Güneyyayla Köyü No:14 Akseki / ANTALYA",
                "İkametgah Adresi: [ADRES_1] (Akseki/Antalya)",
            ),
            (
                "Adres: Ankara Caddesi No:5 Daire:2",
                "Adres: [ADRES_1]",
            ),
            (
                "Adres: Atatürk Mah. 1234 Sok. No:5 D:2 Bornova İzmir",
                "Adres: [ADRES_1] (Bornova/İzmir)",
            ),
            (
                "Adres: Cumhuriyet Mah. Lale Sok. No:7 Şanlıurfa",
                "Adres: [ADRES_1] (Şanlıurfa)",
            ),
        ]
        for raw, expected in cases:
            out, _ = UyapRedactor.redact_text(raw, registry=MaskRegistry())
            self.assertEqual(out, expected, raw)

    def test_registrysiz_cagri_eski_etiketi_korur(self):
        out, _ = UyapRedactor.redact_text(
            "Adres: Caferağa Mah. Moda Cad. No:12 D:3 Kadıköy/İstanbul"
        )
        self.assertEqual(out, "Adres: [ADRES_GİZLENDİ]")
        self.assertNotIn("Kadıköy", out)
        self.assertNotIn("İstanbul", out)

    def test_kurum_adresi_aynen_kalir(self):
        inst = "Türkiye İş Bankası A.Ş. Kadıköy Şubesi, Söğütlüçeşme Cad. No:10 Kadıköy/İstanbul"
        out, _ = UyapRedactor.redact_text(inst, registry=MaskRegistry())
        self.assertEqual(out, inst)

    def test_ipuculu_ve_ipucusuz_ayni_numarayi_alir(self):
        reg = MaskRegistry()
        a, _ = UyapRedactor.redact_text(
            "Adres: Caferağa Mah. Moda Cad. No:12 D:3 Kadıköy/İstanbul", registry=reg
        )
        b, _ = UyapRedactor.redact_text(
            "Tebligat adresi: Caferağa Mahallesi Moda Caddesi No 12 Daire 3", registry=reg
        )
        self.assertEqual(a, "[ADRES_1] (Kadıköy/İstanbul)".replace("[ADRES_1]", "Adres: [ADRES_1]"))
        self.assertEqual(b, "Tebligat adresi: [ADRES_1]")
        self.assertEqual(reg.distinct("adres"), 1)
        self.assertEqual(reg.occurrences["adres"], 2)

    def test_koy_mahalle_sokak_kapi_no_ciktiya_girmez(self):
        raw = "İkametgah Adresi: Güneyyayla Köyü Çiçek Mah. Lale Sok. No:14 D:3 Akseki / ANTALYA"
        out, _ = UyapRedactor.redact_text(raw, registry=MaskRegistry())
        for forbidden in ("Güneyyayla", "Köyü", "Çiçek", "Mah", "Lale", "Sok", "No:14", "14", "D:3"):
            self.assertNotIn(forbidden, out)
        self.assertIn("(Akseki/Antalya)", out)

    def test_cok_satirli_adres_il_ilce_tam_bir_kez_gorunur(self):
        raw1 = "Adres: Caferağa Mah. Moda Cad. No:12\nKadıköy/İstanbul"
        out1, _ = UyapRedactor.redact_text(raw1, registry=MaskRegistry())
        self.assertEqual(out1.count("Kadıköy/İstanbul"), 1, out1)

        raw2 = "Caferağa Mah. Moda Cad. No:12\nK:2 D:3\nKadıköy/İstanbul"
        out2, _ = UyapRedactor.redact_text(raw2, registry=MaskRegistry())
        self.assertEqual(out2.count("Kadıköy/İstanbul"), 1, out2)

    def test_ilcesi_ili_merkez_ve_eski_il_adlari(self):
        self.assertEqual(
            UyapRedactor._address_locality("Güneyyayla Köyü No:14 Akseki İlçesi Antalya İli"),
            "Akseki/Antalya",
        )
        self.assertEqual(
            UyapRedactor._address_locality("Cumhuriyet Mah. No:5 Merkez/Burdur"),
            "Merkez/Burdur",
        )
        self.assertEqual(
            UyapRedactor._address_locality("Atatürk Mah. No:5 Afyon"),
            "Afyonkarahisar",
        )
        self.assertEqual(
            UyapRedactor._address_locality("Atatürk Mah. No:5 İçel"),
            "Mersin",
        )
        self.assertEqual(
            UyapRedactor._address_locality("Atatürk Mah. No:5 İzmit/Kocaeli"),
            "Kocaeli",
        )

    def test_cift_yazim_onlenir_ve_devam_satirlari_ipucuyu_bozmaz(self):
        reg = MaskRegistry()
        dup_out, _ = UyapRedactor.redact_text(
            "Adres: Caferağa Mah. Moda Cad. No:12 Kadıköy/İstanbul, Kadıköy/İstanbul",
            registry=reg,
        )
        self.assertEqual(dup_out.count("Kadıköy/İstanbul"), 1, dup_out)

        cont_in = (
            "Yakalama Adresi: Lale Mah. Gül Sk. No:12 Kadıköy/İstanbul\n"
            "İç Kapı No: 2 Kadıköy / İstanbul Tel: 0216 333 44 55"
        )
        cont_out, stats = UyapRedactor.redact_text(cont_in, registry=MaskRegistry())
        self.assertEqual(cont_out.count("[ADRES_1]"), 2, cont_out)
        self.assertNotIn("[ADRES_2]", cont_out)
        self.assertIn("[ADRES_1] (Kadıköy/İstanbul)", cont_out)
        self.assertNotIn("İç Kapı No", cont_out)
        self.assertEqual(stats["adres"], 2)


class TestKapsamSozlesmesi(unittest.TestCase):
    """Sentetik dava dilekçesi üzerinden 'maskelenenler / korunanlar' kapsam sözleşmesi."""

    # Algoritmik olarak geçerli ama tamamen uydurma TCKN'ler
    TCKN_DAVACI = "10000000146"
    TCKN_TANIK = "20000000114"

    DAVA_DILEKCESI = (
        "T.C.\n"
        "İSTANBUL ANADOLU 5. ASLİYE HUKUK MAHKEMESİNE\n"
        "ESAS NO: 2024/623 E.\n"
        "KARAR NO: 2024/815 K.\n"
        "\n"
        "DAVACI : Ali Kaya\n"
        "T.C. Kimlik No : 10000000146\n"
        "Anne Adı: Emine  Baba Adı: Hüseyin  Doğum Tarihi: 14.05.1985\n"
        "Adres : Caferağa Mah. Moda Cad. No:12 D:3 Kadıköy/İstanbul\n"
        "Cep Tel : 0532 410 22 33\n"
        "\n"
        "VEKİLİ : Av. Zeynep Aksoy\n"
        "İstanbul Barosu Sicil No: 49812\n"
        "E-posta: ornek.avukat@example.com\n"
        "Sabit Tel: 0212 234 56 78\n"
        "\n"
        "DAVALI : Örnek Lojistik Ticaret A.Ş.\n"
        "VKN: 1234567890  Mersis No: 0123456789012345\n"
        "KEP Adresi: sirket@hs01.kep.tr\n"
        "\n"
        "TANIK : Hasan Arslan\n"
        "Tanık T.C. Kimlik No : 20000000114\n"
        "İkametgah Adresi: Bahçelievler Mah. 120 Sok. No:8 D:1 Çankaya/Ankara\n"
        "Tanık GSM: +90 544 520 33 44\n"
        "\n"
        "KONU : Haksız fiil nedeniyle 125.000,00 TL maddi tazminat istemidir.\n"
        "\n"
        "AÇIKLAMALAR :\n"
        "1. 12.03.2024 tarihinde saat 14:30 sıralarında davacı Ali Kaya sevk ve idaresindeki 34 ABC 123 plakalı araç seyir halindeyken,\n"
        "Olay Yeri: Barbaros Bulvarı No:40 Beşiktaş/İstanbul önünde meydana gelmiştir.\n"
        "2. Davacı Ali Kaya (TCKN: 10000000146) tarafından yapılan ödeme aşağıdaki hesaba gönderilmiştir:\n"
        "Ödeme IBAN: TR330006100511123456789012\n"
        "3. Kurum kayıtları ve banka şube yazıları dosyadadır:\n"
        "İstanbul Anadolu Adliyesi, Kartal Mah. E-5 Cad. No:10 Kartal/İstanbul\n"
        "Türkiye İş Bankası A.Ş. Kadıköy Şubesi, Söğütlüçeşme Cad. No:10 Kadıköy/İstanbul\n"
        "\n"
        "HUKUKİ SEBEPLER : TBK m. 49, 6100 sayılı HMK m. 107 ve ilgili mevzuat.\n"
        "SONUÇ VE İSTEM : Yukarıda açıklanan nedenlerle 125.000,00 TL alacağın tahsiline karar verilmesini arz ederim.\n"
        "\n"
        "Hâkim Ayşe Yılmaz (112233)\n"
        "Zabıt Kâtibi Murat Şahin (223344)\n"
    )

    def test_maskelenenler_ve_korunanlar_sozlesmesi(self):
        reg = MaskRegistry()
        out, stats = UyapRedactor.redact_text(self.DAVA_DILEKCESI, registry=reg)

        # 1. Maskelenmesi zorunlu ham değerler çıktıda geçmemeli
        must_hide = [
            self.TCKN_DAVACI,
            self.TCKN_TANIK,
            "0532 410 22 33",
            "+90 544 520 33 44",
            "TR330006100511123456789012",
            "49812",
            "112233",
            "223344",
            "Caferağa Mah.",
            "Moda Cad. No:12",
            "Bahçelievler Mah.",
            "120 Sok. No:8",
        ]
        for raw in must_hide:
            self.assertNotIn(raw, out, f"Ham değer sızdı: {raw}")

        # İlgili maske etiketleri bulunmalı
        self.assertIn("[TCKN_1]", out)
        self.assertIn("[TCKN_2]", out)
        self.assertIn("[TEL_1]", out)
        self.assertIn("[TEL_2]", out)
        self.assertIn("[IBAN_1]", out)
        self.assertIn("[SİCİL_1]", out)
        self.assertIn("[SİCİL_2]", out)
        self.assertIn("[SİCİL_3]", out)
        self.assertIn("[ADRES_1] (Kadıköy/İstanbul)", out)
        self.assertIn("[ADRES_2] (Çankaya/Ankara)", out)

        # Aynı TCKN iki yerde aynı etiketi alır; farklı kişi farklı etiket alır
        self.assertEqual(out.count("[TCKN_1]"), 2)
        self.assertEqual(out.count("[TCKN_2]"), 1)
        self.assertGreaterEqual(stats["tckn"], 3)

        # 2. Aynen korunması zorunlu değerler
        must_keep = [
            "Ali Kaya",
            "Zeynep Aksoy",
            "Hasan Arslan",
            "Ayşe Yılmaz",
            "Murat Şahin",
            "DAVACI",
            "DAVALI",
            "VEKİLİ",
            "TANIK",
            "Anne Adı: Emine",
            "Baba Adı: Hüseyin",
            "Doğum Tarihi: 14.05.1985",
            "12.03.2024 tarihinde saat 14:30 sıralarında",
            "125.000,00 TL",
            "2024/623 E.",
            "2024/815 K.",
            "TBK m. 49",
            "6100 sayılı HMK m. 107",
            "34 ABC 123",
            "Olay Yeri: Barbaros Bulvarı No:40 Beşiktaş/İstanbul önünde meydana gelmiştir.",
            "Örnek Lojistik Ticaret A.Ş.",
            "İstanbul Anadolu Adliyesi, Kartal Mah. E-5 Cad. No:10 Kartal/İstanbul",
            "Türkiye İş Bankası A.Ş. Kadıköy Şubesi, Söğütlüçeşme Cad. No:10 Kadıköy/İstanbul",
            "0212 234 56 78",
            "ornek.avukat@example.com",
            "sirket@hs01.kep.tr",
            "VKN: 1234567890",
            "Mersis No: 0123456789012345",
        ]
        for expected in must_keep:
            self.assertIn(expected, out, f"Korunması gereken veri kayboldu: {expected}")

        # 3. Maskelenmemiş satırlar girdiyle bayt bayt aynıdır
        in_lines = UyapRedactor.normalize_spaces(self.DAVA_DILEKCESI).splitlines()
        out_lines = out.splitlines()
        self.assertEqual(len(in_lines), len(out_lines))
        for src_line, dst_line in zip(in_lines, out_lines):
            if "[" not in dst_line:
                self.assertEqual(dst_line, src_line)

    def test_unvan_ad_soyad_parantezli_sicil_regresyonu(self):
        """Sözleşme testi bulgusu: 'Hâkim Ad Soyad (112233)' biçimi maskelenmeli; para/sayılı/esas korunmalı."""
        reg = MaskRegistry()
        out, _ = UyapRedactor.redact_text(
            "Hâkim Ayşe Yılmaz (112233)\n"
            "Zabıt Kâtibi Murat Şahin (223344)\n"
            "Hâkim kararı ile 150000 TL ödenmesine karar verildi.\n",
            registry=reg,
        )
        self.assertIn("Hâkim Ayşe Yılmaz ([SİCİL_1])", out)
        self.assertIn("Zabıt Kâtibi Murat Şahin ([SİCİL_2])", out)
        self.assertNotIn("112233", out)
        self.assertNotIn("223344", out)
        self.assertIn("150000 TL", out)


class TestDuzyaziCaddeAdiKorunur(unittest.TestCase):
    """Madde 4: Düzyazıdaki tekil cadde/sokak adları korunur, cümlenin kalanı yutulmaz."""

    def test_duzyazi_cadde_sokak_cumleleri_aynen_kalir(self):
        cases = [
            "Olay Atatürk Caddesi üzerindeki ofiste gerçekleşmiştir. Davalı sonra kaçmıştır.",
            "Davacı o gün Bağdat Caddesi üzerinde yürürken davalı ile karşılaşmış ve tartışmıştır.",
            "2. A. Yılmaz olay günü Ahmet Yılmaz Caddesi üzerindeki ofise gitmiş, Mehmet DEMİR'e ihtar çekmiştir. Yılmaz o gün yalnızdı; Ahmet de bunu doğrular.",
            "Kaza İnönü Bulvarı üzerinde meydana gelmiştir.",
            "Araç Cumhuriyet Caddesi ile Lale Sokak kesişiminde durmuştur. Sürücü araçtan inmiştir.",
        ]
        for s in cases:
            with self.subTest(case=s):
                out, stats = UyapRedactor.redact_text(s, registry=MaskRegistry())
                self.assertEqual(out, s)
                self.assertEqual(stats["total"], 0)

    def test_acik_adres_maskelenir_cumle_devami_korunur(self):
        s = "Davalı Atatürk Caddesi No:15 Daire:3 Bornova/İzmir adresinde oturmaktadır. Kendisine ulaşılamamıştır."
        out, _ = UyapRedactor.redact_text(s, registry=MaskRegistry())
        self.assertEqual(
            out,
            "Davalı [ADRES_1] (Bornova/İzmir) adresinde oturmaktadır. Kendisine ulaşılamamıştır.",
        )


class TestKisiKesfi(unittest.TestCase):
    """Madde 2 & 5: Kişi keşfi kalıpları (A-E), negatif kurallar ve D/D2 rol sınırı."""

    def test_disk_esleme_ve_geri_cevirme_api_yok(self):
        self.assertFalse(hasattr(UyapRedactor, "restore_names"))
        self.assertFalse(hasattr(UyapRedactor, "restore_names_in_file"))
        self.assertFalse(hasattr(UyapRedactor, "get_esleme_dir"))
        self.assertFalse(hasattr(MaskRegistry, "export_person_map"))
        self.assertTrue(hasattr(MaskRegistry, "person_map"))

    def test_kalip_a_b_c_d_d2_e_olumlu(self):
        # Kalıp A: ROL : Ad Soyad
        reg_a = MaskRegistry()
        UyapRedactor.collect_persons_from_text("DAVACI : Ahmet Yılmaz\nMÜŞTEKİ : Elif Şahin\n", reg_a)
        reg_a.freeze_persons()
        self.assertEqual(reg_a.person_map(), {"[DAVACI_1]": "Ahmet Yılmaz", "[MÜŞTEKİ_1]": "Elif Şahin"})

        # Kalıp B: Başlık altı Adı Soyadı
        reg_b = MaskRegistry()
        UyapRedactor.collect_persons_from_text("## TANIK\nAdı Soyadı : Kemal Aydın\n", reg_b)
        reg_b.freeze_persons()
        self.assertEqual(reg_b.person_map(), {"[TANIK_1]": "Kemal Aydın"})

        # Kalıp C: Düzyazı sıfat + Ad Soyad
        reg_c = MaskRegistry()
        UyapRedactor.collect_persons_from_text("Duruşmada tanık sıfatıyla Mehmet Can Öztürk dinlendi.\n", reg_c)
        reg_c.freeze_persons()
        self.assertEqual(reg_c.person_map(), {"[TANIK_1]": "Mehmet Can Öztürk"})

        # Kalıp D: Tek başına başlık olmadan Adı Soyadı -> [KİŞİ_1]
        reg_d = MaskRegistry()
        UyapRedactor.collect_persons_from_text("Adı Soyadı : Zeynep Aksoy\n", reg_d)
        reg_d.freeze_persons()
        self.assertEqual(reg_d.person_map(), {"[KİŞİ_1]": "Zeynep Aksoy"})

        # Kalıp D2: Tek başına rol başlığı + hemen altındaki imza sahibi adı
        reg_d2 = MaskRegistry()
        UyapRedactor.collect_persons_from_text("ŞÜPHELİ\nHasan Hüseyin Kaya\n", reg_d2)
        reg_d2.freeze_persons()
        self.assertEqual(reg_d2.person_map(), {"[ŞÜPHELİ_1]": "Hasan Hüseyin Kaya"})

        # Kalıp E: JSON taraflar
        reg_e = MaskRegistry()
        UyapRedactor.collect_persons_from_json(
            {"taraflar": [{"sifat": "Katılan", "adSoyad": "Canan Yıldız"}]},
            reg_e,
        )
        reg_e.freeze_persons()
        self.assertEqual(reg_e.person_map(), {"[KATILAN_1]": "Canan Yıldız"})

    def test_d_ve_d2_onceki_satir_icerik_tasiyorsa_rol_atanmaz(self):
        """Madde 2 regresyon: önceki dolu satır başka içerik taşıyorsa rol None -> [KİŞİ_n]."""
        tutanak = (
            "DAVACI : AHMET CAN YILMAZ\n"
            "DAVALI : MEHMET DEMİR\n"
            "TANIK : FATMA ŞAHİN, Ali kızı, 1980 doğumlu\n"
            "Adı Soyadı : Kemal Aydın\n"
        )
        reg = MaskRegistry()
        UyapRedactor.collect_persons_from_text(tutanak, reg)
        reg.freeze_persons()
        pmap = reg.person_map()
        self.assertEqual(pmap.get("[KİŞİ_1]"), "Kemal Aydın")
        self.assertNotIn("[TANIK_2]", pmap)

        # Standalone başlık çeşitleri (boş satır atlanabilir, ama başka içerik olmamalı)
        for header, expected_prefix in [
            ("ŞÜPHELİ\nAdı Soyadı : Selim Kurt\n", "[ŞÜPHELİ_1]"),
            ("## TANIK\n\nAdı Soyadı : Selim Kurt\n", "[TANIK_1]"),
            ("MÜŞTEKİ:\nAdı Soyadı : Selim Kurt\n", "[MÜŞTEKİ_1]"),
        ]:
            with self.subTest(header=header):
                r2 = MaskRegistry()
                UyapRedactor.collect_persons_from_text(header, r2)
                r2.freeze_persons()
                self.assertEqual(r2.person_map(), {expected_prefix: "Selim Kurt"})

    def test_olumsuz_ornekler_kesinlikle_kaydedilmez(self):
        plan_ve_ek_negatifler = [
            "DAVACI : Örnek İnşaat Ltd. Şti.",
            "DAVALI : Maliye Hazinesi",
            "VEKİLİ : Av. Ayşe Kaya",
            "Bilirkişi Ali Veli",
            "DAVALI : Türkiye İş Bankası A.Ş.",
            "KONU : Alacak Davası",
            "davacı vekili Av. Can Öz",
            "tanık olarak dinlenen",
            "Davacı Tarafından sunulan Dava Dilekçesi",
            "Davalı Banka Genel Müdürlüğü",
            "Tanık Olarak dinlenen",
            "Sanık Sıfatıyla ifadesi alınan",
        ]
        for line in plan_ve_ek_negatifler:
            with self.subTest(line=line):
                reg = MaskRegistry()
                UyapRedactor.collect_persons_from_text(line + "\n", reg)
                reg.freeze_persons()
                self.assertFalse(reg.has_persons(), f"Negatif satırdan kişi üretildi: {line!r} -> {reg.person_map()}")
        # Hâkim adı + sicil artık yargı rolü olarak kaydedilir
        reg_j = MaskRegistry()
        UyapRedactor.collect_persons_from_text("Hâkim Mehmet Demir 112233\n", reg_j)
        reg_j.freeze_persons()
        self.assertEqual(reg_j.person_map(), {"[HAKİM_1]": "Mehmet Demir"})

    def test_rol_cogunlugu_tiebreak_ve_freeze(self):
        reg = MaskRegistry()
        reg.add_person("Ahmet Yılmaz", "DAVACI")
        reg.add_person("AHMET YILMAZ", "TANIK")
        reg.add_person("Ahmet Yilmaz", "TANIK")

        reg.add_person("Ayşe Demir", "DAVALI")
        reg.add_person("Ayşe Demir", "DAVACI")

        reg.label("tckn", "10000000146")
        reg.freeze_persons()
        reg.add_person("Sonradan Gelen", "DAVACI")

        self.assertEqual(reg.person_map(), {"[TANIK_1]": "Ahmet Yılmaz", "[DAVACI_1]": "Ayşe Demir"})
        self.assertIsNone(reg.person_label(reg.person_key("Sonradan Gelen")))


class TestKisiMaskeleme(unittest.TestCase):
    """Madde 3 & 5: Türkçe ek, büyük harf, aksansız, ters sıra, baş harf, orta ad ve negatif maskeleme kuralları."""

    def _reg_with(self, *pairs):
        reg = MaskRegistry()
        for name, role in pairs:
            reg.add_person(name, role)
        reg.freeze_persons()
        return reg

    def test_ek_tumu_buyuk_aksansiz_ters_bas_harf_orta_ad(self):
        reg = self._reg_with(("Ahmet Can Yılmaz", "DAVACI"))
        text = (
            "Ahmet Can Yılmaz'ın talebiyle,\n"
            "AHMET CAN YILMAZ'a soru soruldu.\n"
            "Ahmet Yilmaz’nin beyanı ile Ahmet Yılmaz ve Yılmaz Ahmet ve A. Yılmaz tutanağa geçti.\n"
        )
        out, _ = UyapRedactor.redact_text(text, registry=reg)
        self.assertIn("[DAVACI_1]'ın talebiyle,", out)
        self.assertIn("[DAVACI_1]'a soru soruldu.", out)
        self.assertIn("[DAVACI_1]’nin beyanı", out)
        self.assertEqual(out.count("[DAVACI_1]"), 6)

    def test_negatif_maskeleme_kucuk_tekil_cadde_sirket_etiket_ici(self):
        reg = self._reg_with(("Ahmet Yılmaz", "DAVACI"))
        text = (
            "ahmet yılmaz küçük harfle eşleşmez.\n"
            "Ahmet bugün yalnız geldi, Yılmaz da doğruladı.\n"
            "Ahmet Yılmaz Caddesi ve Ahmet Yılmaz İnşaat Ltd. Şti. korunur.\n"
            "[ADRES_1] (Ahmet Yılmaz/İzmir) ve [DAVACI_1] etiketi bozulmaz.\n"
        )
        out, _ = UyapRedactor.redact_text(text, registry=reg)
        self.assertEqual(out, text)

    def test_belirsiz_bas_harf_maskelenmez(self):
        reg = self._reg_with(("Ahmet Yılmaz", "DAVACI"), ("Ali Yılmaz", "DAVALI"))
        text = "A. Yılmaz duruşmada hazır, Ahmet Yılmaz ile Ali Yılmaz dinlendi."
        out, _ = UyapRedactor.redact_text(text, registry=reg)
        self.assertIn("A. Yılmaz", out)
        self.assertIn("[DAVACI_1]", out)
        self.assertIn("[DAVALI_1]", out)


class TestKisiUctanUca(unittest.TestCase):
    """Madde 1 & 5: İki .md + uyap-project.json + dosya adı/link senkronu, ekran listesi, sıfır disk sızıntısı."""

    def test_end_to_end_mask_names_true_and_false_zero_disk_mapping(self):
        import io
        import json
        import shutil
        from contextlib import redirect_stdout
        from urllib.parse import unquote
        from uyap_redactor import main as cli_main

        tmp = tempfile.mkdtemp(prefix="uyap_e2e_kisi_")
        src = os.path.join(tmp, "ornek_dava")
        dest1 = os.path.join(tmp, "out_masked")
        dest2 = os.path.join(tmp, "out_preserved")
        try:
            os.makedirs(src, exist_ok=True)
            with open(os.path.join(src, "Ahmet Yılmaz Dilekçe.md"), "w", encoding="utf-8") as f:
                f.write(
                    "DAVACI : Ahmet Yılmaz\n"
                    "VEKİLİ : Av. Ayşe Kaya\n"
                    "DAVALI : Örnek İnşaat Ltd. Şti.\n"
                    "TCKN: 10000000146\n"
                    "Adres: Caferağa Mah. Moda Cad. No:12 Kadıköy/İstanbul\n"
                    "Ahmet Yılmaz'ın 125.000,00 TL alacağının tahsili talep edilmiştir.\n"
                    "Hâkim Mehmet Demir (112233) huzurunda.\n"
                )
            with open(os.path.join(src, "tutanak.md"), "w", encoding="utf-8") as f:
                f.write(
                    "Tanık Fatma Çelik yeminli dinlendi.\n"
                    "Davacı A. Yılmaz duruşmada hazır, AHMET YILMAZ'a soru soruldu.\n"
                    "Tanık Fatma Çelik'in beyanı tutanağa geçti.\n"
                )
            with open(os.path.join(src, "INDEX.md"), "w", encoding="utf-8") as f:
                f.write("# Dizin\n- [Ahmet Yılmaz Dilekçesi](Ahmet%20Y%C4%B1lmaz%20Dilek%C3%A7e.md)\n- [Tutanak](tutanak.md)\n")
            with open(os.path.join(src, "uyap-project.json"), "w", encoding="utf-8") as f:
                json.dump({"taraflar": [{"sifat": "Tanık", "adSoyad": "Fatma Çelik"}]}, f, ensure_ascii=False)

            before_tmp = set(os.listdir(tmp))
            # Yeni varsayılan: taraf + tanık + yargı personeli maskeli; avukat/bilirkişi açık
            out1, stats1 = UyapRedactor.export_isolated_clean_folder(src, dest1)
            after_tmp = set(os.listdir(tmp))
            # Kaynak ve hedef dışında yeni dosya/klasör oluşturulmamalı
            self.assertEqual(after_tmp - before_tmp, {"out_masked"})
            self.assertNotIn("esleme_dosyasi", stats1)
            self.assertEqual(stats1["kisi_sayisi"], 3)
            self.assertEqual(
                set(stats1["kisi_listesi"]),
                {("[DAVACI_1]", "Ahmet Yılmaz"), ("[TANIK_1]", "Fatma Çelik"), ("[HAKİM_1]", "Mehmet Demir")},
            )

            # Çıktı dosya adları ve INDEX.md bağlantısı
            out_files = []
            for root_d, _dirs, fns in os.walk(out1):
                for fn in fns:
                    rel = os.path.relpath(os.path.join(root_d, fn), out1)
                    out_files.append(rel)
                    self.assertNotIn("Ahmet", rel)
                    self.assertNotIn("Yılmaz", rel)
                    self.assertNotIn("Fatma", rel)
                    with open(os.path.join(root_d, fn), "r", encoding="utf-8") as rf:
                        content = rf.read()
                    for raw in ("Ahmet Yılmaz", "AHMET YILMAZ", "Fatma Çelik", "Mehmet Demir"):
                        self.assertNotIn(raw, content, f"{rel} içinde ham ad-soyad sızıntısı: {raw}")
            with open(os.path.join(out1, "[DAVACI_1] Dilekçe.md"), "r", encoding="utf-8") as rf:
                self.assertIn("Av. Ayşe Kaya", rf.read())

            self.assertIn("[DAVACI_1] Dilekçe.md", out_files)
            with open(os.path.join(out1, "INDEX.md"), "r", encoding="utf-8") as f:
                idx = f.read()
            m = re.search(r'\(<?([^)>\n]+Dilek[^>)\n]+\.md)>?\)', idx)
            self.assertIsNotNone(m)
            self.assertTrue(os.path.exists(os.path.join(out1, unquote(m.group(1)))))

            # Rapor metni eşleme dosyasının hiçbir yere yazılmadığını belirtir
            with open(os.path.join(out1, "DAVA_DÖNÜŞÜM_VE_GÜVENLİK_RAPORU.md"), "r", encoding="utf-8") as f:
                rapor = f.read()
            self.assertIn("hiçbir yere yazılmadı", rapor)

            # CLI varsayılan (bayraksız) kişi listesini gösterir, diske yazmaz
            dest_cli = os.path.join(tmp, "out_cli")
            old_argv = sys.argv
            try:
                sys.argv = ["uyap_redactor.py", src, "--out", dest_cli]
                buf = io.StringIO()
                with redirect_stdout(buf):
                    cli_main()
                cli_out = buf.getvalue()
                self.assertIn("👤 KİŞİ ETİKETLERİ (yalnızca bu ekranda gösterilir, hiçbir dosyaya kaydedilmez)", cli_out)
                self.assertIn("[DAVACI_1] = Ahmet Yılmaz", cli_out)
                self.assertIn("[TANIK_1] = Fatma Çelik", cli_out)
                self.assertIn("[HAKİM_1] = Mehmet Demir", cli_out)

                # CLI --taraf-isimlerini-koru: taraf açık, yargı yine maskeli
                dest_cli_koru = os.path.join(tmp, "out_cli_koru")
                sys.argv = ["uyap_redactor.py", src, "--out", dest_cli_koru, "--taraf-isimlerini-koru"]
                buf_k = io.StringIO()
                with redirect_stdout(buf_k):
                    cli_main()
                self.assertTrue(os.path.isfile(os.path.join(dest_cli_koru, "Ahmet Yılmaz Dilekçe.md")))
                txt_koru = open(os.path.join(dest_cli_koru, "Ahmet Yılmaz Dilekçe.md"), encoding="utf-8").read()
                self.assertIn("Ahmet Yılmaz", txt_koru)
                self.assertIn("[HAKİM_1]", txt_koru)
                self.assertNotIn("Mehmet Demir", txt_koru)

                # CLI geriye uyumlu --isimleri-koru: --taraf-isimlerini-koru ile aynı (taraf açık, yargı maskeli)
                dest_cli_old_koru = os.path.join(tmp, "out_cli_old_koru")
                sys.argv = ["uyap_redactor.py", src, "--out", dest_cli_old_koru, "--isimleri-koru"]
                with redirect_stdout(io.StringIO()):
                    cli_main()
                txt_old_koru = open(os.path.join(dest_cli_old_koru, "Ahmet Yılmaz Dilekçe.md"), encoding="utf-8").read()
                self.assertIn("Ahmet Yılmaz", txt_old_koru)
                self.assertIn("[HAKİM_1]", txt_old_koru)
                self.assertNotIn("Mehmet Demir", txt_old_koru)

                # CLI geriye uyumlu etkisiz --taraf-isimlerini-maskele: varsayılanla aynı
                dest_cli_noop = os.path.join(tmp, "out_cli_noop")
                sys.argv = ["uyap_redactor.py", src, "--out", dest_cli_noop, "--taraf-isimlerini-maskele"]
                with redirect_stdout(io.StringIO()):
                    cli_main()
                self.assertTrue(os.path.isfile(os.path.join(dest_cli_noop, "[DAVACI_1] Dilekçe.md")))
            finally:
                sys.argv = old_argv

            # mask_names=False (taraf isimlerini koru, yargı maskelemesi açık): yalnızca Hâkim Mehmet Demir maskelenir
            out2, stats2 = UyapRedactor.export_isolated_clean_folder(src, dest2, mask_names=False)
            self.assertEqual(stats2.get("kisi_sayisi", 0), 1)
            self.assertEqual(stats2.get("kisi_listesi"), [("[HAKİM_1]", "Mehmet Demir")])
            self.assertTrue(os.path.isfile(os.path.join(out2, "Ahmet Yılmaz Dilekçe.md")))
            with open(os.path.join(out2, "Ahmet Yılmaz Dilekçe.md"), "r", encoding="utf-8") as f:
                d_pres = f.read()
            self.assertIn("Ahmet Yılmaz", d_pres)
            self.assertIn("[TCKN_1]", d_pres)
            self.assertIn("[HAKİM_1]", d_pres)
            self.assertNotIn("Mehmet Demir", d_pres)

            # mask_names=False ve mask_judicial_names=False: hiçbir ad maskelenmez
            dest3 = os.path.join(tmp, "out_all_open")
            out3, stats3 = UyapRedactor.export_isolated_clean_folder(
                src, dest3, mask_names=False, mask_judicial_names=False
            )
            self.assertEqual(stats3.get("kisi_sayisi", 0), 0)
            self.assertEqual(stats3.get("kisi_listesi"), [])
            with open(os.path.join(out3, "Ahmet Yılmaz Dilekçe.md"), "r", encoding="utf-8") as f:
                d_all_open = f.read()
            self.assertIn("Ahmet Yılmaz", d_all_open)
            self.assertIn("Mehmet Demir", d_all_open)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestSenaryoBulgulari2(unittest.TestCase):
    """Sentetik senaryolarda tespit edilen 6 kök bulgunun odaklanmış regresyon testleri."""

    def test_bulgu_1_yol_ve_baglanti_ayiricili_adlar(self):
        reg = MaskRegistry()
        reg.add_person("Elif Demir", "TANIK")
        reg.add_person("Volkan Tekin", "ŞÜPHELİ")
        reg.add_person("Turgut Yılmaz", "ŞÜPHELİ")
        reg.freeze_persons()

        self.assertEqual(
            UyapRedactor.redact_path_segment("Tanik_Elif_Demir_Beyan.md", registry=reg, is_file=True),
            "Tanik_[TANIK_1]_Beyan.md",
        )
        self.assertEqual(
            UyapRedactor.redact_path_segment("Volkan-Tekin ifade.md", registry=reg, is_file=True),
            "[ŞÜPHELİ_1] ifade.md",
        )
        self.assertEqual(
            UyapRedactor.redact_path_segment("Elif.Demir.pdf", registry=reg, is_file=True),
            "[TANIK_1].pdf",
        )
        self.assertEqual(
            UyapRedactor.redact_path_segment("Supheli_Turgut_Yilmaz_Ifade.md", registry=reg, is_file=True),
            "Supheli_[ŞÜPHELİ_2]_Ifade.md",
        )

        # Markdown bağlantı hedefi maskelenirken düz metindeki Elif_Demir korunmalı (yalnız yol/bağlantı kuralı)
        md_in = "Düz metinde Elif_Demir geçer. Bkz: [Beyan](Ekler/Tanik_Elif_Demir_Beyan.md) ve [İfade](Volkan-Tekin%20ifade.md).\n"
        md_out, _ = UyapRedactor.redact_text(md_in, registry=reg)
        self.assertIn("Düz metinde Elif_Demir geçer.", md_out)
        self.assertIn("[Beyan](Ekler/Tanik_[TANIK_1]_Beyan.md)", md_out)
        self.assertIn("[İfade](<[ŞÜPHELİ_1] ifade.md>)", md_out)

    def test_bulgu_2_noktalamali_hesap_no_ve_tutar_korumasi(self):
        tmp = tempfile.mkdtemp(prefix="uyap_bulgu2_")
        src = os.path.join(tmp, "in")
        dest = os.path.join(tmp, "out")
        try:
            os.makedirs(src, exist_ok=True)
            with open(os.path.join(src, "01_dekont.md"), "w", encoding="utf-8") as f:
                f.write("Gönderen (Hesap No: 77192038, tutar: 1.250,00 TL).\n")
            with open(os.path.join(src, "02_ifade.md"), "w", encoding="utf-8") as f:
                f.write(
                    "Ben de 77192038 hesap numarasına gönderdim.\n"
                    "Tutar: Hesap No: 12500,00 TL, Hesap No: 1.250,00 TL, Hesap No: 20245/623.\n"
                )
            out_dir, _ = UyapRedactor.export_isolated_clean_folder(src, dest)
            out1 = open(os.path.join(out_dir, "01_dekont.md"), encoding="utf-8").read()
            out2 = open(os.path.join(out_dir, "02_ifade.md"), encoding="utf-8").read()
            self.assertNotIn("77192038", out1)
            self.assertNotIn("77192038", out2)
            self.assertIn("[HESAP_1],", out1)
            self.assertIn("[HESAP_1] hesap", out2)
            self.assertIn("12500,00 TL", out2)
            self.assertIn("1.250,00 TL", out2)
            self.assertIn("20245/623", out2)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_bulgu_3_satir_sonu_sirket_ve_klasor_ici_guvenlik_agi(self):
        reg = MaskRegistry()
        UyapRedactor.collect_persons_from_text(
            "1. Davacı Ömer Akın tarafından davalı Bosphorus Metal\n"
            "İthalat İhracat Ltd. Şti. aleyhine açılan davada.\n",
            reg,
        )
        reg.freeze_persons()
        self.assertNotIn("Bosphorus Metal", reg.person_map().values())

        # Klasör içi güvenlik ağı: 01'de tek başına, 02'de Ltd. Şti. ile geçse bile çıkarılmalı
        tmp = tempfile.mkdtemp(prefix="uyap_bulgu3_")
        src = os.path.join(tmp, "in")
        dest = os.path.join(tmp, "out")
        try:
            os.makedirs(src, exist_ok=True)
            with open(os.path.join(src, "01.md"), "w", encoding="utf-8") as f:
                f.write("**DAVACI:** Caner Aydın\ndavalı Kuzey Metal aleyhine talep.\n")
            with open(os.path.join(src, "02.md"), "w", encoding="utf-8") as f:
                f.write("**DAVALI:** Kuzey Metal İthalat İhracat Ltd. Şti.\n")
            out_dir, stats = UyapRedactor.export_isolated_clean_folder(src, dest)
            self.assertNotIn("Kuzey Metal", [v for _, v in stats["kisi_listesi"]])
            out2 = open(os.path.join(out_dir, "02.md"), encoding="utf-8").read()
            self.assertIn("Kuzey Metal İthalat İhracat Ltd. Şti.", out2)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_bulgu_4_sifat_hitap_yakinlik_kirpma(self):
        reg = MaskRegistry()
        sample = (
            "**KONU:** Muris İsmet Karabulut (TCKN: 10101010150) terekesi\n"
            "Kiraya Veren Ali Kaya (TCKN: 20202020200)\n"
            "İşveren vekili Murat Demir (TCKN: 30303030350)\n"
            "Küçük Emir Can (TCKN: 40404040400)\n"
            "Eşi Fatma Karabulut (TCKN: 50505050550)\n"
            "İsmet Karabulut'un mirasçıları hazır.\n"
        )
        UyapRedactor.collect_persons_from_text(sample, reg)
        reg.freeze_persons()
        vals = set(reg.person_map().values())
        self.assertEqual(
            vals,
            {"İsmet Karabulut", "Ali Kaya", "Murat Demir", "Emir Can", "Fatma Karabulut"},
        )
        out, _ = UyapRedactor.redact_text("Muris İsmet Karabulut ile İsmet Karabulut aynı kişidir.", registry=reg)
        self.assertEqual(out.count("[KİŞİ_1]"), 2)

    def test_bulgu_5_uc_dort_belirtecli_soyad_basta(self):
        # Normal sıra -> sonra SOYAD Ad1 Ad2
        reg1 = MaskRegistry()
        reg1.add_person("Fatma Zehra Korkmaz", "DAVALI")
        reg1.add_person("KORKMAZ Fatma Zehra", None)
        reg1.add_person("Zeynep Ela Nur Yıldız", "TANIK")
        reg1.add_person("YILDIZ Zeynep Ela Nur", None)
        reg1.freeze_persons()
        self.assertEqual(reg1.person_map(), {"[DAVALI_1]": "Fatma Zehra Korkmaz", "[TANIK_1]": "Zeynep Ela Nur Yıldız"})
        out1, _ = UyapRedactor.redact_text(
            "KORKMAZ Fatma Zehra ile Fatma Zehra Korkmaz ve YILDIZ Zeynep Ela Nur hazır; "
            "ancak rastgele Zeynep Nur Ela Yıldız eşleşmez.",
            registry=reg1,
        )
        self.assertEqual(out1.count("[DAVALI_1]"), 2)
        self.assertEqual(out1.count("[TANIK_1]"), 1)
        self.assertIn("Zeynep Nur Ela Yıldız", out1)

        # Önce SOYAD Ad1 Ad2 -> sonra normal sıra
        reg2 = MaskRegistry()
        reg2.add_person("KORKMAZ Fatma Zehra", None)
        reg2.add_person("Fatma Zehra Korkmaz", "DAVALI")
        reg2.freeze_persons()
        self.assertEqual(reg2.person_map(), {"[DAVALI_1]": "Fatma Zehra Korkmaz"})

    def test_bulgu_6_bilesik_parantezli_baslik_ve_buyuk_harfli_rol(self):
        reg = MaskRegistry()
        text = (
            "## DAVALI SAVUNMA LAYİHASI\n"
            "## TANIK VE DELİL NOTU\n"
            "**BAŞVURAN / DAVACI:** Caner Başaran (TCKN: 17392846550)\n"
            "- **Alıcı (Davacı):** Caner Başaran\n"
            "**DAVACI (TÜKETİCİ):** Caner Başaran\n"
            "**DAVALI/BORÇLU :** Deniz Arslan (TCKN: 20948172600)\n"
            "Davacı Caner Başaran'ın talebiyle; Davacı Tarafından sunulan Dava Dilekçesi, "
            "Davalı Banka, Tanık Olarak dinlenen, Sanık Sıfatıyla ve Davacı Vekili Av. Mehmet Öz.\n"
        )
        UyapRedactor.collect_persons_from_text(text, reg)
        reg.freeze_persons()
        self.assertEqual(reg.person_map(), {"[DAVACI_1]": "Caner Başaran", "[DAVALI_1]": "Deniz Arslan"})

    def test_gerileme_a_guclu_kanit_sirket_cakismasi(self):
        tmp = tempfile.mkdtemp(prefix="uyap_reg_a_")
        src = os.path.join(tmp, "in")
        dest = os.path.join(tmp, "out")
        try:
            os.makedirs(src, exist_ok=True)
            with open(os.path.join(src, "01.md"), "w", encoding="utf-8") as f:
                f.write(
                    "**DAVALILAR** : 1- Mehmet Demir (TCKN: 10000000078)\n"
                    "Tanık Fatma Şahin, Mehmet Demir İnşaat Ltd. Şti. çalışanıdır.\n"
                    "Davalı Mehmet Demir duruşmaya gelmedi; Kuzey Metal hakkında ise davacı iddiası var.\n"
                    "Olayı davalı Kuzey Metal yetkilisinin bildirdiği öne sürüldü.\n"
                )
            with open(os.path.join(src, "02.md"), "w", encoding="utf-8") as f:
                f.write("**DAVALI:** Kuzey Metal İthalat İhracat Ltd. Şti.\n")
            out_dir, stats = UyapRedactor.export_isolated_clean_folder(src, dest)
            person_vals = {v for _, v in stats["kisi_listesi"]}
            self.assertIn("Mehmet Demir", person_vals)
            self.assertIn("Fatma Şahin", person_vals)
            # Güçlü kanıtı olmayan (yalnızca B kalıbında geçen) Kuzey Metal şirket nedeniyle çıkarılmalı
            self.assertNotIn("Kuzey Metal", person_vals)
            out1 = open(os.path.join(out_dir, "01.md"), encoding="utf-8").read()
            self.assertIn("1- [DAVALI_1] (TCKN: [TCKN_1])", out1)
            self.assertIn("Mehmet Demir İnşaat Ltd. Şti.", out1)
            self.assertIn("Davalı [DAVALI_1] duruşmaya gelmedi", out1)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_gerileme_b_iki_belirtec_uc_belirtec_birlestirme(self):
        # 1. Tekil eşleşme (düz + ters sıra) -> birleşir ve A. Yılmaz kısaltması aktifleşir
        reg = MaskRegistry()
        text = (
            "**DAVACI** : Ahmet Can Yılmaz (T.C. Kimlik No: 10000000146)\n"
            "Davacı Ahmet Yılmaz talepte bulundu; Yılmaz Ahmet haklıdır.\n"
        )
        UyapRedactor.collect_persons_from_text(text, reg)
        reg.freeze_persons()
        self.assertEqual(reg.person_map(), {"[DAVACI_1]": "Ahmet Can Yılmaz"})
        out, _ = UyapRedactor.redact_names("A. Yılmaz ve AHMET YILMAZ ve Yılmaz Ahmet", registry=reg)
        self.assertEqual(out, "[DAVACI_1] ve [DAVACI_1] ve [DAVACI_1]")

        # 2. İstisna A: her ikisi C kalıbıyla FARKLI TCKN'lere bağlıysa birleşmez
        reg_diff_tckn = MaskRegistry()
        UyapRedactor.collect_persons_from_text(
            "Ahmet Can Yılmaz (TCKN: 10000000146) ve Ahmet Yılmaz (TCKN: 10000000078)\n",
            reg_diff_tckn,
        )
        reg_diff_tckn.freeze_persons()
        self.assertEqual(len(reg_diff_tckn.person_map()), 2)

        # 3. İstisna B: birden çok 3-4 belirteçli ad aynı (ilk, son) çiftini taşıyorsa birleşmez
        reg_ambig = MaskRegistry()
        UyapRedactor.collect_persons_from_text(
            "**DAVACI:** Ahmet Can Yılmaz\n"
            "**DAVALI:** Ahmet Murat Yılmaz\n"
            "Tanık Ahmet Yılmaz beyanda bulundu.\n",
            reg_ambig,
        )
        reg_ambig.freeze_persons()
        self.assertEqual(len(reg_ambig.person_map()), 3)


class TestSenaryoBulgulari3(unittest.TestCase):
    """Yeni sentetik klasör (d2) denetiminde tespit edilen 6 bulgunun odaklı regresyon testleri."""

    def test_madde_1_baglanti_hedefi_bicimleri(self):
        tmp = tempfile.mkdtemp(prefix="uyap_bulgu3_m1_")
        src = os.path.join(tmp, "in")
        dest = os.path.join(tmp, "out")
        try:
            os.makedirs(os.path.join(src, "Ekler"), exist_ok=True)
            with open(os.path.join(src, "dava.md"), "w", encoding="utf-8") as f:
                f.write(
                    "TANIK : Derya Koç\n"
                    "- [Derya Koç beyanı](Ekler/Tanik_Derya_Koc_beyani.md)\n"
                    "- [Derya Koç açılı](<Ekler/Tanik_Derya_Koc_beyani.md>)\n"
                    "- [Derya Koç kodlu](Ekler/Tanik%20Derya%20Koc%20beyani.md)\n"
                    "- [Derya Koç açılı kodlu](<Ekler/Tanik%20Derya%20Ko%C3%A7%20beyan%C4%B1.md>)\n"
                )
            with open(os.path.join(src, "Ekler", "Tanik_Derya_Koc_beyani.md"), "w", encoding="utf-8") as f:
                f.write("# Beyan 1\nTANIK : Derya Koç\n")
            with open(os.path.join(src, "Ekler", "Tanik Derya Koc beyani.md"), "w", encoding="utf-8") as f:
                f.write("# Beyan 2\nTANIK : Derya Koç\n")
            with open(os.path.join(src, "Ekler", "Tanik Derya Koç beyanı.md"), "w", encoding="utf-8") as f:
                f.write("# Beyan 3\nTANIK : Derya Koç\n")

            out_dir, _ = UyapRedactor.export_isolated_clean_folder(src, dest)
            dava_out = open(os.path.join(out_dir, "dava.md"), encoding="utf-8").read()
            self.assertNotIn("Derya", dava_out)
            self.assertNotIn("Koc", dava_out)
            self.assertNotIn("Koç", dava_out)

            targets = re.findall(r'\[[^\]]*\[TANIK_1\][^\]]*\]\(([^)]+)\)', dava_out)
            self.assertEqual(len(targets), 4)
            for raw_t in targets:
                rel_t = raw_t.strip("<>")
                self.assertIn("[TANIK_1]", rel_t)
                self.assertTrue(os.path.isfile(os.path.join(out_dir, rel_t)), f"Hedef yok: {rel_t}")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_madde_2_cocuk_ve_yakin_adlari(self):
        reg = MaskRegistry()
        sample = (
            "1. Müşterek çocuk Defne Aktaş 2018 doğumludur; müşterek çocukları Kerem Aktaş ve ortak çocuk Ela Aktaş okula gitmektedir.\n"
            "2. Çocuğu Mert Aktaş, küçük Can Aktaş, oğlu Emre Aktaş, kızı Selin Demir, eşi Burak Kaya hazır bulundu.\n"
            "3. Annesi Nermin Kaya, babası Kemal Kaya, kardeşi Arda Kaya, ağabeyi Hakan Kaya, ablası Pınar Kaya dinlendi.\n"
            "4. Torunu Ece Yılmaz, kayınvalidesi Hatice Demir, kayınpederi Rıza Demir, komşusu Tarık Şen, arkadaşı Sinan Kurt, iş arkadaşı Ozan Aydın ifade verdi.\n"
            "5. Ali Veli Kaya isimli komşu, Fatma Nur Demir isimli şahıs ve Mehmet Can Öz isimli kişi olay yerindeydi.\n"
            "6. Nüfus: FATMA ŞAHİN, Ali kızı, Hasan oğlu, 1980 doğumlu; annesi Gülten Hanım ve Av. Ayşe Kaya isimli kişi korunur.\n"
        )
        UyapRedactor.collect_persons_from_text(sample, reg)
        reg.freeze_persons()
        names = set(reg.person_map().values())
        for expected in (
            "Defne Aktaş", "Kerem Aktaş", "Ela Aktaş", "Mert Aktaş", "Can Aktaş",
            "Emre Aktaş", "Selin Demir", "Burak Kaya", "Nermin Kaya", "Kemal Kaya",
            "Arda Kaya", "Hakan Kaya", "Pınar Kaya", "Ece Yılmaz", "Hatice Demir",
            "Rıza Demir", "Tarık Şen", "Sinan Kurt", "Ozan Aydın",
            "Ali Veli Kaya", "Fatma Nur Demir", "Mehmet Can Öz",
        ):
            self.assertIn(expected, names)
        for lab in reg.person_map():
            self.assertTrue(lab.startswith("[KİŞİ_"), lab)
        self.assertNotIn("Gülten Hanım", names)
        self.assertNotIn("Ayşe Kaya", names)
        self.assertNotIn("Ali", " ".join(n.split()[0] for n in names if n == "Ali"))

    def test_madde_3_on_ad_bey_hanim(self):
        reg = MaskRegistry()
        UyapRedactor.collect_persons_from_text(
            "DAVACI : Selin Nur Aktaş\n"
            "DAVALI : Orhan Aktaş\n"
            "TANIK : Ahmet Yılmaz\n"
            "TANIK : Ahmet Demir\n",
            reg,
        )
        reg.freeze_persons()
        out, _ = UyapRedactor.redact_text(
            "Orhan Bey aylık 85.000 TL kazanır. Selin Hanım çalışmaz. "
            "Selin ağlıyordu. Gülten Hanım ve Ahmet Bey ile Av. Orhan Bey konuşmadı.",
            registry=reg,
        )
        self.assertIn("[DAVALI_1] Bey", out)
        self.assertIn("[DAVACI_1] Hanım", out)
        self.assertIn("Selin ağlıyordu.", out)
        self.assertIn("Gülten Hanım", out)
        self.assertIn("Ahmet Bey", out)
        self.assertIn("Av. Orhan Bey", out)

    def test_madde_4_baro_sicili(self):
        out, _ = UyapRedactor.redact_text(
            "VEKİLİ : Av. Burak Tuna - Ankara Barosu 23456\n"
            "Av. Ayşe Yılmaz (İstanbul Barosu No: 12345) ve İzmir Barosu - 9876\n"
            "Ankara Barosu 2024 yılı faaliyetleri, İstanbul Barosu 1. Bölge, "
            "Ankara Barosu 2024/1234 E. ve Ankara Barosu 15.01.2024 tarihli yazı.\n",
            registry=MaskRegistry(),
        )
        self.assertIn("Av. Burak Tuna - Ankara Barosu [SİCİL_1]", out)
        self.assertIn("İstanbul Barosu No: [SİCİL_2]", out)
        self.assertIn("İzmir Barosu - [SİCİL_3]", out)
        self.assertNotIn("23456", out)
        self.assertIn("Ankara Barosu 2024 yılı", out)
        self.assertIn("İstanbul Barosu 1. Bölge", out)
        self.assertIn("Ankara Barosu 2024/1234 E.", out)
        self.assertIn("Ankara Barosu 15.01.2024 tarihli", out)

    def test_madde_5_sirket_merkezi_adresi(self):
        corp_lines = (
            "Davalı, Aktaş Otomotiv Sanayi ve Ticaret Ltd. Şti. ortağıdır; şirket merkezi Ostim OSB 1234. Cad. No:8 Yenimahalle/Ankara adresindedir.\n"
            "Davacı, Yıldız Holding A.Ş. şubesi Barbaros Mah. Atatürk Cad. No:42 Ataşehir/İstanbul adresine başvurdu.\n"
            "Davalı, Demir Tekstil A.Ş. fabrikası Organize Sanayi 5. Sok. No:11 Nilüfer/Bursa adresindedir.\n"
        )
        out_corp, _ = UyapRedactor.redact_text(corp_lines, registry=MaskRegistry())
        self.assertEqual(out_corp, corp_lines)

        person_lines = (
            "Davalı, Aktaş Otomotiv Ltd. Şti. ortağıdır; davalının ikamet adresi Lale Mah. 5. Sok. No:2 Çankaya/Ankara adresindedir.\n"
        )
        out_person, _ = UyapRedactor.redact_text(person_lines, registry=MaskRegistry())
        self.assertIn("[ADRES_1]", out_person)
        self.assertNotIn("Lale Mah.", out_person)

    def test_madde_6_kisi_listesi_sirasi(self):
        reg = MaskRegistry()
        reg.add_person("Kisi Bir", None)
        reg.add_person("Tanik Bir", "TANIK")
        reg.add_person("Borclu Bir", "BORÇLU")
        reg.add_person("Alacakli Bir", "ALACAKLI")
        reg.add_person("Sanik Bir", "SANIK")
        reg.add_person("Supheli Bir", "ŞÜPHELİ")
        reg.add_person("Magdur Bir", "MAĞDUR")
        reg.add_person("Katilan Bir", "KATILAN")
        reg.add_person("Musteki Bir", "MÜŞTEKİ")
        reg.add_person("Davali Bir", "DAVALI")
        reg.add_person("Davali Iki", "DAVALI")
        reg.add_person("Davaci Bir", "DAVACI")
        reg.add_person("Davaci Iki", "DAVACI")
        reg.freeze_persons()

        self.assertEqual(
            list(reg.person_map().keys()),
            [
                "[DAVACI_1]", "[DAVACI_2]",
                "[DAVALI_1]", "[DAVALI_2]",
                "[MÜŞTEKİ_1]", "[KATILAN_1]", "[MAĞDUR_1]",
                "[ŞÜPHELİ_1]", "[SANIK_1]",
                "[ALACAKLI_1]", "[BORÇLU_1]",
                "[TANIK_1]", "[KİŞİ_1]",
            ],
        )


class TestSatirSonuBolunenAd(unittest.TestCase):
    """Adım 1: Satır sonunda tek satır sonuyla bölünen kayıtlı kişi adlarının maskelenmesi ve korumalar."""

    def _reg(self):
        reg = MaskRegistry()
        reg.add_person("Ahmet Can Yılmaz", "DAVACI")
        reg.add_person("Mehmet Demir", "DAVALI")
        reg.freeze_persons()
        return reg

    def test_satir_sonu_bolunen_ad_ve_ekler(self):
        cases = [
            ("Davacı Ahmet Can\nYılmaz'ın talebi kabul edildi.", "Davacı [DAVACI_1]'ın talebi kabul edildi."),
            ("Ahmet\nCan Yılmaz duruşmada hazır.", "[DAVACI_1] duruşmada hazır."),
            ("AHMET CAN\nYILMAZ", "[DAVACI_1]"),
            ("Ahmet  Can \n  Yılmaz'a tebliğ edildi.", "[DAVACI_1]'a tebliğ edildi."),
            ("Ahmet Can\r\nYılmaz'ın beyanı.", "[DAVACI_1]'ın beyanı."),
            ("Davalı Mehmet\nDEMİR ifade verdi.", "Davalı [DAVALI_1] ifade verdi."),
            ("DEMİR\nMehmet duruşmaya katılmadı.", "[DAVALI_1] duruşmaya katılmadı."),
        ]
        for raw, expected in cases:
            reg = self._reg()
            out, stats = UyapRedactor.redact_text(raw, registry=reg)
            self.assertEqual(out, expected, raw)
            self.assertEqual(stats["kisi"], 1, raw)
            self.assertNotIn("Yılmaz", out)
            self.assertNotIn("YILMAZ", out)
            self.assertNotIn("Demir", out)
            self.assertNotIn("DEMİR", out)

    def test_ayni_metinde_satir_ici_ve_satir_sonlu_ayni_etiket(self):
        reg = self._reg()
        text = (
            "Davacı Ahmet Can Yılmaz dilekçe verdi.\n"
            "Devamında Ahmet Can\nYılmaz'ın talebi incelendi.\n"
            "Mehmet Demir ve Mehmet\nDEMİR aynı kişidir.\n"
        )
        out, stats = UyapRedactor.redact_text(text, registry=reg)
        self.assertEqual(out.count("[DAVACI_1]"), 2)
        self.assertEqual(out.count("[DAVALI_1]"), 2)
        self.assertEqual(stats["kisi"], 4)
        self.assertNotIn("Ahmet", out)
        self.assertNotIn("Mehmet", out)

    def test_yanlis_yakalama_korumalari_aynen_kalir(self):
        reg = self._reg()
        protected_cases = [
            "Ahmet Can\n\nYılmaz",
            "Ahmet Can\n   \nYılmaz",
            "Ahmet Can\n- Yılmaz",
            "Ahmet Can\n## Yılmaz",
            "| Ahmet Can |\n| Yılmaz |",
            "Ahmet Can\n3. Yılmaz",
            "[DAVALI_1] Can\nYılmaz",
            "AHMET CAN\nDAVACI",
            "A.\nYılmaz hazır bulundu.",
            "Ahmet\nBey söz aldı.",
            "Av. Ahmet Can\nYılmaz vekil sıfatıyla",
            "Ahmet Can\nYılmaz İnşaat Ltd. Şti. unvanlı şirket",
            "Ahmet Can\nYılmaz Caddesi üzerinde",
        ]
        for case in protected_cases:
            out, stats = UyapRedactor.redact_text(case, registry=reg)
            self.assertEqual(out, case, f"Korunmalıydı: {case!r}")
            self.assertEqual(stats["kisi"], 0, case)

    def test_yol_ve_baglanti_hedefi_degismedi(self):
        reg = self._reg()
        self.assertEqual(
            UyapRedactor.redact_path_segment("Ahmet_Can_Yılmaz_Dilekce.md", registry=reg, is_file=True),
            "[DAVACI_1]_Dilekce.md",
        )
        self.assertEqual(
            UyapRedactor.redact_path_segment("Ahmet_Can\nYılmaz.md", registry=reg, is_file=True),
            "Ahmet_Can\nYılmaz.md",
        )
        md_in = "Bkz: [Dilekçe](Ekler/Ahmet_Can_Yılmaz_Dilekce.md)\n"
        md_out, _ = UyapRedactor.redact_text(md_in, registry=reg)
        self.assertEqual(md_out, "Bkz: [Dilekçe](Ekler/[DAVACI_1]_Dilekce.md)\n")

    def test_adres_esas_karar_numarasini_yutmaz(self):
        cases = [
            (
                "Adres: Caferağa Mah. Moda Cad. No:5 D:3 Kadıköy/İstanbul, E: 2024/ 123, K: 2024/456",
                "Adres: [ADRES_1] (Kadıköy/İstanbul), E: 2024/ 123, K: 2024/456",
            ),
            (
                "Lale Mah. Gül Sk. No:5 Bornova/İzmir, E: 2024/ 123, K: 2024",
                "[ADRES_1] (Bornova/İzmir), E: 2024/ 123, K: 2024",
            ),
            (
                "| Adres: Lale Mah. Gül Sk. No:5 Bornova/İzmir, E: 2024/ 123, K: 2024 |",
                "| Adres: [ADRES_1] (Bornova/İzmir), E: 2024/ 123, K: 2024 |",
            ),
            (
                "Lale Mah. Bornova/İzmir, E: 2024/ 123, K: 2024/456",
                "Lale Mah. Bornova/İzmir, E: 2024/ 123, K: 2024/456",
            ),
        ]
        for raw, expected in cases:
            reg = MaskRegistry()
            out, _ = UyapRedactor.redact_text(raw, registry=reg)
            self.assertEqual(out, expected, raw)


class TestOcrKisiKesfi(unittest.TestCase):
    """Taranmış (OCR) belgelerden ön taramada kişi keşfi ve tek-okuma/gürültü kuralları."""

    def _make_tree(self, root: str, files: dict) -> None:
        for rel, data in files.items():
            fp = os.path.join(root, rel)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, "wb") as wf:
                wf.write(data)

    def test_yalniz_taramada_gecen_guclu_kanit_a_maskelenir(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            dest = os.path.join(tmp, "dest")
            self._make_tree(src, {
                "notlar.md": "Zeynep Arslan hakkında duruşma günü belirlendi.\n".encode("utf-8"),
                "tarama.pdf": b"%PDF-1.4\n%sahte tarama",
            })
            scan_raw = (
                "DAVACI : Zeynep Arslan\n"
                "Mahkemeye sunulan dilekçe ekinde alacak talebi ayrıntılı şekilde açıklanmıştır.\n"
            )
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("UYAP_OCR_CACHE_DIR", None)
                with patch.object(UyapRedactor, "extract_scanned_raw", return_value=scan_raw):
                    out_dir, stats = UyapRedactor.export_isolated_clean_folder(src, dest)
            self.assertEqual(stats["kisi_listesi"], [("[DAVACI_1]", "Zeynep Arslan")])
            with open(os.path.join(out_dir, "notlar.md"), encoding="utf-8") as f:
                notlar_out = f.read()
            with open(os.path.join(out_dir, "tarama.md"), encoding="utf-8") as f:
                tarama_out = f.read()
            self.assertIn("[DAVACI_1] hakkında duruşma günü belirlendi.", notlar_out)
            self.assertIn("DAVACI : [DAVACI_1]", tarama_out)
            self.assertNotIn("Zeynep", notlar_out)
            self.assertNotIn("Arslan", tarama_out)

    def test_taramada_zayif_kanit_tek_satir_atilir_iki_satir_kabul_edilir(self):
        # Tek satırda geçen B kalıbı kişi sayılmaz
        reg1 = MaskRegistry()
        UyapRedactor.collect_persons_from_text(
            "Duruşmada tanık Murat Kılıç dinlendi.\n", reg1, ocr=True
        )
        reg1.freeze_persons()
        self.assertEqual(reg1._person_order, [])

        # Aynı satırda 2 kez geçse bile 1 farklı satır olduğundan kişi sayılmaz
        reg_same = MaskRegistry()
        UyapRedactor.collect_persons_from_text(
            "Duruşmada tanık Murat Kılıç ile tanık Murat Kılıç hazır bulundu.\n",
            reg_same,
            ocr=True,
        )
        reg_same.freeze_persons()
        self.assertEqual(reg_same._person_order, [])

        # En az 2 farklı satırda geçerse kabul edilir ve çıkışta maskelenir
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            dest = os.path.join(tmp, "dest")
            self._make_tree(src, {"tutanak.tif": b"fake-tiff"})
            scan_two = (
                "Duruşmada tanık Murat Kılıç hazır bulundu ve yeminli ifadesine geçildi.\n"
                "Sorulduğunda tanık Murat Kılıç olay günü işyerinde olduğunu beyan etti.\n"
            )
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("UYAP_OCR_CACHE_DIR", None)
                with patch.object(UyapRedactor, "extract_scanned_raw", return_value=scan_two):
                    out_dir, stats = UyapRedactor.export_isolated_clean_folder(src, dest)
            self.assertEqual(stats["kisi_listesi"], [("[TANIK_1]", "Murat Kılıç")])
            with open(os.path.join(out_dir, "tutanak.md"), encoding="utf-8") as f:
                t_out = f.read()
            self.assertNotIn("Murat Kılıç", t_out)
            self.assertEqual(t_out.count("[TANIK_1]"), 2)

        # Tek satır uçtan uca tarama çıktısında da açık kalır
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            dest = os.path.join(tmp, "dest")
            self._make_tree(src, {"tutanak.tif": b"fake-tiff"})
            scan_one = (
                "Duruşmada tanık Murat Kılıç hazır bulundu ve yeminli ifadesine başlanıp tutanağa geçirildi.\n"
            )
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("UYAP_OCR_CACHE_DIR", None)
                with patch.object(UyapRedactor, "extract_scanned_raw", return_value=scan_one):
                    out_dir, stats = UyapRedactor.export_isolated_clean_folder(src, dest)
            self.assertEqual(stats["kisi_listesi"], [])
            with open(os.path.join(out_dir, "tutanak.md"), encoding="utf-8") as f:
                t_out = f.read()
            self.assertIn("Murat Kılıç", t_out)

    def test_ocr_gurultusu_reddedilir(self):
        noise_cases = [
            "DAVACI : Zzzzz Xxx\n",
            "DAVACI : A B C\n",
            "DAVALI : Ahm3t Yılm4z\n",
            "DAVALI : Ahmet Can Yılm4z\n",
            "DAVALI : Al Bo\n",
        ]
        for txt in noise_cases:
            reg = MaskRegistry()
            UyapRedactor.collect_persons_from_text(txt, reg, ocr=True)
            reg.freeze_persons()
            self.assertEqual(reg._person_order, [], f"Gürültü kişi oldu: {txt!r}")

    def test_taramada_sirket_unvani_kisi_olmaz(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            dest = os.path.join(tmp, "dest")
            self._make_tree(src, {"fatura.pdf": b"%PDF-1.4\n%sahte"})
            scan_corp = (
                "DAVALI : Arslan İnşaat Ltd. Şti.\n"
                "Tanık Arslan İnşaat temsilcisi beyan verdi.\n"
                "Tanık Arslan İnşaat tarafından kesilen faturalar incelendi.\n"
                "Arslan İnşaat Ltd. Şti. unvanlı şirkete ödeme yapılmıştır.\n"
            )
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("UYAP_OCR_CACHE_DIR", None)
                with patch.object(UyapRedactor, "extract_scanned_raw", return_value=scan_corp):
                    out_dir, stats = UyapRedactor.export_isolated_clean_folder(src, dest)
            self.assertEqual(stats["kisi_listesi"], [])
            with open(os.path.join(out_dir, "fatura.md"), encoding="utf-8") as f:
                out = f.read()
            self.assertIn("Arslan İnşaat Ltd. Şti.", out)

    def test_mask_names_false_iken_ocr_on_taramada_cagrilmaz(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            dest = os.path.join(tmp, "dest")
            self._make_tree(src, {
                "dava.md": "DAVACI : Ayşe Kaya\nTalep metni.\n".encode("utf-8"),
                "ek1.pdf": b"%PDF-1.4\n",
                "ek2.tif": b"fake-tiff",
            })
            events = []
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("UYAP_OCR_CACHE_DIR", None)
                with patch.object(
                    UyapRedactor,
                    "extract_scanned_raw",
                    return_value="DAVALI : Zeynep Arslan\nYeterli uzunlukta taranmış belge metni içeriği.\n",
                ) as m_ocr:
                    _, stats = UyapRedactor.export_isolated_clean_folder(
                        src,
                        dest,
                        mask_names=False,
                        mask_judicial_names=False,
                        progress_cb=lambda ev, msg, st: events.append((ev, msg)),
                    )
            self.assertEqual(m_ocr.call_count, 2)
            self.assertFalse(any(ev == "sync" and "Ön tarama (OCR)" in msg for ev, msg in events))
            self.assertEqual(stats["kisi_sayisi"], 0)

    def test_her_ocr_belgesi_yalnizca_bir_kez_okunur(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            dest = os.path.join(tmp, "dest")
            zip_path = os.path.join(src, "paket.zip")
            os.makedirs(src, exist_ok=True)
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("ic_ek.pdf", b"%PDF-1.4\n")
            self._make_tree(src, {
                "ek1.pdf": b"%PDF-1.4\n",
                "ek2.tif": b"fake-tiff",
            })

            def _fake_ocr(fp: str) -> str:
                base = os.path.basename(fp)
                if base == "ek1.pdf":
                    return "DAVACI : Zeynep Arslan\nBirinci taranmış belge içeriği yeterince uzundur.\n"
                if base == "ek2.tif":
                    return "DAVALI : Kemal Demir\nİkinci taranmış belge içeriği ve zeynel değil Zeynep Arslan.\n"
                return "TANIK : Hasan Yıldız\nArşiv içinden gelen taranmış belge metni yeterince uzun.\n"

            progress_log = []
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("UYAP_OCR_CACHE_DIR", None)
                with patch.object(UyapRedactor, "extract_scanned_raw", side_effect=_fake_ocr) as m_ocr:
                    out_dir, stats = UyapRedactor.export_isolated_clean_folder(
                        src,
                        dest,
                        progress_cb=lambda ev, msg, st: progress_log.append(
                            (ev, msg, st["processed_items"], st["total_work"])
                        ),
                    )
            self.assertEqual(m_ocr.call_count, 3)
            prescan_sync = [x for x in progress_log if x[0] == "sync" and "Ön tarama (OCR)" in x[1]]
            self.assertEqual(len(prescan_sync), 3)
            self.assertTrue(all(cur == 0 and tot == 0 for _, _, cur, tot in prescan_sync))
            self.assertEqual(len(stats["kisi_listesi"]), 3)
            with open(os.path.join(out_dir, "ek2.md"), encoding="utf-8") as f:
                self.assertIn("[DAVACI_1]", f.read())

    def test_bellek_tavani_asildiginda_sonuc_ayni_okuma_sayisi_artar(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            dest = os.path.join(tmp, "dest")
            self._make_tree(src, {
                "b1.pdf": b"%PDF-1.4\n1",
                "b2.pdf": b"%PDF-1.4\n2",
            })

            def _fake_ocr(fp: str) -> str:
                if fp.endswith("b1.pdf"):
                    return "DAVACI : Zeynep Arslan\n" + ("Birinci belge açıklama metni. " * 4) + "\n"
                return "DAVALI : Kemal Demir\n" + ("İkinci belge açıklama metni. " * 4) + "\n"

            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("UYAP_OCR_CACHE_DIR", None)
                with patch.object(UyapRedactor, "OCR_PRESCAN_MAX_MEM_BYTES", 150):
                    with patch.object(UyapRedactor, "extract_scanned_raw", side_effect=_fake_ocr) as m_ocr:
                        out_dir, stats = UyapRedactor.export_isolated_clean_folder(src, dest)

            # b1 (<=150 byte) 1 kez, b2 (>150 byte) 2 kez => toplam 3 okuma (>2)
            self.assertGreater(m_ocr.call_count, 2)
            self.assertEqual(m_ocr.call_count, 3)
            self.assertEqual(
                stats["kisi_listesi"],
                [("[DAVACI_1]", "Zeynep Arslan"), ("[DAVALI_1]", "Kemal Demir")],
            )
            with open(os.path.join(out_dir, "b2.md"), encoding="utf-8") as f:
                b2_out = f.read()
            self.assertIn("DAVALI : [DAVALI_1]", b2_out)
            self.assertNotIn("Kemal Demir", b2_out)


class TestFinalPolishAndAIComprehensibility(unittest.TestCase):

    def test_report_lists_anonymous_party_labels_without_real_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "dava")
            dest = os.path.join(tmp, "dava_out")
            os.makedirs(src, exist_ok=True)
            with open(os.path.join(src, "dilekce.md"), "w", encoding="utf-8") as wf:
                wf.write(
                    "DAVACI : Ali Kaya\n"
                    "DAVALI : Mehmet Demir\n"
                    "TANIK : Hasan Arslan\n"
                    "Talep.\n"
                )
            out_dir, _ = UyapRedactor.export_isolated_clean_folder(src, dest)
            report = open(os.path.join(out_dir, UyapRedactor.REPORT_NAME), encoding="utf-8").read()
            self.assertIn("## Dosyadaki anonim yargı ve taraf etiketleri (gerçek ad içermez)", report)
            self.assertIn("- **DAVACI:** `[DAVACI_1]`", report)
            self.assertIn("- **DAVALI:** `[DAVALI_1]`", report)
            self.assertIn("- **TANIK:** `[TANIK_1]`", report)
            self.assertNotIn("yalnızca metinli belgelerde", report)
            for real_name in ("Ali Kaya", "Mehmet Demir", "Hasan Arslan"):
                self.assertNotIn(real_name, report)

    def test_mahal_event_and_named_facilities_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "olay_dava")
            dest = os.path.join(tmp, "olay_dava_out")
            os.makedirs(src, exist_ok=True)
            with open(os.path.join(src, "tutanak.md"), "w", encoding="utf-8") as wf:
                wf.write(
                    "DAVACI : Ali Kaya\n"
                    "Suç mahalli: Barbaros Mah. 10. Sok. No:5 Beşiktaş/İstanbul\n"
                    "Keşif yeri: Çamlıca Mah. Lale Cad. No:8 Üsküdar/İstanbul\n"
                    "Davacı Ali Kaya olay sonrası Ali Kaya Merkezi ve Ali Kaya Köyü civarındaydı.\n"
                )
            out_dir, _ = UyapRedactor.export_isolated_clean_folder(src, dest)
            out = open(os.path.join(out_dir, "tutanak.md"), encoding="utf-8").read()
            self.assertIn("DAVACI : [DAVACI_1]", out)
            self.assertIn("Davacı [DAVACI_1] olay sonrası", out)
            self.assertIn("Suç mahalli: Barbaros Mah. 10. Sok. No:5 Beşiktaş/İstanbul", out)
            self.assertIn("Keşif yeri: Çamlıca Mah. Lale Cad. No:8 Üsküdar/İstanbul", out)
            self.assertIn("Ali Kaya Merkezi", out)
            self.assertIn("Ali Kaya Köyü", out)

    def test_cli_single_file_and_in_place_person_discovery(self):
        import uyap_redactor
        with tempfile.TemporaryDirectory() as tmp:
            # 1) Tek dosya yolu - varsayılan mod (bayraksız: taraf + yargı maskeli, avukat açık)
            single_md = os.path.join(tmp, "tek_belge.md")
            with open(single_md, "w", encoding="utf-8") as wf:
                wf.write(
                    "DAVACI : Zeynep Arslan\n"
                    "VEKİLİ : Av. Ayşe Kaya\n"
                    "HÂKİM : Mehmet Demir (112233)\n"
                    "T.C. Kimlik No: 10000000146\n"
                )

            with patch.object(sys, "argv", ["uyap_redactor.py", single_md]):
                uyap_redactor.main()

            out_dir = os.path.join(tmp, "tek_belge (Maskelenmis AI)")
            self.assertTrue(os.path.isdir(out_dir))
            out_txt = open(os.path.join(out_dir, "tek_belge.md"), encoding="utf-8").read()
            self.assertIn("[DAVACI_1]", out_txt)
            self.assertIn("[HAKİM_1]", out_txt)
            self.assertIn("[TCKN_1]", out_txt)
            self.assertIn("Av. Ayşe Kaya", out_txt)
            self.assertNotIn("Zeynep Arslan", out_txt)
            self.assertNotIn("Mehmet Demir", out_txt)

            # 2) Tek dosya yolu - --taraf-isimlerini-koru (taraf açık, yargı maskeli)
            single_koru_out = os.path.join(tmp, "tek_belge_taraf_acik")
            with patch.object(
                sys,
                "argv",
                ["uyap_redactor.py", single_md, "--out", single_koru_out, "--taraf-isimlerini-koru"],
            ):
                uyap_redactor.main()
            out_koru_txt = open(os.path.join(single_koru_out, "tek_belge.md"), encoding="utf-8").read()
            self.assertIn("Zeynep Arslan", out_koru_txt)
            self.assertIn("[HAKİM_1]", out_koru_txt)
            self.assertNotIn("Mehmet Demir", out_koru_txt)

            # 3) --in-place yolu - varsayılan mod ve --taraf-isimlerini-koru modu
            inplace_dir = os.path.join(tmp, "inplace_case")
            os.makedirs(inplace_dir, exist_ok=True)
            inplace_md = os.path.join(inplace_dir, "dilekce.md")
            with open(inplace_md, "w", encoding="utf-8") as wf:
                wf.write(
                    "DAVACI : Zeynep Arslan\n"
                    "HÂKİM : Mehmet Demir (112233)\n"
                    "Davacı Zeynep Arslan beyan eder.\n"
                )
            with patch.object(sys, "argv", ["uyap_redactor.py", inplace_dir, "--in-place"]):
                uyap_redactor.main()
            inplace_out = open(inplace_md, encoding="utf-8").read()
            self.assertIn("[DAVACI_1]", inplace_out)
            self.assertIn("[HAKİM_1]", inplace_out)
            self.assertNotIn("Zeynep Arslan", inplace_out)
            self.assertNotIn("Mehmet Demir", inplace_out)

            inplace_open_dir = os.path.join(tmp, "inplace_case_open")
            os.makedirs(inplace_open_dir, exist_ok=True)
            inplace_open_md = os.path.join(inplace_open_dir, "dilekce.md")
            with open(inplace_open_md, "w", encoding="utf-8") as wf:
                wf.write("DAVACI : Zeynep Arslan\nHÂKİM : Mehmet Demir (112233)\n")
            with patch.object(
                sys,
                "argv",
                ["uyap_redactor.py", inplace_open_dir, "--in-place", "--taraf-isimlerini-koru"],
            ):
                uyap_redactor.main()
            inplace_open_out = open(inplace_open_md, encoding="utf-8").read()
            self.assertIn("Zeynep Arslan", inplace_open_out)
            self.assertIn("[HAKİM_1]", inplace_open_out)
            self.assertNotIn("Mehmet Demir", inplace_open_out)

            # 4) --taraf-isimlerini-koru + --yargi-isimlerini-koru birlikte (--out ve --in-place)
            single_all_open_out = os.path.join(tmp, "tek_belge_tum_acik")
            with patch.object(
                sys,
                "argv",
                ["uyap_redactor.py", single_md, "--out", single_all_open_out, "--taraf-isimlerini-koru", "--yargi-isimlerini-koru"],
            ):
                uyap_redactor.main()
            all_open_txt = open(os.path.join(single_all_open_out, "tek_belge.md"), encoding="utf-8").read()
            self.assertIn("Zeynep Arslan", all_open_txt)
            self.assertIn("Mehmet Demir", all_open_txt)
            self.assertIn("[TCKN_1]", all_open_txt)

            inplace_legacy_dir = os.path.join(tmp, "inplace_case_legacy")
            os.makedirs(inplace_legacy_dir, exist_ok=True)
            inplace_legacy_md = os.path.join(inplace_legacy_dir, "dilekce.md")
            with open(inplace_legacy_md, "w", encoding="utf-8") as wf:
                wf.write("DAVACI : Zeynep Arslan\nHÂKİM : Mehmet Demir (112233)\n")
            with patch.object(
                sys,
                "argv",
                ["uyap_redactor.py", inplace_legacy_dir, "--in-place", "--isimleri-koru"],
            ):
                uyap_redactor.main()
            inplace_legacy_out = open(inplace_legacy_md, encoding="utf-8").read()
            self.assertIn("Zeynep Arslan", inplace_legacy_out)
            self.assertIn("[HAKİM_1]", inplace_legacy_out)
            self.assertNotIn("Mehmet Demir", inplace_legacy_out)

    def test_ptt_teslimat_not_person_and_subsequent_address_masked(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            dest = os.path.join(tmp, "dest")
            os.makedirs(src, exist_ok=True)
            with open(os.path.join(src, "tebligat.md"), "w", encoding="utf-8") as wf:
                wf.write(
                    "BORÇLU : Hakan Yıldırım\n"
                    "PTT Teslimat TCKN : 100*****146\n"
                    "Adres : Feneryolu Mah. Bağdat Cad. No:110 D:9 Kadıköy/İstanbul\n"
                )
            out_dir, stats = UyapRedactor.export_isolated_clean_folder(src, dest)
            out = open(os.path.join(out_dir, "tebligat.md"), encoding="utf-8").read()
            self.assertIn("[BORÇLU_1]", out)
            self.assertNotIn("PTT Teslimat", {name for _, name in stats["kisi_listesi"]})
            self.assertNotIn("[KİŞİ_", out)
            self.assertNotIn("Feneryolu Mah.", out)
            self.assertNotIn("Bağdat Cad.", out)
            self.assertIn("Kadıköy/İstanbul", out)

    def test_kredi_karti_without_no_and_4_8_4_partial_masked(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            dest = os.path.join(tmp, "dest")
            os.makedirs(src, exist_ok=True)
            with open(os.path.join(src, "kart.md"), "w", encoding="utf-8") as wf:
                wf.write(
                    "Kredi Kartı : 4532 1111 2222 3337\n"
                    "Kısmi Kart : 4532 **** **** 3337\n"
                )
            out_dir, _ = UyapRedactor.export_isolated_clean_folder(src, dest)
            out = open(os.path.join(out_dir, "kart.md"), encoding="utf-8").read()
            self.assertNotIn("4532 1111 2222 3337", out)
            self.assertNotIn("3337", out)
            self.assertIn("[KART_1]", out)

    def test_header_split_name_across_newline_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            dest = os.path.join(tmp, "dest")
            os.makedirs(src, exist_ok=True)
            with open(os.path.join(src, "icra.md"), "w", encoding="utf-8") as wf:
                wf.write(
                    "BORÇLU : Hakan\n"
                    "Yıldırım\n"
                    "Borçlu Hakan Yıldırım ödeme yapmadı.\n"
                )
            out_dir, _ = UyapRedactor.export_isolated_clean_folder(src, dest)
            out = open(os.path.join(out_dir, "icra.md"), encoding="utf-8").read()
            self.assertIn("[BORÇLU_1]", out)
            self.assertNotIn("Hakan", out)
            self.assertNotIn("Yıldırım", out)

    def test_kaza_mahalli_preserved_after_ikametgah(self):
        reg = MaskRegistry()
        raw = (
            "İkametgah Adresi: Bahçelievler Mah. Lale Sok. No:8\n"
            "Kaza mahalli: İzmir Yolu 12. Km Nilüfer/Bursa\n"
            "Olay yeri: Atatürk Bulvarı Kavşağı Çankaya/Ankara\n"
        )
        out, _ = UyapRedactor.redact_text(raw, registry=reg)
        self.assertIn("[ADRES_1]", out)
        self.assertNotIn("Bahçelievler Mah.", out)
        self.assertIn("Kaza mahalli: İzmir Yolu 12. Km Nilüfer/Bursa", out)
        self.assertIn("Olay yeri: Atatürk Bulvarı Kavşağı Çankaya/Ankara", out)

    def test_asc_and_legacy_ssc_role_with_parenthesized_official_sicils(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dest = os.path.join(tmp, "src"), os.path.join(tmp, "dest")
            os.makedirs(src, exist_ok=True)
            with open(os.path.join(src, "durusma.md"), "w", encoding="utf-8") as wf:
                wf.write(
                    "HÂKİM : Murat Sönmez (34567)\n"
                    "C. SAVCISI : Fatih Yıldız (98765)\n"
                    "ZABIT KÂTİBİ : Selin Koç (112233)\n"
                    "ASÇ : Arda Taş\n"
                    "SSÇ : Mert Can\n"
                    "Duruşmada adli süreçteki çocuk Arda Taş ve SSÇ Mert Can söz aldı.\n"
                )
            out_dir, _ = UyapRedactor.export_isolated_clean_folder(src, dest)
            out = open(os.path.join(out_dir, "durusma.md"), encoding="utf-8").read()
            self.assertNotIn("Arda Taş", out)
            self.assertNotIn("Mert Can", out)
            self.assertIn("[ASÇ_1]", out)
            self.assertIn("[ASÇ_2]", out)
            self.assertNotIn("[SSÇ_", out)
            for s in ("34567", "98765", "112233"):
                self.assertNotIn(s, out)
            for masked_j in ("Murat Sönmez", "Fatih Yıldız", "Selin Koç"):
                self.assertNotIn(masked_j, out)
            self.assertIn("[HAKİM_1]", out)
            self.assertIn("[SAVCI_1]", out)
            self.assertIn("[KÂTİP_1]", out)

    def test_disjoint_role_two_and_three_token_persons_not_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dest = os.path.join(tmp, "src"), os.path.join(tmp, "dest")
            os.makedirs(src, exist_ok=True)
            with open(os.path.join(src, "kisiler.md"), "w", encoding="utf-8") as wf:
                wf.write(
                    "DAVACI : Mehmet Yılmaz\n"
                    "TANIK : Mehmet Ali Yılmaz\n"
                    "Davacı Mehmet Yılmaz ile tanık Mehmet Ali Yılmaz ayrı kişilerdir.\n"
                )
            out_dir, _ = UyapRedactor.export_isolated_clean_folder(src, dest)
            out = open(os.path.join(out_dir, "kisiler.md"), encoding="utf-8").read()
            self.assertIn("[DAVACI_1]", out)
            self.assertIn("[TANIK_1]", out)
            self.assertNotIn("Mehmet Yılmaz", out)
            self.assertNotIn("Mehmet Ali Yılmaz", out)

    def test_nfd_unicode_text_and_external_symlink_guarded(self):
        nfd_name = unicodedata.normalize("NFD", "İğneci Şükran Çoşkun")
        with tempfile.TemporaryDirectory() as tmp:
            src, dest = os.path.join(tmp, "src"), os.path.join(tmp, "dest")
            os.makedirs(src, exist_ok=True)
            secret = os.path.join(tmp, "gizli.md")
            with open(secret, "w", encoding="utf-8") as sf:
                sf.write("DAVACI : Dışarıdaki Gizli\nDIS_SIR_123\n")
            os.symlink(secret, os.path.join(src, "dis_bag.md"))
            with open(os.path.join(src, "nfd.md"), "w", encoding="utf-8") as wf:
                wf.write(f"DAVACI : {nfd_name}\nBeyan sahibi {nfd_name} oldu.\n")
            out_dir, _ = UyapRedactor.export_isolated_clean_folder(src, dest)
            out = open(os.path.join(out_dir, "nfd.md"), encoding="utf-8").read()
            self.assertIn("[DAVACI_1]", out)
            self.assertNotIn("Şükran", out)
            self.assertFalse(os.path.exists(os.path.join(out_dir, "dis_bag.md")))

    def test_vertical_table_inline_pipe_and_leading_descriptors(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dest = os.path.join(tmp, "src"), os.path.join(tmp, "dest")
            os.makedirs(src, exist_ok=True)
            with open(os.path.join(src, "karma.md"), "w", encoding="utf-8") as wf:
                wf.write(
                    "| DAVACI | TCKN |\n"
                    "| --- | --- |\n"
                    "| Nevin Şen | 10000000146 |\n\n"
                    "Belge 1: ALACAKLI : Ali Yıldız | BORÇLU : Veli Aksu\n"
                    "DAVALI : Şantiye Şefi Hakan Demir\n"
                    "DAVALI : Sürücü Kemal Kaya\n"
                    "Hakan Demir ve Kemal Kaya dinlendi.\n"
                )
            out_dir, stats = UyapRedactor.export_isolated_clean_folder(src, dest)
            out = open(os.path.join(out_dir, "karma.md"), encoding="utf-8").read()
            for pii in ("Nevin Şen", "10000000146", "Ali Yıldız", "Veli Aksu", "Hakan Demir", "Kemal Kaya"):
                self.assertNotIn(pii, out)
            self.assertEqual(len(stats["kisi_listesi"]), 5)

    def test_pdf_soft_hyphen_ocr_short_surname_and_ascii_province(self):
        reg = MaskRegistry()
        raw_ocr = "DAVACI : Neslihan Ak\nTANIK : Oğuzhan Er\n"
        UyapRedactor.collect_persons_from_text(raw_ocr, reg, ocr=True)
        reg.freeze_persons()
        out_p, _ = UyapRedactor.redact_text(raw_ocr, registry=reg)
        self.assertNotIn("Neslihan Ak", out_p)
        self.assertIn("[DAVACI_1]", out_p)
        self.assertNotIn("Oğuzhan Er", out_p)

        addr_out, _ = UyapRedactor.redact_text(
            "Ev Adresi : İçerenköy Mah. Karslı Ahmet Cad. No:5 Ataşehir/Istanbul",
            registry=MaskRegistry(),
        )
        self.assertIn("(Ataşehir/İstanbul)", addr_out)

        try:
            import fitz
        except ImportError:
            fitz = None
        if fitz is not None:
            with tempfile.TemporaryDirectory() as tmp:
                p = os.path.join(tmp, "soft.pdf")
                doc = fitz.open()
                pg = doc.new_page()
                pg.insert_htmlbox(
                    fitz.Rect(40, 40, 550, 750),
                    "<p>Mahkeme evrakı içerik bilgileri aşağıda sunulmuştur.<br>TCKN: 100000\u00ad00146</p>",
                )
                doc.save(p)
                doc.close()
                ext_txt = UyapRedactor.extract_pdf_raw(p)
                self.assertIn("10000000146", ext_txt)

    def test_nufus_vertical_child_two_given_names_unified_and_notary_wrapped_addresses(self):
        """Nüfus tablosundaki 3 kelimeli çocuk, 2 ön adıyla birleşir; sarılı '/ İl' ve noter adresi doğru işlenir."""
        nufus_doc = (
            "NÜFUS KAYIT ÖRNEĞİ (AİLE)\n"
            "Eşi\n10000000146\nDENİZ\nDEMİR\nBURDUR\nAYŞE\nALİ\n"
            "Kendisi\n10000000236\nMERT\nDEMİR\nBURDUR\nFATMA\nHASAN\n"
            "Oğlu\n10000000326\nCAN\xa0EFE\nDEMİR\nBURDUR\n"
        )
        dilekce_doc = (
            "BURDUR AİLE MAHKEMESİ'NE\n"
            "DAVACI : DENİZ DEMİR - 10000000146\n"
            "Adres: Örnek Mah. Çınar Sk. No: 27a3 / 6 Merkez / BURDUR\n"
            "DAVALI : MERT DEMİR - 10000000236\n"
            "1) Bu evlilikten 2017 doğumlu CAN EFE adında bir adet müşterek çocukları bulunmaktadır.\n"
        )
        protokol_doc = (
            "PROTOKOL\n"
            "Bu evlilikten 2017 doğumlu CAN EFE isimli müşterek çocukları vardır.\n"
            "Tarafların müşterek çocukları olan CAN EFE'nin velayeti anne DENİZ DEMİR'de kalacaktır.\n"
            "Müşterek çocuk CAN EFE ortak karar ile yaşayacaktır.\n"
        )
        vekalet_doc = (
            "BURDUR 1. NOTERİ\n"
            "SEMA KORKMAZ\n"
            "KONAK MAH.GAZI\n"
            "CD.15/1 15100 MERKEZ\n"
            "/ BURDUR\n"
            "DAVACI : DENİZ DEMİR 10000000146\n"
            "Örnek Mah. Çınar Sk. No: 27a3 / 6 Merkez / BURDUR\n"
            "VEKİL : Av. KEREM YILDIZ\n"
            "Adres : Bahçelievler Mah. Park Bulvarı No:4/2 Daire:8 Merkez /\n"
            "BURDUR\n"
        )

        reg = MaskRegistry()
        for doc in (nufus_doc, dilekce_doc, protokol_doc, vekalet_doc):
            UyapRedactor.collect_persons_from_text(doc, reg)
        reg.freeze_persons()

        self.assertEqual(reg.person_count_by_role().get("KİŞİ"), 1)
        red_dilekce, _ = UyapRedactor.redact_text(dilekce_doc, registry=reg)
        red_protokol, _ = UyapRedactor.redact_text(protokol_doc, registry=reg)
        red_vekalet, _ = UyapRedactor.redact_text(vekalet_doc, registry=reg)
        red_nufus, _ = UyapRedactor.redact_text(nufus_doc, registry=reg)

        for red in (red_dilekce, red_protokol, red_nufus):
            self.assertNotIn("CAN EFE", red)
        self.assertIn("[KİŞİ_1]", red_dilekce)
        self.assertIn("[KİŞİ_1]'nin", red_protokol)
        self.assertIn("[KİŞİ_1]", red_nufus)
        self.assertNotIn("DEMİR\nHASAN", red_nufus)

        self.assertNotIn("27a3", red_vekalet)
        self.assertNotIn("3 / 6", red_vekalet)
        self.assertIn("(Merkez/Burdur)", red_vekalet)
        # Satır sonuna sarılan "/\nBURDUR" adrese dahil edilmeli (tek başına sızmamalı)
        self.assertNotRegex(red_vekalet, r"\[ADRES_\d+\]\s*(?:\([^)]+\))?\s*/?\s*\n\s*BURDUR\b")
        # Noter kurum adresi korunmalı
        self.assertIn("BURDUR 1. NOTERİ", red_vekalet)
        self.assertIn("KONAK MAH.GAZI", red_vekalet)








