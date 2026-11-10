#!/usr/bin/env python3
"""Generate initial configuration files without exposing secrets or overwriting existing files."""
import json
import base64
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit

root = Path(__file__).resolve().parents[1]
origin = sys.argv[1].rstrip('/') if len(sys.argv) > 1 else 'http://127.0.0.1:8765'
url = urlsplit(origin)
if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.path or url.query or url.fragment:
    raise SystemExit('Supply only the origin: https://player.example.com')
files = {
    '.env': 'CRUNCHY_LOCAL_PUBLIC_ORIGIN='+origin+'\nCRUNCHY_LOCAL_SESSION_KEY='+base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()+'\n',
    'oauth_apps.json': json.dumps({p:{'client_id':'','client_secret':''} for p in ('one','rip','mal')},indent=2)+'\n'
}
for name, data in files.items():
    try:
        fd = os.open(root/name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        print(name, 'already exists; preserved')
    else:
        with os.fdopen(fd,'w') as f: f.write(data)
        print(name, 'created')
