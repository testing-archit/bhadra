#!/usr/bin/env python3
"""Verify bundled design skills; optionally link them into Claude Code."""

import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--link-claude', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / 'design-skills-lock.json').read_text())
    for skill in manifest['skills']:
        name = skill['name']
        folder = root / '.agents' / 'skills' / name
        for relative, expected in skill['files'].items():
            file = folder / relative
            if not file.is_file():
                raise SystemExit(f'Missing skill file: {file}')
            if hashlib.sha256(file.read_bytes()).hexdigest() != expected:
                raise SystemExit(f'Skill file changed: {file}')
        if args.link_claude:
            link = root / '.claude' / 'skills' / name
            link.parent.mkdir(parents=True, exist_ok=True)
            if link.exists() or link.is_symlink():
                if not link.is_symlink() or link.resolve() != folder.resolve():
                    raise SystemExit(f'Refusing to overwrite existing skill: {link}')
            else:
                link.symlink_to(Path('../../.agents/skills') / name,
                                target_is_directory=True)
        print(f'OK {name}: {len(skill["files"])} files')


if __name__ == '__main__':
    main()
