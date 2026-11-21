"""Synthetic, local-only regressions for saved typed forests and shipped saves."""
import json
import socket
import tempfile
import unittest
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from dendrite.models import Forest, Tree, Node, Moment, NodeState
from dendrite.storage import DendriteEncoder, Storage


class ShippedEncoder(json.JSONEncoder):
    """Original serialization algorithm, frozen to exercise existing files."""
    def default(self, value):
        if isinstance(value, datetime):
            return {"__datetime__": value.isoformat()}
        if isinstance(value, NodeState):
            return {"__nodestate__": value.value}
        if isinstance(value, (Forest, Tree, Node, Moment)):
            return {"__class__": type(value).__name__, **asdict(value)}
        return super().default(value)


def forest_fixture():
    forest = Forest()
    tree = forest.create_tree('Contexts and branches')
    root = tree.add_node('Original root', context='Initial context')
    root.tags = ['tag', 'unicode:🌱']
    root.created_at = datetime(2026, 11, 20, 12, 30, tzinfo=timezone.utc)
    root.edit('Edited root', context='Editing reason')
    for state in NodeState:
        node = tree.branch(root.id, 'Branch ' + state.value, context='Branch reason')
        node.set_state(state, context='State reason')
        tree.branch(node.id, 'Grandchild', context='Nested context')
    tree.add_node('Second root')
    tree.created_at = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    other = forest.create_tree('Other tree')
    other.add_node('Other root')
    forest.active_tree_id = other.id
    return forest


class StorageRoundtrip(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.storage = Storage(Path(self.temp.name))

    def test_nested_new_roundtrip_preserves_all_fields(self):
        original = forest_fixture()
        path = self.storage.save(original)
        raw = json.loads(path.read_text())
        tree_raw = next(iter(raw['trees'].values()))
        self.assertEqual(tree_raw['__class__'], 'Tree')
        restored = self.storage.load()
        self.assertEqual(restored, original)
        self.assertIsInstance(restored.active_tree, Tree)
        self.assertEqual(restored.get_global_timeline(1000), original.get_global_timeline(1000))
        self.assertEqual(len(restored.get_global_timeline(1000)), 22)
        export = self.storage.export_markdown(restored).read_text()
        self.assertIn('Edited root', export)
        self.assertIn('Nested context', export)
        self.assertIn('Branch pruned~~', export)

    def test_original_untagged_format_then_edit_resave(self):
        original = forest_fixture()
        path = self.storage._get_path()
        path.write_text(json.dumps(original, cls=ShippedEncoder))
        self.assertNotIn('__class__', next(iter(json.loads(path.read_text())['trees'].values())))
        restored = self.storage.load()
        self.assertEqual(restored, original)
        self.assertIsInstance(restored.active_tree, Tree)
        node = next(iter(restored.active_tree.nodes.values()))
        node.edit('Edited after legacy reopen', context='New preserved context')
        self.storage.save(restored)
        self.assertEqual(self.storage.load(), restored)
        self.assertIn('New preserved context', self.storage.export_markdown(restored).read_text())

    def test_captured_shipped_app_save_preserves_values(self):
        captured = Path(__file__).parent / 'fixtures/shipped-demo-forest.json'
        self.storage._get_path().write_bytes(captured.read_bytes())
        restored = self.storage.load()
        self.assertIsInstance(restored.active_tree, Tree)
        self.assertTrue(restored.get_global_timeline())
        for tree in restored.trees.values():
            for node in tree.nodes.values():
                self.assertIsInstance(node, Node)
                self.assertTrue(all(isinstance(moment, Moment) for moment in node.history))
        def without_tags(value):
            if isinstance(value, dict):
                return {key: without_tags(item) for key, item in value.items()
                        if key != '__class__'}
            if isinstance(value, list):
                return [without_tags(item) for item in value]
            return value
        normalized_before = without_tags(json.loads(captured.read_text()))
        self.storage.save(restored)
        normalized_after = without_tags(json.loads(self.storage._get_path().read_text()))
        self.assertEqual(normalized_after, normalized_before)
        self.assertEqual(self.storage.load(), restored)
        self.assertTrue(self.storage.export_markdown(restored).exists())

    def test_empty_and_missing(self):
        self.assertIsNone(self.storage.load())
        self.storage.save(Forest())
        self.assertEqual(self.storage.load(), Forest())
        forest = Forest()
        forest.create_tree('Empty tree')
        self.storage.save(forest)
        self.assertEqual(self.storage.load(), forest)

    def test_malformed_legacy_does_not_silently_drop_fields_or_rewrite(self):
        forest = forest_fixture()
        original = json.loads(json.dumps(forest, cls=ShippedEncoder))
        for mutation in ['unknown', 'history', 'content', 'timestamp', 'tags', 'trees', 'missing_state']:
            with self.subTest(mutation=mutation):
                data = json.loads(json.dumps(original))
                tree = next(iter(data['trees'].values()))
                node = next(iter(tree['nodes'].values()))
                if mutation == 'unknown':
                    node['future_field'] = 'must not be silently discarded'
                elif mutation == 'history':
                    node['history'] = ['invalid']
                elif mutation == 'content':
                    node['content'] = 42
                elif mutation == 'timestamp':
                    node['created_at'] = 'not a typed timestamp'
                elif mutation == 'tags':
                    node['tags'] = [42]
                elif mutation == 'missing_state':
                    del node['state']
                else:
                    data['trees'] = []
                path = self.storage._get_path()
                before = json.dumps(data)
                path.write_text(before)
                with self.assertRaises(ValueError):
                    self.storage.load()
                self.assertEqual(path.read_text(), before)


class ActualAppReopen(unittest.IsolatedAsyncioTestCase):
    async def test_actual_first_app_save_second_app_reopen(self):
        from dendrite.app import DendriteApp, CONFIG
        with tempfile.TemporaryDirectory() as temp, patch.object(Storage, 'DEFAULT_DIR', Path(temp)), patch.object(CONFIG, 'llm_enabled', False), patch.object(socket, 'create_connection', side_effect=AssertionError('No network')) as network:
            first = DendriteApp()
            async with first.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                original = first.forest
                first.action_save()
            second = DendriteApp()
            async with second.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                self.assertEqual(second.forest, original)
                self.assertIsInstance(second.active_tree, Tree)
                second.action_save()
                self.assertEqual(second.storage.load(), original)
            network.assert_not_called()


if __name__ == '__main__':
    unittest.main()
