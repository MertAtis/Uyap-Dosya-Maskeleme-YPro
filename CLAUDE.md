# UYAP Dosya Maskeleme (YPro) — Mimari ve Değişmez Kurallar

Bu dosya, projede çalışacak tüm yapay zekâ ajanları ve geliştiriciler için bağlayıcı mimari kuralları içerir. Yeni bir özellik eklerken veya hata düzeltirken aşağıdaki ilkeler **kesinlikle bozulamaz**.

## Güncel Sürüm ve Ortam
- **Sürüm:** `v1.5.5` (Build `25`, `bundle/Info.plist`, `gui.py` `APP_VERSION = "1.5.5"`)
- **Bağımlılık İlkesi:** Sıfır üçüncü parti Python paketi (`Zero-Dependency`). Motor yalnızca Python 3 standart kütüphanesi + macOS yerel araçları (`Vision` OCR, `QuickLook`/`qlmanage`, `textutil`, `sips`) ile çalışır (`requirements.txt` boş/sıfır-bağımlılıktır; `tkinterdnd2` yalnızca masaüstü sürükle-bırak için opsiyoneldir).
- **Kapsam:** %100 çevrimdışı (offline) yerel çalışma. AutoUpdater dışında hiçbir ağ çağrısı yapılmaz; dava verisi hiçbir API'ye gönderilmez.

## Değişmez Mimari Kurallar (Non-Negotiable Invariants)

### 1. Orijinale Dokunmama ve İzole Çıktı (`UyapRedactor.export_isolated_clean_folder`)
- Kaynak dava klasörüne asla dosya yazılmaz, orijinal dosyalar değiştirilmez veya silinmez (`real_src == real_dest` koruması yalnızca `(Maskelenmis AI)` çıktı klasörünün güncellenmesine izin verir).
- Hedef klasöre (`<Dava Klasörü> (Maskelenmis AI)`) hiçbir ikili dosya (`.udf`, `.pdf`, `.pages`, `.docx`, `.doc`, `.xlsx`, `.eyp`, `.zip`, `.tif`/`.tiff`, `.png`, `.jpg`/`.jpeg`, `.heic`, `.bak`) veya `_kaynak/` dizini aktarılmaz; yalnızca maskelenmiş `.md` metinleri ve `DAVA_DÖNÜŞÜM_VE_GÜVENLİK_RAPORU.md` bulunur.
- Desteklenen tüm türler: `.md`, `.txt`, `.udf`, `.pdf` (metin katmanı + Vision OCR), `.doc`, `.docx`, `.xlsx`, `.pages` (Index/Document.iwa Ham Snappy + protobuf ayrıştırıcı), `.eyp`, `.zip`, `.tif`/`.tiff`, `.png`, `.jpg`/`.jpeg`, `.heic`.
- İşlenemeyen dosyalar sessizce atlanmaz; `grand_stats["unprocessed"]` listesine `(masked_rel_path, reason)` olarak eklenir ve rapora yazılır.

### 2. Tutarlı Numaralı Etiketler (`MaskRegistry`) ve Sıfır Disk Eşlemesi
- Aynı gerçek değer belge ve alt klasörlerin tamamında aynı numaralı etiketi alır (`[TCKN_1]`, `[TEL_1]`, `[SERİ_NO_1]`, `[MRZ_1]`, `[IBAN_1]`, `[HESAP_1]`, `[KART_1]`, `[SİCİL_1]`, `[ADRES_1] (İlçe/İl)`, `[DAVACI_1]`, `[DAVALI_1]`, `[TANIK_1]`, `[KİŞİ_1]`, `[HAKİM_1]`, `[SAVCI_1]`, `[KÂTİP_1]`).
- **Sıfır Diske Yazma İlkesi:** Gerçek değer ↔ maske etiketi eşleme tablosu **asla** diske, rapora veya `INDEX.md` içine yazılmaz (`audit_output.has_mapping_leak` kontrolü). Yalnızca işlem tamamlandığında bellek üzerinden GUI günlüğüne / terminal çıktısına geçici özet verilir.

