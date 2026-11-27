# -*- coding: utf-8 -*-
"""
Gerçek dava dosyalarında tespit edilen 5 hata için birim ve regresyon testleri:
1. Bozuk gömülü PDF metin katmanı tespiti (_is_corrupted_pdf_text & extract_pdf_raw)
2. Çok sayfalı TIFF 60 sayfa sınırının kaldırılması (max_pages=2000 & bellek güvenli akış)
3. Koyu/düşük kontrastlı PDF/TIFF sayfalarında 300 DPI + kontrast/ikileştirme yeniden denemesi ve uyarı
4. Standart UYAP/adli belge adlarının kişi adı sanılmaması (MaskRegistry & redact_path_segment)
5. OCR'lı/bozuk metinlerde kontrollü bulanık kişi adı maskeleme dayanıklılığı
"""

import inspect
import os
import tempfile
import unittest
from unittest.mock import patch

from uyap_redactor import MaskRegistry, UyapRedactor


class Test1_BozukPdfMetinKatmani(unittest.TestCase):
    """Bozuk/eksik gömülü PDF metin katmanı tespiti ve Vision OCR karşılaştırması."""

    def test_corrupted_pdf_text_positives_and_negatives(self):
        corrupted_samples = [
            "Mahkemece dtizenlenmig olan bu tutanak qok eks1k ve tar1h1 1510312023 [sayfa$1] yaz1lm1gt1r.",
            "Tutanak m€tn1 qok bozuk, gtirfiItfi ve k1$1 b1lg1ler1 b{u}lunamad1 1210412022 tarihli evrak.",
            "a . b , c ; d / e ! f ? g : h * i . j , k ; l / m ! n ? o : p * r . s",
            "Bu belge 5070 sayılı Elektronik İmza Kanunu uyarınca imzalanmıştır.",
        ]
        # İlk 3 örnek metin bozukluğu nedeniyle doğrudan True
        for sample in corrupted_samples[:3]:
            self.assertTrue(
                UyapRedactor._is_corrupted_pdf_text(sample),
                f"Bozuk PDF metni tespit edilemedi: {sample!r}",
            )
        # 4. örnek büyük gömülü tarama görseli üzerinde yalnız kısa e-imza şerhi -> görsel oranıyla True
        self.assertFalse(UyapRedactor._is_corrupted_pdf_text(corrupted_samples[3], image_area_ratio=0.0))
        self.assertTrue(UyapRedactor._is_corrupted_pdf_text(corrupted_samples[3], image_area_ratio=0.85))

        clean_samples = [
            "Ankara 5. Asliye Hukuk Mahkemesi 2023/145 Esas ve 2024/312 Karar sayılı dosyası incelenmiştir.",
            "6100 sayılı HMK madde 114/1-ç ve 15.03.2023 tarihli 150.000 TL tutarlı dekont dosyadadır.",
            "Mahkeme evrakı içerik bilgileri aşağıda sunulmuştur.\nTCKN: 10000000146",
            "Davacı vekili Av. Ayşe Yılmaz tarafından 01.02.2024 tarihinde dilekçe sunulmuştur.",
        ]
        for sample in clean_samples:
            self.assertFalse(
                UyapRedactor._is_corrupted_pdf_text(sample),
                f"Temiz dijital metin yanlışlıkla bozuk sayıldı: {sample!r}",
            )

    def test_extract_pdf_raw_replaces_corrupted_layer_with_cleaner_ocr(self):
        import fitz

        with tempfile.TemporaryDirectory() as tmp:
            pdf_p = os.path.join(tmp, "bozuk_katman.pdf")
            doc = fitz.open()
            pg = doc.new_page()
            pg.insert_text(
                (40, 60),
                "Mahkemece dtizenlenmig olan bu evrak qok eks1k ve 1510312023 [sayfa$1] yaz1lm1gt1r.",
            )
            doc.save(pdf_p)
            doc.close()

            clean_ocr_lines = [
                "T.C. ANKARA 5. ASLİYE HUKUK MAHKEMESİ",
                "Mahkemece düzenlenmiş olan bu evrak çok açık ve 15/03/2023 tarihinde yazılmıştır.",
            ]
            with patch.object(
                UyapRedactor,
                "_ocr_image_with_retry",
                return_value=(True, clean_ocr_lines),
            ) as mock_ocr:
                raw = UyapRedactor.extract_pdf_raw(pdf_p)
            mock_ocr.assert_called_once()
            self.assertIn("### Sayfa 1 (Yerel OCR)", raw)
            self.assertIn("Mahkemece düzenlenmiş olan bu evrak", raw)
            self.assertNotIn("dtizenlenmig", raw)

    def test_extract_pdf_raw_keeps_clean_digital_layer_without_ocr(self):
        import fitz

        with tempfile.TemporaryDirectory() as tmp:
            pdf_p = os.path.join(tmp, "temiz_dijital.pdf")
            doc = fitz.open()
            pg = doc.new_page()
            pg.insert_text(
                (40, 60),
                "Ankara 5. Asliye Hukuk Mahkemesi 2023/145 Esas sayılı dosyası kapsamında karar verilmiştir.",
            )
            doc.save(pdf_p)
            doc.close()

            with patch.object(UyapRedactor, "_ocr_image_with_retry") as mock_ocr:
                raw = UyapRedactor.extract_pdf_raw(pdf_p)
            mock_ocr.assert_not_called()
            self.assertIn("### Sayfa 1\n\n", raw)
            self.assertNotIn("(Yerel OCR)", raw)


