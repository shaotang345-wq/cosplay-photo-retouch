"""V3 shared orchestration atop the existing native renderer. No AI client."""
import argparse, copy, hashlib, json, shutil, sys, time
from pathlib import Path
import numpy as np
from PIL import Image
import retouch as r
from acceptance import load_image, load_mask, check, energy
from planning import minimal_plan
from native_cache import AssetReader, RenderCache

MODES = {'fast': {'previews':1,'rois':0,'generation':0,'correction':0,'region':1},
         'standard': {'previews':3,'rois':2,'generation':2,'correction':1,'region':2},
         'detail': {'previews':5,'rois':4,'generation':2,'correction':1,'region':2}}
MODULES = {'retouch','background','vfx','finish'}
GRAPH = {'original':[], 'subject':['original'], 'face':['subject'], 'hair':['subject'],
 'costume':['subject'],'props':['subject'],'original_lighting':['original'],
 'composition':['original'],'background':['original'],'environment_light':['background'],
 'depth':['background','composition'],'vfx':['background'],'interaction':['vfx','environment_light'],
 'grading':['original'], 'finish':['interaction','background','grading']}

class Project:
    def __init__(self, root):
        self.root=Path(root).resolve(); self.meta=r.read(self.root/'project.json')
        self.state=self.meta.get('v3'); self.hits=0; self.misses=0; self.times={}
        self.reader=AssetReader(self.root);self.render_cache=RenderCache(self.root/'state/v3/cache');self.modules={}
        if self.state:
            for node in GRAPH:self.state['nodes'].setdefault(node,0)
            self.state.setdefault('events',[]);self.state.setdefault('tasks',[self.state['task']['id']])
    def event(self,action,start,details):
        self.state.setdefault('events',[]).append({'action':action,'seconds':time.perf_counter()-start,'details':details})
        self.save()
    def save(self):
        self.meta['v3']=self.state; r.write(self.root/'project.json',self.meta)
    def attach(self, subject, face=None, foreground=None, foreground_quote=None):
        if self.state: raise ValueError('V3 already attached')
        a,mode,freeze=r.base(self.root,self.meta)
        subject_ref=r.capture(self.root,subject); mask=load_mask(r.asset(self.root,subject_ref),a.shape[:2])>0
        if not mask.any() or np.any(freeze & ~mask): raise ValueError('Subject must cover freeze mask')
        _,info,b=r.version(self.root,self.meta['head'])
        if not check(a,b,freeze)['pass']: raise ValueError('Legacy head invalid')
        for folder in ('state/v3/plans','state/v3/versions','state/v3/cache','analysis','references','previews','qc','reference_feedback'):
            (self.root/folder).mkdir(parents=True,exist_ok=True)
        self.state={'schema':3,'mode':'standard','legacy_head':self.meta['head'],
          'base':r.capture(self.root,self.root/'versions'/self.meta['head']/'image.png'),
          'subject':subject_ref,'subject_bbox':Image.fromarray(mask.astype('uint8')).getbbox(),
          'head':'base','branch':'main','branches':{'main':'base'},'versions':{},'cache':{},
          'nodes':{key:0 for key in GRAPH},'reference_map':[], 'feedback':[],
          'profile':{'persistent':{},'project':{},'image':{}},'approved_operations':[],
          'completed_operations':[], 'background_version':None,'vfx_version':None,
          'limits':copy.deepcopy(MODES),'telemetry':[],'task':{'id':'initial','quote':'initial project task'},'attempt_ledger':[]}
        if foreground is not None:
            if face is None or not foreground_quote or not foreground_quote.strip():raise ValueError('Foreground VFX requires face mask and explicit authorization')
            face_ref=r.capture(self.root,face);front_ref=r.capture(self.root,foreground)
            face_mask=load_mask(r.asset(self.root,face_ref),a.shape[:2])>0
            front_mask=load_mask(r.asset(self.root,front_ref),a.shape[:2])>0
            if not face_mask.any() or np.any(face_mask & ~freeze) or np.any(face_mask & front_mask):
                raise ValueError('Face must be frozen and excluded from foreground area')
            self.state['foreground_vfx']={'face':face_ref,'allowed':front_ref,'user_quote':foreground_quote,'max_subject_coverage':0.15}
        self.save(); return {'attached':True,'legacy_head_preserved':self.meta['head']}
    def baseline(self):
        if not self.state or self.meta['head']!=self.state['legacy_head']:
            raise ValueError('Attach V3 or reconcile changed legacy head in a new project')
        a,mode=self.reader.image(self.meta['source'])
        freeze=self.reader.mask(self.meta['protected'],a.shape[:2])>0
        if not freeze.any() or list(a.shape)!=self.meta['shape'] or mode!=self.meta['mode']:raise ValueError('Invalid baseline')
        b,_=self.reader.image(self.state['base']);subject=self.reader.mask(self.state['subject'],a.shape[:2])>0
        if b.shape!=a.shape or not subject.any() or np.any(freeze & ~subject):raise ValueError('Invalid V3 baseline')
        return a,b,freeze,subject

    def invalidate(self,node):
        if node not in GRAPH: raise ValueError('Unknown dependency node')
        affected={node}
        while True:
            more={k for k,deps in GRAPH.items() if affected.intersection(deps)}-affected
            if not more: break
            affected|=more
        for k in affected:self.state['nodes'][k]+=1
        return sorted(affected)
    def cached(self,name,level,deps,inputs,compute,files=None):
        r.identifier(name)
        if level not in (1,2,3,4) or any(d not in GRAPH for d in deps): raise ValueError('Invalid cache dependency')
        fingerprints={label:r.digest(Path(path)) for label,path in (files or {}).items()}
        key=r.canonical({'version':32,'level':level,'source':self.meta['source']['sha256'],'deps':{d:self.state['nodes'][d] for d in deps},'inputs':inputs,'files':fingerprints})
        old=self.state['cache'].get(name)
        if old and old['key']==key:
            if r.canonical(old['value'])!=old['value_hash']:raise ValueError('Cache value corrupt')
            self.hits+=1; return copy.deepcopy(old['value'])
        t=time.perf_counter(); value=compute(); self.times[name]=time.perf_counter()-t;self.misses+=1
        self.state['cache'][name]={'key':key,'level':level,'deps':deps,'value':value,'value_hash':r.canonical(value)}
        return copy.deepcopy(value)
    def recipe(self,version=None):
        version=version or self.state['head']
        if version=='base': return []
        return copy.deepcopy(self.info(version)['recipe'])
    def info(self,version):
        r.identifier(version); info=r.read(self.root/'state/v3/versions'/version/'version.json')
        expected=self.state['versions'].get(version)
        if not expected or r.canonical(info)!=expected:raise ValueError('Version record changed')
        return info
    def picture(self,version):
        if version=='base':return load_image(r.asset(self.root,self.state['base']))[0]
        info=self.info(version); path=self.root/'state/v3/versions'/version/'image.png'
        if r.digest(path)!=info['image_hash']:raise ValueError('Version image changed')
        return load_image(path)[0]
    def prepare(self,raw):
        stage_start=time.perf_counter();self.baseline()
        allowed={'id','do','do_not','layers','scope','mode','reference_map','effect_budget','confidence','risk','rois','targets','generation_policy'}
        if set(raw)-allowed:raise ValueError('Unknown plan fields')
        r.identifier(raw['id']); mode=raw.get('mode','standard')
        if mode not in MODES or any(not isinstance(raw.get(field),list) or not raw[field] or any(not isinstance(x,str) or not x.strip() for x in raw[field]) for field in ('do','do_not')):raise ValueError('Mode and DO / DO NOT lists required')
        if not isinstance(raw.get('targets',{}),dict):raise ValueError('Targets must be a mapping')
        for value in raw.get('targets',{}).values():r.number(value,0,1)
        if raw.get('generation_policy','assets') not in {'none','assets'}:raise ValueError('Invalid generation policy')
        layers=copy.deepcopy(raw['layers']); ids=set()
        for layer in layers:
            if set(layer)!={'module','op'} or layer['module'] not in MODULES:raise ValueError('Module required')
            op=layer['op'];r.validate_operations([op])
            if op['id'] in ids or op['id'] in {'uncertain','high-risk'}:raise ValueError('Duplicate or reserved layer ID')
            ids.add(op['id'])
            for field in ('mask','layer'):
                if field in op and not isinstance(op[field],dict):op[field]=r.capture(self.root,op[field])
        scope=copy.deepcopy(raw['scope'])
        if not {'allowed','freeze','geometry_lock'}<=set(scope) or set(scope)-{'allowed','freeze','geometry_lock','modules'} or scope['geometry_lock'] is not True:raise ValueError('Geometry lock mandatory')
        for field in ('allowed','freeze'):
            if not isinstance(scope[field],dict):scope[field]=r.capture(self.root,scope[field])
        if not isinstance(scope.get('modules',{}),dict) or set(scope.get('modules',{}))-MODULES:raise ValueError('Unknown module scope')
        for module,value in scope.get('modules',{}).items():
            if not isinstance(value,dict):scope['modules'][module]=r.capture(self.root,value)
            self.reader.mask(scope['modules'][module],tuple(self.meta['shape'][:2]))
        refs=copy.deepcopy(raw.get('reference_map',self.state['reference_map']))
        if not isinstance(refs,list):raise ValueError('Reference map must be a list')
        groups={}
        for ref in refs:
            if set(ref)!={'reference','role','weight','priority','do_not_copy','group'}:raise ValueError('Reference mapping incomplete')
            r.number(ref['weight'],0,1)
            if ref['role'] not in {'color','lighting','material','background','effect','composition'}:raise ValueError('Reference role invalid')
            if not isinstance(ref['group'],str) or not isinstance(ref['do_not_copy'],list) or any(not isinstance(x,str) for x in ref['do_not_copy']):raise ValueError('Reference group and exclusions invalid')
            r.number(ref['priority'],0,100)
            registered=self.state.get('references',{}).get(ref['reference']) if isinstance(ref['reference'],str) else None
            if registered:ref['reference']=registered['asset']
            if isinstance(ref['reference'],dict):r.asset(self.root,ref['reference'])
            identity=ref['group'] or r.canonical(ref['reference'])
            key=ref['role']+'::'+identity
            group=groups.setdefault(key,{'role':ref['role'],'group':identity,'members':[],'effective_weight':0,'priority':0})
            group['members'].append(ref['reference']);group['effective_weight']=max(group['effective_weight'],ref['weight']);group['priority']=max(group['priority'],ref['priority'])
        confidence=r.number(raw.get('confidence',1),0,1)
        risk=raw.get('risk','low')
        if risk not in {'low','high'}:raise ValueError('Unknown plan risk')
        if confidence<.6 and risk=='high':
            confidence_pending=True
        else:confidence_pending=False
        budget=raw.get('effect_budget',{'primary':1,'secondary':2})
        if not isinstance(budget,dict) or set(budget)-{'primary','secondary'}:raise ValueError('Invalid effect budget')
        for field,maximum in (('primary',1),('secondary',2)):
            value=budget.get(field,0)
            if type(value)!=int or not 0<=value<=maximum:raise ValueError('Effect budget requires bounded nonnegative integers')
        plan={**raw,'layers':layers,'scope':scope,'mode':mode,'reference_map':refs,
              'parent':self.state['head'],'branch':self.state['branch'],'source_hash':self.meta['source']['sha256'],
              'base_hash':self.state['base']['sha256'],'confidence_pending':confidence_pending,'reference_groups':list(groups.values())}
        path=self.root/'state/v3/plans'/raw['id'];path.mkdir()
        record={'plan':plan,'hash':r.canonical(plan),'status':'PLAN_PENDING','approvals':{},
                'attempts':[],'corrections':0,'region_attempts':{}}
        r.write(path/'plan.json',record,True)
        self.event('plan',stage_start,{'plan':raw['id'],'layers':len(layers)})
        return {'id':raw['id'],'status':'PLAN_PENDING','changed_layers':self.changed(layers),
                'route':'existing parameters/masks first; native composition','generation_calls':0,'generation_policy':plan.get('generation_policy','assets')}
    def revise(self,raw):
        raw=copy.deepcopy(raw);updates=raw.pop('updates',{})
        layers=self.recipe();found=set()
        for item in layers:
            key=item['op']['id']
            if key in updates:
                if set(updates[key])-{'opacity','blend','mask','exposure','contrast','saturation','gamma','gains','layer'}:
                    raise ValueError('Revision may change parameters/assets, not identity/module/risk')
                item['op'].update(updates[key]);found.add(key)
        if found!=set(updates):raise ValueError('Unknown layer in revision')
        raw['layers']=layers
        raw.setdefault('generation_policy','assets' if any('layer' in x for x in updates.values()) else 'none')
        return self.prepare(raw)
    def metadata(self):
        def compute():
            path=r.asset(self.root,self.meta['source'])
            with Image.open(path) as im:
                return {'size':list(im.size),'mode':im.mode,'orientation':im.getexif().get(274,1),
                        'subject_bbox':self.state['subject_bbox'],'source_hash':self.meta['source']['sha256']}
        result=self.cached('metadata',1,['original'],{},compute);self.save();return result
    def changed(self,layers):
        return self.changed_against(layers,self.recipe())
    @staticmethod
    def changed_against(layers,previous):
        old={x['op']['id']:x for x in previous};new={x['op']['id']:x for x in layers}
        changed={k for k in old.keys()|new.keys() if old.get(k)!=new.get(k)}
        # Layer order changes blending even when every parameter is identical.
        common=set(old)&set(new)
        before=[x['op']['id'] for x in previous if x['op']['id'] in common]
        after=[x['op']['id'] for x in layers if x['op']['id'] in common]
        if before!=after:changed.update(common)
        return sorted(changed)

    def plan(self,pid):
        path=self.root/'state/v3/plans'/r.identifier(pid)/'plan.json';rec=r.read(path)
        if rec['hash']!=r.canonical(rec['plan']):raise ValueError('Plan changed; approvals invalid')
        return path,rec
    def approve(self,pid,scope,quote):
        path,rec=self.plan(pid)
        valid={'overall','uncertain','high-risk'}|{x['op']['id'] for x in rec['plan']['layers'] if x['op'].get('risk') in r.HIGH}
        if scope not in valid or not quote.strip():raise ValueError('Invalid approval')
        if rec['status'] not in {'PLAN_PENDING','PLAN_APPROVED'}:raise ValueError('Plan completed or executing')
        rec['approvals'][scope]={'hash':rec['hash'],'quote':quote,'identity_authenticated':False}
        try:self.approvals(rec);rec['status']='PLAN_APPROVED'
        except ValueError:rec['status']='PLAN_PENDING'
        r.write(path,rec)
        self.state['approved_operations'].append({'plan':pid,'scope':scope,'quote':quote});self.save()
        return {'recorded':scope}
    def approvals(self,rec):
        required=['overall']+[x['op']['id'] for x in rec['plan']['layers'] if x['op'].get('risk') in r.HIGH]
        if rec['plan']['confidence_pending']:required.append('uncertain')
        if rec['plan'].get('risk')=='high':required.append('high-risk')
        for scope in required:
            a=rec['approvals'].get(scope,{})
            if a.get('hash')!=rec['hash'] or not a.get('quote','').strip():raise ValueError('Approval required: '+scope)
    def attempt(self,pid,region,kind='generation',uses_generation=None):
        path,rec=self.plan(pid);self.approvals(rec);r.identifier(region)
        if rec['status'] not in {'PLAN_PENDING','PLAN_APPROVED'} or rec['plan']['parent']!=self.state['head']:raise ValueError('Plan completed or parent changed')
        if kind not in {'generation','correction'}:raise ValueError('Unknown attempt')
        uses_generation=True if uses_generation is None else uses_generation
        if type(uses_generation)!=bool or (kind=='generation' and not uses_generation):raise ValueError('Invalid generation flag')
        if uses_generation and rec['plan'].get('generation_policy','assets')=='none':raise ValueError('STOP: native parameter/mask edit forbids unnecessary generation')
        limits=MODES[rec['plan']['mode']];current=[x for x in self.state['attempt_ledger'] if x['task']==self.state['task']['id']]
        generations=sum(x.get('uses_generation',True) for x in current);corrections=sum(x['kind']=='correction' for x in current)
        if (uses_generation and generations>=limits['generation']) or (kind=='correction' and corrections>=limits['correction']) or sum(x['region']==region for x in current)>=limits['region']:raise ValueError('STOP: attempt budget exhausted')
        ticket=len(rec['attempts'])+1;event={'task':self.state['task']['id'],'plan':pid,'ticket':ticket,'kind':kind,'region':region,'uses_generation':uses_generation,'time':time.time(),'status':'reserved-before-external-call'}
        self.state['attempt_ledger'].append(copy.deepcopy(event));self.save()
        rec['attempts'].append(event);rec['region_attempts'][region]=rec['region_attempts'].get(region,0)+1;r.write(path,rec)
        return {'ticket':ticket,'remaining':limits['generation']-generations-int(uses_generation),'host_call_not_executed':True}
    def attempt_result(self,pid,ticket,status,seconds,tool,reason='',outputs=None):
        if status not in {'success','failure'} or not isinstance(tool,str) or not tool.strip():raise ValueError('Actual result and tool required')
        r.number(seconds,0,86400);path,rec=self.plan(pid)
        matches=[x for x in rec['attempts'] if x.get('ticket')==ticket]
        if len(matches)!=1 or matches[0]['status']!='reserved-before-external-call':raise ValueError('Unknown or completed ticket')
        event=matches[0];result={'status':status,'seconds':seconds,'tool':tool,'reason':reason,'outputs':[r.capture(self.root,p) for p in (outputs or [])]}
        event.update(result)
        for entry in self.state['attempt_ledger']:
            if entry['plan']==pid and entry.get('ticket')==ticket:entry.update(result)
        r.write(path,rec);self.save();return copy.deepcopy(event)
    def new_task(self,id,quote):
        r.identifier(id)
        if not quote.strip() or id in self.state.get('tasks',[]) or any(x['task']==id for x in self.state['attempt_ledger']):raise ValueError('New task ID and actual new user request required')
        self.state.setdefault('tasks',[]).append(id);self.state['task']={'id':id,'quote':quote};self.save();return self.state['task']
    def quality(self,a,out,freeze):
        value=self.cached('qc-original-energy',1,['original'],{'engine':'edge-v1','mask':hashlib.sha256(np.ascontiguousarray(freeze).tobytes()).hexdigest()},lambda:energy(a,freeze))
        return check(a,out,freeze,before_energy=value)
    def reference_analysis(self,id,path,schema='photographic-v1',value=None):
        r.identifier(id);r.identifier(schema);ref=r.capture(self.root,path)
        self.reader.image(ref)  # Check supported image data; this does not analyze its style.
        name='ref-'+ref['sha256'][:48]
        def compute():
            if not isinstance(value,dict):raise ValueError('CACHE MISS: reference needs actual visual analysis')
            return value
        result=self.cached(name,3,[],{'reference_hash':ref['sha256'],'analysis_schema':schema},compute)
        self.state.setdefault('references',{})[id]={'asset':ref,'analysis_cache':name,'schema':schema};self.save();return result
    def route(self,request):return minimal_plan(self,request)
    def context(self):
        profile=self.state['profile'];effective={**profile['persistent'],**profile['project'],**profile['image']}
        return {'head':self.state['head'],'mode':self.state['mode'],'recipe':self.recipe(),'references':self.state.get('references',{}),
            'reference_map':self.state['reference_map'],'reference_groups':self.state.get('reference_groups',[]),'cache':{key:{'level':v['level'],'deps':v['deps']} for key,v in self.state['cache'].items()},
            'preferences':effective,'feedback':self.state['feedback'][-20:],'task':self.state['task'],
            'attempts':[x for x in self.state['attempt_ledger'] if x['task']==self.state['task']['id']]}

    def hard(self,a,b,freeze,parent=None,allowed=None):
        if a.shape!=b.shape or b.dtype!=np.uint8:raise ValueError('Canvas/channel/type lock failed')
        if not np.array_equal(a[freeze],b[freeze]):raise ValueError('Pixel Freeze failed')
        if a.shape[-1]==4 and not np.array_equal(a[...,3],b[...,3]):raise ValueError('Alpha lock failed')
        if parent is not None and not np.array_equal(parent[~allowed],b[~allowed]):raise ValueError('Modification Scope failed')
    def active(self,item,a,freeze,subject):
        op=item['op'];mask=self.reader.mask(op['mask'],a.shape[:2])>0
        if op['type']=='overlay':
            layer,_=self.reader.image(op['layer'],'RGBA')
            if layer.shape[:2]!=a.shape[:2]:raise ValueError('Canvas mismatch')
            active=mask & (layer[...,3]>0) & (op.get('opacity',1)>0)
            if (active & subject).any():
                policy=self.state.get('foreground_vfx')
                if item['module']!='vfx' or not policy:raise ValueError('Geometry Lock: generated overlay on subject forbidden')
                face=self.reader.mask(policy['face'],a.shape[:2])>0;front=self.reader.mask(policy['allowed'],a.shape[:2])>0
                if np.any(active & face) or np.any(active & subject & ~front):raise ValueError('Foreground VFX touches face or leaves authorized region')
                if np.count_nonzero(active & subject)/np.count_nonzero(subject)>policy['max_subject_coverage']:raise ValueError('Foreground VFX covers too much subject')
                if np.all(layer[...,3]==255):raise ValueError('Foreground VFX must be independent transparent asset')
        else:active=mask
        if item['module']=='background' and (active & subject).any():raise ValueError('Background scope touches subject')
        if item['module']=='retouch' and op['type']!='tone':raise ValueError('Retouch only supports tone')
        if (active & freeze).any():raise ValueError('Scope touches frozen pixels')
        return active
    def module_scope(self,layers,previous,scope,a,freeze,subject):
        limits=scope.get('modules',{})
        if not limits:return
        new={x['op']['id']:x for x in layers};old={x['op']['id']:x for x in previous}
        for identity in self.changed_against(layers,previous):
            after=new.get(identity);before=old.get(identity)
            if after and before and after['module']==before['module'] and after['op']['type']==before['op']['type']:
                current=self.active(after,a,freeze,subject);prior=self.active(before,a,freeze,subject)
                op=after['op'];prev=before['op'];mask=self.reader.mask(op['mask'],a.shape[:2]);oldmask=self.reader.mask(prev['mask'],a.shape[:2])
                if op['type']=='tone' and {k:v for k,v in op.items() if k!='mask'}=={k:v for k,v in prev.items() if k!='mask'}:
                    delta=(mask!=oldmask)&(current|prior)
                elif op['type']=='overlay' and op.get('blend','normal')==prev.get('blend','normal'):
                    layer,_=self.reader.image(op['layer'],'RGBA');oldlayer,_=self.reader.image(prev['layer'],'RGBA')
                    weight=mask.astype(np.float64)*layer[...,3]*op.get('opacity',1)
                    oldweight=oldmask.astype(np.float64)*oldlayer[...,3]*prev.get('opacity',1)
                    delta=((weight!=oldweight)|(np.any(layer[...,:3]!=oldlayer[...,:3],axis=2)&((weight>0)|(oldweight>0))))&(current|prior)
                else:delta=current|prior
                # Reordering can change interactions across the entire active region.
                common=set(new)&set(old)
                if [x['op']['id'] for x in layers if x['op']['id'] in common]!=[x['op']['id'] for x in previous if x['op']['id'] in common]:delta|=current|prior
                module=after['module']
                if module in limits and np.any(delta & ~(self.reader.mask(limits[module],a.shape[:2])>0)):raise ValueError('Module Modification Scope failed')
            else:
                for item in (after,before):
                    if item and item['module'] in limits and np.any(self.active(item,a,freeze,subject)&~(self.reader.mask(limits[item['module']],a.shape[:2])>0)):raise ValueError('Module Modification Scope failed')
    def verify_references(self,plan):
        for ref in plan.get('reference_map',[]):
            if isinstance(ref['reference'],dict):r.asset(self.root,ref['reference'])
    def verify_layers(self,layers):
        for item in layers:
            if set(item)!={'module','op'} or item['module'] not in MODULES:raise ValueError('Invalid module')
            r.validate_operations([item['op']])
            for field in ('mask','layer'):
                if field in item['op']:r.asset(self.root,item['op'][field])
        for ref in self.state.get('foreground_vfx',{}).values():
            if isinstance(ref,dict) and 'sha256' in ref:r.asset(self.root,ref)
    def render(self,layers,a,base,freeze,subject):
        start=time.perf_counter();self.verify_layers(layers)
        key=r.canonical({'engine':32,'base':self.state['base']['sha256'],'source':self.meta['source']['sha256'],
            'freeze':hashlib.sha256(np.ascontiguousarray(freeze).tobytes()).hexdigest(),
            'subject':hashlib.sha256(np.ascontiguousarray(subject).tobytes()).hexdigest(),
            'foreground':self.state.get('foreground_vfx')})
        keys=[]
        for item in layers:key=r.canonical({'prefix':key,'layer':item});keys.append(key)
        out,resumed=self.render_cache.restore(keys,base);self.hits+=resumed
        self.hard(a,out,freeze)
        for index in range(resumed,len(layers)):
            item=layers[index];t0=time.perf_counter();active=self.active(item,a,freeze,subject)
            out=r.process(self.root,out,freeze,[item['op']],mask_loader=self.reader.mask,image_loader=self.reader.image)
            self.hard(a,out,freeze);self.render_cache.store(keys[index],out,active);self.misses+=1
            module=item['module'];self.modules[module]=self.modules.get(module,0)+time.perf_counter()-t0
        self.times['render']=time.perf_counter()-start
        return out

    def run(self,pid):
        start=time.perf_counter();path,rec=self.plan(pid);plan=rec['plan'];self.approvals(rec)
        if plan['parent']!=self.state['head'] or plan.get('branch',self.state['branch'])!=self.state['branch'] or rec['status'] in {'QC_PASS','QC_FAIL','FINAL','NO_ACTION_REQUIRED'}:raise ValueError('Plan completed or parent changed')
        saved=copy.deepcopy(self.state);hits,misses=self.hits,self.misses;decodes=self.reader.decodes
        read_bytes,written_bytes=self.render_cache.bytes_read,self.render_cache.bytes_written
        self.times={};self.modules={};rec['status']='EXECUTING';r.write(path,rec)
        try:
            t0=time.perf_counter();a,base,freeze,subject=self.baseline();parent=self.picture(plan['parent']);self.times['decode_baseline']=time.perf_counter()-t0
            if plan['source_hash']!=self.meta['source']['sha256'] or plan['base_hash']!=self.state['base']['sha256']:raise ValueError('Plan source/base changed')
            extra=self.reader.mask(plan['scope']['freeze'],a.shape[:2])>0;allowed=self.reader.mask(plan['scope']['allowed'],a.shape[:2])>0
            changed=self.changed(plan['layers']);self.verify_layers(plan['layers']);self.verify_references(plan)
            self.module_scope(plan['layers'],self.recipe(plan['parent']),plan['scope'],a,freeze,subject)
            if plan['layers']==self.recipe(plan['parent']):
                out=parent;self.hits+=1;self.times['render']=0.0
            else:out=self.render(plan['layers'],a,base,freeze,subject)
            rec['status']='QC_RUNNING';r.write(path,rec);t0=time.perf_counter();self.hard(a,out,freeze,parent,allowed)
            if not np.array_equal(parent[extra],out[extra]):raise ValueError('Revision Pixel Freeze failed')
            qc=self.quality(a,out,freeze)
            if not qc['pass']:raise ValueError('QC failed: '+str(qc['errors']))
            self.times['qc']=time.perf_counter()-t0
            if np.array_equal(out,parent):
                rec['status']='NO_ACTION_REQUIRED';r.write(path,rec);return {'status':rec['status'],'version':self.state['head']}
            index=len(self.state['versions'])+1
            while (self.root/'state/v3/versions'/('v'+str(index).zfill(4))).exists():index+=1
            vid='v'+str(index).zfill(4);vd=self.root/'state/v3/versions'/vid;vd.mkdir()
            t0=time.perf_counter();Image.fromarray(out).save(vd/'image.png',compress_level=3);self.times['png_write']=time.perf_counter()-t0
            info={'parent':plan['parent'],'recipe':plan['layers'],'plan':pid,'plan_hash':rec['hash'],
                  'image_hash':r.digest(vd/'image.png'),'qc':qc,'mode':plan['mode'],'branch':self.state['branch']}
            r.write(vd/'version.json',info,True)
            previous=self.recipe(plan['parent']);modules={x['module'] for x in plan['layers']+previous if x['op']['id'] in changed}
            invalidated=self.invalidate_modules(modules)
            self.state['versions'][vid]=r.canonical(info);self.state['head']=vid;self.state['branches'][self.state['branch']]=vid;self.state['mode']=plan['mode']
            for node in modules & {'background','vfx'}:self.state[node+'_version']=vid
            self.state['reference_map']=plan['reference_map'];self.state['reference_groups']=plan.get('reference_groups',[]);self.state['completed_operations'].append(pid)
            rec['status']='QC_PASS';rec['version']=vid;r.write(path,rec)
            result={'status':'QC_PASS','version':vid,'changed_layers':changed,'invalidated':invalidated}
        except Exception as e:
            self.state=saved;rec['status']='QC_FAIL';rec['error']=str(e);r.write(path,rec)
            r.write(self.root/'qc'/(pid+'.json'),{'status':'QC_FAIL','error':str(e),'retained_head':self.state['head']})
            raise
        finally:
            self.times['total']=time.perf_counter()-start
            attempts=rec['attempts'];generative=[x for x in attempts if x.get('uses_generation',True)]
            self.state['telemetry'].append({'plan':pid,'times':dict(self.times),'module_compute_seconds':dict(self.modules),
                'cache_hits':self.hits-hits,'cache_misses':self.misses-misses,'asset_decodes':self.reader.decodes-decodes,
                'cache_bytes_read':self.render_cache.bytes_read-read_bytes,'cache_bytes_written':self.render_cache.bytes_written-written_bytes,
                'generation_reservations':len(generative),'generation_calls':sum(x.get('status') in {'success','failure'} for x in generative) if all(x.get('status') in {'success','failure'} for x in generative) else None,
                'retries':sum(x['kind']=='correction' for x in attempts),'status':rec['status'],'user_acceptance':'unknown'})
            self.save()
        return result
    def invalidate_modules(self,modules):
        affected=set()
        for module in modules:
            node='grading' if module=='retouch' else module
            if node in GRAPH:
                affected.add(node)
        while True:
            more={key for key,deps in GRAPH.items() if affected.intersection(deps)}-affected
            if not more:break
            affected|=more
        for node in affected:self.state['nodes'][node]+=1
        return sorted(affected)

    def previews(self,vid,rois):
        stage_start=time.perf_counter();out=self.picture(vid);mode=self.info(vid)['mode'];folder=self.root/'previews'/vid;folder.mkdir(exist_ok=True)
        im=Image.fromarray(out);im.thumbnail((1600,1600));im.save(folder/'overview.png',compress_level=3)
        files=[str(folder/'overview.png')]
        for i,box in enumerate(rois[:MODES[mode]['rois']]):
            if len(box)!=4 or any(type(x)!=int for x in box) or not (0<=box[0]<box[2]<=out.shape[1] and 0<=box[1]<box[3]<=out.shape[0]):raise ValueError('ROI out of native canvas')
            p=folder/f'roi-{i}.png';Image.fromarray(out).crop(box).save(p,compress_level=3);files.append(str(p))
        self.event('preview',stage_start,{'version':vid,'native_rois':len(files)-1})
        return {'preview_only':True,'files':files,'native_rois':len(files)-1}
    def inspect(self,vid,checks,evidence):
        stage_start=time.perf_counter();info=self.info(vid)
        required={'space','edges','lighting','effects','intent'}
        if set(checks)!=required or any(x.get('decision') not in {'pass','fail'} or not x.get('observation','').strip() for x in checks.values()):raise ValueError('Five visual decisions/observations required')
        captured=[]
        for path in evidence:
            p=Path(path).resolve()
            with Image.open(p) as im:im.verify()
            captured.append({'path':str(p),'hash':r.digest(p)})
        if not captured:raise ValueError('Evidence required')
        r.write(self.root/'state/v3/versions'/vid/'inspection.json',{'checks':checks,'evidence':captured,'hash':info['image_hash']})
        passed=all(x['decision']=='pass' for x in checks.values());self.event('inspect',stage_start,{'version':vid,'pass':passed,'manual_not_aesthetic_model':True})
        return {'pass':passed,'manual_not_automatic_aesthetic_certification':True}
    def export(self,vid,output,quote):
        stage_start=time.perf_counter();info=self.info(vid);_,rec=self.plan(info['plan']);self.approvals(rec)
        if info['plan_hash']!=rec['hash']:raise ValueError('Plan changed')
        a,base,freeze,subject=self.baseline();out=self.picture(vid);plan=rec['plan'];self.verify_references(plan)
        expected=self.render(info['recipe'],a,base,freeze,subject)
        if not np.array_equal(out,expected):raise ValueError('Recipe output mismatch')
        self.module_scope(info['recipe'],self.recipe(info['parent']),plan['scope'],a,freeze,subject)
        parent=self.picture(info['parent']);allowed=load_mask(r.asset(self.root,plan['scope']['allowed']),a.shape[:2])>0
        self.hard(a,out,freeze,parent,allowed)
        extra=load_mask(r.asset(self.root,plan['scope']['freeze']),a.shape[:2])>0
        if not np.array_equal(parent[extra],out[extra]) or not self.quality(a,out,freeze)['pass']:raise ValueError('Final QC failed')
        inspection=r.read(self.root/'state/v3/versions'/vid/'inspection.json')
        if inspection['hash']!=info['image_hash'] or set(inspection['checks'])!={'space','edges','lighting','effects','intent'} or not inspection.get('evidence') or any(x.get('decision')!='pass' or not isinstance(x.get('observation'),str) or not x['observation'].strip() for x in inspection['checks'].values()):raise ValueError('Visual QC failed/stale')
        for ev in inspection['evidence']:
            if r.digest(ev['path'])!=ev['hash']:raise ValueError('Visual evidence changed')
        target=Path(output).resolve()
        if not quote.strip() or target.exists() or target.is_relative_to(self.root) or target.suffix.lower()!='.png':raise ValueError('New external PNG and real export authorization required')
        with (self.root/'state/v3/versions'/vid/'image.png').open('rb') as src,target.open('xb') as dst:shutil.copyfileobj(src,dst)
        plan_path,rec=self.plan(info['plan']);rec['status']='FINAL';rec['export_authorization']=quote;r.write(plan_path,rec)
        self.event('export',stage_start,{'version':vid,'output_hash':r.digest(target)})
        return {'export':str(target),'hash':r.digest(target),'user_quote':quote}
    def checkout(self,vid,branch=None):
        self.picture(vid);before=self.recipe();after=self.recipe(vid);changed=self.changed(after)
        if branch:
            r.identifier(branch)
            if branch in self.state['branches']:raise ValueError('Branch exists')
            self.state['branch']=branch
        invalidated=self.invalidate_modules({x['module'] for x in before+after if x['op']['id'] in changed})
        self.state['head']=vid;self.state['branches'][self.state['branch']]=vid
        for module in ('background','vfx'):
            self.state[module+'_version']=vid if any(x['module']==module for x in after) else None
        active_plan={} if vid=='base' else self.plan(self.info(vid)['plan'])[1]['plan']
        self.state['reference_map']=active_plan.get('reference_map',[]);self.state['reference_groups']=active_plan.get('reference_groups',[])
        self.save();return {'head':vid,'branch':self.state['branch'],'invalidated':invalidated}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',required=True)
    p.add_argument('action',choices=['attach','plan','revise','metadata','approve','run','attempt','preview','inspect','export','checkout','state','cache-put','cache-get','feedback','profile','task','route','context','reference-analysis','attempt-result'])
    p.add_argument('--file',type=Path);args=p.parse_args();data=r.read(args.file) if args.file else {}
    try:
        with r.locked(Path(args.project)):
            project=Project(args.project);action=args.action
            if action=='attach':result=project.attach(**data)
            elif action=='plan':result=project.prepare(data)
            elif action=='revise':result=project.revise(data)
            elif action=='metadata':result=project.metadata()
            elif action=='approve':result=project.approve(**data)
            elif action=='run':result=project.run(**data)
            elif action=='attempt':result=project.attempt(**data)
            elif action=='attempt-result':result=project.attempt_result(**data)
            elif action=='reference-analysis':result=project.reference_analysis(**data)
            elif action=='route':result=project.route(data)
            elif action=='context':result=project.context()
            elif action=='preview':result=project.previews(**data)
            elif action in {'inspect','export','checkout'}:result=getattr(project,action)(**data)
            elif action=='cache-put':
                result=project.cached(data['name'],data['level'],data['deps'],data['inputs'],lambda:data['value'],files=data.get('files'));project.save()
            elif action=='cache-get':
                def missing():raise ValueError('CACHE MISS: analysis required')
                result=project.cached(data['name'],data['level'],data['deps'],data['inputs'],missing,files=data.get('files'))
            elif action=='feedback':
                if data['decision'] not in {'GOOD','BAD'} or data['category'] not in {'Intent','Planning','Execution','QC','Performance'} or not data['quote'].strip():raise ValueError('Explicit feedback required')
                project.info(data['version']);project.state['feedback'].append(data)
                r.write(project.root/'reference_feedback'/('feedback-'+str(len(project.state['feedback'])).zfill(4)+'.json'),data,True)
                project.save();result=data
            elif action=='task':result=project.new_task(**data)
            elif action=='profile':
                if data['level'] not in {'persistent','project','image'} or not data['quote'].strip():raise ValueError('Preference level and quote required')
                project.state['profile'][data['level']].update(data['values']);project.save()
                result={**project.state['profile']['persistent'],**project.state['profile']['project'],**project.state['profile']['image']}
            else:result=project.state
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,OSError,KeyError,TypeError) as e:p.exit(2,'BLOCKED: '+str(e)+'\n')
if __name__=='__main__':main()
