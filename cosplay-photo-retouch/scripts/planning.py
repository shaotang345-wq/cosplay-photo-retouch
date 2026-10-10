"""Small deterministic planner for already-interpreted user instructions, not an NLP model."""
import copy
from pathlib import Path
import retouch as r

PARAMETERS={'opacity','blend','mask','exposure','contrast','saturation','gamma','gains','layer'}

def minimal_plan(project,request):
    raw=copy.deepcopy(request)
    if 'updates' not in raw:raise ValueError('Route requires explicit existing-layer updates; new designs use plan')
    current={x['op']['id']:x for x in project.recipe()};updates=raw['updates'];changed={};modules=set();needs_asset=False
    if not isinstance(updates,dict):raise ValueError('Updates must be a mapping')
    for identity,values in updates.items():
        if identity not in current or not isinstance(values,dict) or set(values)-PARAMETERS:raise ValueError('Unknown layer or unsupported update')
        original=current[identity]['op'];effective={}
        for field,value in values.items():
            equal=original.get(field)==value
            if field in {'mask','layer'} and isinstance(value,str):equal=original.get(field,{}).get('sha256')==r.digest(Path(value))
            if not equal:effective[field]=value
        if effective:
            candidate=copy.deepcopy(original);candidate.update(effective);r.validate_operations([candidate])
            changed[identity]=effective;modules.add(current[identity]['module']);needs_asset|='layer' in effective
    if not changed:return {'status':'NO_ACTION_REQUIRED','changed_layers':[],'generation_calls':0,'reason':'Requested parameters/assets already match current recipe'}
    raw['updates']=changed;raw.setdefault('mode','standard');raw.setdefault('generation_policy','assets' if needs_asset else 'none')
    return {'status':'PLAN_REQUIRED','request':raw,'changed_layers':sorted(changed),'run_modules':sorted(modules),
        'reuse_layers':sorted(set(current)-set(changed)),'route':'asset replacement' if needs_asset else 'existing parameters/masks',
        'generation_required':False,'generation_policy':raw['generation_policy'],
        'note':'Asset replacement uses the supplied file; generate only if no suitable asset exists, with a separate approved budget reservation.'}
