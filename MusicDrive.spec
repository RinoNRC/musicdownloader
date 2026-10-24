from PyInstaller.utils.hooks import collect_all, collect_submodules

webview_data, webview_bins, webview_imports = collect_all('webview')
yt_data, yt_bins, yt_imports = collect_all('yt_dlp')

common_hidden = yt_imports + collect_submodules('yt_dlp_ejs')
common_excludes = ['tkinter', 'customtkinter', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'matplotlib', 'numpy', 'PIL', 'mutagen', 'unidecode', 'imageio_ffmpeg']

app = Analysis(
    ['main.py'],
    pathex=[SPECPATH],
    binaries=webview_bins + yt_bins,
    datas=[('web', 'web'), ('ffmpeg-download.json', '.')] + webview_data + yt_data,
    hiddenimports=webview_imports + common_hidden + ['webview.platforms.edgechromium', 'webview.platforms.winforms'],
    hookspath=[],
    excludes=common_excludes,
    noarchive=False,
)
worker = Analysis(
    ['download_worker.py'],
    pathex=[SPECPATH],
    binaries=yt_bins,
    datas=yt_data + [('ffmpeg-download.json', '.')],
    hiddenimports=common_hidden,
    hookspath=[],
    excludes=common_excludes + ['webview'],
    noarchive=False,
)

# The console worker uses redirected stdio for its JSON protocol; only the GUI is windowed.
app_pyz = PYZ(app.pure)
worker_pyz = PYZ(worker.pure)
app_exe = EXE(
    app_pyz, app.scripts, [], exclude_binaries=True, name='MusicDrive',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False,
)
worker_exe = EXE(
    worker_pyz, worker.scripts, [], exclude_binaries=True, name='MusicDriveWorker',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=True,
)
collection = COLLECT(
    app_exe, worker_exe, app.binaries, worker.binaries, app.datas, worker.datas,
    strip=False, upx=False, name='MusicDrive',
)
