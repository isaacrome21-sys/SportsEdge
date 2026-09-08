import unittest
from sportsedge.binding_value_scanner import BindingValueError, assert_no_quote_identity_in_model_payload

class ScannerTests(unittest.TestCase):
    def test_nested_quote_identity_rejected(self):
        with self.assertRaises(BindingValueError):assert_no_quote_identity_in_model_payload({"features":{"nested":{"book_key":"dk"}}})
    def test_clean_model_payload_allowed(self):
        assert_no_quote_identity_in_model_payload({"features":{"xwoba":.321,"wind_mph":8.0}})

if __name__=="__main__":unittest.main()
