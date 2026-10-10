"""Place one native RGBA asset on a locked photo grid, without resampling."""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image
from cutout import load_source, mask_file, sha


def assemble(source_path, asset_path, protect_path, output_dir, x, y):
    source_path, asset_path, protect_path = map(Path, (source_path, asset_path, protect_path))
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise ValueError('Output directory must be new')
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (x, y)):
        raise ValueError('Position must use integer native pixels')
    before = {str(p): sha(p) for p in (source_path, asset_path, protect_path)}
    source, _ = load_source(source_path)
    height, width = source.shape[:2]
    protect = mask_file(protect_path, (width, height))
    if not protect.any():
        raise ValueError('Empty subject protection')
    with Image.open(asset_path) as im:
        if im.format != 'PNG' or im.mode != 'RGBA' or getattr(im, 'n_frames', 1) != 1:
            raise ValueError('Asset must be static RGBA PNG')
        if im.getexif().get(274, 1) != 1 or any(k in im.info for k in ('icc_profile', 'gamma', 'chromaticity')):
            raise ValueError('Asset orientation/color preparation required; no silent conversion')
        aw, ah = im.size
        if x < 0 or y < 0 or x + aw > width or y + ah > height:
            raise ValueError('Asset outside canvas; no clipping or resize')
        asset = np.array(im)
    alpha = asset[..., 3]
    if not alpha.any() or np.all(alpha == 255):
        raise ValueError('Require visible transparent local asset, not opaque photo')
    if np.any((alpha > 0) & (protect[y:y+ah, x:x+aw] > 0)):
        raise ValueError('Visible asset intersects protected subject; revise placement')
    layer = np.zeros((height, width, 4), dtype=np.uint8)
    layer[y:y+ah, x:x+aw] = asset
    if any(sha(p) != before[str(p)] for p in (source_path, asset_path, protect_path)):
        raise ValueError('Input changed')
    output_dir.mkdir(parents=True)
    path = output_dir / 'layer.png'
    Image.fromarray(layer).save(path)
    with Image.open(path) as im:
        if not np.array_equal(np.array(im), layer):
            raise ValueError('Saved layer failed native-pixel check; do not use')
    report = {'status': 'ASSET_ONLY_REQUIRES_RETOUCH_PLAN', 'canvas': [width, height],
              'asset_size': [aw, ah], 'position': [x, y], 'resampled': False,
              'source_modified': False, 'inputs_sha256': before, 'layer_sha256': sha(path)}
    (output_dir / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'asset', 'protect', 'output-dir'):
        p.add_argument('--' + name, required=True)
    p.add_argument('--x', required=True, type=int)
    p.add_argument('--y', required=True, type=int)
    a = p.parse_args()
    try:
        print(json.dumps(assemble(a.source, a.asset, a.protect, a.output_dir, a.x, a.y), indent=2))
        return 0
    except Exception as e:
        p.exit(2, 'BLOCKED: ' + str(e) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
