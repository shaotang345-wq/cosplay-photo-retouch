"""Native-grid candidate cutouts: model provides only alpha, never foreground RGB."""
import argparse, hashlib, importlib.metadata, io, json, os, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageCms, ImageFilter
MODELS=('u2netp','u2net','isnet-general-use','birefnet-general-lite','birefnet-portrait')

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def load_source(path):
    with Image.open(path) as im:
        if im.format not in ('PNG','JPEG') or im.mode not in ('RGB','RGBA'):
            raise ValueError('Only 8-bit RGB/RGBA PNG/JPEG supported')
        if getattr(im,'n_frames',1)!=1 or im.getexif().get(274,1)!=1:
            raise ValueError('Frame/orientation changes forbidden')
        icc=im.info.get('icc_profile')
        if icc and ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc))).strip()!='sRGB IEC61966-2.1':
            raise ValueError('Unsupported ICC; color-managed preparation required')
        if any(im.info.get(k) is not None for k in ('gamma','chromaticity')):
            raise ValueError('Special color metadata unsupported')
        return np.array(im),icc

def mask_file(path,size):
    with Image.open(path) as im:
        if im.format!='PNG' or im.mode!='L' or im.size!=size or getattr(im,'n_frames',1)!=1 or im.getexif().get(274,1)!=1:
            raise ValueError('Mask must be same-size L PNG; no resizing')
        return np.array(im)

def assets_from_mask(source,mask,keep=None,padding=12):
    if mask.dtype!=np.uint8 or mask.shape!=source.shape[:2] or not mask.any():
        raise ValueError('Mask empty, wrong type, or wrong dimensions')
    if isinstance(padding,bool) or not isinstance(padding,int) or not 0<=padding<=40:
        raise ValueError('Padding must be integer 0..40')
    if keep is not None and keep.shape!=mask.shape: raise ValueError('Keep mask dimensions differ')
    chosen=mask.copy()
    if keep is not None: chosen[keep!=0]=255
    alpha=source[...,3] if source.shape[2]==4 else np.full(mask.shape,255,dtype=np.uint8)
    alpha=np.rint(chosen.astype(np.float64)*alpha/255).astype(np.uint8)
    if not alpha.any(): raise ValueError('No retained visible foreground')
    rgba=np.empty((*mask.shape,4),dtype=np.uint8);rgba[...,:3]=source[...,:3];rgba[...,3]=alpha
    protected=(alpha>0).astype(np.uint8)*255
    if padding: protected=np.array(Image.fromarray(protected).filter(ImageFilter.MaxFilter(2*padding+1)))
    if keep is not None: protected[keep!=0]=255
    return rgba,protected,255-protected

def infer_mask(rgb,source_sha,model,cache):
    if model not in MODELS: raise ValueError('Only local CPU models allowed')
    cache=cache.resolve()
    version=importlib.metadata.version('rembg')
    os.environ['U2NET_HOME']=str(cache.resolve())
    if os.environ.get('MODEL_CHECKSUM_DISABLED') is not None: raise ValueError('Checksum verification disabled')
    # A valid mask cache must not initialize an ONNX session.
    folder=cache/'mask-cache'
    for metadata in sorted(folder.glob('*.json')):
        saved=json.loads(metadata.read_text(encoding='utf-8'))
        if (saved.get('source_sha256'),saved.get('model'),saved.get('rembg')) != (source_sha,model,version):
            continue
        weights=saved.get('weights',{})
        if not weights: continue
        valid=True
        for rel,expected in weights.items():
            weight=(cache/rel).resolve()
            if not weight.is_relative_to(cache): raise ValueError('Cached weight path escaped')
            if not weight.is_file() or sha(weight)!=expected: valid=False;break
        if not valid: continue
        cached=metadata.with_suffix('.png')
        if not cached.is_file() or sha(cached)!=saved.get('mask_sha256'):
            raise ValueError('Cached mask changed')
        return mask_file(cached,(rgb.shape[1],rgb.shape[0])),{**saved,'cache_hit':True,'session_loaded':False}
    from rembg import new_session,remove
    session=new_session(model,providers=['CPUExecutionProvider'])
    weights=sorted(Path(session.model_dir()).rglob('*.onnx')) or sorted(cache.glob(model+'*.onnx'))
    if not weights: raise ValueError('No model weights for provenance')
    provenance={'source_sha256':source_sha,'model':model,'rembg':version,
                'weights':{str(p.relative_to(cache)):sha(p) for p in weights}}
    key=hashlib.sha256(json.dumps(provenance,sort_keys=True).encode()).hexdigest()
    folder=cache/'mask-cache';folder.mkdir(parents=True,exist_ok=True)
    cached=folder/(key+'.png');metadata=folder/(key+'.json')
    if cached.exists() and metadata.exists():
        if json.loads(metadata.read_text(encoding='utf-8')).get('mask_sha256')!=sha(cached):
            raise ValueError('Cached mask changed')
        return mask_file(cached,(rgb.shape[1],rgb.shape[0])),{**provenance,'cache_hit':True}
    result=remove(Image.fromarray(rgb),session=session,only_mask=True,post_process_mask=False,alpha_matting=False)
    if not isinstance(result,Image.Image) or result.mode!='L' or result.size!=(rgb.shape[1],rgb.shape[0]):
        raise ValueError('Model returned incompatible mask')
    mask=np.array(result)
    if not mask.any(): raise ValueError('Model mask empty')
    if cached.exists() or metadata.exists(): raise ValueError('Incomplete cache entry; no overwrite')
    result.save(cached)
    metadata.write_text(json.dumps({**provenance,'mask_sha256':sha(cached)},indent=2),encoding='utf-8')
    return mask,{**provenance,'cache_hit':False}

