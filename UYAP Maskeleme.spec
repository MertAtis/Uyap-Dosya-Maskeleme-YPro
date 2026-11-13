# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

_dnd_datas = collect_data_files('tkinterdnd2')


a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=[],
    datas=[('uyap_redactor.py', '.')] + _dnd_datas,
    hiddenimports=['tkinterdnd2', 'tkinter', 'tkinter.ttk', 'tkinter.filedialog', 'tkinter.messagebox', 'tkinter.scrolledtext', 'urllib.request', 'urllib.error', 'json', 'ssl', 'Vision', 'Cocoa', 'AppKit', 'Foundation', 'Quartz', 'objc', 'fitz', 'PIL'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'qtpy',
        'matplotlib', 'scipy', 'pandas', 'numpy', 'openblas', 'IPython', 'jupyter',
        'sphinx', 'tornado', 'notebook', 'nbformat', 'nbconvert',
        'docutils', 'lxml', 'zmq', 'black', 'yapf', 'pytest'
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='UYAP Maskeleme',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['bundle/app.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='UYAP Maskeleme',
)
app = BUNDLE(
    coll,
    name='UYAP Maskeleme.app',
    icon='bundle/app.icns',
    bundle_identifier='com.yargipro.uyapredactor',
    info_plist={
        'CFBundleDisplayName': 'UYAP Maskeleme',
        'CFBundleName': 'UYAP Maskeleme',
        'CFBundleShortVersionString': '1.4.2',
        'CFBundleVersion': '11',
        'LSMinimumSystemVersion': '12.0',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': True,
    }
)
