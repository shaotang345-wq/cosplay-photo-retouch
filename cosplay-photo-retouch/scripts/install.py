"""Install/update one unified skill with byte verification and rollback backups."""
import argparse,datetime,hashlib,json,os,shutil,tempfile
from pathlib import Path
NAMES=['cosplay-photo-retouch']
LEGACY=['cosplay-master','cosplay-analyzer','cosplay-retouch','cosplay-background','cosplay-vfx','cosplay-finish']
def files(root):
 result={}
 for p in root.rglob('*'):
  if p.is_symlink():raise ValueError('Symlink not supported')
  if p.is_file() and '__pycache__' not in p.parts and '.venv' not in p.parts and p.suffix!='.pyc':
   result[str(p.relative_to(root))]=hashlib.sha256(p.read_bytes()).hexdigest()
 return result
def install(source,skills,backup):
 source,skills,backup=map(lambda p:Path(p).resolve(),(source,skills,backup))
 for left,right in ((source,skills),(source,backup),(skills,backup)):
  if left==right or left.is_relative_to(right) or right.is_relative_to(left):
   raise ValueError('Unsafe install/backup roots: must be disjoint')
 for name in NAMES:
  if not (source/name/'SKILL.md').is_file():raise ValueError('Incomplete bundle: '+name)
 skills.mkdir(parents=True,exist_ok=True);backup.mkdir(parents=True,exist_ok=False)
 installed=[];moved=[];report={}
 try:
  for name in NAMES:
   src=source/name;target=skills/name;expected=files(src)
   if target.exists() and files(target)==expected:
    report[name]={'status':'unchanged','files':len(expected)};continue
   # Targets and backups are fixed children, never arbitrary recursive deletion.
   if target.parent!=skills or (backup/name).parent!=backup:raise ValueError('Containment failed')
   staged=backup/(name+'.staged');shutil.copytree(src,staged,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.venv'))
   if files(staged)!=expected:raise ValueError('Staged copy failed hash verification')
   if target.exists():target.rename(backup/name);moved.append(name)
   staged.rename(target);installed.append(name)
   if files(target)!=expected:raise ValueError('Installed hash mismatch')
   report[name]={'status':'installed','files':len(expected)}
  for name in LEGACY:
   target=skills/name
   if target.is_symlink():raise ValueError('Legacy symlink unsupported')
   if target.exists():
    if target.resolve().parent!=skills:raise ValueError('Containment failed')
    target.rename(backup/name);moved.append(name)
 except Exception:
  for name in reversed(installed):
   target=skills/name
   if target.exists():target.rename(backup/(name+'.failed'))
  for name in reversed(moved):(backup/name).rename(skills/name)
  raise
 (backup/'installation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 return {'skills_dir':str(skills),'backup':str(backup),'verification':report}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--skills-dir',type=Path);p.add_argument('--backup-dir',type=Path)
 args=p.parse_args();codex=Path(os.environ.get('CODEX_HOME',Path.home()/'.codex'))
 backup=args.backup_dir or codex/'skill-backups'/('cosplay-unified-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
 print(json.dumps(install(Path(__file__).resolve().parents[2],args.skills_dir or codex/'skills',backup),indent=2))
if __name__=='__main__':main()
