"""Build, verify and archive the native app on Windows or macOS."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "xiaoguo.spec"], cwd=ROOT, check=True)
    mac = sys.platform == "darwin"
    arch = {"AMD64": "x64", "x86_64": "x64", "arm64": "arm64"}[platform.machine()]
    label = ("macos-" if mac else "windows-") + arch
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    report = release / f"verification-{label}.json"
    env = os.environ.copy()
    for key in ("PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY"):
        env.pop(key, None)
    env["PATH"] = "/usr/bin:/bin" if mac else str(Path(os.environ["SYSTEMROOT"]) / "System32")
    with tempfile.TemporaryDirectory(prefix="xiaoguo-portable-") as temporary:
        folder = Path(temporary) / "portable 中文 space"
        folder.mkdir()
        if mac:
            bundle = folder / "小果.app"
            shutil.copytree(ROOT / "dist" / "小果.app", bundle, symlinks=True)
            executable = bundle / "Contents" / "MacOS" / "小果"
        else:
            executable = folder / "小果.exe"
            shutil.copy2(ROOT / "dist" / "小果.exe", executable)
        subprocess.run([str(executable), "--self-test", str(report)], cwd=folder, env=env, check=True, timeout=120)
    result = json.loads(report.read_text(encoding="utf-8"))
    if not result.get("passed") or not result.get("frozen"):
        raise RuntimeError("Packaged app self-test did not pass")
    archive = release / f"xiaoguo-{label}.zip"
    if mac:
        # ditto preserves bundle symlinks, executable bits and macOS metadata.
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(ROOT / "dist" / "小果.app"), str(archive)], check=True)
    else:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
            output.write(ROOT / "dist" / "小果.exe", "小果.exe")
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")
    print(f"Verified package: {archive.name}", flush=True)


if __name__ == "__main__":
    main()
