"""Disk-backed STEP dependency index for bounded IFC geometry batches.

Fragments retain STEP ids, GlobalIds, units, placements, mapped representations,
styles and void relationships. No geometry or quantities are approximated here.
"""
from __future__ import annotations

import mmap
import re
import sqlite3
from pathlib import Path

# Strings (including doubled quotes) and comments are opaque to both scanners.
TOKENS = re.compile(rb"'(?:[^']|'')*'|/\*.*?\*/|;", re.DOTALL)
REFS = re.compile(rb"'(?:[^']|'')*'|/\*.*?\*/|#(\d+)", re.DOTALL)
ENTITY = re.compile(rb"\s*(?:/\*.*?\*/\s*)*#(\d+)\s*=\s*([A-Z0-9_]+)\s*\(", re.I | re.S)


def references(record):
    return [int(m[1]) for m in REFS.finditer(record) if m[1] is not None]


class Fragments:
    def __init__(self, source: Path, database: Path):
        self.source = source.open('rb')
        self.mapping = mmap.mmap(self.source.fileno(), 0, access=mmap.ACCESS_READ)
        self.db = sqlite3.connect(database)
        self.db.executescript('''PRAGMA cache_size=-2048; PRAGMA journal_mode=OFF;
            CREATE TABLE records(id INTEGER PRIMARY KEY, type TEXT, start INTEGER, end INTEGER);
            CREATE TABLE inverse(owner INTEGER, relation INTEGER);
            CREATE INDEX inverse_owner ON inverse(owner);''')
        start, in_data, header_end = 0, False, None
        for token in TOKENS.finditer(self.mapping):
            if token[0] != b';':
                continue
            end = token.end()
            record = self.mapping[start:end]
            if not in_data:
                if record.strip().upper() == b'DATA;':
                    in_data, header_end = True, end
            else:
                match = ENTITY.match(record)
                if match:
                    step_id, kind = int(match[1]), match[2].decode('ascii').upper()
                    self.db.execute('INSERT INTO records VALUES (?,?,?,?)', (step_id, kind, start, end))
                    if kind in ('IFCSTYLEDITEM', 'IFCRELVOIDSELEMENT'):
                        refs = references(record[match.end():])
                        owner = refs[0] if kind == 'IFCSTYLEDITEM' and refs else refs[-2] if len(refs) >= 2 else None
                        if owner is not None:
                            self.db.execute('INSERT INTO inverse VALUES (?,?)', (owner, step_id))
            start = end
        if header_end is None:
            raise ValueError('The IFC has no readable STEP DATA section. Export it again as IFC.')
        self.header = self.mapping[:header_end] + b'\n'
        self.db.commit()
        schema = re.search(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", self.header, re.I)
        if not schema:
            raise ValueError('The IFC schema header is missing or unreadable.')
        self.schema = schema[1].decode('ascii')

    def product_ids(self):
        import ifcopenshell
        import ifcopenshell.util.schema
        schema = ifcopenshell.schema_by_name(self.schema)
        kinds = {d.name().upper() for base in ('IfcElement', 'IfcSpace')
                 for d in ifcopenshell.util.schema.get_subtypes(schema.declaration_by_name(base))}
        openings = {d.name().upper() for d in ifcopenshell.util.schema.get_subtypes(schema.declaration_by_name('IfcOpeningElement'))}
        return [i for i, kind in self.db.execute('SELECT id,type FROM records ORDER BY id') if kind in kinds - openings]

    def dependencies(self, roots):
        pending = list(roots)
        seen, size = set(), 0
        while pending:
            step_id = pending.pop()
            if step_id in seen:
                continue
            seen.add(step_id)
            row = self.db.execute('SELECT start,end FROM records WHERE id=?', (step_id,)).fetchone()
            if row is None:
                raise ValueError(f'The IFC has a missing STEP reference #{step_id}. Export it again as IFC.')
            start, end = row
            size += end - start
            match = ENTITY.match(self.mapping, start, end)
            # The optional whitespace and comments may precede the entity id.
            refs_start = match.end() if match else start
            pending.extend(references(self.mapping[refs_start:end]))
            pending.extend(r[0] for r in self.db.execute('SELECT relation FROM inverse WHERE owner=?', (step_id,)))
        return seen, size

    def batches(self, max_products=16, max_bytes=2 * 1024**2):
        projects = [r[0] for r in self.db.execute("SELECT id FROM records WHERE type='IFCPROJECT'")]
        base, _ = self.dependencies(projects)
        ids, selected, size = [], set(base), 0
        for step_id in self.product_ids():
            closure, _ = self.dependencies([step_id])
            added = closure - selected
            extra = sum(self.db.execute('SELECT end-start FROM records WHERE id=?', (i,)).fetchone()[0] for i in added)
            if ids and (len(ids) >= max_products or size + extra > max_bytes):
                yield ids, selected
                ids, selected, size = [], set(base), 0
            ids.append(step_id)
            selected.update(closure)
            size += extra
        if ids:
            yield ids, selected

    def write(self, path: Path, selected):
        with path.open('wb') as target:
            target.write(self.header)
            for step_id in sorted(selected):
                start, end = self.db.execute('SELECT start,end FROM records WHERE id=?', (step_id,)).fetchone()
                target.write(self.mapping[start:end])
                target.write(b'\n')
            target.write(b'ENDSEC;\nEND-ISO-10303-21;\n')

    def close(self):
        self.db.close()
        self.mapping.close()
        self.source.close()
