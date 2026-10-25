#!/usr/bin/env python3
"""Package tracked public source only. No network, credentials or live trading."""
import argparse
import hashlib
import subprocess
from pathlib import Path, PurePosixPath
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {'.gitignore', 'README.md', 'SKILL.md', 'llms.txt', 'LICENSE', 'NOTICE.md'}
DIRECTORIES = {'bridge', 'references', 'docs', 'examples', 'scripts', 'LICENSES', '.github'}
TEXT_SUFFIXES = {'.md', '.txt', '.py', '.js', '.pine', '.json', '.sh', '.yml', '.yaml'}


def public_files(root=ROOT):
    raw = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root)
    names = sorted(set(raw.decode('utf-8').rstrip('\0').split('\0')))
    if not names or names == ['']:
        raise ValueError('No tracked files. Add reviewed public files to Git first.')
    files = []
    for name in names:
        rel = PurePosixPath(name)
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError('Unsafe Git path: ' + name)
        if name not in ROOT_FILES and rel.parts[0] not in DIRECTORIES:
            raise ValueError('Unexpected tracked path; review before publication: ' + name)
        if name not in ROOT_FILES and rel.suffix not in TEXT_SUFFIXES:
            raise ValueError('Unexpected file type: ' + name)
        if any(p in {'.env', 'robot.conf', 'node_modules', '__pycache__'} or
               p.startswith('.env.') for p in rel.parts):
            raise ValueError('Deployment/private file is forbidden: ' + name)
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing file or symlink: ' + name)
        data = path.read_bytes()
        data.decode('utf-8')
        # Check assembled byte markers to avoid matching this validator's own source.
        forbidden = [b'-----BEGIN ' + b'PRIVATE KEY-----',
                     b'-----BEGIN RSA ' + b'PRIVATE KEY-----',
                     b'-----BEGIN OPENSSH ' + b'PRIVATE KEY-----']
        if any(marker in data for marker in forbidden):
            raise ValueError('Credential material detected: ' + name)
        files.append((name, data))
    required = {'SKILL.md', 'docs/HANDOVER.md', 'NOTICE.md', 'LICENSE',
                'LICENSES/MPL-2.0.txt', 'examples/alligator-fractal/Alligator-Fractal-OneBullEx.js'}
    missing = required - {name for name, _ in files}
    if missing:
        raise ValueError('Public package incomplete: ' + ', '.join(sorted(missing)))
    return files


def package(output):
    files = public_files()
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
        for name, data in files:
            info = ZipInfo('onebullex-fmz-bridge/' + name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + '.sha256').write_text(digest + '  ' + output.name + '\n')
    print(f'Packaged {len(files)} tracked public files: {output}')
    print('SHA-256: ' + digest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/onebullex-fmz-bridge-public.zip')
    package(parser.parse_args().output)
