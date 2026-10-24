import hashlib
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0.0"


def main():
    folder = ROOT / "dist" / "MusicDrive"
    for relative in ("MusicDrive.exe", "MusicDriveWorker.exe", "_internal/web/index.html", "licenses/manifest.json"):
        if not (folder / relative).is_file():
            raise SystemExit(f"Missing release file: {relative}")
    for path in folder.rglob("*"):
        if path.is_file() and (path.name.lower().startswith("ffmpeg") and path.suffix.lower() in {".exe", ".whl"}):
            raise SystemExit(f"FFmpeg must not be bundled: {path}")
        if path.name.lower() in {"settings.json", "cookies.txt", ".env"}:
            raise SystemExit(f"Private file in release: {path}")
    for filename in ("README.md", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / filename, folder / filename)
    archive = ROOT / "dist" / f"MusicDrive-{VERSION}-windows-x64.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                package.write(path, path.relative_to(folder.parent).as_posix())
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (archive.parent / "SHA256SUMS.txt").write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
    print(f"Release archive: {archive} ({archive.stat().st_size / 1024 / 1024:.1f} MiB)")
    print(f"SHA256: {checksum}")


if __name__ == "__main__":
    main()
