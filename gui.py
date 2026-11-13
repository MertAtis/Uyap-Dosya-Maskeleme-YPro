#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UYAP Maskeleme — macOS Desktop GUI
Çevrimdışı (Offline) UYAP Kişisel Veri Maskeleme ve AI Hazırlık Aracı

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
import re
import sys
import json
import ssl
import tempfile
import urllib.request
import urllib.error
import urllib.parse
import threading
import queue
import time
import subprocess
import unicodedata
import shutil
from datetime import datetime
from typing import Optional, Dict, Tuple, Callable
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

# Uygulama Sürümü ve Otomatik Güncelleme Kaynağı
APP_VERSION = "1.4.4"
RUN_BUTTON_TEXT = "▶  Başlat"
GITHUB_REPO = "MertAtis/Uyap-Dosya-Maskeleme-YPro"
GITHUB_API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
# API'nin saatlik istek sınırına takılınca kullanılan, sınırsız web adresleri
GITHUB_WEB_LATEST = f"https://github.com/{GITHUB_REPO}/releases/latest"
GITHUB_WEB_DOWNLOAD = f"https://github.com/{GITHUB_REPO}/releases/download/{{tag}}/{{asset}}"
DMG_ASSET_NAME = "UYAP-Maskeleme.dmg"


class AutoUpdater:
    """
    GitHub Releases üzerinden tek tıkla (baştan kurulum gerektirmeyen)
    otomatik DMG indirme, bağlama ve .app paketini yerinde yenileme motoru.
    Çevrimdışı (offline) kullanımda sessizce devre dışı kalır, asla hata vermez.
    """

    @staticmethod
    def parse_version(v_str: str) -> Tuple[int, ...]:
        """'v1.2.3' veya '1.2.3-beta' gibi sürüm dizgesini (1, 2, 3) demetine çevirir."""
        if not v_str:
            return (0, 0, 0)
        clean = str(v_str).strip().lstrip("vV").split("-")[0]
        nums = [int(x) for x in re.findall(r"\d+", clean)]
        return tuple(nums) if nums else (0, 0, 0)

    @classmethod
    def is_newer_version(cls, remote_tag: str, local_version: str = APP_VERSION) -> bool:
        """Uzak sürümün mevcut yerel sürümden daha yeni olup olmadığını döndürür."""
        return cls.parse_version(remote_tag) > cls.parse_version(local_version)

    @staticmethod
    def _create_ssl_context() -> ssl.SSLContext:
        """macOS PyInstaller paketlerinde sistem ve certifi kök sertifikalarını kullanan güvenli SSL bağlamı."""
        # 1. macOS sistem OpenSSL sertifika demeti
        if os.path.exists("/etc/ssl/cert.pem"):
            try:
                return ssl.create_default_context(cafile="/etc/ssl/cert.pem")
            except Exception:
                pass
        # 2. certifi kök sertifika deposu (varsa)
        try:
            import certifi
            if os.path.exists(certifi.where()):
                return ssl.create_default_context(cafile=certifi.where())
        except Exception:
            pass
        # 3. Python varsayılan SSL bağlamı
        return ssl.create_default_context()

    @classmethod
    def check_for_updates(cls, current_version: str = APP_VERSION, timeout: float = 5.0) -> Optional[Dict]:
        """
        GitHub Releases API'sini sorgular.
        Daha yeni bir sürüm varsa {'version', 'tag_name', 'download_url', 'release_notes', 'html_url', 'size'}
        sözlüğünü döndürür. Güncelse None döndürür. Bağlantı hatasında exception fırlatır.

        API, kimliksiz isteklerde IP başına saatte 60 sorguyla sınırlıdır. Aynı ağı paylaşan
        bürolarda bu sınır dolunca (403/429) veya API geçici olarak yanıt vermezse (5xx),
        sınırı olmayan github.com web adreslerinden aynı bilgi çıkarılır.
        """
        req = urllib.request.Request(
            GITHUB_API_LATEST,
            headers={
                "User-Agent": f"UYAP-Maskeleme-macOS/{current_version}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        ctx = cls._create_ssl_context()
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as api_err:
            if api_err.code in (403, 429) or api_err.code >= 500:
                try:
                    return cls._check_for_updates_via_web(current_version, timeout)
                except Exception:
                    # Yedek yol da başarısızsa asıl API hatasını bildir
                    raise api_err
            raise

        tag_name = data.get("tag_name", "")
        if not tag_name or not cls.is_newer_version(tag_name, current_version):
            return None

        # Release içindeki .dmg dosyasını bul
        assets = data.get("assets", []) or []
        dmg_asset = None
        for asset in assets:
            name = asset.get("name", "")
            if name.lower().endswith(".dmg"):
                dmg_asset = asset
                if "uyap" in name.lower():
                    break

        if not dmg_asset or not dmg_asset.get("browser_download_url"):
            return None

        return {
            "version": tag_name.lstrip("vV"),
            "tag_name": tag_name,
            "download_url": dmg_asset["browser_download_url"],
            "size": int(dmg_asset.get("size", 0) or 0),
            "release_notes": (data.get("body") or "").strip() or "Yeni kişisel veri yakalama kuralları ve performans iyileştirmeleri.",
            "html_url": data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases/latest"),
        }

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        """Yönlendirmeyi izlemez; 30x yanıtı HTTPError olarak döner ki Location okunabilsin."""
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    @classmethod
    def _head_status(cls, url: str, user_agent: str, timeout: float) -> Tuple[int, str]:
        """URL'ye yönlendirme izlemeden HEAD isteği atar; (durum_kodu, Location) döndürür."""
        opener = urllib.request.build_opener(
            cls._NoRedirect(),
            urllib.request.HTTPSHandler(context=cls._create_ssl_context()),
        )
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": user_agent})
        try:
            with opener.open(req, timeout=timeout) as resp:
                return resp.status, resp.headers.get("Location", "") or ""
        except urllib.error.HTTPError as e:
            return e.code, (e.headers.get("Location", "") if e.headers else "") or ""

    @classmethod
    def _check_for_updates_via_web(cls, current_version: str, timeout: float) -> Optional[Dict]:
        """
        API sınırına takılınca yedek yol:
        1. github.com/<repo>/releases/latest -> /releases/tag/<etiket> yönlendirmesinden etiketi okur.
        2. Etiketteki DMG'nin varlığını releases/download/<etiket>/UYAP-Maskeleme.dmg ile doğrular
           (dosya indirilmez; yalnızca HEAD).
        """
        ua = f"UYAP-Maskeleme-macOS/{current_version}"
        status, location = cls._head_status(GITHUB_WEB_LATEST, ua, timeout)
        m = re.search(r"/releases/tag/([^/?#]+)/?$", location)
        if status not in (301, 302, 303, 307, 308) or not m:
            raise RuntimeError(f"Son sürüm etiketi okunamadı (HTTP {status}).")
        tag_name = urllib.parse.unquote(m.group(1))
        if not cls.is_newer_version(tag_name, current_version):
            return None

        download_url = GITHUB_WEB_DOWNLOAD.format(tag=urllib.parse.quote(tag_name), asset=DMG_ASSET_NAME)
        asset_status, _ = cls._head_status(download_url, ua, timeout)
        if asset_status not in (200, 301, 302, 303, 307, 308):
            # Etiket var ama DMG henüz yüklenmemiş: güncelleme sunma
            return None

        return {
            "version": tag_name.lstrip("vV"),
            "tag_name": tag_name,
            "download_url": download_url,
            "size": 0,
            "release_notes": "Sürüm notları için GitHub sürüm sayfasına bakabilirsiniz.",
            "html_url": f"https://github.com/{GITHUB_REPO}/releases/tag/{tag_name}",
        }

    @staticmethod
    def get_target_app_path() -> str:
        """Güncellemenin yazılacağı hedef .app paket yolunu belirler."""
        exe_path = os.path.abspath(sys.executable)
        default_app = "/Applications/UYAP Maskeleme.app"

        if ".app/Contents/MacOS" in exe_path:
            app_root = exe_path.split(".app/Contents/MacOS")[0] + ".app"
            # Uç Durum Korumaları:
            # 1. Salt-okunur DMG bağlı diskindeyse (/Volumes/...)
            # 2. macOS Gatekeeper App Translocation geçici salt-okunur dizinindeyse (/AppTranslocation/...)
            # 3. Bulunduğu ana dizine yazma izni (W_OK) yoksa
            # Bu durumlarda standart '/Applications/UYAP Maskeleme.app' yoluna yönlendir.
            if (
                not app_root.startswith("/Volumes/")
                and "AppTranslocation" not in app_root
                and os.path.exists(app_root)
                and os.access(os.path.dirname(app_root), os.W_OK)
            ):
                return app_root
        return default_app

    @classmethod
    def build_updater_script(
        cls,
        target_app: str,
        src_app: str,
        mnt_dir: str,
        tmp_dir: str,
        old_pid: Optional[int] = None,
    ) -> str:
        """Uygulama kapandıktan hemen sonra eski .app'i yenisiyle güvenli/atomik değiştirip yeniden başlatan kabuk betiği."""
        pid_arg = str(old_pid) if old_pid else ""
        return (
            "#!/bin/sh\n"
            'TARGET_APP="$1"\n'
            'SRC_APP="$2"\n'
            'MNT_DIR="$3"\n'
            'TMP_DIR="$4"\n'
            'OLD_PID="$5"\n\n'
            "# 1. Eski uygulamanın (PID) tamamen kapanmasını bekle (maksimum 10 saniye)\n"
            'if [ -n "$OLD_PID" ]; then\n'
            "    count=0\n"
            '    while kill -0 "$OLD_PID" 2>/dev/null; do\n'
            "        sleep 0.2\n"
            "        count=$((count + 1))\n"
            '        if [ "$count" -ge 50 ]; then\n'
            '            kill -9 "$OLD_PID" 2>/dev/null || true\n'
            "            break\n"
            "        fi\n"
            "    done\n"
            "fi\n"
            "sleep 0.3\n\n"
            "# 2. Kaynak paketin bütünlüğünü doğrula\n"
            'if [ ! -d "$SRC_APP/Contents/MacOS" ]; then\n'
            '    hdiutil detach "$MNT_DIR" -force >/dev/null 2>&1 || true\n'
            '    rm -rf "$TMP_DIR" 2>/dev/null || true\n'
            "    exit 1\n"
            "fi\n\n"
            "# 3. Güvenli Yedekleme ve Atomik Değiştirme\n"
            'BACKUP_APP=""\n'
            'if [ -d "$TARGET_APP" ]; then\n'
            '    BACKUP_APP="${TARGET_APP}.backup_$$\"\n'
            '    mv "$TARGET_APP" "$BACKUP_APP" 2>/dev/null || true\n'
            "fi\n\n"
            'if ditto "$SRC_APP" "$TARGET_APP"; then\n'
            '    if [ -n "$BACKUP_APP" ] && [ -d "$BACKUP_APP" ]; then\n'
            '        rm -rf "$BACKUP_APP" 2>/dev/null || true\n'
            "    fi\n"
            '    xattr -cr "$TARGET_APP" 2>/dev/null || true\n'
            '    codesign --force --deep --sign - "$TARGET_APP" 2>/dev/null || true\n'
            "else\n"
            '    rm -rf "$TARGET_APP" 2>/dev/null || true\n'
            '    if [ -n "$BACKUP_APP" ] && [ -d "$BACKUP_APP" ]; then\n'
            '        mv "$BACKUP_APP" "$TARGET_APP"\n'
            "    fi\n"
            "fi\n\n"
            "# 4. DMG diskini ayır ve temizle\n"
            'hdiutil detach "$MNT_DIR" -force >/dev/null 2>&1 || true\n'
            'rm -rf "$TMP_DIR" 2>/dev/null || true\n\n'
            "# 5. Uygulamayı yeniden başlat\n"
            'if [ -d "$TARGET_APP" ]; then\n'
            '    open -n "$TARGET_APP"\n'
            "fi\n"
        )

    @classmethod
    def download_and_install(
        cls,
        download_url: str,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> str:
        """
        DMG'yi geçici klasöre indirir, bağlar, güncelleme betiğini arka planda başlatır
        ve güncellenecek hedef .app yolunu döndürür.
        """
        tmp_dir = tempfile.mkdtemp(prefix="uyap_update_")
        dmg_path = os.path.join(tmp_dir, "UYAP-Maskeleme.dmg")
        mnt_dir = os.path.join(tmp_dir, "mnt")
        os.makedirs(mnt_dir, exist_ok=True)

        req = urllib.request.Request(
            download_url,
            headers={"User-Agent": f"UYAP-Maskeleme-macOS/{APP_VERSION}"},
        )
        ctx = cls._create_ssl_context()

        with urllib.request.urlopen(req, timeout=30.0, context=ctx) as resp:
            total_size = int(resp.headers.get("Content-Length", 0) or 0)
            downloaded = 0
            chunk_size = 65536
            with open(dmg_path, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        progress_cb(downloaded, total_size)

        if not os.path.exists(dmg_path) or os.path.getsize(dmg_path) < 100_000:
            raise RuntimeError("İndirilen güncelleme paketi eksik veya bozuk görünüyor.")

        # DMG'yi sessizce bağla
        attach_res = subprocess.run(
            ["hdiutil", "attach", dmg_path, "-nobrowse", "-readonly", "-mountpoint", mnt_dir],
            capture_output=True,
            text=True,
        )
        if attach_res.returncode != 0:
            raise RuntimeError(f"DMG bağlanamadı: {attach_res.stderr.strip()}")

        # Bağlanan diskteki .app paketini bul
        src_app = os.path.join(mnt_dir, "UYAP Maskeleme.app")
        if not os.path.exists(src_app):
            found_apps = [
                os.path.join(mnt_dir, item)
                for item in os.listdir(mnt_dir)
                if item.endswith(".app")
            ]
            if not found_apps:
                subprocess.run(["hdiutil", "detach", mnt_dir, "-force"], capture_output=True)
                raise RuntimeError("Güncelleme paketinin içinde .app uygulaması bulunamadı.")
            src_app = found_apps[0]

        target_app = cls.get_target_app_path()
        updater_sh = os.path.join(tmp_dir, "apply_update.sh")
        old_pid = os.getpid()
        with open(updater_sh, "w", encoding="utf-8") as sh_file:
            sh_file.write(cls.build_updater_script(target_app, src_app, mnt_dir, tmp_dir, old_pid=old_pid))
        os.chmod(updater_sh, 0o755)

        subprocess.Popen(
            ["/bin/sh", updater_sh, target_app, src_app, mnt_dir, tmp_dir, str(old_pid)],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return target_app

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
            # (Pencere henüz haritalanmamışken winfo_width()/winfo_height() 1 döner;
            #  istenen boyutla (winfo_reqwidth/reqheight) birlikte büyük olanı kullan)
            btn_w = max(self.winfo_width(), self.winfo_reqwidth())
            btn_h = max(self.winfo_height(), self.winfo_reqheight())
            if was_pressed and 0 <= e.x <= btn_w and 0 <= e.y <= btn_h:
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
            padx=7,
            pady=3,
            **kwargs
        )
        self.color = color

        # 1. Üst kenar Liquid Glass ışık yansıması (Subtle Highlight Bevel)
        self.top_highlight = tk.Frame(self, bg="#F4F4F6", height=1)
        self.top_highlight.pack(fill="x", pady=(0, 1))

        # 2. Başlık / Etiket
        self.lbl_title = tk.Label(
            self,
            text=title,
            font=Theme.font_text(9, "bold"),
            fg=Theme.TEXT_MUTED,
            bg=Theme.BG_SURFACE,
            anchor="w"
        )
        self.lbl_title.pack(anchor="w", fill="x")

        # 3. İstatistik Sayı Değeri (SF Pro Display)
        self.lbl_val = tk.Label(
            self,
            text=str(value),
            font=Theme.font_display(13, "bold"),
            fg=color,
            bg=Theme.BG_SURFACE
        )
        self.lbl_val.pack(anchor="w")

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
            padx=8,
            pady=3,
            **kwargs
        )
        self.pulse_index = 0
        self.is_pulsing = False
        self._pulse_job = None

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
            bg=Theme.BG_SURFACE,
            anchor="w"
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
        if self._pulse_job:
            try:
                self.after_cancel(self._pulse_job)
            except Exception:
                pass
            self._pulse_job = None
        try:
            self.lbl_dot.config(fg=color)
        except tk.TclError:
            pass

    def _pulse_loop(self):
        try:
            if not self.winfo_exists() or not self.is_pulsing:
                self.is_pulsing = False
                return
        except Exception:
            self.is_pulsing = False
            return
        colors = ["#0071E3", "#38BDF8", "#818CF8", "#0071E3"]
        self.pulse_index = (self.pulse_index + 1) % len(colors)
        try:
            self.lbl_dot.config(fg=colors[self.pulse_index])
            self._pulse_job = self.after(380, self._pulse_loop)
        except (tk.TclError, Exception):
            self.is_pulsing = False
            self._pulse_job = None


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
        if w <= 1:
            try:
                w = int(self.cget("width"))
            except (ValueError, tk.TclError):
                w = self.winfo_reqwidth()
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

try:  # Sürükle-bırak desteği (tkinterdnd2 yoksa uygulama yine çalışır, yalnızca "Seç…" kullanılır)
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _AppBase = TkinterDnD.Tk
    DND_AVAILABLE = True
except Exception:  # pragma: no cover - paket kurulu değilse
    DND_FILES = None
    _AppBase = tk.Tk
    DND_AVAILABLE = False


class UyapRedactorApp(_AppBase):
    def __init__(self):
        super().__init__()
        self.title("UYAP Kişisel Veri Maskeleme & İzole Temiz Klasör Üretici (Offline)")
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            px = max(0, (sw - 760) // 2)
            py = max(25, (sh - 560) // 2 - 15)
            self.geometry(f"760x560+{px}+{py}")
        except Exception:
            self.geometry("760x560")
        self.minsize(400, 440)
        self.configure(bg=Theme.BG_CANVAS)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.msg_queue = queue.Queue()
        self.is_running = False
        self.last_dest_folder = None
        self._queue_job = None
        self._update_check_job = None
        self.pending_update_info = None
        self.sources = []            # Sürükle-bırak / seçimle gelen dosya ve klasörler
        self._sources_display = ""   # Girdi kutusuna yazdığımız metin (elle düzenlendi mi anlamak için)
        self.out_var = tk.StringVar(value="")   # Boşsa: kaynağın yanına

        self._create_widgets()
        self._setup_dnd()
        self._setup_shortcuts()
        self._check_queue()
        # Açılışta arka planda sessiz güncelleme kontrolü (çevrimdışıysa sessizce geçer).
        # Otomatik testler UYAP_DISABLE_UPDATE_CHECK=1 ile kapatır ki GitHub sorgu sınırını tüketmesin.
        if os.environ.get("UYAP_DISABLE_UPDATE_CHECK") != "1":
            self._update_check_job = self.after(1500, lambda: self._check_updates(manual=False))

    def _setup_shortcuts(self):
        """macOS Klavye Kısayolları (⌘O, ⌘R, ⌘K, ⌘Q, ⌘W)."""
        self.bind("<Command-o>", lambda e: self._select_folder())
        self.bind("<Control-o>", lambda e: self._select_folder())
        self.bind("<Command-r>", lambda e: self._start_process() if not self.is_running else None)
        self.bind("<Control-r>", lambda e: self._start_process() if not self.is_running else None)
        self.bind("<Command-k>", lambda e: self._clear_logs())
        self.bind("<Control-k>", lambda e: self._clear_logs())
        self.bind("<Command-q>", lambda e: self._on_close())
        self.bind("<Command-w>", lambda e: self._on_close())

    def _on_close(self):
        """İşlem devam ederken yanlışlıkla kapatmayı önleyen güvenli çıkış kontrolü."""
        if getattr(self, "is_running", False):
            confirm = messagebox.askyesno(
                "İşlem Devam Ediyor",
                "Şu anda arka planda maskeleme veya güncelleme işlemi devam ediyor.\n\n"
                "Uygulamayı şimdi kapatırsanız işlem yarım kalabilir.\n"
                "Yine de çıkmak istiyor musunuz?"
            )
            if not confirm:
                return
        self.destroy()

    # Pencere bu genişliğin altına inince dar (tek sütun) düzene geçilir
    NARROW_BREAKPOINT = 640

    def _create_widgets(self):
        """
        Kompakt ve esnek düzen.
        - Geniş pencere: klasör + Seç + Başlat + Aç tek satırda, 8 istatistik tek satırda.
        - Dar pencere: Başlat/Aç ikinci satıra iner, istatistikler 4x2 ızgaraya geçer,
          ikincil açıklamalar gizlenir. Her öğe grid ağırlıklarıyla küçülür, taşmaz.
        """
        self._layout_mode = None

        # ------------------------------------------------------------------
        # 1. ÜST BAŞLIK
        # ------------------------------------------------------------------
        header = tk.Frame(self, bg=Theme.BG_SURFACE, padx=12, pady=6,
                          highlightbackground=Theme.BORDER_GLASS, highlightthickness=1)
        header.pack(fill="x", side="top")
        header.columnconfigure(2, weight=1)

        self.lbl_title = tk.Label(header, text="🛡️ UYAP Maskeleme", font=Theme.font_display(13, "bold"),
                                  fg=Theme.TEXT_PRIMARY, bg=Theme.BG_SURFACE)
        self.lbl_title.grid(row=0, column=0, sticky="w")

        self.lbl_subtitle = tk.Label(header, text="Çevrimdışı • Orijinal dosyalara dokunmaz",
                                     font=Theme.font_text(10), fg=Theme.TEXT_MUTED, bg=Theme.BG_SURFACE, anchor="w")
        self.lbl_subtitle.grid(row=0, column=1, sticky="w", padx=(10, 0))

        self.btn_update = GlassButton(header, text=f"v{APP_VERSION} • Güncelle", variant="secondary",
                                      command=self._on_update_button_click, padx=8, pady=2,
                                      font=Theme.font_text(10, "bold"))
        self.btn_update.grid(row=0, column=3, sticky="e")

        # ------------------------------------------------------------------
        # 7. ALT BİLGİ (başlıktan hemen sonra pack'lenir ki küçülünce kaybolmasın)
        # ------------------------------------------------------------------
        footer = tk.Frame(self, bg=Theme.BG_SURFACE, padx=12, pady=4,
                          highlightbackground=Theme.BORDER_GLASS, highlightthickness=1)
        footer.pack(fill="x", side="bottom")
        tk.Label(footer, text="⌘O Seç • ⌘R Başlat • ⌘K Temizle • Sürükle-bırak desteklenir", font=Theme.font_text(9),
                 fg=Theme.TEXT_MUTED, bg=Theme.BG_SURFACE).pack(side="left")
        self.lbl_secure = tk.Label(footer, text="🔒 Ağ bağlantısı gerektirmez", font=Theme.font_text(9),
                                   fg=Theme.TEXT_MUTED, bg=Theme.BG_SURFACE)
        self.lbl_secure.pack(side="right")

        # ------------------------------------------------------------------
        # ANA İÇERİK
        # ------------------------------------------------------------------
        main = tk.Frame(self, bg=Theme.BG_CANVAS, padx=12, pady=8)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(4, weight=1)

        # 2. Klasör + işlem butonları
        self.controls = tk.Frame(main, bg=Theme.BG_CANVAS)
        self.controls.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self.folder_var = tk.StringVar(value="")
        self.entry_wrap = tk.Frame(self.controls, bg=Theme.BG_SURFACE,
                                   highlightbackground=Theme.BORDER_GLASS, highlightthickness=1, padx=6)
        tk.Label(self.entry_wrap, text="Klasör", font=Theme.font_text(10, "bold"),
                 fg=Theme.TEXT_MUTED, bg=Theme.BG_SURFACE).pack(side="left", padx=(0, 6))
        self.entry_folder = tk.Entry(self.entry_wrap, textvariable=self.folder_var, width=1,
                                     font=Theme.font_text(11), bg=Theme.BG_SURFACE, fg=Theme.TEXT_PRIMARY,
                                     relief="flat", bd=0, highlightthickness=0,
                                     insertbackground=Theme.TEXT_PRIMARY)
        self.entry_folder.pack(side="left", fill="x", expand=True, ipady=4)

        self.btn_browse = GlassButton(self.controls, text="Seç…", variant="secondary",
                                      command=self._select_folder, padx=10, pady=4)
        self.btn_run = GlassButton(self.controls, text=RUN_BUTTON_TEXT, variant="primary",
                                   command=self._start_process, padx=12, pady=4)
        self.btn_open_folder = GlassButton(self.controls, text="Aç", variant="secondary",
                                           command=self._open_dest_folder, state="disabled", padx=10, pady=4)

        # 3. Çıktı konumu satırı
        self.out_row = tk.Frame(main, bg=Theme.BG_CANVAS)
        self.out_row.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self.out_row.columnconfigure(0, weight=1)
        out_wrap = tk.Frame(self.out_row, bg=Theme.BG_SURFACE,
                            highlightbackground=Theme.BORDER_GLASS, highlightthickness=1, padx=6)
        out_wrap.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        tk.Label(out_wrap, text="Kaydet", font=Theme.font_text(10, "bold"),
                 fg=Theme.TEXT_MUTED, bg=Theme.BG_SURFACE).pack(side="left", padx=(0, 6))
        self.entry_out = tk.Entry(out_wrap, textvariable=self.out_var, width=1,
                                  font=Theme.font_text(11), bg=Theme.BG_SURFACE, fg=Theme.TEXT_PRIMARY,
                                  relief="flat", bd=0, highlightthickness=0,
                                  insertbackground=Theme.TEXT_PRIMARY)
        self.entry_out.pack(side="left", fill="x", expand=True, ipady=4)
        self.lbl_out_hint = tk.Label(out_wrap, text="boşsa kaynağın yanına", font=Theme.font_text(9),
                                     fg=Theme.TEXT_MUTED, bg=Theme.BG_SURFACE)
        self.lbl_out_hint.pack(side="right")
        self.btn_out_browse = GlassButton(self.out_row, text="Konum…", variant="secondary",
                                          command=self._select_output_folder, padx=10, pady=4)
        self.btn_out_browse.grid(row=0, column=1)

        # 4. İstatistik kartları
        self.stats_frame = tk.Frame(main, bg=Theme.BG_CANVAS)
        self.stats_frame.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        self.card_tckn = GlassStatCard(self.stats_frame, "TCKN", "0", color=Theme.STAT_TCKN)
        self.card_telefon = GlassStatCard(self.stats_frame, "Telefon", "0", color=Theme.STAT_TEL)
        self.card_seri_no = GlassStatCard(self.stats_frame, "Seri No", "0", color=Theme.STAT_SERI)
        self.card_mrz = GlassStatCard(self.stats_frame, "MRZ", "0", color=Theme.STAT_MRZ)
        self.card_iban = GlassStatCard(self.stats_frame, "IBAN", "0", color=Theme.STAT_IBAN)
        self.card_sicil = GlassStatCard(self.stats_frame, "Sicil", "0", color=Theme.STAT_SICIL)
        self.card_adres = GlassStatCard(self.stats_frame, "Adres", "0", color=Theme.STAT_ADRES)
        self.card_files = GlassStatCard(self.stats_frame, "Dosya (OCR)", "0", color=Theme.STAT_FILES)
        self._cards = [self.card_tckn, self.card_telefon, self.card_seri_no, self.card_mrz,
                       self.card_iban, self.card_sicil, self.card_adres, self.card_files]

        # 5. Durum + ilerleme
        self.status_row = tk.Frame(main, bg=Theme.BG_CANVAS)
        self.status_row.grid(row=3, column=0, sticky="ew", pady=(0, 6))
        self.lbl_status = GlassStatusPill(
            self.status_row, text="Hazır. Klasör/dosya seçin ya da sürükleyip bırakın."
        )
        self.progress = GlassProgressBar(self.status_row, height=6, bg=Theme.BG_CANVAS)

        # 6. İşlem günlüğü
        log_panel = tk.Frame(main, bg=Theme.TERM_BG, highlightbackground=Theme.TERM_BORDER, highlightthickness=1)
        log_panel.grid(row=4, column=0, sticky="nsew")
        log_header = tk.Frame(log_panel, bg=Theme.TERM_BAR, padx=8, pady=3)
        log_header.pack(fill="x")
        self.lbl_console_title = tk.Label(log_header, text="İşlem Günlüğü", font=Theme.font_mono(9, "bold"),
                                          fg=Theme.TEXT_TERTIARY, bg=Theme.TERM_BAR)
        self.lbl_console_title.pack(side="left")
        self.btn_clear = GlassButton(log_header, text="Temizle", variant="subtle",
                                     command=self._clear_logs, padx=8, pady=1)
        self.btn_clear.pack(side="right")

        self.log_text = ScrolledText(log_panel, font=Theme.font_mono(10), bg=Theme.TERM_BG, fg=Theme.TERM_FG,
                                     relief="flat", wrap="word", bd=0, padx=10, pady=6, height=4, width=1,
                                     insertbackground="#FFFFFF")
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_configure("mask", foreground="#34D399")
        self.log_text.tag_configure("ocr", foreground="#A78BFA")
        self.log_text.tag_configure("sync", foreground="#38BDF8")
        self.log_text.tag_configure("error", foreground="#F87171")
        self.log_text.tag_configure("header", foreground="#FCD34D", font=Theme.font_mono(10, "bold"))
        self.log_text.tag_configure("info", foreground="#94A3B8")
        self.log_text.tag_configure("dim", foreground="#52525B")

        self._apply_layout("wide")
        self.bind("<Configure>", self._on_window_resize, add="+")
        # Pencere ekrana geldiğinde (ilk açılış, simge durumundan dönüş) gerçek genişliğe eşitle
        self.bind("<Map>", lambda e: self._sync_layout() if e.widget is self else None, add="+")
        self.after_idle(self._sync_layout)

    def _on_window_resize(self, event):
        """Pencere genişliği eşiği geçince düzeni değiştirir (yalnızca kök pencere olayları)."""
        if event.widget is not self:
            return
        self._sync_layout(event.width)

    def _sync_layout(self, width: Optional[int] = None):
        """
        Düzeni gerçek pencere genişliğine eşitler. Pencere henüz çizilmemişken gelen
        1 px'lik geçici ölçüler yok sayılır; aksi halde 760 px pencere dar düzende kalabilir.
        """
        try:
            if width is None:
                width = self.winfo_width()
        except tk.TclError:
            return
        if width <= 1:
            return
        mode = "narrow" if width < self.NARROW_BREAKPOINT else "wide"
        if mode != self._layout_mode:
            self._apply_layout(mode)

    def _apply_layout(self, mode: str):
        """'wide' veya 'narrow' düzenini uygular; aynı widget'lar yeniden yerleştirilir."""
        self._layout_mode = mode
        narrow = mode == "narrow"

        # Klasör / buton satırı
        for w in (self.entry_wrap, self.btn_browse, self.btn_run, self.btn_open_folder):
            w.grid_forget()
        for c in range(4):
            self.controls.columnconfigure(c, weight=0)
        self.controls.columnconfigure(0, weight=1)
        if narrow:
            self.entry_wrap.grid(row=0, column=0, sticky="ew", padx=(0, 6))
            self.btn_browse.grid(row=0, column=1, sticky="ew")
            self.btn_run.grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=(6, 0))
            self.btn_open_folder.grid(row=1, column=1, sticky="ew", pady=(6, 0))
        else:
            self.entry_wrap.grid(row=0, column=0, sticky="ew", padx=(0, 6))
            self.btn_browse.grid(row=0, column=1, padx=(0, 6))
            self.btn_run.grid(row=0, column=2, padx=(0, 6))
            self.btn_open_folder.grid(row=0, column=3)

        # İstatistik ızgarası: geniş 8x1, dar 4x2
        cols = 4 if narrow else 8
        for c in range(8):
            self.stats_frame.columnconfigure(c, weight=0, uniform="")
        for c in range(cols):
            self.stats_frame.columnconfigure(c, weight=1, uniform="stat")
        for i, card in enumerate(self._cards):
            r, c = divmod(i, cols)
            card.grid(row=r, column=c, sticky="ew",
                      padx=(0 if c == 0 else 2, 0 if c == cols - 1 else 2), pady=(0 if r == 0 else 4, 0))

        # Durum satırı: geniş yan yana, dar alt alta
        self.lbl_status.grid_forget()
        self.progress.grid_forget()
        self.status_row.columnconfigure(0, weight=1, uniform="")
        self.status_row.columnconfigure(1, weight=0, uniform="")
        if narrow:
            self.lbl_status.grid(row=0, column=0, sticky="ew")
            self.progress.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        else:
            self.status_row.columnconfigure(0, weight=3, uniform="st")
            self.status_row.columnconfigure(1, weight=2, uniform="st")
            self.lbl_status.grid(row=0, column=0, sticky="ew", padx=(0, 8))
            self.progress.grid(row=0, column=1, sticky="ew")

        # İkincil metinler yalnızca geniş düzende
        if narrow:
            self.lbl_subtitle.grid_remove()
            self.lbl_secure.pack_forget()
        else:
            self.lbl_subtitle.grid()
            if not self.lbl_secure.winfo_ismapped():
                self.lbl_secure.pack(side="right")

    # ==========================================================================
    # İŞLEVSEL METOTLAR
    # ==========================================================================

    def _select_folder(self):
        folder = filedialog.askdirectory(title="UYAP Dava Klasörünü Seçin")
        if folder:
            self._set_sources([folder])
            self._log(f"📁 Kaynak klasör seçildi: {folder}\n")
            self.lbl_status.config(text=f"Klasör hazır: {os.path.basename(folder)}")

    def _select_output_folder(self):
        folder = filedialog.askdirectory(title="Maskelenmiş Klasörün Kaydedileceği Konumu Seçin")
        if folder:
            self.out_var.set(folder)
            self._log(f"💾 Çıktı konumu: {folder}\n")

    def _set_sources(self, paths):
        """Kaynak listesini ayarlar ve girdi kutusunu günceller."""
        self.sources = list(paths)
        if len(self.sources) == 1:
            text = self.sources[0]
        else:
            text = f"{len(self.sources)} öğe seçildi"
        self._sources_display = text
        self.folder_var.set(text)

    def _setup_dnd(self):
        """Pencerenin TÜM alt bileşenlerini bırakma hedefi yapar (yalnızca kök kayıtlıysa bazı alanlar bırakmayı almaz)."""
        if not DND_AVAILABLE:
            return

        def register(w):
            try:
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass
            for c in w.winfo_children():
                register(c)

        register(self)

    def _on_drop(self, event):
        if self.is_running:
            return "copy"
        try:
            raw = list(self.tk.splitlist(event.data))
            paths = []
            for p in raw:
                if p.startswith("file://"):
                    p = urllib.parse.unquote(urllib.parse.urlparse(p).path)
                if os.path.exists(p):
                    paths.append(p)
            if not paths:
                self._log(f"⚠️ Bırakılan öğe okunamadı: {event.data!r}\n")
                return "copy"
            self._set_sources(paths)
            self._log(f"📥 Sürükle-bırak: {len(paths)} öğe alındı\n")
            self.lbl_status.config(text=f"{len(paths)} öğe hazır. Başlat'a tıklayın.")
        except Exception as e:
            self._log(f"⚠️ Sürükle-bırak hatası: {e}\n")
        return "copy"

    def _resolve_sources(self):
        """Geçerli kaynak yollarının listesini döndürür (girdi kutusu elle düzenlendiyse onu esas alır)."""
        typed = self.folder_var.get().strip().strip("'\"").strip()
        if typed != self._sources_display or not self.sources:
            self.sources = [os.path.expanduser(typed)] if typed else []
        return [p for p in self.sources if os.path.isdir(p) or os.path.isfile(p)]

    @staticmethod
    def _stage_sources(srcs):
        """
        Tek klasör doğrudan işlenir. Dosyalar / birden çok öğe için geçici bir hazırlık klasörüne
        KOPYALANIR (orijinallere dokunulmaz). (klasör, ad, geçici_kök) döndürür.
        """
        if len(srcs) == 1 and os.path.isdir(srcs[0]):
            return srcs[0], None, None
        base = os.path.splitext(os.path.basename(srcs[0]))[0] if len(srcs) == 1 else "Seçilen Evraklar"
        stage_root = tempfile.mkdtemp(prefix="uyap_maske_")
        stage = os.path.join(stage_root, base)
        os.makedirs(stage)
        for p in srcs:
            name = os.path.basename(p.rstrip(os.sep))
            target, n = os.path.join(stage, name), 1
            while os.path.exists(target):
                stem, ext = os.path.splitext(name)
                target = os.path.join(stage, f"{stem} ({n}){ext}")
                n += 1
            if os.path.isdir(p):
                shutil.copytree(p, target)
            else:
                shutil.copy2(p, target)
        return stage, base, stage_root

    def _open_dest_folder(self):
        if self.last_dest_folder and os.path.exists(self.last_dest_folder):
            subprocess.run(["open", self.last_dest_folder])
        else:
            messagebox.showinfo("Bilgi", "Oluşturulmuş izole temiz klasör bulunamadı.")

    def _log(self, text, autoscroll: bool = True):
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
        if autoscroll:
            self.log_text.see(tk.END)

    def _clear_logs(self):
        self.log_text.delete("1.0", tk.END)

    def _check_queue(self):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return

        # Bekleyen önceki döngü varsa temizle
        if hasattr(self, "_queue_job") and self._queue_job:
            try:
                self.after_cancel(self._queue_job)
            except Exception:
                pass
            self._queue_job = None

        has_new_log = False
        try:
            while True:
                msg_type, payload = self.msg_queue.get_nowait()
                if msg_type == "log":
                    self._log(payload, autoscroll=False)
                    has_new_log = True
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
                    udf_cnt = payload.get("udf_converted", 0)
                    office_cnt = payload.get("office_converted", 0)
                    ocr_cnt = payload.get("ocr_converted", 0)
                    self.card_files.update_value(f"{md_cnt} ({udf_cnt} UDF, {office_cnt} Office, {ocr_cnt} OCR)")
                elif msg_type == "done":
                    self.is_running = False
                    self.btn_run.config(state="normal", text=RUN_BUTTON_TEXT)
                    self.btn_open_folder.config(state="normal")
                    summary_text, dest_f = payload if isinstance(payload, tuple) else (payload, self.last_dest_folder)
                    res = messagebox.askyesno(
                        "İşlem Başarıyla Tamamlandı",
                        f"{summary_text}\n\nOluşturulan izole temiz klasörü Finder'da açmak ister misiniz?"
                    )
                    if res and dest_f and os.path.exists(dest_f):
                        subprocess.run(["open", dest_f])
                elif msg_type == "no_documents":
                    self.is_running = False
                    self.btn_run.config(state="normal", text=RUN_BUTTON_TEXT)
                    no_doc_msg, _dest_f = payload if isinstance(payload, tuple) else (payload, self.last_dest_folder)
                    messagebox.showwarning("Belge Bulunamadı", no_doc_msg)
                elif msg_type == "error":
                    self.is_running = False
                    self.btn_run.config(state="normal", text=RUN_BUTTON_TEXT)
                    messagebox.showerror("Hata Oluştu", payload)
                elif msg_type == "update_available":
                    info, manual = payload
                    self.pending_update_info = info
                    new_ver = info.get("version", "")
                    self.btn_update.config(
                        state="normal",
                        text=f"✨ Yeni Sürüm İndir (v{new_ver})"
                    )
                    self._log(
                        f"✨ [GÜNCELLEME] Yeni sürüm yayınlandı: v{new_ver} "
                        f"(Mevcut: v{APP_VERSION}) — Tek tıkla güncellemeye hazır.\n"
                    )
                    self._prompt_and_install_update(info)
                elif msg_type == "update_up_to_date":
                    manual = payload
                    self.btn_update.config(
                        state="normal",
                        text=f"✅ v{APP_VERSION} • Güncel"
                    )
                    if manual:
                        messagebox.showinfo(
                            "Sürüm Güncel",
                            f"UYAP Maskeleme uygulamasının en güncel sürümünü (v{APP_VERSION}) kullanıyorsunuz."
                        )
                elif msg_type == "update_check_error":
                    err_str, manual = payload
                    self.btn_update.config(
                        state="normal",
                        text=f"v{APP_VERSION} • Güncelle"
                    )
                    if manual:
                        if "CERTIFICATE_VERIFY_FAILED" in str(err_str):
                            msg_text = (
                                "Kurumsal ağ güvenlik duvarı veya antivirüs SSL sertifika denetimi algılandı.\n\n"
                                "Yeni sürümü web tarayıcınızdan doğrudan indirebilirsiniz:\n"
                                f"https://github.com/{GITHUB_REPO}/releases/latest"
                            )
                        else:
                            msg_text = (
                                "Güncelleme kontrolü için internet bağlantısı kurulamadı.\n\n"
                                "Not: UYAP Maskeleme motoru çevrimdışı (offline) çalışmaya devam etmektedir."
                            )
                        messagebox.showwarning(
                            "Güncelleme Sunucusuna Ulaşılamadı",
                            msg_text
                        )
                elif msg_type == "update_ready_restart":
                    target_app = payload
                    self.lbl_status.config(text="Güncelleme tamamlandı, yeni sürüm başlatılıyor...")
                    self.after(250, self.destroy)
                elif msg_type == "update_install_error":
                    self.is_running = False
                    self.btn_run.config(state="normal", text=RUN_BUTTON_TEXT)
                    self.btn_update.config(state="normal")
                    messagebox.showerror(
                        "Güncelleme Hatası",
                        f"Otomatik güncelleme sırasında bir sorun oluştu:\n{payload}"
                    )
        except queue.Empty:
            pass
        except (tk.TclError, Exception):
            return

        if has_new_log:
            try:
                self.log_text.see(tk.END)
            except (tk.TclError, Exception):
                pass

        try:
            if self.winfo_exists():
                self._queue_job = self.after(100, self._check_queue)
        except (tk.TclError, Exception):
            self._queue_job = None

    def destroy(self):
        """Uygulama kapatılırken bekleyen timer ve pulse işlerini temizle."""
        if hasattr(self, "_update_check_job") and self._update_check_job:
            try:
                self.after_cancel(self._update_check_job)
            except Exception:
                pass
            self._update_check_job = None
        if hasattr(self, "_queue_job") and self._queue_job:
            try:
                self.after_cancel(self._queue_job)
            except Exception:
                pass
            self._queue_job = None
        if hasattr(self, "lbl_status") and hasattr(self.lbl_status, "stop_pulse"):
            self.lbl_status.stop_pulse()
        super().destroy()

    def _on_update_button_click(self):
        """Üst bardaki güncelleme butonuna tıklandığında çalışır."""
        if self.is_running:
            return
        if self.pending_update_info:
            self._prompt_and_install_update(self.pending_update_info)
        else:
            self._check_updates(manual=True)

    def _check_updates(self, manual: bool = False):
        """GitHub Releases üzerinden yeni sürüm kontrolünü arka planda çalıştırır."""
        if self.is_running:
            return
        if manual:
            self.btn_update.config(state="disabled", text="⏳ Denetleniyor...")

        def _check_worker():
            try:
                info = AutoUpdater.check_for_updates(APP_VERSION)
                if info:
                    self.msg_queue.put(("update_available", (info, manual)))
                else:
                    self.msg_queue.put(("update_up_to_date", manual))
            except Exception as e:
                self.msg_queue.put(("update_check_error", (str(e), manual)))

        threading.Thread(target=_check_worker, daemon=True).start()

    def _prompt_and_install_update(self, info: Dict):
        """Kullanıcıya yeni sürüm onay penceresi gösterir ve onaylanırsa tek tıkla günceller."""
        if self.is_running:
            return
        new_ver = info.get("version", "")
        notes = (info.get("release_notes") or "").strip()
        if len(notes) > 420:
            notes = notes[:420].rstrip() + "..."

        ask = messagebox.askyesno(
            "Yeni Güncelleme Mevcut",
            f"UYAP Maskeleme uygulamasının yeni bir sürümü yayınlandı!\n\n"
            f"• Mevcut Sürüm: v{APP_VERSION}\n"
            f"• Yeni Sürüm: v{new_ver}\n\n"
            f"Yenilikler:\n{notes}\n\n"
            f"Baştan kurulum yapmadan tek tıkla otomatik güncellensin ve yeniden başlatılsın mı?"
        )
        if not ask:
            return

        self.is_running = True
        self.btn_run.config(state="disabled", text="Güncelleniyor...")
        self.btn_update.config(state="disabled", text="⬇️ İndiriliyor...")
        self.progress["value"] = 0
        self.lbl_status.config(text=f"v{new_ver} güncellemesi indiriliyor...")
        self._log(f"\n⬇️ [GÜNCELLEME] v{new_ver} paketi indiriliyor ve yerinde kuruluyor...\n")

        threading.Thread(target=self._install_update_worker, args=(info,), daemon=True).start()

    def _install_update_worker(self, info: Dict):
        """DMG indirme, bağlama ve yerinde yenileme işlemini arka planda yürütür."""
        download_url = info["download_url"]
        fallback_total = info.get("size", 0) or 26_000_000

        def on_progress(downloaded: int, total: int):
            tot = total if total > 0 else fallback_total
            pct = min(100, int((downloaded / max(tot, 1)) * 100))
            mb_done = downloaded / (1024 * 1024)
            mb_tot = tot / (1024 * 1024)
            self.msg_queue.put(("progress", (pct, 100)))
            self.msg_queue.put((
                "status",
                f"⬇️ Güncelleme indiriliyor: %{pct} ({mb_done:.1f} MB / {mb_tot:.1f} MB)"
            ))

        try:
            target_app = AutoUpdater.download_and_install(download_url, progress_cb=on_progress)
            self.msg_queue.put(("progress", (100, 100)))
            self.msg_queue.put((
                "log",
                f"✅ [GÜNCELLEME] Yeni sürüm hazır ({target_app}). Uygulama yeniden başlatılıyor...\n"
            ))
            self.msg_queue.put(("update_ready_restart", target_app))
        except Exception as e:
            self.msg_queue.put(("log", f"❌ [HATA] Güncelleme başarısız: {e}\n"))
            self.msg_queue.put(("update_install_error", str(e)))

    def _start_process(self):
        if self.is_running:
            return
        folder = self.folder_var.get().strip().strip("'\"").strip()
        if folder:
            folder = os.path.expanduser(folder)
        if folder != self.folder_var.get():
            self.folder_var.set(folder)
        srcs = self._resolve_sources()
        if not srcs:
            messagebox.showwarning("Geçersiz Kaynak", "Lütfen geçerli bir UYAP dava klasörü seçin veya dosya/klasör sürükleyip bırakın.")
            return
        out_parent = os.path.expanduser(self.out_var.get().strip().strip("'\"").strip()) or None
        if out_parent and not os.path.isdir(out_parent):
            messagebox.showwarning("Geçersiz Çıktı Konumu", "Seçilen kaydetme konumu bulunamadı. Lütfen mevcut bir klasör seçin.")
            return

        if len(srcs) == 1 and unicodedata.normalize("NFC", folder.rstrip("/\\")).endswith("(Maskelenmis AI)"):
            proceed = messagebox.askyesno(
                "Zaten Maskelenmiş Klasör",
                "Seçtiğiniz klasör daha önce üretilmiş bir '(Maskelenmis AI)' çıktı klasörüne benziyor.\n\n"
                "Orijinal UDF/PDF/TIFF dosyalarını içeren ana dava klasörünü seçmeniz önerilir.\n"
                "Yine de bu klasör üzerinde işlem yapmak istiyor musunuz?"
            )
            if not proceed:
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

        thread = threading.Thread(target=self._worker, args=(srcs[0] if len(srcs) == 1 and os.path.isdir(srcs[0]) else srcs, out_parent), daemon=True)
        thread.start()

    def _worker(self, folder, out_parent=None):
        start_time = time.time()
        stage_root = None
        dest_arg = None
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
            if isinstance(folder, (list, tuple)):
                self.msg_queue.put(("status", "Seçilen öğeler hazırlanıyor..."))
                folder, base, stage_root = self._stage_sources(list(folder))
            if out_parent:
                name = os.path.basename(os.path.abspath(folder).rstrip(os.sep))
                if not unicodedata.normalize("NFC", name).endswith("(Maskelenmis AI)"):
                    name += " (Maskelenmis AI)"
                dest_arg = os.path.join(out_parent, name)
            if dest_arg:
                dest_folder, final_stats = UyapRedactor.export_isolated_clean_folder(
                    folder, dest_arg, progress_cb=progress_cb)
            elif stage_root:
                # Hazırlık klasörü geçici olduğundan varsayılan çıktı ilk kaynağın yanına yazılır
                first = self.sources[0] if self.sources else folder
                dest_arg = os.path.join(os.path.dirname(os.path.abspath(first)),
                                        os.path.basename(folder) + " (Maskelenmis AI)")
                dest_folder, final_stats = UyapRedactor.export_isolated_clean_folder(
                    folder, dest_arg, progress_cb=progress_cb)
            else:
                dest_folder, final_stats = UyapRedactor.export_isolated_clean_folder(folder, progress_cb=progress_cb)
            self.last_dest_folder = dest_folder
            elapsed = time.time() - start_time

            self.msg_queue.put(("progress", (100, 100)))
            self.msg_queue.put(("stats", final_stats))

            unprocessed = final_stats.get("unprocessed") or []
            if unprocessed:
                unproc_logs = "".join(f"⚠️ [İŞLENEMEDİ] {rel_p} — {reason}\n" for rel_p, reason in unprocessed)
                self.msg_queue.put(("log", unproc_logs))

            if final_stats.get("warning_no_documents"):
                no_doc_msg = (
                    "Seçilen klasörde işlenebilir belge bulunamadı.\n\n"
                    "Desteklenen türler: .udf, .pdf, .doc/.docx, .xlsx, .eyp, .zip, .tif/.tiff, .jpg/.png/.heic, .md, .txt\n\n"
                    "Lütfen doğru dava klasörünü seçtiğinizden emin olun."
                )
                self.msg_queue.put(("log", f"\n⚠️ {no_doc_msg}\n"))
                self.msg_queue.put(("status", "İşlenebilir belge bulunamadı."))
                self.msg_queue.put(("no_documents", (no_doc_msg, dest_folder)))
            else:
                unproc_line = f"⚠️ İşlenemeyen dosya: {len(unprocessed)} (liste raporda)\n" if unprocessed else ""
                summary_msg = (
                    f"Maskeli klasör oluşturuldu ({elapsed:.1f} sn).\n\n"
                    f"📂 Hedef Klasör: {os.path.basename(dest_folder)}\n"
                    f"📄 Aktarılan .md Belgesi: {final_stats.get('md_transferred', 0)} adet\n"
                    f"📝 UDF'den Metne Dökülen: {final_stats.get('udf_converted', 0)} adet\n"
                    f"💼 Word/Excel Belgesi: {final_stats.get('office_converted', 0)} adet\n"
                    f"📦 Açılan EYP/ZIP Arşivi: {final_stats.get('archive_count', 0)} adet\n"
                    f"👁️ Yerel OCR ile Çözülen Taranmış Ek: {final_stats.get('ocr_converted', 0)} adet\n"
                    f"🔄 İndeks Senkronizasyonu: {final_stats.get('index_synced', 0)} satır güncellendi\n"
                    f"{unproc_line}\n"
                    f"🔒 Gizlenen Kişisel Veriler (Toplam: {final_stats.get('total', 0)}):\n"
                    f"  • TCKN: {final_stats.get('tckn', 0)}\n"
                    f"  • Cep Telefonu: {final_stats.get('telefon', 0)}\n"
                    f"  • Kimlik Seri No: {final_stats.get('seri_no', 0)}\n"
                    f"  • Kimlik MRZ Kodu: {final_stats.get('mrz', 0)}\n"
                    f"  • IBAN / Kart: {final_stats.get('iban', 0)}\n"
                    f"  • Hesap / Müşteri No: {final_stats.get('hesap', 0)}\n"
                    f"  • Sicil No: {final_stats.get('sicil', 0)}\n"
                    f"  • Açık Adres: {final_stats.get('adres', 0)}\n\n"
                    f"✅ Bu klasöre orijinal UDF, PDF, TIFF dosyası aktarılmadı.\n"
                    f"ℹ️ Aynı numaralı etiket = aynı değer. Otomatik maskeleme hatasız değildir; paylaşmadan önce\n"
                    f"   klasördeki DAVA_DÖNÜŞÜM_VE_GÜVENLİK_RAPORU.md dosyasına ve OCR uyarılarına göz atın.\n"
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
        finally:
            if stage_root:
                shutil.rmtree(stage_root, ignore_errors=True)


if __name__ == "__main__":
    app = UyapRedactorApp()
    app.mainloop()
