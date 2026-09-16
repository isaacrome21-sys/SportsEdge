import importlib.util, unittest
from pathlib import Path
_spec=importlib.util.spec_from_file_location("persist_captured_evidence",Path(__file__).resolve().parents[1]/"scripts"/"persist_captured_evidence.py"); pe=importlib.util.module_from_spec(_spec); _spec.loader.exec_module(pe)
HEAD="a"*40; REMOTE_OK=f"{HEAD}\trefs/heads/main\n"
class FakeGit:
 def __init__(self,dirty=True,push_results=None,remote=REMOTE_OK): self.dirty=dirty; self.push_results=list(push_results or [(0,"","")]); self.remote=remote; self.calls=[]
 def __call__(self,args):
  self.calls.append(list(args)); a=list(args)
  if a[:2]==["git","status"]: return (0,"?? data/mlb_forward_capture/x.json\n" if self.dirty else "","")
  if a[:2]==["git","push"]: return self.push_results.pop(0) if self.push_results else (0,"","")
  if a[:2]==["git","rev-parse"]: return (0,HEAD+"\n","")
  if a[:2]==["git","ls-remote"]: return (0,self.remote,"")
  return (0,"","")
 def pushes(self): return sum(1 for c in self.calls if c[:2]==["git","push"])
class PersistTest(unittest.TestCase):
 def test_clean_tree(self): self.assertEqual(pe.persist(paths=["data/x"],runner=FakeGit(dirty=False))["status"],"NOTHING_TO_PERSIST")
 def test_happy_path(self): self.assertEqual(pe.persist(paths=["data/x"],runner=FakeGit())["status"],"PERSISTED")
 def test_permission_no_retry(self):
  g=FakeGit(push_results=[(1,"","protected branch hook declined")])
  with self.assertRaises(pe.PersistenceBlocked) as c: pe.persist(paths=["data/x"],runner=g)
  self.assertEqual(c.exception.reason,"BLOCKED_PERSISTENCE_PERMISSION"); self.assertEqual(g.pushes(),1)
 def test_unverified(self):
  with self.assertRaises(pe.PersistenceBlocked) as c: pe.persist(paths=["data/x"],runner=FakeGit(remote="b"*40+"\trefs/heads/main\n"))
  self.assertEqual(c.exception.reason,"BLOCKED_PERSISTENCE_UNVERIFIED")
if __name__=="__main__": unittest.main()
