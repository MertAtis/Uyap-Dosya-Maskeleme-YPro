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


if __name__ == "__main__":
    unittest.main()
