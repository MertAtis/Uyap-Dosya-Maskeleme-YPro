#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.5.2 testleri: .pages metin çıkarma ve denetimin kaynak eşleme / hizalama iyileştirmeleri.

Tüm değerler UYDURMADIR (gerçek kişi, adres veya numara içermez)."""

import os
import sys
import tempfile
import unittest
import zipfile

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import audit_output as A  # noqa: E402
from uyap_redactor import UyapRedactor  # noqa: E402


def fake_tckn(first9: str) -> str:
    d = [int(c) for c in first9]
    d10 = ((d[0] + d[2] + d[4] + d[6] + d[8]) * 7 - (d[1] + d[3] + d[5] + d[7])) % 10
    return first9 + str(d10) + str((sum(d) + d10) % 10)


T1 = fake_tckn("123456789")


# ---------------------------------------------------------------------------
# Test yardımcıları: Snappy (yalnız literal) + protobuf + IWA + .pages üretimi
# ---------------------------------------------------------------------------
def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _snappy_literal(data: bytes) -> bytes:
    out = bytearray(_varint(len(data)))
    pos = 0
    while pos < len(data):
        chunk = data[pos:pos + 60]
        out.append((len(chunk) - 1) << 2)
        out += chunk
        pos += len(chunk)
    return bytes(out)


def _pb_len(field: int, payload: bytes) -> bytes:
    return _varint((field << 3) | 2) + _varint(len(payload)) + payload


def _pb_int(field: int, value: int) -> bytes:
    return _varint(field << 3) + _varint(value)


def _iwa_record(msg_type: int, payload: bytes) -> bytes:
    minfo = _pb_int(1, msg_type) + _pb_int(3, len(payload))
    info = _pb_int(1, 1) + _pb_len(2, minfo)
    return _varint(len(info)) + info + payload


def _make_pages(path: str, paragraphs, msg_type: int = 2001, extra_noise: bool = True) -> None:
    text_payload = b"".join(_pb_len(3, p.encode("utf-8")) for p in paragraphs)
    stream = b""
    if extra_noise:
        # Metin deposu olmayan bir ileti: içindeki dize çıkarılmamalı
        stream += _iwa_record(3005, _pb_len(3, b"METIN-DEGIL"))
    stream += _iwa_record(msg_type, text_payload)
    comp = _snappy_literal(stream)
    iwa = b"\x00" + len(comp).to_bytes(3, "little") + comp
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("Index/Document.iwa", iwa)
        zf.writestr("Metadata/Properties.plist", b"<plist/>")


class SnappyTests(unittest.TestCase):
    def test_literal_ve_kopya(self):
        # "abcdabcdabcd": literal 'abcd' + 2 baytlık ofsetli kopya (uzunluk 8, ofset 4)
        raw = _varint(12) + bytes([(4 - 1) << 2]) + b"abcd" + bytes([((8 - 1) << 2) | 2]) + (4).to_bytes(2, "little")
        self.assertEqual(UyapRedactor._snappy_raw_decompress(raw), b"abcdabcdabcd")

    def test_bir_baytlik_ofset_kopya(self):
        # kind=1: uzunluk 4+((tag>>2)&7), ofset ((tag>>5)<<8)|sonraki bayt
        raw = _varint(10) + bytes([(2 - 1) << 2]) + b"xy" + bytes([((8 - 4) << 2) | 1, 2])
        self.assertEqual(UyapRedactor._snappy_raw_decompress(raw), b"xyxyxyxyxy")

    def test_bozuk_girdi_hata_verir(self):
        with self.assertRaises(ValueError):
            UyapRedactor._snappy_raw_decompress(_varint(5) + bytes([((4 - 1) << 2) | 2]) + (9).to_bytes(2, "little"))
        with self.assertRaises(ValueError):
            UyapRedactor._snappy_raw_decompress(_varint(100) + bytes([0]) + b"a")  # uzunluk uyuşmazlığı


class PagesExtractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_paragraflar_cikarilir_ve_metin_degil_iletiler_atlanir(self):
        p = os.path.join(self.tmp, "belge.pages")
        _make_pages(p, ["Birinci paragraf Çağlar Şişli", "İkinci satır üçüncü"])
        txt = UyapRedactor.extract_pages_raw(p)
        self.assertIn("Birinci paragraf Çağlar Şişli", txt)
        self.assertIn("üçüncü", txt)
        self.assertNotIn("METIN-DEGIL", txt)

    def test_tanimsiz_veya_bozuk_dosya_bos_doner(self):
        bad = os.path.join(self.tmp, "bozuk.pages")
        with open(bad, "wb") as f:
            f.write(b"zip degil")
        self.assertEqual(UyapRedactor.extract_pages_raw(bad), "")
        nodoc = os.path.join(self.tmp, "bos.pages")
        with zipfile.ZipFile(nodoc, "w") as zf:
            zf.writestr("Metadata/Properties.plist", b"<plist/>")
        self.assertEqual(UyapRedactor.extract_pages_raw(nodoc), "")
        trunc = os.path.join(self.tmp, "kesik.pages")
        _make_pages(trunc, ["x" * 200])
        with zipfile.ZipFile(trunc, "r") as zf:
            blob = zf.read("Index/Document.iwa")
        with zipfile.ZipFile(trunc, "w") as zf:
            zf.writestr("Index/Document.iwa", blob[: len(blob) // 2])
        self.assertEqual(UyapRedactor.extract_pages_raw(trunc), "")

    def test_uc_uzantisi_destekleniyor(self):
        self.assertIn(".pages", UyapRedactor.TEXT_DOC_EXTS)
        self.assertIn(".pages", UyapRedactor.OFFICE_DOC_EXTS)

    def test_tum_akis_pages_maskelenir_bozuk_pages_islenemeyen_listesinde(self):
        src = os.path.join(self.tmp, "Dava Klasörü")
        out = os.path.join(self.tmp, "cikti")
        os.makedirs(src)
        _make_pages(os.path.join(src, "protokol.pages"), [f"Tarafın TC kimlik numarası: {T1}", "Tarih: 01.02.2024"])
        with open(os.path.join(src, "bozuk.pages"), "wb") as f:
            f.write(b"zip degil")
        import subprocess
        r = subprocess.run(
            [sys.executable, os.path.join(current_dir, "uyap_redactor.py"), src, "--out", out],
            capture_output=True, text=True, timeout=300,
        )
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        md = os.path.join(out, "protokol.md")
        self.assertTrue(os.path.isfile(md), os.listdir(out))
        body = open(md, encoding="utf-8").read()
        self.assertNotIn(T1, body)
        self.assertIn("01.02.2024", body)
        report = open(os.path.join(out, "DAVA_DÖNÜŞÜM_VE_GÜVENLİK_RAPORU.md"), encoding="utf-8").read()
        self.assertIn("İşlenemeyen dosyalar", report)
        self.assertIn("bozuk.pages", report)  # sessizce atlanmaz, raporda yazılır
        self.assertNotIn("protokol.pages", report.split("İşlenemeyen dosyalar", 1)[1])


# ---------------------------------------------------------------------------
# Denetim: kaynak eşleme ve hizalama
# ---------------------------------------------------------------------------
class AuditV152Tests(unittest.TestCase):
    def _dirs(self):
        tmp = tempfile.mkdtemp()
        src, out, cache = (os.path.join(tmp, x) for x in ("src", "out", "cache"))
        for d in (src, out, cache):
            os.makedirs(d)
        return src, out, cache

    @staticmethod
    def _w(path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_etiketli_dosya_adi_iki_adaya_ragmen_tek_kaynaga_eslenir(self):
        """Kaynakta 'X.pdf' varsa aday listesinde 'X.md' ve 'X.pdf.md' birlikte bulunur; tek kaynaktır."""
        src, out, cache = self._dirs()
        with open(os.path.join(src, "VEKALET - Ayşe Örnek.pdf"), "wb") as f:
            f.write(b"%PDF-1.4 sahte")
        self._w(os.path.join(cache, "VEKALET - Ayşe Örnek.md"), f"Müvekkil No: {T1}\n")
        self._w(os.path.join(out, "VEKALET - [DAVACI_1].md"), "Müvekkil No: [TCKN_1]\n")
        res = A.audit(src, out, cache)
        self.assertEqual(res["files_with_source"], 1)
        self.assertEqual(res["masked_name_unmatched"], [])

    def test_gercekten_farkli_iki_kaynak_belirsiz_kalir(self):
        cands = ["VEKALET - Ali Veli.md", "VEKALET - Ayşe Örnek.md"]
        self.assertIsNone(A._match_masked_source_rel("VEKALET - [DAVACI_1].md", cands))
        self.assertEqual(
            A._match_masked_source_rel("VEKALET - [DAVACI_1].md", ["VEKALET - Ali Veli.md", "VEKALET - Ali Veli.pdf.md"]),
            "VEKALET - Ali Veli.md",
        )

    def test_tckn_ve_bolunmus_ad_satirlari_hizalanir(self):
        """Kaynakta TCKN / ad / soyad ayrı satırlarsa çıktıda [TCKN_1] ve tek kişi etiketi vardır."""
        src, out, cache = self._dirs()
        self._w(os.path.join(src, "nufus.md"), f"Kendisi\n{T1}\nAyşe\nÖrnek\nAnne\n")
        self._w(os.path.join(out, "nufus.md"), "Kendisi\n[TCKN_1]\n[DAVACI_1]\nAnne\n")
        res = A.audit(src, out)
        self.assertEqual(res["unaligned"], [])
        kinds = sorted(A.mask_kind(x[2]) for x in res["over"])
        self.assertEqual(kinds, ["DAVACI", "TCKN"])
        self.assertTrue(any(x[3] == T1 for x in res["over"]))

    def test_alakasiz_satir_yutulmasi_hizalanamayan_kalir(self):
        """Dar kural: ad olmayan (rakam/cümle içeren) kaynak satırları yutulursa hâlâ raporlanır."""
        src, out, cache = self._dirs()
        self._w(os.path.join(src, "n.md"), "Başlık\nbu satır tamamen yutuldu 123 sözleşme bedeli\nikinci uzun cümle de yutuldu\nSon\n")
        self._w(os.path.join(out, "n.md"), "Başlık\n[KİŞİ_1]\nSon\n")
        res = A.audit(src, out)
        self.assertTrue(res["unaligned"])

    def test_kisa_ad_takma_adi_celiski_sayilmaz(self):
        """Aynı etiketin hem tam ad hem yalnız ad değeri aynı kişidir (alt küme); farklı kişi çelişkidir."""
        src, out, cache = self._dirs()
        self._w(os.path.join(src, "a.md"), "Ali Veli geldi.\nSonra Ali konuştu.\n")
        self._w(os.path.join(out, "a.md"), "[DAVALI_1] geldi.\nSonra [DAVALI_1] konuştu.\n")
        res = A.audit(src, out)
        self.assertEqual(res["consistency_label_multi_value"], {})
        src2, out2, _ = self._dirs()
        self._w(os.path.join(src2, "a.md"), "Ali Veli geldi.\nSonra Hasan Kaya konuştu.\n")
        self._w(os.path.join(out2, "a.md"), "[DAVALI_1] geldi.\nSonra [DAVALI_1] konuştu.\n")
        res2 = A.audit(src2, out2)
        self.assertTrue(res2["consistency_label_multi_value"])

    def test_adres_devam_satiri_yutulmasi_beklenen_davranis(self):
        src, out, cache = self._dirs()
        self._w(os.path.join(src, "v.md"), "Av. Test Kişi\nAdres : Örnek Mah. Deneme Cad. No:1\nMERKEZ\nSon cümle burada.\n")
        self._w(os.path.join(out, "v.md"), "Av. Test Kişi\nAdres : [ADRES_1]\nSon cümle burada.\n")
        res = A.audit(src, out)
        self.assertEqual(res["unaligned"], [])


if __name__ == "__main__":
    unittest.main()