### 3. Hukuki Bütünlük ve Birebir Metin Korunumu
- Tarihler, para tutarları, mahkeme adları, esas/karar numaraları, kanun maddeleri, avukat/vekil adları, bilirkişi adları, anne/baba tekil adları, şirket/kurum/banka adları, Ticaret Sicil numaraları, kurum adresleri ve olay yerleri **maskelenmez**.
- Maskeleme dışında kalan tüm metin blokları orijinal evraklarla harfi harfine (%100 verbatim) aynı kalmalıdır.

### 4. Ad Görünümü (`--ad-gorunumu`) ve Yargı Görevlileri
- Seçenekler: `etiket` (varsayılan, tam gizlilik `[DAVACI_1]`) | `bas_harf` (`Ahmet Y. [DAVACI_1]`, kısmi ön-ad açık) | `acik` (taraf/tanık adları açık; TCKN/telefon/adres/IBAN/seri/MRZ/sicil maskelenmeye devam eder).
- Dosya adlarında ve yerel Markdown bağlantı hedeflerinde `bas_harf` kullanılmaz; orada her zaman yalnız `[ROL_n]` etiketi kullanılır.
- Hâkim/savcı/kâtip adları `mask_judicial_names` (`--yargi-isimlerini-koru`) ile bağımsız yönetilir ve `bas_harf` biçiminde açılmaz (ya etiketli ya açık).

### 5. GUI Tasarım Sistemi (`gui.py` — "Editorial LegalTech" Teması)
- Eski Windows görünümü (sert mavi düğmeler, dağınık gri çerçeveler, koyu siyah terminal) geri getirilmemelidir.
- `Theme` sabitleri korunmalıdır: sıcak fildişi kanvas (`BG_CANVAS = "#F7F6F2"`), beyaz kart yüzeyi (`BG_SURFACE = "#FFFFFF"`), kurumsal lacivert vurgu (`BLUE_PRIMARY = "#1B2A4A"`), sıcak fildişi denetim günlüğü (`TERM_BG = "#FCFBF9"`, `TERM_FG = "#1C1B18"`), editoryal mürekkep stat renkleri (`STAT_*`).
- Özel bileşenler ve test sözleşmeleri korunmalıdır: `UyapRedactorApp`, `GlassButton`, `GlassStatCard`, `LegalCheckToggle`, `LegalSegmentRadio`, `GlassStatusPill`, `GlassProgressBar`, `chk_mask_judicial_names`, `mask_judicial_names_var`, `ad_gorunumu_var`, `radio_ad_gorunumu`, `AD_GORUNUMU_SECENEKLERI`, `_ad_gorunumu_secimi`, `_set_option_state`.

### 6. Tek Uygulama ve Temiz Bilgisayar Politikası
- Bilgisayarda tek kurulum olarak **`/Applications/UYAP Maskeleme.app`** tutulur; masaüstünde ikinci bir `.app`, kısayol veya kalıntı `dist/` / `build/` klasörü bırakılmaz.
- Kod değişikliği yapıldığında zorunlu sıra:
  1. Tüm testleri çalıştır (`PYTHONDONTWRITEBYTECODE=1 pytest -q --ignore=test_standalone_binary_qa.py`).
  2. `./build_app.sh` ve `./build_dmg.sh` ile derle, `/Applications/UYAP Maskeleme.app` paketini güncelle ve standalone QA testini çalıştır (`PYTHONDONTWRITEBYTECODE=1 pytest -q test_standalone_binary_qa.py`).
  3. `/Users/avmertatis/.gemini/config/skills/uyap-pii-redactor/scripts/{uyap_redactor.py,gui.py}` kopyalarını senkronize et.
  4. Derleme sonrası `dist/`, `build/`, `__pycache__/`, `.pytest_cache/` ve `/tmp` geçici çıktılarını temizle (`git status -s --ignored` boş kalmalıdır).

### 7. Güvenlik ve Gizlilik Kuralı
- Gerçek müvekkil dosyaları test edilirken terminale, loglara veya sohbet yanıtlarına **hiçbir kişisel veri** (gerçek isim, TCKN, telefon, IBAN, adres, seri no, müvekkil adı içeren klasör/dosya adı) yazdırılmaz. Denetim için `audit_output.py` (`--details` yalnızca yerel geçici dosyaya) kullanılır ve iş bitiminde geçici dosyalar silinir.
