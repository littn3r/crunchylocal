"""Rewrite native HLS resources through authenticated, resource-bound proxy URLs."""
import re
from urllib.parse import urljoin, urlsplit

def select_quality(source, height):
    """Restrict a master playlist without disturbing alternate audio renditions."""
    if not height or '#EXT-X-STREAM-INF:' not in source:
        return source
    lines = source.splitlines()
    result = []
    keep = True
    matched = False
    for line in lines:
        if line.startswith('#EXT-X-STREAM-INF:'):
            resolution = re.search(r'(?:^|,)RESOLUTION=\d+x(\d+)(?:,|$)', line.split(':', 1)[1])
            keep = bool(resolution and int(resolution[1]) == height)
            matched = matched or keep
            if keep:
                result.append(line)
        elif line and not line.startswith('#'):
            if keep:
                result.append(line)
            keep = True
        else:
            result.append(line)
    if not matched:
        raise ValueError('The selected video quality is unavailable.')
    return '\n'.join(result) + '\n'

def rewrite_manifest(source, base_url, proxy_url):
    if not source.lstrip().startswith('#EXTM3U'):
        raise ValueError('Crunchyroll did not return an HLS playlist.')
    resources = {}
    def resource(value):
        if urlsplit(value).scheme in ('skd','data'): return value
        absolute = urljoin(base_url, value)
        if urlsplit(absolute).scheme != 'https':
            raise ValueError('Unsupported HLS resource URL.')
        playlist = urlsplit(absolute).path.lower().endswith('.m3u8')
        # Implicit byte-range offsets require identical URIs for repeated files.
        if absolute not in resources:
            resources[absolute] = proxy_url(absolute, playlist)
        return resources[absolute]
    result=[]
    for line in source.splitlines():
        stripped=line.strip()
        if stripped.startswith('#'):
            line=re.sub(r'(?<![A-Za-z0-9-])URI="([^"]+)"',lambda m:'URI="'+resource(m.group(1))+'"',line)
        elif stripped:
            line=resource(stripped)
        result.append(line)
    return '\n'.join(result)+'\n'
