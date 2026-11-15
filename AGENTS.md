# AGENTS.md — UYAP Dosya Maskeleme (YPro) Ajan Çalışma Kuralları

Bu depo **UYAP Maskeleme (`v1.5.4`)** uygulamasının ana kod tabanıdır. Bu projede değişiklik yapan her ajan (Antigravity, Claude Code, Codex, Cursor vb.) [`CLAUDE.md`](file:///Users/avmertatis/Desktop/uyap-dosya-maskeleme-ypro/CLAUDE.md) ile birlikte aşağıdaki özeti esas almalıdır:

1. **Çekirdek İlkeler:**
   - **Sıfır Dış Bağımlılık:** `uyap_redactor.py` ve `gui.py` yalnızca Python standart kütüphanesi + macOS yerleşik ikilileriyle (`Vision` OCR, `qlmanage`, `textutil`, `sips`) çalışır. `pip install` gerektiren yeni bağımlılık eklenmez.
   - **Orijinale Dokunmama:** `export_isolated_clean_folder` kaynak dava klasörüne yazmaz; hedefe (`.udf`, `.pdf`, `.pages`, `.docx`, `.doc`, `.xlsx`, `.eyp`, `.zip`, `.tif`/`.png`/`.jpg`/`.heic`) ikili dosya kopyalamaz, yalnız maskelenmiş `.md` dosyaları + `DAVA_DÖNÜŞÜM_VE_GÜVENLİK_RAPORU.md` üretir.
   - **Sıfır Eşleme Sızıntısı:** `MaskRegistry` eşleme tablosu asla diske/rapora yazılmaz.
   - **Hukuki Veri Korunumu:** Tarihler, tutarlar, esas/karar no, kanun maddeleri, avukat/bilirkişi/kurum adları ve anne/baba tekil adları korunur; maske dışı metin %100 birebir kalır.
   - **Sessiz Atma Yasak:** Okunamayan/desteklenmeyen/şifreli her dosya `grand_stats["unprocessed"]` içinde raporlanır.

2. **Arayüz (`gui.py`) Koruma Kuralları:**
   - Editorial LegalTech paleti (`#F7F6F2` sıcak fildişi kanvas, `#FFFFFF` belge yüzeyi, `#1B2A4A` lacivert vurgu, `#FCFBF9` fildişi günlüğü) ve `UyapRedactorApp`, `LegalCheckToggle`, `LegalSegmentRadio`, `GlassButton`, `GlassStatCard`, `GlassStatusPill`, `GlassProgressBar` bileşenleri ile `UYAP_DISABLE_UPDATE_CHECK=1` test kancası korunmalıdır.

3. **Doğrulama ve Dağıtım Akışı:**
   - Çekirdek + GUI testleri:
     ```bash
     PYTHONDONTWRITEBYTECODE=1 pytest -q --ignore=test_standalone_binary_qa.py
     ```
   - Derleme + Standalone QA + Tek Uygulama Güncelleme:
     ```bash
     ./build_app.sh && ./build_dmg.sh "$HOME/Desktop"
     PYTHONDONTWRITEBYTECODE=1 pytest -q test_standalone_binary_qa.py
     ```
   - Güncel `/Applications/UYAP Maskeleme.app` tek kurulumdur; `~/.gemini/config/skills/uyap-pii-redactor/scripts/{uyap_redactor.py,gui.py}` senkronize edilir ve işlem sonunda `dist/`, `build/`, `__pycache__/`, `.pytest_cache/` silinir.
   - Gerçek dava klasörleriyle yapılan testlerde ekrana veya sohbete gerçek PII basılmaz; yalnızca `audit_output.py` sayısal denetim özetleri ve anonim sayaçlar kullanılır.
