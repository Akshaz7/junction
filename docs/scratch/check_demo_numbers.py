#!/usr/bin/env python3
"""X-16 done test: audit demo/Q&A measurements using the report checker pattern.

Run: python3 docs/scratch/check_demo_numbers.py
Only the declared editorial schedule's clock cells and named identifiers are
metadata. Every other numeric literal must link to its exact results JSON field.
Also validate local links, JSON pointers, Q&A coverage and reset-table parsing.
No network, model calls or reset mutations.
"""
from decimal import Decimal
import json
from pathlib import Path
import re
import runpy
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
DOCS = [ROOT / 'docs' / name for name in ('DEMO.md', 'JUDGE_QA.md')]
LINK = re.compile(r'\[([^\]\n]+)\]\(([^)\n]+)\)')
NUMBER = re.compile(r'(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?%?(?![\w.])')
IDENTIFIERS = re.compile(
    r'`[^`\n]*[A-Za-z_][^`\n]*`'
    r'|`848/2017 §33`'  # Statute identifier, not an observed quantity.
    r'|\b[A-Za-z][\w]*(?:[-.][\w]+)+\b'
)
CLOCK_CELL = re.compile(r'^(\| )\d+:\d{2}–\d+:\d{2}( \|)')
failures = []
checked = 0
links = 0


def value_at(path, fragment):
    value = json.loads(path.read_text(), parse_float=Decimal)
    for token in unquote(fragment).lstrip('/').split('/'):
        token = token.replace('~1', '/').replace('~0', '~')
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


for doc in DOCS:
    for line_no, original in enumerate(doc.read_text().splitlines(), 1):
        line = CLOCK_CELL.sub(r'\1editorial time\2', original)
        outside = list(line)
        location = f'{doc.name}:{line_no}'
        for link in LINK.finditer(line):
            links += 1
            label, target = link.groups()
            path_text, sep, fragment = target.partition('#')
            remote = target.startswith(('https://', 'http://'))
            path = (doc.parent / path_text).resolve()
            if not remote:
                if not path.is_file():
                    failures.append(f'{location}: missing local link {target}')
                elif sep and fragment.startswith('/'):
                    try:
                        value_at(path, fragment)
                    except (OSError, ValueError, KeyError, IndexError, TypeError):
                        failures.append(f'{location}: invalid JSON pointer {target}')
            for number in NUMBER.finditer(IDENTIFIERS.sub(' ', label)):
                checked += 1
                raw = number.group()
                try:
                    assert not remote and path.is_relative_to(ROOT / 'results')
                    assert sep and fragment.startswith('/')
                    stored = value_at(path, fragment)
                    assert isinstance(stored, (int, Decimal)) and not isinstance(stored, bool)
                    displayed = Decimal(raw.rstrip('%').replace(',', ''))
                    expected = Decimal(stored) * (100 if raw.endswith('%') else 1)
                    assert displayed == expected
                except (AssertionError, OSError, ValueError, KeyError, IndexError, TypeError):
                    failures.append(f'{location}: number {raw} does not match {target}')
            outside[link.start():link.end()] = ' ' * (link.end() - link.start())
        for number in NUMBER.finditer(IDENTIFIERS.sub(' ', ''.join(outside))):
            checked += 1
            failures.append(f'{location}: number {number.group()} has no results link')

qa = DOCS[1].read_text()
if re.findall(r'^### (Q\d+) ·', qa, re.M) != [f'Q{i:02}' for i in range(1, 16)]:
    failures.append('Q&A must contain exactly Q01 through Q15')
try:
    helper = runpy.run_path(str(ROOT / 'scripts/demo_reset.py'))
    questions = helper['demo_questions'](DOCS[0])
    for question in (
        'How many doors are on the ground floor?',
        'show me the doors',
        'remove the front door, is it still compliant?',
        'reset the model',
    ):
        if ('ifc_bench__ac20-arc', question) not in questions:
            failures.append(f'reset table missing AC20 question: {question}')
except (OSError, ValueError, RuntimeError) as exc:
    failures.append(f'reset-table parsing failed: {exc}')
if not checked:
    failures.append('no measured literals checked')
for failure in failures:
    print('FAIL ' + failure)
print(f'{"FAIL" if failures else "PASS"}: {checked} measured literals, '
      f'{links} links, fifteen Q&As and reset-table compatibility')
sys.exit(bool(failures))
