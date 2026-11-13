#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_output.py birim testleri — tüm değerler UYDURMADIR."""

import io
import os
import sys
import tempfile
import unittest
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
            {"INDEX.md": idx, "b.md": "12345"},
            {"INDEX.md": idx, "b.md": "12345", "c.pdf": b"%PDF", "esleme.md": "[TCKN_1] = 12345678901"},
        )
        res = A.audit(src, out)
        self.assertEqual(res["binary_files"], ["c.pdf"])
        self.assertEqual(len(res["broken_links"]), 1)  # kod içindeki örnek sayılmaz
        self.assertEqual(len(res["index_mismatch"]), 1)
        self.assertIn("esleme.md", res["mapping_leak"])
        self.assertIn("esleme.md", res["unexpected_files"])

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


if __name__ == "__main__":
    unittest.main()
