#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UYAP Maskeleme — macOS Desktop GUI Otomasyon Test Paketi
gui.py ve bundle/launcher.sh bileşenlerinin kapsamlı UI/UX ve işlevsel testleri.
"""

import os
import sys
import unittest
import queue
import time
import subprocess
from unittest.mock import MagicMock, patch

# Testlerde açılan uygulamalar (alt süreçler dahil) GitHub güncelleme sorgusu yapmasın
os.environ["UYAP_DISABLE_UPDATE_CHECK"] = "1"

# Çalışma dizini ayarları
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

import tkinter as tk
from tkinter import messagebox, filedialog
import gui
from gui import (
    Theme,
    GlassPillBadge,
    GlassButton,
    GlassStatCard,
    ModernCard,
    GlassStatusPill,
    GlassProgressBar,
    UyapRedactorApp
)


class TestLauncherScript(unittest.TestCase):
    """bundle/launcher.sh başlatıcı betiğinin doğrulama testleri."""

    def setUp(self):
        self.launcher_path = os.path.join(CURRENT_DIR, "bundle", "launcher.sh")

    def test_launcher_exists_and_executable(self):
        """launcher.sh mevcut ve çalıştırılabilir (+x) iznine sahip mi?"""
        self.assertTrue(os.path.exists(self.launcher_path), f"launcher.sh bulunamadı: {self.launcher_path}")
        self.assertTrue(os.access(self.launcher_path, os.X_OK), "launcher.sh çalıştırılabilir izne (+x) sahip değil!")

    def test_launcher_syntax(self):
        """launcher.sh bash sözdizimi doğrulaması (bash -n)."""
        res = subprocess.run(["bash", "-n", self.launcher_path], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"launcher.sh sözdizimi hatası içeriyor: {res.stderr}")

    def test_launcher_shebang_and_encoding(self):
        """launcher.sh shebang, UTF-8 ayarları ve aday Python yollarını içeriyor mu?"""
        with open(self.launcher_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertTrue(content.startswith("#!/bin/bash"), "Shebang '#!/bin/bash' ile başlamalı")
        self.assertIn('export LC_ALL="en_US.UTF-8"', content)
        self.assertIn('export LANG="en_US.UTF-8"', content)
        self.assertIn('export PYTHONIOENCODING="utf-8"', content)
        self.assertIn("/opt/homebrew/bin/python3", content)
        self.assertIn("import tkinter", content)
        self.assertIn("gui.py", content)

    def test_launcher_python_detection_logic(self):
        """Aktif sistem Python'unun tkinter ile uyumlu olduğunu simüle etme."""
        res = subprocess.run([sys.executable, "-c", "import tkinter; print('OK')"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout.strip(), "OK")


class TestTheme(unittest.TestCase):
    """Apple HIG ve Shadcn Zinc tema tanımları testi."""

    def test_theme_colors_format(self):
        """Tema renk kodlarının geçerli HEX formatında olduğunu doğrula."""
        colors = [
            Theme.BG_CANVAS, Theme.BG_SURFACE, Theme.BG_SURFACE_ALT,
            Theme.BORDER_GLASS, Theme.BORDER_HOVER, Theme.BORDER_SHINE,
            Theme.TEXT_PRIMARY, Theme.TEXT_SECONDARY, Theme.TEXT_MUTED, Theme.TEXT_TERTIARY,
            Theme.BLUE_PRIMARY, Theme.BLUE_HOVER, Theme.BLUE_PRESS,
            Theme.STAT_TCKN, Theme.STAT_TEL, Theme.STAT_SERI, Theme.STAT_MRZ,
            Theme.STAT_IBAN, Theme.STAT_SICIL, Theme.STAT_ADRES, Theme.STAT_FILES,
            Theme.TERM_BG, Theme.TERM_BAR, Theme.TERM_BORDER, Theme.TERM_FG, Theme.TERM_LINE
        ]
        for c in colors:
            self.assertTrue(c.startswith("#"), f"Geçersiz renk kodu: {c}")
            self.assertIn(len(c), (4, 7, 9), f"Geçersiz renk uzunluğu: {c}")

    def test_theme_fonts(self):
        """Apple HIG SF Pro ve SF Mono font hiyerarşisi doğrulaması."""
        display = Theme.font_display(18, "bold")
        self.assertEqual(display, ("SF Pro Display", 18, "bold"))

        text_font = Theme.font_text(11, "normal")
        self.assertEqual(text_font, ("SF Pro Text", 11, "normal"))

        mono = Theme.font_mono(10, "normal")
        self.assertEqual(mono, ("SF Mono", 10, "normal"))


class TestGlassPillBadge(unittest.TestCase):
    """Shadcn minimalist hap rozet (GlassPillBadge) testleri."""

    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_badge_creation(self):
        badge = GlassPillBadge(
            self.root,
            text="Çevrimdışı",
            dot_color="#10B981",
            bg="#F0FDF4",
            border="#DCFCE7",
            fg="#15803D"
        )
        self.assertEqual(badge.lbl_text.cget("text"), "Çevrimdışı")
        self.assertEqual(badge.lbl_dot.cget("text"), "●")
        self.assertEqual(badge.lbl_dot.cget("fg"), "#10B981")
        self.assertEqual(badge.cget("bg"), "#F0FDF4")
        badge.destroy()


class TestGlassButton(unittest.TestCase):
    """Liquid Glass Etkileşimli Buton (GlassButton) testleri."""

    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_button_variants(self):
        """Primary, secondary ve subtle varyantlarının renk ve font tanımları."""
        btn_prim = GlassButton(self.root, text="Kaydet", variant="primary")
        self.assertEqual(btn_prim.bg_normal, Theme.BLUE_PRIMARY)
        self.assertEqual(btn_prim.fg_normal, "#FFFFFF")

        btn_sec = GlassButton(self.root, text="İptal", variant="secondary")
        self.assertEqual(btn_sec.bg_normal, "#FFFFFF")
        self.assertEqual(btn_sec.fg_normal, Theme.BLUE_PRIMARY)

        btn_subtle = GlassButton(self.root, text="Temizle", variant="subtle")
        self.assertEqual(btn_subtle.bg_normal, "#27272A")
        self.assertEqual(btn_subtle.fg_normal, "#F4F4F5")

        btn_prim.destroy()
        btn_sec.destroy()
        btn_subtle.destroy()

    def test_button_command_execution(self):
        """Tıklandığında ve buton alanında bırakıldığında komut çalıştırma testi."""
        mock_cmd = MagicMock()
        btn = GlassButton(self.root, text="Test", command=mock_cmd, variant="primary")
        btn.pack()
        self.root.update()

        # Sahte event oluştur
        event_press = MagicMock(x=10, y=10)
        btn._on_press(event_press)
        self.assertTrue(btn._is_pressed)
        self.assertEqual(btn.cget("bg"), btn.bg_press)

        # Alan içinde bırakma
        event_release = MagicMock(x=10, y=10)
        btn._on_release(event_release)
        self.assertFalse(btn._is_pressed)
        mock_cmd.assert_called_once()

        # Alan dışında bırakma durumunda komut çalıştırılmamalı
        mock_cmd.reset_mock()
        btn._on_press(event_press)
        # Koordinat buton sınırları dışında (negatif veya genişlikten büyük)
        event_outside = MagicMock(x=-10, y=-10)
        btn._on_release(event_outside)
        mock_cmd.assert_not_called()

        btn.destroy()

    def test_button_hover_events(self):
        """Hover ve press olaylarının görsel stilleri."""
        btn = GlassButton(self.root, text="Hover Test", variant="primary")
        btn.pack()
        self.root.update()

        # _on_enter
        btn._on_enter(None)
        self.assertEqual(btn.cget("bg"), btn.bg_hover)

        # _on_leave
        btn._on_leave(None)
        self.assertEqual(btn.cget("bg"), btn.bg_normal)

        btn.destroy()

    def test_button_state_disabled_and_normal(self):
        """State disabled ve normal geçişleri."""
        mock_cmd = MagicMock()
        btn = GlassButton(self.root, text="Durum", command=mock_cmd, state="normal")
        btn.pack()
        self.root.update()

        # Disabled yapma
        btn.config(state="disabled")
        self.assertEqual(btn.state, "disabled")
        self.assertEqual(btn.cget("bg"), btn.bg_disabled)
        self.assertEqual(btn.label.cget("cursor"), "arrow")

        # Disabled iken tıklanırsa komut çalışmamalı
        event = MagicMock(x=10, y=10)
        btn._on_press(event)
        self.assertFalse(btn._is_pressed)
        btn._on_release(event)
        mock_cmd.assert_not_called()

        # Normal'e döndürme
        btn.config(state="normal")
        self.assertEqual(btn.state, "normal")
        self.assertEqual(btn.cget("bg"), btn.bg_normal)
        self.assertEqual(btn.label.cget("cursor"), "pointinghand")

        btn.destroy()

    def test_button_item_access(self):
        """btn['state'] ve btn['text'] erişim protokolü."""
        btn = GlassButton(self.root, text="Başlangıç")
        self.assertEqual(btn["text"], "Başlangıç")
        self.assertEqual(btn["state"], "normal")

        btn["text"] = "Güncellendi"
        btn["state"] = "disabled"
        self.assertEqual(btn["text"], "Güncellendi")
        self.assertEqual(btn["state"], "disabled")
        btn.destroy()


class TestGlassStatusPill(unittest.TestCase):
    """Parlayan Cam Durum Göstergesi (GlassStatusPill) testleri."""

    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_initial_state(self):
        pill = GlassStatusPill(self.root, text="Hazır.")
        self.assertEqual(pill.lbl_text.cget("text"), "Hazır.")
        self.assertEqual(pill.lbl_dot.cget("fg"), "#10B981")  # Yeşil
        self.assertFalse(pill.is_pulsing)
        pill.destroy()

    def test_text_auto_detection_pulsing(self):
        """İşleniyor/OCR/Senkron kelimelerinde otomatik pulse başlatma."""
        pill = GlassStatusPill(self.root, text="Bekleniyor")
        pill.config(text="Metin Maskeleniyor (1/10)...")
        self.assertTrue(pill.is_pulsing)

        pill.config(text="Yerel Apple Vision OCR Yapılıyor...")
        self.assertTrue(pill.is_pulsing)

        pill.config(text="İndeks Senkronizasyonu Sürüyor...")
        self.assertTrue(pill.is_pulsing)

        pill.stop_pulse()
        pill.destroy()

    def test_text_auto_detection_error(self):
        """Hata kelimelerinde kırmızı nokta ve pulse durdurma."""
        pill = GlassStatusPill(self.root)
        pill.start_pulse()
        self.assertTrue(pill.is_pulsing)

        pill.config(text="Hata Oluştu: Dosya bulunamadı")
        self.assertFalse(pill.is_pulsing)
        self.assertEqual(pill.lbl_dot.cget("fg"), "#EF4444")  # Kırmızı
        pill.destroy()

    def test_text_auto_detection_success(self):
        """Tamamlandı kelimelerinde yeşil nokta ve pulse durdurma."""
        pill = GlassStatusPill(self.root)
        pill.start_pulse()
        self.assertTrue(pill.is_pulsing)

        pill.config(text="İşlem başarıyla tamamlandı.")
        self.assertFalse(pill.is_pulsing)
        self.assertEqual(pill.lbl_dot.cget("fg"), "#10B981")  # Yeşil
        pill.destroy()

    def test_pulse_loop_colors(self):
        """Pulse döngüsü renk geçişi."""
        pill = GlassStatusPill(self.root)
        pill.is_pulsing = True
        init_idx = pill.pulse_index
        pill._pulse_loop()
        self.assertNotEqual(pill.pulse_index, init_idx)
        pill.stop_pulse()
        pill.destroy()


class TestGlassProgressBar(unittest.TestCase):
    """Liquid Glass Canvas İlerleme Çubuğu (GlassProgressBar) testleri."""

    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_progress_set_and_get(self):
        bar = GlassProgressBar(self.root, height=12)
        bar.pack()
        self.root.update()

        bar["maximum"] = 150
        bar["value"] = 75
        self.assertEqual(bar["maximum"], 150)
        self.assertEqual(bar["value"], 75)

        with self.assertRaises(KeyError):
            _ = bar["invalid_key"]

        bar.destroy()

    def test_clamping_and_redraw(self):
        """0'dan küçük değerleri ve aşırı değerleri kırpma."""
        bar = GlassProgressBar(self.root, height=12, width=200)
        bar.pack(fill="x")
        self.root.update()

        # Negatif değer verilirse 0'a kırpar
        bar["value"] = -10
        self.assertEqual(bar["value"], 0)

        # 0 maksimum sıfıra bölme hatası vermemeli
        bar["maximum"] = 0
        self.assertEqual(bar["maximum"], 1)

        # Canvas öğelerinin çizildiğini doğrula
        bar["value"] = 50
        bar._redraw()
        items = bar.find_all()
        self.assertGreater(len(items), 0, "Canvas üzerine çizim yapılmadı!")

        bar.destroy()


class TestGlassStatCard(unittest.TestCase):
    """Liquid Glass İstatistik Kartı (GlassStatCard) testleri."""

    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_card_initial_and_update(self):
        card = GlassStatCard(self.root, title="TCKN Gizlenen", value="0", color=Theme.STAT_TCKN)
        card.pack()
        self.root.update()

        self.assertEqual(card.lbl_title.cget("text"), "TCKN Gizlenen")
        self.assertEqual(card.lbl_val.cget("text"), "0")
        self.assertEqual(card.lbl_val.cget("fg"), Theme.STAT_TCKN)

        card.update_value(14)
        self.assertEqual(card.lbl_val.cget("text"), "14")

        card.update_value("12 (3 OCR)")
        self.assertEqual(card.lbl_val.cget("text"), "12 (3 OCR)")

        card.destroy()

    def test_card_hover_events(self):
        card = GlassStatCard(self.root, title="Test", value="0")
        card._on_enter(None)
        self.assertEqual(card.cget("highlightbackground"), Theme.BORDER_HOVER)

        card._on_leave(None)
        self.assertEqual(card.cget("highlightbackground"), Theme.BORDER_GLASS)
        card.destroy()

    def test_card_backward_compatibility_alias(self):
        """ModernCard takma adının GlassStatCard olduğunu doğrula."""
        self.assertIs(ModernCard, GlassStatCard)


class TestUyapRedactorApp(unittest.TestCase):
    """UyapRedactorApp ana pencere, bileşenler ve entegrasyon testleri."""

    def setUp(self):
        # messagebox ve filedialog'u mockla ki test sırasında bloklayıcı pencere açılmasın
        self.patch_msg_info = patch.object(messagebox, "showinfo")
        self.patch_msg_warn = patch.object(messagebox, "showwarning")
        self.patch_msg_err = patch.object(messagebox, "showerror")
        self.patch_msg_yesno = patch.object(messagebox, "askyesno", return_value=False)
        self.patch_filedialog = patch.object(filedialog, "askdirectory", return_value="/tmp/test_uyap_case")
        self.patch_subproc = patch.object(subprocess, "run")

        self.mock_info = self.patch_msg_info.start()
        self.mock_warn = self.patch_msg_warn.start()
        self.mock_err = self.patch_msg_err.start()
        self.mock_yesno = self.patch_msg_yesno.start()
        self.mock_filedialog = self.patch_filedialog.start()
        self.mock_subproc = self.patch_subproc.start()

        self.app = UyapRedactorApp()
        self.app.update()
        self.app.withdraw()  # Test sırasında ekranı kirletmemek için gizle

    def tearDown(self):
        self.app.destroy()
        self.patch_msg_info.stop()
        self.patch_msg_warn.stop()
        self.patch_msg_err.stop()
        self.patch_msg_yesno.stop()
        self.patch_filedialog.stop()
        self.patch_subproc.stop()

    def test_window_geometry_and_properties(self):
        """Pencere geometrisi (760x560), minsize (400x440) ve arka plan (#F4F4F6) doğrulaması."""
        self.assertEqual(self.app.cget("bg"), Theme.BG_CANVAS)
        self.assertIn("760", self.app.geometry())
        self.assertIn("560", self.app.geometry())
        min_w, min_h = self.app.minsize()
        self.assertEqual(min_w, 400)
        self.assertEqual(min_h, 440)
        self.assertIn("UYAP Kişisel Veri Maskeleme", self.app.title())

    def test_responsive_layout_switches_between_wide_and_narrow(self):
        """Pencere daraltılınca dar düzene, genişletilince geniş düzene geçiş ve taşma olmaması."""
        # Gizli pencerede boyut (<Configure>) olayları üretilmez; bu test için göster
        self.app.deiconify()

        def resize(w, h):
            self.app.geometry(f"{w}x{h}")
            for _ in range(10):
                self.app.update()
                time.sleep(0.02)

        resize(760, 560)
        self.assertEqual(self.app._layout_mode, "wide", f"genişlik={self.app.winfo_width()} geo={self.app.geometry()}")
        self.assertEqual(int(self.app.btn_run.grid_info()["row"]), 0)
        self.assertEqual(int(self.app.card_files.grid_info()["column"]), 7)

        resize(420, 500)
        self.assertEqual(self.app._layout_mode, "narrow")
        # Başlat ikinci satıra iner, kartlar 4x2 ızgaraya geçer
        self.assertEqual(int(self.app.btn_run.grid_info()["row"]), 1)
        self.assertEqual(int(self.app.card_files.grid_info()["row"]), 1)
        self.assertEqual(int(self.app.card_files.grid_info()["column"]), 3)
        self.assertFalse(self.app.lbl_subtitle.winfo_ismapped())
        # Hiçbir ana öğe pencerenin sağ kenarından taşmamalı
        win_right = self.app.winfo_rootx() + self.app.winfo_width()
        for w in (self.app.btn_browse, self.app.btn_open_folder, self.app.card_mrz,
                  self.app.card_files, self.app.btn_clear, self.app.btn_update):
            self.assertLessEqual(w.winfo_rootx() + w.winfo_width(), win_right + 1)

        resize(760, 560)
        self.assertEqual(self.app._layout_mode, "wide")
        self.assertTrue(self.app.lbl_subtitle.winfo_ismapped())

    def test_all_components_instantiated(self):
        """Tüm stat kartlarının, butonların, durum göstergesi ve konsolun varlığı."""
        # 8 adet stat kartı
        self.assertIsInstance(self.app.card_tckn, GlassStatCard)
        self.assertIsInstance(self.app.card_telefon, GlassStatCard)
        self.assertIsInstance(self.app.card_seri_no, GlassStatCard)
        self.assertIsInstance(self.app.card_mrz, GlassStatCard)
        self.assertIsInstance(self.app.card_iban, GlassStatCard)
        self.assertIsInstance(self.app.card_sicil, GlassStatCard)
        self.assertIsInstance(self.app.card_adres, GlassStatCard)
        self.assertIsInstance(self.app.card_files, GlassStatCard)

        # Butonlar
        self.assertIsInstance(self.app.btn_run, GlassButton)
        self.assertIsInstance(self.app.btn_open_folder, GlassButton)
        self.assertEqual(self.app.btn_open_folder.state, "disabled")

        # Durum ve İlerleme
        self.assertIsInstance(self.app.lbl_status, GlassStatusPill)
        self.assertIsInstance(self.app.progress, GlassProgressBar)

        # Konsol ve Konsol Butonları
        self.assertTrue(hasattr(self.app, "log_text"))
        self.assertIsInstance(self.app.btn_clear, GlassButton)
        self.assertEqual(self.app.btn_clear["text"], "Temizle")
        self.assertIn("İşlem Günlüğü", self.app.lbl_console_title.cget("text"))

    def test_keyboard_shortcuts_bound(self):
        """macOS Klavye Kısayolları bağlamalarının (bind) varlığı."""
        bound_keys = self.app.bind()
        # macOS Tkinter ortamında <Command-Key-...> Tk dahili tablosunda <Mod1-Key-...> veya <Command-...> olarak tutulur.
        for k in ["o", "r", "k", "q", "w"]:
            has_cmd = any((("command" in b.lower()) or ("mod1" in b.lower())) and k in b.lower() for b in bound_keys)
            self.assertTrue(has_cmd, f"<{k}> için Command/Mod1 kısayolu bulunamadı! Aktif: {bound_keys}")

    def test_keyboard_shortcut_triggers(self):
        """Kısayolların olay üretimiyle (event_generate) hedef fonksiyonları tetiklemesi."""
        # 1. Command-o -> _select_folder
        with patch.object(self.app, "_select_folder") as mock_sel:
            self.app.event_generate("<Command-o>")
            mock_sel.assert_called_once()

        # 2. Command-k -> _clear_logs
        with patch.object(self.app, "_clear_logs") as mock_clear:
            self.app.event_generate("<Command-k>")
            mock_clear.assert_called_once()

        # 3. Command-r -> _start_process (is_running = False iken)
        self.app.is_running = False
        with patch.object(self.app, "_start_process") as mock_run:
            self.app.event_generate("<Command-r>")
            mock_run.assert_called_once()

        # 4. Command-r -> is_running = True iken engellenmeli
        self.app.is_running = True
        with patch.object(self.app, "_start_process") as mock_run_blocked:
            self.app.event_generate("<Command-r>")
            mock_run_blocked.assert_not_called()

        # 5. Command-q ve Command-w -> _on_close çağrılmalı
        with patch.object(self.app, "_on_close") as mock_close:
            self.app.event_generate("<Command-q>")
            mock_close.assert_called_once()

        with patch.object(self.app, "_on_close") as mock_close_w:
            self.app.event_generate("<Command-w>")
            mock_close_w.assert_called_once()

    def test_start_process_reentrancy_and_path_expansion(self):
        """_start_process reentrancy koruması ve '~' tilde yol genişletme testi."""
        # 1. is_running = True iken doğrudan _start_process çağrısı engellenmeli
        self.app.is_running = True
        self.app.folder_var.set("/tmp")
        with patch("threading.Thread") as mock_th:
            self.app._start_process()
            mock_th.assert_not_called()

        # 2. '~' ile başlayan geçerli yolun expanduser ile genişletilmesi
        self.app.is_running = False
        fake_home = os.path.expanduser("~")
        self.app.folder_var.set("~/")
        with patch.object(gui.UyapRedactor, "export_isolated_clean_folder") as mock_exp:
            with patch("threading.Thread") as mock_th:
                self.app._start_process()
                self.assertTrue(self.app.folder_var.get().startswith(fake_home))

    def test_console_logging_and_tags(self):
        """Konsol loglama ve syntax etiketleri (mask, ocr, sync, error, header, info)."""
        self.app._clear_logs()
        self.assertEqual(self.app.log_text.get("1.0", tk.END).strip(), "")

        # Maske logu
        self.app._log("🔒 [MASKE] Dosya: test.udf.md -> TCKN: 2\n")
        # OCR logu
        self.app._log("👁️ [YEREL OCR & MASKE] Ek: fotokopi.pdf\n")
        # Senkron logu
        self.app._log("🔄 [İNDEKS SENKRON] INDEX.md güncellendi\n")
        # Hata logu
        self.app._log("⚠️ [HATA] Bir dosya okunamadı\n")
        # Header logu
        self.app._log("=== BAŞLATILDI ===\n")
        # Info logu
        self.app._log("📁 Kaynak Klasör Seçildi\n")
        # Normal log
        self.app._log("Normal metin satırı\n")

        content = self.app.log_text.get("1.0", tk.END)
        self.assertIn("[MASKE]", content)
        self.assertIn("OCR", content)
        self.assertIn("SENKRON", content)
        self.assertIn("[HATA]", content)
        self.assertIn("BAŞLATILDI", content)

        # Temizleme
        self.app._clear_logs()
        self.assertEqual(self.app.log_text.get("1.0", tk.END).strip(), "")

    def test_btn_browse_action(self):
        """btn_browse tıklandığında klasör seçiminin yapılması ve arayüze yansıması."""
        self.app._select_folder()
        self.mock_filedialog.assert_called_once()
        self.assertEqual(self.app.folder_var.get(), "/tmp/test_uyap_case")
        self.assertIn("test_uyap_case", self.app.lbl_status.lbl_text.cget("text"))
        self.assertIn("Kaynak klasör seçildi", self.app.log_text.get("1.0", tk.END))

    def test_btn_open_folder_when_none(self):
        """Henüz izole klasör oluşturulmamışken Klasörü Aç butonu info mesajı göstermeli."""
        self.app.last_dest_folder = None
        self.app._open_dest_folder()
        self.mock_info.assert_called_once_with("Bilgi", "Oluşturulmuş izole temiz klasör bulunamadı.")
        self.mock_subproc.assert_not_called()

    def test_btn_open_folder_when_exists(self):
        """İzole klasör mevcutken Klasörü Aç butonu Finder 'open' komutunu çalıştırmalı."""
        with patch("os.path.exists", return_value=True):
            self.app.last_dest_folder = "/tmp/test_case (Maskelenmis AI)"
            self.app._open_dest_folder()
            self.mock_subproc.assert_called_once_with(["open", "/tmp/test_case (Maskelenmis AI)"])

    def test_btn_run_empty_folder_warning(self):
        """Klasör seçilmeden Başlat'a basıldığında uyarı çıkmalı ve işlem başlamamalı."""
        self.app.folder_var.set("")
        self.app._start_process()
        self.mock_warn.assert_called_once()
        self.assertFalse(self.app.is_running)

    def test_queue_synchronization_flow(self):
        """Thread kuyruğuna gelen tüm mesaj tiplerinin (log, status, progress, stats, done, error) GUI'ye yansıması."""
        # 1. log mesajı
        self.app.msg_queue.put(("log", "Sistem testi logu\n"))
        self.app._check_queue()
        self.assertIn("Sistem testi logu", self.app.log_text.get("1.0", tk.END))

        # 2. status mesajı
        self.app.msg_queue.put(("status", "İşlem yapılıyor..."))
        self.app._check_queue()
        self.assertEqual(self.app.lbl_status.lbl_text.cget("text"), "İşlem yapılıyor...")

        # 3. progress mesajı
        self.app.msg_queue.put(("progress", (45, 100)))
        self.app._check_queue()
        self.assertEqual(self.app.progress["value"], 45)
        self.assertEqual(self.app.progress["maximum"], 100)

        # 4. stats mesajı
        mock_stats = {
            "tckn": 8,
            "telefon": 3,
            "seri_no": 1,
            "mrz": 2,
            "iban": 4,
            "sicil": 6,
            "adres": 11,
            "md_transferred": 15,
            "ocr_converted": 5
        }
        self.app.msg_queue.put(("stats", mock_stats))
        self.app._check_queue()

        self.assertEqual(self.app.card_tckn.lbl_val.cget("text"), "8")
        self.assertEqual(self.app.card_telefon.lbl_val.cget("text"), "3")
        self.assertEqual(self.app.card_seri_no.lbl_val.cget("text"), "1")
        self.assertEqual(self.app.card_mrz.lbl_val.cget("text"), "2")
        self.assertEqual(self.app.card_iban.lbl_val.cget("text"), "4")
        self.assertEqual(self.app.card_sicil.lbl_val.cget("text"), "6")
        self.assertEqual(self.app.card_adres.lbl_val.cget("text"), "11")
        self.assertEqual(self.app.card_files.lbl_val.cget("text"), "15 (5 OCR)")

        # 5. done mesajı
        self.app.is_running = True
        self.app.btn_run.config(state="disabled", text="İşleniyor...")
        self.app.msg_queue.put(("done", ("İşlem Başarılı!", "/tmp/fake_dest")))
        self.app._check_queue()
        self.assertFalse(self.app.is_running)
        self.assertEqual(self.app.btn_run.state, "normal")
        self.assertEqual(self.app.btn_run.label.cget("text"), gui.RUN_BUTTON_TEXT)
        self.assertEqual(self.app.btn_open_folder.state, "normal")
        self.mock_yesno.assert_called_once()

        # 6. error mesajı
        self.app.is_running = True
        self.app.btn_run.config(state="disabled")
        self.app.msg_queue.put(("error", "Simüle edilen hata mesajı"))
        self.app._check_queue()
        self.assertFalse(self.app.is_running)
        self.assertEqual(self.app.btn_run.state, "normal")
        self.mock_err.assert_called_once_with("Hata Oluştu", "Simüle edilen hata mesajı")

    def test_worker_flow_success(self):
        """Worker thread metodunun UyapRedactor.export_isolated_clean_folder çağrısı ve callback akışı."""
        with patch.object(gui.UyapRedactor, "export_isolated_clean_folder") as mock_export:
            mock_export.return_value = (
                "/tmp/dava (Maskelenmis AI)",
                {"md_transferred": 10, "ocr_converted": 2, "index_synced": 12, "total": 20, "tckn": 5}
            )

            # Doğrudan _worker metodunu senkron çağırarak kuyruğu doldur
            self.app._worker("/tmp/dava")

            # Kuyrukta en azından status, log, progress, stats, done mesajlarının olduğunu denetle
            messages = []
            while not self.app.msg_queue.empty():
                messages.append(self.app.msg_queue.get_nowait())

            msg_types = [m[0] for m in messages]
            self.assertIn("status", msg_types)
            self.assertIn("log", msg_types)
            self.assertIn("progress", msg_types)
            self.assertIn("stats", msg_types)
            self.assertIn("done", msg_types)

            self.assertEqual(self.app.last_dest_folder, "/tmp/dava (Maskelenmis AI)")

    def test_worker_flow_exception_handling(self):
        """Worker thread içerisinde hata oluştuğunda kuyruğa 'error' ve 'log' mesajı düşmesi."""
        with patch.object(gui.UyapRedactor, "export_isolated_clean_folder", side_effect=RuntimeError("Disk dolu!")):
            self.app._worker("/tmp/dava")

            messages = []
            while not self.app.msg_queue.empty():
                messages.append(self.app.msg_queue.get_nowait())

            msg_types = [m[0] for m in messages]
            self.assertIn("error", msg_types)
            self.assertIn("log", msg_types)

            err_msg = [m[1] for m in messages if m[0] == "error"][0]
            self.assertIn("Disk dolu!", err_msg)

    def test_update_queue_messages(self):
        """Otomatik güncelleme kuyruk mesajlarının (update_available, update_up_to_date) işlenmesi."""
        fake_info = {
            "version": "2.0.0",
            "tag_name": "v2.0.0",
            "download_url": "https://github.com/MertAtis/Uyap-Dosya-Maskeleme-YPro/releases/download/v2.0.0/UYAP-Maskeleme.dmg",
            "size": 25000000,
            "release_notes": "Yeni kurallar eklendi.",
            "html_url": "https://github.com/MertAtis/Uyap-Dosya-Maskeleme-YPro/releases/tag/v2.0.0",
        }
        self.app.msg_queue.put(("update_available", (fake_info, False)))
        self.app._check_queue()
        self.assertEqual(self.app.pending_update_info, fake_info)
        self.assertIn("v2.0.0", self.app.btn_update["text"])
        self.mock_yesno.assert_called_once()


class TestAutoUpdater(unittest.TestCase):
    """AutoUpdater sürüm karşılaştırma, GitHub API ayrıştırma ve yerinde güncelleme betiği testleri."""

    def test_version_parsing_and_comparison(self):
        self.assertEqual(gui.AutoUpdater.parse_version("v1.1.0"), (1, 1, 0))
        self.assertEqual(gui.AutoUpdater.parse_version("1.2.3-beta1"), (1, 2, 3))
        self.assertTrue(gui.AutoUpdater.is_newer_version("v1.2.0", "1.1.0"))
        self.assertTrue(gui.AutoUpdater.is_newer_version("v2.0.0", "1.9.9"))
        self.assertFalse(gui.AutoUpdater.is_newer_version("v1.1.0", "1.1.0"))
        self.assertFalse(gui.AutoUpdater.is_newer_version("v1.0.0", "1.1.0"))

    def test_check_for_updates_when_newer(self):
        fake_json = (
            '{"tag_name": "v1.2.0", "body": "Yeni sürüm notları", '
            '"html_url": "https://github.com/example", '
            '"assets": [{"name": "UYAP-Maskeleme.dmg", "size": 26000000, '
            '"browser_download_url": "https://example.com/UYAP-Maskeleme.dmg"}]}'
        ).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_json
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = gui.AutoUpdater.check_for_updates(current_version="1.1.0")
            self.assertIsNotNone(res)
            self.assertEqual(res["version"], "1.2.0")
            self.assertEqual(res["download_url"], "https://example.com/UYAP-Maskeleme.dmg")

    def test_check_for_updates_when_up_to_date(self):
        fake_json = '{"tag_name": "v1.1.0", "assets": []}'.encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_json
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = gui.AutoUpdater.check_for_updates(current_version="1.1.0")
            self.assertIsNone(res)

    @staticmethod
    def _rate_limited(*args, **kwargs):
        import urllib.error
        raise urllib.error.HTTPError(gui.GITHUB_API_LATEST, 403, "rate limit exceeded", {}, None)

    def test_rate_limit_falls_back_to_web_redirect(self):
        """API sınırı (403) dolunca releases/latest yönlendirmesinden yeni sürüm bulunur."""
        def fake_head(url, ua, timeout):
            if url == gui.GITHUB_WEB_LATEST:
                return 302, "https://github.com/MertAtis/Uyap-Dosya-Maskeleme-YPro/releases/tag/v1.3.0"
            self.assertTrue(url.endswith("/releases/download/v1.3.0/UYAP-Maskeleme.dmg"))
            return 302, "https://objects.githubusercontent.com/..."

        with patch("urllib.request.urlopen", side_effect=self._rate_limited), \
                patch.object(gui.AutoUpdater, "_head_status", side_effect=fake_head):
            res = gui.AutoUpdater.check_for_updates(current_version="1.2.0")
        self.assertIsNotNone(res)
        self.assertEqual(res["version"], "1.3.0")
        self.assertEqual(
            res["download_url"],
            "https://github.com/MertAtis/Uyap-Dosya-Maskeleme-YPro/releases/download/v1.3.0/UYAP-Maskeleme.dmg",
        )

    def test_rate_limit_fallback_up_to_date_and_missing_dmg(self):
        """Yedek yolda sürüm güncelse veya DMG yüklenmemişse güncelleme önerilmez."""
        same = lambda url, ua, t: (302, "https://github.com/x/y/releases/tag/v1.2.0")
        with patch("urllib.request.urlopen", side_effect=self._rate_limited), \
                patch.object(gui.AutoUpdater, "_head_status", side_effect=same):
            self.assertIsNone(gui.AutoUpdater.check_for_updates(current_version="1.2.0"))

        def no_dmg(url, ua, t):
            if url == gui.GITHUB_WEB_LATEST:
                return 302, "https://github.com/x/y/releases/tag/v1.3.0"
            return 404, ""
        with patch("urllib.request.urlopen", side_effect=self._rate_limited), \
                patch.object(gui.AutoUpdater, "_head_status", side_effect=no_dmg):
            self.assertIsNone(gui.AutoUpdater.check_for_updates(current_version="1.2.0"))

    def test_rate_limit_fallback_failure_reports_original_error(self):
        """Yedek yol da başarısızsa asıl API hatası (403) iletilir; 404 gibi diğer hatalarda yedek denenmez."""
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=self._rate_limited), \
                patch.object(gui.AutoUpdater, "_head_status", side_effect=OSError("ağ yok")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                gui.AutoUpdater.check_for_updates(current_version="1.2.0")
            self.assertEqual(ctx.exception.code, 403)

        def not_found(*a, **k):
            raise urllib.error.HTTPError(gui.GITHUB_API_LATEST, 404, "Not Found", {}, None)
        with patch("urllib.request.urlopen", side_effect=not_found), \
                patch.object(gui.AutoUpdater, "_head_status") as mock_head:
            with self.assertRaises(urllib.error.HTTPError):
                gui.AutoUpdater.check_for_updates(current_version="1.2.0")
            mock_head.assert_not_called()

    def test_auto_update_check_disabled_by_env(self):
        """UYAP_DISABLE_UPDATE_CHECK=1 iken açılışta güncelleme kontrolü zamanlanmaz."""
        with patch.object(messagebox, "showinfo"):
            app = UyapRedactorApp()
        try:
            self.assertIsNone(app._update_check_job)
        finally:
            app.destroy()

    def test_build_updater_script(self):
        script = gui.AutoUpdater.build_updater_script(
            "/Applications/UYAP Maskeleme.app",
            "/tmp/mnt/UYAP Maskeleme.app",
            "/tmp/mnt",
            "/tmp/uyap_update_123",
            old_pid=12345,
        )
        self.assertIn('OLD_PID="$5"', script)
        self.assertIn('while kill -0 "$OLD_PID"', script)
        self.assertIn('ditto "$SRC_APP" "$TARGET_APP"', script)
        self.assertIn('.backup_', script)
        self.assertIn('hdiutil detach "$MNT_DIR"', script)
        self.assertIn('open -n "$TARGET_APP"', script)

    def test_target_app_path_edge_cases(self):
        # 1. Normal /Applications
        with patch("sys.executable", "/Applications/UYAP Maskeleme.app/Contents/MacOS/UYAP Maskeleme"):
            with patch("os.access", return_value=True), patch("os.path.exists", return_value=True):
                self.assertEqual(gui.AutoUpdater.get_target_app_path(), "/Applications/UYAP Maskeleme.app")

        # 2. Salt-okunur DMG /Volumes/
        with patch("sys.executable", "/Volumes/UYAP Maskeleme/UYAP Maskeleme.app/Contents/MacOS/UYAP Maskeleme"):
            self.assertEqual(gui.AutoUpdater.get_target_app_path(), "/Applications/UYAP Maskeleme.app")

        # 3. macOS AppTranslocation geçici dizini
        with patch("sys.executable", "/private/var/folders/xx/T/AppTranslocation/d/UYAP Maskeleme.app/Contents/MacOS/UYAP Maskeleme"):
            self.assertEqual(gui.AutoUpdater.get_target_app_path(), "/Applications/UYAP Maskeleme.app")

        # 4. Yazma izni olmayan dizin
        with patch("sys.executable", "/opt/restricted/UYAP Maskeleme.app/Contents/MacOS/UYAP Maskeleme"):
            with patch("os.access", return_value=False), patch("os.path.exists", return_value=True):
                self.assertEqual(gui.AutoUpdater.get_target_app_path(), "/Applications/UYAP Maskeleme.app")


def run_tests():
    """Testleri çalıştır ve detaylı sonuç döndür."""
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result


if __name__ == "__main__":
    result = run_tests()
    sys.exit(0 if result.wasSuccessful() else 1)
