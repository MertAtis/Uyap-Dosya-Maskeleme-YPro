# 🛡️ Uyap Dosya Maskeleme (YPro)

> **%100 Çevrimdışı (Offline) UYAP Kişisel Veri Maskeleme, Temizleme ve Yapay Zekâya Hazırlama Aracı**

UYAP dava dosyalarında yer alan hassas kişisel verileri (TCKN, Cep Telefonu, Kimlik Seri No, Kimlik MRZ Kodu, IBAN, Açık Adres, Hâkim/Savcı/Kâtip Sicil No) **sıfır veri kaybı prensibiyle** ve **tamamen yerel bilgisayarınızda (offline)** maskeleyerek yapay zekâ analizlerine hazır hale getiren profesyonel hukuk aracıdır.

---

## ✨ Öne Çıkan Özellikler

- **🔒 %100 Çevrimdışı ve Sıfır Veri Sızıntısı:** Hiçbir harici API'ye, sunucuya veya buluta veri göndermez. Tüm işlem yerel Python çekirdeği ile RAM üzerinde gerçekleşir.
- **🛡️ Sıfır Veri Değişikliği (Non-Destructive):** Orijinal `.udf`, `.pdf`, `.tif` dosyalarınıza kesinlikle dokunmaz. Yalnızca makine-okur türev `.md` metinleri üzerinde çalışır.
- **⚖️ Hukuki Bütünlük Garantisi:** Olay örgüsü, tarihler, para miktarları, mahkeme esas/karar numaraları, ceza maddeleri, anne/baba adları ve taraf ad-soyadları korunur; dava analizi için gerekli hiçbir hukuki veri bozulmaz.
- **📱 Cep Telefonu ve İletişim Koruması:** Müvekkil ve taraf cep telefonlarının tüm Türkiye formatlarını (`05xx`, `+90 5xx`, boşluklu, parantezli) tespit ederek maskeler.
- **🪪 Kimlik Kartı & MRZ Koruma:** Taranmış evraklardaki kimlik fotokopilerinde yer alan yeni/eski seri numaralarını ve 3 satırlı ICAO/MRZ şeritlerini (`I<TUR...`) kapatır.
- **🔄 Otomatik INDEX.md Senkronizasyonu:** OCR sonradan tamamlansa dahi `INDEX.md` dosyasını tarayarak güncel `.md` bağlantılarını ve karakter sayılarını otomatik olarak tabloya işler.
- **📦 EYP ve Arşiv Desteği:** DYS üzerinden gelen `.eyp` (Elektronik Yazışma Paketleri) arşivlerini otomatik açar ve ekleri metne döker.
- **👁️ Apple Vision OCR Uyumu:** Taranmış fiziki belgeleri, tebliğ mazbatalarını ve hastane tahlillerini yerel OCR ile metne dönüştürerek maskeler.

---

## 🎯 Hedef 7 Kişisel Veri Kategorisi

