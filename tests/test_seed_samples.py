"""표본 채우기(scripts/seed_samples.py)가 폴더 규칙서(README.md)를 표본으로 복사하지 않는지 본다. 실행: python -m unittest tests.test_seed_samples"""

import os
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import seed_samples  # noqa: E402


class ReadmeIsNotASample(unittest.TestCase):
    def test_the_folder_readme_at_the_sample_root_is_skipped(self):
        with tempfile.TemporaryDirectory(prefix="hazop-seed-") as tmp:
            samples, work = os.path.join(tmp, "samples"), os.path.join(tmp, "work")
            os.makedirs(os.path.join(samples, "regions"))
            for rel in ("README.md", "regions/region-a.json", "regions/README.md"):
                with open(os.path.join(samples, *rel.split("/")), "w", encoding="utf-8") as f:
                    f.write("x")
            with mock.patch.object(seed_samples, "SAMPLE_ROOT", samples):
                rels = [rel for rel, _state in seed_samples.plan(work)]
        self.assertEqual(["regions/README.md", "regions/region-a.json"], rels)

    def test_the_real_sample_root_has_no_readme_to_copy(self):
        self.assertNotIn("README.md", [rel for rel, _state in seed_samples.plan(os.path.join(tempfile.gettempdir(), "hazop-seed-none"))])


if __name__ == "__main__":
    unittest.main()
