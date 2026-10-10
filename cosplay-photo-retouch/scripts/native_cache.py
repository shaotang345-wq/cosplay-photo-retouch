"""Native array caching. No resampling; every file read still checks SHA-256."""
from collections import OrderedDict
from pathlib import Path
import os
import numpy as np
import retouch as r
from acceptance import load_image

class AssetReader:
    def __init__(self, root, max_bytes=64*1024*1024):
        self.root=Path(root);self.max_bytes=max_bytes;self.arrays=OrderedDict();self.bytes=0;self.decodes=0
    def image(self, ref, mode=None):
        path=r.asset(self.root,ref)  # Never trust a cached decode without checking its source.
        key=(ref['sha256'],mode)
        if key in self.arrays:
            self.arrays.move_to_end(key);return self.arrays[key]
        array,actual_mode=load_image(path,mode);self.decodes+=1;array.flags.writeable=False
        if array.nbytes<=self.max_bytes:
            while self.arrays and self.bytes+array.nbytes>self.max_bytes:
                _,(old,_)=self.arrays.popitem(last=False);self.bytes-=old.nbytes
            self.arrays[key]=(array,actual_mode);self.bytes+=array.nbytes
        return array,actual_mode
    def mask(self, ref, shape):
        array,_=self.image(ref,'L')
        if array.shape!=shape:raise ValueError('Mask dimensions differ; resampling forbidden')
        return array

class RenderCache:
    def __init__(self, folder):self.folder=Path(folder);self.bytes_read=0;self.bytes_written=0
    def paths(self,key):return self.folder/(key+'.npy'),self.folder/(key+'.json')
    def record(self,key):
        data,meta=self.paths(key)
        if not data.exists() and not meta.exists():return None
        if not data.exists() or not meta.exists():raise ValueError('Incomplete render cache; inspect or remove only this cache entry')
        rec=r.read(meta)
        if rec.get('key')!=key or rec.get('kind') not in {'full','tile'}:raise ValueError('Render cache metadata changed')
        return rec
    def load(self,key,rec,shape):
        data,_=self.paths(key)
        if r.digest(data)!=rec['hash']:raise ValueError('Render cache changed')
        value=np.load(data,allow_pickle=False);self.bytes_read+=data.stat().st_size
        if value.dtype!=np.uint8:raise ValueError('Render cache dtype changed')
        if rec['kind']=='full':
            if list(value.shape)!=list(shape):raise ValueError('Render cache shape changed')
        else:
            box=rec.get('box')
            if not isinstance(box,list) or len(box)!=4 or any(type(x)!=int for x in box):raise ValueError('Render cache box invalid')
            x0,y0,x1,y1=box
            if not (0<=x0<x1<=shape[1] and 0<=y0<y1<=shape[0]) or value.shape!=(y1-y0,x1-x0,shape[2]):raise ValueError('Render cache tile dimensions changed')
        return value
    def restore(self,keys,base):
        # Find the longest valid prefix; jump to its last full checkpoint and replay tiny native tiles.
        end=len(keys)
        while end and self.record(keys[end-1]) is None:end-=1
        if not end:return base.copy(),0
        chain=[];index=end-1
        while index>=0:
            rec=self.record(keys[index])
            if rec is None:return base.copy(),0
            chain.append((keys[index],rec))
            if rec['kind']=='full':break
            index-=1
        out=base.copy()
        for key,rec in reversed(chain):
            value=self.load(key,rec,base.shape)
            if rec['kind']=='full':out=value
            else:
                x0,y0,x1,y1=rec['box'];out[y0:y1,x0:x1]=value
        return out,end
    def store(self,key,out,active):
        rows=np.flatnonzero(active.any(axis=1));cols=np.flatnonzero(active.any(axis=0))
        rec={'key':key,'kind':'full'};value=out
        if len(rows) and len(cols):
            box=[int(cols[0]),int(rows[0]),int(cols[-1])+1,int(rows[-1])+1];x0,y0,x1,y1=box
            if (x1-x0)*(y1-y0)<=out.shape[0]*out.shape[1]//4:
                rec.update(kind='tile',box=box);value=out[y0:y1,x0:x1]
        data,meta=self.paths(key)
        if data.exists() or meta.exists():
            existing=self.record(key);cached=self.load(key,existing,out.shape)
            if existing['kind']=='tile':
                x0,y0,x1,y1=existing['box'];expected=out[y0:y1,x0:x1]
            else:expected=out
            if not np.array_equal(cached,expected):raise ValueError('Recomputed render cache differs')
            return
        # Publishing data before metadata is safe: incomplete entries refuse execution.
        with data.open('xb') as stream:np.save(stream,value,allow_pickle=False)
        rec['hash']=r.digest(data);r.write(meta,rec,True);self.bytes_written+=data.stat().st_size
