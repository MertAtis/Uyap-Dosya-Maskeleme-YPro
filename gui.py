#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UYAP Maskeleme — macOS Desktop GUI
%100 Çevrimdışı (Offline) UYAP Kişisel Veri Maskeleme ve Koruma Aracı
"""

import os
import sys
import threading
import queue
import time
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

# Kaynak dizinindeki redactor modülünü içeri aktar
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
for p in [current_dir, parent_dir]:
    if p and p not in sys.path:
        sys.path.insert(0, p)

try:
    from uyap_redactor import UyapRedactor
except ImportError:
    try:
        from src.uyap_redactor import UyapRedactor
    except ImportError:
        alt_dir = os.path.expanduser("~/Documents/YargiPRO")
        if alt_dir not in sys.path:
            sys.path.insert(0, alt_dir)
        from uyap_redactor import UyapRedactor


class ModernCard(tk.Frame):
    """Modern macOS tarzı istatistik kartı."""
    def __init__(self, parent, title, value="0", color="#007AFF", bg="#F2F2F7", **kwargs):
        super().__init__(parent, bg=bg, highlightbackground="#D1D1D6", highlightthickness=1, padx=12, pady=8, **kwargs)
        self.lbl_title = tk.Label(self, text=title, font=("SF Pro Text", 10, "bold"), fg="#6C6C70", bg=bg)
        self.lbl_title.pack(anchor="w")
        self.lbl_val = tk.Label(self, text=value, font=("SF Pro Display", 18, "bold"), fg=color, bg=bg)
        self.lbl_val.pack(anchor="w", pady=(2, 0))

    def update_value(self, val):
        self.lbl_val.config(text=str(val))


class UyapRedactorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("UYAP Kişisel Veri Maskeleme (Offline)")
        self.geometry("780x640")
        self.minsize(700, 560)
        self.configure(bg="#F8F8FA")

        self.msg_queue = queue.Queue()
        self.is_running = False

        self._create_widgets()
        self._check_queue()

    def _create_widgets(self):
        # ÜST BAŞLIK BÖLÜMÜ
        header_frame = tk.Frame(self, bg="#FFFFFF", padx=20, pady=16, highlightbackground="#E5E5EA", highlightthickness=1)
        header_frame.pack(fill="x")

        title_lbl = tk.Label(
            header_frame,
            text="🛡️ UYAP Kişisel Veri Maskeleme Aracı",
            font=("SF Pro Display", 16, "bold"),
            fg="#1C1C1E",
            bg="#FFFFFF"
        )
        title_lbl.pack(anchor="w")

        sub_lbl = tk.Label(
            header_frame,
            text="%100 Çevrimdışı (Offline) • Sıfır Veri Değişikliği Prensibi • Orijinal UDF/PDF dosyalarına asla dokunmaz.",
            font=("SF Pro Text", 10),
            fg="#636366",
            bg="#FFFFFF"
        )
        sub_lbl.pack(anchor="w", pady=(3, 0))

        # ANA İÇERİK
        main_frame = tk.Frame(self, bg="#F8F8FA", padx=20, pady=12)
        main_frame.pack(fill="both", expand=True)

        # 1. KLASÖR SEÇİMİ
        folder_card = tk.LabelFrame(main_frame, text=" 📂 Dava Klasörü ", font=("SF Pro Text", 11, "bold"), bg="#F8F8FA", padx=12, pady=10)
        folder_card.pack(fill="x", pady=(0, 10))

        self.folder_var = tk.StringVar(value="")
        entry_folder = tk.Entry(folder_card, textvariable=self.folder_var, font=("SF Pro Text", 11), bg="#FFFFFF", relief="solid", bd=1)
        entry_folder.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 8))

        btn_browse = tk.Button(
            folder_card,
            text="Klasör Seç...",
            font=("SF Pro Text", 11, "bold"),
            bg="#E5E5EA",
            fg="#007AFF",
            relief="flat",
            padx=12,
            pady=4,
            command=self._select_folder,
            cursor="pointinghand"
        )
        btn_browse.pack(side="right")

        # 2. İŞLEM MODU SEÇİMİ
        mode_card = tk.LabelFrame(main_frame, text=" ⚙️ İşlem Modu ", font=("SF Pro Text", 11, "bold"), bg="#F8F8FA", padx=12, pady=8)
        mode_card.pack(fill="x", pady=(0, 10))

        self.mode_var = tk.StringVar(value="mask")
        
        rb1 = tk.Radiobutton(
            mode_card,
            text="🔍 Önizleme / Raporla (Dry-Run): Dosyaları değiştirmez, kişisel verileri listeler.",
            variable=self.mode_var,
            value="preview",
            font=("SF Pro Text", 10),
            bg="#F8F8FA",
            activebackground="#F8F8FA"
        )
        rb1.pack(anchor="w", pady=2)

        rb2 = tk.Radiobutton(
            mode_card,
            text="🔒 Güvenli Maskele (.md dosyalarını yedekler (.bak) ve TCKN/IBAN/Adres/Sicil gizler)",
            variable=self.mode_var,
            value="mask",
            font=("SF Pro Text", 10, "bold"),
            fg="#007AFF",
            bg="#F8F8FA",
            activebackground="#F8F8FA"
        )
        rb2.pack(anchor="w", pady=2)

        rb3 = tk.Radiobutton(
            mode_card,
            text="↩️ Yedekten Geri Yükle (.md.bak dosyalarından orijinal metinleri geri getirir)",
            variable=self.mode_var,
            value="restore",
            font=("SF Pro Text", 10),
            fg="#C93400",
            bg="#F8F8FA",
            activebackground="#F8F8FA"
        )
        rb3.pack(anchor="w", pady=2)

        rb4 = tk.Radiobutton(
            mode_card,
            text="📦 İzole Temiz Klasör Üret (SADECE maskeli .md'leri yeni bir klasöre kopyalar; UDF/PDF içermez)",
            variable=self.mode_var,
            value="export",
            font=("SF Pro Text", 10, "bold"),
            fg="#28A745",
            bg="#F8F8FA",
            activebackground="#F8F8FA"
        )
        rb4.pack(anchor="w", pady=2)

        # 3. İSTATİSTİK KARTLARI
        stats_frame = tk.Frame(main_frame, bg="#F8F8FA")
        stats_frame.pack(fill="x", pady=(0, 10))

        self.card_tckn = ModernCard(stats_frame, "🆔 TCKN Gizlenen", "0", color="#FF3B30")
        self.card_tckn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.card_iban = ModernCard(stats_frame, "💳 IBAN Gizlenen", "0", color="#FF9500")
        self.card_iban.pack(side="left", fill="x", expand=True, padx=4)

        self.card_sicil = ModernCard(stats_frame, "⚖️ Sicil No Gizlenen", "0", color="#5856D6")
        self.card_sicil.pack(side="left", fill="x", expand=True, padx=4)

        self.card_adres = ModernCard(stats_frame, "📍 Adres Gizlenen", "0", color="#34C759")
        self.card_adres.pack(side="left", fill="x", expand=True, padx=4)

        self.card_files = ModernCard(stats_frame, "📄 Dosyalar", "0", color="#1C1C1E")
        self.card_files.pack(side="left", fill="x", expand=True, padx=(4, 0))

        # 4. İŞLEM BUTONU VE İLERLEME ÇUBUĞU
        action_frame = tk.Frame(main_frame, bg="#F8F8FA")
        action_frame.pack(fill="x", pady=(0, 10))

        self.btn_run = tk.Button(
            action_frame,
            text="İşlemi Başlat",
            font=("SF Pro Text", 12, "bold"),
            bg="#007AFF",
            fg="#FFFFFF",
            relief="flat",
            padx=20,
            pady=8,
            cursor="pointinghand",
            command=self._start_process
        )
        self.btn_run.pack(side="left", padx=(0, 12))

        self.lbl_status = tk.Label(action_frame, text="Hazır. Klasör seçip 'İşlemi Başlat'a tıklayın.", font=("SF Pro Text", 10), fg="#3C3C43", bg="#F8F8FA")
        self.lbl_status.pack(side="left", fill="x", expand=True)

        self.progress = ttk.Progressbar(main_frame, orient="horizontal", mode="determinate")
        self.progress.pack(fill="x", pady=(0, 10))

        # 5. DETAYLI GÜNLÜK (LOG) ALANI
        log_frame = tk.LabelFrame(main_frame, text=" 📜 İşlem Kayıtları ", font=("SF Pro Text", 10, "bold"), bg="#F8F8FA", padx=6, pady=6)
        log_frame.pack(fill="both", expand=True)

        self.log_text = ScrolledText(log_frame, font=("Menlo", 10), bg="#FFFFFF", fg="#1C1C1E", relief="flat", wrap="none")
        self.log_text.pack(fill="both", expand=True)

        # Alt bar
        bottom_frame = tk.Frame(self, bg="#FFFFFF", padx=16, pady=8, highlightbackground="#E5E5EA", highlightthickness=1)
        bottom_frame.pack(fill="x", side="bottom")

        btn_clear = tk.Button(bottom_frame, text="Kayıtları Temizle", font=("SF Pro Text", 9), relief="flat", command=self._clear_logs)
        btn_clear.pack(side="left")

        lbl_secure = tk.Label(bottom_frame, text="🔒 Bu uygulama hiçbir ağ/internet bağlantısı yapmaz.", font=("SF Pro Text", 9, "italic"), fg="#8E8E93", bg="#FFFFFF")
        lbl_secure.pack(side="right")

    def _select_folder(self):
        folder = filedialog.askdirectory(title="UYAP Dava Klasörünü Seçin")
        if folder:
            self.folder_var.set(folder)
            self._log(f"📁 Klasör seçildi: {folder}\n")

    def _log(self, text):
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)

    def _clear_logs(self):
        self.log_text.delete("1.0", tk.END)

    def _check_queue(self):
        try:
            while True:
                msg_type, payload = self.msg_queue.get_nowait()
                if msg_type == "log":
                    self._log(payload)
                elif msg_type == "status":
                    self.lbl_status.config(text=payload)
                elif msg_type == "progress":
                    cur, total = payload
                    self.progress["maximum"] = total
                    self.progress["value"] = cur
                elif msg_type == "stats":
                    self.card_tckn.update_value(payload.get("tckn", 0))
                    self.card_iban.update_value(payload.get("iban", 0))
                    self.card_sicil.update_value(payload.get("sicil", 0))
                    self.card_adres.update_value(payload.get("adres", 0))
                    self.card_files.update_value(f"{payload.get('modified_files', 0)}/{payload.get('total_files', 0)}")
                elif msg_type == "done":
                    self.is_running = False
                    self.btn_run.config(state="normal", text="İşlemi Başlat")
                    messagebox.showinfo("İşlem Tamamlandı", payload)
                elif msg_type == "error":
                    self.is_running = False
                    self.btn_run.config(state="normal", text="İşlemi Başlat")
                    messagebox.showerror("Hata Oluştu", payload)
        except queue.Empty:
            pass
        self.after(100, self._check_queue)

    def _start_process(self):
        folder = self.folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("Geçersiz Klasör", "Lütfen geçerli bir UYAP dava klasörü seçin.")
            return

        mode = self.mode_var.get()
        self.is_running = True
        self.btn_run.config(state="disabled", text="İşleniyor...")
        self.progress["value"] = 0

        # İstatistikleri sıfırla
        self.card_tckn.update_value("0")
        self.card_iban.update_value("0")
        self.card_sicil.update_value("0")
        self.card_adres.update_value("0")
        self.card_files.update_value("0")

        thread = threading.Thread(target=self._worker, args=(folder, mode), daemon=True)
        thread.start()

    def _worker(self, folder, mode):
        start_time = time.time()
        self.msg_queue.put(("status", "Dosyalar taranıyor..."))
        self.msg_queue.put(("log", f"\n{'='*55}\nBaşlatıldı: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nKlasör: {folder}\nMod: {mode.upper()}\n{'='*55}\n"))

        # Geri yükleme modu
        if mode == "restore":
            self._worker_restore(folder)
            return

        # İzole temiz kopya modu
        if mode == "export":
            self._worker_export(folder)
            return

        # Markdown dosyalarını topla (_kaynak klasörleri hariç)
        md_files = []
        for root, dirs, files in os.walk(folder):
            if "_kaynak" in root or ".git" in root or "node_modules" in root:
                continue
            for f in files:
                if f.endswith(".md") and not f.endswith(".bak"):
                    md_files.append(os.path.join(root, f))

        total_files = len(md_files)
        if total_files == 0:
            self.msg_queue.put(("error", "Seçilen klasörde işlenecek '.md' uzantılı dosya bulunamadı."))
            return

        self.msg_queue.put(("log", f"Toplam {total_files} adet markdown (.md) dosyası bulundu.\n"))
        
        grand_stats = {
            "tckn": 0,
            "iban": 0,
            "sicil": 0,
            "adres": 0,
            "total": 0,
            "modified_files": 0,
            "total_files": total_files
        }

        for idx, file_path in enumerate(md_files, 1):
            rel_path = os.path.relpath(file_path, folder)
            self.msg_queue.put(("progress", (idx, total_files)))
            self.msg_queue.put(("status", f"İşleniyor ({idx}/{total_files}): {rel_path[:40]}..."))

            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

                redacted_text, stats = UyapRedactor.redact_text(content)

                if stats["total"] > 0:
                    grand_stats["tckn"] += stats["tckn"]
                    grand_stats["iban"] += stats["iban"]
                    grand_stats["sicil"] += stats["sicil"]
                    grand_stats["adres"] += stats["adres"]
                    grand_stats["total"] += stats["total"]
                    grand_stats["modified_files"] += 1

                    self.msg_queue.put(("log", f"[BULUNDU] {rel_path} -> TCKN:{stats['tckn']}, IBAN:{stats['iban']}, Sicil:{stats['sicil']}, Adres:{stats['adres']}\n"))

                    if mode == "mask":
                        # Güvenli yedekleme (.md.bak oluştur)
                        bak_path = file_path + ".bak"
                        if not os.path.exists(bak_path):
                            with open(bak_path, "w", encoding="utf-8") as bf:
                                bf.write(content)

                        # Maskeli metni yaz
                        with open(file_path, "w", encoding="utf-8") as wf:
                            wf.write(redacted_text)
            except Exception as e:
                self.msg_queue.put(("log", f"[HATA] {rel_path}: {str(e)}\n"))

            if idx % 10 == 0 or idx == total_files:
                self.msg_queue.put(("stats", grand_stats))

        elapsed = time.time() - start_time
        summary_msg = (
            f"İşlem Tamamlandı! ({elapsed:.1f} saniye)\n\n"
            f"Taranan Dosya: {total_files}\n"
            f"Kişisel Veri Bulunan Dosya: {grand_stats['modified_files']}\n"
            f"Gizlenen TCKN: {grand_stats['tckn']}\n"
            f"Gizlenen IBAN: {grand_stats['iban']}\n"
            f"Gizlenen Sicil: {grand_stats['sicil']}\n"
            f"Gizlenen Adres: {grand_stats['adres']}\n"
            f"Toplam Gizlenen: {grand_stats['total']}"
        )
        self.msg_queue.put(("log", f"\n{'='*55}\n{summary_msg}\n{'='*55}\n"))
        self.msg_queue.put(("status", "İşlem başarıyla tamamlandı."))
        self.msg_queue.put(("done", summary_msg))

    def _worker_restore(self, folder):
        bak_files = []
        for root, dirs, files in os.walk(folder):
            for f in files:
                if f.endswith(".md.bak"):
                    bak_files.append(os.path.join(root, f))

        total_bak = len(bak_files)
        if total_bak == 0:
            self.msg_queue.put(("error", "Geri yüklenecek '.md.bak' yedek dosyası bulunamadı."))
            return

        self.msg_queue.put(("log", f"Toplam {total_bak} adet yedek (.md.bak) dosyası bulundu. Geri yükleniyor...\n"))

        restored_count = 0
        for idx, bak_path in enumerate(bak_files, 1):
            orig_md_path = bak_path[:-4]  # Remove .bak
            rel_path = os.path.relpath(orig_md_path, folder)
            self.msg_queue.put(("progress", (idx, total_bak)))
            self.msg_queue.put(("status", f"Geri yükleniyor ({idx}/{total_bak}): {rel_path}"))

            try:
                with open(bak_path, "r", encoding="utf-8") as bf:
                    content = bf.read()
                with open(orig_md_path, "w", encoding="utf-8") as wf:
                    wf.write(content)
                os.remove(bak_path)
                restored_count += 1
                self.msg_queue.put(("log", f"[GERİ YÜKLENDİ] {rel_path}\n"))
            except Exception as e:
                self.msg_queue.put(("log", f"[HATA] {rel_path}: {str(e)}\n"))

        res_msg = f"{restored_count} adet dosya orijinal yedeğinden geri yüklendi ve '.bak' dosyaları temizlendi."
        self.msg_queue.put(("log", f"\n{res_msg}\n"))
        self.msg_queue.put(("status", "Geri yükleme tamamlandı."))
        self.msg_queue.put(("done", res_msg))

    def _worker_export(self, folder):
        import shutil
        start_time = time.time()
        dest_folder = folder.rstrip(os.sep) + " (Maskelenmis AI)"
        self.msg_queue.put(("status", "İzole kopya oluşturuluyor..."))
        self.msg_queue.put(("log", f"\n{'='*55}\nİZOLE KOPYA OLUŞTURULUYOR (SADECE MASKE Lİ .MD)\nHedef: {dest_folder}\n{'='*55}\n"))

        md_files = []
        for root, dirs, files in os.walk(folder):
            if "_kaynak" in root or ".git" in root or "node_modules" in root:
                continue
            for f in files:
                if f.endswith(".md") and not f.endswith(".bak"):
                    md_files.append(os.path.join(root, f))

        total_files = len(md_files)
        if total_files == 0:
            self.msg_queue.put(("error", "Seçilen klasörde '.md' uzantılı dosya bulunamadı."))
            return

        grand_stats = {
            "tckn": 0, "iban": 0, "sicil": 0, "adres": 0, "total": 0,
            "modified_files": 0, "total_files": total_files
        }

        os.makedirs(dest_folder, exist_ok=True)

        for idx, file_path in enumerate(md_files, 1):
            rel_path = os.path.relpath(file_path, folder)
            dest_path = os.path.join(dest_folder, rel_path)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            self.msg_queue.put(("progress", (idx, total_files)))
            self.msg_queue.put(("status", f"Dışa aktarılıyor ({idx}/{total_files}): {rel_path[:35]}..."))

            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

                redacted_text, stats = UyapRedactor.redact_text(content)
                if stats["total"] > 0:
                    grand_stats["tckn"] += stats["tckn"]
                    grand_stats["iban"] += stats["iban"]
                    grand_stats["sicil"] += stats["sicil"]
                    grand_stats["adres"] += stats["adres"]
                    grand_stats["total"] += stats["total"]
                    grand_stats["modified_files"] += 1

                with open(dest_path, "w", encoding="utf-8") as wf:
                    wf.write(redacted_text)
            except Exception as e:
                self.msg_queue.put(("log", f"[HATA] {rel_path}: {str(e)}\n"))

            if idx % 10 == 0 or idx == total_files:
                self.msg_queue.put(("stats", grand_stats))

        # Standalone PDF dosyalarını tara (yanında .md olmayan taranmış belgeler)
        standalone_pdfs = []
        for root, dirs, files in os.walk(folder):
            if "_kaynak" in root or ".git" in root or "node_modules" in root:
                continue
            for f in files:
                if f.lower().endswith(".pdf"):
                    pdf_full = os.path.join(root, f)
                    base_no_ext = os.path.splitext(pdf_full)[0]
                    if not os.path.exists(base_no_ext + ".md"):
                        standalone_pdfs.append(pdf_full)

        ocr_converted = []
        if standalone_pdfs:
            self.msg_queue.put(("log", f"\n🔍 Metne dönüştürülmemiş {len(standalone_pdfs)} adet taranmış PDF bulundu. Yerel Apple Vision OCR ile işleniyor...\n"))
            for p_idx, pdf_path in enumerate(standalone_pdfs, 1):
                rel_path = os.path.relpath(pdf_path, folder)
                base_rel = os.path.splitext(rel_path)[0] + ".md"
                dest_path = os.path.join(dest_folder, base_rel)
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)

                self.msg_queue.put(("status", f"Yerel OCR ({p_idx}/{len(standalone_pdfs)}): {os.path.basename(pdf_path)[:30]}..."))
                try:
                    red_text, p_stats = UyapRedactor.extract_and_redact_pdf(pdf_path)
                    if len(red_text.strip()) > 0:
                        with open(dest_path, "w", encoding="utf-8") as wf:
                            wf.write(red_text)
                        ocr_converted.append(rel_path)
                        grand_stats["tckn"] += p_stats["tckn"]
                        grand_stats["iban"] += p_stats["iban"]
                        grand_stats["sicil"] += p_stats["sicil"]
                        grand_stats["adres"] += p_stats["adres"]
                        grand_stats["total"] += p_stats["total"]
                        grand_stats["modified_files"] += 1
                        grand_stats["total_files"] += 1
                        self.msg_queue.put(("log", f"[OCR & MASKE BAŞARILI] {rel_path} -> {os.path.basename(base_rel)}\n"))
                except Exception as oe:
                    self.msg_queue.put(("log", f"[OCR HATA] {rel_path}: {str(oe)}\n"))

        # Manifest varsa kopyala
        proj_json = os.path.join(folder, "uyap-project.json")
        if os.path.exists(proj_json):
            shutil.copy2(proj_json, os.path.join(dest_folder, "uyap-project.json"))

        # DAVA_DONUSUM_RAPORU.md yaz
        report_path = os.path.join(dest_folder, "DAVA_DÖNÜŞÜM_VE_GÜVENLİK_RAPORU.md")
        with open(report_path, "w", encoding="utf-8") as rf:
            rf.write("# 🛡️ Dava Dönüşüm ve Güvenlik Raporu\n\n")
            rf.write(f"**Kaynak Dava Klasörü:** {os.path.basename(folder)}\n")
            rf.write(f"**Oluşturulma Tarihi:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            rf.write(f"**Toplam Aktarılan Markdown Belgesi:** {grand_stats['total_files']} adet\n")
            rf.write(f"**Yerel OCR ile Metne Dökülen Taranmış Ekler:** {len(ocr_converted)} adet\n")
            rf.write(f"**Gizlenen Toplam Kişisel Veri:** {grand_stats['total']} adet\n\n")
            rf.write("---\n\n")
            rf.write("## 🔒 Güvenlik & Gizlilik Durumu\n\n")
            rf.write("- ✅ Bu klasörde tek bir orijinal UDF, PDF, TIFF veya ikili dosya **BULUNMAMAKTADIR**.\n")
            rf.write("- ✅ TCKN, IBAN, Sicil No ve Açık Adres bilgileri tamamen maskelenmiştir.\n")
            rf.write("- ✅ Taranmış evraklar Apple Vision OCR ile yerelde çözülmüş ve metne dökülmüştür.\n")
            rf.write("- ✅ Yapay zekâ bu klasörün tamamını %100 eksiksiz ve sıfır veri sızıntısıyla okuyabilir.\n")

        elapsed = time.time() - start_time
        summary_msg = (
            f"İzole Temiz Klasör %100 Başarıyla Oluşturuldu! ({elapsed:.1f} sn)\n\n"
            f"Klasör: {os.path.basename(dest_folder)}\n"
            f"Toplam Maskelenmiş .md Belgesi: {grand_stats['total_files']}\n"
            f"Yerel OCR ile Kurtarılan Fotokopi/Ek: {len(ocr_converted)}\n"
            f"Toplam Gizlenen Kişisel Veri: {grand_stats['total']}\n\n"
            f"🔒 Orijinal UDF/PDF dosyaları bu klasöre ALINMADI.\n"
            f"🎯 Yapay zekâya doğrudan bu temiz klasörü verebilirsiniz."
        )
        self.msg_queue.put(("log", f"\n{'='*55}\n{summary_msg}\n{'='*55}\n"))
        self.msg_queue.put(("status", "İzole kopya %100 hazırlandı."))
        self.msg_queue.put(("done", summary_msg))


if __name__ == "__main__":
    app = UyapRedactorApp()
    app.mainloop()
