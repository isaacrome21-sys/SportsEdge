from pathlib import Path
import unittest
class SecurityNotesTests(unittest.TestCase):
    def test_provider_id_not_sufficient(self):self.assertIn("Do not trust provider event IDs alone",Path("docs/BINDING_SECURITY_NOTES.md").read_text())
if __name__=="__main__":unittest.main()
