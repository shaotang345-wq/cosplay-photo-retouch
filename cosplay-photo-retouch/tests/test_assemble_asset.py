import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from assemble_asset import assemble


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.d = Path(self.temp.name)
        self.source = self.d/'source.png'; self.asset = self.d/'asset.png'; self.protect = self.d/'protect.png'
        Image.new('RGB', (12, 10), (40, 60, 80)).save(self.source)
        self.a = np.zeros((3, 4, 4), dtype=np.uint8); self.a[1, 1] = [120, 40, 60, 100]
        Image.fromarray(self.a).save(self.asset)
        protect = np.zeros((10, 12), dtype=np.uint8); protect[0:2, 0:2] = 255
        Image.fromarray(protect).save(self.protect)
    def run_asset(self, x=4, y=4):
        return assemble(self.source, self.asset, self.protect, self.d/'out', x, y)
    def test_exact_placement_and_source_unchanged(self):
        original = self.source.read_bytes(); r = self.run_asset()
        actual = np.array(Image.open(self.d/'out/layer.png'))
        expected = np.zeros((10, 12, 4), dtype=np.uint8); expected[4:7, 4:8] = self.a
        np.testing.assert_array_equal(actual, expected)
        self.assertEqual(original, self.source.read_bytes()); self.assertFalse(r['resampled'])
    def test_outside_canvas_rejected_before_output(self):
        for x, y in ((-1, 0), (10, 0), (0, 9)):
            with self.assertRaisesRegex(ValueError, 'canvas'): self.run_asset(x, y)
        self.assertFalse((self.d/'out').exists())
    def test_subject_overlap_rejected(self):
        with self.assertRaisesRegex(ValueError, 'protected'): self.run_asset(0, 0)
    def test_opaque_and_empty_rejected(self):
        for a in (0, 255):
            self.a[...,3] = a; Image.fromarray(self.a).save(self.asset)
            with self.assertRaisesRegex(ValueError, 'transparent'): self.run_asset()
    def test_bad_mask_and_asset_modes(self):
        Image.new('L', (2, 2), 255).save(self.protect)
        with self.assertRaises(ValueError): self.run_asset()
        Image.new('L', (12, 10), 255).save(self.protect)
        Image.new('RGB', (4, 3)).save(self.asset)
        with self.assertRaisesRegex(ValueError, 'RGBA'): self.run_asset()
    def test_existing_output_and_fractional_position_rejected(self):
        with self.assertRaisesRegex(ValueError, 'integer'): self.run_asset(1.5, 2)
        self.run_asset()
        with self.assertRaisesRegex(ValueError, 'new'): self.run_asset()


if __name__ == '__main__': unittest.main()
