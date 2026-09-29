# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys

root = Path(SPECPATH)
a = Analysis(
    [str(root / 'desktop_entry.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'lab.html'), '.'), (str(root / 'chess.html'), '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
if sys.platform == 'darwin':
    exe = EXE(
        pyz, a.scripts, [], exclude_binaries=True,
        name='小果', debug=False, strip=False, upx=False, console=False,
        argv_emulation=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='小果')
    app = BUNDLE(
        coll, name='小果.app', bundle_identifier='io.github.wanghao9103.xiaoguo',
        info_plist={'NSHighResolutionCapable': True, 'CFBundleDisplayName': '小果'},
    )
else:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name='小果', debug=False, bootloader_ignore_signals=False,
        strip=False, upx=False, console=False,
    )
