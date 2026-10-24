# Third-party notices for MusicDrive

This document concerns third-party software only. It does **not** select or grant a license for MusicDrive's own application code. Each third-party component remains subject to its own terms; the full upstream texts and copyright notices take precedence over the summaries below.

## Packaged application

The Windows release is a PyInstaller **onedir** distribution in `dist/MusicDrive`. Keep its `licenses` directory with the application when redistributing it. That directory is generated from the Python environment used to build the release and contains:

- Full license, authors, notice and copying files found in installed distribution metadata, preserving their contents.
- The complete `python/LICENSE.txt` from the Python installation used for the build, including its bundled-software acknowledgements.
- The WebView2 SDK license for the exact version identified below.
- An upstream license missing from the `proxy_tools` wheel, and the bundled JavaScript dependency notices from `yt_dlp_ejs`.
- A `manifest.json` recording component names, installed versions, collected file paths, titles, sources and SHA-256 hashes. It also records excluded installed packages separately; those exclusions are not redistributed components.

The collector deliberately includes licenses for all installed distributions except the explicit exclusions below. Some entries, such as pip, setuptools and build tools, may therefore not represent code shipped in the application. **The manifest is a license collection, not a binary inventory or a claim that every listed component is bundled.** No binaries are copied by the collector.

### Principal components

Exact Python package versions and their original notices are recorded in `licenses/manifest.json`.

| Component | License / notice summary | Project |
| --- | --- | --- |
| Python | PSF License Agreement and historical/bundled-software terms; see the full Python license | <https://www.python.org/> |
| pywebview | BSD-3-Clause | <https://github.com/r0x0r/pywebview> |
| Microsoft.Web.WebView2 SDK | Microsoft BSD-style terms, exact version **1.0.3856.49**; see below | <https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.3856.49> |
| pythonnet | MIT; includes upstream authors list | <https://github.com/pythonnet/pythonnet> |
| clr_loader | MIT | <https://github.com/pythonnet/clr-loader> |
| proxy_tools | Upstream BSD text; wheel metadata reports MIT; see below | <https://github.com/jtushman/proxy_tools> |
| bottle | MIT | <https://github.com/bottlepy/bottle> |
| requests | Apache-2.0; includes its NOTICE | <https://github.com/psf/requests> |
| urllib3 | MIT | <https://github.com/urllib3/urllib3> |
| certifi | MPL-2.0 certificate bundle; exact-version source availability below | <https://github.com/certifi/python-certifi> |
| charset-normalizer | MIT | <https://github.com/jawah/charset_normalizer> |
| idna | BSD-3-Clause | <https://github.com/kjd/idna> |
| yt-dlp | Unlicense for its own code; dependencies retain their own terms | <https://github.com/yt-dlp/yt-dlp> |
| yt-dlp-ejs | Unlicense for its own code; bundled meriyah (ISC) and astring (MIT) notices retained separately | <https://github.com/yt-dlp/ejs> |
| cffi / pycparser | MIT-0 / BSD-3-Clause respectively | <https://github.com/python-cffi/cffi>, <https://github.com/eliben/pycparser> |
| PyCryptodomex | Mixed public-domain/BSD terms; consult its full LICENSE and AUTHORS | <https://www.pycryptodome.org/> |
| Brotli / websockets | MIT / BSD-3-Clause respectively | <https://github.com/google/brotli>, <https://github.com/python-websockets/websockets> |
| PyInstaller | GPL-2.0-or-later with the bootloader/distribution exception described in its COPYING file | <https://pyinstaller.org/> |

Other installed dependencies and build-tool licenses, including packaging, altgraph, pywin32-ctypes and PyInstaller hooks, are retained when present. The PyInstaller exception applies according to its original text; inclusion of its license does not assign that license to MusicDrive.

### Microsoft WebView2

pywebview includes WebView2 SDK assemblies and loader libraries. Their SDK license is obtained from the **version-specific** NuGet license page:

<https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.3856.49/License>

The complete extracted license is retained in `licenses/microsoft-web-webview2-1.0.3856.49/LICENSE.txt`. The collector verifies the text against a pinned SHA-256 hash and fails rather than silently substituting a different license. This SDK license is distinct from the terms of the Microsoft Edge WebView2 Runtime installed on the user's computer; it is not a license grant for that separately installed runtime.

