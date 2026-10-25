#!/usr/bin/env python3
"""Build the Chromium extension and Tampermonkey script for a player origin."""
import json
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

root = Path(__file__).resolve().parents[1]
if len(sys.argv) != 2:
    raise SystemExit('Usage: python3 tools/configure_extension.py https://player.example.com')
url = urlsplit(sys.argv[1])
if (url.scheme != 'https' and not (url.scheme == 'http' and url.hostname in ('127.0.0.1', 'localhost'))) or not url.hostname or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment:
    raise SystemExit('Use an HTTPS origin, or HTTP on localhost. No path, credentials or query.')
origin = url.scheme + '://' + url.netloc
origins = list(dict.fromkeys([origin, 'http://127.0.0.1:8765', 'http://localhost:8765']))
# Match patterns omit ports; runtime checks still require the exact configured origin.
patterns = list(dict.fromkeys(urlsplit(o).scheme + '://' + urlsplit(o).hostname + '/*' for o in origins))
manifest_path = root / 'extension/manifest.json'
manifest = json.loads(manifest_path.read_text())
manifest.update(name='Crunchy Local — sign-in', version='1.1.0', description='Connect your Crunchyroll session to your own Crunchy Local player after official sign-in.')
manifest['host_permissions'] = ['https://*.crunchyroll.com/*', *patterns]
manifest['content_scripts'][0]['matches'] = patterns
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
for name, marker in [('background.js','const ALLOWED_ORIGINS = new Set('), ('content.js','const ALLOWED_PAGE_ORIGINS = new Set(')]:
    p = root / 'extension' / name
    source = p.read_text()
    start = source.index(marker)
    end = source.index(');', start)+2
    p.write_text(source[:start] + marker + json.dumps(origins) + ');' + source[end:])
with zipfile.ZipFile(root/'public/crunchy-local-extension.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in sorted((root/'extension').glob('*')):
        if path.is_file(): archive.write(path, 'extension/'+path.name)
script_path = root/'userscripts/crunchy-local-login.user.js'
script = script_path.read_text()
start = script.index('  const ALLOWED_PLAYER_ORIGINS = new Set(')
end = script.index(');', start)+2
script = script[:start] + '  const ALLOWED_PLAYER_ORIGINS = new Set('+json.dumps(origins)+');' + script[end:]
import re
script = re.sub(r'^// @match.*\n', '', script, flags=re.M)
entries = ''.join('// @match        '+pattern+'\n' for pattern in [*patterns, 'https://www.crunchyroll.com/*'])
script = script.replace('// @grant        GM_cookie', entries+'// @grant        GM_cookie')
script_path.write_text(script)
(root/'public/crunchy-local-login.user.js').write_text(script)
print('Chromium extension and Tampermonkey script configured for', origin)
