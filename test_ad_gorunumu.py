#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Taraf/tanık ad görünümü (etiket | bas_harf | acik) testleri. Tüm veriler sentetiktir.

Kapsam: 3 görünüm × yargı adı gizli/açık × metin / dosya adı / bağlantı hedefi / INDEX / rapor,
'bas_harf' biçimi (Türkçe İ/ı, BÜYÜK HARF, 3-4 parçalı ad, aynı baş harfli kişiler, ek),
denetim aracının modları, CLI eski bayrak uyumu ve API uyumu.
Her test signal.alarm ile zaman aşımına karşı korunur.
"""

import os
import re
import signal
import subprocess
import sys
import tempfile
import unittest
from typing import Dict, Tuple

import audit_output
from uyap_redactor import MaskRegistry, UyapRedactor

HERE = os.path.dirname(os.path.abspath(__file__))

DOC = (
    "T.C.\nANKARA 3. SULH HUKUK MAHKEMESİ\n"
    "DAVACI : Ahmet YILMAZ\n"
    "DAVALI : Veli KARAKAYA\n"
    "Hâkim Ayşe ÖRNEKOĞLU 445566\n"
    "Katip Fatma DEMİRCAN 778899\n"
    "Davacı Ahmet YILMAZ dava açmıştır. Davalı Veli KARAKAYA'nın cevabı alınmıştır.\n"
    "Ahmet Yılmaz'ın iddiası yerindedir.\n"
)
SRC_NAME = "Ahmet_YILMAZ_karar.md"
INDEX = "# INDEX\n- [Ahmet YILMAZ dilekçe](Ahmet_YILMAZ_karar.md)\n"

# Yalnızca yargı adları (soyadlar ve ön adlar)
JUDGE_TOKENS = ("ÖRNEKOĞLU", "Ayşe", "DEMİRCAN", "Fatma")
PARTY_SURNAMES = ("YILMAZ", "Yılmaz", "KARAKAYA")


class _Base(unittest.TestCase):
    ALARM_SECONDS = 60

    def setUp(self) -> None:
        self._prev = signal.getsignal(signal.SIGALRM)

        def _on_alarm(signum, frame):
            raise TimeoutError(f"Test {self.ALARM_SECONDS}s içinde bitmedi")

        signal.signal(signal.SIGALRM, _on_alarm)
        signal.alarm(self.ALARM_SECONDS)
        self._tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self._tmp.name, "src")
        self.out = os.path.join(self._tmp.name, "out")
        os.makedirs(self.src)

    def tearDown(self) -> None:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, self._prev)
        self._tmp.cleanup()

    def write_src(self, docs: Dict[str, str]) -> None:
        for rel, body in docs.items():
            fp = os.path.join(self.src, rel)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, "w", encoding="utf-8", newline="") as f:
                f.write(body)

    def export(self, docs: Dict[str, str], ad: str, jud: bool = True, **kw) -> Dict[str, str]:
        """Dışa aktarır; çıktıdaki TÜM dosyaların adlarını ve içeriklerini döner (rapor ve INDEX dahil)."""
        self.write_src(docs)
        UyapRedactor.export_isolated_clean_folder(
            self.src, self.out, ad_gorunumu=ad, mask_judicial_names=jud, **kw
        )
        res: Dict[str, str] = {}
        for root, _d, files in os.walk(self.out):
            for fn in files:
                fp = os.path.join(root, fn)
                with open(fp, "r", encoding="utf-8") as f:
                    res[os.path.relpath(fp, self.out)] = f.read()
        return res

    @staticmethod
    def blob(outputs: Dict[str, str]) -> str:
        """Dosya adları + içerikler tek metinde (sızıntı aramak için)."""
        return "\n".join(list(outputs.keys()) + list(outputs.values()))

    @staticmethod
    def pick(outputs: Dict[str, str], suffix: str) -> Tuple[str, str]:
        for rel, txt in outputs.items():
            if rel.endswith(suffix):
                return rel, txt
        raise AssertionError(f"{suffix} bulunamadı: {sorted(outputs)}")

    def karar(self, outputs: Dict[str, str]) -> Tuple[str, str]:
        for rel, txt in outputs.items():
            if rel.endswith("_karar.md"):
                return rel, txt
        raise AssertionError(f"karar dosyası bulunamadı: {sorted(outputs)}")

    def assert_audit_clean(self, ad: str) -> Dict:
        res = audit_output.audit(self.src, self.out, ad_gorunumu=ad)
        lines, det, leak = audit_output.summarize(res)
        self.assertFalse(leak, "\n".join(lines) + "\n" + "\n".join(det[:10]))
        self.assertEqual(res["mapping_leak"], [])
        return res


class TestUcGorunumMatrisi(_Base):
    """3 görünüm × yargı gizli/açık: metin, dosya adı, bağlantı hedefi, INDEX, rapor."""

    def run_mode(self, ad: str, jud: bool) -> Dict[str, str]:
        outputs = self.export({SRC_NAME: DOC, "INDEX.md": INDEX}, ad, jud)
        if jud:
            self.assert_audit_clean(ad)
        else:
            # Yargı adları bilerek açık: denetim aracı bunları sızıntı sayar (yargı bayrağı yoktur);
            # bunun dışında hiçbir sızıntı olmamalı ve işaretlenenler yalnız yargı etiketleridir.
            res = audit_output.audit(self.src, self.out, ad_gorunumu=ad)
            for key, items in res["leaks"].items():
                if key == "person_name":
                    self.assertTrue(items)
                    for _rel, _ln, label in items:
                        self.assertTrue(MaskRegistry.is_judicial_label(label), f"{ad}: yargı dışı sızıntı {label}")
                else:
                    self.assertEqual(items, [], f"{ad}: beklenmeyen sızıntı {key}")
            self.assertEqual(res["mapping_leak"], [])
        return outputs

    def _judge_checks(self, outputs: Dict[str, str], jud: bool) -> None:
        _rel, text = self.karar(outputs)
        if jud:
            for tok in JUDGE_TOKENS:
                self.assertNotIn(tok, self.blob(outputs), f"yargı adı sızdı: {tok}")
            self.assertIn("[HAKİM_1]", text)
            self.assertIn("[KÂTİP_1]", text)
            # yargı adları hiçbir görünümde baş harfli yazılmaz
            self.assertNotIn("Ayşe Ö.", self.blob(outputs))
            self.assertNotIn("Fatma D.", self.blob(outputs))
        else:
            self.assertIn("Ayşe ÖRNEKOĞLU", text)
            self.assertIn("Fatma DEMİRCAN", text)
            self.assertNotIn("[HAKİM_1]", text)

    def test_etiket_yargi_gizli(self) -> None:
        o = self.run_mode("etiket", True)
        self._judge_checks(o, True)
        for tok in PARTY_SURNAMES + ("Ahmet", "Veli"):
            self.assertNotIn(tok, self.blob(o), f"etiket modunda ad sızdı: {tok}")
        _rel, t = self.karar(o)
        self.assertIn("DAVACI : [DAVACI_1]", t)
        self.assertIn("[DAVALI_1]'nın cevabı", t)

    def test_etiket_yargi_acik(self) -> None:
        o = self.run_mode("etiket", False)
        self._judge_checks(o, False)
        for tok in PARTY_SURNAMES + ("Ahmet", "Veli"):
            self.assertNotIn(tok, self.blob(o))

    def test_bas_harf_yargi_gizli(self) -> None:
        o = self.run_mode("bas_harf", True)
        self._judge_checks(o, True)
        rel, t = self.karar(o)
        self.assertIn("DAVACI : Ahmet Y. [DAVACI_1]", t)
        self.assertIn("DAVALI : Veli K. [DAVALI_1]", t)
        self.assertIn("Veli K. [DAVALI_1]'nın cevabı", t)
        # tam soyad hiçbir yerde (metin, dosya adı, bağlantı hedefi, INDEX, rapor) yok
        for tok in PARTY_SURNAMES + ("Veli KARAKAYA", "Ahmet Yılmaz"):
            self.assertNotIn(tok, self.blob(o), f"bas_harf modunda soyad sızdı: {tok}")
        # dosya adında yalnız etiket (ad bile yok)
        self.assertNotIn("Ahmet", rel)
        self.assertIn("[DAVACI_", rel)
        # INDEX: bağlantı METNİ baş harfli, bağlantı HEDEFİ yalnız etiket
        _ir, idx = self.pick(o, "INDEX.md")
        m = re.search(r"\[(?P<text>.*?)\]\((?P<target>[^)]*)\)", idx)
        self.assertIsNotNone(m, idx)
        self.assertIn("Ahmet Y. [", idx)
        self.assertNotIn("Ahmet", m.group("target"))
        self.assertIn("[DAVACI_", m.group("target"))

    def test_bas_harf_yargi_acik(self) -> None:
        o = self.run_mode("bas_harf", False)
        self._judge_checks(o, False)
        _rel, t = self.karar(o)
        self.assertIn("Ahmet Y. [DAVACI_1]", t)
        for tok in PARTY_SURNAMES:
            self.assertNotIn(tok, self.blob(o).replace("ÖRNEKOĞLU", ""))

    def test_acik_yargi_gizli(self) -> None:
        o = self.run_mode("acik", True)
        self._judge_checks(o, True)
        rel, t = self.karar(o)
        self.assertIn("DAVACI : Ahmet YILMAZ", t)
        self.assertIn("Veli KARAKAYA'nın cevabı", t)
        self.assertNotIn("[DAVACI_", t)
        self.assertEqual(rel, SRC_NAME)  # dosya adı olduğu gibi

    def test_acik_yargi_acik(self) -> None:
        o = self.run_mode("acik", False)
        self._judge_checks(o, False)
        _rel, t = self.karar(o)
        self.assertIn("DAVACI : Ahmet YILMAZ", t)

    def test_rapor_moda_gore_anlatir(self) -> None:
        o_bh = self.export({SRC_NAME: DOC}, "bas_harf", True)
        _r, rep = self.pick(o_bh, UyapRedactor.REPORT_NAME)
        self.assertIn("kısmi eşleme", rep)
        self.assertIn("baş harf", rep)
        self.assertNotIn("Ahmet", rep)
        self.assertNotIn("YILMAZ", rep)
        self.assertNotIn("Yılmaz", rep)
        # Sıfır-diske-eşleme ilkesi: baş harfli görünümde istisna belgelenir
        self.assertIn("Tek istisna", rep)

    def test_rapor_etiket_ve_acik_istisna_yazmaz(self) -> None:
        o_e = self.export({SRC_NAME: DOC}, "etiket", True)
        _r, rep_e = self.pick(o_e, UyapRedactor.REPORT_NAME)
        self.assertNotIn("kısmi eşleme", rep_e)
        self.assertNotIn("Tek istisna", rep_e)
        self.assertIn("bilerek hiçbir yere yazılmadı", rep_e)
        self.assertNotIn("Ahmet", rep_e)
        self.assertNotIn("YILMAZ", rep_e)

    def test_rapor_acik_modu_anlatir(self) -> None:
        self._tmp.cleanup()
        self._tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self._tmp.name, "src")
        self.out = os.path.join(self._tmp.name, "out")
        os.makedirs(self.src)
        o = self.export({SRC_NAME: DOC}, "acik", True)
        _r, rep = self.pick(o, UyapRedactor.REPORT_NAME)
        self.assertIn("--ad-gorunumu=acik", rep)
        self.assertNotIn("kısmi eşleme", rep)
        self.assertNotIn("ÖRNEKOĞLU", rep)


class TestBasHarfBicimi(_Base):
    def one(self, body: str, jud: bool = True) -> str:
        o = self.export({"k.md": "ANKARA 3. SULH HUKUK MAHKEMESİ\n" + body}, "bas_harf", jud)
        _r, txt = self.pick(o, "k.md")
        return txt

    def test_buyuk_harf_soyad_ilk(self) -> None:
        t = self.one("DAVALI : VELİOĞLU Ali\n")
        self.assertIn("DAVALI : Ali V. [DAVALI_1]", t)
        self.assertNotIn("VELİOĞLU", t)

    def test_turkce_i_buyuk_noktali_ve_noktasiz(self) -> None:
        t = self.one("DAVACI : Işıl KARA\nDAVALI : Ali İLHAN\n")
        self.assertIn("Işıl K. [DAVACI_1]", t)
        self.assertIn("Ali İ. [DAVALI_1]", t)

    def test_tamami_buyuk_yazilan_ad_baslik_harfli_olur(self) -> None:
        t = self.one("DAVALI : İSMAİL ÖZKAN\n")
        self.assertIn("İsmail Ö. [DAVALI_1]", t)
        self.assertNotIn("ÖZKAN", t)
        self.assertNotIn("İSMAİL", t)

    def test_uc_ve_dort_parcali_ad(self) -> None:
        t = self.one("DAVACI : Mehmet Ali YILDIRIM\nDAVALI : İsmail Hakkı Kemal ÖZ\n")
        self.assertIn("Mehmet Ali Y. [DAVACI_1]", t)
        self.assertIn("İsmail Hakkı Kemal Ö. [DAVALI_1]", t)
        self.assertNotIn("YILDIRIM", t)

    def test_ayni_bas_harfli_iki_kisi_etiketle_ayrilir(self) -> None:
        t = self.one(
            "DAVACI : Ahmet YILMAZ\nDAVALI : Ahmet YILDIZ\n"
            "Ahmet Yılmaz geldi. Ahmet Yıldız gitti.\n"
        )
        self.assertIn("DAVACI : Ahmet Y. [DAVACI_1]", t)
        self.assertIn("DAVALI : Ahmet Y. [DAVALI_1]", t)
        self.assertIn("Ahmet Y. [DAVACI_1] geldi. Ahmet Y. [DAVALI_1] gitti.", t)
        self.assertNotIn("YILMAZ", t)
        self.assertNotIn("YILDIZ", t)
        self.assertNotIn("Yıldız", t)

    def test_ek_etiketten_sonra_korunur(self) -> None:
        t = self.one(
            "DAVACI : Zeynep KAYA\nDAVALI : Ahmet YILMAZ\n"
            "Ahmet Yılmaz'ın evi. Ahmet Yılmaz'a tebligat. Ahmet Yılmaz'dan alacak.\n"
        )
        self.assertIn("Ahmet Y. [DAVALI_1]'ın evi", t)
        self.assertIn("Ahmet Y. [DAVALI_1]'a tebligat", t)
        self.assertIn("Ahmet Y. [DAVALI_1]'dan alacak", t)

    def test_numarali_liste_ve_cumle_icinde(self) -> None:
        t = self.one(
            "DAVALILAR :\n1- Ahmet YILMAZ\n2- Veli KARA\n3- Mustafa DEMİR\n"
            "Hâkim Zeynep ÖRNEKOĞLU 445566\n"
        )
        for init, lab in (("Ahmet Y.", "[DAVALI_1]"), ("Veli K.", "[DAVALI_2]"), ("Mustafa D.", "[DAVALI_3]")):
            self.assertIn(f"{init} {lab}", t)
        self.assertNotIn("YILMAZ", t)
        self.assertNotIn("KARA\n", t)
        self.assertNotIn("DEMİR", t)
        self.assertIn("Hâkim [HAKİM_1]", t)

    def test_yargi_adi_bas_harfli_yazilmaz(self) -> None:
        t = self.one("Hâkim Ayşe ÖRNEKOĞLU 445566\nDAVACI : Ahmet YILMAZ\n")
        self.assertNotIn("Ayşe", t)
        self.assertNotIn("Ö.", t)
        self.assertIn("[HAKİM_1]", t)


class TestDavaliListesiHakimOncesi(_Base):
    """Regresyon: 'Hâkim ...' satırından hemen önceki son liste maddesi de maskelenmeli (tüm görünümler)."""

    BODY = (
        "ANKARA 3. SULH HUKUK MAHKEMESİ\nDAVALILAR :\n"
        "1- Ahmet YILMAZ\n2- Veli KARA\n3- Mustafa DEMİR\n"
        "Hâkim Zeynep ÖRNEKOĞLU 445566\n"
    )

    def test_son_madde_etiket(self) -> None:
        o = self.export({"k.md": self.BODY}, "etiket")
        self.assertNotIn("Mustafa", self.blob(o))
        self.assertNotIn("DEMİR", self.blob(o))
        self.assertIn("3- [DAVALI_3]", self.pick(o, "k.md")[1])

    def test_son_madde_bos_satirdan_sonra_hakim(self) -> None:
        o = self.export({"k.md": self.BODY.replace("Hâkim", "\nHâkim")}, "etiket")
        self.assertNotIn("DEMİR", self.blob(o))


class TestDenetimModlari(_Base):
    def _out_file(self) -> str:
        for root, _d, files in os.walk(self.out):
            for fn in files:
                if fn.endswith("_karar.md") or fn == SRC_NAME:
                    return os.path.join(root, fn)
        raise AssertionError("karar çıktısı yok")

    def _inject(self, extra: str) -> None:
        fp = self._out_file()
        with open(fp, "a", encoding="utf-8") as f:
            f.write("\n" + extra + "\n")

    def _leaks(self, ad: str):
        res = audit_output.audit(self.src, self.out, ad_gorunumu=ad)
        _l, _d, leak = audit_output.summarize(res)
        return leak, res["leaks"]["person_name"]

    def test_etiket_ve_bas_harf_tam_ad_sizinti_baslharf_degil(self) -> None:
        for ad in ("etiket", "bas_harf"):
            with self.subTest(ad=ad):
                self._tmp.cleanup()
                self.setUp()
                self.export({SRC_NAME: DOC}, ad, True)
                leak, names = self._leaks(ad)
                self.assertFalse(leak, f"{ad}: temiz çıktı sızıntı sayıldı")
                self._inject("Ahmet YILMAZ burada.")
                leak, names = self._leaks(ad)
                self.assertTrue(leak, f"{ad}: tam ad sızıntı sayılmadı")
                self.assertTrue(names)

    def test_bas_harfli_biçim_sizinti_sayilmaz(self) -> None:
        self.export({SRC_NAME: DOC}, "bas_harf", True)
        self._inject("Ahmet Y. [DAVACI_1] ve Veli K. [DAVALI_1] burada.")
        leak, _n = self._leaks("bas_harf")
        self.assertFalse(leak)

    def test_yanlis_mod_tam_ad_yakalamayi_bozmaz(self) -> None:
        """bas_harf çıktısı etiket moduyla denetlenirse de baş harfli biçim sızıntı olmaz."""
        self.export({SRC_NAME: DOC}, "bas_harf", True)
        leak, _n = self._leaks("etiket")
        self.assertFalse(leak)

    def test_acik_modda_taraf_adi_sizinti_degil_yargi_adi_sizinti(self) -> None:
        self.export({SRC_NAME: DOC}, "acik", True)
        leak, _n = self._leaks("acik")
        self.assertFalse(leak, "açık modda taraf adı sızıntı sayılmamalı")
        # aynı çıktı etiket modunda denetlenirse taraf adı sızıntıdır
        leak_e, _n2 = self._leaks("etiket")
        self.assertTrue(leak_e)
        self._inject("Hâkim Ayşe ÖRNEKOĞLU imzalamıştır.")
        leak, names = self._leaks("acik")
        self.assertTrue(leak, "açık modda yargı adı hâlâ sızıntı sayılmalı")
        self.assertTrue(names)

    def test_eski_api_ve_cli_bayragi_uyumlu(self) -> None:
        self.export({SRC_NAME: DOC}, "acik", True)
        r_old = audit_output.audit(self.src, self.out, mask_names=False)
        r_new = audit_output.audit(self.src, self.out, ad_gorunumu="acik")
        self.assertEqual(r_old["ad_gorunumu"], "acik")
        self.assertEqual(len(r_old["leaks"]["person_name"]), len(r_new["leaks"]["person_name"]))
        self.assertEqual(audit_output.main([self.src, self.out, "--taraf-isimleri-acik"]), 0)
        self.assertEqual(audit_output.main([self.src, self.out, "--ad-gorunumu", "acik"]), 0)
        self.assertEqual(audit_output.main([self.src, self.out, "--taraf-isimleri"]), 1)  # varsayılan etiket
        self.assertEqual(audit_output.main([self.src, self.out]), 1)

    def test_cli_bas_harf_cikis_kodu_sifir(self) -> None:
        self.export({SRC_NAME: DOC}, "bas_harf", True)
        self.assertEqual(audit_output.main([self.src, self.out, "--ad-gorunumu", "bas-harf"]), 0)

    def test_audit_gecersiz_mod(self) -> None:
        self.export({SRC_NAME: DOC}, "etiket", True)
        with self.assertRaises(ValueError):
            audit_output.audit(self.src, self.out, ad_gorunumu="yanlis")


class TestApiVeCliUyumu(_Base):
    def _run_cli(self, *args: str, src: str = None, out: str = None) -> str:
        src = src or self.src
        out = out or self.out
        p = subprocess.run(
            [sys.executable, os.path.join(HERE, "uyap_redactor.py"), src, "--out", out, *args],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return self._read_karar(out)

    @staticmethod
    def _read_karar(out: str) -> str:
        for fn in os.listdir(out):
            if fn.endswith("_karar.md") or fn == SRC_NAME:
                with open(os.path.join(out, fn), encoding="utf-8") as f:
                    return f.read()
        raise AssertionError("çıktı yok")

    def test_normalize(self) -> None:
        n = MaskRegistry.normalize_ad_gorunumu
        self.assertEqual(n(None), "etiket")
        self.assertEqual(n("bas-harf"), "bas_harf")
        self.assertEqual(n("Baş Harf"), "bas_harf")
        self.assertEqual(n("AÇIK"), "acik")
        self.assertEqual(n("etiket"), "etiket")
        with self.assertRaises(ValueError):
            n("tamam")

    def test_export_mask_names_bayragi_turetilir(self) -> None:
        self.write_src({SRC_NAME: DOC})
        out_t = os.path.join(self._tmp.name, "o_true")
        out_f = os.path.join(self._tmp.name, "o_false")
        UyapRedactor.export_isolated_clean_folder(self.src, out_t, mask_names=True)
        UyapRedactor.export_isolated_clean_folder(self.src, out_f, mask_names=False)
        self.assertNotIn("YILMAZ", self.blob({fn: "" for fn in os.listdir(out_t)}))
        self.assertNotIn("Ahmet", self._read_karar(out_t))
        self.assertIn("Ahmet YILMAZ", self._read_karar(out_f))

    def test_export_gecersiz_mod(self) -> None:
        self.write_src({SRC_NAME: DOC})
        with self.assertRaises(ValueError):
            UyapRedactor.export_isolated_clean_folder(self.src, self.out, ad_gorunumu="yanlis")

    def test_cli_varsayilan_etiket(self) -> None:
        self.write_src({SRC_NAME: DOC})
        t = self._run_cli()
        self.assertIn("[DAVACI_1]", t)
        self.assertNotIn("Ahmet", t)

    def test_cli_uc_mod(self) -> None:
        self.write_src({SRC_NAME: DOC})
        outs = {}
        for m in ("etiket", "bas-harf", "acik"):
            outs[m] = self._run_cli("--ad-gorunumu", m, out=os.path.join(self._tmp.name, "o_" + m))
        self.assertIn("DAVACI : [DAVACI_1]", outs["etiket"])
        self.assertIn("DAVACI : Ahmet Y. [DAVACI_1]", outs["bas-harf"])
        self.assertIn("DAVACI : Ahmet YILMAZ", outs["acik"])
        for t in outs.values():
            self.assertIn("[HAKİM_1]", t)

    def test_cli_eski_bayraklar(self) -> None:
        self.write_src({SRC_NAME: DOC})
        for i, flag in enumerate(("--taraf-isimlerini-koru", "--isimleri-koru")):
            t = self._run_cli(flag, out=os.path.join(self._tmp.name, f"o_koru{i}"))
            self.assertIn("Ahmet YILMAZ", t, flag)
            self.assertIn("[HAKİM_1]", t, flag)
        t = self._run_cli("--taraf-isimlerini-maskele", out=os.path.join(self._tmp.name, "o_mask"))
        self.assertIn("[DAVACI_1]", t)
        self.assertNotIn("Ahmet", t)

    def test_cli_acik_ad_gorunumu_eski_bayragin_onune_gecer(self) -> None:
        self.write_src({SRC_NAME: DOC})
        t = self._run_cli("--taraf-isimlerini-koru", "--ad-gorunumu", "bas-harf",
                          out=os.path.join(self._tmp.name, "o_x"))
        self.assertIn("Ahmet Y. [DAVACI_1]", t)

    def test_cli_yargi_isimlerini_koru_aynen(self) -> None:
        self.write_src({SRC_NAME: DOC})
        t = self._run_cli("--yargi-isimlerini-koru", out=os.path.join(self._tmp.name, "o_y"))
        self.assertIn("Ayşe ÖRNEKOĞLU", t)
        self.assertIn("[DAVACI_1]", t)

    def test_cli_tek_dosya(self) -> None:
        self.write_src({SRC_NAME: DOC})
        out = os.path.join(self._tmp.name, "o_tek")
        t = self._run_cli("--ad-gorunumu", "bas-harf", src=os.path.join(self.src, SRC_NAME), out=out)
        self.assertIn("Ahmet Y. [DAVACI_1]", t)

    def test_cli_in_place_bas_harf(self) -> None:
        self.write_src({"k.md": "ANKARA 3. SULH HUKUK MAHKEMESİ\n" + DOC})
        p = subprocess.run(
            [sys.executable, os.path.join(HERE, "uyap_redactor.py"), self.src, "--in-place",
             "--ad-gorunumu", "bas-harf"],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        with open(os.path.join(self.src, "k.md"), encoding="utf-8") as f:
            t = f.read()
        self.assertIn("Ahmet Y. [DAVACI_1]", t)
        self.assertNotIn("YILMAZ", t)
        self.assertIn("[HAKİM_1]", t)

    def test_cli_in_place_varsayilan_etiket(self) -> None:
        self.write_src({"k.md": "ANKARA 3. SULH HUKUK MAHKEMESİ\n" + DOC})
        p = subprocess.run(
            [sys.executable, os.path.join(HERE, "uyap_redactor.py"), self.src, "--in-place"],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        with open(os.path.join(self.src, "k.md"), encoding="utf-8") as f:
            t = f.read()
        self.assertIn("DAVACI : [DAVACI_1]", t)
        self.assertNotIn("Ahmet", t)

    def test_cli_in_place_acik(self) -> None:
        self.write_src({"k.md": "ANKARA 3. SULH HUKUK MAHKEMESİ\n" + DOC})
        p = subprocess.run(
            [sys.executable, os.path.join(HERE, "uyap_redactor.py"), self.src, "--in-place",
             "--ad-gorunumu", "acik"],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        with open(os.path.join(self.src, "k.md"), encoding="utf-8") as f:
            t = f.read()
        self.assertIn("Ahmet YILMAZ", t)
        self.assertIn("[HAKİM_1]", t)


if __name__ == "__main__":
    unittest.main()