| Veri Türü | Maskeleme Formatı | Açıklama |
| :--- | :--- | :--- |
| **T.C. Kimlik No / YKN** | `[TCKN_GİZLENDİ]` | Algoritmik doğrulama (Mod-10/11) + etiketli 9-11 hane yakalama (dilekçelerdeki 10 haneli yazım hataları dahil; PTT yıldızlı TCKN'ler korunur) |
| **Cep Telefonu Numarası** | `[TELEFON_GİZLENDİ]` | Türkiye 5xx mobil numaraları (05xx, +90 5xx, boşluklu, tireli, parantezli tüm varyasyonlar) |
| **Kimlik Kartı Seri No** | `[SERİ_NO_GİZLENDİ]` | Yeni çipli (`[A-Z]\d{2}[A-Z]\d{5}`) ve eski nüfus cüzdanı seri numaraları |
| **ICAO / MRZ Kodu** | `[KİMLİK_MRZ_KODU_GİZLENDİ]` | Kimlik kartı ve pasaport altındaki 3 satırlı/2 satırlı makine okunur şeritler (`I<TUR...`) |
| **IBAN** | `[IBAN_GİZLENDİ]` | TR ile başlayan tüm ulusal banka hesap numaraları |
| **Hâkim / Savcı / Kâtip Sicil** | `[SİCİL_GİZLENDİ]` | Unvan bazlı regex taraması (Başkan, Üye, Hâkim, C. Savcısı, Yazı İşleri Müdürü, Kâtip) |
| **Açık Adres** | `[ADRES_GİZLENDİ]` | Mahalle, sokak, cadde, kapı no, il/ilçe kalıpları |

---

## ⚙️ 4 Farklı İşlem Modu

1. **🔍 Önizleme / Raporla (Dry-Run):**  
   Dosyaları değiştirmez; klasördeki kişisel verileri tarar, sayar, `INDEX.md` durumunu kontrol eder ve istatistiki rapor sunar.
2. **🔒 Güvenli Maskele:**  
   Metin dosyalarını önce `.md.bak` olarak yedekler, ardından 7 veri kategorisini maskeler ve `INDEX.md` tablosunu günceller.
3. **↩️ Yedekten Geri Yükle:**  
   Daha önce alınan `.md.bak` yedeklerini geri yükleyerek orijinal metinlere döner.
4. **📦 İzole Temiz Klasör Üret (AI Export):**  
   Orijinal klasöre dokunmadan, masaüstünde yalnızca maskelenmiş `.md` dosyalarından oluşan, UDF/PDF içermeyen, taranmış evrakları Apple Vision OCR ile metne döken ve `INDEX.md` tablosunu %100 senkronize eden **tamamen güvenli ve izole yeni bir dava klasörü** oluşturur.

---

## 🚀 Kurulum ve Çalıştırma

### 1. Terminal / Python ile Çalıştırma
Herhangi bir üçüncü parti kütüphane (`pip install`) gerektirmez; Python standart kütüphaneleriyle çalışır:

```bash
# Grafik arayüzü başlatmak için:
python3 gui.py

# Doğrudan terminalden maskelemek için:
python3 uyap_redactor.py "/dosya/yolu/Dava Klasoru"

# Yalnızca INDEX.md dosyasını senkronize etmek için:
python3 uyap_redactor.py "/dosya/yolu/Dava Klasoru" --sync-index
```

### 2. macOS `.app` Olarak Derleme
Uygulamayı çift tıklanabilir yerel macOS uygulaması olarak derlemek için:

```bash
chmod +x build_app.sh
./build_app.sh
```

Derleme tamamlandığında `dist/UYAP Maskeleme.app` dosyası hazır hale gelir. Masaüstündeki uygulamayı güncellemek için:

```bash
./build_app.sh /Users/avmertatis/Desktop
```

---

## 📁 Proje Yapısı

```text
uyap-dosya-maskeleme-ypro/
├── gui.py                  # macOS Tkinter modern grafik arayüzü (2x4 İstatistik Paneli)
├── uyap_redactor.py        # 7 Katmanlı maskeleme ve INDEX.md senkronizasyon motoru
├── test_uyap_redactor.py   # Kapsamlı otomatik birim test paketi
├── build_app.sh            # macOS .app derleme betiği
├── requirements.txt        # Sistem gereksinimleri (Zero-Dependency)
├── bundle/                 # macOS uygulama kaynakları
│   ├── Info.plist          # Paket meta verileri
│   ├── app.icns            # Uygulama simgesi
│   └── launcher.sh         # macOS başlatıcı kabuk betiği
├── README.md               # Dokümantasyon
└── .gitignore              # Git yoksayma kuralları
```

---

## 📄 Lisans ve Sorumluluk Reddi
Bu yazılım avukatlar ve hukuk profesyonelleri için KVKK ve veri koruma uyumluluğunu kolaylaştırmak amacıyla geliştirilmiştir. Yapay zekâ analizleri öncesinde üçüncü parti bulut sistemlerine veri aktarılmadan önce yerelde çalıştırılması tavsiye edilir.
