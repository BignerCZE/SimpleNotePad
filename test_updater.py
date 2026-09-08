import unittest
from updater import version_tuple

class VersionTests(unittest.TestCase):
    def test_versions(self):
        self.assertEqual(version_tuple("v2.0.1"), (2, 0, 1))
        self.assertGreater(version_tuple("2.1.0"), version_tuple("2.0.9"))
        self.assertEqual(version_tuple("v3.4"), (3, 4, 0))

if __name__ == "__main__":
    unittest.main()