class Test2_CokSayfaliTiffVeBellekGuvenligi(unittest.TestCase):
    """Çok sayfalı TIFF'lerde 60 sayfa sınırının kalktığını ve max_pages=2000 desteğini doğrular."""

    def test_extract_image_raw_default_max_pages_is_2000(self):
        sig1 = inspect.signature(UyapRedactor.extract_image_raw)
        sig2 = inspect.signature(UyapRedactor.extract_and_redact_image)
        self.assertEqual(sig1.parameters["max_pages"].default, 2000)
        self.assertEqual(sig2.parameters["max_pages"].default, 2000)

    def test_multipage_tiff_processes_over_60_pages_and_warns_above_max_pages(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            tiff_p = os.path.join(tmp, "cok_sayfa.tif")
            frames = [Image.new("RGB", (120, 120), "white") for _ in range(65)]
            frames[0].save(tiff_p, format="TIFF", save_all=True, append_images=frames[1:])
            for f in frames:
                f.close()

            call_idx = {"n": 0}

            def fake_ocr(_img_path, _tmpdir, tag="img", pdf_page=None):
                call_idx["n"] += 1
                return True, [f"Belge sayfası numarası {call_idx['n']} okundu."]

            with patch.object(UyapRedactor, "_ocr_image_with_retry", side_effect=fake_ocr):
                raw_all = UyapRedactor.extract_image_raw(tiff_p)

            self.assertIn("### Sayfa 61 (Yerel OCR)", raw_all)
            self.assertIn("### Sayfa 65 (Yerel OCR)", raw_all)
            self.assertNotIn("yalnızca ilk", raw_all)

            call_idx["n"] = 0
            with patch.object(UyapRedactor, "_ocr_image_with_retry", side_effect=fake_ocr):
                raw_lim = UyapRedactor.extract_image_raw(tiff_p, max_pages=5)

            self.assertIn("### Sayfa 5 (Yerel OCR)", raw_lim)
            self.assertNotIn("### Sayfa 6 (Yerel OCR)", raw_lim)
            self.assertIn("Bu belge 65 sayfadır; yalnızca ilk 5 sayfa işlenmiştir.", raw_lim)

    def test_multipage_tiff_exotic_colorspace_frames_handled_safely(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            tiff_p = os.path.join(tmp, "renkli.tif")
            f1 = Image.new("CMYK", (120, 120), (0, 0, 0, 0))
            f2 = Image.new("RGBA", (120, 120), (255, 255, 255, 255))
            f3 = Image.new("1", (120, 120), 1)
            f1.save(tiff_p, format="TIFF", save_all=True, append_images=[f2, f3])
            f1.close()
            f2.close()
            f3.close()

            with patch.object(
                UyapRedactor,
                "_ocr_image_with_retry",
                return_value=(True, ["Renk uzayı dönüştürülmüş sayfa metni okundu."]),
            ):
                raw = UyapRedactor.extract_image_raw(tiff_p)
            self.assertIn("### Sayfa 1 (Yerel OCR)", raw)
            self.assertIn("### Sayfa 2 (Yerel OCR)", raw)
            self.assertIn("### Sayfa 3 (Yerel OCR)", raw)


class Test3_KoyuDusukKontrastRetryVeUyari(unittest.TestCase):
    """Düşük kontrastlı PDF/TIFF sayfalarında 300 DPI + kontrast/ikileştirme retry ve uyarı."""

    def test_pdf_retries_at_300_dpi_then_contrast_enhanced(self):
        import fitz

        with tempfile.TemporaryDirectory() as tmp:
            pdf_p = os.path.join(tmp, "koyu_tarama.pdf")
            doc = fitz.open()
            pg = doc.new_page()
            # Sayfaya görsel ekle (PIL ile üretilen küçük koyu gri PNG)
            from PIL import Image
            img_p = os.path.join(tmp, "dark.png")
            Image.new("RGB", (200, 200), (40, 40, 40)).save(img_p, "PNG")
            pg.insert_image(fitz.Rect(20, 20, 560, 780), filename=img_p)
            doc.save(pdf_p)
            doc.close()

            seen_paths = []

            def fake_vision(path_p):
                seen_paths.append(os.path.basename(path_p))
                if "_enh.png" in path_p or "_bin.png" in path_p:
                    return True, ["Koyu tarama kontrast artırma ile başarıyla okundu."]
                return True, []

            with patch.object(UyapRedactor, "_vision_ocr_image", side_effect=fake_vision):
                raw = UyapRedactor.extract_pdf_raw(pdf_p)

            self.assertTrue(any("_150.png" in p for p in seen_paths), seen_paths)
            self.assertTrue(any("_300.png" in p for p in seen_paths), seen_paths)
            self.assertTrue(any("_enh.png" in p for p in seen_paths), seen_paths)
            self.assertIn("Koyu tarama kontrast artırma ile başarıyla okundu.", raw)

    def test_unreadable_scanned_pdf_and_tiff_emit_explicit_warning(self):
        import fitz
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            pdf_p = os.path.join(tmp, "okunamayan.pdf")
            img_p = os.path.join(tmp, "blank_dark.png")
            Image.new("RGB", (300, 300), (20, 20, 20)).save(img_p, "PNG")
            doc = fitz.open()
            pg = doc.new_page()
            pg.insert_image(fitz.Rect(20, 20, 560, 780), filename=img_p)
            doc.save(pdf_p)
            doc.close()

            tiff_p = os.path.join(tmp, "okunamayan.tif")
            f1 = Image.new("RGB", (300, 300), (20, 20, 20))
            f2 = Image.new("RGB", (300, 300), (25, 25, 25))
            f1.save(tiff_p, format="TIFF", save_all=True, append_images=[f2])
            f1.close()
            f2.close()

            with patch.object(UyapRedactor, "_vision_ocr_image", return_value=(True, [])):
                pdf_raw = UyapRedactor.extract_pdf_raw(pdf_p)
                tiff_raw = UyapRedactor.extract_image_raw(tiff_p)

            expected_note = "Bu sayfa taranmış görseldir ancak düşük kontrast/tarama kalitesi nedeniyle yerel OCR ile metin okunamadı."
            self.assertIn("### Sayfa 1 (Yerel OCR)", pdf_raw)
            self.assertIn(expected_note, pdf_raw)
            self.assertIn("### Sayfa 1 (Yerel OCR)", tiff_raw)
            self.assertIn("### Sayfa 2 (Yerel OCR)", tiff_raw)
            self.assertIn(expected_note, tiff_raw)


class Test4_UyapEvrakAdlariKorunumu(unittest.TestCase):
    """Standart UYAP/adli belge adlarının kişi adı sanılmaması ve path'te korunması."""

    DOC_NAMES = [
        "Reddiyat Fişi",
        "Posta Reddiyat",
        "Sayman Mutemet Alındısı",
        "Tahsilat Makbuzu",
        "Dosyanın Birime Gönderilmesi",
        "Dosyanın İade Edilmesi",
        "Kapalı Tebligat",
        "E-Tebliğ Mazbatası",
        "Dava Açılış Formu",
        "Vekalet Pulu Makbuzu",
        "Ara Karar Cevabı",
    ]

    def test_uyap_doc_names_never_registered_as_persons(self):
        reg = MaskRegistry()
        for doc_name in self.DOC_NAMES:
            reg.add_person(doc_name, "KİŞİ", strong=True)
            reg.add_person(doc_name.upper(), "DAVACI", strong=True)
            snippet = (
                f"# {doc_name}.pdf\n\n"
                f"DAVACI : {doc_name}\n"
                f"Adı Soyadı : {doc_name.upper()}\n"
                f"TANIK\n{doc_name.upper()}\n\n"
                f"| Evrak Türü | Dosya Adı |\n|---|---|\n| {doc_name} | {doc_name.replace(' ', '_')}.pdf |\n"
            )
            UyapRedactor.collect_persons_from_text(snippet, reg)
        UyapRedactor.collect_persons_from_json(
            [
                {"evrakTuru": "Sayman Mutemet Alındısı", "ad": "Reddiyat Fişi"},
                {"dosyaAdi": "Dosyanin_Iade_Edilmesi.udf", "taraf": "Posta Reddiyat"},
                {"taraf": "Ara Karar Cevabı", "sifat": "Diğer"},
            ],
            reg,
        )
        reg.freeze_persons()
        self.assertEqual(reg.person_map(), {}, f"Sahte kişi öğrenildi: {reg.person_map()}")

    def test_redact_path_segment_protects_uyap_doc_names_while_masking_real_person(self):
        reg = MaskRegistry()
        reg.add_person("Ahmet Yılmaz", "DAVACI", strong=True)
        # Normal dışı bir senaryoda tekil ad/soyad çakışsa bile evrak kelimeleri korunmalı
        reg.freeze_persons()

        for doc_name in self.DOC_NAMES:
            seg = doc_name.replace(" ", "_") + ".pdf"
            out = UyapRedactor.redact_path_segment(seg, registry=reg, is_file=True)
            self.assertEqual(out, seg, f"Dosya adı yanlış maskelendi: {seg} -> {out}")

        mixed = "Sayman_Mutemet_Alindisi_Ahmet_Yilmaz.pdf"
        out_mixed = UyapRedactor.redact_path_segment(mixed, registry=reg, is_file=True)
        self.assertIn("Sayman_Mutemet_Alindisi_", out_mixed)
        self.assertIn("[DAVACI_1]", out_mixed)
        self.assertNotIn("Ahmet", out_mixed)
        self.assertNotIn("Yilmaz", out_mixed)


class Test5_OcrBulanikKisiMaskeleme(unittest.TestCase):
    """OCR'lı/bozuk metinlerde önceden keşfedilmiş tam ad-soyadların bulanık eşlenmesi."""

    def _make_reg(self, ad_gorunumu="etiket"):
        reg = MaskRegistry()
        reg.name_display = ad_gorunumu
        reg.add_person("Ahmet Yılmaz", "DAVACI", strong=True)
        reg.add_person("Çağlar Şahin", "DAVALI", strong=True)
        reg.add_person("Gülşen Doğan", "TANIK", strong=True)
        reg.freeze_persons()
        return reg

    def test_ocr_and_corrupted_pdf_fuzzy_name_masking(self):
        reg = self._make_reg()
        ocr_doc = (
            "# tarama.pdf\n\n### Sayfa 1 (Yerel OCR)\n\n"
            "Davacı Ahmet Ytlmaz tarafından sunulan dilekçede, Ahmet Yrlmaz ve Ahmet Y1lmaz "
            "ile Ahrnet Yılmaz'ln beyanları incelenmiştir. Ayrıca Ahmet Yılmaz'm talebi "
            "ve Ahrnet Yılmazln imzası yer almaktadır.\n"
            "Davalı Qa[lar Qahin ile tanık Gulsen Do[an duruşmada hazır bulundu.\n"
            "Ankara 5. Asliye Hukuk Mahkemesi ve Adalet Bakanlığı yazısı korunmalıdır.\n"
        )
        out, stats = UyapRedactor.redact_text(ocr_doc, registry=reg)
        for leaked in ("Ytlmaz", "Yrlmaz", "Y1lmaz", "Ahrnet", "Qa[lar", "Qahin", "Do[an", "Gulsen"):
            self.assertNotIn(leaked, out, f"OCR bozuk ad kaçtı ({leaked}):\n{out}")
        self.assertIn("[DAVACI_1]", out)
        self.assertIn("[DAVALI_1]", out)
        self.assertIn("[TANIK_1]", out)
        self.assertIn("Ankara 5. Asliye Hukuk Mahkemesi", out)
        self.assertIn("Adalet Bakanlığı", out)
        self.assertGreaterEqual(stats["kisi"], 8)

        # Bozuk PDF gömülü katmanı ((Yerel OCR) etiketi olmadan da)
        corrupted_pdf = (
            "Mahkemece dtizenlenmig olan bu tutanak qok eks1k ve tar1h1 1510312023 [sayfa$1] "
            "olup Ahmet Ytlmaz ve Qa[lar Qahin hazırdır."
        )
        out_corrupt, _ = UyapRedactor.redact_text(corrupted_pdf, registry=self._make_reg())
        self.assertNotIn("Ytlmaz", out_corrupt)
        self.assertNotIn("Qa[lar", out_corrupt)
        self.assertIn("[DAVACI_1]", out_corrupt)
        self.assertIn("[DAVALI_1]", out_corrupt)

    def test_clean_non_ocr_text_does_not_apply_fuzzy_matching(self):
        reg = self._make_reg()
        clean_doc = "Temiz dijital metinde Ahmet Ytlmaz değil başka bir ifade ve Ankara 5. Asliye Hukuk Mahkemesi vardır."
        out, _ = UyapRedactor.redact_text(clean_doc, registry=reg)
        # Temiz metinde bulanık eşleme devreye girmemelidir
        self.assertIn("Ahmet Ytlmaz", out)
        self.assertIn("Ankara 5. Asliye Hukuk Mahkemesi", out)

    def test_ocr_fuzzy_respects_bas_harf_and_avukat_block(self):
        reg = self._make_reg(ad_gorunumu="bas_harf")
        ocr_doc = (
            "### Taranmış Belge (Yerel OCR)\n\n"
            "Davacı Ahrnet Ytlmaz beyanında bulundu; vekili Av. Ahmet Ytlmaz değildir.\n"
        )
        out, _ = UyapRedactor.redact_text(ocr_doc, registry=reg)
        self.assertIn("Ahmet Y. [DAVACI_1]", out)
        self.assertNotIn("Ahrnet Ytlmaz", out)
        # Av. ön ekli vekil bağlamı korunmalıdır
        self.assertIn("Av. Ahmet Ytlmaz", out)


class Test6_EntegrasyonVeGercekKontrast(unittest.TestCase):
    """Gerçek kontrast artırma çıktısı ve uçtan uca izole temiz klasör entegrasyonu."""

    def test_enhance_image_for_ocr_stretches_dark_low_contrast_image(self):
        from PIL import Image, ImageDraw

        with tempfile.TemporaryDirectory() as tmp:
            dark_p = os.path.join(tmp, "koyu.png")
            im = Image.new("RGB", (300, 120), (30, 30, 30))
            draw = ImageDraw.Draw(im)
            draw.rectangle((40, 35, 260, 85), fill=(48, 48, 48))
            im.save(dark_p, "PNG")
            im.close()

            outs = UyapRedactor._enhance_image_for_ocr(dark_p, tmp, "test")
            self.assertEqual(len(outs), 2)
            with Image.open(outs[0]) as enh_im:
                lo, hi = enh_im.getextrema()
                self.assertEqual(lo, 0)
                self.assertGreaterEqual(hi, 200)
            with Image.open(outs[1]) as bin_im:
                self.assertEqual(bin_im.mode, "1")

    def test_export_isolated_clean_folder_end_to_end_with_5_fixes(self):
        import fitz
        from PIL import Image
        import audit_output

        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "dava")
            dest = os.path.join(tmp, "dava (Maskelenmis AI)")
            os.makedirs(src, exist_ok=True)

            # 1. Taraf keşfi için temiz dilekçe
            with open(os.path.join(src, "Dava_Acilis_Formu.md"), "w", encoding="utf-8") as f:
                f.write(
                    "# Dava Açılış Formu\n\n"
                    "DAVACI : Ahmet Yılmaz (T.C. Kimlik No: 10000000146)\n"
                    "DAVALI : Çağlar Şahin\n"
                )
            # 2. Standart UYAP evrak adlı ekler
            with open(os.path.join(src, "Sayman_Mutemet_Alindisi.md"), "w", encoding="utf-8") as f:
                f.write("Sayman Mutemet Alındısı tutarı 1.250,00 TL olup Tahsilat Makbuzu kesilmiştir.\n")

            # 3. Okunamayan koyu taranmış TIFF ve 16x17 küçük simge
            tiff_p = os.path.join(src, "Kapali_Tebligat.tif")
            Image.new("RGB", (300, 300), (25, 25, 25)).save(tiff_p, "TIFF")
            Image.new("RGB", (16, 17), "white").save(os.path.join(src, "logo.png"), "PNG")

            # 4. Bozuk gömülü PDF katmanı
            pdf_p = os.path.join(src, "Reddiyat_Fisi.pdf")
            doc = fitz.open()
            pg = doc.new_page()
            pg.insert_text(
                (40, 60),
                "Mahkemece dtizenlenmig qok bozuk evrak 1510312023 [sayfa$1] eks1k",
            )
            doc.save(pdf_p)
            doc.close()

            def fake_vision(path_p):
                if "tiff" in os.path.basename(path_p) or "Kapali_Tebligat" in path_p or "single" in os.path.basename(path_p):
                    return True, []
                return True, [
                    "Reddiyat Fişi kapsamında davacı Ahmet Ytlmaz ve davalı Qa[lar Qahin adına işlem yapılmıştır.",
                ]

            with patch.object(UyapRedactor, "_vision_ocr_image", side_effect=fake_vision):
                out_dir, stats = UyapRedactor.export_isolated_clean_folder(src, dest)

            self.assertEqual(stats["small_images_skipped"], 1)
            self.assertTrue(os.path.isfile(os.path.join(out_dir, "Sayman_Mutemet_Alindisi.md")))
            self.assertTrue(os.path.isfile(os.path.join(out_dir, "Kapali_Tebligat.md")))
            self.assertTrue(os.path.isfile(os.path.join(out_dir, "Reddiyat_Fisi.md")))

            with open(os.path.join(out_dir, "Kapali_Tebligat.md"), encoding="utf-8") as f:
                kapali_txt = f.read()
            self.assertIn("düşük kontrast/tarama kalitesi nedeniyle yerel OCR ile metin okunamadı", kapali_txt)

            with open(os.path.join(out_dir, "Reddiyat_Fisi.md"), encoding="utf-8") as f:
                red_txt = f.read()
            self.assertNotIn("Ytlmaz", red_txt)
            self.assertNotIn("Qa[lar", red_txt)
            self.assertIn("[DAVACI_1]", red_txt)
            self.assertIn("[DAVALI_1]", red_txt)

            audit_res = audit_output.audit(src, out_dir)
            _lines, _det, has_leak = audit_output.summarize(audit_res)
            self.assertFalse(has_leak, f"Audit sızıntısı: {audit_res}")
            self.assertEqual(audit_res["mapping_leak"], [])


if __name__ == "__main__":
    unittest.main()
