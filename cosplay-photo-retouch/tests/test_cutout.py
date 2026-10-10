import sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from cutout import assets_from_mask,create,infer_mask

class CutoutTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.d=Path(self.t.name)
        self.a=np.arange(9*7*3,dtype=np.uint8).reshape(7,9,3)
        self.mask=np.zeros((7,9),dtype=np.uint8);self.mask[2:5,3:6]=128
        Image.fromarray(self.a).save(self.d/'original.png');Image.fromarray(self.mask).save(self.d/'mask.png')
    def test_every_rgb_pixel_retained(self):
        rgba,p,bg=assets_from_mask(self.a,self.mask,padding=0)
        np.testing.assert_array_equal(rgba[...,:3],self.a);np.testing.assert_array_equal(rgba[...,3],self.mask)
        np.testing.assert_array_equal(p+bg,np.full(self.mask.shape,255,dtype=np.uint8))
    def test_keep_restores_missed_subject(self):
        keep=np.zeros_like(self.mask);keep[1,1]=255
        rgba,p,b=assets_from_mask(self.a,self.mask,keep,padding=0)
        self.assertEqual(rgba[1,1,3],255);self.assertEqual(p[1,1],255);self.assertEqual(b[1,1],0)
    def test_original_alpha_respected(self):
        a=np.concatenate([self.a,np.full((7,9,1),100,dtype=np.uint8)],axis=2)
        rgba,_,_=assets_from_mask(a,self.mask,padding=0)
        self.assertEqual(rgba[3,4,3],50);np.testing.assert_array_equal(rgba[...,:3],self.a)
    def test_wrong_dimension_and_empty_rejected(self):
        for m in (self.mask[:-1],np.zeros_like(self.mask)):
            with self.assertRaises(ValueError):assets_from_mask(self.a,m)
    def test_padding_only_expands_protection(self):
        rgba,p,_=assets_from_mask(self.a,self.mask,padding=1)
        self.assertGreater(np.count_nonzero(p),np.count_nonzero(self.mask));np.testing.assert_array_equal(rgba[...,3],self.mask)
        with self.assertRaises(ValueError):assets_from_mask(self.a,self.mask,padding=41)
    def test_candidate_saved_and_never_overwritten(self):
        out=self.d/'out';r=create(self.d/'original.png',out,self.d/'mask.png',padding=0)
        self.assertEqual(r['status'],'CANDIDATE_REQUIRES_EDGE_REVIEW');self.assertFalse(r['rgb_resampled']);self.assertFalse(r['model_internal_resize'])
        with Image.open(out/'foreground-candidate.png') as im:np.testing.assert_array_equal(np.array(im)[...,:3],self.a)
        with self.assertRaisesRegex(ValueError,'new'):create(self.d/'original.png',out,self.d/'mask.png')
    def test_failure_does_not_create_output(self):
        Image.new('L',(2,2)).save(self.d/'bad.png');out=self.d/'failed'
        with self.assertRaises(ValueError):create(self.d/'original.png',out,self.d/'bad.png')
        self.assertFalse(out.exists())
    def test_orientation_rejected(self):
        im=Image.fromarray(self.a);exif=Image.Exif();exif[274]=6;im.save(self.d/'turned.png',exif=exif)
        with self.assertRaisesRegex(ValueError,'orientation'):create(self.d/'turned.png',self.d/'out',self.d/'mask.png')
    def fake_backend(self):
        folder=self.d/'models'/'models'/'u2netp';folder.mkdir(parents=True);(folder/'weights.onnx').write_bytes(b'test weights only')
        class Session:
            def model_dir(inner):return str(folder)
        calls=[]
        def remove(im,**kw):calls.append(kw);return Image.fromarray(self.mask)
        return types.SimpleNamespace(new_session=lambda *a,**kw:Session(),remove=remove),calls
    def test_mask_cache_reused(self):
        module,calls=self.fake_backend()
        with patch.dict(sys.modules,{'rembg':module}),patch('importlib.metadata.version',return_value='test'):
            a,r=infer_mask(self.a,'source','u2netp',self.d/'models');b,s=infer_mask(self.a,'source','u2netp',self.d/'models')
        self.assertEqual(len(calls),1);self.assertTrue(calls[0]['only_mask']);self.assertTrue(s['cache_hit']);np.testing.assert_array_equal(a,b)
    def test_warm_cache_never_loads_session(self):
        module,calls=self.fake_backend()
        with patch.dict(sys.modules,{'rembg':module}),patch('importlib.metadata.version',return_value='test'):
            infer_mask(self.a,'source','u2netp',self.d/'models')
            def forbidden(*a,**kw):raise AssertionError('Model loaded on cache hit')
            module.new_session=forbidden
            _,report=infer_mask(self.a,'source','u2netp',self.d/'models')
            self.assertFalse(report['session_loaded'])
    def test_cache_tamper_blocks(self):
        module,calls=self.fake_backend()
        with patch.dict(sys.modules,{'rembg':module}),patch('importlib.metadata.version',return_value='test'):
            infer_mask(self.a,'source','u2netp',self.d/'models')
            for f in (self.d/'models'/'mask-cache').glob('*.png'):f.write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'changed'):infer_mask(self.a,'source','u2netp',self.d/'models')
if __name__=='__main__':unittest.main()
