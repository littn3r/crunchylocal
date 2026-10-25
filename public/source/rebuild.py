#!/usr/bin/env python3
"""Rebuild the bundled WASM from supplied sources without downloading libraries."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

root = Path(__file__).resolve().parents[2]
kit = root / 'third_party/libass-wasm'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--install', action='store_true', help='Replace public worker and wrapper files after a successful build')
args = parser.parse_args()
manifest = json.loads((kit/'manifest.json').read_text())
archive = root/'public/source/libass-wasm-4.1.0-source.tar.gz'
if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest['source_archive_sha256']:
    raise SystemExit('Source archive checksum mismatch.')
work = root/'.build/subtitles'
work.mkdir(parents=True, exist_ok=True)
source = work/'libass-wasm-4.1.0'
if not source.exists():
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            target = (work/member.name).resolve()
            if work.resolve() not in target.parents:
                raise SystemExit('Unsafe source archive path.')
            if member.issym() or member.islnk():
                link = (target.parent/member.linkname).resolve() if member.issym() else (work/member.linkname).resolve()
                if work.resolve() not in link.parents:
                    raise SystemExit('Unsafe source archive link.')
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise SystemExit('Unsupported source archive entry.')
        bundle.extractall(work)
    subprocess.run(['patch','-p1','-i',str(kit/'clear-subtitles.patch')],cwd=source,check=True)
# Build only the WASM worker. The upstream all target also builds an unused asm.js worker
# and regenerates notices using Git metadata absent from a source archive.
subprocess.run(['make','JSO_MAKE=emmake make -j 2','dist/js/subtitles-octopus-worker.js'],cwd=source,check=True)
dist=source/'dist/js'
shutil.copy2(kit/'COPYRIGHT',dist/'COPYRIGHT')
notices=(kit/'COPYRIGHT').read_text()
(dist/'subtitles-octopus.js').write_text(''.join('// '+line+'\n' for line in notices.splitlines())+(source/'src/subtitles-octopus.js').read_text())
shutil.copy2(source/'assets/default.woff2',dist/'default.woff2')
shutil.copy2(root/'licenses/liberation-sans.txt',dist/'OFL.txt')
shutil.copy2(root/'public/libass/EMSCRIPTEN-NOTICES.txt',dist/'EMSCRIPTEN-NOTICES.txt')
if args.install:
    for name in ['subtitles-octopus-worker.js','subtitles-octopus-worker.wasm','subtitles-octopus.js','COPYRIGHT','default.woff2','OFL.txt']:
        shutil.copy2(dist/name,root/'public/libass'/name)
print('Built subtitle artifacts in',dist)
print('Keep the source archive, manifest, notices and patch alongside any distributed binaries.')
