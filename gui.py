#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UYAP Maskeleme — macOS Desktop GUI
%100 Çevrimdışı (Offline) UYAP Kişisel Veri Maskeleme ve AI Hazırlık Aracı

Tasarım ve Estetik:
- Shadcn Sadeliği (Zinc renk paleti, mikro kontrast, 1px rafine kenarlıklar, minimalist hap rozetler)
- Apple Elitliği (macOS HIG, SF Pro Display/Text/Mono tipografisi, hover/press mikro etkileşimleri)
- Liquid Glass (Katmanlı buzlu cam yüzeyler, üst kenar ışık yansıması pahı, parlayan durum hapı)

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


# ==============================================================================
# TASARIM SİSTEMİ — SHADCN ZINC & APPLE HIG & LIQUID GLASS
# ==============================================================================
class Theme:
    # macOS Backdrop & Glass Surfaces
    BG_CANVAS = "#F4F4F6"         # Apple HIG hafif soğuk kanvas
    BG_SURFACE = "#FFFFFF"        # Saf beyaz cam panel
    BG_SURFACE_ALT = "#FAFAFB"    # İkincil hafif cam yüzey
    BORDER_GLASS = "#E4E4E7"      # Zinc-200 1px rafine kenarlık
    BORDER_HOVER = "#A1A1AA"      # Zinc-400 fare üzerine gelme kenarlığı
    BORDER_SHINE = "#FFFFFF"      # Cam üst kenar ışık yansıması (Liquid Glass)

    # Tipografi Renkleri (Zinc Scale)
    TEXT_PRIMARY = "#09090B"      # Zinc-950 en yüksek kontrast
    TEXT_SECONDARY = "#3F3F46"    # Zinc-700 ikincil metin
    TEXT_MUTED = "#71717A"        # Zinc-500 açıklama / soluk metin
    TEXT_TERTIARY = "#A1A1AA"     # Zinc-400 yer tutucu / mikro metin

    # Apple Vurgu Renkleri (System Colors)
    BLUE_PRIMARY = "#0071E3"      # Apple System Blue
    BLUE_HOVER = "#0077ED"
    BLUE_PRESS = "#005BB5"

    # Stat Kartı Vurguları (Canlı Apple Paleti)
    STAT_TCKN = "#EF4444"         # Apple Red (Zinc-500 Red)
    STAT_TEL = "#0284C7"          # Apple Sky / Cyan
    STAT_SERI = "#8B5CF6"         # Apple Purple
    STAT_MRZ = "#F43F5E"          # Apple Rose
    STAT_IBAN = "#D97706"         # Apple Amber
    STAT_SICIL = "#6366F1"        # Apple Indigo
    STAT_ADRES = "#059669"        # Apple Emerald
    STAT_FILES = "#18181B"        # Deep Zinc

    # Terminal / Konsol (Koyu Cam Konsol)
    TERM_BG = "#09090B"           # Zinc-950 koyu zemin
    TERM_BAR = "#18181B"          # Zinc-900 konsol başlık çubuğu
    TERM_BORDER = "#27272A"       # Zinc-800 konsol sınırı
    TERM_FG = "#F4F4F5"           # Zinc-100 ana metin
    TERM_LINE = "#27272A"

    # Tipografi Tanımları (Apple HIG Font Hiyerarşisi)
    @staticmethod
    def font_display(size=16, weight="bold"):
        return ("SF Pro Display", size, weight)

    @staticmethod
    def font_text(size=10, weight="normal"):
        return ("SF Pro Text", size, weight)

    @staticmethod
    def font_mono(size=10, weight="normal"):
        return ("SF Mono", size, weight)


# ==============================================================================
# ÖZEL BİLEŞENLER (LIQUID GLASS & SHADCN BİLEŞENLERİ)
# ==============================================================================

class GlassPillBadge(tk.Frame):
    """Shadcn minimalist hap rozet (Capsule / Pill Badge)."""
    def __init__(self, parent, text, dot_color="#10B981", bg="#F4F4F5", border="#E4E4E7", fg="#27272A", **kwargs):
        super().__init__(parent, bg=bg, highlightbackground=border, highlightthickness=1, padx=9, pady=4, **kwargs)
        self.lbl_dot = tk.Label(self, text="●", font=Theme.font_text(7, "bold"), fg=dot_color, bg=bg)
        self.lbl_dot.pack(side="left", padx=(0, 5))
        self.lbl_text = tk.Label(self, text=text, font=Theme.font_text(9, "bold"), fg=fg, bg=bg)
        self.lbl_text.pack(side="left")


