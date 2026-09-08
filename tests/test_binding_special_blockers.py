from pathlib import Path
import unittest
class SpecialBlockerTests(unittest.TestCase):
    def test_f5_and_first_hr_remain_blocked(self):
        t=Path("docs/BINDING_F5_FIRST_HR_BLOCKERS.md").read_text();self.assertIn("cannot be certified",t);self.assertIn("cannot use the two-way",t)
if __name__=="__main__":unittest.main()
