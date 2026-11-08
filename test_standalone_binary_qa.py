#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UYAP Maskeleme — macOS Standalone Binary & GUI QA Otomasyon Test Paketi
'dist/UYAP Maskeleme.app' paketinin bağımsız çalıştırılabilir ikili dosyasını,
gömülü Python çalışma zamanını, Tkinter arayüzünü, kısayollarını,
butonlarını ve durum mekanizmalarını test eden kapsamlı otomasyon test kiti.
"""

import os
import sys
import time
import signal
import unittest
import subprocess
from unittest.mock import patch, MagicMock

# Proje ana dizini
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(PROJECT_ROOT, "dist", "UYAP Maskeleme.app")
BINARY_PATH = os.path.join(APP_PATH, "Contents", "MacOS", "UYAP Maskeleme")
FRAMEWORKS_PATH = os.path.join(APP_PATH, "Contents", "Frameworks")
RESOURCES_PATH = os.path.join(APP_PATH, "Contents", "Resources")
INFO_PLIST_PATH = os.path.join(APP_PATH, "Contents", "Info.plist")

import tkinter as tk
import gui
from gui import (
    Theme,
    GlassPillBadge,
    GlassButton,
    GlassStatCard,
    GlassStatusPill,
    GlassProgressBar,
    UyapRedactorApp
)


class Test1_PackageArchitecture(unittest.TestCase):
    """1. Adım: dist/UYAP Maskeleme.app paket mimarisi ve imza incelemesi."""

    def test_bundle_structure(self):
        """App bundle dizin ve anahtar dosya yapısı doğrulaması."""
        self.assertTrue(os.path.isdir(APP_PATH), f"App bundle bulunamadı: {APP_PATH}")
        self.assertTrue(os.path.isfile(BINARY_PATH), f"Binary bulunamadı: {BINARY_PATH}")
        self.assertTrue(os.path.isfile(INFO_PLIST_PATH), f"Info.plist bulunamadı: {INFO_PLIST_PATH}")
        self.assertTrue(os.path.isdir(FRAMEWORKS_PATH), f"Frameworks dizini bulunamadı: {FRAMEWORKS_PATH}")
        self.assertTrue(os.path.isdir(RESOURCES_PATH), f"Resources dizini bulunamadı: {RESOURCES_PATH}")
        self.assertTrue(os.access(BINARY_PATH, os.X_OK), "Binary çalıştırılabilir izne (+x) sahip değil!")

    def test_macho_arm64_architecture(self):
        """Binary dosyasının Mach-O 64-bit arm64 olduğunu doğrula."""
        cmd = ["file", BINARY_PATH]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        self.assertIn("Mach-O 64-bit executable arm64", res.stdout)

    def test_otool_shared_libraries(self):
        """otool -L ile sistem kütüphane bağlantılarını doğrula."""
        cmd = ["otool", "-L", BINARY_PATH]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        self.assertIn("Carbon.framework", res.stdout)
        self.assertIn("CoreFoundation.framework", res.stdout)
        self.assertIn("ApplicationServices.framework", res.stdout)
        self.assertIn("libSystem.B.dylib", res.stdout)

    def test_codesign_ad_hoc(self):
        """codesign doğrulaması ve ad-hoc imza varlığı."""
        cmd = ["codesign", "-dvvv", APP_PATH]
        res = subprocess.run(cmd, capture_output=True, text=True)
        combined = res.stdout + res.stderr
        self.assertIn("Identifier=com.yargipro.uyapredactor", combined)
        self.assertIn("Format=app bundle with Mach-O thin (arm64)", combined)
        self.assertIn("Signature=adhoc", combined)

    def test_info_plist_keys(self):
        """Info.plist kritik anahtar-değer doğrulaması."""
        cmd = ["plutil", "-p", INFO_PLIST_PATH]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        self.assertIn('"CFBundleDisplayName" => "UYAP Maskeleme"', res.stdout)
        self.assertIn('"CFBundleIdentifier" => "com.yargipro.uyapredactor"', res.stdout)
        self.assertIn('"CFBundleExecutable" => "UYAP Maskeleme"', res.stdout)
        self.assertIn('"LSMinimumSystemVersion" => "12.0"', res.stdout)
        self.assertIn('"NSHighResolutionCapable" => true', res.stdout)
        self.assertIn('"NSRequiresAquaSystemAppearance" => true', res.stdout)


class Test2_EmbeddedLibraries(unittest.TestCase):
    """4. Adım: Gömülü kütüphanelerin paket içinde mevcut ve erişilebilir olması."""

    def test_python_runtime_dylib(self):
        """libpython3.13.dylib paket içinde mevcut ve arm64 mimarisinde."""
        libpy = os.path.join(FRAMEWORKS_PATH, "libpython3.13.dylib")
        self.assertTrue(os.path.isfile(libpy), "libpython3.13.dylib bulunamadı!")
        res = subprocess.run(["file", libpy], capture_output=True, text=True, check=True)
        self.assertIn("Mach-O 64-bit dynamically linked shared library arm64", res.stdout)

    def test_tkinter_tcl_dylibs(self):
        """Tk ve Tcl 8.6 kütüphaneleri ve veri dosyaları mevcut."""
        libtk = os.path.join(FRAMEWORKS_PATH, "libtk8.6.dylib")
        libtcl = os.path.join(FRAMEWORKS_PATH, "libtcl8.6.dylib")
        self.assertTrue(os.path.isfile(libtk), "libtk8.6.dylib bulunamadı!")
        self.assertTrue(os.path.isfile(libtcl), "libtcl8.6.dylib bulunamadı!")
        self.assertTrue(os.path.exists(os.path.join(FRAMEWORKS_PATH, "_tk_data")), "_tk_data bulunamadı!")
        self.assertTrue(os.path.exists(os.path.join(FRAMEWORKS_PATH, "_tcl_data")), "_tcl_data bulunamadı!")

    def test_pymupdf_fitz_components(self):
        """PyMuPDF / fitz kütüphanesi C-extension ve paylaşımlı kütüphaneleri mevcut."""
        pymupdf_dir = os.path.join(FRAMEWORKS_PATH, "pymupdf")
        self.assertTrue(os.path.isdir(pymupdf_dir), "pymupdf dizini bulunamadı!")
        self.assertTrue(os.path.isfile(os.path.join(pymupdf_dir, "_mupdf.so")), "_mupdf.so bulunamadı!")
        self.assertTrue(os.path.isfile(os.path.join(pymupdf_dir, "libmupdf.dylib")), "libmupdf.dylib bulunamadı!")

    def test_vision_cocoa_pil_libraries(self):
        """Vision, Cocoa (AppKit, Foundation, Quartz) ve PIL paketleri mevcut."""
        self.assertTrue(os.path.isdir(os.path.join(FRAMEWORKS_PATH, "Vision")), "Vision dizini bulunamadı!")
        self.assertTrue(os.path.isdir(os.path.join(FRAMEWORKS_PATH, "PIL")), "PIL dizini bulunamadı!")
        self.assertTrue(os.path.isdir(os.path.join(FRAMEWORKS_PATH, "AppKit")), "AppKit dizini bulunamadı!")
        self.assertTrue(os.path.isdir(os.path.join(FRAMEWORKS_PATH, "Foundation")), "Foundation dizini bulunamadı!")
        self.assertTrue(os.path.isdir(os.path.join(FRAMEWORKS_PATH, "Quartz")), "Quartz dizini bulunamadı!")
        self.assertTrue(os.path.isdir(os.path.join(FRAMEWORKS_PATH, "objc")), "objc dizini bulunamadı!")


class Test3_GUIComponentsAndLayout(unittest.TestCase):
    """3. Adım A: Tkinter Arayüzü, Bileşenleri, İstatistik Kartları, Terminal."""

    @classmethod
    def setUpClass(cls):
        cls.app = UyapRedactorApp()
        cls.app.update()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.app.destroy()
        except Exception:
            pass

    def test_window_geometry_and_properties(self):
        """Pencere boyutu (860x780), minsize (800, 700), başlık ve arka plan rengi."""
        self.assertEqual(self.app.cget("bg"), Theme.BG_CANVAS)
        self.assertIn("UYAP Kişisel Veri Maskeleme", self.app.title())
        min_w, min_h = self.app.minsize()
        self.assertEqual(min_w, 800)
        self.assertEqual(min_h, 700)
        self.assertEqual(self.app.winfo_width(), 860)

    def test_canvas_progress_bar(self):
        """Canvas tabanlı GlassProgressBar bileşeni doğrulama."""
        pbar = self.app.progress
        self.assertIsInstance(pbar, GlassProgressBar)
        self.assertEqual(pbar.bar_height, 12)
        self.assertEqual(pbar.track_color, "#E4E4E7")
        self.assertEqual(pbar.fill_color, Theme.BLUE_PRIMARY)

        # Değer atama ve okuma testi
        pbar["value"] = 50
        pbar["maximum"] = 100
        self.assertEqual(pbar["value"], 50)
        self.assertEqual(pbar["maximum"], 100)
        pbar._redraw()
        self.app.update()

    def test_glowing_status_pill(self):
        """Apple tarzı parlayan cam hap durum göstergesi (GlassStatusPill)."""
        pill = self.app.lbl_status
        self.assertIsInstance(pill, GlassStatusPill)
        self.assertEqual(pill.lbl_dot.cget("fg"), "#10B981")  # Başlangıçta zümrüt yeşili
        self.assertIn("Hazır", pill.lbl_text.cget("text"))

        # Pulsing moduna geçiş
        pill.start_pulse()
        self.assertTrue(pill.is_pulsing)

        # Durdurma ve renk atama
        pill.stop_pulse(color="#EF4444")
        self.assertFalse(pill.is_pulsing)
        self.assertEqual(pill.lbl_dot.cget("fg"), "#EF4444")

        # Otomatik algılama
        pill.config(text="Dosyalar işleniyor...")
        self.assertTrue(pill.is_pulsing)
        pill.config(text="İşlem başarıyla tamamlandı.")
        self.assertFalse(pill.is_pulsing)
        self.assertEqual(pill.lbl_dot.cget("fg"), "#10B981")

    def test_eight_stat_cards(self):
        """8 adet istatistik kartının varlığı, renkleri ve başlangıç değerleri."""
        cards = [
            (self.app.card_tckn, "🆔 TCKN Gizlenen", Theme.STAT_TCKN),
            (self.app.card_telefon, "📱 Telefon Gizlenen", Theme.STAT_TEL),
            (self.app.card_seri_no, "🪪 Kimlik Seri No", Theme.STAT_SERI),
            (self.app.card_mrz, "📑 Kimlik MRZ Kodu", Theme.STAT_MRZ),
            (self.app.card_iban, "💳 IBAN Gizlenen", Theme.STAT_IBAN),
            (self.app.card_sicil, "⚖️ Sicil No Gizlenen", Theme.STAT_SICIL),
            (self.app.card_adres, "📍 Adres Gizlenen", Theme.STAT_ADRES),
            (self.app.card_files, "📄 Aktarılan / OCR", Theme.STAT_FILES),
        ]
        self.assertEqual(len(cards), 8, "Tam olarak 8 adet stat kartı bulunmalı!")
        for card, title, color in cards:
            self.assertIsInstance(card, GlassStatCard)
            self.assertEqual(card.lbl_title.cget("text"), title)
            self.assertEqual(card.lbl_val.cget("fg"), color)
            self.assertEqual(card.lbl_val.cget("text"), "0")
            # Değer güncelleme testi
            card.update_value("42")
            self.assertEqual(card.lbl_val.cget("text"), "42")
            card.update_value("0")

    def test_dark_terminal_console(self):
        """Koyu terminal konsolu, renkleri, pencere noktaları ve syntax etiketleri."""
        self.assertEqual(self.app.log_text.cget("bg"), Theme.TERM_BG)
        self.assertEqual(self.app.log_text.cget("fg"), Theme.TERM_FG)
        self.assertEqual(self.app.lbl_console_title.cget("text"), "Console Output  •  Canlı İşlem Günlüğü")

        # Syntax tag kontrolleri
        tags = self.app.log_text.tag_names()
        for expected_tag in ["mask", "ocr", "sync", "error", "header"]:
            self.assertIn(expected_tag, tags, f"Syntax tag '{expected_tag}' tanımlı değil!")


class Test4_ButtonInteractionsAndShortcuts(unittest.TestCase):
    """3. Adım B: Buton Etkileşimleri ve Klavye Kısayolları."""

    def setUp(self):
        self.app = UyapRedactorApp()
        self.app.update()

    def tearDown(self):
        try:
            self.app.destroy()
        except Exception:
            pass

    def test_button_existence_and_variants(self):
        """Tüm butonların varlığı ve doğru varyantlarda tanımlandığı."""
        self.assertIsInstance(self.app.btn_run, GlassButton)
        self.assertIsInstance(self.app.btn_open_folder, GlassButton)
        self.assertIsInstance(self.app.btn_clear, GlassButton)

        self.assertEqual(self.app.btn_run.variant, "primary")
        self.assertEqual(self.app.btn_open_folder.variant, "secondary")
        self.assertEqual(self.app.btn_clear.variant, "subtle")

    def test_btn_clear_action(self):
        """btn_clear tıklandığında log metninin temizlenmesi."""
        self.app.log_text.insert(tk.END, "Test log metni 1\nTest log metni 2\n")
        self.assertIn("Test log", self.app.log_text.get("1.0", tk.END))
        self.app.btn_clear.command()
        self.assertEqual(self.app.log_text.get("1.0", tk.END).strip(), "")

    def test_btn_browse_interaction(self):
        """btn_browse tıklandığında klasör seçimi yapılması, durum ve log alanına yansıması."""
        with patch.object(gui.filedialog, "askdirectory", return_value="/tmp/test_dava_klasoru") as mock_dir:
            self.app._select_folder()
            mock_dir.assert_called_once()
            self.assertEqual(self.app.folder_var.get(), "/tmp/test_dava_klasoru")
            self.assertIn("test_dava_klasoru", self.app.lbl_status.lbl_text.cget("text"))
            self.assertIn("Kaynak klasör seçildi", self.app.log_text.get("1.0", tk.END))

    def test_btn_open_folder_interaction(self):
        """btn_open_folder tıklandığında hedef klasör yoksa bilgi vermesi, varsa Finder ile açması."""
        # Durum 1: Henüz klasör üretilmemişken
        self.app.last_dest_folder = None
        with patch.object(gui.messagebox, "showinfo") as mock_info:
            self.app._open_dest_folder()
            mock_info.assert_called_once_with("Bilgi", "Oluşturulmuş izole temiz klasör bulunamadı.")

        # Durum 2: Klasör üretilmişken
        with patch("os.path.exists", return_value=True), patch("subprocess.run") as mock_subproc:
            self.app.last_dest_folder = "/tmp/test_dava (Maskelenmis AI)"
            self.app._open_dest_folder()
            mock_subproc.assert_called_once_with(["open", "/tmp/test_dava (Maskelenmis AI)"])

    def test_btn_run_empty_folder_validation(self):
        """Klasör seçilmeden btn_run tıklandığında uyarı verilmesi ve çalışmanın engellenmesi."""
        self.app.folder_var.set("")
        with patch.object(gui.messagebox, "showwarning") as mock_warn:
            self.app.btn_run.command()
            mock_warn.assert_called_once()
            self.assertFalse(self.app.is_running)

    def test_btn_run_execution_flow(self):
        """btn_run tıklandığında (klasör geçerli iken) işlem thread'inin başlatılması ve buton durumları."""
        self.app.folder_var.set("/tmp/test_dava")
        with patch("os.path.isdir", return_value=True), patch("threading.Thread") as mock_thread_cls:
            mock_thread_instance = MagicMock()
            mock_thread_cls.return_value = mock_thread_instance

            self.app.btn_run.command()

            self.assertTrue(self.app.is_running)
            self.assertEqual(self.app.btn_run.state, "disabled")
            self.assertEqual(self.app.btn_run.label.cget("text"), "İşleniyor...")
            mock_thread_instance.start.assert_called_once()

    def test_keyboard_shortcuts_binding(self):
        """Kısayolların (<Command-o>, <Command-r>, <Command-k>, <Command-q>, <Command-w>) doğru bağlanması."""
        # Command-o (Klasör Seçme)
        with patch.object(self.app, "_select_folder") as mock_o:
            self.app.event_generate("<Command-o>")
            mock_o.assert_called_once()

        # Command-k (Log Temizleme)
        with patch.object(self.app, "_clear_logs") as mock_k:
            self.app.event_generate("<Command-k>")
            mock_k.assert_called_once()

        # Command-r (Başlatma)
        with patch.object(self.app, "_start_process") as mock_r:
            self.app.is_running = False
            self.app.event_generate("<Command-r>")
            mock_r.assert_called_once()

        # Command-r çalışırken engellenmeli
        with patch.object(self.app, "_start_process") as mock_r_blocked:
            self.app.is_running = True
            self.app.event_generate("<Command-r>")
            mock_r_blocked.assert_not_called()

        # Command-w (Kapatma)
        with patch.object(self.app, "destroy") as mock_destroy_w:
            self.app.event_generate("<Command-w>")
            mock_destroy_w.assert_called_once()

        # Command-q (Çıkış)
        with patch.object(self.app, "destroy") as mock_destroy_q:
            self.app.event_generate("<Command-q>")
            mock_destroy_q.assert_called_once()


