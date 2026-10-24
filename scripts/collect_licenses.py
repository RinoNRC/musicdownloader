"""Collect third-party notices using the Python environment that built MusicDrive."""

import argparse
import hashlib
import html
import importlib.metadata
import json
import re
import sys
import urllib.request
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'customtkinter', 'darkdetect', 'imageio-ffmpeg', 'unidecode', 'mutagen'}
WEBVIEW_VERSION = '1.0.3856.49'
WEBVIEW_URL = f'https://www.nuget.org/packages/Microsoft.Web.WebView2/{WEBVIEW_VERSION}/License'
PROXY_URL = (
    'https://raw.githubusercontent.com/jtushman/proxy_tools/'
    'ccd35a569b95bec271a59890780c7821756c548a/LICENSE.txt'
)


def normalized(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'MusicDrive-license-collector/1.0'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def upstream_license(dest, relative, url, expected_hash, extract_html=False):
    cached = dest / relative
    if cached.is_file() and digest(cached.read_bytes()) == expected_hash:
        return cached.read_bytes()
    data = fetch(url)
    if extract_html:
        match = re.search(
            r'<pre\b[^>]*class="license-file-contents[^\"]*"[^>]*>(.*?)</pre>',
            data.decode('utf-8'), re.DOTALL,
        )
        if not match:
            raise RuntimeError(f'Cannot find the license text at {url}')
        data = (html.unescape(match.group(1)).replace('\r\n', '\n').strip() + '\n').encode('utf-8')
    if digest(data) != expected_hash:
        raise RuntimeError(f'Upstream license changed; review it before updating its hash: {url}')
    return data


def license_path(path):
    parts = PurePosixPath(str(path)).parts
    if not parts or not parts[0].lower().endswith('.dist-info'):
        return None
    relative = PurePosixPath(*parts[1:])
    if '..' in relative.parts or relative.is_absolute():
        raise RuntimeError(f'Unsafe metadata path: {path}')
    if re.match(r'^(licen[cs]e|authors?|notice|copying)([._-]|$)', relative.name, re.I):
        return relative
    if any(part.lower() == 'licenses' for part in relative.parts[:-1]):
        return relative
    return None


def collect(dest):
    contents = {}
    components = []
    excluded = []

    def add(component, relative, data, source, title=None):
        if relative in contents:
            raise RuntimeError(f'Duplicate output path: {relative}')
        contents[relative] = data
        component['files'].append({
            'path': relative,
            'title': title or PurePosixPath(relative).name,
            'source': source,
            'sha256': digest(data),
        })

    distributions = sorted(
        importlib.metadata.distributions(),
        key=lambda dist: (normalized(dist.metadata['Name']), dist.version),
    )
    for dist in distributions:
        name = dist.metadata['Name']
        key = normalized(name)
        if key in EXCLUDED:
            excluded.append({'name': name, 'version': dist.version, 'reason': 'Not bundled'})
            continue
        component = {
            'name': name,
            'version': dist.version,
            'scope': 'Installed build environment; not proof of inclusion in the application',
            'license_metadata': dist.metadata.get('License-Expression') or dist.metadata.get('License'),
            'project_urls': sorted(dist.metadata.get_all('Project-URL') or []),
            'files': [],
        }
        for path in sorted(dist.files or [], key=str):
            relative = license_path(path)
            if relative is not None:
                add(component, f'{key}/{relative.as_posix()}', dist.locate_file(path).read_bytes(), str(path))
        if key == 'proxy-tools':
            relative = f'{key}/upstream-LICENSE.txt'
            data = upstream_license(
                dest, relative, PROXY_URL,
                'a428fb8a2e762af3eb0a6edbbb88e9b42ccfee80fd9b423958bcacf9b9abbfe4',
            )
            add(component, relative, data, PROXY_URL, 'Upstream BSD license (metadata says MIT)')
        if key == 'yt-dlp-ejs':
            libraries = [path for path in dist.files or [] if str(path).endswith('/lib.min.js')]
            if not libraries:
                raise RuntimeError('yt-dlp-ejs lib.min.js is missing; its dependency notices are required')
            for path in sorted(libraries, key=str):
                data = dist.locate_file(path).read_bytes()
                if not data.startswith(b'/*!') or b'Bundled Dependencies:' not in data.split(b'*/', 1)[0]:
                    raise RuntimeError(f'Cannot locate bundled dependency notices in {path}')
                header = data.split(b'*/', 1)[0] + b'*/\n'
                add(component, f'{key}/{path}.NOTICE.txt', header, str(path),
                    'Complete license header, including bundled JavaScript dependency notices')
        if key == 'certifi':
            metadata_url = f'https://pypi.org/pypi/certifi/{dist.version}/json'
            metadata = json.loads(fetch(metadata_url))
            sources = sorted(
                (item for item in metadata['urls'] if item['packagetype'] == 'sdist'),
                key=lambda item: item['filename'],
            )
            if not sources:
                raise RuntimeError(f'No certifi source archive listed at {metadata_url}')
            component['source_archives'] = [
                {'url': item['url'], 'sha256': item['digests']['sha256']} for item in sources
            ]
            source_notice = (
                f'Certifi {dist.version} source availability (MPL-2.0)\n'
                f'Exact release metadata: {metadata_url}\n'
                'Unmodified source, including the certificate bundle, is available at:\n'
                + ''.join(f"{item['url']}\nSHA256: {item['digests']['sha256']}\n" for item in sources)
            )
            add(component, f'{key}/SOURCE.txt', source_notice.encode('utf-8'), metadata_url,
                'Exact-version source availability')
        if not component['files']:
            raise RuntimeError(f'No license/notice files found for {name} {dist.version}; review upstream')
        components.append(component)

    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if not python_license.is_file():
        raise RuntimeError(f'Full Python license not found: {python_license}')
    python = {'name': 'Python', 'version': sys.version.split()[0], 'files': []}
    add(python, 'python/LICENSE.txt', python_license.read_bytes(), 'Python installation/LICENSE.txt',
        'Full Python license and bundled software acknowledgements')
    components.append(python)

    webview = {'name': 'Microsoft.Web.WebView2', 'version': WEBVIEW_VERSION, 'files': []}
    relative = f'microsoft-web-webview2-{WEBVIEW_VERSION}/LICENSE.txt'
    data = upstream_license(
        dest, relative, WEBVIEW_URL,
        '324083bf015092054be9d5851dafa1b79cbfab3331ff983476d502839515d8bb',
        extract_html=True,
    )
    add(webview, relative, data, WEBVIEW_URL, 'WebView2 SDK license from the exact NuGet version')
    components.append(webview)

    contents['THIRD_PARTY_NOTICES.md'] = (ROOT / 'THIRD_PARTY_NOTICES.md').read_bytes()
    manifest = {
        'format_version': 1,
        'description': 'License collection, not a binary inventory. Extra build-tool licenses may be included.',
        'components': sorted(components, key=lambda item: normalized(item['name'])),
        'excluded_distributions': excluded,
        'not_redistributed': ['FFmpeg executable; installed separately with user consent'],
        'files': sorted(contents),
    }
    manifest_path = dest / 'manifest.json'
    # Only remove stale files tracked by an earlier run; leave unrelated user files alone.
    if manifest_path.is_file():
        previous = json.loads(manifest_path.read_text(encoding='utf-8'))
        for relative in previous.get('files', []):
            path = dest / relative
            if relative not in contents and path.resolve().is_relative_to(dest.resolve()) and path.is_file():
                path.unlink()
    contents['manifest.json'] = (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')
    for relative, data in sorted(contents.items()):
        path = dest / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(f'Collected {len(components)} components and {len(contents)} files into {dest}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', nargs='?', type=Path, default=ROOT / 'dist' / 'MusicDrive' / 'licenses')
    args = parser.parse_args()
    try:
        collect(args.destination.resolve())
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        parser.exit(1, f'License collection failed: {error}\n')


if __name__ == '__main__':
    main()
