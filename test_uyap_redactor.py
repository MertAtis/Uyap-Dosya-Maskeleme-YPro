#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UYAP Maskeleme ve İndeks Senkronizasyon Test Paketi (Adversarial Güvenlik & Doğrulama)
"""

import os
import sys
import tempfile
import unittest

# Modülü içeri aktar
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from uyap_redactor import UyapRedactor


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

            self.assertNotIn("12345678901", dest_md_content)
            self.assertIn("[TCKN_GİZLENDİ]", dest_md_content)
            self.assertNotIn("05321112233", dest_md_content)
            self.assertIn("[TELEFON_GİZLENDİ]", dest_md_content)
            self.assertNotIn("A12B34567", dest_md_content)
            self.assertIn("[SERİ_NO_GİZLENDİ]", dest_md_content)
            self.assertNotIn("TR330006100511123456789012", dest_md_content)
            self.assertIn("[IBAN_GİZLENDİ]", dest_md_content)

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
            self.assertIn("[TCKN_GİZLENDİ]", content)

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
            self.assertEqual(red_project["taraflar"][0]["tckn"], UyapRedactor.MASK_TCKN)
            self.assertEqual(red_project["taraflar"][1]["tckn_int"], UyapRedactor.MASK_TCKN)
            self.assertIn("[ADRES_GİZLENDİ]", red_project["adres"])
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



if __name__ == "__main__":
    unittest.main()
