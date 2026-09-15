# -*- mode: python ; coding: utf-8 -*-
#
# Bündelt die Bridge zu einer einzigen EXE.
#
# Zwei Dinge, die leicht übersehen werden:
#
# 1. assets/ muss mit hinein. Die Symbol-Dateien werden zur Laufzeit aus einer
#    Datei geladen (LoadImageW braucht einen Pfad) – ohne sie hätte die EXE
#    kein Fenstersymbol und die Bridge kein Symbol im Infobereich.
# 2. icon= setzt das Symbol der EXE selbst; davon zehren Startmenü,
#    Desktop-Verknüpfung und Taskleiste.

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('help.html', '.'), ('assets', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ChurchToolsBridge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app.ico',
)