class GlassButton(tk.Frame):
    """
    Apple / Shadcn Liquid Glass Etkileşimli Buton.
    - Pointer-down anında gecikmesiz tepki (WWDC Fluid Interfaces kuralı).
    - Hover ve press durumlarında yumuşak tonlama.
    - 1px rafine sınır çizgisi ve üst cam ışık yansıması pahı.
    """
    def __init__(
        self,
        parent,
        text="",
        command=None,
        variant="primary",  # "primary" | "secondary" | "subtle"
        font=None,
        padx=18,
        pady=7,
        state="normal",
        **kwargs
    ):
        self.variant = variant
        self.command = command
        self.state = state
        self._is_pressed = False
        self.pad_x = padx
        self.pad_y = pady

        if variant == "primary":
            self.bg_normal = Theme.BLUE_PRIMARY
            self.bg_hover = Theme.BLUE_HOVER
            self.bg_press = Theme.BLUE_PRESS
            self.fg_normal = "#FFFFFF"
            self.border_normal = "#0062C4"
            self.border_hover = "#005BB5"
            self.bg_disabled = "#E4E4E7"
            self.fg_disabled = "#A1A1AA"
            self.border_disabled = "#E4E4E7"
            default_font = Theme.font_text(11, "bold")
        elif variant == "secondary":
            self.bg_normal = "#FFFFFF"
            self.bg_hover = "#F4F4F5"
            self.bg_press = "#E4E4E7"
            self.fg_normal = Theme.BLUE_PRIMARY
            self.border_normal = Theme.BORDER_GLASS
            self.border_hover = Theme.BORDER_HOVER
            self.bg_disabled = "#FAFAFA"
            self.fg_disabled = "#A1A1AA"
            self.border_disabled = "#E4E4E7"
            default_font = Theme.font_text(11, "bold")
        else:  # subtle
            self.bg_normal = "#27272A"
            self.bg_hover = "#3F3F46"
            self.bg_press = "#18181B"
            self.fg_normal = "#F4F4F5"
            self.border_normal = "#3F3F46"
            self.border_hover = "#52525B"
            self.bg_disabled = "#18181B"
            self.fg_disabled = "#71717A"
            self.border_disabled = "#27272A"
            default_font = Theme.font_text(9, "bold")

        cur_bg = self.bg_normal if state == "normal" else self.bg_disabled
        cur_border = self.border_normal if state == "normal" else self.border_disabled
        cur_fg = self.fg_normal if state == "normal" else self.fg_disabled

        super().__init__(
            parent,
            bg=cur_bg,
            highlightbackground=cur_border,
            highlightthickness=1,
            **kwargs
        )

        self.btn_font = font or default_font
        self.label = tk.Label(
            self,
            text=text,
            font=self.btn_font,
            bg=cur_bg,
            fg=cur_fg,
            padx=padx,
            pady=pady,
            cursor="pointinghand" if state == "normal" else "arrow"
        )
        self.label.pack(fill="both", expand=True)

        for w in (self, self.label):
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
            w.bind("<ButtonPress-1>", self._on_press)
            w.bind("<ButtonRelease-1>", self._on_release)

    def _on_enter(self, e):
        if self.state == "normal" and not self._is_pressed:
            self.config(bg=self.bg_hover, highlightbackground=self.border_hover)
            self.label.config(bg=self.bg_hover)

    def _on_leave(self, e):
        if self.state == "normal":
            self._is_pressed = False
            self.config(bg=self.bg_normal, highlightbackground=self.border_normal)
            self.label.config(bg=self.bg_normal)

    def _on_press(self, e):
        if self.state == "normal":
            self._is_pressed = True
            self.config(bg=self.bg_press, highlightbackground=self.border_hover)
            self.label.config(bg=self.bg_press)

    def _on_release(self, e):
        if self.state == "normal":
            was_pressed = self._is_pressed
            self._is_pressed = False
            self.config(bg=self.bg_hover, highlightbackground=self.border_hover)
            self.label.config(bg=self.bg_hover)
            # Fare imleci buton alanı içinde mi bırakıldı kontrolü
            if was_pressed and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
                if self.command:
                    self.command()

    def config(self, **kwargs):
        if "state" in kwargs:
            self.state = kwargs.pop("state")
            if self.state == "disabled":
                super().config(bg=self.bg_disabled, highlightbackground=self.border_disabled)
                self.label.config(bg=self.bg_disabled, fg=self.fg_disabled, cursor="arrow")
            else:
                super().config(bg=self.bg_normal, highlightbackground=self.border_normal)
                self.label.config(bg=self.bg_normal, fg=self.fg_normal, cursor="pointinghand")
        if "text" in kwargs:
            txt = kwargs.pop("text")
            self.label.config(text=txt)
        if kwargs:
            super().config(**kwargs)

    def configure(self, **kwargs):
        self.config(**kwargs)

    def __setitem__(self, key, value):
        self.config(**{key: value})

    def __getitem__(self, key):
        if key == "state":
            return self.state
        if key == "text":
            return self.label.cget("text")
        return super().__getitem__(key)


