"""Regression tests for minimal planning, native caching, budgets and real state changes."""
import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import test_v3 as fixtures
import retouch as r
from v3 import Project
from native_cache import AssetReader

class OptimizationTests(unittest.TestCase):
    setUp=fixtures.V3Tests.setUp
    raw=fixtures.V3Tests.raw
    layer=fixtures.V3Tests.layer
    runplan=fixtures.V3Tests.runplan
    foreground_setup=fixtures.V3Tests.foreground_setup
    def test_decode_reuse_still_checks_source_hash(self):
        reader=AssetReader(self.root);ref=r.capture(self.root,self.d/'bg.png')
        a=reader.mask(ref,self.a.shape[:2]);b=reader.mask(ref,self.a.shape[:2]);self.assertIs(a,b);self.assertEqual(reader.decodes,1)
        self.assertFalse(a.flags.writeable);(self.root/ref['path']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'Asset changed'):reader.mask(ref,self.a.shape[:2])
    def test_decode_memory_is_bounded(self):
        reader=AssetReader(self.root,max_bytes=1);ref=r.capture(self.root,self.d/'bg.png')
        reader.mask(ref,self.a.shape[:2]);reader.mask(ref,self.a.shape[:2]);self.assertEqual(reader.bytes,0);self.assertEqual(reader.decodes,2)
    def test_sparse_cache_uses_only_native_tile(self):
        small=np.zeros_like(self.bg);small[1:4,1:5]=128;Image.fromarray(small).save(self.d/'small.png')
        result=self.runplan(self.raw(layers=[self.layer('small')],allowed='bg'));out=self.p.picture(result['version'])
        records=[r.read(p) for p in (self.root/'state/v3/cache').glob('*.json')];self.assertEqual(records[0]['kind'],'tile')
        arr=np.load(next((self.root/'state/v3/cache').glob('*.npy')));self.assertEqual(arr.shape,(3,4,3))
        np.testing.assert_array_equal(out[small==0],self.a[small==0])
    def test_warm_final_checkpoint_skips_layer_decodes_and_processing(self):
        layers=[self.layer(),{'module':'finish','op':{'id':'finish','type':'tone','mask':str(self.d/'bg.png'),'exposure':.01}}]
        self.runplan(self.raw(layers=layers));_,rec=self.p.plan('p1');new=Project(self.root);a,b,freeze,subject=new.baseline();decodes=new.reader.decodes
        with patch('retouch.process',side_effect=AssertionError('unexpected pixel processing')):
            out=new.render(rec['plan']['layers'],a,b,freeze,subject)
        self.assertEqual(new.reader.decodes,decodes);self.assertEqual(new.hits,2);np.testing.assert_array_equal(out,self.p.picture(self.p.state['head']))
    def test_cached_array_corruption_blocks(self):
        self.runplan(self.raw());path=next((self.root/'state/v3/cache').glob('*.npy'));path.write_bytes(b'bad')
        _,rec=self.p.plan('p1');a,b,f,s=self.p.baseline()
        with self.assertRaisesRegex(ValueError,'cache changed'):self.p.render(rec['plan']['layers'],a,b,f,s)
    def test_cached_policy_change_does_not_bypass_subject_guard(self):
        layer=self.foreground_setup();self.runplan(self.raw(layers=[layer],allowed='front'));_,rec=self.p.plan('p1');self.p.state.pop('foreground_vfx')
        a,b,f,s=self.p.baseline()
        with self.assertRaisesRegex(ValueError,'Geometry'):self.p.render(rec['plan']['layers'],a,b,f,s)
    def test_noop_skips_renderer_but_runs_quality_guard(self):
        self.runplan(self.raw());raw=self.raw('p2');self.p.prepare(raw);self.p.approve('p2','overall','synthetic approval')
        with patch.object(self.p,'render',side_effect=AssertionError('noop rendered')),patch('v3.check',return_value={'pass':False,'errors':['guard failure']}):
            with self.assertRaisesRegex(ValueError,'QC failed'):self.p.run('p2')
        self.assertEqual(self.p.state['head'],'v0001')
    def test_reorder_is_a_change_and_invalidates_both_modules(self):
        first=self.layer();last={'module':'finish','op':{'id':'finish','type':'tone','mask':str(self.d/'bg.png'),'gains':[1.01,1,1]}}
        self.runplan(self.raw(layers=[first,last]));self.assertEqual(self.p.changed([last,first]),['finish','grade'])
        result=self.runplan(self.raw('p2',layers=[last,first]));self.assertIn('background',result['invalidated']);self.assertIn('finish',result['invalidated'])
    def test_retouch_invalidates_grading_but_not_face(self):
        mask=np.where((self.subject>0)&(self.freeze==0),255,0).astype('uint8');Image.fromarray(mask).save(self.d/'skin.png');layer=self.layer('skin');layer['module']='retouch'
        result=self.runplan(self.raw(layers=[layer],allowed='skin'));self.assertIn('grading',result['invalidated']);self.assertIn('finish',result['invalidated']);self.assertNotIn('face',result['invalidated'])
    def test_branch_switch_uses_partial_invalidation(self):
        self.runplan(self.raw());result=self.p.checkout('base','other');self.assertNotIn('face',result['invalidated']);self.assertEqual(self.p.state['reference_map'],[])
    def test_module_mask_blocks_changes_even_when_global_allows(self):
        raw=self.raw();raw['scope']['modules']={'background':str(self.d/'right.png')};self.p.prepare(raw);self.p.approve('p1','overall','synthetic approval')
        with self.assertRaisesRegex(ValueError,'Module Modification Scope'):self.p.run('p1')
        self.assertEqual(self.p.state['head'],'base')
    def test_wrong_scope_dimensions_record_failure_and_keep_head(self):
        Image.new('L',(2,2),255).save(self.d/'bad.png');raw=self.raw();raw['scope']['allowed']=str(self.d/'bad.png');self.p.prepare(raw);self.p.approve('p1','overall','synthetic approval')
        with self.assertRaises(ValueError):self.p.run('p1')
        self.assertEqual(self.p.state['head'],'base');self.assertTrue((self.root/'qc/p1.json').exists())
    def test_failed_version_write_does_not_advance_head(self):
        raw=self.raw();self.p.prepare(raw);self.p.approve('p1','overall','synthetic approval');real=r.write
        def fail(path,value,*args,**kw):
            if Path(path).name=='version.json':raise OSError('synthetic disk failure')
            return real(path,value,*args,**kw)
        with patch('retouch.write',side_effect=fail):
            with self.assertRaises(OSError):self.p.run('p1')
        self.assertEqual(self.p.state['head'],'base');self.assertEqual(r.read(self.root/'project.json')['v3']['head'],'base')
        result=self.runplan(self.raw('p2'));self.assertEqual(result['version'],'v0002')
    def test_telemetry_counts_only_this_run(self):
        self.runplan(self.raw());self.runplan(self.raw('p2',layers=[self.layer(sat=.97)]));row=self.p.state['telemetry'][-1]
        self.assertEqual(row['cache_misses'],1);self.assertEqual(row['generation_calls'],0);self.assertIn('background',row['module_compute_seconds'])
        self.assertGreaterEqual(row['cache_bytes_written'],0)
    def test_source_energy_cache_preserves_qc_failure(self):
        a,b,f,s=self.p.baseline();good=self.p.quality(a,a,f);bad=a.copy();bad[~f]=128;self.assertTrue(good['pass']);self.assertFalse(self.p.quality(a,bad,f)['pass'])
    def test_file_bound_analysis_rechecks_mutated_reference(self):
        calls=[];files={'reference':str(self.d/'src.png')}
        for _ in range(2):self.p.cached('analysis',3,[],{'schema':1},lambda:calls.append(1) or {'observed':1},files=files)
        self.assertEqual(len(calls),1);Image.new('RGB',(64,48),(12,24,36)).save(self.d/'src.png')
        self.p.cached('analysis',3,[],{'schema':1},lambda:calls.append(1) or {'observed':2},files=files);self.assertEqual(len(calls),2)
    def test_reference_analysis_reuse_and_schema_invalidation(self):
        value={'observations':['synthetic fixture'],'risk':'unknown'};self.p.reference_analysis('ref',self.d/'src.png',value=value)
        self.assertEqual(self.p.reference_analysis('same',self.d/'src.png'),value)
        with self.assertRaisesRegex(ValueError,'CACHE MISS'):self.p.reference_analysis('ref',self.d/'src.png',schema='v2')
    def test_route_selects_existing_parameters_without_mutating_input(self):
        self.runplan(self.raw());raw=self.raw('p2');raw.pop('layers');raw['updates']={'grade':{'saturation':.97}};original=copy.deepcopy(raw)
        route=self.p.route(raw);self.assertEqual(route['run_modules'],['background']);self.assertEqual(route['request']['generation_policy'],'none');self.assertEqual(raw,original)
        self.p.revise(route['request']);self.p.approve('p2','overall','synthetic approval')
        with self.assertRaisesRegex(ValueError,'unnecessary generation'):self.p.attempt('p2','background')
    def test_route_noop_creates_no_plan(self):
        self.runplan(self.raw());result=self.p.route({'updates':{'grade':{'saturation':.98}}});self.assertEqual(result['status'],'NO_ACTION_REQUIRED');self.assertEqual(len(list((self.root/'state/v3/plans').iterdir())),1)
    def test_revise_does_not_mutate_request(self):
        self.runplan(self.raw());raw=self.raw('p2');raw.pop('layers');raw['updates']={'grade':{'saturation':.97}};expected=copy.deepcopy(raw);self.p.revise(raw);self.assertEqual(raw,expected)
    def test_generation_and_generated_corrections_share_cap(self):
        self.p.prepare(self.raw());self.p.approve('p1','overall','synthetic approval');self.p.attempt('p1','left');self.p.attempt('p1','right')
        with self.assertRaisesRegex(ValueError,'STOP'):self.p.attempt('p1','other','correction')
        self.p.attempt('p1','other','correction',uses_generation=False)
    def test_attempt_results_do_not_refund_budget(self):
        self.p.prepare(self.raw());self.p.approve('p1','overall','synthetic approval');self.p.attempt('p1','left');self.p.attempt_result('p1',1,'failure',.5,'synthetic backend','test failure')
        self.p.attempt('p1','right')
        with self.assertRaisesRegex(ValueError,'STOP'):self.p.attempt('p1','other')
        with self.assertRaisesRegex(ValueError,'completed'):self.p.attempt_result('p1',1,'success',.5,'synthetic backend')
    def test_unreported_calls_remain_unknown_in_telemetry(self):
        self.p.prepare(self.raw());self.p.approve('p1','overall','synthetic approval');self.p.attempt('p1','left');self.p.run('p1')
        self.assertIsNone(self.p.state['telemetry'][-1]['generation_calls'])
    def test_failed_plan_cannot_reopen_via_approve(self):
        self.p.prepare(self.raw(allowed='right'));self.p.approve('p1','overall','synthetic approval')
        with self.assertRaises(ValueError):self.p.run('p1')
        with self.assertRaisesRegex(ValueError,'completed'):self.p.approve('p1','overall','synthetic approval')
    def test_task_ids_never_reused_even_without_attempts(self):
        self.p.new_task('second','synthetic new task');self.p.new_task('third','synthetic new task')
        with self.assertRaises(ValueError):self.p.new_task('second','synthetic repeat')
    def test_profile_context_overrides_persistent_with_image(self):
        self.p.state['profile']={'persistent':{'palette':'warm'},'project':{'palette':'blue'},'image':{'palette':'neutral'}}
        self.assertEqual(self.p.context()['preferences']['palette'],'neutral')
    def test_reference_map_survives_parameter_revision(self):
        raw=self.raw();raw['reference_map']=[{'reference':'ref','role':'color','weight':.6,'priority':1,'do_not_copy':['glow'],'group':'series'}];self.runplan(raw)
        revise=self.raw('p2');revise.pop('layers');revise['updates']={'grade':{'saturation':.97}};self.p.revise(revise)
        self.assertEqual(self.p.plan('p2')[1]['plan']['reference_map'],raw['reference_map'])
    def test_modes_keep_full_hard_gates(self):
        for i,mode in enumerate(('fast','standard','detail')):
            self.p.prepare(self.raw('mode'+str(i),mode=mode,allowed='right'));self.p.approve('mode'+str(i),'overall','synthetic approval')
            with self.assertRaisesRegex(ValueError,'Scope'):self.p.run('mode'+str(i))
    def test_local_vfx_scope_allows_right_mask_delta_on_full_width_layer(self):
        fx=np.zeros((48,64,4),dtype='uint8');fx[1:9,1:63]=[255,100,20,100];Image.fromarray(fx).save(self.d/'fire.png')
        layer={'module':'vfx','op':{'id':'fire','type':'overlay','mask':str(self.d/'bg.png'),'layer':str(self.d/'fire.png'),'opacity':.4,'blend':'screen','risk':'cosmetic'}}
        self.runplan(self.raw(layers=[layer]));before=self.p.picture(self.p.state['head'])
        weak=self.bg.copy();weak[:,44:]//=2;Image.fromarray(weak).save(self.d/'weak.png')
        raw=self.raw('delta',allowed='right');raw.pop('layers');raw['updates']={'fire':{'mask':str(self.d/'weak.png')}};raw['scope']['modules']={'vfx':str(self.d/'right.png')}
        self.p.revise(raw);self.p.approve('delta','overall','synthetic authorization');res=self.p.run('delta')
        np.testing.assert_array_equal(before[:,:44],self.p.picture(res['version'])[:,:44])
    def test_local_vfx_scope_rejects_global_opacity_change(self):
        fx=np.zeros((48,64,4),dtype='uint8');fx[1:9,1:63]=[255,100,20,100];Image.fromarray(fx).save(self.d/'fire.png')
        layer={'module':'vfx','op':{'id':'fire','type':'overlay','mask':str(self.d/'bg.png'),'layer':str(self.d/'fire.png'),'opacity':.4,'blend':'screen','risk':'cosmetic'}}
        self.runplan(self.raw(layers=[layer]));raw=self.raw('delta');raw.pop('layers');raw['updates']={'fire':{'opacity':.2}};raw['scope']['modules']={'vfx':str(self.d/'right.png')}
        self.p.revise(raw);self.p.approve('delta','overall','synthetic authorization')
        with self.assertRaisesRegex(ValueError,'Module Modification Scope'):self.p.run('delta')
    def test_reference_group_weights_are_not_added(self):
        raw=self.raw();raw['reference_map']=[{'reference':'a','role':'color','weight':.6,'priority':1,'do_not_copy':[],'group':'battlefield'},{'reference':'b','role':'color','weight':.7,'priority':2,'do_not_copy':[],'group':'battlefield'}]
        self.p.prepare(raw);group=self.p.plan('p1')[1]['plan']['reference_groups'];self.assertEqual(len(group),1);self.assertEqual(group[0]['effective_weight'],.7)
    def test_registered_reference_is_hash_bound_in_plan(self):
        self.p.reference_analysis('ref',self.d/'src.png',value={'observations':[]});raw=self.raw();raw['reference_map']=[{'reference':'ref','role':'color','weight':.6,'priority':1,'do_not_copy':[],'group':'series'}]
        self.p.prepare(raw);ref=self.p.plan('p1')[1]['plan']['reference_map'][0]['reference'];self.assertEqual(ref['sha256'],r.digest(self.d/'src.png'))
    def test_missing_upstream_tile_cache_can_recompute(self):
        small=np.zeros_like(self.bg);small[1:4,1:5]=128;Image.fromarray(small).save(self.d/'small.png')
        layers=[self.layer('small'),{'module':'finish','op':{'id':'finish','type':'tone','mask':str(self.d/'small.png'),'exposure':.01}}]
        self.runplan(self.raw(layers=layers));_,rec=self.p.plan('p1');records=list((self.root/'state/v3/cache').glob('*.json'));self.assertEqual(len(records),2)
        # Remove only a re-creatable cache entry, leaving downstream data intact.
        from native_cache import RenderCache
        cache=RenderCache(self.root/'state/v3/cache');a,b,f,s=self.p.baseline();keys=[]
        import hashlib
        key=r.canonical({'engine':32,'base':self.p.state['base']['sha256'],'source':self.p.meta['source']['sha256'],'freeze':hashlib.sha256(np.ascontiguousarray(f).tobytes()).hexdigest(),'subject':hashlib.sha256(np.ascontiguousarray(s).tobytes()).hexdigest(),'foreground':None})
        for item in rec['plan']['layers']:key=r.canonical({'prefix':key,'layer':item});keys.append(key)
        for path in cache.paths(keys[0]):path.unlink()
        out=self.p.render(rec['plan']['layers'],a,b,f,s);np.testing.assert_array_equal(out,self.p.picture(self.p.state['head']))
    def test_reference_tamper_blocks_bound_plan(self):
        self.p.reference_analysis('ref',self.d/'src.png',value={'observations':[]});raw=self.raw();raw['reference_map']=[{'reference':'ref','role':'color','weight':.6,'priority':1,'do_not_copy':[],'group':'series'}]
        self.p.prepare(raw);self.p.approve('p1','overall','synthetic authorization');ref=self.p.plan('p1')[1]['plan']['reference_map'][0]['reference']
        (self.root/ref['path']).write_bytes(b'changed reference')
        with self.assertRaisesRegex(ValueError,'Asset changed'):self.p.run('p1')
    def test_export_rechecks_all_five_visual_checks(self):
        vid=self.runplan(self.raw())['version'];ev=self.root/'state/v3/versions'/vid/'image.png';checks={k:{'decision':'pass','observation':'synthetic fixture'} for k in ('space','edges','lighting','effects','intent')};self.p.inspect(vid,checks,[ev])
        file=ev.parent/'inspection.json';record=r.read(file);record['checks'].pop('intent');r.write(file,record)
        with self.assertRaisesRegex(ValueError,'Visual QC'):self.p.export(vid,self.d/'bad.png','synthetic export')
        self.assertFalse((self.d/'bad.png').exists())
if __name__=='__main__':unittest.main()
