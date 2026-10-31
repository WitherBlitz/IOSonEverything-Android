"""Reconstruct the frozen source assets; upload only exact expected SHA-256 bytes.

This never compiles/signs an APK, changes a tag, or publishes a release.
APK reconstruction preserves the existing signed APK byte for byte.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import urllib.parse
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument('--translator', type=Path, required=True)
parser.add_argument('--deflater', type=Path, required=True)
args = parser.parse_args()
root = Path.cwd()
repo = 'WitherBlitz/IOSonEverything-Android'
tag = 'v0.0.1'
release_id = 430225118
expected = {
    'IOSOE-v0.0.1-source.zip': '381b3378dd07aa9b3b88e68a796647fc6796df41093ea93e5d4bf93a617214aa',
    'IOSOE-v0.0.1-graphics-source.zip': 'caad9e7b0cf49891e1606d9f5cf42fb68e08d6ccd2e16b490a46a77610ccccd4',
}

def gh(*command):
    return subprocess.check_output(['gh', *command])

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

releases = json.loads(gh('api', 'repos/' + repo + '/releases?per_page=100'))
matches = [r for r in releases if r['tag_name'] == tag]
assert len(matches) == 1 and matches[0]['draft'] and matches[0]['id'] == release_id, 'Expected the existing draft release'
release = matches[0]
readme = next(a for a in release['assets'] if a['name'] == 'README.md')
original_readme = gh('api', 'repos/' + repo + '/releases/assets/' + str(readme['id']),
                     '-H', 'Accept: application/octet-stream')
manifest = json.loads((root/'SOURCE-CONTENTS.json').read_text(encoding='utf-8'))['files']

def upload_exact(destination, wanted):
    assert digest(destination) == wanted
    current = json.loads(gh('api', 'repos/' + repo + '/releases/' + str(release_id)))
    assert current['id'] == release_id and current['tag_name'] == tag and current['draft']
    existing = [a for a in current['assets'] if a['name'] == destination.name]
    if existing:
        assert len(existing) == 1 and existing[0].get('digest') == 'sha256:' + wanted
        return
    upload_url = current['upload_url'].split('{', 1)[0] + '?' + urllib.parse.urlencode({'name': destination.name})
    content_type = 'application/vnd.android.package-archive' if destination.suffix == '.apk' else 'application/zip'
    uploaded = json.loads(gh('api', upload_url, '-X', 'POST', '--input', str(destination),
                             '-H', 'Content-Type: ' + content_type))
    assert uploaded['name'] == destination.name and uploaded.get('digest') == 'sha256:' + wanted
    print('Uploaded exact frozen asset: ' + destination.name, flush=True)

layout = json.loads((root/'.github/release-inputs/apk-layout.json').read_text(encoding='utf-8'))
residual_path = root/'.github/release-inputs/apk-residual.bin'
assert digest(residual_path) == layout['residual_sha256']
residual = residual_path.read_bytes()
apk_path = Path('/tmp/IOSOE-v0.0.1-android-arm64.apk')
with apk_path.open('wb') as apk:
    for segment in layout['segments']:
        if segment['kind'] == 'literal':
            data = residual[segment['offset']:segment['offset'] + segment['bytes']]
        else:
            assert segment['kind'] == 'native-deflate'
            source_path = Path(segment['path'])
            assert source_path.as_posix().startswith('app/src/main/jniLibs/arm64-v8a/') and '..' not in source_path.parts
            data = subprocess.check_output([str(args.deflater)], input=(root/source_path).read_bytes())
            assert hashlib.sha256(data).hexdigest() == segment['sha256']
        assert len(data) == segment['bytes']
        apk.write(data)
apk_sha256 = 'c08a957ff368bbdaa66b12296e65d5e278b0d5d965f215cc2c2e4c81d962d849'
assert layout['apk_sha256'] == apk_sha256 and apk_path.stat().st_size == layout['apk_bytes']
upload_exact(apk_path, apk_sha256)

class ExactDeflater:
    def compress(self, data):
        return subprocess.check_output([str(args.deflater)], input=data)
    def flush(self):
        return b''

zipfile._get_compressor = lambda method, level=None: ExactDeflater()

with tempfile.TemporaryDirectory(prefix='iosoe-source-') as temporary:
    stage = Path(temporary)
    for name, metadata in manifest.items():
        relative = Path(name)
        assert not relative.is_absolute() and '..' not in relative.parts
        if name.startswith('graphics-source/metal-research/shader/metal2vulkan/'):
            data = (args.translator/name.split('metal2vulkan/', 1)[1]).read_bytes()
        elif name == 'README.md':
            data = original_readme
        elif name == '.gitmodules':
            data = (root/'.github/release-inputs/gitmodules-v0.0.1').read_bytes()
        else:
            data = (root/name).read_bytes()
        if hashlib.sha256(data).hexdigest() != metadata['sha256']:
            lf = data.replace(b'\r\n', b'\n')
            candidates = [lf, lf.replace(b'\n', b'\r\n')]
            data = next((b for b in candidates if hashlib.sha256(b).hexdigest() == metadata['sha256']), None)
            assert data is not None, 'Source mismatch: ' + name
        assert len(data) == metadata['bytes'], name
        path = stage/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (stage/'SOURCE-CONTENTS.json').write_bytes((root/'SOURCE-CONTENTS.json').read_bytes())
    files = list(manifest) + ['SOURCE-CONTENTS.json']
    for filename, wanted in expected.items():
        graphics = filename.endswith('graphics-source.zip')
        prefix = 'IOSOE-v0.0.1-graphics-source' if graphics else 'IOSOE-v0.0.1'
        destination = Path('/tmp')/filename
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for name in files:
                if graphics and not name.startswith('graphics-source/'):
                    continue
                suffix = name[len('graphics-source/'):] if graphics else name
                info = zipfile.ZipInfo(prefix + '/' + suffix, (2026, 10, 30, 0, 0, 0))
                info.create_system = 0  # The original package was produced on Windows.
                executable = Path(name).name == 'gradlew' or Path(name).suffix in {'.sh', '.so'}
                info.external_attr = (0o100755 if executable else 0o100644) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, (stage/name).read_bytes(), compresslevel=6)
        actual = digest(destination)
        assert actual == wanted, f'{filename}: {actual} != {wanted}'
        print('Exact frozen archive verified: ' + filename, flush=True)
        upload_exact(destination, wanted)
