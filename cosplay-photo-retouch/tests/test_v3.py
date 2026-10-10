import sys,tempfile,unittest,copy
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import retouch as r
from v3 import Project,MODES
class V3Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.d=Path(self.tmp.name)
  y,x=np.indices((48,64));self.a=np.stack([(x*7+y*3)%150+40,(x*3)%130+45,(y*5)%120+50],-1).astype('uint8')
  self.freeze=np.zeros((48,64),dtype='uint8');self.freeze[14:30,22:40]=255
  self.subject=self.freeze.copy();self.subject[10:40,20:43]=255
  self.bg=np.where(self.subject,0,255).astype('uint8');self.right=self.bg.copy();self.right[:,:44]=0
  for name,array in [('src',self.a),('freeze',self.freeze),('subject',self.subject),('bg',self.bg),('right',self.right)]:Image.fromarray(array).save(self.d/(name+'.png'))
  self.root=self.d/'project';r.initialize(self.root,self.d/'src.png',self.d/'freeze.png');self.p=Project(self.root);self.p.attach(self.d/'subject.png')
 def layer(self,mask='bg',sat=.98):return {'module':'background','op':{'id':'grade','type':'tone','mask':str(self.d/(mask+'.png')),'saturation':sat}}
 def raw(self,pid='p1',layers=None,mode='standard',allowed='bg'):
  return {'id':pid,'do':['background only'],'do_not':['face','geometry'],'layers':layers if layers is not None else [self.layer()],
   'scope':{'allowed':str(self.d/(allowed+'.png')),'freeze':str(self.d/'freeze.png'),'geometry_lock':True},'mode':mode}
 def runplan(self,raw):
  self.p.prepare(raw);self.p.approve(raw['id'],'overall','Synthetic test authorization');return self.p.run(raw['id'])
 def test_canvas_freeze_geometry(self):
  res=self.runplan(self.raw());b=self.p.picture(res['version']);self.assertEqual(b.shape,self.a.shape);np.testing.assert_array_equal(b[self.subject>0],self.a[self.subject>0])
 def test_geometry_transform_rejected(self):
  layer=self.layer();layer['op']['type']='warp'
  with self.assertRaises(ValueError):self.p.prepare(self.raw(layers=[layer]))
 def test_geometry_tone_allowed_outside_freeze(self):
  m=np.where((self.subject>0)&(self.freeze==0),255,0).astype('uint8');Image.fromarray(m).save(self.d/'skin.png')
  l=self.layer('skin');l['module']='retouch'
  res=self.runplan(self.raw(layers=[l],allowed='skin'));b=self.p.picture(res['version'])
  np.testing.assert_array_equal(b[self.freeze>0],self.a[self.freeze>0]);self.assertFalse(np.array_equal(b[m>0],self.a[m>0]))
 def test_background_cannot_touch_face(self):
  with self.assertRaisesRegex(ValueError,'subject'):self.runplan(self.raw(layers=[self.layer('subject')],allowed='subject'))
  self.assertEqual(self.p.state['head'],'base')
 def test_modification_scope(self):
  with self.assertRaisesRegex(ValueError,'Scope'):self.runplan(self.raw(allowed='right'))
  self.assertEqual(self.p.state['head'],'base')
 def test_pixel_freeze_overlap(self):
  l=self.layer('freeze');l['module']='retouch'
  with self.assertRaisesRegex(ValueError,'frozen'):self.runplan(self.raw(layers=[l],allowed='freeze'))
 def test_cache_reuse(self):
  calls=[]
  for _ in range(2):self.p.cached('face',1,['face'],{'mask':'v1'},lambda:calls.append(1) or {'ok':1})
  self.assertEqual(len(calls),1);self.assertEqual(self.p.hits,1)
 def test_reference_cache(self):
  calls=[]
  for _ in range(2):self.p.cached('ref',3,[],{'reference_hash':'abc'},lambda:calls.append(1) or {'role':'color'})
  self.assertEqual(len(calls),1)
 def test_partial_invalidation(self):
  counts={'face':0,'env':0}
  def f(k):counts[k]+=1;return counts[k]
  self.p.cached('face',1,['face'],{},lambda:f('face'));self.p.cached('env',2,['environment_light'],{},lambda:f('env'))
  changed=self.p.invalidate('background');self.assertNotIn('face',changed)
  self.p.cached('face',1,['face'],{},lambda:f('face'));self.p.cached('env',2,['environment_light'],{},lambda:f('env'))
  self.assertEqual(counts,{'face':1,'env':2})
 def test_budget(self):
  self.p.prepare(self.raw());self.p.approve('p1','overall','Test approval')
  self.p.attempt('p1','right');self.p.attempt('p1','left')
  with self.assertRaisesRegex(ValueError,'STOP'):self.p.attempt('p1','top')
 def test_correction_budget(self):
  self.p.prepare(self.raw());self.p.approve('p1','overall','Test approval');self.p.attempt('p1','right','correction')
  with self.assertRaisesRegex(ValueError,'STOP'):self.p.attempt('p1','left','correction')
 def test_budget_cannot_reset_with_new_plan(self):
  self.p.prepare(self.raw());self.p.approve('p1','overall','test')
  self.p.attempt('p1','a');self.p.attempt('p1','b')
  self.p.prepare(self.raw('p2'));self.p.approve('p2','overall','test')
  with self.assertRaisesRegex(ValueError,'STOP'):self.p.attempt('p2','c')
 def test_revision_uses_existing_recipe(self):
  self.runplan(self.raw());raw=self.raw('p2');raw.pop('layers');raw['updates']={'grade':{'saturation':.97}}
  self.p.revise(raw);self.p.approve('p2','overall','test');res=self.p.run('p2')
  self.assertEqual(self.p.info(res['version'])['recipe'][0]['op']['saturation'],.97)
 def test_fast_no_generation(self):
  self.p.prepare(self.raw(mode='fast'));self.p.approve('p1','overall','Test approval')
  with self.assertRaises(ValueError):self.p.attempt('p1','right')
 def test_noop(self):
  result=self.runplan(self.raw(layers=[self.layer(sat=1)]));self.assertEqual(result['status'],'NO_ACTION_REQUIRED');self.assertEqual(self.p.state['head'],'base')
 def test_same_recipe_noop_cache(self):
  self.runplan(self.raw());res=self.runplan(self.raw('p2'));self.assertEqual(res['status'],'NO_ACTION_REQUIRED');self.assertGreater(self.p.hits,0)
 def test_differential_fire_right_only(self):
  fx=np.zeros((48,64,4),dtype='uint8');fx[1:9,1:63]=[255,100,20,100];Image.fromarray(fx).save(self.d/'fire.png')
  layer={'module':'vfx','op':{'id':'fire','type':'overlay','mask':str(self.d/'bg.png'),'layer':str(self.d/'fire.png'),'opacity':.4,'blend':'screen','risk':'cosmetic'}}
  self.runplan(self.raw(layers=[layer]));before=self.p.picture(self.p.state['head'])
  mask=self.bg.copy();mask[:,44:]//=2;Image.fromarray(mask).save(self.d/'weaker.png');layer['op']['mask']=str(self.d/'weaker.png')
  self.runplan(self.raw('p2',[layer],allowed='right'));after=self.p.picture(self.p.state['head'])
  np.testing.assert_array_equal(before[:,:44],after[:,:44]);self.assertFalse(np.array_equal(before[:,44:],after[:,44:]))
  self.assertEqual(self.p.state['telemetry'][-1]['generation_reservations'],0)
 def test_modes_previews_and_hard_gates(self):
  counts=[]
  for i,mode in enumerate(MODES):
   self.p.checkout('base');res=self.runplan(self.raw('mode'+str(i),mode=mode));vid=res['version']
   result=self.p.previews(vid,[[0,0,10,10]]*5);counts.append(len(result['files']))
   self.assertTrue(self.p.info(vid)['qc']['pass'])
  self.assertEqual(counts,[1,3,5])
 def test_branch_rollback(self):
  first=self.runplan(self.raw())['version'];self.p.checkout('base','other');self.assertEqual(self.p.state['head'],'base')
  self.p.checkout(first);self.assertEqual(self.p.state['head'],first)
 def test_qc_failure_retains_head(self):
  first=self.runplan(self.raw())['version']
  self.p.prepare(self.raw('p2',layers=[self.layer(sat=.97)]));self.p.approve('p2','overall','Test approval')
  with patch('v3.check',return_value={'pass':False,'errors':['synthetic QC failure']}):
   with self.assertRaises(ValueError):self.p.run('p2')
  self.assertEqual(self.p.state['head'],first)
 def test_export_visual_gate(self):
  vid=self.runplan(self.raw())['version']
  with self.assertRaises(OSError):self.p.export(vid,self.d/'final.png','test export')
  ev=self.root/'state/v3/versions'/vid/'image.png';checks={k:{'decision':'pass','observation':'synthetic fixture only'} for k in ('space','edges','lighting','effects','intent')}
  self.p.inspect(vid,checks,[ev]);self.p.export(vid,self.d/'final.png','test export');self.assertEqual(r.digest(ev),r.digest(self.d/'final.png'))
 def test_asset_tamper_blocks(self):
  self.p.prepare(self.raw());self.p.approve('p1','overall','test');_,rec=self.p.plan('p1');path=self.root/rec['plan']['layers'][0]['op']['mask']['path'];path.write_bytes(b'bad')
  with self.assertRaises(ValueError):self.p.run('p1')
 def test_subject_overlay_forbidden(self):
  Image.new('RGBA',(64,48),(255,0,0,255)).save(self.d/'fx.png')
  l={'module':'vfx','op':{'id':'fx','type':'overlay','mask':str(self.d/'subject.png'),'layer':str(self.d/'fx.png'),'risk':'cosmetic'}}
  with self.assertRaisesRegex(ValueError,'Geometry'):self.runplan(self.raw(layers=[l],allowed='subject'))
 def foreground_setup(self):
  face=self.freeze.copy();front=np.zeros_like(face);front[10:13,20:24]=255
  Image.fromarray(face).save(self.d/'face.png');Image.fromarray(front).save(self.d/'front.png')
  self.p.state['foreground_vfx']={'face':r.capture(self.root,self.d/'face.png'),'allowed':r.capture(self.root,self.d/'front.png'),'user_quote':'test foreground authorization','max_subject_coverage':.15};self.p.save()
  fx=np.zeros((48,64,4),dtype='uint8');fx[front>0]=[250,100,150,100];Image.fromarray(fx).save(self.d/'front-layer.png')
  return {'module':'vfx','op':{'id':'petal','type':'overlay','mask':str(self.d/'front.png'),'layer':str(self.d/'front-layer.png'),'risk':'cosmetic','opacity':.4}}
 def test_authorized_foreground_preserves_face(self):
  layer=self.foreground_setup();res=self.runplan(self.raw(layers=[layer],allowed='front'));out=self.p.picture(res['version'])
  np.testing.assert_array_equal(out[self.freeze>0],self.a[self.freeze>0]);self.assertFalse(np.array_equal(out,self.a))
 def test_foreground_outside_authorized_mask_rejected(self):
  layer=self.foreground_setup();fx=np.array(Image.open(self.d/'front-layer.png'));fx[11,30]=[255,0,0,255];Image.fromarray(fx).save(self.d/'front-layer.png');layer['op']['mask']=str(self.d/'subject.png')
  with self.assertRaisesRegex(ValueError,'authorized'):self.runplan(self.raw(layers=[layer],allowed='subject'))
 def test_foreground_never_on_face(self):
  layer=self.foreground_setup();fx=np.array(Image.open(self.d/'front-layer.png'));fx[18,28]=[255,0,0,255];Image.fromarray(fx).save(self.d/'front-layer.png');layer['op']['mask']=str(self.d/'subject.png')
  with self.assertRaisesRegex(ValueError,'face'):self.runplan(self.raw(layers=[layer],allowed='subject'))
 def test_foreground_does_not_authorize_background(self):
  layer=self.foreground_setup();layer['module']='background'
  with self.assertRaises(ValueError):self.runplan(self.raw(layers=[layer],allowed='front'))
 def test_approval_missing(self):
  self.p.prepare(self.raw())
  with self.assertRaisesRegex(ValueError,'Approval'):self.p.run('p1')
 def test_plan_tamper(self):
  self.p.prepare(self.raw());path,rec=self.p.plan('p1');rec['plan']['do']=['tamper'];r.write(path,rec)
  with self.assertRaises(ValueError):self.p.approve('p1','overall','test')
 def test_invalid_confidence_and_risk(self):
  for i,(field,value) in enumerate([('confidence',True),('confidence',-.1),('confidence',1.1),('confidence',float('nan')),('confidence','low'),('risk','HIGH')]):
   with self.subTest(field=field,value=value):
    raw=self.raw('invalid'+str(i));raw[field]=value
    with self.assertRaises(ValueError):self.p.prepare(raw)
    self.assertFalse((self.root/'state/v3/plans'/raw['id']).exists())
 def test_uncertain_high_risk_needs_both_scopes(self):
  raw=self.raw();raw.update(confidence=.5,risk='high');self.p.prepare(raw);self.p.approve('p1','overall','synthetic authorization')
  with self.assertRaisesRegex(ValueError,'uncertain'):self.p.run('p1')
  self.p.approve('p1','uncertain','synthetic authorization')
  with self.assertRaisesRegex(ValueError,'high-risk'):self.p.run('p1')
  self.p.approve('p1','high-risk','synthetic authorization');self.assertEqual(self.p.run('p1')['status'],'QC_PASS')
 def test_reserved_approval_layer_names(self):
  for name in ('overall','uncertain','high-risk'):
   with self.subTest(name=name):
    layer=self.layer();layer['op']['id']=name
    with self.assertRaises(ValueError):self.p.prepare(self.raw(layers=[layer]))
 def test_invalid_effect_budget(self):
  for i,budget in enumerate([{'primary':-1},{'primary':True},{'secondary':1.5},{'extra':1},[],{'secondary':3}]):
   with self.subTest(budget=budget):
    raw=self.raw('budget'+str(i));raw['effect_budget']=budget
    with self.assertRaises(ValueError):self.p.prepare(raw)

if __name__=='__main__':unittest.main()
