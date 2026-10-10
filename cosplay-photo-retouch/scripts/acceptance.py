"""Deterministic pixel checks; NOT semantic sharpness certification."""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image


def load_image(path, mode=None):
    with Image.open(path) as im:
        allowed_formats = {'PNG', 'JPEG'} if mode is None else {'PNG'}
        if im.format not in allowed_formats:
            raise ValueError('Unsupported format; masks/layers require PNG')
        if getattr(im, 'n_frames', 1) != 1:
            raise ValueError('Multi-frame images unsupported')
        if im.getexif().get(274, 1) != 1:
            raise ValueError('EXIF orientation must be 1; no auto rotation')
        if any(im.info.get(k) is not None for k in ('icc_profile', 'gamma', 'chromaticity')):
            raise ValueError('ICC/gamma/chromaticity unsupported; confirm 8-bit sRGB')
        unsupported = im.mode not in ('RGB', 'RGBA') if mode is None else im.mode != mode
        if unsupported:
            raise ValueError('Unsupported mode: ' + im.mode)
        return np.array(im), im.mode


def load_mask(path, size):
    a, _ = load_image(path, 'L')
    if a.shape != size:
        raise ValueError('Mask dimensions differ; resampling forbidden')
    return a


def energy(a, protected):
    gray = a[..., :3].astype(np.float64) @ np.array([0.2126, 0.7152, 0.0722])
    dx = np.abs(np.diff(gray, axis=1))
    dy = np.abs(np.diff(gray, axis=0))
    mx = ~(protected[:, 1:] | protected[:, :-1])
    my = ~(protected[1:, :] | protected[:-1, :])
    count = int(mx.sum() + my.sum())
    return float((dx[mx].sum() + dy[my].sum()) / count) if count else 0.0


def check(original, candidate, protected, *, before_energy=None):
    errors = []
    if original.shape != candidate.shape:
        return {'pass': False, 'errors': ['Dimensions or channel count changed']}
    if protected.shape != original.shape[:2] or not protected.any():
        return {'pass': False, 'errors': ['Protection mask invalid or empty']}
    protected = protected != 0
    if not np.array_equal(original[protected], candidate[protected]):
        errors.append('Protected pixels changed')
    if original.shape[2] == 4 and not np.array_equal(original[..., 3], candidate[..., 3]):
        errors.append('Alpha changed')
    # Trusted caller may reuse source energy bound to the unchanged source/mask hashes.
    before = energy(original, protected) if before_energy is None else before_energy
    if isinstance(before, bool) or not isinstance(before, (int, float)) or not np.isfinite(before) or before < 0:
        raise ValueError("Invalid cached original edge energy")
    after = energy(candidate, protected)
    ratio = after / before if before > 1e-9 else None
    if ratio is not None and ratio < 0.85:
        errors.append('Edge-energy loss below 0.85; human review cannot override')
    return {'pass': not errors, 'errors': errors, 'edge_energy_before': before,
            'edge_energy_after': after, 'edge_ratio': ratio,
            'human_review_required': True,
            'scope': 'Pixel invariants and heuristic only; mask coverage not certified'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('original'); p.add_argument('candidate'); p.add_argument('protected')
    p.add_argument('--report', required=True)
    args = p.parse_args()
    try:
        a, am = load_image(args.original); b, bm = load_image(args.candidate)
        mask = load_mask(args.protected, a.shape[:2])
        report = check(a, b, mask)
        if am != bm:
            report['pass'] = False; report['errors'].append('Mode changed')
    except (ValueError, OSError) as e:
        report = {'pass': False, 'errors': [str(e)]}
    target = Path(args.report)
    if target.exists() or target.resolve() in {Path(x).resolve() for x in
                                             (args.original, args.candidate, args.protected)}:
        p.error('Report must be a new path, separate from input files')
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['pass'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
