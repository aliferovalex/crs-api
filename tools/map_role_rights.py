"""Infer native right UUIDs from paired XML/native values, without row ordering.

Input: a JSON list of {xml: {right: bool}, native: {uuid: 1|-1}} records.
The native field can instead contain a complete native rights table string,
including its restriction envelope.
Only uniquely identified rights are emitted as mappings. Unresolved candidates
and inconsistent observations remain visible for further independent probes.
"""
import argparse
import json
import uuid
import sys
from pathlib import Path


def native_states(text):
    source = Path(__file__).resolve().parents[1] / 'src' / '\u0421\u0435\u0440\u0438\u0430\u043b\u0438\u0437\u0430\u0446\u0438\u044f'
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    import native_metadata
    import role_rights_native
    documents = native_metadata.Parser(text).documents()
    if len(documents) != 1:
        raise ValueError('Expected one native rights table')
    return dict(role_rights_native.read(documents[0]).states)


def propagate(candidates):
    """Apply one-to-one assignments without choosing among correlated rights.

    Stop on contradictions: an inconsistent assignment must not be used to
    manufacture further mappings. The caller reports empty sets and aliases.
    """
    candidates = {name: set(values) for name, values in candidates.items()}
    while True:
        fixed = [next(iter(values)) for values in candidates.values() if len(values) == 1]
        if any(not values for values in candidates.values()) or len(fixed) != len(set(fixed)):
            return candidates
        assigned = set(fixed)
        narrowed = {name: values - assigned if len(values) > 1 else values
                    for name, values in candidates.items()}
        if narrowed == candidates:
            return candidates
        candidates = narrowed


def infer(samples):
    candidates = {}
    evidence = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict) or set(sample) != {'xml', 'native'}:
            raise ValueError('Expected paired XML and native rights')
        named, native = sample['xml'], sample['native']
        if isinstance(native, str):
            native = native_states(native)
        if not isinstance(named, dict) or not isinstance(native, dict):
            raise ValueError('Expected rights dictionaries')
        for oid, state in native.items():
            if str(uuid.UUID(oid)) != oid or type(state) is not int or state not in (-1, 1):
                raise ValueError('Invalid native right UUID or state')
        changed = False
        for name, value in named.items():
            if not isinstance(name, str) or not name or type(value) is not bool:
                raise ValueError('Invalid XML right name or value')
            allowed = {oid for oid, state in native.items() if state == (1 if value else -1)}
            narrowed = candidates[name] & allowed if name in candidates else allowed
            if name not in candidates or narrowed != candidates[name]:
                changed = True
            candidates[name] = narrowed
        if changed:
            evidence.append(index)
    candidates = propagate(candidates)
    resolved = {name: next(iter(values)) for name, values in candidates.items() if len(values) == 1}
    # A single native right cannot represent two distinct XML rights. Do not
    # silently choose one when input observations contradict that invariant.
    aliases = {}
    for name, oid in resolved.items():
        aliases.setdefault(oid, []).append(name)
    collisions = {oid: sorted(names) for oid, names in aliases.items() if len(names) > 1}
    invalid = {name for names in collisions.values() for name in names}
    return {
        'resolved': {name: oid for name, oid in sorted(resolved.items()) if name not in invalid},
        'unresolved': {name: sorted(values) for name, values in sorted(candidates.items()) if len(values) > 1},
        'conflicts': sorted(name for name, values in candidates.items() if not values),
        'collisions': collisions,
        'evidence': evidence,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('samples', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    samples = json.loads(args.samples.read_text(encoding='utf-8-sig'))
    if not isinstance(samples, list):
        parser.error('Samples must be a JSON list')
    result = infer(samples)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('Resolved:', len(result['resolved']), 'unresolved:', len(result['unresolved']),
          'conflicts:', len(result['conflicts']), 'collisions:', len(result['collisions']))
    return int(bool(result['conflicts'] or result['collisions']))


if __name__ == '__main__':
    raise SystemExit(main())
