#!/usr/bin/env python3
"""
Kalıcı ReDoS (felaket geri izleme) koruma testleri.
Tüm maskeleme, ad keşif ve denetim katmanlarının kötü/uzun girdilerde
doğrusal zamanda (<2 sn) tamamlandığını signal.alarm(10) ile güvenceye alır.
"""

import signal
import time
import unittest

import audit_output
from uyap_redactor import MaskRegistry, UyapRedactor


class _RedosAlarmError(TimeoutError):
    """SIGALRM zaman aşımı hatası."""


class TestRedosKoruma(unittest.TestCase):
    """Tüm katmanlar için kalıcı ReDoS ve zaman aşımı testleri."""

    ALARM_SECONDS = 10
    MAX_LAYER_SECONDS = 2.0

    def setUp(self) -> None:
        self._prev_handler = signal.getsignal(signal.SIGALRM)

        def _alarm_handler(signum, frame):
            raise _RedosAlarmError(f"ReDoS zaman aşımı (>{self.ALARM_SECONDS}s)")

        signal.signal(signal.SIGALRM, _alarm_handler)
        signal.alarm(self.ALARM_SECONDS)

    def tearDown(self) -> None:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, self._prev_handler)

    def _run_timed(self, label: str, fn, *args, **kwargs):
        t0 = time.perf_counter()
        res = fn(*args, **kwargs)
        dt = time.perf_counter() - t0
        self.assertLessEqual(
            dt,
            self.MAX_LAYER_SECONDS,
            f"{label} çok yavaş sürdü: {dt:.3f}s (limit {self.MAX_LAYER_SECONDS:.1f}s)",
        )
        return res

    @staticmethod
    def _build_adversarial_corpus(n: int) -> str:
        parts = [
            "HÂKİM : " + ("Ali " * n) + "\n",
            "- **Zabıt Kâtibi:** " + ("Kelime " * n) + "\n",
            "BAŞKAN : " + ("A" * n) + " " + ("SOYAD " * min(n, 1000)) + "\n",
            "Hâkim | " + ("Veli | " * n) + "\n",
            "HÂKİM" + (" \t" * n) + "Deneme\n",
            "HÂKİM : " + ("[HAKİM_1] " * n) + "\n",
            "T.C. Kimlik No:" + ("\u00a0" * n) + "Metin\n",
            "Adres: " + ("Sokak\u00a0" * min(n, 2000)) + "\n",
            "Telefon: 05" + (" " * n) + "Metin\n",
            "IBAN: TR" + (" " * n) + "Metin\n",
            "Hesap No: " + ("A" * n) + " / " + ("B" * n) + "\n",
            "HAKİM\n: " + ("*" * n) + " " + ("Ali " * min(n, 1000)) + "\n",
            "DAVALILAR\n: 1- Ali Veli\n" + "".join(f"  {k}- Ahmet Kaya\n" for k in range(2, min(n, 500) + 2)),
            "davalılar " + ("Ali Veli, " * min(n, 1000)) + "arasında\n",
        ]
        return "".join(parts)

    def test_n50_n500_n5000_title_plus_words_redact_sicil(self) -> None:
        for n in (50, 500, 5000):
            with self.subTest(n=n):
                txt = "HÂKİM : " + ("Ali " * n) + "\n"
                out, c = self._run_timed(f"redact_sicil(Ali*{n})", UyapRedactor.redact_sicil, txt)
                self.assertEqual(c, 0)
                self.assertEqual(out, txt)

    def test_all_adversarial_shapes_all_layers_n5000(self) -> None:
        corpus = self._build_adversarial_corpus(5000)

        self._run_timed("redact_sicil", UyapRedactor.redact_sicil, corpus)
        self._run_timed("redact_address", UyapRedactor.redact_address, corpus)
        self._run_timed("redact_address_safety_net", UyapRedactor.redact_address_safety_net, corpus)
        self._run_timed("redact_tckn", UyapRedactor.redact_tckn, corpus)
        self._run_timed("redact_phone", UyapRedactor.redact_phone, corpus)
        self._run_timed("redact_iban", UyapRedactor.redact_iban, corpus)
        self._run_timed("redact_account", UyapRedactor.redact_account, corpus)

        reg_names = MaskRegistry()
        reg_names.add_person("Ali Veli", "DAVACI")
        self._run_timed("redact_names", UyapRedactor.redact_names, corpus, reg_names)

        reg_collect = MaskRegistry()
        self._run_timed("collect_persons_from_text", UyapRedactor.collect_persons_from_text, corpus, reg_collect)

        out, _ = self._run_timed("redact_text", UyapRedactor.redact_text, corpus)
        self._run_timed("audit_output.audit", audit_output.audit, corpus, out)

    def test_individual_evil_patterns_each_layer_scales_linearly(self) -> None:
        # Her katman için N=50, 500, 5000 ayrı ayrı hızlı tamamlanmalı
        evil_inputs = {
            "sicil_pipe_tag_nbsp": lambda n: (
                "Hâkim | " + ("|" * n) + "\n"
                + "BAŞKAN : " + ("[HAKİM_1] " * min(n, 2000)) + "[" * min(n, 2000) + "\n"
                + "Kâtip\u00a0:\u00a0" + ("Metin\u00a0" * n) + "\n"
            ),
            "all_caps_and_tabs": lambda n: (
                ("UZUNBÜYÜKHARF" + ("\t \t" * 2)) * (n // 2 + 1) + "\n"
            ),
            "address_repeated_keywords": lambda n: (
                "Adres: " + ("Test Mahallesi " * min(n, 1500)) + "\n"
                + ("No: / " * min(n, 1500)) + "\n"
            ),
            "tckn_split_noise": lambda n: (
                "T.C. Kimlik No: " + ("1 " * min(n, 2000)) + "\n"
                + "TCKN" + ("*" * n) + "Metin\n"
            ),
            "phone_iban_account_noise": lambda n: (
                "GSM: 05" + ("-" * n) + "\n"
                + "TR" + ("0" * 2) + (" " * n) + "X\n"
                + "Hesap: " + ("12-" * min(n, 1500)) + "\n"
            ),
        }

        for name, make_txt in evil_inputs.items():
            for n in (50, 500, 5000):
                with self.subTest(pattern=name, n=n):
                    txt = make_txt(n)
                    reg = MaskRegistry()
                    self._run_timed(f"sicil/{name}/{n}", UyapRedactor.redact_sicil, txt)
                    self._run_timed(f"addr/{name}/{n}", UyapRedactor.redact_address, txt)
                    self._run_timed(f"safety/{name}/{n}", UyapRedactor.redact_address_safety_net, txt)
                    self._run_timed(f"tckn/{name}/{n}", UyapRedactor.redact_tckn, txt)
                    self._run_timed(f"phone/{name}/{n}", UyapRedactor.redact_phone, txt)
                    self._run_timed(f"iban/{name}/{n}", UyapRedactor.redact_iban, txt)
                    self._run_timed(f"account/{name}/{n}", UyapRedactor.redact_account, txt)
                    self._run_timed(f"collect/{name}/{n}", UyapRedactor.collect_persons_from_text, txt, reg)
                    reg_n = MaskRegistry()
                    reg_n.add_person("Ali Veli", "TANIK")
                    self._run_timed(f"names/{name}/{n}", UyapRedactor.redact_names, txt, reg_n)
                    out, _ = self._run_timed(f"redact_text/{name}/{n}", UyapRedactor.redact_text, txt)
                    self._run_timed(f"audit/{name}/{n}", audit_output.audit, txt, out)

    def test_redact_sicil_functional_formats_preserved(self) -> None:
        samples = [
            ("Hâkim:Ayşe Kaya 112233", "Hâkim:Ayşe Kaya [SİCİL_"),
            ("Hâkim\tAyşe Kaya 112233", "Hâkim\tAyşe Kaya [SİCİL_"),
            ("Hakim Ayşe Kaya 112233", "Hakim Ayşe Kaya [SİCİL_"),
            ("HÂKİM : Murat Sönmez (34567)", "HÂKİM : Murat Sönmez ([SİCİL_"),
            ("- **Zabıt Kâtibi:** Seda Ak (223344)", "- **Zabıt Kâtibi:** Seda Ak ([SİCİL_"),
            ("HÂKİM : [HAKİM_1] (34567)", "HÂKİM : [HAKİM_1] ([SİCİL_"),
            ("| Hâkim | [HAKİM_1] | 112233 |", "[SİCİL_"),
            ("Hâkim Ayşe Kaya\n112233", "[SİCİL_"),
            ("HAKİM\n: Ayşe ÖRNEKOĞLU KAYA  445566", "[SİCİL_"),
            ("HAKİM\n: [HAKİM_1]  445566", "[SİCİL_"),
            ("HAKİM\n: Ayşe ÖRNEKOĞLU KAYA\n445566", "[SİCİL_"),
        ]
        for raw, expected_prefix in samples:
            with self.subTest(raw=raw):
                out, cnt = self._run_timed("sicil_sample", UyapRedactor.redact_sicil, raw)
                self.assertEqual(cnt, 1, f"Beklenen sicil sayısı 1, çıktı: {out!r}")
                self.assertIn(expected_prefix, out)

    def test_new_table_and_list_patterns_n5000_linear(self) -> None:
        # 1. Tablo düzeni başlık + 5000 satır
        txt_table_5000 = "T.C. ANKARA 1. ASLİYE HUKUK MAHKEMESİ\nHAKİM\n: " + ("*\t " * 1000) + "\n" + ("Boş satır metni\n" * 5000)
        reg1 = MaskRegistry()
        self._run_timed("sicil/table_5000", UyapRedactor.redact_sicil, txt_table_5000)
        self._run_timed("collect/table_5000", UyapRedactor.collect_persons_from_text, txt_table_5000, reg1)

        # 2. Liste + 5000 öğe (çok satırlı)
        txt_list_5000 = "DAVALILAR\n: 1- Kişi Bir\n" + "".join(f"  {i}- Deneme Kelime\n" for i in range(2, 5002))
        reg2 = MaskRegistry()
        self._run_timed("collect/list_5000", UyapRedactor.collect_persons_from_text, txt_list_5000, reg2)

        # 3. Cümle içi çoğul taraf + 5000 öğe / gürültülü ayrım
        txt_prose_5000 = "Davalılar " + ("Deneme Kelime, " * 5000) + "arasında.\n"
        reg3 = MaskRegistry()
        self._run_timed("collect/prose_plural_5000", UyapRedactor.collect_persons_from_text, txt_prose_5000, reg3)

        # 4. Çok sütunlu sekme/boşluk + 5000 parça
        txt_cols_5000 = "HAKİM : " + ("Ali\t" * 5000) + "\n"
        reg4 = MaskRegistry()
        self._run_timed("collect/cols_5000", UyapRedactor.collect_persons_from_text, txt_cols_5000, reg4)

        # 5. Satır içi 5000 yıldız/ayraçlı _HEADER_COLON_RE kötü girdisi
        txt_hdr_evil = ("*" * 5000) + "A" * 50 + "\n"
        reg5 = MaskRegistry()
        self._run_timed("collect/hdr_evil_5000", UyapRedactor.collect_persons_from_text, txt_hdr_evil, reg5)

    def test_madde_isareti_ve_blok_baglami_kotu_girdiler_linear(self) -> None:
        """TUR A2: madde işareti ayıklama ve blok-yerel yargı bağlamı büyük/kötü girdilerde doğrusal kalır."""
        self._run_timed("extract/bullet_spaces_200k", UyapRedactor._extract_name_from_segment, "- " + " " * 200000 + "x")
        self._run_timed("extract/dash_run_100k", UyapRedactor._extract_name_from_segment, "- " * 100000)
        txt_bullets = "TANIKLAR\n: - Ali Veli\n" + "\n".join(f"  - Ali Veli{i}" for i in range(5000)) + "\n"
        self._run_timed("collect/bullets_5000", UyapRedactor.collect_persons_from_text, txt_bullets, MaskRegistry())
        txt_blocks = "T.C. X MAHKEMESİ\n" + "BAŞKAN\n: Ali Veli\n" * 3000
        self._run_timed("collect/baskan_blocks_3000", UyapRedactor.collect_persons_from_text, txt_blocks, MaskRegistry())
        txt_ctx = "\n".join("Katip 445566 e-imzalıdır" for _ in range(5000))
        self._run_timed("collect/ctx_lines_5000", UyapRedactor.collect_persons_from_text, txt_ctx, MaskRegistry())


if __name__ == "__main__":
    unittest.main()
