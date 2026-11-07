#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UYAP Maskeleme — macOS Desktop GUI
%100 Çevrimdışı (Offline) UYAP Kişisel Veri Maskeleme ve AI Hazırlık Aracı

TEK VE STANDART İŞLEM MODU:
İzole Temiz Klasör Üret (SADECE maskeli .md'leri yeni klasöre kopyalar,
taranmış evraklara yerel Apple Vision OCR uygular ve INDEX.md senkronize eder).
Orijinal UDF/PDF/TIFF dosyalarına ASLA dokunmaz.
"""

import os
import sys
import threading
import queue
import time
import subprocess
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
        super().__init__(parent, bg=bg, highlightbackground="#D1D1D6", highlightthickness=1, padx=10, pady=6, **kwargs)
        self.lbl_title = tk.Label(self, text=title, font=("SF Pro Text", 9, "bold"), fg="#6C6C70", bg=bg)
        self.lbl_title.pack(anchor="w")
        self.lbl_val = tk.Label(self, text=value, font=("SF Pro Display", 16, "bold"), fg=color, bg=bg)
        self.lbl_val.pack(anchor="w", pady=(1, 0))

    def update_value(self, val):
        self.lbl_val.config(text=str(val))


class UyapRedactorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("UYAP Kişisel Veri Maskeleme & İzole Temiz Klasör Üretici (Offline)")
        self.geometry("840x740")
        self.minsize(780, 660)
        self.configure(bg="#F8F8FA")

        self.msg_queue = queue.Queue()
        self.is_running = False
        self.last_dest_folder = None

        self._create_widgets()
        self._check_queue()

    def _create_widgets(self):
        # 1. ÜST BAŞLIK BÖLÜMÜ
        header_frame = tk.Frame(self, bg="#FFFFFF", padx=20, pady=14, highlightbackground="#E5E5EA", highlightthickness=1)
        header_frame.pack(fill="x")

        title_lbl = tk.Label(
            header_frame,
            text="🛡️ UYAP Kişisel Veri Maskeleme & AI Klasör Üretici",
            font=("SF Pro Display", 16, "bold"),
            fg="#1C1C1E",
            bg="#FFFFFF"
        )
        title_lbl.pack(anchor="w")

        sub_lbl = tk.Label(
            header_frame,
            text="%100 Çevrimdışı (Offline) • Sıfır İkili Dosya • Orijinal UDF/PDF dosyalarına ASLA dokunmaz.",
            font=("SF Pro Text", 10),
            fg="#636366",
            bg="#FFFFFF"
        )
        sub_lbl.pack(anchor="w", pady=(3, 0))

        # ANA İÇERİK
        main_frame = tk.Frame(self, bg="#F8F8FA", padx=20, pady=10)
        main_frame.pack(fill="both", expand=True)

        # 2. KLASÖR SEÇİMİ
        folder_card = tk.LabelFrame(main_frame, text=" 📂 Dava Klasörü ", font=("SF Pro Text", 11, "bold"), bg="#F8F8FA", padx=12, pady=8)
        folder_card.pack(fill="x", pady=(0, 8))

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
            padx=14,
            pady=4,
            command=self._select_folder,
            cursor="pointinghand"
        )
        btn_browse.pack(side="right")

        # 3. TEK VE STANDART İŞLEM MODU (Vurgulanan Güvenli Standart Paneli)
        mode_card = tk.LabelFrame(
            main_frame,
            text=" 🎯 İşlem Standardı (Tek Mod) ",
            font=("SF Pro Text", 11, "bold"),
            bg="#F8F8FA",
            padx=14,
            pady=10
        )
        mode_card.pack(fill="x", pady=(0, 8))

        mode_header = tk.Label(
            mode_card,
            text="📦 İzole Temiz Klasör Üret (AI Export)",
            font=("SF Pro Display", 12, "bold"),
            fg="#007AFF",
            bg="#F8F8FA"
        )
        mode_header.pack(anchor="w")

        mode_desc = tk.Label(
            mode_card,
            text=(
                "• Orijinal dosyalara ASLA dokunmaz; yanına '<Dava Klasörü> (Maskelenmis AI)' adında izole bir klasör üretir.\n"
                "• SADECE maskeli Markdown (.md) dosyalarını aktarır; ikili UDF/PDF/TIFF dosyalarını dışarıda bırakır.\n"
                "• Taranmış fotokopi ve ekleri yerel Apple Vision OCR motoruyla çevrimdışı olarak metne döker.\n"
                "• 7 Katmanlı PII Maskelemesi: TCKN, Cep Telefonu, Kimlik Seri No, MRZ Kodu, IBAN, Sicil No, Adres.\n"
                "• INDEX.md tablosunu güncel karakter sayıları ve .md dosya bağlantılarıyla %100 senkronize eder."
            ),
            font=("SF Pro Text", 10),
            justify="left",
            fg="#3C3C43",
            bg="#F8F8FA"
        )
        mode_desc.pack(anchor="w", pady=(4, 0))

        # 4. İSTATİSTİK KARTLARI (2 Satır x 4 Kart)
        stats_frame_row1 = tk.Frame(main_frame, bg="#F8F8FA")
        stats_frame_row1.pack(fill="x", pady=(0, 4))

        self.card_tckn = ModernCard(stats_frame_row1, "🆔 TCKN Gizlenen", "0", color="#FF3B30")
        self.card_tckn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.card_telefon = ModernCard(stats_frame_row1, "📱 Telefon Gizlenen", "0", color="#007AFF")
        self.card_telefon.pack(side="left", fill="x", expand=True, padx=4)

        self.card_seri_no = ModernCard(stats_frame_row1, "🪪 Kimlik Seri No", "0", color="#AF52DE")
        self.card_seri_no.pack(side="left", fill="x", expand=True, padx=4)

        self.card_mrz = ModernCard(stats_frame_row1, "📑 Kimlik MRZ Kodu", "0", color="#FF2D55")
        self.card_mrz.pack(side="left", fill="x", expand=True, padx=(4, 0))

        stats_frame_row2 = tk.Frame(main_frame, bg="#F8F8FA")
        stats_frame_row2.pack(fill="x", pady=(0, 8))

        self.card_iban = ModernCard(stats_frame_row2, "💳 IBAN Gizlenen", "0", color="#FF9500")
        self.card_iban.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.card_sicil = ModernCard(stats_frame_row2, "⚖️ Sicil No Gizlenen", "0", color="#5856D6")
        self.card_sicil.pack(side="left", fill="x", expand=True, padx=4)

        self.card_adres = ModernCard(stats_frame_row2, "📍 Adres Gizlenen", "0", color="#34C759")
        self.card_adres.pack(side="left", fill="x", expand=True, padx=4)

        self.card_files = ModernCard(stats_frame_row2, "📄 Aktarılan / OCR", "0", color="#1C1C1E")
        self.card_files.pack(side="left", fill="x", expand=True, padx=(4, 0))

        # 5. İŞLEM BUTONLARI VE DURUM
        action_frame = tk.Frame(main_frame, bg="#F8F8FA")
        action_frame.pack(fill="x", pady=(0, 8))

        self.btn_run = tk.Button(
            action_frame,
            text="🚀 İzole Temiz Klasör Üret",
            font=("SF Pro Text", 12, "bold"),
            bg="#007AFF",
            fg="#FFFFFF",
            relief="flat",
            padx=18,
            pady=8,
            cursor="pointinghand",
            command=self._start_process
        )
        self.btn_run.pack(side="left", padx=(0, 10))

        self.btn_open_folder = tk.Button(
            action_frame,
            text="📂 Klasörü Aç (Finder)",
            font=("SF Pro Text", 11, "bold"),
            bg="#E5E5EA",
            fg="#007AFF",
            relief="flat",
            padx=14,
            pady=8,
            state="disabled",
            cursor="pointinghand",
            command=self._open_dest_folder
        )
        self.btn_open_folder.pack(side="left", padx=(0, 12))

        self.lbl_status = tk.Label(
            action_frame,
            text="Hazır. Dava klasörünü seçip 'İzole Temiz Klasör Üret' butonuna tıklayın.",
            font=("SF Pro Text", 10),
            fg="#3C3C43",
            bg="#F8F8FA"
        )
        self.lbl_status.pack(side="left", fill="x", expand=True)

        self.progress = ttk.Progressbar(main_frame, orient="horizontal", mode="determinate")
        self.progress.pack(fill="x", pady=(0, 8))

        # 6. DETAYLI GÜNLÜK (LOG) ALANI
        log_frame = tk.LabelFrame(main_frame, text=" 📜 İşlem Kayıtları ", font=("SF Pro Text", 10, "bold"), bg="#F8F8FA", padx=6, pady=6)
        log_frame.pack(fill="both", expand=True)

        self.log_text = ScrolledText(log_frame, font=("Menlo", 10), bg="#FFFFFF", fg="#1C1C1E", relief="flat", wrap="none")
        self.log_text.pack(fill="both", expand=True)

        # 7. ALT BİLGİ BARI
        bottom_frame = tk.Frame(self, bg="#FFFFFF", padx=16, pady=8, highlightbackground="#E5E5EA", highlightthickness=1)
        bottom_frame.pack(fill="x", side="bottom")

        btn_clear = tk.Button(bottom_frame, text="Kayıtları Temizle", font=("SF Pro Text", 9), relief="flat", command=self._clear_logs)
        btn_clear.pack(side="left")

        lbl_secure = tk.Label(
            bottom_frame,
            text="🔒 Tamamen Yerel ve Çevrimdışı (Zero-Cloud / Offline) • Ağ bağlantısı gerektirmez.",
            font=("SF Pro Text", 9, "italic"),
            fg="#8E8E93",
            bg="#FFFFFF"
        )
        lbl_secure.pack(side="right")

    def _select_folder(self):
        folder = filedialog.askdirectory(title="UYAP Dava Klasörünü Seçin")
        if folder:
            self.folder_var.set(folder)
            self._log(f"📁 Klasör seçildi: {folder}\n")
            self.lbl_status.config(text=f"Klasör hazır: {os.path.basename(folder)}")

    def _open_dest_folder(self):
        if self.last_dest_folder and os.path.exists(self.last_dest_folder):
            subprocess.run(["open", self.last_dest_folder])
        else:
            messagebox.showinfo("Bilgi", "Oluşturulmuş izole temiz klasör bulunamadı.")

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
                    self.progress["maximum"] = max(total, 1)
                    self.progress["value"] = cur
                elif msg_type == "stats":
                    self.card_tckn.update_value(payload.get("tckn", 0))
                    self.card_telefon.update_value(payload.get("telefon", 0))
                    self.card_seri_no.update_value(payload.get("seri_no", 0))
                    self.card_mrz.update_value(payload.get("mrz", 0))
                    self.card_iban.update_value(payload.get("iban", 0))
                    self.card_sicil.update_value(payload.get("sicil", 0))
                    self.card_adres.update_value(payload.get("adres", 0))
                    md_cnt = payload.get("md_transferred", 0)
                    ocr_cnt = payload.get("ocr_converted", 0)
                    self.card_files.update_value(f"{md_cnt} ({ocr_cnt} OCR)")
                elif msg_type == "done":
                    self.is_running = False
                    self.btn_run.config(state="normal", text="🚀 İzole Temiz Klasör Üret")
                    self.btn_open_folder.config(state="normal")
                    summary_text, dest_f = payload if isinstance(payload, tuple) else (payload, self.last_dest_folder)
                    res = messagebox.askyesno(
                        "İşlem Başarıyla Tamamlandı",
                        f"{summary_text}\n\nOluşturulan izole temiz klasörü Finder'da açmak ister misiniz?"
                    )
                    if res and dest_f and os.path.exists(dest_f):
                        subprocess.run(["open", dest_f])
                elif msg_type == "error":
                    self.is_running = False
                    self.btn_run.config(state="normal", text="🚀 İzole Temiz Klasör Üret")
                    messagebox.showerror("Hata Oluştu", payload)
        except queue.Empty:
            pass
        self.after(100, self._check_queue)

    def _start_process(self):
        folder = self.folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("Geçersiz Klasör", "Lütfen geçerli bir UYAP dava klasörü seçin.")
            return

        self.is_running = True
        self.btn_run.config(state="disabled", text="İşleniyor...")
        self.btn_open_folder.config(state="disabled")
        self.progress["value"] = 0

        # İstatistikleri sıfırla
        self.card_tckn.update_value("0")
        self.card_telefon.update_value("0")
        self.card_seri_no.update_value("0")
        self.card_mrz.update_value("0")
        self.card_iban.update_value("0")
        self.card_sicil.update_value("0")
        self.card_adres.update_value("0")
        self.card_files.update_value("0")

        thread = threading.Thread(target=self._worker, args=(folder,), daemon=True)
        thread.start()

    def _worker(self, folder):
        start_time = time.time()
        self.msg_queue.put(("status", "İzole temiz dava klasörü üretimi başlatılıyor..."))
        self.msg_queue.put((
            "log",
            f"\n{'='*60}\n"
            f"BAŞLATILDI: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Kaynak Dava Klasörü: {folder}\n"
            f"İşlem Modu: İzole Temiz Klasör Üret (AI Export)\n"
            f"{'='*60}\n"
        ))

        def progress_cb(evt, msg_or_path, stats):
            cur = stats.get("processed_items", 0)
            tot = stats.get("total_work", stats.get("total_files", 1))

            if evt == "md":
                self.msg_queue.put(("progress", (cur, tot)))
                self.msg_queue.put(("status", f"Metin Maskeleniyor ({cur}/{tot}): {os.path.basename(msg_or_path)[:32]}..."))
                last_st = stats.get("last_file_stats", {})
                if last_st and last_st.get("total", 0) > 0:
                    self.msg_queue.put((
                        "log",
                        f"🔒 [MASKE] {msg_or_path} -> TCKN:{last_st.get('tckn', 0)}, "
                        f"Tel:{last_st.get('telefon', 0)}, Seri:{last_st.get('seri_no', 0)}, "
                        f"MRZ:{last_st.get('mrz', 0)}, IBAN:{last_st.get('iban', 0)}, "
                        f"Sicil:{last_st.get('sicil', 0)}, Adres:{last_st.get('adres', 0)}\n"
                    ))
                self.msg_queue.put(("stats", stats))
            elif evt == "ocr":
                self.msg_queue.put(("progress", (cur, tot)))
                self.msg_queue.put(("status", f"Yerel Apple Vision OCR ({cur}/{tot}): {os.path.basename(msg_or_path)[:32]}..."))
                self.msg_queue.put(("log", f"👁️ [YEREL OCR & MASKE] {msg_or_path}\n"))
                self.msg_queue.put(("stats", stats))
            elif evt == "sync":
                self.msg_queue.put(("status", msg_or_path))
                self.msg_queue.put(("log", f"🔄 [İNDEKS SENKRON] {msg_or_path}\n"))
                self.msg_queue.put(("stats", stats))
            elif evt == "error":
                self.msg_queue.put(("log", f"⚠️ [HATA] {msg_or_path}\n"))

        try:
            dest_folder, final_stats = UyapRedactor.export_isolated_clean_folder(folder, progress_cb=progress_cb)
            self.last_dest_folder = dest_folder
            elapsed = time.time() - start_time

            self.msg_queue.put(("progress", (100, 100)))
            self.msg_queue.put(("stats", final_stats))

            summary_msg = (
                f"İzole Temiz Klasör %100 Başarıyla Oluşturuldu! ({elapsed:.1f} sn)\n\n"
                f"📂 Hedef Klasör: {os.path.basename(dest_folder)}\n"
                f"📄 Aktarılan .md Belgesi: {final_stats.get('md_transferred', 0)} adet\n"
                f"👁️ Yerel OCR ile Çözülen Taranmış Ek: {final_stats.get('ocr_converted', 0)} adet\n"
                f"🔄 İndeks Senkronizasyonu: {final_stats.get('index_synced', 0)} satır güncellendi\n\n"
                f"🔒 Gizlenen Kişisel Veriler (Toplam: {final_stats.get('total', 0)}):\n"
                f"  • TCKN: {final_stats.get('tckn', 0)}\n"
                f"  • Cep Telefonu: {final_stats.get('telefon', 0)}\n"
                f"  • Kimlik Seri No: {final_stats.get('seri_no', 0)}\n"
                f"  • Kimlik MRZ Kodu: {final_stats.get('mrz', 0)}\n"
                f"  • IBAN: {final_stats.get('iban', 0)}\n"
                f"  • Sicil No: {final_stats.get('sicil', 0)}\n"
                f"  • Açık Adres: {final_stats.get('adres', 0)}\n\n"
                f"✅ Bu klasörde tek bir orijinal UDF, PDF, TIFF dosyası BULUNMAMAKTADIR.\n"
                f"🎯 Yapay zekâya doğrudan bu temiz klasörü verebilirsiniz."
            )
            self.msg_queue.put(("log", f"\n{'='*60}\n{summary_msg}\n{'='*60}\n"))
            self.msg_queue.put(("status", "İşlem başarıyla tamamlandı. İzole klasör AI analizine hazır."))
            self.msg_queue.put(("done", (summary_msg, dest_folder)))

        except Exception as e:
            import traceback
            err_trace = traceback.format_exc()
            self.msg_queue.put(("log", f"\n❌ [HATA DETAYI]\n{err_trace}\n"))
            self.msg_queue.put(("status", f"Hata: {str(e)}"))
            self.msg_queue.put(("error", f"İşlem sırasında bir hata oluştu:\n{str(e)}"))


if __name__ == "__main__":
    app = UyapRedactorApp()
    app.mainloop()
