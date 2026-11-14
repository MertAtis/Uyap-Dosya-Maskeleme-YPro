# -*- coding: utf-8 -*-
"""
Yanlış yakalama (false positive) koruma testleri:
Kişisel olmayan hukuki/ticari/kamusal metinlerin maskelenmediğini doğrular.
"""

import os
import tempfile
import unittest

import audit_output as A
from uyap_redactor import MaskRegistry, UyapRedactor


class TestYanlisYakalama(unittest.TestCase):
    """Kişisel olmayan metinler maskelenmemelidir."""

    def _assert_all_preserved(self, lines):
        failures = []
        for line in lines:
            reg = MaskRegistry(set())
            UyapRedactor.collect_persons_from_text(line, reg)
            reg.freeze_persons()
            out, stats = UyapRedactor.redact_text(line, registry=reg)
            if out != line:
                failures.append(
                    f"Yanlış yakalama! Maskelenen satır:\n  Girdi : {line}\n  Çıktı : {out}\n  Stats : {stats}"
                )
        if failures:
            self.fail(f"{len(failures)} satır yanlış maskelendi:\n" + "\n".join(failures))

    def test_gemini_probe_benign_satirlari(self):
        lines = [
            "Ankara 5. Asliye Hukuk Mahkemesi 2023/145 Esas, 2024/312 Karar sayılı dosya.",
            "Dava konusu alacak 245.000 TL olup 15.03.2023 tarihinde ödenmiştir.",
            "Fatura No: 2023123456 tutarı 12.500,00 TL'dir.",
            "Dosya No: 123456789 sayılı icra takibi başlatılmıştır.",
            "TMK madde 2, TBK madde 49 ve HMK madde 114/1-ç uyarınca dava şartı yoktur.",
            "Kaza 34 ABC 123 plakalı araç ile Atatürk Bulvarı üzerinde Kızılay Meydanı önünde meydana gelmiştir.",
            "Olay yeri: Bağdat Caddesi No: 45 Kadıköy/İstanbul kavşağıdır.",
            "Davalı şirketin adresi: Maslak Mahallesi Büyükdere Caddesi No: 12 Sarıyer/İstanbul (Anteti).",
            "Ankara Adliyesi Kızılay Mah. Adliye Sarayı Sıhhiye/Ankara adresinde duruşma yapılacaktır.",
            "Taraflar 01.01.2022 tarihli kira sözleşmesinin 5. maddesi uyarınca 3 yıllık süre belirlemiştir.",
            "Tel: 0312 555 12 34 sabit hat kurum telefonudur.",
            "Barkod No: 8690123456789 evrak takip numarasıdır.",
            "UYAP Evrak No: 1234567890 tarih 12/05/2023 saat 14:30.",
            "Bilirkişi raporunda 1.250.000 TL hasar ve 12345 TL tamir bedeli tespit edilmiştir.",
            "Hakim 150000 TL tazminata hükmetmiştir.",
            "Madde 12345 sayılı Kanun kapsamında değerlendirilmiştir.",
            "Davacı vekili Av. Ayşe Yılmaz Ankara Barosu'na kayıtlıdır.",
            "Araç şasi no: WVWZZZ1JZ3W386752 olup motor no 123456789012 dir.",
            "Sanık 28.05.2023 günü saat 22.00 sıralarında İstanbul Beyoğlu İstiklal Caddesi'nde gözaltına alınmıştır.",
            "T.C. Ankara Cumhuriyet Başsavcılığı Soruşturma No: 2023/12345",
            "Karar No: 2024/98765 Esas No: 2023/54321",
            "Ankara Gayrimenkul 35 Ada 12 Parsel numaralı taşınmazın tapu kaydı incelenmiştir.",
        ]
        self._assert_all_preserved(lines)

    def test_ticaret_sicil_korunur_ancak_yargi_ve_baro_sicil_maskelenir(self):
        benign_ticaret = [
            "Ticaret Sicil No: 123456 olan Örnek İnşaat A.Ş. davalıdır.",
            "Tic. Sicil No: 862070 MERSİS: 0123456789000019.",
            "İstanbul Ticaret Odası Sicil No: 456789 kayıtlı şirket.",
            "Ticaret Sicili: 334455 numarasıyla tescil edilmiştir.",
        ]
        self._assert_all_preserved(benign_ticaret)

        # Yargı ve baro sicilleri maskelenmeye DEVAM etmelidir
        must_mask_sicil = [
            ("Hâkim Mehmet Kaya (Sicil 123456)", "123456"),
            ("Baro Sicil No : Burdur Barosu , 490", "490"),
            ("Ankara Barosu Sicil No: 23456", "23456"),
            ("Cumhuriyet Savcısı Ali Veli 112233", "112233"),
        ]
        for line, sicil in must_mask_sicil:
            out, _ = UyapRedactor.redact_text(line, registry=MaskRegistry())
            self.assertNotIn(sicil, out, f"Gerçek sicil maskelenmedi: {line} -> {out}")
            self.assertIn("[SİCİL_", out, f"Sicil etiketi yok: {line} -> {out}")

    def test_kapsamli_sentetik_benign_satirlar_en_az_40(self):
        lines = [
            # Araç plakaları (1-4)
            "06 XYZ 9876 plakalı kamyonet ile 35 KLM 45 plakalı otomobil çarpışmıştır.",
            "Davalı şirkete ait 34 DEF 4567 plakalı araç trafik kaydında görünmektedir.",
            "16 GH 281 plakalı araç hakkında yakalama şerhi kaldırılmıştır.",
            "07 ABC 001 plakalı servis aracı kaza saatinde güzergahta bulunuyordu.",
            # Ada / parsel / tapu kayıtları (5-8)
            "Bursa Osmangazi İlçesi Demirtaş Mahallesi 450 Ada 12 Parsel sayılı taşınmaz.",
            "Ankara Çankaya 1020 Ada 3 Parsel 5 No'lu Bağımsız Bölüm tapu kaydı.",
            "İzmir Bornova 215 Ada 8 Parsel üzerindeki irtifak hakkı terkin edilmiştir.",
            "Tapu Kütüğü Cilt No: 45 Sayfa No: 128 Yevmiye No: 19452 ile tescil edildi.",
            # Barkod / evrak / fatura / dekont / yevmiye no (9-14)
            "PTT Barkod No: 2710012345678 gönderisi alıcısına teslim edilmiştir.",
            "E-Arşiv Fatura No: GIB2024000012345 bedeli 38.400,00 TL'dir.",
            "Dekont No: 9876543210 tarihli havale açıklaması kira bedelidir.",
            "Noter Yevmiye No: 14523 tarih 04.07.2024 sayılı ihtarname incelendi.",
            "UYAP Evrak Kayıt No: 20245678901 sistem üzerinden doğrulanmıştır.",
            "Poliçe No: 10023456789 Zeyilname No: 0000012345 kapsamında teminat verilmiştir.",
            # 9-11 haneli etiketsiz/geçersiz sağlamalı sayılar (15-18)
            "Referans kodu 12345678902 ve işlem numarası 98765432100 olarak kayda geçti.",
            "Arşiv takip kodu 456789123 olup sistem numarası 9876543210 olarak atanmıştır.",
            "Gümrük beyanname numarası 240612345678 olup vergi dairesi kodu 006123456 şeklindedir.",
            "Proje onay numarası 11122233344 (sağlama toplamı geçersiz) dosya ekindedir.",
            # Tutarlar (19-22)
            "Toplam 1.450.000,00 TL asıl alacak ve 245.500 TL işlemiş faiz talep edildi.",
            "Gümrük bedeli 48.750,00 USD ve navlun ücreti 12.300,00 EUR olarak faturalandı.",
            "150000 TL manevi tazminat ile 25000 TL maddi tazminata karar verildi.",
            "KDV dahil 118.000 TL sözleşme bedeli 6 taksitte ödenmiştir.",
            # Tarih / saat (23-25)
            "14.09.2022 tarihinde saat 09:45 itibarıyla keşif mahallinde hazır bulunuldu.",
            "Sözleşme süresi 01/01/2023 - 31/12/2025 tarihleri arasını kapsamaktadır.",
            "2024-06-15T10:30:00 zaman damgalı log kaydı bilirkişiye sunuldu.",
            # Esas / karar / soruşturma / icra no (26-29)
            "İstanbul 12. Asliye Ticaret Mahkemesi 2023/412 E. ve 2024/890 K. sayılı ilamı.",
            "Ankara 3. İcra Dairesi 2024/15230 Esas sayılı dosyası birleştirilmiştir.",
            "İzmir Cumhuriyet Başsavcılığı 2023/45678 Soruşturma ve 2024/11223 İddianame no.",
            "Yargıtay 9. Hukuk Dairesi 2022/10035 E., 2024/171 K. sayılı bozma kararı.",
            # Kanun maddeleri (30-32)
            "6100 sayılı HMK m. 114/1-ç, m. 119 ve m. 324 hükümleri değerlendirilmiştir.",
            "6098 sayılı TBK madde 49, madde 51 ve 4721 sayılı TMK madde 2 uygulanmıştır.",
            "5237 sayılı TCK'nın 86/2, 53/1 ve 62. maddeleri gereğince hüküm kurulmuştur.",
            # Kurum / adliye / banka / PTT / noter adresleri (33-38)
            "İstanbul Adliyesi Merkez Mah. Abide-i Hürriyet Cad. No:223 Şişli/İstanbul adresinde duruşma.",
            "Örnek Bankası A.Ş. Genel Müdürlüğü Büyükdere Cad. No:123 Beşiktaş/İstanbul adresi.",
            "Kadıköy 5. Noterliği Bahariye Cad. No:45 Kadıköy/İstanbul adresinden tebliğ edildi.",
            "PTT Başmüdürlüğü Cumhuriyet Bulvarı No:10 Konak/İzmir şubesine teslim edildi.",
            "Ankara Ticaret Odası Söğütözü Mah. 2180. Cad. No:5 Çankaya/Ankara adresi.",
            "Yıldız Lojistik Hizmetleri Ltd. Şti. İkitelli OSB 12. Sok. No:4 Başakşehir/İstanbul (Anteti).",
            # Olay yeri (39-41)
            "Olay yeri: Meşrutiyet Caddesi No: 32 Kızılay Çankaya/Ankara önüdür.",
            "Kaza mahalli: TEM Otoyolu 15. Km Esenyurt/İstanbul mevkii olarak tespit edildi.",
            "Suç mahalli: İstiklal Caddesi No: 88 Beyoğlu/İstanbul kamera açısındadır.",
            # Sabit hat telefonları (42-44)
            "Santral: 0212 444 55 66 ve Fax: 0212 444 55 67 hatlarından teyit alınmıştır.",
            "Kurum irtibat hattı 0232 333 44 55 ile müşteri hizmetleri 0850 222 00 00 numarası.",
            "Adliye kalemi telefon: (0312) 222 33 44 dahili 1234 üzerinden arandı.",
            # Şasi / motor / IMEI (45-46)
            "Şasi No: NM0EXXTTGE1234567 ve Motor No: DURATORQ987654321 ruhsatta yazılıdır.",
            "Cihaz IMEI: 356938035643809 numarası BTK kayıtlarından sorgulanmıştır.",
            # Şirket unvanları ve il/ilçe adları (47-50)
            "Örnek Yapı İnşaat San. ve Tic. A.Ş. ile Anadolu Teknoloji Ltd. Şti. sözleşme imzaladı.",
            "Kaya Holding A.Ş. ve Demir Otomotiv A.Ş. arasındaki cari hesap ekstresi sunuldu.",
            "İstanbul İli Kadıköy İlçesi ile İzmir İli Konak İlçesi arasındaki taşıma bedeli.",
            "Ankara İli Çankaya İlçesi sınırları içindeki Bursa Nilüfer şubesi kayıtları.",
        ]
        self.assertGreaterEqual(len(lines), 40)
        self._assert_all_preserved(lines)

    def test_gercek_kisi_ikamet_karsi_ornekleri_maskelenir(self):
        """
        Yanlış yakalama düzeltmesinin (şirket adresi / Ticaret Odası) gerçek kişi adresini
        veya kişisel ikametgah bilgisini kaçırmadığını doğrulayan karşı örnekler.
        """
        person_lines = [
            "Davalı şirketin yetkilisi Ali Veli ikametgah adresi: Atatürk Mah. 10. Sok. No: 5 Çankaya/Ankara.",
            "Davalı şirket çalışanı Mehmet Kaya adresi: Bahçelievler Mah. 3. Cad. No: 12 Nilüfer/Bursa.",
            "Davalı Mehmet Kaya Adresi: Bahçelievler Mah. 3. Cad. No: 12 (Örnek Bankası Şubesi yanı) Nilüfer/Bursa.",
            "Davalı şirket yetkilisi Ahmet Çelik'in adresi: Lale Mah. Çam Sok. No: 7 Çankaya/Ankara.",
            "Örnek Yapı A.Ş. ortağı Mehmet Demir'in adresi: Karanfil Mah. Sümbül Sok. No: 8 Yenimahalle/Ankara.",
            "Şirket ortağı Hasan Öz ikamet adresi: Güzelyalı Mah. 5. Sok. No: 14 Konak/İzmir.",
            "Tebligat adresi: Gül Sokak No: 4 Yenimahalle/Ankara",
        ]
        for ln in person_lines:
            reg = MaskRegistry()
            out, _ = UyapRedactor.redact_text(ln, registry=reg)
            self.assertIn("[ADRES_1]", out, msg=f"Gerçek kişi adresi kaçtı: {ln!r} -> {out!r}")

    def test_tuzel_kisi_ve_oda_adresi_audit_ile_tam_uyumlu(self):
        """
        Redaktörün koruduğu şirket antedi ve oda adresleri audit_output tarafından sızıntı sayılmaz;
        maskesiz kalan gerçek kişi adresleri ise hem redaktörce maskelenir hem audit tarafından yakalanır.
        """
        corp_doc = (
            "Davalı şirketin adresi: Maslak Mahallesi Büyükdere Caddesi No: 12 Sarıyer/İstanbul (Anteti).\n"
            "Ankara Ticaret Odası: Atatürk Bulvarı No:21 Çankaya/Ankara\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            dest = os.path.join(tmp, "dest")
            os.makedirs(src, exist_ok=True)
            with open(os.path.join(src, "belge.md"), "w", encoding="utf-8") as f:
                f.write(corp_doc)
            out_dir, _ = UyapRedactor.export_isolated_clean_folder(src, dest)
            with open(os.path.join(out_dir, "belge.md"), "r", encoding="utf-8") as f:
                out_md = f.read()
            self.assertIn("Maslak Mahallesi Büyükdere Caddesi No: 12", out_md)
            self.assertIn("Atatürk Bulvarı No:21 Çankaya/Ankara", out_md)

            res = A.audit(src, out_dir)
            self.assertEqual(res["leaks"]["addr_kisi"], [], f"Kişi adresi yanlış alarmı: {res['leaks']['addr_kisi']}")
            self.assertEqual(res["leaks"]["addr_prefix"], [])
            self.assertEqual(A.main([src, out_dir]), 0)

        # Karşı örnek: gerçek kişi adresleri maskesiz bırakılırsa audit addr_kisi + exit code 1 vermeli
        for idx, person_line in enumerate(
            [
                "Davalı şirket yetkilisi Ahmet Çelik'in adresi: Lale Mah. Çam Sok. No: 7 Çankaya/Ankara.",
                "Şirket ortağı Hasan Öz ikamet adresi: Güzelyalı Mah. 5. Sok. No: 14 Konak/İzmir.",
                "Örnek Yapı A.Ş. ortağı Mehmet Demir'in adresi: Karanfil Mah. Sümbül Sok. No: 8 Yenimahalle/Ankara.",
                "Tebligat adresi: Gül Sokak No: 4 Yenimahalle/Ankara",
            ]
        ):
            with tempfile.TemporaryDirectory() as tmp:
                src_p = os.path.join(tmp, "src")
                out_p = os.path.join(tmp, "out")
                os.makedirs(src_p, exist_ok=True)
                os.makedirs(out_p, exist_ok=True)
                with open(os.path.join(src_p, "kisi.md"), "w", encoding="utf-8") as f:
                    f.write(person_line + "\n")
                with open(os.path.join(out_p, "kisi.md"), "w", encoding="utf-8") as f:
                    f.write(person_line + "\n")
                res_p = A.audit(src_p, out_p)
                self.assertEqual(
                    len(res_p["leaks"]["addr_kisi"]),
                    1,
                    f"Karşı örnek #{idx} audit tarafından addr_kisi yakalanmadı: {person_line!r} -> {res_p['leaks']}",
                )
                self.assertEqual(A.main([src_p, out_p]), 1)


if __name__ == "__main__":
    unittest.main()
