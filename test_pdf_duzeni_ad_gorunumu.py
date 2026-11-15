#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF tablo düzeni, yargı başlık/alt-satır keşfi ve taraf liste keşfi testleri (TUR A).
Tüm veriler tamamen sentetiktir. Her senaryo izole geçici klasör üzerinde
export_isolated_clean_folder + audit_output.audit ile doğrulanır ve
signal.alarm(30) zaman aşımı koruması altında çalışır.
"""

import os
import re
import signal
import tempfile
import unittest
from typing import Dict, Iterable, List, Optional, Tuple

import audit_output
from uyap_redactor import MaskRegistry, UyapRedactor, _fold_tr


def _tckn(seed9: str) -> str:
    """9 haneli tohumdan algoritmik olarak geçerli sentetik 11 haneli TCKN üretir."""
    assert len(seed9) == 9 and seed9.isdigit() and seed9[0] != "0", seed9
    d = [int(c) for c in seed9]
    odd = d[0] + d[2] + d[4] + d[6] + d[8]
    even = d[1] + d[3] + d[5] + d[7]
    d10 = (odd * 7 - even) % 10
    d11 = (sum(d) + d10) % 10
    return f"{seed9}{d10}{d11}"


TC_ALI = _tckn("100000001")      # 10000000146
TC_VELI = _tckn("100000002")     # 10000000227
TC_HASAN = _tckn("100000003")    # 10000000308
TC_ZEHRA = _tckn("100000004")    # 10000000499
TC_MEHMET = _tckn("100000005")   # 10000000580
TC_AYSE = _tckn("100000006")     # 10000000661
TC_FATMA = _tckn("100000007")
TC_KEMAL = _tckn("100000008")
TC_SELMA = _tckn("100000009")


class _AlarmTimeout(TimeoutError):
    """Test zaman aşımı (SIGALRM)."""


class _BasePdfTabloTest(unittest.TestCase):
    """Ortak alarm koruması ve sentetik dışa aktarım + audit yardımcısı."""

    ALARM_SECONDS = 30

    def setUp(self) -> None:
        self._prev_handler = signal.getsignal(signal.SIGALRM)

        def _on_alarm(signum, frame):
            raise _AlarmTimeout(f"Test {self.ALARM_SECONDS}s içinde tamamlanmadı")

        signal.signal(signal.SIGALRM, _on_alarm)
        signal.alarm(self.ALARM_SECONDS)
        self._tmp = tempfile.TemporaryDirectory()
        self.src_dir = os.path.join(self._tmp.name, "src")
        self.out_dir = os.path.join(self._tmp.name, "out")
        os.makedirs(self.src_dir, exist_ok=True)

    def tearDown(self) -> None:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, self._prev_handler)
        self._tmp.cleanup()

    def _run_export_and_audit(
        self,
        docs: Dict[str, str],
        must_contain: Iterable[str] = (),
        must_not_contain: Iterable[str] = (),
        per_file_checks: Optional[Dict[str, Tuple[Iterable[str], Iterable[str]]]] = None,
    ) -> Tuple[Dict[str, str], Dict]:
        for rel, body in docs.items():
            fp = os.path.join(self.src_dir, rel)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, "w", encoding="utf-8", newline="") as wf:
                wf.write(body)

        UyapRedactor.export_isolated_clean_folder(self.src_dir, self.out_dir)
        audit_res = audit_output.audit(self.src_dir, self.out_dir)
        lines, det, has_leak = audit_output.summarize(audit_res)
        self.assertFalse(
            has_leak,
            "Audit sızıntı bildirdi:\n" + "\n".join(lines) + "\nDetay:\n" + "\n".join(det[:20]),
        )
        self.assertEqual(audit_res["mapping_leak"], [], f"Eşleme sızıntısı: {audit_res['mapping_leak']}")

        outputs: Dict[str, str] = {}
        for root, _dirs, files in os.walk(self.out_dir):
            for fn in sorted(files):
                if not fn.lower().endswith(".md"):
                    continue
                if fn in (UyapRedactor.REPORT_NAME, "INDEX.md"):
                    continue
                fp = os.path.join(root, fn)
                rel = os.path.relpath(fp, self.out_dir).replace("\\", "/")
                with open(fp, "r", encoding="utf-8") as rf:
                    outputs[rel] = rf.read()

        combined = "\n".join(outputs.values())
        for tok in must_contain:
            self.assertIn(tok, combined, f"Beklenen çıktı yok: {tok!r}\nÇıktı:\n{combined}")
        for tok in must_not_contain:
            self.assertNotIn(tok, combined, f"Sızan ifade bulundu: {tok!r}\nÇıktı:\n{combined}")

        if per_file_checks:
            for rel, (inc, exc) in per_file_checks.items():
                self.assertIn(rel, outputs, f"Dosya çıktıda yok: {rel}")
                txt = outputs[rel]
                for tok in inc:
                    self.assertIn(tok, txt, f"{rel} içinde beklenen yok: {tok!r}\n{txt}")
                for tok in exc:
                    self.assertNotIn(tok, txt, f"{rel} içinde sızıntı: {tok!r}\n{txt}")

        return outputs, audit_res


class TestYargiTabloDuzeni(_BasePdfTabloTest):
    """Adım 1a: Yargı PDF tablo düzeni (başlık üst satırda, alt satırda ':' + ad + sicil)."""

    def test_a01_hakim_alt_satir_iki_nokta_sicil_ayni_satir(self) -> None:
        doc = (
            "T.C.\nANKARA\n3. SULH HUKUK MAHKEMESİ\nTENSİP TUTANAĞI\n"
            "HAKİM\n: Ayşe ÖRNEKOĞLU KAYA  445566\n"
            "GEREĞİ DÜŞÜNÜLDÜ:\n1- Duruşma günü verilmesine.\n"
        )
        self._run_export_and_audit(
            {"tensip.md": doc},
            must_contain=["[HAKİM_1]", "[SİCİL_1]", ": [HAKİM_1]"],
            must_not_contain=["Ayşe", "ÖRNEKOĞLU", "445566"],
        )

    def test_a02_katip_alt_satir_iki_nokta_sicil_ayni_satir(self) -> None:
        doc = (
            "T.C.\nANKARA\n3. SULH HUKUK MAHKEMESİ\n"
            "KATİP\n: Fatma DEMİRCAN  778899\n"
            "Tutanak düzenlendi.\n"
        )
        self._run_export_and_audit(
            {"tutanak.md": doc},
            must_contain=["[KÂTİP_1]", "[SİCİL_1]", ": [KÂTİP_1]"],
            must_not_contain=["Fatma", "DEMİRCAN", "778899"],
        )

    def test_a03_savci_ve_cumhuriyet_savcisi_alt_satir_iki_nokta(self) -> None:
        doc = (
            "T.C.\nİZMİR CUMHURİYET BAŞSAVCILIĞI\n"
            "SAVCI\n: Ahmet KAYA  334455\n"
            "CUMHURİYET SAVCISI\n: Burak YILMAZ  556677\n"
            "Soruşturma evrakı incelendi.\n"
        )
        self._run_export_and_audit(
            {"sorusturma.md": doc},
            must_contain=["[SAVCI_1]", "[SAVCI_2]", "[SİCİL_1]", "[SİCİL_2]"],
            must_not_contain=["Ahmet KAYA", "Burak YILMAZ", "334455", "556677"],
        )

    def test_a04_zabit_katibi_alt_satir_iki_nokta(self) -> None:
        doc = (
            "T.C.\nBURSA 1. ASLİYE CEZA MAHKEMESİ\nDURUŞMA TUTANAĞI\n"
            "ZABIT KATİBİ\n: Selin KORKMAZ  667788\n"
            "Celse açıldı.\n"
        )
        self._run_export_and_audit(
            {"celse.md": doc},
            must_contain=["[KÂTİP_1]", "[SİCİL_1]"],
            must_not_contain=["Selin", "KORKMAZ", "667788"],
        )

    def test_a05_gerekceli_karar_baskan_uye_uye_katip_mahkeme_baglamli(self) -> None:
        doc = (
            "T.C.\nANKARA\n2. AĞIR CEZA MAHKEMESİ\nGEREKÇELİ KARAR\n"
            "ESAS NO\n: 2026/101 Esas\n"
            "BAŞKAN\n: Mehmet ÖZKAN  112233\n"
            "ÜYE\n: Zeynep ARSLAN  223344\n"
            "ÜYE\n: Emre ŞAHİN  334455\n"
            "KATİP\n: Deniz ÇELİK  445566\n"
            "HÜKÜM: Beraatine karar verildi.\n"
        )
        self._run_export_and_audit(
            {"karar.md": doc},
            must_contain=["[HAKİM_1]", "[HAKİM_2]", "[HAKİM_3]", "[KÂTİP_1]", "[SİCİL_4]"],
            must_not_contain=[
                "Mehmet ÖZKAN", "Zeynep ARSLAN", "Emre ŞAHİN", "Deniz ÇELİK",
                "112233", "223344", "334455", "445566",
            ],
        )

    def test_a06_alt_satir_iki_nokta_ad_ve_sicil_sonraki_satirda(self) -> None:
        doc = (
            "T.C.\nKONYA 4. ASLİYE HUKUK MAHKEMESİ\n"
            "HAKİM\n: Ayşe ÖRNEKOĞLU KAYA\n445566\n"
            "KATİP\n: Fatma DEMİRCAN\n(778899)\n"
            "Dava dosyası incelendi.\n"
        )
        self._run_export_and_audit(
            {"dosya.md": doc},
            must_contain=["[HAKİM_1]", "[KÂTİP_1]", "[SİCİL_1]", "[SİCİL_2]"],
            must_not_contain=["Ayşe", "ÖRNEKOĞLU", "Fatma", "DEMİRCAN", "445566", "778899"],
        )

    def test_a07_alt_satir_iki_nokta_sicilsiz_yalniz_ad(self) -> None:
        doc = (
            "T.C.\nESKİŞEHİR 1. SULH HUKUK MAHKEMESİ\n"
            "HAKİM\n: Ayşe ÖRNEKOĞLU KAYA\n"
            "KATİP\n: Fatma DEMİRCAN\n"
            "Ara karar kuruldu.\n"
        )
        self._run_export_and_audit(
            {"ara_karar.md": doc},
            must_contain=["[HAKİM_1]", "[KÂTİP_1]"],
            must_not_contain=["Ayşe", "ÖRNEKOĞLU", "Fatma", "DEMİRCAN"],
        )

    def test_a08_baslik_iki_nokta_bosluk_alt_satir_ad(self) -> None:
        doc = (
            "T.C.\nMERSİN 2. İŞ MAHKEMESİ\n"
            "HAKİM :   \nAyşe ÖRNEKOĞLU KAYA  445566\n"
            "KATİP :\nFatma DEMİRCAN  778899\n"
            "Duruşma zaptı.\n"
        )
        self._run_export_and_audit(
            {"zapit.md": doc},
            must_contain=["[HAKİM_1]", "[KÂTİP_1]", "[SİCİL_1]", "[SİCİL_2]"],
            must_not_contain=["Ayşe", "ÖRNEKOĞLU", "Fatma", "DEMİRCAN", "445566", "778899"],
        )

    def test_a09_cok_sutunlu_ayni_satir_uc_bosluk_hakim_katip(self) -> None:
        doc = (
            "T.C.\nANTALYA 5. ASLİYE HUKUK MAHKEMESİ\n"
            "HAKİM : Ayşe ÖRNEKOĞLU KAYA 445566   KATİP : Fatma DEMİRCAN 778899\n"
            "Tensip zaptıdır.\n"
        )
        self._run_export_and_audit(
            {"cok_sutun.md": doc},
            must_contain=["[HAKİM_1]", "[KÂTİP_1]", "[SİCİL_1]", "[SİCİL_2]"],
            must_not_contain=["Ayşe", "ÖRNEKOĞLU", "Fatma", "DEMİRCAN", "445566", "778899"],
        )

    def test_a10_cok_sutunlu_ayni_satir_sekme_ve_boru_hakim_savci_katip(self) -> None:
        doc = (
            "T.C.\nADANA 3. AĞIR CEZA MAHKEMESİ\n"
            "BAŞKAN : Kemal YILDIRIM 112233\tÜYE : Selma AKAR 223344\tKATİP : Merve ŞEN 334455\n"
            "| Hâkim : Tolga ÖZTÜRK 445566 | Savcı : Hakan POLAT 556677 |\n"
        )
        self._run_export_and_audit(
            {"heyet.md": doc},
            must_contain=["[HAKİM_1]", "[HAKİM_2]", "[HAKİM_3]", "[KÂTİP_1]", "[SAVCI_1]"],
            must_not_contain=[
                "Kemal YILDIRIM", "Selma AKAR", "Merve ŞEN", "Tolga ÖZTÜRK", "Hakan POLAT",
                "112233", "223344", "334455", "445566", "556677",
            ],
        )

    def test_a11_alt_imza_hakim_sicil_adsiz_sorunsuz(self) -> None:
        doc = (
            "T.C.\nANKARA 3. SULH HUKUK MAHKEMESİ\n"
            "06/08/2026\n"
            "Katip 778899\n \ne-imzalıdır\n \nHakim 445566\n \ne-imzalıdır\n"
        )
        self._run_export_and_audit(
            {"imza.md": doc},
            must_contain=["[SİCİL_1]", "[SİCİL_2]", "e-imzalıdır"],
            must_not_contain=["778899", "445566"],
        )

    def test_a12_all_caps_yargi_adlari_alt_satir_iki_nokta(self) -> None:
        doc = (
            "T.C.\nANKARA 3. SULH HUKUK MAHKEMESİ\n"
            "HAKİM\n: AYŞE ÖRNEKOĞLU KAYA  445566\n"
            "KATİP\n: FATMA DEMİRCAN  778899\n"
        )
        self._run_export_and_audit(
            {"allcaps.md": doc},
            must_contain=["[HAKİM_1]", "[KÂTİP_1]", "[SİCİL_1]", "[SİCİL_2]"],
            must_not_contain=["AYŞE", "ÖRNEKOĞLU", "FATMA", "DEMİRCAN", "445566", "778899"],
        )

    def test_a13_soyad_ad_sirasi_tablo_alt_satir(self) -> None:
        doc = (
            "T.C.\nANKARA 3. SULH HUKUK MAHKEMESİ\n"
            "HAKİM\n: KAYA Ayşe  445566\n"
            "KATİP\n: DEMİRCAN Fatma  778899\n"
            "Hâkim Ayşe Kaya tarafından ara karar verildi.\n"
        )
        outputs, _ = self._run_export_and_audit(
            {"soyad_ad.md": doc},
            must_contain=["[HAKİM_1]", "[KÂTİP_1]", "[SİCİL_1]", "[SİCİL_2]"],
            must_not_contain=["KAYA Ayşe", "Ayşe Kaya", "DEMİRCAN Fatma", "445566", "778899"],
        )
        # Aynı hâkim hem başlıkta hem cümlede aynı etiketi almalı
        self.assertEqual(outputs["soyad_ad.md"].count("[HAKİM_1]"), 2)

    def test_a14_iki_uc_dort_parcali_yargi_adlari(self) -> None:
        doc = (
            "T.C.\nİSTANBUL 7. ASLİYE TİCARET MAHKEMESİ\n"
            "BAŞKAN\n: Ali Can Mehmet YILMAZOĞLU  112233\n"
            "ÜYE\n: Zeynep Nur KARA  223344\n"
            "KATİP\n: Fatma DEMİRCAN  334455\n"
        )
        self._run_export_and_audit(
            {"parcali.md": doc},
            must_contain=["[HAKİM_1]", "[HAKİM_2]", "[KÂTİP_1]"],
            must_not_contain=[
                "Ali Can Mehmet YILMAZOĞLU", "Zeynep Nur KARA", "Fatma DEMİRCAN",
                "112233", "223344", "334455",
            ],
        )

    def test_a15_durusma_tutanagi_tam_duzen(self) -> None:
        doc = (
            "T.C.\nBURSA\n2. ASLİYE TİCARET MAHKEMESİ\nDURUŞMA TUTANAĞI\n"
            "ESAS NO\n: 2026/112 Esas\n"
            "CELSE NO\n: 3\n"
            "BAŞKAN\n: Kemal YILDIRIM  123456\n"
            "ÜYE\n: Selma AKAR  234567\n"
            "ÜYE\n: Tolga ÖZTÜRK  345678\n"
            "KATİP\n: Merve ŞEN  456789\n"
            "CUMHURİYET SAVCISI\n: Hakan POLAT  567890\n"
            "Belirli gün ve saatte celse açıldı.\n"
        )
        self._run_export_and_audit(
            {"durusma.md": doc},
            must_contain=["[HAKİM_1]", "[HAKİM_2]", "[HAKİM_3]", "[KÂTİP_1]", "[SAVCI_1]", "2026/112 Esas"],
            must_not_contain=[
                "Kemal YILDIRIM", "Selma AKAR", "Tolga ÖZTÜRK", "Merve ŞEN", "Hakan POLAT",
                "123456", "234567", "345678", "456789", "567890",
            ],
        )

    def test_a16_iddianame_savci_blogu_tablo_duzeni(self) -> None:
        doc = (
            "T.C.\nİZMİR\nCUMHURİYET BAŞSAVCILIĞI\nİDDİANAME\n"
            "SORUŞTURMA NO\n: 2026/450\n"
            "CUMHURİYET SAVCISI\n: Tarık GÜNEŞ  223344\n"
            "ŞÜPHELİ\n: Caner YILDIZ - " + TC_VELI + "\n"
            "SUÇ\n: Güvenin Kötüye Kullanılması\n"
        )
        self._run_export_and_audit(
            {"iddianame.md": doc},
            must_contain=["[SAVCI_1]", "[ŞÜPHELİ_1]", "[SİCİL_1]", "[TCKN_1]"],
            must_not_contain=["Tarık GÜNEŞ", "Caner YILDIZ", "223344", TC_VELI],
        )

    def test_a17_repro_tensip_duzeni_tek_belge(self) -> None:
        doc = (
            "# Tensip Zaptı.pdf\n\n### Sayfa 1\n\n"
            "T.C.\nANKARA\n3. SULH HUKUK MAHKEMESİ\nTENSİP TUTANAĞI\n"
            "ESAS NO\n: 2026/645 Esas\n \n"
            "HAKİM\n: Ayşe ÖRNEKOĞLU KAYA  445566\n"
            "KATİP\n: Fatma DEMİRCAN  778899\n"
            "DAVACI\n: Ali VELİOĞLU - " + TC_ALI + " - \n"
            "VEKİLİ\n: Av. Can DEMİR - [11111-22222-33333] UETS\n"
            "DAVA\n: Ortaklığın Giderilmesi\n\n"
            "06/08/2026\nKatip 778899\n \ne-imzalıdır\n \nHakim 445566\n \ne-imzalıdır\n"
        )
        self._run_export_and_audit(
            {"Tensip.md": doc},
            must_contain=["[HAKİM_1]", "[KÂTİP_1]", "[DAVACI_1]", "Av. Can DEMİR", "Ortaklığın Giderilmesi"],
            must_not_contain=["Ayşe", "ÖRNEKOĞLU", "Fatma", "DEMİRCAN", "Ali VELİOĞLU", "445566", "778899", TC_ALI],
        )

    def test_a18_bes_haneli_sicil_ve_parantezli_sicil_alt_satir(self) -> None:
        doc = (
            "T.C.\nSAMSUN 1. SULH HUKUK MAHKEMESİ\n"
            "HAKİM\n: Orhan YILMAZ  34567\n"
            "KATİP\n: Seda AKSOY (45678)\n"
        )
        self._run_export_and_audit(
            {"bes_hane.md": doc},
            must_contain=["[HAKİM_1]", "[KÂTİP_1]", "[SİCİL_1]", "[SİCİL_2]"],
            must_not_contain=["Orhan YILMAZ", "Seda AKSOY", "34567", "45678"],
        )

    def test_a19_negatif_sirket_genel_kurulu_mahkeme_baglami_yok(self) -> None:
        doc = (
            "ÖRNEK TİCARET ANONİM ŞİRKETİ\n"
            "OLAĞAN GENEL KURUL TOPLANTI TUTANAĞI\n"
            "BAŞKAN\n: Mehmet DEMİR\n"
            "ÜYE\n: Hasan YILMAZ\n"
            "Gündem maddeleri oybirliğiyle kabul edildi.\n"
        )
        outputs, _ = self._run_export_and_audit(
            {"genel_kurul.md": doc},
            must_contain=["Mehmet DEMİR", "Hasan YILMAZ"],
            must_not_contain=["[HAKİM_1]", "[HAKİM_2]"],
        )
        self.assertIn("Mehmet DEMİR", outputs["genel_kurul.md"])

    def test_a20_negatif_dava_vekil_konu_alt_satiri_yargi_sayilmaz(self) -> None:
        doc = (
            "T.C.\nANKARA 3. SULH HUKUK MAHKEMESİ\n"
            "HAKİM\n: Ayşe ÖRNEKOĞLU KAYA  445566\n"
            "VEKİLİ\n: Av. Can DEMİR - [11111-22222-33333] UETS\n"
            "DAVA\n: Ortaklığın Giderilmesi\n"
            "KONU\n: Paylaşım Talebi\n"
        )
        self._run_export_and_audit(
            {"negatif_basliklar.md": doc},
            must_contain=["[HAKİM_1]", "Av. Can DEMİR", "Ortaklığın Giderilmesi", "Paylaşım Talebi"],
            must_not_contain=["Ayşe ÖRNEKOĞLU KAYA", "445566", "[HAKİM_2]"],
        )

    def test_a21_ayni_hakim_farkli_belgelerde_ayni_etiket(self) -> None:
        doc1 = (
            "T.C.\nANKARA 3. SULH HUKUK MAHKEMESİ\n"
            "HAKİM\n: Ayşe ÖRNEKOĞLU KAYA  445566\n"
        )
        doc2 = (
            "T.C.\nANKARA 3. SULH HUKUK MAHKEMESİ\n"
            "Hâkim Ayşe Örnekoğlu Kaya tarafından inceleme yapıldı.\n"
        )
        self._run_export_and_audit(
            {"01_tensip.md": doc1, "02_tutanak.md": doc2},
            must_contain=["[HAKİM_1]"],
            must_not_contain=["Ayşe", "ÖRNEKOĞLU", "Örnekoğlu", "[HAKİM_2]", "445566"],
            per_file_checks={
                "01_tensip.md": (["[HAKİM_1]"], ["Ayşe"]),
                "02_tutanak.md": (["[HAKİM_1]"], ["Ayşe"]),
            },
        )

    def test_a22_markdown_kalin_baslik_alt_satir_iki_nokta(self) -> None:
        doc = (
            "T.C.\nKAYSERİ 2. AİLE MAHKEMESİ\n"
            "**HAKİM**\n: **Ayşe ÖRNEKOĞLU KAYA**  445566\n"
            "**ZABIT KÂTİBİ**\n: **Fatma DEMİRCAN**  778899\n"
        )
        self._run_export_and_audit(
            {"markdown_kalin.md": doc},
            must_contain=["[HAKİM_1]", "[KÂTİP_1]", "[SİCİL_1]", "[SİCİL_2]"],
            must_not_contain=["Ayşe", "ÖRNEKOĞLU", "Fatma", "DEMİRCAN", "445566", "778899"],
        )

    def test_a23_degismez_sicil_satirinda_maskesiz_yargi_adi_kalmaz_sentetik_ve_korpus(self) -> None:
        """
        DEĞİŞMEZ: Yargı başlığı aynı satırda ya da bir üst satırda olan ve [SİCİL_n]
        içeren her satırda maskesiz ad-benzeri belirteç (iki+ Büyük harfle başlayan/ALL CAPS sözcük)
        KALMAMALI. Hem sentetik düzenlerde hem test_senaryolar.py korpusunda denetlenir.
        """
        import test_senaryolar

        jud_hdr_re = re.compile(
            r'(?i)\b(?:h[aâ]kim|k[aâ]ti[bp]|zab[ıi]t\s+k[aâ]tib[iı]|'
            r'(?:cumhuriyet\s+)?(?:ba[şs])?savc[ıi](?:s[ıi])?|ba[şs]kan|[üu]ye)\b'
        )
        sicil_tag_re = re.compile(r'\[SİCİL_\d+\]')
        cap_seq_re = re.compile(
            r'(?:[A-ZÇĞİÖŞÜÂÎÛ][a-zçğıöşüâîû]+|[A-ZÇĞİÖŞÜÂÎÛ]{2,})'
            r'(?:[ \t]+(?:[A-ZÇĞİÖŞÜÂÎÛ][a-zçğıöşüâîû]+|[A-ZÇĞİÖŞÜÂÎÛ]{2,})){1,3}'
        )

        def _assert_invariant(doc_label: str, raw_texts: List[str]) -> None:
            reg = MaskRegistry()
            for t in raw_texts:
                UyapRedactor.collect_persons_from_text(t, reg)
            UyapRedactor._prune_corp_candidates(raw_texts, reg)
            reg.freeze_persons()
            for idx_doc, t in enumerate(raw_texts):
                if not UyapRedactor._DOC_JUDICIAL_CTX_RE.search(t):
                    continue
                out, _ = UyapRedactor.redact_text(t, registry=reg)
                out_lines = out.splitlines()
                for li, ln in enumerate(out_lines):
                    if not sicil_tag_re.search(ln):
                        continue
                    prev_ln = ""
                    for pj in range(li - 1, -1, -1):
                        if out_lines[pj].strip():
                            prev_ln = out_lines[pj]
                            break
                    if not (jud_hdr_re.search(ln) or (ln.lstrip().startswith(":") and jud_hdr_re.search(prev_ln))):
                        continue
                    cleaned = re.sub(r'\[[A-ZÇĞİÖŞÜ_]+_\d+\]', ' ', ln)
                    cleaned = re.sub(
                        r'(?i)\b(?:cumhuriyet|soruşturma|nöbetçi|zabıt|duruşma|mahkeme|heyet|başkan|üye|hâkimi?|savcısı?|kâtibi?|başsavcısı?|sicil|no|numarası|t\.c\.|esas|karar)\b',
                        ' ',
                        cleaned,
                    )
                    for m in cap_seq_re.finditer(cleaned):
                        cand = m.group(0)
                        if UyapRedactor._is_person_name(
                            cand,
                            before_ctx=cleaned[:m.start()],
                            after_ctx=cleaned[m.end():],
                            allow_judicial_pre_title=True,
                        ):
                            self.fail(
                                f"DEĞİŞMEZ İHLALİ ({doc_label} belge#{idx_doc} satır {li+1}): "
                                f"sicil satırında maskesiz ad kaldı: {cand!r}\nSatır: {ln!r}"
                            )

        synthetic_cases = {
            "tablo_alt_satir": [
                "T.C. ANKARA 3. SULH HUKUK MAHKEMESİ\n"
                "HAKİM\n: Ayşe ÖRNEKOĞLU KAYA  445566\n"
                "KATİP\n: Fatma DEMİRCAN  778899\n"
            ],
            "heyet_tablo": [
                "T.C. İZMİR 2. AĞIR CEZA MAHKEMESİ\nGEREKÇELİ KARAR\n"
                "BAŞKAN\n: Kemal YILDIRIM  112233\n"
                "ÜYE\n: Selma AKAR  223344\n"
                "KATİP\n: Deniz ÇELİK  334455\n"
            ],
            "tek_satir_coklu": [
                "T.C. BURSA 1. ASLİYE HUKUK MAHKEMESİ\n"
                "HAKİM : Orhan YILMAZ 34567   KATİP : Seda AKSOY 45678\n"
            ],
        }
        for name, txts in synthetic_cases.items():
            _assert_invariant(name, txts)

        for sen in test_senaryolar.SENARYOLAR:
            txts = [v for k, v in sen.dosyalar.items() if k.lower().endswith(".md") and isinstance(v, str)]
            if txts:
                _assert_invariant(f"senaryo:{sen.ad}", txts)


class TestTarafListeKesfi(_BasePdfTabloTest):
    """Adım 1b: Taraf numaralı listeleri ve cümle içi çoğul taraf kalıpları."""

    def test_b01_davalilar_alt_satir_numarali_liste_tcknli(self) -> None:
        doc = (
            "T.C. ANKARA 3. SULH HUKUK MAHKEMESİ\n"
            "DAVALILAR\n"
            f": 1- Veli VELİOĞLU-{TC_VELI} - \n"
            f"  2- Hasan VELİOĞLU-{TC_HASAN} - \n"
            f"  3- Zehra VELİOĞLU-{TC_ZEHRA} - \n"
            f"  4- Mehmet VELİOĞLU-{TC_MEHMET} - \n"
            "DAVA\n: Ortaklığın Giderilmesi\n"
        )
        outputs, _ = self._run_export_and_audit(
            {"tensip.md": doc},
            must_contain=[
                "1- [DAVALI_1]-[TCKN_1]",
                "2- [DAVALI_2]-[TCKN_2]",
                "3- [DAVALI_3]-[TCKN_3]",
                "4- [DAVALI_4]-[TCKN_4]",
                "Ortaklığın Giderilmesi",
            ],
            must_not_contain=[
                "Veli VELİOĞLU", "Hasan VELİOĞLU", "Zehra VELİOĞLU", "Mehmet VELİOĞLU",
                TC_VELI, TC_HASAN, TC_ZEHRA, TC_MEHMET, "[KİŞİ_",
            ],
        )
        self.assertIn("[DAVALI_1]", outputs["tensip.md"])

    def test_b02_davalilar_listede_yalniz_nufus_yok_dorduncu_kisi_sizmaz(self) -> None:
        dilekce = (
            "# DAVA DİLEKÇESİ\n"
            "Müvekkil Ali VELİOĞLU ile davalılar Veli VELİOĞLU, Hasan VELİOĞLU, "
            "Zehra VELİOĞLU ve Mehmet VELİOĞLU arasında ortaklığın giderilmesi talep edilmektedir.\n"
            f"Davacı Ali VELİOĞLU - T.C. {TC_ALI}\n"
        )
        nufus = (
            "# NÜFUS KAYIT ÖRNEĞİ\n"
            f"Adı Soyadı : Veli VELİOĞLU (TC {TC_VELI})\n"
            "Baba Adı : MUSTAFA\n"
            f"Adı Soyadı : Hasan VELİOĞLU (TC {TC_HASAN})\n"
            f"Adı Soyadı : Zehra VELİOĞLU (TC {TC_ZEHRA})\n"
        )
        tensip = (
            "# Tensip Zaptı.pdf\n\n### Sayfa 1\n\n"
            "T.C.\nANKARA\n3. SULH HUKUK MAHKEMESİ\nTENSİP TUTANAĞI\n"
            "ESAS NO\n: 2026/645 Esas\n \n"
            "HAKİM\n: Ayşe ÖRNEKOĞLU KAYA  445566\n"
            "KATİP\n: Fatma DEMİRCAN  778899\n"
            f"DAVACI\n: Ali VELİOĞLU - {TC_ALI} - \n"
            "VEKİLİ\n: Av. Can DEMİR - [11111-22222-33333] UETS\n"
            "DAVALILAR\n"
            f": 1- Veli VELİOĞLU-{TC_VELI} - \n"
            f"  2- Hasan VELİOĞLU-{TC_HASAN} - \n"
            f"  3- Zehra VELİOĞLU-{TC_ZEHRA} - \n"
            f"  4- Mehmet VELİOĞLU-{TC_MEHMET} - \n"
            "DAVA\n: Ortaklığın Giderilmesi\n"
        )
        self._run_export_and_audit(
            {"Dilekce.md": dilekce, "Nufus.md": nufus, "Tensip Zaptı.md": tensip},
            must_contain=[
                "[DAVACI_1]", "[DAVALI_1]", "[DAVALI_2]", "[DAVALI_3]", "[DAVALI_4]",
                "[HAKİM_1]", "[KÂTİP_1]", "Av. Can DEMİR",
            ],
            must_not_contain=[
                "Ali VELİOĞLU", "Veli VELİOĞLU", "Hasan VELİOĞLU", "Zehra VELİOĞLU", "Mehmet VELİOĞLU",
                "Ayşe ÖRNEKOĞLU KAYA", "Fatma DEMİRCAN", "[KİŞİ_",
                TC_ALI, TC_VELI, TC_HASAN, TC_ZEHRA, TC_MEHMET, "445566", "778899",
            ],
        )

    def test_b03_davacilar_alt_satir_numarali_liste(self) -> None:
        doc = (
            "DAVACILAR\n"
            f": 1- Ali VELİOĞLU - {TC_ALI} -\n"
            f"  2- Ayşe VELİOĞLU - {TC_AYSE} -\n"
            "DAVA\n: Tapu İptali\n"
        )
        self._run_export_and_audit(
            {"davacilar.md": doc},
            must_contain=["1- [DAVACI_1]", "2- [DAVACI_2]", "Tapu İptali"],
            must_not_contain=["Ali VELİOĞLU", "Ayşe VELİOĞLU", TC_ALI, TC_AYSE, "[KİŞİ_"],
        )

    def test_b04_saniklar_ve_supheliler_alt_satir_numarali_liste(self) -> None:
        doc = (
            "SANIKLAR\n"
            f": 1- Kemal ARSLAN - {TC_KEMAL}\n"
            f"  2- Murat YILDIZ - {TC_SELMA}\n"
            "ŞÜPHELİLER\n"
            f": 1- Burak KAYA - {TC_VELI}\n"
            f"  2- Emre ŞAHİN - {TC_HASAN}\n"
        )
        self._run_export_and_audit(
            {"ceza.md": doc},
            must_contain=["[SANIK_1]", "[SANIK_2]", "[ŞÜPHELİ_1]", "[ŞÜPHELİ_2]"],
            must_not_contain=["Kemal ARSLAN", "Murat YILDIZ", "Burak KAYA", "Emre ŞAHİN", "[KİŞİ_"],
        )

    def test_b05_mustekiler_ve_katilanlar_alt_satir_numarali_liste(self) -> None:
        doc = (
            "MÜŞTEKİLER\n"
            f": 1- Fatma YILMAZ - {TC_FATMA}\n"
            f"  2- Zehra DEMİR - {TC_ZEHRA}\n"
            "KATILANLAR\n"
            f": 1- Hasan KARA - {TC_HASAN}\n"
            f"  2- Mehmet ÇELİK - {TC_MEHMET}\n"
        )
        self._run_export_and_audit(
            {"musteki_katilan.md": doc},
            must_contain=["[MÜŞTEKİ_1]", "[MÜŞTEKİ_2]", "[KATILAN_1]", "[KATILAN_2]"],
            must_not_contain=["Fatma YILMAZ", "Zehra DEMİR", "Hasan KARA", "Mehmet ÇELİK", "[KİŞİ_"],
        )

    def test_b06_magdurlar_ve_taniklar_alt_satir_numarali_liste(self) -> None:
        doc = (
            "MAĞDURLAR\n"
            f": 1- Selma ÖZTÜRK - {TC_SELMA}\n"
            f"  2- Deniz AYDIN - {TC_AYSE}\n"
            "TANIKLAR\n"
            f": 1- Tarık POLAT - {TC_VELI}\n"
            f"  2- Canan GÜNEŞ - {TC_ALI}\n"
        )
        self._run_export_and_audit(
            {"magdur_tanik.md": doc},
            must_contain=["[MAĞDUR_1]", "[MAĞDUR_2]", "[TANIK_1]", "[TANIK_2]"],
            must_not_contain=["Selma ÖZTÜRK", "Deniz AYDIN", "Tarık POLAT", "Canan GÜNEŞ", "[KİŞİ_"],
        )

    def test_b07_alacaklilar_ve_borclular_alt_satir_numarali_liste(self) -> None:
        doc = (
            "ALACAKLILAR\n"
            f": 1- Ali VELİOĞLU - {TC_ALI}\n"
            f"  2- Ayşe VELİOĞLU - {TC_AYSE}\n"
            "BORÇLULAR\n"
            f": 1- Kemal ARSLAN - {TC_KEMAL}\n"
            f"  2- Mehmet YILDIZ - {TC_MEHMET}\n"
        )
        self._run_export_and_audit(
            {"icra.md": doc},
            must_contain=["[ALACAKLI_1]", "[ALACAKLI_2]", "[BORÇLU_1]", "[BORÇLU_2]"],
            must_not_contain=["Ali VELİOĞLU", "Ayşe VELİOĞLU", "Kemal ARSLAN", "Mehmet YILDIZ", "[KİŞİ_"],
        )

    def test_b08_liste_ogesi_koseli_parantez_tckn_ve_parantez_tc(self) -> None:
        doc = (
            "DAVALILAR\n"
            f": 1- Ahmet YILMAZ - [{TC_ALI}]\n"
            f"  2- Kemal DEMİR (TC: {TC_VELI})\n"
            f"  3- Hasan KAYA (T.C. Kimlik No: {TC_HASAN})\n"
        )
        self._run_export_and_audit(
            {"tckn_bicim.md": doc},
            must_contain=["[DAVALI_1]", "[DAVALI_2]", "[DAVALI_3]", "[TCKN_1]", "[TCKN_2]", "[TCKN_3]"],
            must_not_contain=["Ahmet YILMAZ", "Kemal DEMİR", "Hasan KAYA", TC_ALI, TC_VELI, TC_HASAN],
        )

    def test_b09_liste_ogesi_tcknsiz_tire_bitimli(self) -> None:
        doc = (
            "DAVALILAR\n"
            ": 1- Ahmet YILMAZ -\n"
            "  2- Kemal DEMİR -\n"
            "  3- Mehmet KAYA -\n"
            "KONU\n: Alacak Davası\n"
        )
        self._run_export_and_audit(
            {"tcknsiz_liste.md": doc},
            must_contain=["[DAVALI_1]", "[DAVALI_2]", "[DAVALI_3]", "Alacak Davası"],
            must_not_contain=["Ahmet YILMAZ", "Kemal DEMİR", "Mehmet KAYA", "[KİŞİ_"],
        )

    def test_b10_liste_baslikta_biter_vekil_dava_konu(self) -> None:
        doc = (
            "DAVALILAR\n"
            f": 1- Veli VELİOĞLU - {TC_VELI}\n"
            f"  2- Hasan VELİOĞLU - {TC_HASAN}\n"
            "VEKİLİ\n: Av. Can DEMİR - [11111-22222-33333] UETS\n"
            "DAVA\n: Ortaklığın Giderilmesi\n"
            "KONU\n: Tapu İptal Talebi\n"
        )
        self._run_export_and_audit(
            {"bitis.md": doc},
            must_contain=["[DAVALI_1]", "[DAVALI_2]", "Av. Can DEMİR", "Ortaklığın Giderilmesi", "Tapu İptal Talebi"],
            must_not_contain=["Veli VELİOĞLU", "Hasan VELİOĞLU", "[DAVALI_3]", "[DAVALI_4]"],
        )

    def test_b11_liste_icinde_vekil_satirlari_karismaz(self) -> None:
        doc = (
            "DAVALILAR\n"
            f": 1- Veli VELİOĞLU - {TC_VELI}\n"
            "  Vekili: Av. Can DEMİR\n"
            f"  2- Hasan VELİOĞLU - {TC_HASAN}\n"
            "  Vekili: Av. Seda KARA\n"
        )
        self._run_export_and_audit(
            {"liste_vekil.md": doc},
            must_contain=["[DAVALI_1]", "[DAVALI_2]", "Av. Can DEMİR", "Av. Seda KARA"],
            must_not_contain=["Veli VELİOĞLU", "Hasan VELİOĞLU", "[DAVALI_3]"],
        )

    def test_b12_ayni_kisi_iki_belgede_farkli_sirada_tutarli_etiket(self) -> None:
        doc1 = (
            "# DİLEKÇE\n"
            "Davalılar Veli VELİOĞLU, Hasan VELİOĞLU ve Zehra VELİOĞLU arasında taşınmaz paylaşımı.\n"
        )
        doc2 = (
            "# TENSİP\n"
            "DAVALILAR\n"
            f": 1- Zehra VELİOĞLU - {TC_ZEHRA}\n"
            f"  2- Veli VELİOĞLU - {TC_VELI}\n"
            f"  3- Hasan VELİOĞLU - {TC_HASAN}\n"
        )
        outputs, _ = self._run_export_and_audit(
            {"01_Dilekce.md": doc1, "02_Tensip.md": doc2},
            must_contain=["[DAVALI_1]", "[DAVALI_2]", "[DAVALI_3]"],
            must_not_contain=["Veli VELİOĞLU", "Hasan VELİOĞLU", "Zehra VELİOĞLU", "[DAVALI_4]"],
        )
        # 01_Dilekce tarama sırasında Veli=1, Hasan=2, Zehra=3 olur;
        # 02_Tensip'te liste Zehra ile başlasa da Zehra yine [DAVALI_3], Veli [DAVALI_1], Hasan [DAVALI_2] olmalı.
        self.assertIn("1- [DAVALI_3]", outputs["02_Tensip.md"])
        self.assertIn("2- [DAVALI_1]", outputs["02_Tensip.md"])
        self.assertIn("3- [DAVALI_2]", outputs["02_Tensip.md"])

    def test_b13_cumle_ici_davalilar_a_b_ve_c_arasinda(self) -> None:
        doc = (
            "Müvekkil Ali VELİOĞLU ile davalılar Veli VELİOĞLU, Hasan VELİOĞLU, "
            "Zehra VELİOĞLU ve Mehmet VELİOĞLU arasında ortaklığın giderilmesi talep edilmektedir.\n"
        )
        self._run_export_and_audit(
            {"cumle_liste.md": doc},
            must_contain=["[DAVALI_1]", "[DAVALI_2]", "[DAVALI_3]", "[DAVALI_4]"],
            must_not_contain=["Veli VELİOĞLU", "Hasan VELİOĞLU", "Zehra VELİOĞLU", "Mehmet VELİOĞLU", "[KİŞİ_"],
        )

    def test_b14_cumle_ici_davacilar_a_ile_b(self) -> None:
        doc = "Davacılar Ahmet YILMAZ ile Mehmet KAYA tarafından açılan alacak davasında...\n"
        self._run_export_and_audit(
            {"davacilar_ile.md": doc},
            must_contain=["[DAVACI_1]", "[DAVACI_2]"],
            must_not_contain=["Ahmet YILMAZ", "Mehmet KAYA", "[KİŞİ_"],
        )

    def test_b15_cumle_ici_yer_adlari_asla_davali_olmaz(self) -> None:
        doc = (
            "Davalılar Veli VELİOĞLU, Hasan VELİOĞLU, Zehra VELİOĞLU arasında, "
            "Burdur ili, Merkez ilçesi, Sarıova Köyü'nde kain 123 ada 11 parsel taşınmaz hakkında...\n"
        )
        self._run_export_and_audit(
            {"yer_adi_koruma.md": doc},
            must_contain=["[DAVALI_1]", "[DAVALI_2]", "[DAVALI_3]", "Burdur", "Merkez", "Sarıova Köyü"],
            must_not_contain=["Veli VELİOĞLU", "Hasan VELİOĞLU", "Zehra VELİOĞLU", "[DAVALI_4]"],
        )

    def test_b16_negatif_davalilar_vekili_adina_davalilara_liste_degil(self) -> None:
        doc = (
            "Davalılar vekili Av. Can DEMİR beyanında; davalılar adına tebligat alındığı, "
            "davalılara süre verildiği ve davalıların vekili Av. Seda KARA tarafından cevap sunulduğu görüldü.\n"
        )
        self._run_export_and_audit(
            {"negatif_cumle.md": doc},
            must_contain=["Av. Can DEMİR", "Av. Seda KARA"],
            must_not_contain=["[DAVALI_1]", "Can DEMİR]", "Seda KARA]"],
        )

    def test_b17_nufus_adi_soyadi_bloklari_rol_almis_kisiyle_eslesir(self) -> None:
        nufus = (
            "# NÜFUS KAYIT ÖRNEĞİ\n"
            f"Adı Soyadı : Veli VELİOĞLU (TC {TC_VELI})\n"
            "Baba Adı : MUSTAFA\n"
        )
        tensip = (
            "# TENSİP\n"
            "DAVALILAR\n"
            f": 1- Veli VELİOĞLU-{TC_VELI} - \n"
            f"  2- Hasan VELİOĞLU-{TC_HASAN} - \n"
        )
        self._run_export_and_audit(
            {"01_Nufus.md": nufus, "02_Tensip.md": tensip},
            must_contain=["[DAVALI_1]", "[DAVALI_2]"],
            must_not_contain=["Veli VELİOĞLU", "Hasan VELİOĞLU", "[KİŞİ_"],
            per_file_checks={
                "01_Nufus.md": (["[DAVALI_1]"], ["Veli VELİOĞLU", "[KİŞİ_"]),
                "02_Tensip.md": (["[DAVALI_1]", "[DAVALI_2]"], ["Veli VELİOĞLU", "Hasan VELİOĞLU"]),
            },
        )

    def test_b18_adresli_cok_satirli_numarali_liste(self) -> None:
        doc = (
            "DAVALILAR\n"
            f": 1- Veli VELİOĞLU - {TC_VELI}\n"
            "     Adres: Çiçek Mah. Papatya Sk. No:5 Çankaya/Ankara\n"
            f"  2- Hasan VELİOĞLU - {TC_HASAN}\n"
            "     Adres: Gül Mah. Lale Cad. No:12 Keçiören/Ankara\n"
        )
        self._run_export_and_audit(
            {"adresli_liste.md": doc},
            must_contain=["[DAVALI_1]", "[DAVALI_2]", "[ADRES_1]", "[ADRES_2]"],
            must_not_contain=["Veli VELİOĞLU", "Hasan VELİOĞLU", "Papatya", "Lale Cad", "[DAVALI_3]"],
        )

    def test_b19_tek_satir_coklu_numarali_liste(self) -> None:
        doc = "DAVALILAR : 1- Veli VELİOĞLU 2- Hasan VELİOĞLU 3- Zehra VELİOĞLU\n"
        self._run_export_and_audit(
            {"tek_satir_liste.md": doc},
            must_contain=["1- [DAVALI_1]", "2- [DAVALI_2]", "3- [DAVALI_3]"],
            must_not_contain=["Veli VELİOĞLU", "Hasan VELİOĞLU", "Zehra VELİOĞLU"],
        )

    def test_b20_tekil_davaci_davali_alt_satir_iki_nokta(self) -> None:
        doc = (
            "DAVACI\n"
            f": Ali VELİOĞLU - {TC_ALI} -\n"
            "DAVALI\n"
            f": Mehmet VELİOĞLU - {TC_MEHMET} -\n"
        )
        self._run_export_and_audit(
            {"tekil.md": doc},
            must_contain=["[DAVACI_1]", "[DAVALI_1]"],
            must_not_contain=["Ali VELİOĞLU", "Mehmet VELİOĞLU", TC_ALI, TC_MEHMET],
        )

    def test_b21_cumle_ici_supheliler_saniklar_mustekiler_taniklar(self) -> None:
        doc = (
            "Müştekiler Ayşe KAYA, Fatma DEMİR ile şüpheliler Kemal ARSLAN ve Murat YILDIZ "
            "arasındaki olayda tanıklar Selim ÇELİK ile Emine ÖZKAN dinlendi.\n"
        )
        self._run_export_and_audit(
            {"ceza_cumle.md": doc},
            must_contain=["[MÜŞTEKİ_1]", "[MÜŞTEKİ_2]", "[ŞÜPHELİ_1]", "[ŞÜPHELİ_2]", "[TANIK_1]", "[TANIK_2]"],
            must_not_contain=["Ayşe KAYA", "Fatma DEMİR", "Kemal ARSLAN", "Murat YILDIZ", "Selim ÇELİK", "Emine ÖZKAN"],
        )

    def test_b22_cumle_ici_uc_dort_parcali_adlar_ve_turkce_ekler(self) -> None:
        doc = (
            "Davalılar Ali Can VELİOĞLU, Ayşe Nur DEMİRCAN ve Fatma Zehra KARA ÖZKAN arasında "
            "anlaşmazlık çıktığı, Ali Can VELİOĞLU'nun taşınmaza müdahale ettiği görüldü.\n"
        )
        self._run_export_and_audit(
            {"parcali_cumle.md": doc},
            must_contain=["[DAVALI_1]", "[DAVALI_2]", "[DAVALI_3]", "[DAVALI_1]'nun"],
            must_not_contain=["Ali Can VELİOĞLU", "Ayşe Nur DEMİRCAN", "Fatma Zehra KARA ÖZKAN"],
        )

    def test_b23_baslik_alt_satir_liste_bosluksuz_tire_ve_noktali_numara(self) -> None:
        doc = (
            "DAVALILAR\n"
            f": 1-Veli VELİOĞLU-{TC_VELI}\n"
            f"2. Hasan VELİOĞLU-{TC_HASAN}\n"
            f"3) Zehra VELİOĞLU-{TC_ZEHRA}\n"
        )
        self._run_export_and_audit(
            {"noktali.md": doc},
            must_contain=["[DAVALI_1]", "[DAVALI_2]", "[DAVALI_3]"],
            must_not_contain=["Veli VELİOĞLU", "Hasan VELİOĞLU", "Zehra VELİOĞLU", "[KİŞİ_"],
        )


class TestTurA2ListeVeBlokBaglami(_BasePdfTabloTest):
    """TUR A2: madde işaretli/numarasız liste öğeleri ve blok-yerel BAŞKAN/ÜYE bağlamı."""

    def test_c01_madde_isaretli_liste_tum_ogeler_maskelenir(self) -> None:
        doc = "T.C. ANKARA 2. ASLİYE CEZA MAHKEMESİ\nTANIKLAR\n: - Yusuf KARA\n  - Nuray ÖZ\n  - Cemil YAĞCI\n"
        self._run_export_and_audit(
            {"tanik.md": doc},
            must_contain=["[TANIK_1]", "[TANIK_2]", "[TANIK_3]"],
            must_not_contain=["Yusuf", "Nuray", "Cemil", "YAĞCI"],
        )

    def test_c02_farkli_madde_isaretleri(self) -> None:
        doc = "SANIKLAR\n: • Orhan TAŞ\n  * Leyla AYDIN\n  – Cemal ŞAHİN\n  — Zeynep ARAS\n"
        self._run_export_and_audit(
            {"isaretler.md": doc},
            must_contain=["[SANIK_1]", "[SANIK_2]", "[SANIK_3]", "[SANIK_4]"],
            must_not_contain=["Orhan", "Leyla", "Cemal", "Zeynep"],
        )

    def test_c03_numarasiz_girintili_liste_devami(self) -> None:
        doc = "TANIKLAR\n: Yusuf KARA\n  Nuray ÖZ\n  Cemil YAĞCI\nDAVA\n: Alacak\n"
        self._run_export_and_audit(
            {"numarasiz.md": doc},
            must_contain=["[TANIK_1]", "[TANIK_2]", "[TANIK_3]"],
            must_not_contain=["Yusuf", "Nuray", "Cemil"],
        )

    def test_c04_liste_sonraki_baslikta_biter_ve_avukat_yer_adi_etiket_almaz(self) -> None:
        doc = (
            "DAVALILAR\n: - Veli VELİOĞLU\n  - Hasan VELİOĞLU\n"
            "VEKİLİ\n: Av. Can DEMİR\n"
            "DAVALILAR VEKİLİ\n: Av. Can DEMİR\n"
            "Davalılar adına Av. Can DEMİR cevap vermiştir.\n"
            "davalılar ile davacılar arasındaki Burdur ili, Merkez ilçesi, Sarıova Köyü 123 ada 11 parsel\n"
            "Davalılar Burdur Merkez Sarıova Köyü'nde oturmaktadır.\n"
        )
        out, _ = self._run_export_and_audit(
            {"liste_bitis.md": doc},
            must_contain=["[DAVALI_1]", "[DAVALI_2]", "Av. Can DEMİR", "Sarıova Köyü", "Burdur ili", "Merkez ilçesi"],
            must_not_contain=["Veli VELİOĞLU", "Hasan VELİOĞLU", "[DAVALI_3]", "[KİŞİ_"],
        )
        self.assertEqual(len(set(re.findall(r"\[DAVALI_\d+\]", "\n".join(out.values())))), 2)

    def test_c05_genel_kurul_baskan_uye_yargi_ipucu_yok_acik_kalir(self) -> None:
        doc = "GENEL KURUL TUTANAĞI\nBAŞKAN\n: Hasan POLAT\nÜYE\n: Can DEMİR\nGündem maddeleri görüşüldü.\n"
        self._run_export_and_audit(
            {"genel_kurul.md": doc},
            must_contain=["Hasan POLAT", "Can DEMİR"],
            must_not_contain=["[HAKİM_"],
        )

    def test_c06_uzaktaki_mahkeme_ipucu_baskan_uye_yargi_yapmaz(self) -> None:
        filler = "\n".join(f"Gündem maddesi {i} görüşüldü ve oylandı." for i in range(1, 31))
        doc = (
            "YÖNETİM KURULU TUTANAĞI\nBAŞKAN\n: Selin KOÇ\nÜYE\n: Kemal ARIK\n" + filler +
            "\nBakırköy 3. Asliye Ticaret Mahkemesi'nin 2025/12 Esas sayılı kararı okundu.\n"
        )
        self._run_export_and_audit(
            {"yk_uzak.md": doc},
            must_contain=["Selin KOÇ", "Kemal ARIK"],
            must_not_contain=["[HAKİM_"],
        )

    def test_c07_mahkeme_basligina_yakin_baskan_uye_yargi_sayilir(self) -> None:
        doc = (
            "T.C. İZMİR 4. ASLİYE HUKUK MAHKEMESİ\nGEREKÇELİ KARAR\n"
            "BAŞKAN - 112233\n: Murat SÖNMEZ\nÜYE - 223344\n: Seda KOÇ\n"
            "ÜYE - 334455\n: Kemal ARIK\nKATİP - 445566\n: Hacer ÇELİK\n"
        )
        self._run_export_and_audit(
            {"karar.md": doc},
            must_contain=["[HAKİM_1]", "[HAKİM_2]", "[HAKİM_3]", "[KÂTİP_1]"],
            must_not_contain=["Murat", "Seda KOÇ", "Kemal ARIK", "Hacer"],
        )

    def test_c08_uzun_kararda_imza_blogu_katip_sicil_yakinligi(self) -> None:
        body = "\n".join(f"Gerekçe satırı {i}: davanın kabulüne karar verilmiştir." for i in range(1, 40))
        doc = (
            "T.C. İZMİR 4. ASLİYE HUKUK MAHKEMESİ\nESAS NO : 2025/1\n" + body +
            "\nBaşkan 112233\n e-imzalıdır\nMurat SÖNMEZ\nÜye 223344\n e-imzalıdır\nSeda KOÇ\n"
            "Katip 445566\n e-imzalıdır\nHacer ÇELİK\n"
        )
        self._run_export_and_audit(
            {"uzun_karar.md": doc},
            must_contain=["[HAKİM_1]", "[HAKİM_2]", "[KÂTİP_1]"],
            must_not_contain=["Murat", "SÖNMEZ", "Seda KOÇ", "Hacer", "ÇELİK"],
        )

    def test_c09_belgeler_arasi_ayni_kisiler_farkli_sirada_tutarli_etiket(self) -> None:
        d1 = f"DAVALILAR\n: 1- Veli VELİOĞLU-{TC_VELI} -\n  2- Hasan VELİOĞLU-{TC_HASAN} -\n"
        d2 = "Davalılar Hasan VELİOĞLU ve Veli VELİOĞLU arasında ortaklığın giderilmesi talep edilmektedir.\n"
        out, _ = self._run_export_and_audit(
            {"01_tensip.md": d1, "02_dilekce.md": d2},
            must_not_contain=["Veli VELİOĞLU", "Hasan VELİOĞLU"],
        )
        l1 = re.findall(r"\[DAVALI_\d+\]", out["01_tensip.md"])
        l2 = re.findall(r"\[DAVALI_\d+\]", out["02_dilekce.md"])
        self.assertEqual(len(set(l1)), 2)
        self.assertEqual(set(l1), set(l2))
        # İkinci belgede sıra tersine (Hasan, Veli): etiket sırası ilk belgedeki listenin tersi olmalı
        self.assertEqual(l1, l2[::-1])

    def test_c10_baslik_cumle_icinde_hakimi_gecen_sirket_belgesi(self) -> None:
        doc = "ORTAKLAR KURULU\nBAŞKAN\n: Hasan POLAT\nÜYE\n: Can DEMİR\nHâkim ortak Mehmet KAYA hisse devrini kabul etti.\n"
        self._run_export_and_audit(
            {"ortaklar.md": doc},
            must_contain=["Hasan POLAT", "Can DEMİR"],
            must_not_contain=["[HAKİM_"],
        )


if __name__ == "__main__":
    unittest.main()
