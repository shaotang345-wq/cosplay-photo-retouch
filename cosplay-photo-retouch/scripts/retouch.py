"""Native-grid retouch with recorded approvals, immutable versions and export gates."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import numpy as np
from PIL import Image
from acceptance import load_image, load_mask, check

HIGH = {'background', 'repaint', 'strong_effect'}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def canonical(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, obj, new=False):
    path = Path(path)
    data = json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)
    if new:
        with path.open('x', encoding='utf-8') as f:
            f.write(data)
    else:
        temp = path.with_suffix(path.suffix + '.tmp')
        with temp.open('x', encoding='utf-8') as f:
            f.write(data)
        temp.replace(path)


def identifier(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', value):
        raise ValueError('Invalid ID')
    if value.upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
                         *(f'LPT{i}' for i in range(1, 10))}:
        raise ValueError('Reserved Windows ID')
    return value


@contextmanager
def locked(root):
    path = root / '.lock'
    with path.open('x'):
        pass
    try:
        yield
    finally:
        path.unlink()


def asset(root, ref):
    if not re.fullmatch(r'assets/[0-9a-f]{64}', ref['path']):
        raise ValueError('Invalid asset path')
    path = root / ref['path']
    if not path.resolve().is_relative_to(root.resolve()) or digest(path) != ref['sha256']:
        raise ValueError('Asset changed or escaped project')
    return path


def capture(root, path):
    path = Path(path)
    sha = digest(path)
    target = root / 'assets' / sha
    if not target.exists():
        with path.open('rb') as src, target.open('xb') as dst:
            shutil.copyfileobj(src, dst)
    if digest(target) != sha:
        raise ValueError('Asset changed during capture')
    return {'path': 'assets/' + sha, 'sha256': sha}


def number(value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Finite numeric parameter required')
    if not lo <= value <= hi:
        raise ValueError('Parameter out of range')
    return value


def validate_operations(ops):
    if not isinstance(ops, list) or not ops:
        raise ValueError('At least one operation required')
    ids = set()
    for op in ops:
        if not isinstance(op, dict):
            raise ValueError('Operation must be object')
        identifier(op['id'])
        if op['id'] in ids or op['id'] == 'overall':
            raise ValueError('Duplicate or reserved operation ID')
        ids.add(op['id'])
        if op['type'] == 'tone':
            allowed = {'id', 'type', 'mask', 'exposure', 'contrast', 'saturation', 'gamma', 'gains'}
            for key, bounds in {'exposure': (-2, 2), 'contrast': (0.5, 1.5),
                                'saturation': (0, 1.5), 'gamma': (0.5, 2)}.items():
                number(op.get(key, 0 if key == 'exposure' else 1), *bounds)
            gains = op.get('gains', [1, 1, 1])
            if not isinstance(gains, list) or len(gains) != 3:
                raise ValueError('Three gains required')
            for gain in gains:
                number(gain, 0.5, 1.5)
        elif op['type'] == 'overlay':
            allowed = {'id', 'type', 'mask', 'layer', 'blend', 'opacity', 'risk'}
            if op['risk'] not in HIGH | {'cosmetic'}:
                raise ValueError('Unknown risk')
            if op.get('blend', 'normal') not in {'normal', 'screen', 'multiply'}:
                raise ValueError('Unknown blend')
            number(op.get('opacity', 1), 0, 1)
            if 'layer' not in op:
                raise ValueError('Layer required')
        else:
            raise ValueError('Operation unsupported; geometry transforms forbidden')
        if set(op) - allowed or 'mask' not in op:
            raise ValueError('Unknown fields or missing mask')


def base(root, meta):
    a, mode = load_image(asset(root, meta['source']))
    protected = load_mask(asset(root, meta['protected']), a.shape[:2]) != 0
    if not protected.any() or list(a.shape) != meta['shape'] or mode != meta['mode']:
        raise ValueError('Invalid baseline')
    return a, mode, protected


def version(root, name):
    path = root / 'versions' / identifier(name)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Version escaped project')
    info = read(path / 'version.json')
    if digest(path / 'image.png') != info['image_sha256']:
        raise ValueError('Version image changed')
    a, _ = load_image(path / 'image.png')
    return path, info, a


def plan_record(root, name):
    directory = root / 'plans' / identifier(name)
    if not directory.resolve().is_relative_to(root.resolve()):
        raise ValueError('Plan escaped project')
    record = read(directory / 'plan.json')
    if canonical(record['plan']) != record['digest']:
        raise ValueError('Plan changed; approvals invalid')
    validate_operations(record['plan']['operations'])
    for op in record['plan']['operations']:
        asset(root, op['mask'])
        if op['type'] == 'overlay':
            asset(root, op['layer'])
    return directory, record


def process(root, source, protected, ops, *, mask_loader=None, image_loader=None):
    out = source.copy()
    for op in ops:
        mask = (mask_loader(op['mask'], out.shape[:2]) if mask_loader else
                load_mask(asset(root, op['mask']), out.shape[:2]))
        active = mask > 0
        layer = None
        if op['type'] == 'overlay':
            layer, _ = (image_loader(op['layer'], 'RGBA') if image_loader else
                        load_image(asset(root, op['layer']), 'RGBA'))
            if layer.shape[:2] != out.shape[:2]:
                raise ValueError('Layer dimensions differ; resampling forbidden')
            active &= layer[..., 3] > 0
            if op.get('opacity', 1) == 0:
                active[:] = False
        if np.any(active & protected):
            raise ValueError('Operation overlaps protected pixels')
        rows = np.flatnonzero(active.any(axis=1))
        if not len(rows):
            continue
        columns = np.flatnonzero(active.any(axis=0))
        x0, x1 = int(columns[0]), int(columns[-1]) + 1
        # Work only on the native-grid active bounds, in bounded row bands.
        # No image geometry changes, interpolation, or lower-resolution work buffer.
        for y0 in range(int(rows[0]), int(rows[-1]) + 1, 256):
            y1 = min(y0 + 256, int(rows[-1]) + 1)
            region = np.s_[y0:y1, x0:x1]
            if not active[region].any():
                continue
            rgb = out[region][..., :3].astype(np.float64) / 255
            weight = mask[region].astype(np.float64) / 255
            if op['type'] == 'tone':
                changed = rgb * (2 ** op.get('exposure', 0)) * np.array(op.get('gains', [1, 1, 1]))
                changed = (changed - 0.5) * op.get('contrast', 1) + 0.5
                gray = changed @ np.array([0.2126, 0.7152, 0.0722])
                changed = gray[..., None] + (changed - gray[..., None]) * op.get('saturation', 1)
                changed = np.clip(changed, 0, 1) ** (1 / op.get('gamma', 1))
            else:
                patch = layer[region]
                weight *= patch[..., 3] / 255 * op.get('opacity', 1)
                color = patch[..., :3].astype(np.float64) / 255
                blend = op.get('blend', 'normal')
                changed = color if blend == 'normal' else (1 - (1 - rgb) * (1 - color)
                                                           if blend == 'screen' else rgb * color)
            result = np.rint(np.clip(rgb * (1 - weight[..., None]) + changed * weight[..., None],
                                    0, 1) * 255).astype(np.uint8)
            untouched = weight == 0
            if not np.array_equal(result[untouched], out[region][..., :3][untouched]):
                raise ValueError('Unmasked pixels changed')
            out[region][..., :3] = result
    if not np.array_equal(out[protected], source[protected]):
        raise ValueError('Protected pixels changed')
    return out


def initialize(root, original, mask):
    if root.exists():
        raise ValueError('Project path must not exist')
    a, mode = load_image(original)
    protected = load_mask(mask, a.shape[:2])
    if not protected.any():
        raise ValueError('Protection mask must be nonempty')
    root.mkdir(parents=True)
    for name in ('assets', 'versions', 'plans'):
        (root / name).mkdir()
    src = capture(root, original); prot = capture(root, mask)
    v = root / 'versions' / 'v0000'; v.mkdir()
    Image.fromarray(a).save(v / 'image.png')
    write(v / 'version.json', {'parent': None, 'branch': 'main', 'plan': None,
                              'image_sha256': digest(v / 'image.png')}, True)
    write(v / 'report.json', check(a, a, protected), True)
    write(root / 'project.json', {'source': src, 'protected': prot, 'shape': list(a.shape),
                                 'mode': mode, 'head': 'v0000', 'branch': 'main',
                                 'branches': {'main': 'v0000'}}, True)
    return {'head': 'v0000', 'source_sha256': src['sha256']}


def execute(args):
    root = Path(args.project).resolve()
    if args.command == 'init':
        return initialize(root, args.original, args.protected)
    with locked(root):
        meta = read(root / 'project.json')
        original, mode, protected = base(root, meta)
        if args.command == 'plan':
            raw = read(args.file)
            if set(raw) != {'summary', 'operations'} or not isinstance(raw['summary'], str):
                raise ValueError('Plan requires summary and operations only')
            validate_operations(raw['operations'])
            _, parent_info, parent = version(root, meta['head'])
            for op in raw['operations']:
                for key in ('mask', 'layer'):
                    if key in op:
                        op[key] = capture(root, Path(args.file).resolve().parent / op[key])
                load_mask(asset(root, op['mask']), original.shape[:2])
                if op['type'] == 'overlay':
                    layer, _ = load_image(asset(root, op['layer']), 'RGBA')
                    if layer.shape[:2] != original.shape[:2]:
                        raise ValueError('Layer size mismatch')
            raw.update(parent=meta['head'], parent_sha256=parent_info['image_sha256'],
                       branch=meta['branch'], source_sha256=meta['source']['sha256'],
                       protected_sha256=meta['protected']['sha256'])
            directory = root / 'plans' / identifier(args.id); directory.mkdir()
            record = {'plan': raw, 'digest': canonical(raw)}
            write(directory / 'plan.json', record, True)
            return record
        if args.command in ('approve', 'run'):
            directory, record = plan_record(root, args.id)
            plan = record['plan']
            _, parent_info, parent = version(root, plan['parent'])
            if (plan['parent'] != meta['head'] or plan['branch'] != meta['branch'] or
                plan['parent_sha256'] != parent_info['image_sha256'] or
                plan['source_sha256'] != meta['source']['sha256'] or
                plan['protected_sha256'] != meta['protected']['sha256']):
                raise ValueError('Plan baseline/head changed; create a fresh plan')
            if (directory / 'result.json').exists():
                raise ValueError('Plan already executed; create a fresh plan')
            if args.command == 'approve':
                valid = {'overall'} | {op['id'] for op in plan['operations'] if op.get('risk') in HIGH}
                if args.scope not in valid or not args.note.strip():
                    raise ValueError('Invalid scope or empty approval quote')
                write(directory / ('approval-' + args.scope + '.json'),
                      {'digest': record['digest'], 'scope': args.scope, 'user_quote': args.note}, True)
                return {'recorded': args.scope, 'identity_authenticated': False}
            for scope in ['overall'] + [op['id'] for op in plan['operations'] if op.get('risk') in HIGH]:
                approval = read(directory / ('approval-' + scope + '.json'))
                if approval.get('digest') != record['digest'] or approval.get('scope') != scope or not approval.get('user_quote', '').strip():
                    raise ValueError('Missing or stale approval')
            inherited = check(original, parent, protected)
            if not inherited['pass']:
                raise ValueError('Parent failed acceptance')
            candidate = process(root, parent, protected, plan['operations'])
            report = check(original, candidate, protected)
            # Also check detail loss relative to parent, not just the original.
            parent_report = check(parent, candidate, protected)
            if not parent_report['pass']:
                report['pass'] = False
                report['errors'].extend('Parent: ' + x for x in parent_report['errors'])
            report['parent_edge_ratio'] = parent_report.get('edge_ratio')
            index = 1
            while (root / 'versions' / f'v{index:04d}').exists():
                index += 1
            name = f'v{index:04d}'; v = root / 'versions' / name; v.mkdir()
            Image.fromarray(candidate).save(v / 'image.png')
            write(v / 'version.json', {'parent': plan['parent'], 'branch': plan['branch'],
                                      'plan': args.id, 'digest': record['digest'],
                                      'image_sha256': digest(v / 'image.png')}, True)
            write(v / 'report.json', report, True)
            write(directory / 'result.json', {'version': name, 'pass': report['pass']}, True)
            if report['pass']:
                meta['head'] = name; meta['branches'][meta['branch']] = name
                write(root / 'project.json', meta)
            return {'version': name, 'pass': report['pass'], 'report': report}
        if args.command in ('inspect', 'review', 'export', 'checkout', 'branch'):
            v, info, candidate = version(root, args.version)
            if candidate.shape != original.shape:
                raise ValueError('Version dimensions changed')
            report = check(original, candidate, protected)
            stored = read(v / 'report.json')
            if not report['pass'] or not stored['pass']:
                raise ValueError('Version failed automatic acceptance')
            if args.command == 'inspect':
                inspection = read(Path(args.file).resolve())
                checks = inspection.get('checks', {})
                required = {'space', 'edges', 'lighting', 'effects'}
                if set(checks) != required or any(
                    not isinstance(item, dict) or item.get('decision') not in {'pass', 'fail'}
                    or not isinstance(item.get('observation'), str)
                    or not item['observation'].strip() for item in checks.values()):
                    raise ValueError('Inspection requires four decisions and observations')
                evidence = inspection.get('evidence')
                if not isinstance(evidence, list) or not evidence:
                    raise ValueError('Inspection evidence required')
                captured = []
                for item in evidence:
                    path = Path(item)
                    if not path.is_absolute() or not path.is_file():
                        raise ValueError('Inspection evidence must be existing absolute files')
                    with Image.open(path) as im:
                        im.verify()
                    captured.append({'path': str(path), 'sha256': digest(path)})
                passed = all(item['decision'] == 'pass' for item in checks.values())
                write(v / 'inspection.json', {'checks': checks, 'evidence': captured,
                      'pass': passed, 'image_sha256': info['image_sha256'],
                      'scope': 'Manual assistant observations; aesthetic correctness not certified'})
                return {'inspection': passed, 'version': args.version}
            if args.command == 'review':
                if not args.note.strip():
                    raise ValueError('Human review quote required')
                write(v / 'review.json', {'decision': args.decision, 'user_quote': args.note,
                                         'image_sha256': info['image_sha256']})
                return {'review': args.decision, 'version': args.version}
            if args.command == 'export':
                if info['plan'] is None:
                    raise ValueError('Baseline is not a retouched result')
                directory, record = plan_record(root, info['plan'])
                if info['digest'] != record['digest']:
                    raise ValueError('Version plan changed')
                for scope in ['overall'] + [op['id'] for op in record['plan']['operations'] if op.get('risk') in HIGH]:
                    approval = read(directory / ('approval-' + scope + '.json'))
                    if approval.get('digest') != record['digest'] or approval.get('scope') != scope or not approval.get('user_quote', '').strip():
                        raise ValueError('Approval invalid at export')
                _, pinfo, parent = version(root, info['parent'])
                if pinfo['image_sha256'] != record['plan']['parent_sha256']:
                    raise ValueError('Parent changed')
                expected = process(root, parent, protected, record['plan']['operations'])
                if not np.array_equal(expected, candidate) or not check(parent, candidate, protected)['pass']:
                    raise ValueError('Candidate does not match approved processing')
                # A tonal child still contains its parent's background/effects.
                ancestor = info
                visual_required = False
                while ancestor.get('plan') is not None:
                    _, ancestor_plan = plan_record(root, ancestor['plan'])
                    visual_required |= any(op.get('risk') in HIGH for op in ancestor_plan['plan']['operations'])
                    if ancestor.get('parent') is None:
                        break
                    _, ancestor, _ = version(root, ancestor['parent'])
                if visual_required:
                    inspection = read(v / 'inspection.json')
                    if not inspection.get('pass') or inspection.get('image_sha256') != info['image_sha256']:
                        raise ValueError('Visual inspection missing/stale/failed')
                    for evidence in inspection.get('evidence', []):
                        if digest(evidence['path']) != evidence['sha256']:
                            raise ValueError('Visual inspection evidence changed')
                review = read(v / 'review.json')
                if review.get('decision') != 'pass' or review.get('image_sha256') != info['image_sha256'] or not review.get('user_quote', '').strip():
                    raise ValueError('Human review missing/stale/failed')
                target = Path(args.output).resolve()
                if target.suffix.lower() != '.png' or target.exists() or target.is_relative_to(root):
                    raise ValueError('Export requires new PNG outside project')
                # Byte-copy the exact already validated PNG, exclusively.
                with (v / 'image.png').open('rb') as src, target.open('xb') as dst:
                    shutil.copyfileobj(src, dst)
                return {'export': str(target), 'sha256': digest(target), 'version': args.version}
            if args.command == 'branch':
                identifier(args.name)
                if args.name in meta['branches']:
                    raise ValueError('Branch exists')
                meta['branches'][args.name] = args.version; meta['branch'] = args.name
            meta['head'] = args.version
            meta['branches'][meta['branch']] = args.version
            write(root / 'project.json', meta)
            return {'head': meta['head'], 'branch': meta['branch']}
    raise ValueError('Unknown command')


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', required=True)
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('init'); s.add_argument('--original', required=True); s.add_argument('--protected', required=True)
    s = sub.add_parser('plan'); s.add_argument('--file', required=True); s.add_argument('--id', required=True)
    s = sub.add_parser('approve'); s.add_argument('--id', required=True); s.add_argument('--scope', required=True); s.add_argument('--note', required=True)
    s = sub.add_parser('run'); s.add_argument('--id', required=True)
    s = sub.add_parser('inspect'); s.add_argument('--version', required=True); s.add_argument('--file', required=True)
    s = sub.add_parser('review'); s.add_argument('--version', required=True); s.add_argument('--decision', choices=['pass', 'fail'], required=True); s.add_argument('--note', required=True)
    s = sub.add_parser('export'); s.add_argument('--version', required=True); s.add_argument('--output', required=True)
    s = sub.add_parser('checkout'); s.add_argument('--version', required=True)
    s = sub.add_parser('branch'); s.add_argument('--version', required=True); s.add_argument('--name', required=True)
    return p


def main():
    args = parser().parse_args()
    try:
        result = execute(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result.get('pass') is False else 0
    except (ValueError, OSError, KeyError, TypeError) as e:
        print('BLOCKED: ' + str(e), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