def create(input_path,output_dir,mask_path=None,keep_path=None,model='u2netp',padding=12,model_cache=None):
    input_path,output_dir=Path(input_path).resolve(),Path(output_dir).resolve()
    if output_dir.exists(): raise ValueError('Output directory must be new')
    source,icc=load_source(input_path);size=(source.shape[1],source.shape[0]);source_sha=sha(input_path)
    if mask_path:
        mask=mask_file(mask_path,size);backend={'backend':'supplied-mask','mask_sha256':sha(mask_path)}
    else:
        codex=Path(os.environ['CODEX_HOME']) if os.environ.get('CODEX_HOME') else Path.home()/'.codex'
        cache=Path(model_cache) if model_cache else codex/'skill-envs/cosplay-cutout/models'
        mask,backend=infer_mask(source[...,:3],source_sha,model,cache)
    keep=mask_file(keep_path,size) if keep_path else None
    rgba,protected,background=assets_from_mask(source,mask,keep,padding)
    assert np.array_equal(rgba[...,:3],source[...,:3])
    output_dir.mkdir(parents=True)
    for name,a in [('mask-candidate.png',mask),('foreground-candidate.png',rgba),
                   ('protect-candidate.png',protected),('background-candidate.png',background)]:
        Image.fromarray(a).save(output_dir/name,**({'icc_profile':icc} if icc and a.ndim==3 else {}))
    with Image.open(output_dir/'foreground-candidate.png') as im:
        if im.size!=size or not np.array_equal(np.array(im)[...,:3],source[...,:3]):
            raise ValueError('Saved cutout failed pixel check; do not use outputs')
    if sha(input_path)!=source_sha: raise ValueError('Input changed; do not use outputs')
    report={'status':'CANDIDATE_REQUIRES_EDGE_REVIEW','source_sha256':source_sha,'native_size':list(size),
            'rgb_pixels_changed':0,'rgb_resampled':False,'alpha_changed_intentionally':True,
            'padding_native_pixels':padding,'manual_keep_sha256':sha(keep_path) if keep_path else None,
            'icc_preserved':bool(icc),'backend':backend,'model_internal_resize':not bool(mask_path),
            'human_review_required':['hair','costume','props','translucent edges'],
            'outputs':{n:sha(output_dir/n) for n in ('mask-candidate.png','foreground-candidate.png','protect-candidate.png','background-candidate.png')}}
    (output_dir/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',required=True);p.add_argument('--output-dir',required=True)
    p.add_argument('--mask');p.add_argument('--keep');p.add_argument('--padding',type=int,default=12)
    p.add_argument('--model',choices=MODELS,default='u2netp');p.add_argument('--model-cache')
    a=p.parse_args()
    try:
        print(json.dumps(create(a.input,a.output_dir,a.mask,a.keep,a.model,a.padding,a.model_cache),ensure_ascii=False,indent=2));return 0
    except Exception as e:
        print('BLOCKED: '+str(e),file=sys.stderr);return 2
if __name__=='__main__': raise SystemExit(main())