class GlassStatCard(tk.Frame):
    """
    Apple & Shadcn Liquid Glass İstatistik Kartı.
    - Katmanlı cam panel (#FFFFFF üzerinde 1px #E4E4E7 kenarlık).
    - Üst kenarda 1px ışık yansıması simülasyonu.
    - Canlı ve ayırt edici Apple HIG tipografisi.
    - Fare üzerine gelindiğinde mikro kenarlık tepkisi.
    """
    def __init__(self, parent, title, value="0", color=Theme.BLUE_PRIMARY, **kwargs):
        super().__init__(
            parent,
            bg=Theme.BG_SURFACE,
            highlightbackground=Theme.BORDER_GLASS,
            highlightthickness=1,
            padx=12,
            pady=9,
            **kwargs
        )
        self.color = color

        # 1. Üst kenar Liquid Glass ışık yansıması (Subtle Highlight Bevel)
        self.top_highlight = tk.Frame(self, bg="#F4F4F6", height=1)
        self.top_highlight.pack(fill="x", pady=(0, 5))

        # 2. Başlık / Etiket
        self.lbl_title = tk.Label(
            self,
            text=title,
            font=Theme.font_text(9, "bold"),
            fg=Theme.TEXT_MUTED,
            bg=Theme.BG_SURFACE
        )
        self.lbl_title.pack(anchor="w")

        # 3. İstatistik Sayı Değeri (SF Pro Display)
        self.lbl_val = tk.Label(
            self,
            text=str(value),
            font=Theme.font_display(17, "bold"),
            fg=color,
            bg=Theme.BG_SURFACE
        )
        self.lbl_val.pack(anchor="w", pady=(2, 0))

        # Hover mikro etkileşimi
        for w in (self, self.top_highlight, self.lbl_title, self.lbl_val):
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)

    def _on_enter(self, e):
        self.config(highlightbackground=Theme.BORDER_HOVER)

    def _on_leave(self, e):
        self.config(highlightbackground=Theme.BORDER_GLASS)

    def update_value(self, val):
        self.lbl_val.config(text=str(val))


# Eski isimle geriye dönük tam uyumluluk
ModernCard = GlassStatCard


