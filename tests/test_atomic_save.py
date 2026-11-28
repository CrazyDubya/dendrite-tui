"""A failed save must not destroy the previous saved forest."""
import json
import tempfile
import unittest
from pathlib import Path

from dendrite.models import Forest
from dendrite.storage import Storage


def make_forest(n=50):
    forest = Forest()
    tree = forest.create_tree("Ideas")
    root = tree.add_node("root")
    for i in range(n):
        tree.branch(root.id, f"idea {i}", context="ctx")
    return forest


class AtomicSave(unittest.TestCase):
    def test_failed_save_keeps_previous_file(self):
        with tempfile.TemporaryDirectory() as d:
            storage = Storage(Path(d))
            storage.save(make_forest())
            before = (Path(d) / "forest.json").read_text()
            broken = make_forest()
            # An unserializable value makes the encoder fail part-way through the dump.
            list(broken.active_tree.nodes.values())[-1].content = object()
            with self.assertRaises(TypeError):
                storage.save(broken)
            self.assertEqual((Path(d) / "forest.json").read_text(), before)
            self.assertIsNotNone(storage.load())

    def test_no_temp_files_left_after_success_or_failure(self):
        with tempfile.TemporaryDirectory() as d:
            storage = Storage(Path(d))
            storage.save(make_forest())
            broken = make_forest()
            list(broken.active_tree.nodes.values())[-1].content = object()
            with self.assertRaises(TypeError):
                storage.save(broken)
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ["forest.json"])

    def test_save_roundtrip_and_named_file(self):
        with tempfile.TemporaryDirectory() as d:
            storage = Storage(Path(d))
            path = storage.save(make_forest(3), "other.json")
            self.assertEqual(path.name, "other.json")
            json.loads(path.read_text())
            self.assertEqual(len(storage.load("other.json").trees), 1)
            self.assertEqual([n for n, _ in storage.list_saves()], ["other.json"])


if __name__ == "__main__":
    unittest.main()
