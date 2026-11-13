#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_output.py birim testleri — tüm değerler UYDURMADIR."""

import io
import os
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import audit_output as A  # noqa: E402


def fake_tckn(first9: str) -> str:
    d = [int(c) for c in first9]
    d10 = ((d[0] + d[2] + d[4] + d[6] + d[8]) * 7 - (d[1] + d[3] + d[5] + d[7])) % 10
    return first9 + str(d10) + str((sum(d) + d10) % 10)


T1 = fake_tckn("123456789")
IBAN = "TR120006400000112345678901"


class AuditCase(unittest.TestCase):

    def _case(self, src_files, out_files):
        tmp = tempfile.mkdtemp()
        src, out = os.path.join(tmp, "src"), os.path.join(tmp, "out")
        for base, files in ((src, src_files), (out, out_files)):
            for rel, content in files.items():
                p = os.path.join(base, rel)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                mode = "wb" if isinstance(content, bytes) else "w"
                with open(p, mode, **({} if mode == "wb" else {"encoding": "utf-8"})) as f:
                    f.write(content)
        return src, out

    def test_mask_regex_old_and_numbered(self):
        for lab in ("[TCKN_GİZLENDİ]", "[TCKN_3]", "[SİCİL_12]", "[ADRES_1]", "[KİMLİK_MRZ_KODU_GİZLENDİ]"):
            self.assertTrue(A.MASK_RE.fullmatch(lab), lab)
        self.assertEqual(A.mask_kind("[TELEFON_GİZLENDİ]"), "TEL")
        self.assertEqual(A.mask_kind("[SİCİL_4]"), "SİCİL")

    def test_detects_leaks(self):
        out_text = (f"TCKN {T1}\nIBAN: TR12 0006 4000 0011 2345 6789 01\nTel: 0532 111 22 33\n"
                    "Ali Örnek - Lale Mah. Gül Sk. No:12 Merkez/BURDUR\n"
                    "### TR9900\n\n### 064000 \n\n### 001123 \n\n### 456789 \n\n### 01\n")
        src, out = self._case({"a.md": out_text}, {"a.md": out_text})
        res = A.audit(src, out)
        L = res["leaks"]
        self.assertEqual(len(L["tckn"]), 1)
        self.assertEqual(len(L["iban"]), 1)
        self.assertEqual(len(L["phone"]), 1)
        self.assertEqual(len(L["addr_kisi"]), 1)
        self.assertEqual(len(L["iban_multiline"]), 1)
        _lines, _det, leak = A.summarize(res)
        self.assertTrue(leak)

    def test_institution_and_olay_address_not_person(self):
        t = ("Adres : Örnek Bankası A.Ş. Genel Müdürlüğü Çam Mah. Tersane Cad. No:15 Pendik\n"
             "SUÇUN YERİ : Kardelen Mah. Zambak Cad. No:5 önünde\n")
        src, out = self._case({"a.md": t}, {"a.md": t})
        L = A.audit(src, out)["leaks"]
        self.assertEqual(len(L["addr_kisi"]), 0)
        self.assertEqual(len(L["addr_kurum"]), 1)
        self.assertEqual(len(L["addr_olay"]), 1)

    def test_over_masking_and_flags(self):
        s = "Karar tarihi 12.03.2024 esas 2024/55 TCKN 11111 son\nAdres: Lale Mah. Gül Sk. No:3\n"
        o = "Karar tarihi [ADRES_1] TCKN [TCKN_1] son\nAdres: [ADRES_2]\n"
        src, out = self._case({"a.md": s}, {"a.md": o})
        res = A.audit(src, out)
        pieces = {(x[2], x[3]) for x in res["over"]}
        self.assertIn(("[ADRES_1]", "12.03.2024 esas 2024/55"), pieces)
        self.assertIn(("[ADRES_2]", "Lale Mah. Gül Sk. No:3"), pieces)
        flagged = [x for x in res["over"] if x[4]]
        self.assertEqual(len(flagged), 1)
        self.assertIn("tarih", flagged[0][4])
        # Kaybolan tarih ve esas no E bölümünde görünür
        self.assertTrue(res["preserve_lost"]["tarih"])
        self.assertTrue(res["preserve_lost"]["esas_yil"])

    def test_consistency_conflict(self):
        t2 = fake_tckn("234567891")
        s = f"A {T1}\nB {t2}\nC {T1}\n"
        o = "A [TCKN_1]\nB [TCKN_1]\nC [TCKN_2]\n"
        src, out = self._case({"a.md": s}, {"a.md": o})
        res = A.audit(src, out)
        self.assertTrue(res["consistency_value_multi_label"])
        self.assertTrue(res["consistency_label_multi_value"])

    def test_structure_checks(self):
        idx = "| Dosya | Metin |\n|---|---|\n| x | [↗](<b.md>) (3 karakter) |\n[kopuk](<yok.md>) `[örnek](<göreli yol>)`\n"
        src, out = self._case(
            {"INDEX.md": idx, "b.md": "12345", "yok.md": "kaynakta var"},
            {"INDEX.md": idx, "b.md": "12345", "c.pdf": b"%PDF", "esleme.md": "[TCKN_1] = 12345678901"},
        )
        res = A.audit(src, out)
        self.assertEqual(res["binary_files"], ["c.pdf"])
        self.assertEqual(len(res["broken_links"]), 1)  # kod içindeki örnek sayılmaz
        self.assertEqual(len(res["index_mismatch"]), 1)
        self.assertIn("esleme.md", res["mapping_leak"])
        self.assertIn("esleme.md", res["unexpected_files"])

    # --- Toplu denetimde bulunan yanlış alarm sınıfları (gerekçeli düzeltmeler) ---
    def test_hex_hash_tokens_are_not_tckn(self):
        # JSON meta verisindeki sha256 vb. onaltılık özetler rastgele 11 haneli geçerli sayı içerebilir
        h = "ab" + T1 + "cd" + "e" * 40
        t = f'{{"sha256": "{h}", "x": 1}}\n'
        src, out = self._case({"a.md": t}, {"a.md": t})
        L = A.audit(src, out)["leaks"]
        self.assertEqual(len(L["tckn"]), 0)
        self.assertEqual(len(L["tckn_known"]), 0)
        # Gerçek bir TCKN yine yakalanır
        t2 = t + f"TCKN {T1}\n"
        src, out = self._case({"a.md": t2}, {"a.md": t2})
        self.assertEqual(len(A.audit(src, out)["leaks"]["tckn"]), 1)

    def test_mapping_leak_needs_matching_value_shape_same_line(self):
        table = ": [TCKN_1] : 12345678 : 12.03.2024 10:30 : SGK\n[ADRES_2]\n: 12345678\n"
        src, out = self._case({"a.md": table}, {"a.md": table})
        self.assertEqual(A.audit(src, out)["mapping_leak"], [])
        real = "[TCKN_1] = " + T1 + "\n"
        src, out = self._case({"b.md": real}, {"b.md": real})
        self.assertEqual(A.audit(src, out)["mapping_leak"], ["b.md"])
        real2 = "[IBAN_1]: " + IBAN + "\n"
        src, out = self._case({"b.md": real2}, {"b.md": real2})
        self.assertEqual(A.audit(src, out)["mapping_leak"], ["b.md"])

    def test_preservation_ignores_link_targets_and_image_note(self):
        s = ("| [(Ek 1)DİĞER (2024/123).tif](<(Ek 1)DİĞER (2024/123).tif>) | [↗](<(Ek 1)DİĞER (2024/123).pdf>) |\n"
             "> **Görseller:** Bu belgedeki 2 görsel `Yakalama (CMK 90)/` klasörüne çıkarıldı.\n")
        o = ("| [(Ek 1)DİĞER (2024/123).tif (OCR metni)](<(Ek 1)DİĞER (2024/123).md>) | — |\n"
             "> **Görseller:** güvenlik gereği aktarılmadı.\n")
        src, out = self._case({"a.md": s}, {"a.md": o})
        res = A.audit(src, out)
        self.assertEqual(sum(x[2] for x in res["preserve_lost"]["esas_yil"]), 0)
        self.assertEqual(sum(x[2] for x in res["preserve_lost"]["kanun"]), 0)
        # İçerikteki kayıp yine görülür
        s2, o2 = "Karar 12.03.2024 verildi\n", "Karar [ADRES_1] verildi\n"
        src, out = self._case({"a.md": s2}, {"a.md": o2})
        self.assertTrue(A.audit(src, out)["preserve_lost"]["tarih"])

    def test_form_template_phrase_is_not_address(self):
        t = "Tebligatın yapılacağı (caddesi / sokağı) ile açık adres bildirilmelidir.\n"
        src, out = self._case({"a.md": t}, {"a.md": t})
        L = A.audit(src, out)["leaks"]
        self.assertEqual(len(L["addr_kisi"]) + len(L["addr_kurum"]) + len(L["addr_olay"]), 0)

    def test_consistency_ignores_invalid_ocr_variants_of_same_label(self):
        # Aynı etiket: geçerli TCKN + onun OCR bozulmuş (geçersiz) varyantı -> çelişki değil
        bad = T1[:-1] + str((int(T1[-1]) + 1) % 10)
        s = f"A {T1}\nB {bad}\n"
        o = "A [TCKN_1]\nB [TCKN_1]\n"
        src, out = self._case({"a.md": s}, {"a.md": o})
        self.assertFalse(A.audit(src, out)["consistency_label_multi_value"])
        # İki farklı geçerli TCKN aynı etikette -> çelişki
        t2 = fake_tckn("234567891")
        s = f"A {T1}\nB {t2}\n"
        src, out = self._case({"a.md": s}, {"a.md": o})
        self.assertTrue(A.audit(src, out)["consistency_label_multi_value"])

    def test_link_broken_in_source_too_is_not_counted(self):
        # Kaynakta da bulunmayan .md hedefi: aracın değil kaynağın kusuru (ayrı raporlanır)
        s = "[Tensip](<01/yok.md>) ve [var](<b.md>)\n"
        src, out = self._case({"dava.md": s, "b.md": "x"}, {"dava.md": s})
        res = A.audit(src, out)
        self.assertEqual([x[1] for x in res["broken_links"]], ["b.md"])
        self.assertEqual([x[1] for x in res["source_broken_links"]], ["01/yok.md"])

    def test_person_address_not_hidden_by_distant_institution_context(self):
        # MERNİS satırı: iki satır yukarıda "Genel Müdürlüğü" geçse de kişi adresidir
        t = ("Bilginin Alındığı Kurum İçişleri Bakanlığı Nüfus Genel Müdürlüğü\n\n"
             "**MERNİS (Yurtiçi) Adres Bilgisi** Mahalle :TESTTEPE MAH. Cd./Sk./Bul./Mev :DENEME CAD. Kapı No :12/3 İlçe :MERKEZ\n")
        src, out = self._case({"a.md": t}, {"a.md": t})
        L = A.audit(src, out)["leaks"]
        self.assertEqual(len(L["addr_kisi"]), 1)
        # Kurum adı aynı satırda veya hemen önceki satırda ise kurum
        t2 = "Örnek Bankası A.Ş. Genel Müdürlüğü\nÇam Mah. Tersane Cad. No:15 Pendik\n"
        src, out = self._case({"b.md": t2}, {"b.md": t2})
        L = A.audit(src, out)["leaks"]
        self.assertEqual((len(L["addr_kisi"]), len(L["addr_kurum"])), (0, 1))
        # "adresini ..." ifadesi kişi adresidir, aynı satırda müdürlük geçse de
        t3 = 'Serbestlik Müdürlüğü aracılığıyla; adresini "Şehit Kuzey Sok. Testtepe Mah. No:12 Silivri"\n'
        src, out = self._case({"c.md": t3}, {"c.md": t3})
        self.assertEqual(len(A.audit(src, out)["leaks"]["addr_kisi"]), 1)

    def test_business_building_next_line_and_two_lines_up_context_is_kurum(self):
        cases = {
            "a.md": "**Adres : **Test Mahallesi, Gül Caddesi, Örnek Plaza, No:12, BUCAK/BURDUR.\n",
            "b.md": "PAPATYA MAH. ZAMBAK CAD.\nMİLLİ EĞİTİM MÜDÜRLÜĞÜ NO: 3 BURDUR\n",
            "c.md": "ÖRNEK KATILIM BANKASI A.Ş\nBurdur Subesi\nNs:12 Test Mahallesi Menekşe Caddesi\n",
        }
        for name, t in cases.items():
            src, out = self._case({name: t}, {name: t})
            L = A.audit(src, out)["leaks"]
            self.assertEqual((len(L["addr_kisi"]), len(L["addr_kurum"])), (0, 1), name)

    def test_event_description_with_evrak_no_in_link_is_not_address(self):
        t = ("| 12.03.2024 | Lalezar Mahallesi Uygulama Noktasında aracı durduruldu. | "
             "[Kolluk (OCR metni)](<_ilgili/x/Kolluk_12.md>) (12.03.2024, evrak no 4521) |\n")
        src, out = self._case({"a.md": t}, {"a.md": t})
        L = A.audit(src, out)["leaks"]
        self.assertEqual(len(L["addr_kisi"]) + len(L["addr_kurum"]) + len(L["addr_olay"]), 0)

    def test_stdout_has_no_raw_values_and_exit_code(self):
        t = f"TCKN {T1} IBAN {IBAN}\n"
        src, out = self._case({"a.md": t}, {"a.md": t})
        det = os.path.join(os.path.dirname(src), "det.txt")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = A.main([src, out, "--details", det])
        self.assertEqual(rc, 1)
        self.assertNotIn(T1, buf.getvalue())
        self.assertNotIn(IBAN, buf.getvalue())
        with open(det, encoding="utf-8") as f:
            self.assertIn(T1, f.read())

    def test_ocr_cache_used_as_source(self):
        tmp = tempfile.mkdtemp()
        src, out, cache = (os.path.join(tmp, x) for x in ("src", "out", "cache"))
        for d in (src, out, cache):
            os.makedirs(d)
        with open(os.path.join(cache, "t.md"), "w", encoding="utf-8") as f:
            f.write(f"TCKN: {T1}\n")
        with open(os.path.join(out, "t.md"), "w", encoding="utf-8") as f:
            f.write("TCKN: [TCKN_1]\n")
        res = A.audit(src, out, cache)
        self.assertEqual(res["files_with_source"], 1)
        self.assertEqual(res["over"][0][3], T1)

    @staticmethod
    def _write_udf(path: str, content_text: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        xml_body = (
            '<?xml version="1.0" encoding="UTF-8" ?>'
            f'<template format_id="1.8"><content><![CDATA[{content_text}]]></content></template>'
        )
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("content.xml", xml_body.encode("utf-8"))

    def test_udf_source_clean_output_has_no_leaks(self):
        """UDF kaynak + doğru maskeli çıktı: sızıntı 0, beklenmedik dosya 0, files_with_source == 1."""
        tmp = tempfile.mkdtemp()
        src, out = os.path.join(tmp, "src"), os.path.join(tmp, "out")
        os.makedirs(out)
        self._write_udf(
            os.path.join(src, "dilekce.udf"),
            f"DOSYA NO: 2026/100\nDavacı TCKN: {T1}\nTalep dilekçesi metni.",
        )
        with open(os.path.join(out, "dilekce.md"), "w", encoding="utf-8") as f:
            f.write("DOSYA NO: 2026/100\nDavacı TCKN: [TCKN_1]\nTalep dilekçesi metni.")
        res = A.audit(src, out)
        _lines, _det, leak = A.summarize(res)
        self.assertFalse(leak)
        self.assertEqual(res["unexpected_files"], [])
        self.assertEqual(res["files_with_source"], 1)

    def test_udf_source_unmasked_tckn_detected_as_leak(self):
        """UDF kaynak + TCKN'si maskelenmemiş çıktı: sızıntı >= 1 yakalanmalı."""
        tmp = tempfile.mkdtemp()
        src, out = os.path.join(tmp, "src"), os.path.join(tmp, "out")
        os.makedirs(out)
        self._write_udf(
            os.path.join(src, "tutanak.udf"),
            f"DOSYA NO: 2026/101\nDavacı TCKN: {T1}\nDuruşma tutanağı.",
        )
        with open(os.path.join(out, "tutanak.md"), "w", encoding="utf-8") as f:
            f.write(f"DOSYA NO: 2026/101\nDavacı TCKN: {T1}\nDuruşma tutanağı.")
        res = A.audit(src, out)
        _lines, _det, leak = A.summarize(res)
        self.assertTrue(leak)
        total_tckn_leaks = len(res["leaks"]["tckn"]) + len(res["leaks"]["tckn_known"])
        self.assertGreaterEqual(total_tckn_leaks, 1)

    def test_kaynak_udf_matches_top_level_md_output(self):
        """_kaynak/x.udf kaynak dosyası kökteki x.md çıktısıyla eşleşir."""
        tmp = tempfile.mkdtemp()
        src, out = os.path.join(tmp, "src"), os.path.join(tmp, "out")
        os.makedirs(out)
        self._write_udf(
            os.path.join(src, "_kaynak", "x.udf"),
            f"DOSYA NO: 2026/102\nTaraf TCKN: {T1}\nİçerik satırı.",
        )
        with open(os.path.join(out, "x.md"), "w", encoding="utf-8") as f:
            f.write("DOSYA NO: 2026/102\nTaraf TCKN: [TCKN_1]\nİçerik satırı.")
        res = A.audit(src, out)
        _lines, _det, leak = A.summarize(res)
        self.assertFalse(leak)
        self.assertEqual(res["unexpected_files"], [])
        self.assertEqual(res["files_with_source"], 1)
        self.assertEqual(res["over"][0][3], T1)


if __name__ == "__main__":
    unittest.main()
