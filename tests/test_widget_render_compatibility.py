"""Exercise both Static widgets through the real Textual rendering lifecycle."""
import unittest
from textual.app import App, ComposeResult
from dendrite.widgets import ContextInputWidget, StatsBar


class HintApp(App):
    def compose(self) -> ComposeResult:
        yield ContextInputWidget(id='hint')


class StatsApp(App):
    def compose(self) -> ComposeResult:
        yield StatsBar(id='stats')


class WidgetRenderCompatibility(unittest.IsolatedAsyncioTestCase):
    async def test_hint_mount_and_all_modes(self):
        app = HintApp()
        async with app.run_test(size=(100, 20)) as pilot:
            await pilot.pause()
            hint = app.query_one('#hint', ContextInputWidget)
            self.assertIn('Welcome to Dendrite', str(hint.render()))
            for mode in ('normal', 'success', 'error', 'thinking', 'ai', 'unknown'):
                hint.set_hint('Render compatibility fixture ' + mode, mode)
                await pilot.pause()
                self.assertIn('Render compatibility fixture ' + mode, str(hint.render()))

    async def test_stats_mount_update_and_clear(self):
        app = StatsApp()
        async with app.run_test(size=(100, 20)) as pilot:
            await pilot.pause()
            stats = app.query_one('#stats', StatsBar)
            stats.set_stats({'total': 6, 'seed': 2, 'growing': 4})
            await pilot.pause()
            self.assertIn('6 ideas', str(stats.render()))
            stats.set_stats({'total': 0})
            await pilot.pause()
            self.assertIn('0 ideas', str(stats.render()))
