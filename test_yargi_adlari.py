# -*- coding: utf-8 -*-
"""
Yargı personeli (hâkim, savcı, kâtip) ad-soyadlarının maskelenmesi ve rol tabanlı
etiketlenmesi için kapsamlı sentetik test paketi.
"""

import json
import os
import tempfile
import unittest

from uyap_redactor import MaskRegistry, UyapRedactor


def _build_registry(*texts: str, json_data=None) -> MaskRegistry:
    reg = MaskRegistry()
    for t in texts:
        UyapRedactor.collect_persons_from_text(t, reg)
    if json_data is not None:
        UyapRedactor.collect_persons_from_json(json_data, reg)
    UyapRedactor._prune_corp_candidates(list(texts), reg)
    reg.freeze_persons()
    return reg


class TestYargiAdlariMaskeleme(unittest.TestCase):
    """Hâkim, savcı ve kâtip ad-soyadlarının tutarlı rol etiketleriyle maskelenmesi."""

    def test_hakim_cumle_ici_ve_sicil(self):
        src = "Bursa Asliye Ceza Mahkemesi Hâkimi Mehmet Kaya (Sicil 123456) tarafından yargılama yapılmıştır."
        reg = _build_registry(src)
        out, _ = UyapRedactor.redact_text(src, registry=reg)
        self.assertNotIn("Mehmet Kaya", out)
        self.assertNotIn("123456", out)
        self.assertIn("[HAKİM_1]", out)
        self.assertIn("[SİCİL_1]", out)
        self.assertIn("Hâkimi [HAKİM_1]", out)

    def test_baslik_satirlari_hakim_baskan_uye_katip_savci(self):
        doc = (
            "Hâkim : Murat Sönmez (34567)\n"
            "**BAŞKAN :** Ayşe ÖRNEK  123456\n"
            "ÜYE : Kemal Aydın 234567\n"
            "ÜYE HÂKİM : Deniz Özkan (345678)\n"
            "Katip Fatma Demir 445566\n"
            "KÂTİP : Selin Koç (556677)\n"
            "Cumhuriyet Savcısı Ali Veli 112233\n"
            "Soruşturma Savcısı Hakan Yıldız (667788)\n"
        )
        reg = _build_registry(doc)
        out, _ = UyapRedactor.redact_text(doc, registry=reg)
        for hidden in (
            "Murat Sönmez", "34567",
            "Ayşe ÖRNEK", "123456",
            "Kemal Aydın", "234567",
            "Deniz Özkan", "345678",
            "Fatma Demir", "445566",
            "Selin Koç", "556677",
            "Ali Veli", "112233",
            "Hakan Yıldız", "667788",
        ):
            self.assertNotIn(hidden, out, f"Gizlenmedi: {hidden}\n{out}")

        # Roller ayrı ayrı ve tutarlı numaralandırılmalı
        self.assertIn("Hâkim : [HAKİM_1]", out)
        self.assertIn("**BAŞKAN :** [HAKİM_2]", out)
        self.assertIn("ÜYE : [HAKİM_3]", out)
        self.assertIn("ÜYE HÂKİM : [HAKİM_4]", out)
        self.assertIn("Katip [KÂTİP_1]", out)
        self.assertIn("KÂTİP : [KÂTİP_2]", out)
        self.assertIn("Cumhuriyet Savcısı [SAVCI_1]", out)
        self.assertIn("Soruşturma Savcısı [SAVCI_2]", out)

    def test_iyelikli_savcisi_ve_katibi_kalibi(self):
        doc = (
            "Bursa Cumhuriyet Savcısı Ali Veli duruşmaya katıldı.\n"
            "Duruşma Katibi Fatma Demir zaptı imzaladı.\n"
            "Başsavcı Vekili Hasan Çelik tarafından onaylandı.\n"
        )
        reg = _build_registry(doc)
        out, _ = UyapRedactor.redact_text(doc, registry=reg)
        self.assertNotIn("Ali Veli", out)
        self.assertNotIn("Fatma Demir", out)
        self.assertNotIn("Hasan Çelik", out)
        self.assertIn("Savcısı [SAVCI_1]", out)
        self.assertIn("Katibi [KÂTİP_1]", out)
        self.assertIn("Başsavcı Vekili [SAVCI_2]", out)

    def test_imza_blogu_ve_e_imzalidir_varyantlari(self):
        doc = (
            "Karar gereğince tebliğe çıkarıldı.\n\n"
            "Ayşe YILMAZ\n"
            "Hâkim 112233\n"
            "e-imzalıdır\n\n"
            "e-imzalıdır\n"
            "Zeynep KAYA\n"
            "Cumhuriyet Savcısı 223344\n\n"
            "Zabıt Kâtibi 334455\n"
            "Mert DEMİR\n"
            "e-imzalıdır\n"
        )
        reg = _build_registry(doc)
        out, _ = UyapRedactor.redact_text(doc, registry=reg)
        for hidden in ("Ayşe YILMAZ", "112233", "Zeynep KAYA", "223344", "Mert DEMİR", "334455"):
            self.assertNotIn(hidden, out, f"İmza bloğu ad/sicil kaldı: {hidden}\n{out}")
        self.assertIn("[HAKİM_1]", out)
        self.assertIn("[SAVCI_1]", out)
        self.assertIn("[KÂTİP_1]", out)
        self.assertIn("e-imzalıdır", out)

    def test_ayni_kisi_tutarli_etiket_ters_sira_buyuk_harf_ve_ek(self):
        doc1 = "HÂKİM : MEHMET KAYA (123456)\n"
        doc2 = "Hâkim Mehmet Kaya'nın ara kararı uyarınca; Kaya Mehmet ve Hâkim Mehmet Aydın'ın işlemi incelendi.\n"
        doc3 = "Cumhuriyet Savcısı Ali Veli 112233 mütalaasını sundu.\n"
        reg = _build_registry(doc1, doc2, doc3)
        out1, _ = UyapRedactor.redact_text(doc1, registry=reg)
        out2, _ = UyapRedactor.redact_text(doc2, registry=reg)
        out3, _ = UyapRedactor.redact_text(doc3, registry=reg)

        self.assertIn("HÂKİM : [HAKİM_1]", out1)
        self.assertIn("Hâkim [HAKİM_1]'nın ara kararı", out2)
        self.assertIn("[HAKİM_1] ve Hâkim [HAKİM_2]'ın", out2)
        self.assertIn("Cumhuriyet Savcısı [SAVCI_1]", out3)
        self.assertNotIn("MEHMET KAYA", out1)
        self.assertNotIn("Mehmet Kaya", out2)
        self.assertNotIn("Kaya Mehmet", out2)
        self.assertNotIn("Mehmet Aydın", out2)
        self.assertNotIn("Ali Veli", out3)

    def test_negatifler_maskelenmemeli(self):
        doc = (
            "Hâkim kararı ile 150000 TL tazminata hükmedildi.\n"
            "Hakim Bey duruşmayı erteledi.\n"
            "Davalı işveren vekili beyanda bulundu.\n"
            "Hâkim ve Savcı kürsüdeki yerini aldı.\n"
            "Savcılık makamı tarafından hazırlanan yazı ve Cumhuriyet Başsavcılığı evrakı okundu.\n"
            "Örnek şirket başkanı Ali Veli genel kurulda konuştu.\n"
            "Dernek üyesi Hasan Çelik ve yönetim kurulu üyesi Kemal Demir toplantıya katıldı.\n"
        )
        reg = _build_registry(doc)
        self.assertFalse(reg.has_persons(), f"Negatif metinden kişi kaydı üretildi: {reg.person_map()}")
        out, _ = UyapRedactor.redact_text(doc, registry=reg)
        self.assertEqual(out, doc)

    def test_varsayilan_mod_taraf_ve_yargi_maskeli_avukat_bilirkisi_acik(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            dest = os.path.join(tmp, "dest")
            os.makedirs(src, exist_ok=True)
            with open(os.path.join(src, "dava.md"), "w", encoding="utf-8") as f:
                f.write(
                    "DAVACI : Ahmet Çelik\n"
                    "VEKİLİ : Av. Ayşe Yılmaz\n"
                    "BİLİRKİŞİ : Bilirkişi Can Demir\n"
                    "HÂKİM : Mehmet Kaya (Sicil 123456)\n"
                    "CUMHURİYET SAVCISI : Ali Veli (223344)\n"
                    "ZABIT KÂTİBİ : Fatma Demir (334455)\n"
                    "Davacı Ahmet Çelik, Av. Ayşe Yılmaz ve Bilirkişi Can Demir huzurunda Hâkim Mehmet Kaya karar verdi.\n"
                )
            with open(os.path.join(src, "uyap-project.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "taraflar": [
                            {"sifat": "Davacı", "adSoyad": "Ahmet Çelik"},
                            {"sifat": "Vekil", "adSoyad": "Ayşe Yılmaz"},
                            {"sifat": "Hâkim", "adSoyad": "Mehmet Kaya"},
                        ]
                    },
                    f,
                    ensure_ascii=False,
                )

            out_dir, stats = UyapRedactor.export_isolated_clean_folder(src, dest)
            with open(os.path.join(out_dir, "dava.md"), "r", encoding="utf-8") as f:
                out_md = f.read()

            # Taraf ve yargı personeli varsayılan modda maskelenmiş olmalı
            self.assertNotIn("Ahmet Çelik", out_md)
            self.assertNotIn("Mehmet Kaya", out_md)
            self.assertNotIn("Ali Veli", out_md)
            self.assertNotIn("Fatma Demir", out_md)
            self.assertIn("[DAVACI_1]", out_md)
            self.assertIn("[HAKİM_1]", out_md)
            self.assertIn("[SAVCI_1]", out_md)
            self.assertIn("[KÂTİP_1]", out_md)

            # Avukat ve bilirkişi adları AÇIK kalmalı
            self.assertIn("Av. Ayşe Yılmaz", out_md)
            self.assertIn("Bilirkişi Can Demir", out_md)
            self.assertTrue(stats.get("mask_names"))
            self.assertTrue(stats.get("mask_judicial_names"))

            # Manifest JSON da tutarlı olmalı
            with open(os.path.join(out_dir, "uyap-project.json"), "r", encoding="utf-8") as f:
                out_json = f.read()
            self.assertNotIn("Ahmet Çelik", out_json)
            self.assertIn("[DAVACI_1]", out_json)
            self.assertNotIn("Mehmet Kaya", out_json)
            self.assertIn("[HAKİM_1]", out_json)

    def test_taraf_isimlerini_koru_modu_taraf_acik_yargi_maskeli(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            dest_party_open = os.path.join(tmp, "dest_party_open")
            dest_all_open = os.path.join(tmp, "dest_all_open")
            os.makedirs(src, exist_ok=True)
            with open(os.path.join(src, "tutanak.md"), "w", encoding="utf-8") as f:
                f.write(
                    "DAVACI : Ahmet Çelik\n"
                    "VEKİLİ : Av. Ayşe Yılmaz\n"
                    "Bilirkişi Can Demir raporu sundu.\n"
                    "HÂKİM : Mehmet Kaya (123456)\n"
                    "CUMHURİYET SAVCISI : Ali Veli (223344)\n"
                    "ZABIT KÂTİBİ : Fatma Demir (334455)\n"
                    "Davacı Ahmet Çelik dinlendi, Hâkim Mehmet Kaya zapta geçirdi.\n"
                )

            out_dir, stats = UyapRedactor.export_isolated_clean_folder(
                src, dest_party_open, mask_names=False
            )
            with open(os.path.join(out_dir, "tutanak.md"), "r", encoding="utf-8") as f:
                out_md = f.read()

            # Yargı personeli hâlâ maskeli
            self.assertNotIn("Mehmet Kaya", out_md)
            self.assertNotIn("Ali Veli", out_md)
            self.assertNotIn("Fatma Demir", out_md)
            self.assertIn("[HAKİM_1]", out_md)
            self.assertIn("[SAVCI_1]", out_md)
            self.assertIn("[KÂTİP_1]", out_md)

            # Taraf, avukat ve bilirkişi adları AÇIK
            self.assertIn("Ahmet Çelik", out_md)
            self.assertIn("Av. Ayşe Yılmaz", out_md)
            self.assertIn("Bilirkişi Can Demir", out_md)
            self.assertNotIn("[DAVACI_", out_md)
            self.assertFalse(stats.get("mask_names"))
            self.assertTrue(stats.get("mask_judicial_names"))

            # Her iki koruma birden açıkken hiç ad maskesi olmamalı
            out_open_dir, stats_open = UyapRedactor.export_isolated_clean_folder(
                src, dest_all_open, mask_names=False, mask_judicial_names=False
            )
            with open(os.path.join(out_open_dir, "tutanak.md"), "r", encoding="utf-8") as f:
                out_open = f.read()
            for kept in ("Ahmet Çelik", "Av. Ayşe Yılmaz", "Bilirkişi Can Demir", "Mehmet Kaya", "Ali Veli", "Fatma Demir"):
                self.assertIn(kept, out_open)
            self.assertNotIn("[DAVACI_", out_open)
            self.assertNotIn("[HAKİM_", out_open)
            self.assertFalse(stats_open.get("mask_names"))
            self.assertFalse(stats_open.get("mask_judicial_names"))

    def test_rol_cakismasi_yargi_baglaminda_maskelenir(self):
        """
        Aynı kişi hem yargı bağlamında hem başka bir bağlamda anıldığında çakışmada
        muhafazakâr yol seçilir: yargı rolü korunur ve varsayılan modda dahi maskelenir (sızıntı olmaz).
        """
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            dest = os.path.join(tmp, "dest")
            os.makedirs(src, exist_ok=True)
            with open(os.path.join(src, "belge.md"), "w", encoding="utf-8") as f:
                f.write(
                    "HÂKİM : Kemal Arslan (123456)\n"
                    "TANIK : Kemal Arslan\n"
                    "TANIK : Kemal Arslan\n"
                    "Duruşmada Kemal Arslan hakkında tutanak tutuldu.\n"
                )
            out_dir, _ = UyapRedactor.export_isolated_clean_folder(src, dest)
            with open(os.path.join(out_dir, "belge.md"), "r", encoding="utf-8") as f:
                out_md = f.read()
            self.assertNotIn("Kemal Arslan", out_md)
            self.assertIn("[HAKİM_1]", out_md)

    def test_dosya_adi_ve_markdown_link_hedefinde_hakim_adi(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            dest = os.path.join(tmp, "dest")
            os.makedirs(src, exist_ok=True)
            with open(os.path.join(src, "Hakim_Mehmet_Kaya_Karar.md"), "w", encoding="utf-8") as f:
                f.write("HÂKİM : Mehmet Kaya (123456)\nKarar metni.\n")
            with open(os.path.join(src, "dizin.md"), "w", encoding="utf-8") as f:
                f.write("- [Karar](Hakim_Mehmet_Kaya_Karar.md)\n")

            out_dir, _ = UyapRedactor.export_isolated_clean_folder(src, dest)
            self.assertFalse(os.path.exists(os.path.join(out_dir, "Hakim_Mehmet_Kaya_Karar.md")))
            self.assertTrue(os.path.exists(os.path.join(out_dir, "Hakim_[HAKİM_1]_Karar.md")))
            with open(os.path.join(out_dir, "dizin.md"), "r", encoding="utf-8") as f:
                dizin_out = f.read()
            self.assertNotIn("Mehmet_Kaya", dizin_out)
            self.assertIn("(Hakim_[HAKİM_1]_Karar.md)", dizin_out)

    def test_baskan_uye_yargi_baglami_olmadan_maskelenmez(self):
        """
        Genel kurul / ihale komisyonu / yönetim kurulu tutanaklarındaki Başkan ve Üye başlıkları
        mahkeme/yargı bağlamı yoksa yargı rolü sayılmaz; mahkeme tutanağındakiler [HAKİM_n] olur.
        """
        genel_kurul = (
            "ÖRNEK YAPI A.Ş. OLAĞAN GENEL KURUL TOPLANTI TUTANAĞI\n"
            "Karar No: 2025/1\n"
            "Divan Başkanı : Kerem Aksoy\n"
            "Toplantı Başkanı : Deniz Arslan\n"
            "Yönetim Kurulu Başkanı : Hasan Yiğit\n"
            "Başkan : Haluk Şen\n"
            "Üye : Can Demir\n"
        )
        ihale_komisyonu = (
            "ÖRNEK BELEDİYESİ İHALE KOMİSYONU TUTANAĞI\n"
            "Karar No: 2025/12\n"
            "Komisyon Başkanı : Emre Koç\n"
            "Komisyon Üyesi : Cemre Tan\n"
            "Başkan : Selim Kara\n"
            "Üye : Can Demir\n"
            "Başkan        Üye\n"
            "Selim Kara    Can Demir\n"
        )
        mahkeme_ici_alinti = (
            "T.C. ANKARA 2. ASLİYE TİCARET MAHKEMESİ\n"
            "ESAS NO: 2025/210\n"
            "BAŞKAN : Ayşe Örnek (112233)\n"
            "ÜYE : Kemal Aydın (234567)\n\n"
            "Davalı şirketin sunduğu belgede aşağıdaki isimler geçmektedir:\n"
            "Divan Başkanı : Kerem Aksoy\n"
            "Komisyon Başkanı : Emre Koç\n"
            "Komisyon Üyesi : Cemre Tan\n"
            "Yönetim Kurulu Başkanı : Hasan Yiğit\n"
            "Toplantı Başkanı : Deniz Arslan\n"
        )
        reg_gk = _build_registry(genel_kurul)
        self.assertEqual(reg_gk.person_map(), {})
        out_gk, _ = UyapRedactor.redact_text(genel_kurul, registry=reg_gk)
        for name in ("Kerem Aksoy", "Deniz Arslan", "Hasan Yiğit", "Haluk Şen", "Can Demir"):
            self.assertIn(name, out_gk)
        self.assertNotIn("[HAKİM_", out_gk)

        reg_ik = _build_registry(ihale_komisyonu)
        self.assertEqual(reg_ik.person_map(), {})
        out_ik, _ = UyapRedactor.redact_text(ihale_komisyonu, registry=reg_ik)
        for name in ("Emre Koç", "Cemre Tan", "Selim Kara", "Can Demir"):
            self.assertIn(name, out_ik)
        self.assertNotIn("[HAKİM_", out_ik)

        reg_m = _build_registry(mahkeme_ici_alinti)
        out_m, _ = UyapRedactor.redact_text(mahkeme_ici_alinti, registry=reg_m)
        self.assertNotIn("Ayşe Örnek", out_m)
        self.assertNotIn("Kemal Aydın", out_m)
        self.assertIn("BAŞKAN : [HAKİM_1]", out_m)
        self.assertIn("ÜYE : [HAKİM_2]", out_m)
        for kept in ("Kerem Aksoy", "Emre Koç", "Cemre Tan", "Hasan Yiğit", "Deniz Arslan"):
            self.assertIn(kept, out_m)

    def test_yalniz_hakim_sozcugu_sirket_belgesinde_uye_yargi_yapmaz(self):
        """
        Şirket/genel kurul belgesinde geçen 'Hâkim ortak Mehmet Kaya' veya yalın 'hâkim'
        sözcüğü belgeyi yargı belgesi yapmaz; ne 'Mehmet Kaya' ne 'Üye : Can Demir' maskelenir.
        """
        doc = (
            "ÖRNEK YAPI A.Ş. OLAĞAN GENEL KURUL TUTANAĞI\n"
            "Hâkim ortak Mehmet Kaya toplantıya katıldı.\n"
            "Hâkim Ortak Ayşe Yılmaz hazirun cetvelini imzaladı.\n"
            "Üye : Can Demir\n"
        )
        reg = _build_registry(doc)
        self.assertEqual(reg.person_map(), {})
        out, _ = UyapRedactor.redact_text(doc, registry=reg)
        self.assertIn("Mehmet Kaya", out)
        self.assertIn("Ayşe Yılmaz", out)
        self.assertIn("Can Demir", out)
        self.assertNotIn("[HAKİM_", out)

    def test_karisik_rol_tanik_ve_hakim_her_iki_modda_her_yerde_hakim(self):
        """Aynı kişi bir belgede tanık, başka belgede hâkimse her iki modda da her belgede [HAKİM_n] olur."""
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            dest_default = os.path.join(tmp, "dest_default")
            dest_party_open = os.path.join(tmp, "dest_party_open")
            os.makedirs(src, exist_ok=True)
            with open(os.path.join(src, "01_tanik.md"), "w", encoding="utf-8") as f:
                f.write(
                    "TANIK : Kemal Kaya\n"
                    "Tanık Kemal Kaya beyanında olayı gördüğünü söylemiştir.\n"
                    "TANIK : Kemal Kaya\n"
                    "TANIK : Kemal Kaya\n"
                )
            with open(os.path.join(src, "02_karar.md"), "w", encoding="utf-8") as f:
                f.write(
                    "T.C. ANKARA 1. ASLİYE HUKUK MAHKEMESİ\n"
                    "HÂKİM : Kemal Kaya (123456)\n"
                )
            for mask_names_flag, dest in ((True, dest_default), (False, dest_party_open)):
                out_dir, stats = UyapRedactor.export_isolated_clean_folder(
                    src, dest, mask_names=mask_names_flag
                )
                for fn in ("01_tanik.md", "02_karar.md"):
                    with open(os.path.join(out_dir, fn), "r", encoding="utf-8") as f:
                        txt = f.read()
                    self.assertNotIn("Kemal Kaya", txt, f"mask_names={mask_names_flag} {fn}")
                    self.assertIn("[HAKİM_1]", txt, f"mask_names={mask_names_flag} {fn}")
                    self.assertNotIn("[TANIK_", txt, f"mask_names={mask_names_flag} {fn}")
                self.assertEqual(stats.get("kisi_listesi"), [("[HAKİM_1]", "Kemal Kaya")])

    def test_keep_only_roles_taraf_oylari_fazla_olsa_da_yargi_kanitiyla_tutar(self):
        """Bir kişinin taraf rolü oyu yargı oyundan fazla olsa da keep_only_roles(JUDICIAL_ROLES) kişiyi korur."""
        reg = MaskRegistry()
        for _ in range(5):
            reg.add_person("Kemal Kaya", "TANIK", strong=True)
        reg.add_person("Kemal Kaya", "HAKİM", strong=True)
        for _ in range(3):
            reg.add_person("Ahmet Çelik", "DAVACI", strong=True)
        reg.keep_only_roles(MaskRegistry.JUDICIAL_ROLES)
        reg.freeze_persons()
        self.assertEqual(reg.person_map(), {"[HAKİM_1]": "Kemal Kaya"})
        self.assertEqual(reg.person_count_by_role(), {"HAKİM": 1})

    def test_buyuk_harf_ocr_tablo_ve_udf_yargi_kesfi(self):
        """BÜYÜK HARF, OCR unvan varyantları, yatay tablo satırı (| Hâkim | Ad | Sicil |) ve UDF imza sütunu."""
        doc = (
            "T.C. ANKARA ASLİYE TİCARET MAHKEMESİ\n"
            "| Unvan | Ad Soyad | Sicil |\n"
            "|---|---|---|\n"
            "| Hâkim | Mehmet Kaya | 112233 |\n"
            "| Cumhuriyet Savcısı | Ali Veli | 223344 |\n\n"
            "ZABIT KÂTİBİ : FATMA DEMİR 334455\n"
            "Hâkim (445566)        Zabıt Kâtibi (556677)\n"
            "Ayşe Yılmaz           Zeynep Çelik\n"
            "e-imzalıdır           e-imzalıdır\n"
        )
        reg = _build_registry(doc)
        out, _ = UyapRedactor.redact_text(doc, registry=reg)
        for hidden in ("Mehmet Kaya", "Ali Veli", "FATMA DEMİR", "Ayşe Yılmaz", "Zeynep Çelik"):
            self.assertNotIn(hidden, out, f"Tablo/Büyük harf/İmza ad gizlenmedi: {hidden}\n{out}")
        self.assertEqual(out.count("[SİCİL_"), 5)
        self.assertIn("| Hâkim | [HAKİM_1] | [SİCİL_", out)
        self.assertIn("| Cumhuriyet Savcısı | [SAVCI_1] | [SİCİL_", out)


if __name__ == "__main__":
    unittest.main()
