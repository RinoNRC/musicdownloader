import hashlib
import json
import os
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path


_RUSSIAN = dict(zip(
    'абвгдеёжзийклмнопрстуфхцчшщъыьэюя',
    ['a', 'b', 'v', 'g', 'd', 'e', 'io', 'zh', 'z', 'i', 'i', 'k', 'l', 'm', 'n', 'o', 'p', 'r', 's', 't', 'u', 'f', 'kh', 'ts', 'ch', 'sh', 'shch', '', 'y', '', 'e', 'iu', 'ia'],
))


def transliterate(text):
    import unicodedata

    result = ''.join(_RUSSIAN.get(char.lower(), char).capitalize() if char.isupper() and char.lower() in _RUSSIAN
                     else _RUSSIAN.get(char, char) for char in text)
    return unicodedata.normalize('NFKD', result).encode('ascii', 'ignore').decode('ascii')


def get_ffmpeg(cancel=None, progress=None):
    def check_cancelled():
        if cancel is not None and cancel.is_set():
            from music_core import Cancelled
            raise Cancelled()

    check_cancelled()
    if not getattr(sys, 'frozen', False):
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    manifest = json.loads((Path(__file__).parent / 'ffmpeg-download.json').read_text(encoding='utf-8'))
    configured = os.environ.get('IMAGEIO_FFMPEG_EXE')
    if configured and Path(configured).is_file():
        return configured
    cache = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'MusicDownloader' / 'tools'
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / manifest['filename']
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == manifest['exe_sha256']:
        return str(target)
    if not (cache / 'download-consent').is_file():
        raise RuntimeError('Не подтверждена загрузка FFmpeg.')
    if progress:
        progress(0, 'Первая загрузка: установка FFmpeg с PyPI…')
    with tempfile.TemporaryDirectory(prefix='musicdrive-ffmpeg-') as temporary:
        wheel = Path(temporary) / 'ffmpeg.whl'
        request = urllib.request.Request(manifest['url'], headers={'User-Agent': 'MusicDrive/1.0'})
        with urllib.request.urlopen(request, timeout=30) as response, wheel.open('wb') as output:
            size = 0
            while chunk := response.read(1024 * 1024):
                check_cancelled()
                size += len(chunk)
                if size > 100 * 1024 * 1024:
                    raise RuntimeError('Пакет FFmpeg превышает допустимый размер.')
                output.write(chunk)
        if hashlib.sha256(wheel.read_bytes()).hexdigest() != manifest['wheel_sha256']:
            raise RuntimeError('Не совпала контрольная сумма FFmpeg. Повторите скачивание.')
        with zipfile.ZipFile(wheel) as package:
            data = package.read('imageio_ffmpeg/binaries/' + manifest['filename'])
        if hashlib.sha256(data).hexdigest() != manifest['exe_sha256']:
            raise RuntimeError('Повреждён исполняемый файл FFmpeg.')
        check_cancelled()
        partial = cache / (manifest['filename'] + '.tmp')
        try:
            partial.write_bytes(data)
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
    return str(target)
