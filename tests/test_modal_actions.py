"""Full mounted keyboard regressions at the declared Textual minimum.

Temporary storage, disabled LLMs and blocked sockets keep this local-only.
Search assertions check dispatch/filter state, not root filtering semantics.
"""
import os
import socket
import tempfile
import unittest
from unittest.mock import patch

from dendrite.app import DendriteApp, CONFIG, InputModal, ContextModal, SearchModal
from dendrite.widgets import IdeaTreeWidget, FilterMode
from dendrite.models import NodeState
from dendrite.storage import Storage
from pathlib import Path
from textual.widgets import Input


class ModalActions(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.home = tempfile.TemporaryDirectory(prefix="dendrite-keyboard-")
        self.addCleanup(self.home.cleanup)
        self.env = patch.dict(os.environ, {"HOME": self.home.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.llm = patch.object(CONFIG, "llm_enabled", False)
        self.llm.start()
        self.addCleanup(self.llm.stop)
        self.storage = patch.object(Storage, "DEFAULT_DIR", Path(self.home.name) / ".dendrite")
        self.storage.start()
        self.addCleanup(self.storage.stop)
        self.network = []
        def block(*args, **kwargs):
            self.network.append(1)
            raise AssertionError("Network prohibited in modal regression")
        self.sockets = patch.object(socket, "create_connection", block)
        self.sockets.start()
        self.addCleanup(self.sockets.stop)
        self.connect = patch.object(socket.socket, "connect", block)
        self.connect.start()
        self.addCleanup(self.connect.stop)

    async def test_keyboard_modal_lifecycle(self):
        app=DendriteApp();rows=[]
        async with app.run_test(size=(120,40)) as p:
         await p.pause()
         async def press(*keys):
          await p.press(*keys);await p.pause()
         async def text(value):
          app.screen.query_one(Input).value=value;await press('enter')
         async def screen(cls):assert isinstance(app.screen,cls),type(app.screen)
         async def select(nid):
          w=app.query_one('#idea-tree',IdeaTreeWidget)
          def walk(n):
           yield n
           for c in n.children:yield from walk(c)
          for n in walk(w.root):
           if n.data==nid:w.select_node(n);await p.pause();return
          raise AssertionError('Node not visible')
         start=len(app.active_tree.nodes)
         await press('/');await screen(SearchModal);await press('escape');assert not isinstance(app.screen,SearchModal);rows.append('search cancel')
         await press('/');await screen(SearchModal);await text('test');w=app.query_one('#idea-tree',IdeaTreeWidget);assert w.filter_mode==FilterMode.SEARCH;rows.append('search accept dispatch')
         await press('0');assert w.filter_mode==FilterMode.ALL
         await press('n');await screen(InputModal);await press('escape');assert len(app.active_tree.nodes)==start;rows.append('seed cancel')
         await press('n');await screen(InputModal);await text('Owner modal seed');await screen(ContextModal)
         await text('Owner seed context');assert len(app.active_tree.nodes)==start+1
         seed=next(n for n in app.active_tree.nodes.values() if n.content=='Owner modal seed');assert seed.history[-1].context=='Owner seed context';rows.append('seed accept context')
         await select(seed.id)
         await press('b');await screen(InputModal);await press('escape');assert len(app.active_tree.nodes)==start+1;rows.append('branch cancel')
         await select(seed.id);await press('b');await screen(InputModal);await text('Owner child');await screen(ContextModal);await press('escape')
         child=next(n for n in app.active_tree.nodes.values() if n.content=='Owner child');assert child.parent_id==seed.id and child.history[-1].context=='';rows.append('branch accept skip context')
         await select(child.id);await press('e');await screen(InputModal);await press('escape');assert child.content=='Owner child';rows.append('edit cancel')
         await select(child.id);await press('e');await screen(InputModal);await text('Owner child edited');await screen(ContextModal);await text('Owner edit context');assert child.content=='Owner child edited' and child.history[-1].context=='Owner edit context';rows.append('edit accept context')
         for key,state in [('g',NodeState.GROWING),('p',NodeState.PRUNED),('d',NodeState.DORMANT)]:
          await select(seed.id);await press(key);await screen(ContextModal);await text('Owner state '+key);assert seed.state==state and seed.history[-1].context=='Owner state '+key;rows.append('state '+key)
         await press('n');await text('Owner skip seed');await screen(ContextModal);await press('escape');assert len(app.active_tree.nodes)==start+3;rows.append('seed context skip')
         before=app.query_one('#timeline-container').display;await press('t');assert app.query_one('#timeline-container').display!=before;rows.append('post-modal keyboard responsive')
        self.assertEqual(self.network,[])
        self.assertEqual(len(rows),13)
