"""Synthetic behavioral tests, not photographic aesthetic validation."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np
from PIL import Image
SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from acceptance import check, load_image
from retouch import execute, read, digest, write, capture, process

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.d = Path(self.temp.name); self.root = self.d / 'project'
        y, x = np.indices((24, 32))
        self.a = np.stack([(x*17+y*9)%170+30, (y*23)%160+40, (x*11)%150+50], axis=2).astype(np.uint8)
        self.protect = np.zeros((24, 32), dtype=np.uint8); self.protect[6:18, 10:22] = 255
        self.mask = np.where(self.protect, 0, 255).astype(np.uint8)
        for name, a in [('source', self.a), ('protect', self.protect), ('mask', self.mask)]:
            Image.fromarray(a).save(self.d / (name+'.png'))
        self.call('init', original=str(self.d/'source.png'), protected=str(self.d/'protect.png'))
    def call(self, command, **kw):
        return execute(argparse.Namespace(project=str(self.root), command=command, **kw))
    def plan(self, id='p1', ops=None):
        ops = ops or [{'id':'tone','type':'tone','mask':'mask.png','saturation':0.98}]
        path = self.d/(id+'.json'); path.write_text(json.dumps({'summary':'synthetic test','operations':ops}), encoding='utf-8')
        return self.call('plan', file=str(path), id=id)
    def approve(self, id='p1', scope='overall'):
        self.call('approve', id=id, scope=scope, note='Synthetic test approval only')
    def success(self):
        self.plan(); self.approve(); result = self.call('run', id='p1')
        self.assertTrue(result['pass']); return result['version']
    def inspected_high_risk(self):
        layer=np.zeros((24,32,4),dtype=np.uint8);layer[1:4,1:4,:3]=120;layer[1:4,1:4,3]=64
        Image.fromarray(layer).save(self.d/'layer.png')
        self.plan(ops=[{'id':'fx','type':'overlay','mask':'mask.png','layer':'layer.png','risk':'strong_effect','blend':'screen','opacity':0.2}])
        self.approve();self.approve(scope='fx');r=self.call('run',id='p1')
        self.assertTrue(r['pass']);name=r['version']
        self.call('review',version=name,decision='pass',note='synthetic direct export instruction')
        return name
    def inspection_file(self, decision='pass'):
        path=self.d/'inspection-input.json'
        path.write_text(json.dumps({'checks':{k:{'decision':decision,'observation':'Synthetic fixture only'} for k in ['space','edges','lighting','effects']},'evidence':[str(self.d/'source.png')]}),encoding='utf-8')
        return str(path)
    def test_high_risk_export_requires_inspection(self):
        name=self.inspected_high_risk();out=self.d/'final.png'
        with self.assertRaises(OSError):self.call('export',version=name,output=str(out))
        self.assertFalse(out.exists())
        self.call('inspect',version=name,file=self.inspection_file())
        self.call('export',version=name,output=str(out))
        self.assertEqual(digest(out),digest(self.root/'versions'/name/'image.png'))
    def test_tonal_child_of_high_risk_still_needs_inspection(self):
        self.inspected_high_risk();self.plan(id='p2');self.approve(id='p2')
        r=self.call('run',id='p2');self.assertTrue(r['pass']);name=r['version']
        self.call('review',version=name,decision='pass',note='synthetic export request')
        with self.assertRaises(OSError):self.call('export',version=name,output=str(self.d/'child.png'))
        self.call('inspect',version=name,file=self.inspection_file())
        self.call('export',version=name,output=str(self.d/'child.png'))
    def test_failed_visual_inspection_blocks_export(self):
        name=self.inspected_high_risk()
        self.call('inspect',version=name,file=self.inspection_file('fail'))
        with self.assertRaisesRegex(ValueError,'Visual inspection'):
            self.call('export',version=name,output=str(self.d/'bad.png'))
        self.assertFalse((self.d/'bad.png').exists())
    def test_visual_inspection_hash_stale(self):
        name=self.inspected_high_risk();self.call('inspect',version=name,file=self.inspection_file())
        path=self.root/'versions'/name/'inspection.json';r=read(path);r['image_sha256']='stale';write(path,r)
        with self.assertRaisesRegex(ValueError,'Visual inspection'):
            self.call('export',version=name,output=str(self.d/'bad.png'))
    def test_visual_inspection_evidence_changed(self):
        name=self.inspected_high_risk();self.call('inspect',version=name,file=self.inspection_file())
        Image.new('RGB',(32,24),255).save(self.d/'source.png')
        with self.assertRaisesRegex(ValueError,'evidence changed'):
            self.call('export',version=name,output=str(self.d/'bad.png'))
    def test_visual_inspection_requires_observations(self):
        name=self.inspected_high_risk();path=Path(self.inspection_file());r=read(path);r['checks']['edges']['observation']='';write(path,r)
        with self.assertRaisesRegex(ValueError,'four decisions'):
            self.call('inspect',version=name,file=str(path))
    def test_visual_inspection_requires_evidence(self):
        name=self.inspected_high_risk();path=Path(self.inspection_file());r=read(path);r['evidence']=[];write(path,r)
        with self.assertRaisesRegex(ValueError,'evidence required'):
            self.call('inspect',version=name,file=str(path))
    def test_native_grid_and_exact_protection(self):
        name = self.success(); b, mode = load_image(self.root/'versions'/name/'image.png')
        self.assertEqual(b.shape,self.a.shape); self.assertEqual(mode,'RGB')
        np.testing.assert_array_equal(b[self.protect!=0],self.a[self.protect!=0])
        self.assertTrue(np.any(b[self.mask!=0]!=self.a[self.mask!=0]))
    def test_no_approval_blocks(self):
        self.plan()
        with self.assertRaises(OSError): self.call('run',id='p1')
        self.assertEqual(read(self.root/'project.json')['head'],'v0000')
    def test_high_risk_separate_approval(self):
        layer=np.zeros((24,32,4),dtype=np.uint8); layer[...,:3]=100; layer[1:4,1:4,3]=100
        Image.fromarray(layer).save(self.d/'layer.png')
        self.plan(ops=[{'id':'fx','type':'overlay','mask':'mask.png','layer':'layer.png','risk':'strong_effect','blend':'screen','opacity':0.2}]); self.approve()
        with self.assertRaises(OSError): self.call('run',id='p1')
        self.approve(scope='fx'); self.assertTrue(self.call('run',id='p1')['pass'])
    def test_protection_overlap_blocks(self):
        Image.new('L',(32,24),255).save(self.d/'mask.png'); self.plan(); self.approve()
        with self.assertRaisesRegex(ValueError,'overlaps'): self.call('run',id='p1')
    def test_mask_size_mismatch(self):
        Image.new('L',(16,12),255).save(self.d/'mask.png')
        with self.assertRaisesRegex(ValueError,'dimensions'): self.plan()
    def test_layer_size_mismatch(self):
        Image.new('RGBA',(4,4)).save(self.d/'layer.png')
        with self.assertRaisesRegex(ValueError,'size'):
            self.plan(ops=[{'id':'fx','type':'overlay','mask':'mask.png','layer':'layer.png','risk':'cosmetic'}])
    def test_plan_tamper(self):
        self.plan(); self.approve(); path=self.root/'plans'/'p1'/'plan.json'
        data=read(path); data['plan']['summary']='changed'; write(path,data)
        with self.assertRaisesRegex(ValueError,'Plan changed'): self.call('run',id='p1')
    def test_asset_tamper(self):
        r=self.plan(); self.approve(); (self.root/r['plan']['operations'][0]['mask']['path']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'Asset changed'): self.call('run',id='p1')
    def test_export_human_gate_and_exact_bytes(self):
        name=self.success(); out=self.d/'final.png'
        with self.assertRaises(OSError): self.call('export',version=name,output=str(out))
        self.assertFalse(out.exists()); self.call('review',version=name,decision='fail',note='test fail')
        with self.assertRaisesRegex(ValueError,'Human review'): self.call('export',version=name,output=str(out))
        self.call('review',version=name,decision='pass',note='test pass'); self.call('export',version=name,output=str(out))
        self.assertEqual(digest(out),digest(self.root/'versions'/name/'image.png'))
        with self.assertRaisesRegex(ValueError,'new PNG'): self.call('export',version=name,output=str(out))
    def test_version_tamper(self):
        name=self.success(); Image.new('RGB',(32,24)).save(self.root/'versions'/name/'image.png')
        with self.assertRaisesRegex(ValueError,'Version image changed'): self.call('review',version=name,decision='pass',note='test')
    def test_failed_acceptance_blocks_export_and_head(self):
        self.plan(ops=[{'id':'dim','type':'tone','mask':'mask.png','contrast':0.5}]); self.approve(); r=self.call('run',id='p1')
        self.assertFalse(r['pass']); self.assertEqual(read(self.root/'project.json')['head'],'v0000')
        for command,kw in [('review',{'decision':'pass','note':'test'}),('export',{'output':str(self.d/'bad.png')})]:
            with self.assertRaisesRegex(ValueError,'failed automatic'): self.call(command,version=r['version'],**kw)
        self.assertFalse((self.d/'bad.png').exists())
    def test_branch_rollback_history(self):
        name=self.success(); self.call('branch',version='v0000',name='cool')
        self.assertEqual(read(self.root/'project.json')['branches']['main'],name)
        self.plan(id='p2'); self.approve(id='p2'); r=self.call('run',id='p2'); self.assertTrue(r['pass'])
        self.call('checkout',version='v0000'); self.assertTrue((self.root/'versions'/r['version']/'image.png').exists())
    def test_stale_parent(self):
        self.plan(); self.approve(); self.plan(id='p2'); self.approve(id='p2'); self.call('run',id='p2')
        with self.assertRaisesRegex(ValueError,'baseline/head changed'): self.call('run',id='p1')
    def test_repeat_plan(self):
        self.success()
        with self.assertRaises(ValueError): self.call('run',id='p1')
    def test_rgba_alpha(self):
        a=np.concatenate([self.a,np.full((24,32,1),170,dtype=np.uint8)],axis=2); Image.fromarray(a).save(self.d/'rgba.png')
        self.root=self.d/'rgba-project'; self.call('init',original=str(self.d/'rgba.png'),protected=str(self.d/'protect.png'))
        name=self.success(); b,_=load_image(self.root/'versions'/name/'image.png'); np.testing.assert_array_equal(b[...,3],a[...,3])
    def test_unknown_nan_and_id(self):
        for ops in ([{'id':'x','type':'resize','mask':'mask.png'}],[{'id':'../bad','type':'tone','mask':'mask.png'}],
                    [{'id':'bad','type':'tone','mask':'mask.png','exposure':float('nan')}],[{'id':'overall','type':'tone','mask':'mask.png'}]):
            with self.assertRaises(ValueError): self.plan(ops=ops)
    def test_acceptance_detects_pixel_loss_and_size(self):
        b=self.a.copy(); b[8,12]=0; self.assertFalse(check(self.a,b,self.protect)['pass'])
        b=self.a.copy(); b[self.mask!=0]=128; self.assertFalse(check(self.a,b,self.protect)['pass'])
        self.assertFalse(check(self.a,b[:-1],self.protect)['pass'])
    def test_metadata_and_mode(self):
        path=self.d/'metadata.png'; Image.fromarray(self.a).save(path,icc_profile=b'unsupported')
        with self.assertRaisesRegex(ValueError,'ICC'): load_image(path)
        im=Image.fromarray(self.a); exif=Image.Exif(); exif[274]=6; im.save(path,exif=exif)
        with self.assertRaisesRegex(ValueError,'orientation'): load_image(path)
        Image.new('L',(32,24)).save(path)
        with self.assertRaisesRegex(ValueError,'mode'): load_image(path)
    def test_acceptance_cli_exit_and_no_overwrite(self):
        command=[sys.executable,str(SCRIPTS/'acceptance.py'),str(self.d/'source.png'),str(self.d/'source.png'),str(self.d/'protect.png'),'--report',str(self.d/'report.json')]
        first=subprocess.run(command,capture_output=True,text=True,encoding="utf-8",env=dict(__import__("os").environ,PYTHONUTF8="1")); self.assertEqual(first.returncode,0,first.stderr)
        self.assertNotEqual(subprocess.run(command,capture_output=True,text=True,encoding="utf-8",env=dict(__import__("os").environ,PYTHONUTF8="1")).returncode,0)
    def test_installer(self):
        command=[sys.executable,str(SCRIPTS/'install.py'),'--skills-dir',str(self.d/'skills')]
        first=subprocess.run(command,capture_output=True,text=True,encoding="utf-8",env=dict(__import__("os").environ,PYTHONUTF8="1")); self.assertEqual(first.returncode,0,first.stderr)
        self.assertEqual(digest(self.d/'skills'/'cosplay-photo-retouch'/'SKILL.md'),digest(SCRIPTS.parent/'SKILL.md'))
        self.assertNotEqual(subprocess.run(command,capture_output=True,text=True,encoding="utf-8",env=dict(__import__("os").environ,PYTHONUTF8="1")).returncode,0)
    def test_empty_protection_rejected(self):
        Image.new('L',(32,24)).save(self.d/'empty.png'); self.root=self.d/'empty-project'
        with self.assertRaisesRegex(ValueError,'nonempty'):
            self.call('init',original=str(self.d/'source.png'),protected=str(self.d/'empty.png'))
        self.assertFalse(self.root.exists())
    def test_unsupported_format(self):
        Image.fromarray(self.a).save(self.d/'source.bmp')
        with self.assertRaisesRegex(ValueError,'format'): load_image(self.d/'source.bmp')
    def test_alpha_loss_detected(self):
        a=np.concatenate([self.a,np.full((24,32,1),170,dtype=np.uint8)],axis=2)
        b=a.copy(); b[0,0,3]=169
        self.assertIn('Alpha changed',check(a,b,self.protect)['errors'])
    def test_outside_edit_mask_exact(self):
        small=np.zeros((24,32),dtype=np.uint8); small[1:3,1:3]=128
        Image.fromarray(small).save(self.d/'mask.png'); name=self.success()
        b,_=load_image(self.root/'versions'/name/'image.png')
        np.testing.assert_array_equal(b[small==0],self.a[small==0])
    def test_retouch_cli_help(self):
        result=subprocess.run([sys.executable,str(SCRIPTS/'retouch.py'),'--help'],capture_output=True,text=True,encoding="utf-8",env=dict(__import__("os").environ,PYTHONUTF8="1"))
        self.assertEqual(result.returncode,0,result.stderr); self.assertIn('export',result.stdout)
    def test_sparse_operation_across_row_bands(self):
        a=np.full((600,40,3),100,dtype=np.uint8); p=np.zeros((600,40),dtype=bool);p[:,20:25]=True
        m=np.zeros((600,40),dtype=np.uint8);m[2:5,2:5]=255;m[580:590,30:35]=255
        Image.fromarray(m).save(self.d/'band-mask.png')
        op={'type':'tone','mask':capture(self.root,self.d/'band-mask.png'),'exposure':1}
        b=process(self.root,a,p,[op]);expected=a.copy();expected[m!=0]=200
        np.testing.assert_array_equal(b,expected)
    def test_fractional_overlay_across_row_bands(self):
        a=np.full((600,40,4),100,dtype=np.uint8);a[...,3]=170
        p=np.zeros((600,40),dtype=bool);p[:,20:25]=True
        m=np.full((600,40),255,dtype=np.uint8);m[p]=0
        layer=np.full((600,40,4),200,dtype=np.uint8);layer[...,3]=128
        Image.fromarray(m).save(self.d/'band-mask.png');Image.fromarray(layer).save(self.d/'band-layer.png')
        op={'type':'overlay','mask':capture(self.root,self.d/'band-mask.png'),
            'layer':capture(self.root,self.d/'band-layer.png'),'blend':'normal','opacity':1}
        b=process(self.root,a,p,[op]);expected=a.copy();expected[~p,:3]=150
        np.testing.assert_array_equal(b,expected)
    def test_zero_opacity_does_not_overlap_or_change(self):
        layer=np.full((24,32,4),255,dtype=np.uint8);Image.fromarray(layer).save(self.d/'zero-layer.png')
        Image.new('L',(32,24),255).save(self.d/'zero-mask.png')
        op={'type':'overlay','mask':capture(self.root,self.d/'zero-mask.png'),
            'layer':capture(self.root,self.d/'zero-layer.png'),'opacity':0}
        b=process(self.root,self.a,self.protect!=0,[op]);np.testing.assert_array_equal(b,self.a)

if __name__=='__main__':
    unittest.main()
