#!/usr/bin/env python3
"""Validate the central documentation boundary without running application code."""
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r'\]\(([^\s)]+)(?:\s+"[^"]*")?\)')
PRIVATE = re.compile(r'/home/(?:ubuntu|informatica)/|\.tail[a-z0-9]+\.ts\.net|(?:^|[\s`(])(?:odd/|AGENTS\.md|docs/reviews/)')


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True)


def main():
    errors = []
    docs = [ROOT / 'README.md', ROOT / 'INSTALL.md', *sorted((ROOT / 'docs').rglob('*.md'))]
    docs = [p for p in docs if '/reviews/' not in str(p)]
    for document in docs:
        text = document.read_text()
        for number, line in enumerate(text.splitlines(), 1):
            if PRIVATE.search(line):
                errors.append(f'{document.relative_to(ROOT)}:{number}: internal reference')
        for target in LINK.findall(text):
            if target.startswith(('http:', 'https:', 'mailto:', '#', 'data:')):
                if re.search(r'hadar-it-(?:frontend|backend)/blob/master/(?:docs/|DESIGN\.md|brand-spec\.md)', target):
                    errors.append(f'{document.relative_to(ROOT)}: removed component documentation link')
                continue
            path = unquote(target.split('#', 1)[0])
            if path and not (document.parent / path).resolve().is_file():
                errors.append(f'{document.relative_to(ROOT)}: missing {target}')
        if text.count('```') % 2:
            errors.append(f'{document.relative_to(ROOT)}: unclosed code fence')
    for name in ('frontend', 'backend'):
        repo = ROOT / name
        if not (repo / '.git').exists():
            continue
        tracked = git(repo, 'ls-files').splitlines()
        bad = [p for p in tracked if p.startswith('docs/') or p in ('DESIGN.md', 'brand-spec.md', 'AGENTS.md', 'SYSTEM.md')]
        if bad:
            errors.append(f'{name}: internal files still tracked: {bad}')
        for path in ('docs/internal.md', 'DESIGN.md', 'brand-spec.md', 'odd/internal.md', 'AGENTS.md'):
            result = subprocess.run(['git', '-C', str(repo), 'check-ignore', '--no-index', '-q', path])
            if result.returncode != 0:
                errors.append(f'{name}: not ignored: {path}')
        dockerignore = (repo / '.dockerignore').read_text().splitlines()
        for path in ('docs/', 'DESIGN.md', 'brand-spec.md', 'SYSTEM.md'):
            if path not in dockerignore:
                errors.append(f'{name}: build context includes internal material: {path}')
        readme = (repo / 'README.md').read_text()
        if 'hadar-it/blob/master/docs/' + name + '/development.md' not in readme:
            errors.append(f'{name}: README must link central development guide')
        if name == 'backend':
            for prefix in ('itsm/agent_integrations/skills/', 'itsm/extensions/sdk/references/'):
                if not any(p.startswith(prefix) for p in tracked):
                    errors.append(f'backend: packaged resources missing: {prefix}')
    for error in errors:
        print('FAIL', error)
    print(f'Checked {len(docs)} central documents; {len(errors)} errors')
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
