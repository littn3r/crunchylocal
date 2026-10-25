#!/usr/bin/env python3
"""Collect installed runtime notices and package inventory; not a source-code offer."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys

out = Path(sys.argv[1]) if len(sys.argv)>1 else Path('/app/licenses/runtime')
out.mkdir(parents=True,exist_ok=True)
records=[]
def copy(path, category):
    if not path.is_file(): return
    target=out/category/str(path).lstrip('/')
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(path,target)
    records.append({'path':str(target.relative_to(out)), 'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
for base in [Path('/usr/share/doc'),Path('/usr/share/licenses')]:
    if base.exists():
        for p in base.rglob('*'):
            if p.name.lower()=='copyright' or p.name.lower().startswith(('license','copying','notice')):
                copy(p,'system')
for p in [Path('/usr/local/LICENSE'),Path('/app/LICENSE'),Path('/app/node_modules/electron/dist/LICENSE'),Path('/app/node_modules/electron/dist/LICENSES.chromium.html')]:
    copy(p,'runtime')
node=Path('/app/node_modules')
if node.exists():
    for p in node.rglob('*'):
        if p.name.lower().startswith(('license','copying','notice')):copy(p,'npm')
packages=[]
for dist in importlib.metadata.distributions():
    packages.append({'name':dist.metadata.get('Name'),'version':dist.version,'license':dist.metadata.get('License-Expression') or dist.metadata.get('License')})
    for p in dist.files or []:
        if any(word in str(p).lower() for word in ['license','copying','notice']):copy(Path(dist.locate_file(p)),'python')
if shutil.which('dpkg-query'):
    (out/'system-packages.tsv').write_bytes(subprocess.check_output(['dpkg-query','-W','-f=${binary:Package}\t${Version}\n']))
if Path('/lib/apk/db/installed').exists():
    (out/'apk-package-metadata.txt').write_bytes(Path('/lib/apk/db/installed').read_bytes())
(out/'inventory.json').write_text(json.dumps({'python':packages,'notice_files':records},indent=2)+'\n')
(out/'README.txt').write_text('Installed runtime notices collected at image build time.\nThis is not proof of complete compliance and does not replace corresponding-source obligations.\nBefore distributing an OCI image, review its exact package inventory, native bundled libraries, notices and source availability.\n')
print('Runtime notices collected:',len(records))