### proxy_tools

The installed `proxy_tools` 0.1.0 wheel identifies its license as MIT in metadata but omits a license file. Upstream's `LICENSE.txt` instead contains BSD terms and copyright notices for Armin Ronacher (2013) and Jonathan Tushman (2014). The collector preserves that upstream file **verbatim**, including the upstream wording, at `licenses/proxy-tools/upstream-LICENSE.txt` rather than inventing replacement MIT terms.

Pinned source of the preserved text:

<https://raw.githubusercontent.com/jtushman/proxy_tools/ccd35a569b95bec271a59890780c7821756c548a/LICENSE.txt>

### yt-dlp-ejs bundled JavaScript

The Python distribution's own license is not the only relevant notice. `yt_dlp_ejs/yt/solver/lib.min.js` contains a complete opening license header for its bundled dependencies, including meriyah and astring. The collector copies that header without removing its copyright notices or license terms into a `lib.min.js.NOTICE.txt` file under `licenses/yt-dlp-ejs/`. It checks that the expected dependency-notice header exists and fails if it cannot find it. Dependency versions in the copied header are authoritative for the built release.

### certifi source availability (MPL-2.0)

The certificate bundle is supplied by certifi and is not modified by MusicDrive. Its original license notice is retained under `licenses/certifi/`. Source for the certifi version currently used, **2026.10.19**, including the certificate bundle, is available as the exact PyPI source archive:

<https://files.pythonhosted.org/packages/a6/bd/1436c50cc46699de0230fbaacc1d1de7bfec413176099949e9d5112e88f2/certifi-2026.10.19.tar.gz>

SHA-256: `035c1e85572b141bf1c3a3eff0e33a8eb74917522f2559075ff8d2fea780a1ae`

This link and hash are published in the release metadata at:

<https://pypi.org/pypi/certifi/2026.10.19/json>

For subsequent builds, **`licenses/certifi/SOURCE.txt` and the manifest record the source archive URL and checksum from PyPI metadata for the version actually installed**. Use that generated exact-version notice if it differs from this example. The upstream repository is <https://github.com/certifi/python-certifi>; the Mozilla Public License 2.0 is available at <https://www.mozilla.org/MPL/2.0/>. Nothing in this document restricts recipients' rights in the MPL-covered source.

## Software not redistributed in this package

The frozen application excludes **customtkinter, darkdetect, imageio-ffmpeg, Unidecode and mutagen**. Their licenses are intentionally not copied as if they were bundled dependencies. An entry under `excluded_distributions` only documents a package present in the build environment that is excluded from this release.

**No FFmpeg executable or imageio-ffmpeg wheel is included in the MusicDrive distribution.** In the packaged application, `runtime_ffmpeg.py` obtains the configured FFmpeg wheel directly from PyPI only after user consent, verifies its configured wheel and executable SHA-256 checksums, and installs the executable separately in the user's local application-data cache. That download is not part of the distributed application archive.

The downloaded FFmpeg executable may be GPL-licensed and is governed by the actual binary build's own terms, not by the imageio-ffmpeg Python wrapper's license. Users can review the download provider and upstream information at <https://pypi.org/project/imageio-ffmpeg/> and <https://ffmpeg.org/legal.html>. A checksum verifies integrity, not licensing. Anyone who subsequently redistributes that executable must separately satisfy the applicable FFmpeg/build-provider license and corresponding-source obligations; these application notices are not a substitute for those obligations.

## Regenerating the collection

After the PyInstaller build, run the collector with the same Python environment:

```powershell
.\.venv\Scripts\python.exe scripts\collect_licenses.py
```

The default destination is `dist/MusicDrive/licenses`. An optional positional destination supports verification or another staging directory:

```powershell
.\.venv\Scripts\python.exe scripts\collect_licenses.py C:\Temp\opencode\musicdrive-licenses
```

First collection requires HTTPS access to the pinned WebView2 and proxy_tools license sources and exact-version certifi PyPI metadata. Verified WebView2 and proxy_tools text already in the destination can be reused. Missing license texts or changed pinned upstream texts cause collection to fail for review. Output ordering and contents contain no timestamps or machine-specific absolute paths; repeated runs with the same environment and upstream release metadata produce the same manifest and file bytes. After changing dependencies or bundled SDK versions, regenerate and review the notices before release.
