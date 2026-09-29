# FluentTaleClient.spec
# -*- mode: python ; coding: utf-8 -*-
"""
发布版：console=False，无黑框，日志被 _safe_print 静默丢弃
"""
import os
from PyInstaller.utils.hooks import collect_all

# qfluentwidgets 及 qframelesswindow 的资源
qf_datas, qf_bins, qf_hidden = collect_all('qfluentwidgets')
fw_datas, fw_bins, fw_hidden = collect_all('qframelesswindow')

# 递归收集 plugins/ 下的所有文件（保留相对结构）
_plugin_datas = []
for _root, _dirs, _files in os.walk('plugins'):
    for _f in _files:
        _src = os.path.join(_root, _f)
        _plugin_datas.append((_src, _root))

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=qf_bins + fw_bins,
    datas=qf_datas + fw_datas + [
        ('content', 'content'),
        ('qss', 'qss'),
        ('images', 'images'),
        ('config', 'config'),
    ] + _plugin_datas,
    hiddenimports=(
        qf_hidden + fw_hidden
        + [
            'PySide6.QtSvg',
            'PySide6.QtSvgWidgets',
            'win32crypt',
            'pyotp',
            'qrcode',
            'tqdm',
            'login_questions',
            'concurrent',
            'concurrent.futures',
            'concurrent.futures.thread',
        ]
    ),
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # ── 大块头，项目用不到 ──
        'scipy',
        'scipy.sparse',
        'scipy.spatial',
        'scipy.linalg',
        'scipy.optimize',
        'scipy.signal',
        'scipy.ndimage',
        'scipy.stats',
        'pandas',
        'matplotlib',
        'sklearn',
        'sympy',
        'IPython',
        'notebook',
        'jupyter',

        # ── Qt 绑定：只留 PySide6 ──
        'PyQt5',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PyQt5.QtSvg',
        'PyQt5.sip',
        'PyQt6',
        'PySide2',

        # ── Qt 用不到的大模块 ──
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineQuick',
        'PySide6.QtWebChannel',
        'PySide6.QtWebSockets',
        'PySide6.QtQuick',
        'PySide6.QtQuick3D',
        'PySide6.QtQuickWidgets',
        'PySide6.QtQml',
        'PySide6.QtQmlModels',
        'PySide6.QtCharts',
        'PySide6.QtDataVisualization',
        'PySide6.QtGraphs',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DRender',
        'PySide6.Qt3DInput',
        'PySide6.Qt3DLogic',
        'PySide6.Qt3DAnimation',
        'PySide6.Qt3DExtras',
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
        'PySide6.QtDesigner',
        'PySide6.QtHelp',
        'PySide6.QtTest',
        'PySide6.QtSql',
        'PySide6.QtBluetooth',
        'PySide6.QtNfc',
        'PySide6.QtPositioning',
        'PySide6.QtSerialPort',
        'PySide6.QtRemoteObjects',
        'PySide6.QtScxml',
        'PySide6.QtSensors',
        'PySide6.QtSpatialAudio',
        'PySide6.QtStateMachine',
        'PySide6.QtTextToSpeech',

        # ── 标准库用不到的 ──
        'tkinter',
        'unittest',
        'pydoc',
        'doctest',
        'distutils',
        'setuptools',
        'pip',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FluentTaleClient',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                    # ← 发布版：无黑框
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='images/ftclogo.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FluentTaleClient',
)