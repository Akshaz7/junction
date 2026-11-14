#!/usr/bin/env python3
"""Audit all quantitative literals in the report set against linked results.

Run with the repo Python: .venv/bin/python docs/scratch/check_report_numbers.py
Each measured number must be inside a result link with a JSON pointer to its
value. The explicitly allowlisted /computed/ fragments below are recomputed
from raw results without writing or changing those results. Percentages are
rendered from stored fractions. Version numbers, model/dataset names, row IDs,
file names, API paths and licence identifiers are metadata, not measurements.
Task-chain metadata is separately checked against the current models YAML.
"""
from decimal import Decimal
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
DOCS = [ROOT / 'docs' / f'{name}.md' for name in ('REPORT', 'MODELS', 'JUDGES')]
LINK = re.compile(r'\[([^\]\n]+)\]\(([^)\n]+)\)')
NUMBER = re.compile(r'(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?%?(?![\w.])')
# Remove complete named identifiers, not bare numeric code literals.
IDENTIFIERS = re.compile(
    r'`[^`\n]*[A-Za-z_][^`\n]*`'
    r'|\b(?:Claude Sonnet|Fable|Gemini|Opus) \d+(?:\.\d+)?\b'
    r'|\bCC BY(?:-[A-Z]+)* \d+\.\d+\b'
    r'|\b\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|November|December) \d{4}\b'
    r'|\b\d+\.\d+ Super VL\b'
    r'|\bFantasy Office 3\b'
    r'|Installed `\d+(?:\.\d+)+` metadata'
    r'|\b[A-Za-z][\w]*(?:[-.][\w]+)+\b'
)
failed = 0
checked = 0


def report(ok, label):
    global failed
    print(('PASS ' if ok else 'FAIL ') + label)
    failed += not ok


def value_at(path, fragment):
    if fragment.startswith('/computed/'):
        # Derived links name calculations, not fields claimed to exist on disk.
        # Keep the allowed sources and formulas explicit and fail on missing data.
        field = fragment.removeprefix('/computed/')
        if path == ROOT / 'results/bench/e-s200-z1.rows.jsonl':
            rows = [json.loads(line, parse_float=Decimal)
                    for line in path.read_text().splitlines() if line.strip()]
            assert rows
            costs = [row['cost_usd'] for row in rows]
            assert all(isinstance(cost, (int, Decimal)) and not isinstance(cost, bool)
                       and cost >= 0 for cost in costs)
            zero = sum(cost == 0 for cost in costs)
            return {'n': len(rows), 'zero_cost_answers': zero,
                    'zero_cost_share': Decimal(zero) / len(rows),
                    'zero_cost_usd': min(costs)}[field]
        if path in {ROOT / 'results/qa/judge_run-r4.json',
                    ROOT / 'results/qa/judge_run-dep2.json'}:
            rows = json.loads(path.read_text())
            assert rows and all(row['grade'] in {'correct', 'partial', 'wrong'}
                                for row in rows)
            return {'n': len(rows),
                    'correct': sum(row['grade'] == 'correct' for row in rows),
                    'partial': sum(row['grade'] == 'partial' for row in rows)}[field]
        raise ValueError('unsupported derived metric')
    value = json.loads(path.read_text(), parse_float=Decimal)
    for token in unquote(fragment).lstrip('/').split('/'):
        token = token.replace('~1', '/').replace('~0', '~')
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


for doc in DOCS:
    for line_no, line in enumerate(doc.read_text().splitlines(), 1):
        # Numeric link labels remain measurements; destinations are never numbers.
        outside = list(line)
        for link in LINK.finditer(line):
            label, target = link.groups()
            nums = list(NUMBER.finditer(IDENTIFIERS.sub(' ', label)))
            path_text, sep, fragment = target.partition('#')
            path = (doc.parent / path_text).resolve()
            if not target.startswith(('https://', 'http://')):
                report(path.is_file(), f'{doc.name}:{line_no} link {path_text}')
            for num in nums:
                checked += 1
                raw = num.group()
                ok = False
                detail = 'requires a linked results JSON field'
                try:
                    assert path.is_relative_to(ROOT / 'results') and sep and fragment.startswith('/')
                    stored = value_at(path, fragment)
                    assert isinstance(stored, (int, Decimal)) and not isinstance(stored, bool)
                    displayed = Decimal(raw.rstrip('%').replace(',', ''))
                    expected = Decimal(stored) * (100 if raw.endswith('%') else 1)
                    ok = displayed == expected
                    detail = f'{target} = {stored}'
                except (AssertionError, OSError, ValueError, KeyError, IndexError, TypeError):
                    pass
                report(ok, f'{doc.name}:{line_no} number {raw} -> {detail}')
            outside[link.start():link.end()] = ' ' * (link.end() - link.start())
        for num in NUMBER.finditer(IDENTIFIERS.sub(' ', ''.join(outside))):
            checked += 1
            report(False, f'{doc.name}:{line_no} number {num.group()} has no results link')

# No model calls. Validate every documented chain, not just the lead's examples.
try:
    config = ROOT / 'engine/models/models.yaml'
    try:
        import yaml
    except ImportError:
        # The required python3 command need not have the repo's dependencies.
        # Read YAML with the existing repo interpreter; do not install anything.
        parsed = subprocess.run(
            [str(ROOT / '.venv/bin/python'), '-c',
             'import json,sys,yaml; print(json.dumps(yaml.safe_load(open(sys.argv[1]))))',
             str(config)], capture_output=True, text=True, check=True, timeout=10)
        tasks = json.loads(parsed.stdout)['tasks']
    else:
        tasks = yaml.safe_load(config.read_text())['tasks']
    table = (ROOT / 'docs/MODELS.md').read_text()
    for task, spec in tasks.items():
        expected = '| `' + task + '` | ' + ' → '.join(
            '`' + item['provider'] + ':' + item['model'] + '`'
            for item in [spec, *spec.get('fallback', [])]
        ) + ' |'
        report(expected in table, f'configured chain {task}')
    documented = re.findall(r'^\| `([^`]+)` \| .*→', table, re.M)
    report(set(documented) == set(tasks), 'task-chain table has no missing or obsolete tasks')
except (ImportError, OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError) as exc:
    report(False, f'cannot validate model chains: {exc}')
submission = (ROOT / 'docs/REPORT.md').read_text()
visible = LINK.sub(lambda match: match.group(1), submission)
words = len(visible.split())
report(words <= 1500, f'REPORT.md word limit: {words}/1500 (link destinations excluded)')
for section in ('Accuracy', 'Visual verifiability', 'Creativity', 'Low inference cost',
                'Limits and provenance'):
    report(submission.count('## ' + section + '\n') == 1, f'REPORT.md section {section}')
screenshots = [match for match in LINK.finditer(submission)
               if match.group(2).endswith('.png')]
report(len(screenshots) == 4, 'REPORT.md links four evidence screenshots')
report(checked > 0, f'checked {checked} quantitative literals')
print('FAIL' if failed else 'PASS')
sys.exit(bool(failed))