class GlassStatusPill(tk.Frame):
    """
    Apple Tarzı Parlayan Cam Hap Durum Göstergesi (Glowing Pill Status).
    - Durum değişimine göre renk değiştiren parlayan gösterge noktası (●).
    - İşlem sürerken yumuşak nefes alan (pulsing) görsel canlılık.
    """
    def __init__(self, parent, text="Hazır. Dava klasörünü seçip başlatın.", **kwargs):
        super().__init__(
            parent,
            bg=Theme.BG_SURFACE,
            highlightbackground=Theme.BORDER_GLASS,
            highlightthickness=1,
            padx=12,
            pady=7,
            **kwargs
        )
        self.pulse_index = 0
        self.is_pulsing = False

        # Parlayan durum noktası
        self.lbl_dot = tk.Label(
            self,
            text="●",
            font=Theme.font_text(10, "bold"),
            fg="#10B981",  # Varsayılan: Canlı Zümrüt Yeşili (Hazır)
            bg=Theme.BG_SURFACE
        )
        self.lbl_dot.pack(side="left", padx=(0, 7))

        # Durum Metni
        self.lbl_text = tk.Label(
            self,
            text=text,
            font=Theme.font_text(10, "normal"),
            fg=Theme.TEXT_SECONDARY,
            bg=Theme.BG_SURFACE
        )
        self.lbl_text.pack(side="left", fill="x", expand=True, anchor="w")

    def config(self, **kwargs):
        if "text" in kwargs:
            txt = kwargs.pop("text")
            self.lbl_text.config(text=txt)
            # Otomatik durum algılama ve parıldama moduna geçiş
            txt_lower = txt.lower()
            if any(k in txt_lower for k in ["işleniyor", "başlatılıyor", "maskeleniyor", "ocr", "senkron"]):
                self.start_pulse()
            elif any(k in txt_lower for k in ["hata", "başarısız", "iptal"]):
                self.stop_pulse(color="#EF4444")
            elif any(k in txt_lower for k in ["tamamlandı", "başarıyla", "hazır"]):
                self.stop_pulse(color="#10B981")
            else:
                self.stop_pulse(color="#10B981")
        if kwargs:
            super().config(**kwargs)

    def configure(self, **kwargs):
        self.config(**kwargs)

    def start_pulse(self):
        if not self.is_pulsing:
            self.is_pulsing = True
            self._pulse_loop()

    def stop_pulse(self, color="#10B981"):
        self.is_pulsing = False
        self.lbl_dot.config(fg=color)

    def _pulse_loop(self):
        if not self.is_pulsing:
            return
        colors = ["#0071E3", "#38BDF8", "#818CF8", "#0071E3"]
        self.pulse_index = (self.pulse_index + 1) % len(colors)
        self.lbl_dot.config(fg=colors[self.pulse_index])
        self.after(380, self._pulse_loop)


class GlassProgressBar(tk.Canvas):
    """
    Liquid Glass Minimalist İlerleme Çubuğu (Canvas Tabanlı).
    - macOS Aqua platform kısıtlarından bağımsız piksel-hassas çizim.
    - Yumuşak yuvarlatılmış kapsül uçları.
    - Üst kenarda cam ışık parıltısı şeridi.
    """
    def __init__(self, parent, height=12, bg=Theme.BG_CANVAS, track_color="#E4E4E7", fill_color=Theme.BLUE_PRIMARY, **kwargs):
        super().__init__(parent, height=height, bg=bg, highlightthickness=0, bd=0, **kwargs)
        self.bar_height = height
        self.track_color = track_color
        self.fill_color = fill_color
        self.val = 0
        self.max_val = 100
        self.bind("<Configure>", self._on_resize)

    def __setitem__(self, key, value):
        if key == "value":
            self.val = max(0, value)
            self._redraw()
        elif key == "maximum":
            self.max_val = max(1, value)
            self._redraw()

    def __getitem__(self, key):
        if key == "value":
            return self.val
        if key == "maximum":
            return self.max_val
        raise KeyError(key)

    def _on_resize(self, event):
        self._redraw()

    def _redraw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.bar_height
        if w < 10:
            return

        r = h / 2
        # Kapsül Taban İzi (Track)
        self.create_oval(0, 0, h, h, fill=self.track_color, outline="")
        self.create_oval(w - h, 0, w, h, fill=self.track_color, outline="")
        self.create_rectangle(r, 0, w - r, h, fill=self.track_color, outline="")

        # İlerleme Dolgusu
        ratio = min(max(self.val / max(self.max_val, 1), 0.0), 1.0)
        if ratio > 0:
            fill_w = max(h, w * ratio)
            self.create_oval(0, 0, h, h, fill=self.fill_color, outline="")
            self.create_oval(fill_w - h, 0, fill_w, h, fill=self.fill_color, outline="")
            self.create_rectangle(r, 0, fill_w - r, h, fill=self.fill_color, outline="")

            # Sıvı Cam Üst Işık Yansıması (Liquid Glass Highlight)
            shine_h = max(2, int(h * 0.35))
            self.create_rectangle(r, 1, fill_w - r, shine_h, fill="#60A5FA", outline="")


# ==============================================================================
# ANA UYGULAMA PENCERESİ (UYAP REDACTOR APP)
# ==============================================================================

class UyapRedactorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("UYAP Kişisel Veri Maskeleme & İzole Temiz Klasör Üretici (Offline)")
        self.geometry("860x780")
        self.minsize(800, 700)
        self.configure(bg=Theme.BG_CANVAS)

        self.msg_queue = queue.Queue()
        self.is_running = False
        self.last_dest_folder = None

        self._create_widgets()
        self._setup_shortcuts()
        self._check_queue()

    def _setup_shortcuts(self):
        """macOS Klavye Kısayolları (⌘O, ⌘R, ⌘K)."""
        self.bind("<Command-o>", lambda e: self._select_folder())
        self.bind("<Control-o>", lambda e: self._select_folder())
        self.bind("<Command-r>", lambda e: self._start_process() if not self.is_running else None)
        self.bind("<Control-r>", lambda e: self._start_process() if not self.is_running else None)
        self.bind("<Command-k>", lambda e: self._clear_logs())
        self.bind("<Control-k>", lambda e: self._clear_logs())

    def _create_widgets(self):
        # ----------------------------------------------------------------------
        # 1. ÜST BAŞLIK BÖLÜMÜ (FROSTED GLASS HEADER)
        # ----------------------------------------------------------------------
        header_frame = tk.Frame(
            self,
            bg=Theme.BG_SURFACE,
            padx=24,
            pady=14,
            highlightbackground=Theme.BORDER_GLASS,
            highlightthickness=1
        )
        header_frame.pack(fill="x")

        # Üst Satır: Başlık & Rozetler
        header_top = tk.Frame(header_frame, bg=Theme.BG_SURFACE)
        header_top.pack(fill="x")

        title_lbl = tk.Label(
            header_top,
            text="🛡️ UYAP Kişisel Veri Maskeleme",
            font=Theme.font_display(17, "bold"),
            fg=Theme.TEXT_PRIMARY,
            bg=Theme.BG_SURFACE
        )
        title_lbl.pack(side="left")

        # Shadcn Hap Rozetler (Pill Badges)
        badge_container = tk.Frame(header_top, bg=Theme.BG_SURFACE)
        badge_container.pack(side="right")

        GlassPillBadge(
            badge_container,
            text="%100 Çevrimdışı",
            dot_color="#10B981",
            bg="#F0FDF4",
            border="#DCFCE7",
            fg="#15803D"
        ).pack(side="left", padx=(0, 6))

        GlassPillBadge(
            badge_container,
            text="Sıfır Değişiklik",
            dot_color="#3B82F6",
            bg="#EFF6FF",
            border="#DBEAFE",
            fg="#1D4ED8"
        ).pack(side="left", padx=(0, 6))

        GlassPillBadge(
            badge_container,
            text="Apple Vision OCR",
            dot_color="#8B5CF6",
            bg="#F5F3FF",
            border="#EDE9FE",
            fg="#6D28D9"
        ).pack(side="left")

        # Alt Satır: Açıklama
        sub_lbl = tk.Label(
            header_frame,
            text="İzole Temiz Klasör & AI Hazırlık Motoru • Orijinal UDF/PDF/TIFF dosyalarına ASLA dokunmaz.",
            font=Theme.font_text(10, "normal"),
            fg=Theme.TEXT_MUTED,
            bg=Theme.BG_SURFACE
        )
        sub_lbl.pack(anchor="w", pady=(4, 0))

        # ----------------------------------------------------------------------
        # ANA İÇERİK KONTEYNERİ
        # ----------------------------------------------------------------------
        main_frame = tk.Frame(self, bg=Theme.BG_CANVAS, padx=20, pady=12)
        main_frame.pack(fill="both", expand=True)

        # ----------------------------------------------------------------------
        # 2. DAVA KLASÖRÜ SEÇİMİ (GLASS PANEL)
        # ----------------------------------------------------------------------
        folder_card = tk.Frame(
            main_frame,
            bg=Theme.BG_SURFACE,
            highlightbackground=Theme.BORDER_GLASS,
            highlightthickness=1,
            padx=14,
            pady=10
        )
        folder_card.pack(fill="x", pady=(0, 8))

        # Başlık ve ipucu
        f_header = tk.Frame(folder_card, bg=Theme.BG_SURFACE)
        f_header.pack(fill="x", pady=(0, 6))

        tk.Label(
            f_header,
            text="📂  Kaynak Dava Klasörü",
            font=Theme.font_text(11, "bold"),
            fg=Theme.TEXT_PRIMARY,
            bg=Theme.BG_SURFACE
        ).pack(side="left")

        tk.Label(
            f_header,
            text="UYAP UDF, taranmış TIFF veya PDF içeren yerel klasör",
            font=Theme.font_text(9, "normal"),
            fg=Theme.TEXT_MUTED,
            bg=Theme.BG_SURFACE
        ).pack(side="right")

        # Giriş kutusu ve Seç butonu satırı
        f_input_row = tk.Frame(folder_card, bg=Theme.BG_SURFACE)
        f_input_row.pack(fill="x")

        self.folder_var = tk.StringVar(value="")
        entry_wrap = tk.Frame(
            f_input_row,
            bg=Theme.BG_SURFACE_ALT,
            highlightbackground=Theme.BORDER_GLASS,
            highlightthickness=1,
            padx=8,
            pady=3
        )
        entry_wrap.pack(side="left", fill="x", expand=True, padx=(0, 8))

        entry_folder = tk.Entry(
            entry_wrap,
            textvariable=self.folder_var,
            font=Theme.font_text(11, "normal"),
            bg=Theme.BG_SURFACE_ALT,
            fg=Theme.TEXT_PRIMARY,
            relief="flat",
            bd=0,
            insertbackground=Theme.TEXT_PRIMARY
        )
        entry_folder.pack(fill="x", expand=True, ipady=3)

        btn_browse = GlassButton(
            f_input_row,
            text="Klasör Seç...",
            variant="secondary",
            command=self._select_folder,
            padx=14,
            pady=6
        )
        btn_browse.pack(side="right")

        # ----------------------------------------------------------------------
        # 3. TEK VE STANDART İŞLEM MODU (STANDART PANELİ)
        # ----------------------------------------------------------------------
        mode_card = tk.Frame(
            main_frame,
            bg=Theme.BG_SURFACE,
            highlightbackground=Theme.BORDER_GLASS,
            highlightthickness=1,
            padx=14,
            pady=10
        )
        mode_card.pack(fill="x", pady=(0, 8))

        mode_header = tk.Frame(mode_card, bg=Theme.BG_SURFACE)
        mode_header.pack(fill="x", pady=(0, 4))

        tk.Label(
            mode_header,
            text="📦  Standart İşlem Modu: İzole Temiz Klasör (AI Export)",
            font=Theme.font_display(11, "bold"),
            fg=Theme.BLUE_PRIMARY,
            bg=Theme.BG_SURFACE
        ).pack(side="left")

        GlassPillBadge(
            mode_header,
            text="Güvenli Standart",
            dot_color="#10B981",
            bg="#F0FDF4",
            border="#DCFCE7",
            fg="#15803D"
        ).pack(side="right")

        mode_desc = tk.Label(
            mode_card,
            text=(
                "• Orijinal dosyalara ASLA dokunmaz; yanına '<Dava Klasörü> (Maskelenmis AI)' adında izole bir klasör üretir.\n"
                "• SADECE maskeli Markdown (.md) dosyalarını aktarır; ikili UDF/PDF/TIFF dosyalarını dışarıda bırakır.\n"
                "• Taranmış fotokopi ve ekleri yerel Apple Vision OCR motoruyla çevrimdışı olarak metne döker.\n"
                "• 7 Katmanlı PII Maskelemesi: TCKN, Cep Telefonu, Kimlik Seri No, MRZ Kodu, IBAN, Sicil No, Adres.\n"
                "• INDEX.md tablosunu güncel karakter sayıları ve .md dosya bağlantılarıyla %100 senkronize eder."
            ),
            font=Theme.font_text(10, "normal"),
            justify="left",
            fg=Theme.TEXT_SECONDARY,
            bg=Theme.BG_SURFACE
        )
        mode_desc.pack(anchor="w", pady=(2, 0))

        # ----------------------------------------------------------------------
        # 4. İSTATİSTİK KARTLARI (2 Satır x 4 Cam Kart)
        # ----------------------------------------------------------------------
        stats_frame_row1 = tk.Frame(main_frame, bg=Theme.BG_CANVAS)
        stats_frame_row1.pack(fill="x", pady=(0, 5))

        self.card_tckn = GlassStatCard(stats_frame_row1, "🆔 TCKN Gizlenen", "0", color=Theme.STAT_TCKN)
        self.card_tckn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.card_telefon = GlassStatCard(stats_frame_row1, "📱 Telefon Gizlenen", "0", color=Theme.STAT_TEL)
        self.card_telefon.pack(side="left", fill="x", expand=True, padx=4)

        self.card_seri_no = GlassStatCard(stats_frame_row1, "🪪 Kimlik Seri No", "0", color=Theme.STAT_SERI)
        self.card_seri_no.pack(side="left", fill="x", expand=True, padx=4)

        self.card_mrz = GlassStatCard(stats_frame_row1, "📑 Kimlik MRZ Kodu", "0", color=Theme.STAT_MRZ)
        self.card_mrz.pack(side="left", fill="x", expand=True, padx=(4, 0))

        stats_frame_row2 = tk.Frame(main_frame, bg=Theme.BG_CANVAS)
        stats_frame_row2.pack(fill="x", pady=(0, 8))

        self.card_iban = GlassStatCard(stats_frame_row2, "💳 IBAN Gizlenen", "0", color=Theme.STAT_IBAN)
        self.card_iban.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.card_sicil = GlassStatCard(stats_frame_row2, "⚖️ Sicil No Gizlenen", "0", color=Theme.STAT_SICIL)
        self.card_sicil.pack(side="left", fill="x", expand=True, padx=4)

        self.card_adres = GlassStatCard(stats_frame_row2, "📍 Adres Gizlenen", "0", color=Theme.STAT_ADRES)
        self.card_adres.pack(side="left", fill="x", expand=True, padx=4)

        self.card_files = GlassStatCard(stats_frame_row2, "📄 Aktarılan / OCR", "0", color=Theme.STAT_FILES)
        self.card_files.pack(side="left", fill="x", expand=True, padx=(4, 0))

        # ----------------------------------------------------------------------
        # 5. İŞLEM BUTONLARI VE DURUM HAPI
        # ----------------------------------------------------------------------
        action_frame = tk.Frame(main_frame, bg=Theme.BG_CANVAS)
        action_frame.pack(fill="x", pady=(0, 8))

        # 🚀 Ana Çalıştırma Butonu (Apple Blue Primary)
        self.btn_run = GlassButton(
            action_frame,
            text="🚀  İzole Temiz Klasör Üret",
            variant="primary",
            command=self._start_process,
            padx=18,
            pady=8
        )
        self.btn_run.pack(side="left", padx=(0, 8))

        # 📂 Klasörü Aç Butonu
        self.btn_open_folder = GlassButton(
            action_frame,
            text="📂  Klasörü Aç (Finder)",
            variant="secondary",
            command=self._open_dest_folder,
            state="disabled",
            padx=14,
            pady=8
        )
        self.btn_open_folder.pack(side="left", padx=(0, 10))

        # Parlayan Durum Hapı (Glowing Status Pill)
        self.lbl_status = GlassStatusPill(
            action_frame,
            text="Hazır. Dava klasörünü seçip 'İzole Temiz Klasör Üret' butonuna tıklayın."
        )
        self.lbl_status.pack(side="left", fill="x", expand=True)

        # ----------------------------------------------------------------------
        # İLERLEME ÇUBUĞU (LIQUID GLASS PROGRESS BAR)
        # ----------------------------------------------------------------------
        self.progress = GlassProgressBar(main_frame, height=12, bg=Theme.BG_CANVAS)
        self.progress.pack(fill="x", pady=(0, 8))

        # ----------------------------------------------------------------------
        # 6. GELİŞTİRİCİ KONSOLU / İŞLEM KAYITLARI (APPLE DARK TERMINAL)
        # ----------------------------------------------------------------------
        log_panel = tk.Frame(
            main_frame,
            bg=Theme.TERM_BG,
            highlightbackground=Theme.TERM_BORDER,
            highlightthickness=1
        )
        log_panel.pack(fill="both", expand=True)

        # Konsol Üst Barı (macOS Trafik Işıkları & Başlık)
        log_header = tk.Frame(log_panel, bg=Theme.TERM_BAR, padx=10, pady=6)
        log_header.pack(fill="x")

        # 3 macOS Pencere Noktası
        dots_frame = tk.Frame(log_header, bg=Theme.TERM_BAR)
        dots_frame.pack(side="left")

        for dot_color in ["#FF5F56", "#FFBD2E", "#27C93F"]:
            d = tk.Label(dots_frame, text="●", font=Theme.font_text(7, "bold"), fg=dot_color, bg=Theme.TERM_BAR)
            d.pack(side="left", padx=(0, 4))

        tk.Label(
            log_header,
            text="Console Output  •  Canlı İşlem Günlüğü",
            font=Theme.font_mono(9, "bold"),
            fg=Theme.TEXT_MUTED,
            bg=Theme.TERM_BAR
        ).pack(side="left", padx=(6, 0))

        btn_clear = GlassButton(
            log_header,
            text="Kayıtları Temizle",
            variant="subtle",
            command=self._clear_logs,
            padx=10,
            pady=3
        )
        btn_clear.pack(side="right")

        # Monospace Terminal Metin Alanı
        self.log_text = ScrolledText(
            log_panel,
            font=Theme.font_mono(10, "normal"),
            bg=Theme.TERM_BG,
            fg=Theme.TERM_FG,
            relief="flat",
            wrap="none",
            bd=0,
            padx=12,
            pady=8,
            insertbackground="#FFFFFF"
        )
        self.log_text.pack(fill="both", expand=True)

        # Syntax Renk Tanımları
        self.log_text.tag_configure("mask", foreground="#34D399")      # Emerald 400 (Maskelenen veriler)
        self.log_text.tag_configure("ocr", foreground="#A78BFA")       # Violet 400 (Apple Vision OCR)
        self.log_text.tag_configure("sync", foreground="#38BDF8")      # Sky 400 (İndeks Senkron)
        self.log_text.tag_configure("error", foreground="#F87171")     # Rose 400 (Hata mesajları)
        self.log_text.tag_configure("header", foreground="#FCD34D", font=Theme.font_mono(10, "bold"))  # Amber
        self.log_text.tag_configure("info", foreground="#94A3B8")      # Slate 400
        self.log_text.tag_configure("dim", foreground="#52525B")       # Zinc 600

        # ----------------------------------------------------------------------
        # 7. ALT BİLGİ BARI (MINIMALIST FOOTER)
        # ----------------------------------------------------------------------
        bottom_frame = tk.Frame(
            self,
            bg=Theme.BG_SURFACE,
            padx=20,
            pady=7,
            highlightbackground=Theme.BORDER_GLASS,
            highlightthickness=1
        )
        bottom_frame.pack(fill="x", side="bottom")

        lbl_shortcuts = tk.Label(
            bottom_frame,
            text="⌘O Klasör Seç  •  ⌘R Başlat  •  ⌘K Temizle",
            font=Theme.font_text(9, "normal"),
            fg=Theme.TEXT_MUTED,
            bg=Theme.BG_SURFACE
        )
        lbl_shortcuts.pack(side="left")

        lbl_secure = tk.Label(
            bottom_frame,
            text="🔒 %100 Yerel ve Çevrimdışı (Zero-Cloud / Neural Engine) • Ağ bağlantısı gerektirmez.",
            font=Theme.font_text(9, "italic"),
            fg=Theme.TEXT_MUTED,
            bg=Theme.BG_SURFACE
        )
        lbl_secure.pack(side="right")

    # ==========================================================================
    # İŞLEVSEL METOTLAR
    # ==========================================================================

    def _select_folder(self):
        folder = filedialog.askdirectory(title="UYAP Dava Klasörünü Seçin")
        if folder:
            self.folder_var.set(folder)
            self._log(f"📁 Kaynak klasör seçildi: {folder}\n")
            self.lbl_status.config(text=f"Klasör hazır: {os.path.basename(folder)}")

    def _open_dest_folder(self):
        if self.last_dest_folder and os.path.exists(self.last_dest_folder):
            subprocess.run(["open", self.last_dest_folder])
        else:
            messagebox.showinfo("Bilgi", "Oluşturulmuş izole temiz klasör bulunamadı.")

    def _log(self, text):
        tag = None
        if "[MASKE]" in text:
            tag = "mask"
        elif "OCR" in text:
            tag = "ocr"
        elif "SENKRON" in text:
            tag = "sync"
        elif "[HATA]" in text or "Hata" in text:
            tag = "error"
        elif "===" in text or "BAŞLATILDI" in text or "Hedef Klasör" in text:
            tag = "header"
        elif "📁" in text or "Klasör" in text:
            tag = "info"

        if tag:
            self.log_text.insert(tk.END, text, tag)
        else:
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
                    self.btn_run.config(state="normal", text="🚀  İzole Temiz Klasör Üret")
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
                    self.btn_run.config(state="normal", text="🚀  İzole Temiz Klasör Üret")
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
            f"\n{'='*64}\n"
            f"BAŞLATILDI: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Kaynak Dava Klasörü: {folder}\n"
            f"İşlem Modu: İzole Temiz Klasör Üret (AI Export)\n"
            f"{'='*64}\n"
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
            self.msg_queue.put(("log", f"\n{'='*64}\n{summary_msg}\n{'='*64}\n"))
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