class Test5_LiveStandaloneBinaryProcess(unittest.TestCase):
    """2. ve 3. Adım C: Bağımsız ikili dosyanın çalıştırılması, osascript ile tespiti ve temiz sonlanma."""

    def test_live_binary_launch_and_sigterm_exit(self):
        """İkili dosyanın başlatılması, Window Server'da pencere tespiti ve SIGTERM ile temiz kapanma."""
        proc = subprocess.Popen([BINARY_PATH], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        pid = proc.pid
        time.sleep(2.0)

        try:
            # Sürecin canlı olduğunu doğrula
            self.assertIsNone(proc.poll(), f"Binary başlatılamadı veya erken kapandı: PID {pid}")

            # AppleScript ile Window Server'dan pencere başlığı ve boyutunu doğrula
            ascript = f'''
            tell application "System Events"
                set procs to every process whose unix id is {pid}
                if (count of procs) > 0 then
                    set theProc to item 1 of procs
                    set winTitles to {{}}
                    repeat with w in (every window of theProc)
                        set end of winTitles to (name of w as string)
                    end repeat
                    return (winTitles as string)
                else
                    return "NOT_FOUND"
                end if
            end tell
            '''
            res = subprocess.run(["osascript", "-e", ascript], capture_output=True, text=True)
            output = res.stdout.strip()
            self.assertIn("UYAP Kişisel Veri Maskeleme", output)

            # SIGTERM sinyali ile temiz kapanmayı doğrula (takılı kalmadan sonlanması)
            os.kill(pid, signal.SIGTERM)
            exit_code = proc.wait(timeout=5.0)
            # SIGTERM sonucu exit code işletim sistemi ve PyInstaller bootloader tarafından 0, 1, -15 veya 143 dönebilir
            self.assertIn(exit_code, [0, 1, -15, 143])
            self.assertIsNotNone(proc.poll(), "Süreç SIGTERM sonrasında kapanmadı!")
        finally:
            if proc.poll() is None:
                proc.kill()

    def test_live_binary_close_via_command_q(self):
        """Canlı çalışan bağımsız binary'ye macOS Command-Q göndererek destroy ile temiz kapanmasını test etme."""
        proc = subprocess.Popen([BINARY_PATH], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        pid = proc.pid
        time.sleep(2.0)

        try:
            self.assertIsNone(proc.poll(), f"Binary başlatılamadı: PID {pid}")

            # AppleScript ile ön plana al ve Command-q tuş kombinasyonu gönder
            ascript = f'''
            tell application "System Events"
                set procs to every process whose unix id is {pid}
                if (count of procs) > 0 then
                    set frontmost of (item 1 of procs) to true
                    delay 0.5
                    keystroke "q" using {{command down}}
                    return "SENT"
                end if
            end tell
            '''
            subprocess.run(["osascript", "-e", ascript], capture_output=True, text=True)
            
            # Uygulamanın destroy ile kapanmasını bekle
            exit_code = proc.wait(timeout=4.0)
            self.assertEqual(exit_code, 0, f"Command-Q ile temiz çıkış kodu 0 bekleniyordu, gelen: {exit_code}")
        finally:
            if proc.poll() is None:
                proc.kill()

    def test_live_binary_close_via_command_w(self):
        """Canlı çalışan bağımsız binary'ye macOS Command-W göndererek kapanmasını test etme."""
        proc = subprocess.Popen([BINARY_PATH], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        pid = proc.pid
        time.sleep(2.0)

        try:
            self.assertIsNone(proc.poll(), f"Binary başlatılamadı: PID {pid}")

            # AppleScript ile ön plana al ve Command-w tuş kombinasyonu gönder
            ascript = f'''
            tell application "System Events"
                set procs to every process whose unix id is {pid}
                if (count of procs) > 0 then
                    set frontmost of (item 1 of procs) to true
                    delay 0.5
                    keystroke "w" using {{command down}}
                    return "SENT"
                end if
            end tell
            '''
            subprocess.run(["osascript", "-e", ascript], capture_output=True, text=True)
            
            # 3 saniye içinde uygulamanın destroy ile kapanmasını bekle
            exit_code = proc.wait(timeout=4.0)
            self.assertEqual(exit_code, 0, f"Command-W ile temiz çıkış kodu 0 bekleniyordu, gelen: {exit_code}")
        finally:
            if proc.poll() is None:
                proc.kill()


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
