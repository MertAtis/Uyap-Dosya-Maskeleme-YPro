# 🛡️ Uyap Dosya Maskeleme (YPro)

> **%100 Çevrimdışı (Offline) UYAP Kişisel Veri Maskeleme, Temizleme ve Yapay Zekâya Hazırlama Aracı**

<div align="center">

[![macOS İndir](https://img.shields.io/badge/İndir-UYAP--Maskeleme.dmg-007AFF?style=for-the-badge&logo=apple&logoColor=white)](https://github.com/MertAtis/Uyap-Dosya-Maskeleme-YPro/releases/latest/download/UYAP-Maskeleme.dmg)
[![Son Sürüm](https://img.shields.io/github/v/release/MertAtis/Uyap-Dosya-Maskeleme-YPro?style=for-the-badge&color=10B981&label=S%C3%BCr%C3%BCm)](https://github.com/MertAtis/Uyap-Dosya-Maskeleme-YPro/releases/latest)
[![Platform](https://img.shields.io/badge/Platform-macOS%2011%2B%20(Apple%20Silicon%20%26%20Intel)-6B7280?style=for-the-badge&logo=apple)](https://github.com/MertAtis/Uyap-Dosya-Maskeleme-YPro/releases/latest)
[![Offline](https://img.shields.io/badge/%25100-Çevrimdışı%20(Offline)-3B82F6?style=for-the-badge)](https://github.com/MertAtis/Uyap-Dosya-Maskeleme-YPro)

**[⬇️ Son Sürüm UYAP-Maskeleme.dmg İndir (Doğrudan Bağlantı)](https://github.com/MertAtis/Uyap-Dosya-Maskeleme-YPro/releases/latest/download/UYAP-Maskeleme.dmg)**  
*macOS Sequoia (15.x), Sonoma (14.x), Ventura (13.x) ve Monterey uyumludur. Python veya ek kurulum gerektirmez.*

</div>

---

## ✨ Öne Çıkan Özellikler

- **🔒 %100 Çevrimdışı ve Sıfır Veri Sızıntısı:** Hiçbir harici API'ye, sunucuya veya buluta veri göndermez. Tüm işlem yerel Python çekirdeği ile RAM üzerinde gerçekleşir.
- **🛡️ Sıfır Veri Değişikliği (Non-Destructive):** Orijinal `.udf`, `.pdf`, `.tif` dosyalarınıza kesinlikle dokunmaz. Yalnızca makine-okur türev `.md` metinleri üzerinde çalışır.
- **⚖️ Hukuki Bütünlük Garantisi:** Olay örgüsü, tarihler, para miktarları, mahkeme esas/karar numaraları, ceza maddeleri, anne/baba adları ve taraf ad-soyadları korunur; dava analizi için gerekli hiçbir hukuki veri bozulmaz.
- **📱 Cep Telefonu ve İletişim Koruması:** Müvekkil ve taraf cep telefonlarının tüm Türkiye formatlarını (`05xx`, `+90 5xx`, boşluklu, parantezli) tespit ederek maskeler.
- **🪪 Kimlik Kartı & MRZ Koruma:** Taranmış evraklardaki kimlik fotokopilerinde yer alan yeni/eski seri numaralarını ve 3 satırlı ICAO/MRZ şeritlerini (`I<TUR...`) kapatır.
- **🔄 Otomatik INDEX.md Senkronizasyonu:** OCR sonradan tamamlansa dahi `INDEX.md` dosyasını tarayarak güncel `.md` bağlantılarını ve karakter sayılarını otomatik olarak tabloya işler.
- **🔄 Tek Tıkla Otomatik Güncelleme (Auto-Updater):** Yeni bir sürüm çıktığında uygulama açılışında haber verir; tek tıkla arka planda DMG'yi indirip baştan kurulum gerektirmeden kendini yerinde günceller.
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

## 🎯 Standart Tek İşlem Modu: İzole Temiz Klasör Üret (AI Export)

Kullanıcı deneyimini sadeleştirmek ve veri güvenliğini en üst seviyeye çıkarmak amacıyla uygulama **tek ve kusursuz bir işlem standardına** odaklanmıştır:

* **📦 İzole Temiz Dava Klasörü Oluşturma:**  
  Orijinal klasöre ASLA dokunmaz. Seçilen dava klasörünün yanına `<Dava Klasörü> (Maskelenmis AI)` adında izole bir klasör üretir.
* **📄 Sıfır İkili Dosya Prensibi:**  
  Orijinal `.udf`, `.pdf`, `.tif`, `.eyp` veya ikili ekler hedef klasöre KESİNLİKLE kopyalanmaz. Yalnızca maskelenmiş metin `.md` dosyaları aktarılır.
* **👁️ Yerel Apple Vision OCR Motoru:**  
  Taranmış fotokopi ve ekler macOS yerel OCR motoruyla çevrimdışı olarak çözülür ve `.md` formatında temiz klasöre kazandırılır.
* **🔒 7 Katmanlı Kişisel Veri Maskelemesi:**  
  TCKN, Cep Telefonu, Kimlik Seri No, MRZ Kodu, IBAN, Sicil No ve Açık Adresler tamamen maskelenir.
* **🔄 Tam Otomatik INDEX.md Senkronizasyonu:**  
  `INDEX.md` tablosundaki tüm evrak satırları taranarak üretilen `.md` bağlantıları ve güncel karakter sayılarıyla senkronize edilir.
* **📂 Tek Tıkla Finder'da Açma:**  
  İşlem bittiğinde oluşturulan temiz klasör doğrudan macOS Finder'da açılabilir.

---

## 🚀 Kurulum ve Çalıştırma

### 1. Avukatlar ve Son Kullanıcılar İçin (Önerilen: Tek Tıkla Kurulum)
Kullanıcıların bilgisayarında Python veya herhangi bir geliştirici aracı bulunmasına gerek yoktur:
1. **İndirin:** Doğrudan **[UYAP-Maskeleme.dmg](https://github.com/MertAtis/Uyap-Dosya-Maskeleme-YPro/releases/latest/download/UYAP-Maskeleme.dmg)** bağlantısına tıklayarak son sürüm kurulum paketini indirin.
2. **Kurun:** İndirilen DMG dosyasına çift tıklayın; açılan penceredeki **`UYAP Maskeleme`** simgesini **`Applications` (Uygulamalar)** klasörüne sürükleyip bırakın.
3. **İlk Açılış (macOS Gatekeeper İzni):**
   - Uygulama bağımsız dağıtıldığı için macOS ilk açılışta güvenlik uyarısı gösterebilir.
   - **Yöntem A (Hızlı):** Uygulama simgesine **Sağ Tık (veya İki Parmakla Tık) -> Aç** deyin ve gelen onay penceresinde **Aç**'a tıklayın.
   - **Yöntem B (macOS Sequoia / Sonoma için):** Sağ tıkta "Aç" seçeneği çıkmazsa: Mac'inizde **Sistem Ayarları > Gizlilik ve Güvenlik** sekmesine gidin. Sayfanın altına kaydırın ve *"UYAP Maskeleme engellendi"* uyarısının yanındaki **"Yine de Aç" (Open Anyway)** butonuna tıklayın.
4. **Otomatik Güncelleme:** Uygulamayı bir kez kurduktan sonra güncellemeleri takip etmeniz gerekmez. Yeni bir sürüm çıktığında uygulama açılışta sizi uyarır ve onayınızla kendini baştan kurulum yapmadan günceller.

---

### 2. Geliştiriciler İçin: Kaynak Koddan Çalıştırma ve Derleme

#### A. Terminalden Doğrudan Çalıştırma
Herhangi bir üçüncü parti kütüphane (`pip install`) gerektirmez; Python standart kütüphaneleriyle çalışır:
```bash
# Grafik arayüzü başlatmak için:
python3 gui.py

# Doğrudan terminalden maskelemek için:
python3 uyap_redactor.py "/dosya/yolu/Dava Klasoru"

# Yalnızca INDEX.md dosyasını senkronize etmek için:
python3 uyap_redactor.py "/dosya/yolu/Dava Klasoru" --sync-index
```

#### B. %100 Bağımsız `.app` ve Kurulum `.dmg`'si Derleme (Standalone)
Python çalışma zamanını ve kütüphaneleri uygulamanın içine paketleyip dağıtılabilir DMG üretmek için:
```bash
chmod +x build_dmg.sh
./build_dmg.sh "$HOME/Desktop"
```

---

## 📁 Proje Yapısı

```text
uyap-dosya-maskeleme-ypro/
├── gui.py                  # macOS Tkinter modern grafik arayüzü (2x4 İstatistik Paneli & AutoUpdater)
├── uyap_redactor.py        # 7 Katmanlı maskeleme ve INDEX.md senkronizasyon motoru
├── test_uyap_redactor.py   # Çekirdek motor test paketi
├── test_gui_automation.py  # 40 Testlik GUI, AutoUpdater ve UI/UX otomasyon paketi
├── test_standalone_binary_qa.py # Standalone ikili dosya, otool ve Apple Vision QA paketi
├── build_dmg.sh            # %100 Bağımsız standalone .app ve .dmg derleme betiği (Resmî Dağıtım)
├── build_app.sh            # Geliştiriciler için hızlı yerel test .app derleme betiği
├── UYAP Maskeleme.spec     # PyInstaller bağımsız derleme spesifikasyonu
├── requirements.txt        # Sistem gereksinimleri (Zero-Dependency)
├── bundle/                 # macOS uygulama kaynakları
│   ├── Info.plist          # Paket meta verileri
│   ├── app.icns            # Uygulama simgesi
│   └── launcher.sh         # macOS yerel geliştirici başlatıcı betiği
├── README.md               # Dokümantasyon
└── .gitignore              # Git yoksayma kuralları
```

---

## 📄 Lisans ve Sorumluluk Reddi
Bu yazılım avukatlar ve hukuk profesyonelleri için KVKK ve veri koruma uyumluluğunu kolaylaştırmak amacıyla geliştirilmiştir. Yapay zekâ analizleri öncesinde üçüncü parti bulut sistemlerine veri aktarılmadan önce yerelde çalıştırılması tavsiye edilir.
