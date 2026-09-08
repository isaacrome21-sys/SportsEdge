from pathlib import Path
import unittest
class ReviewStateTests(unittest.TestCase):
    def test_review_not_promotion(self):
        t=Path("docs/BINDING_IMPLEMENTATION_COMPLETE_FOR_REVIEW.md").read_text();self.assertIn("Ready for review, not promotion",t);self.assertIn("not ready for production promotion",t)
if __name__=="__main__":unittest.main()
