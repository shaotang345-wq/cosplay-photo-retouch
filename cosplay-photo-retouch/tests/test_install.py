import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import install as installer
class InstallTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.d=Path(self.tmp.name)
  self.src=self.d/'bundle';self.dst=self.d/'skills';self.backup=self.d/'backup'
  p=self.src/installer.NAMES[0];p.mkdir(parents=True);(p/'SKILL.md').write_text('new')
  for name in installer.NAMES+installer.LEGACY:
   p=self.dst/name;p.mkdir(parents=True);(p/'SKILL.md').write_text('old '+name)
 def test_migration_preserves_backup_and_single_entry(self):
  installer.install(self.src,self.dst,self.backup)
  self.assertEqual([p.name for p in self.dst.iterdir()],installer.NAMES)
  self.assertEqual(installer.files(self.src/installer.NAMES[0]),installer.files(self.dst/installer.NAMES[0]))
  for n in installer.NAMES+installer.LEGACY:self.assertEqual((self.backup/n/'SKILL.md').read_text(),'old '+n)
 def test_failure_during_legacy_migration_rolls_back_all(self):
  real=Path.rename
  def fail(p,target):
   if p==self.dst/installer.LEGACY[1]:raise OSError('synthetic failure')
   return real(p,target)
  with patch.object(Path,'rename',fail):
   with self.assertRaises(OSError):installer.install(self.src,self.dst,self.backup)
  for n in installer.NAMES+installer.LEGACY:self.assertEqual((self.dst/n/'SKILL.md').read_text(),'old '+n)
 def test_overlap_rejected(self):
  with self.assertRaisesRegex(ValueError,'Unsafe'):installer.install(self.src,self.dst,self.dst/'backup')
  self.assertFalse((self.dst/'backup').exists())
if __name__=='__main__':unittest.main()
