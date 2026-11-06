# 🛡️ Uyap Dosya Maskeleme (YPro)

> **%100 Çevrimdışı (Offline) UYAP Kişisel Veri Maskeleme, Temizleme ve Yapay Zekâya Hazırlama Aracı**

UYAP dava dosyalarında yer alan hassas kişisel verileri (TCKN, IBAN, Açık Adres, Hâkim/Savcı/Kâtip Sicil No) **sıfır veri kaybı prensibiyle** ve **tamamen yerel bilgisayarınızda (offline)** maskeleyerek yapay zekâ analizlerine hazır hale getiren profesyonel hukuk aracıdır.

---

## ✨ Öne Çıkan Özellikler

- **🔒 %100 Çevrimdışı ve Sıfır Veri Sızıntısı:** Hiçbir harici API'ye, sunucuya veya buluta veri göndermez. Tüm işlem yerel Python çekirdeği ile RAM üzerinde gerçekleşir.
- **🛡️ Sıfır Veri Değişikliği (Non-Destructive):** Orijinal `.udf`, `.pdf`, `.tif` dosyalarınıza kesinlikle dokunmaz. Yalnızca makine-okur türev `.md` metinleri üzerinde çalışır.
- **⚖️ Hukuki Bütünlük Garantisi:** Olay örgüsü, tarihler, para miktarları, mahkeme esas/karar numaraları, ceza maddeleri ve taraf ad-soyadları korunur; dava analizi için gerekli hiçbir hukuki veri bozulmaz.
- **📦 EYP ve Arşiv Desteği:** DYS üzerinden gelen `.eyp` (Elektronik Yazışma Paketleri) arşivlerini otomatik açar ve ekleri metne döker.
- **👁️ Apple Vision OCR Uyumu:** Taranmış fiziki belgeleri, tebliğ mazbatalarını ve hastane tahlillerini yerel OCR ile metne dönüştürerek maskeler.

---

## 🎯 Hedef 4 Kişisel Veri Kategorisi

| Veri Türü | Maskeleme Formatı | Açıklama |
| :--- | :--- | :--- |
| **T.C. Kimlik No / YKN** | `[TCKN_GİZLENDİ]` | Algoritmik doğrulama + etiketli OCR yakalama (telefon no ve barkodlar hariç tutulur) |
| **IBAN** | `[IBAN_GİZLENDİ]` | TR ile başlayan tüm ulusal banka hesap numaraları |
| **Hâkim / Savcı / Kâtip Sicil** | `[SİCİL_GİZLENDİ]` | Unvan bazlı regex taraması (Başkan, Üye, Hâkim, C. Savcısı, Yazı İşleri Müdürü, Kâtip) |
| **Açık Adres** | `[ADRES_GİZLENDİ]` | Mahalle, sokak, cadde, kapı no, il/ilçe kalıpları |

---

## ⚙️ 4 Farklı İşlem Modu

1. **🔍 Önizleme / Raporla (Dry-Run):**  
   Dosyaları değiştirmez; klasördeki kişisel verileri tarar, sayar ve istatistiki rapor sunar.
2. **🔒 Güvenli Maskele:**  
   Metin dosyalarını önce `.md.bak` olarak yedekler, ardından 4 veri kategorisini maskeler.
3. **↩️ Yedekten Geri Yükle:**  
   Daha önce alınan `.md.bak` yedeklerini geri yükleyerek orijinal metinlere döner.
4. **📦 İzole Temiz Klasör Üret (AI Export):**  
   Orijinal klasöre dokunmadan, masaüstünde yalnızca maskelenmiş `.md` dosyalarından oluşan, UDF/PDF içermeyen **tamamen güvenli ve izole yeni bir dava klasörü** oluşturur.

---

## 🚀 Kurulum ve Çalıştırma

### 1. Terminal / Python ile Çalıştırma
Herhangi bir üçüncü parti kütüphane (`pip install`) gerektirmez; Python standart kütüphaneleriyle çalışır:

```bash
# Grafik arayüzü başlatmak için:
python3 gui.py

# Doğrudan terminalden maskelemek için:
python3 uyap_redactor.py "/dosya/yolu/Dava Klasoru"
```

### 2. macOS `.app` Olarak Derleme
Uygulamayı çift tıklanabilir yerel macOS uygulaması olarak derlemek için:

```bash
chmod +x build_app.sh
./build_app.sh
```

Derleme tamamlandığında `dist/UYAP Maskeleme.app` dosyası hazır hale gelir. Uygulamayı `Applications` veya `Desktop` dizinine taşıyarak kullanabilirsiniz.

---

## 📁 Proje Yapısı

```text
uyap-dosya-maskeleme-ypro/
├── gui.py              # macOS Tkinter modern grafik arayüzü
├── uyap_redactor.py    # Temel maskeleme ve regex motoru
├── build_app.sh        # macOS .app derleme betiği
├── requirements.txt    # Sistem gereksinimleri (Zero-Dependency)
├── bundle/             # macOS uygulama kaynakları
│   ├── Info.plist      # Paket meta verileri
│   ├── app.icns        # Uygulama simgesi
│   └── launcher.sh     # macOS başlatıcı kabuk betiği
├── README.md           # Dokümantasyon
└── .gitignore          # Git yoksayma kuralları
```

---

## 📄 Lisans ve Sorumluluk Reddi
Bu yazılım avukatlar ve hukuk profesyonelleri için KVKK ve veri koruma uyumluluğunu kolaylaştırmak amacıyla geliştirilmiştir. Yapay zekâ analizleri öncesinde üçüncü parti bulut sistemlerine veri aktarılmadan önce yerelde çalıştırılması tavsiye edilir.
