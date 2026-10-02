"""Dendrite - A TUI for growing ideas through time."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Static, Label, Button, Select
from textual.css.query import NoMatches

from .models import Forest, Tree, Node, NodeState
from .storage import Storage
from .widgets import (
    IdeaTreeWidget,
    TimelineWidget,
    NodeDetailWidget,
    ContextInputWidget,
    StatsBar,
    LLMResponseWidget,
    FilterMode,
)


# =============================================================================
# CONFIGURATION
# =============================================================================

class DendriteConfig:
    """Application configuration."""

    def __init__(self):
        # LLM Configuration - CHANGE THESE TO SWITCH PROVIDERS
        self.llm_provider: str = "anthropic"  # anthropic, openai, openrouter, xai, vultr
        self.llm_model: Optional[str] = None  # None = use provider default
        self.llm_enabled: bool = True

        # Storage
        self.auto_save: bool = True
        self.save_file: str = "forest.json"

        # UI
        self.show_timeline: bool = True
        self.show_stats: bool = True


CONFIG = DendriteConfig()


# =============================================================================
# MODALS
# =============================================================================

class InputModal(ModalScreen[str]):
    """A modal for text input."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    InputModal {
        align: center middle;
    }

    InputModal > Container {
        width: 70;
        height: auto;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }

    InputModal Input {
        width: 100%;
        margin: 1 0;
    }

    InputModal .title {
        text-align: center;
        text-style: bold;
        color: $accent;
        padding: 1;
    }

    InputModal .hint {
        text-align: center;
        color: $text-muted;
        text-style: italic;
    }
    """

    def __init__(self, title: str, placeholder: str = "", hint: str = "", default: str = ""):
        super().__init__()
        self.title_text = title
        self.placeholder = placeholder
        self.hint_text = hint
        self.default = default

    def compose(self) -> ComposeResult:
        with Container():
            yield Label(self.title_text, classes="title")
            yield Input(placeholder=self.placeholder, value=self.default)
            if self.hint_text:
                yield Label(self.hint_text, classes="hint")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.value.strip():
            self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        self.dismiss("")


class ContextModal(ModalScreen[str]):
    """A modal for adding context to an action."""

    BINDINGS = [
        Binding("escape", "skip", "Skip"),
    ]

    CSS = """
    ContextModal {
        align: center middle;
    }

    ContextModal > Container {
        width: 70;
        height: auto;
        border: thick $warning;
        background: $surface;
        padding: 1 2;
    }

    ContextModal Input {
        width: 100%;
        margin: 1 0;
    }

    ContextModal .title {
        text-align: center;
        text-style: bold;
        color: $warning;
        padding: 1;
    }

    ContextModal .subtitle {
        text-align: center;
        color: $text-muted;
        text-style: italic;
        padding-bottom: 1;
    }
    """

    def __init__(self, action: str):
        super().__init__()
        self.action = action

    def compose(self) -> ComposeResult:
        with Container():
            yield Label("What's the context?", classes="title")
            yield Label(f"Why are you {self.action}? What triggered this thought?", classes="subtitle")
            yield Input(placeholder="Optional: capture the moment...")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def action_skip(self) -> None:
        self.dismiss("")


class SearchModal(ModalScreen[str]):
    """Modal for searching/filtering the tree."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    SearchModal {
        align: center middle;
    }

    SearchModal > Container {
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    SearchModal Input {
        width: 100%;
        margin: 1 0;
    }

    SearchModal .title {
        text-align: center;
        text-style: bold;
        color: $primary;
        padding: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Container():
            yield Label("🔍 Search Ideas", classes="title")
            yield Input(placeholder="Type to search...")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        self.dismiss("")


class AIResponseModal(ModalScreen[list[str]]):
    """Modal for displaying AI responses and selecting branches."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("1", "select_1", "Select 1", show=False),
        Binding("2", "select_2", "Select 2", show=False),
        Binding("3", "select_3", "Select 3", show=False),
    ]

    CSS = """
    AIResponseModal {
        align: center middle;
    }

    AIResponseModal > Container {
        width: 80;
        height: auto;
        max-height: 80%;
        border: thick $secondary;
        background: $surface;
        padding: 1 2;
    }

    AIResponseModal .title {
        text-align: center;
        text-style: bold;
        color: $secondary;
        padding: 1;
    }

    AIResponseModal .response {
        padding: 1;
        margin: 1 0;
        background: $surface-darken-1;
    }

    AIResponseModal .hint {
        text-align: center;
        color: $text-muted;
        text-style: italic;
        padding: 1;
    }

    AIResponseModal Button {
        margin: 0 1;
    }
    """

    def __init__(self, title: str, response: str, suggestions: list[str]):
        super().__init__()
        self.title_text = title
        self.response = response
        self.suggestions = suggestions
        self.selected: list[str] = []

    def compose(self) -> ComposeResult:
        with Container():
            yield Label(self.title_text, classes="title")
            yield Static(self.response, classes="response")
            yield Label("Press 1-3 to select suggestions, Enter to confirm, Esc to cancel", classes="hint")
            with Horizontal():
                for i, suggestion in enumerate(self.suggestions[:3], 1):
                    yield Button(f"[{i}] {suggestion[:30]}...", id=f"btn_{i}")

    def action_cancel(self) -> None:
        self.dismiss([])

    def action_select_1(self) -> None:
        if len(self.suggestions) >= 1:
            self._toggle_selection(0)

    def action_select_2(self) -> None:
        if len(self.suggestions) >= 2:
            self._toggle_selection(1)

    def action_select_3(self) -> None:
        if len(self.suggestions) >= 3:
            self._toggle_selection(2)

    def _toggle_selection(self, idx: int) -> None:
        suggestion = self.suggestions[idx]
        if suggestion in self.selected:
            self.selected.remove(suggestion)
        else:
            self.selected.append(suggestion)
        # Visual feedback would go here

    def on_button_pressed(self, event: Button.Pressed) -> None:
        idx = int(event.button.id.split("_")[1]) - 1
        self.selected = [self.suggestions[idx]]
        self.dismiss(self.selected)


# =============================================================================
# MAIN APPLICATION
# =============================================================================

class DendriteApp(App):
    """The main Dendrite application."""

    TITLE = "Dendrite"
    SUB_TITLE = "Grow your ideas through time"

    CSS = """
    Screen {
        background: $surface;
    }

    #main-container {
        width: 100%;
        height: 100%;
    }

    #left-panel {
        width: 50%;
        height: 100%;
        border-right: solid $primary;
    }

    #right-panel {
        width: 50%;
        height: 100%;
    }

    #tree-container {
        height: 1fr;
        border-bottom: solid $primary-darken-2;
    }

    #stats-bar {
        height: 3;
        padding: 0 1;
        background: $primary-darken-3;
    }

    #timeline-container {
        height: 35%;
        padding: 1;
    }

    #detail-container {
        height: 50%;
        padding: 1;
        border-bottom: solid $primary-darken-2;
    }

    #ai-container {
        height: 30%;
        padding: 1;
        border-bottom: solid $primary-darken-2;
    }

    #context-container {
        height: 20%;
        padding: 1;
    }

    IdeaTreeWidget {
        padding: 1;
        scrollbar-gutter: stable;
    }

    TimelineWidget {
        height: 100%;
        overflow-y: auto;
    }

    NodeDetailWidget {
        height: 100%;
        overflow-y: auto;
    }

    LLMResponseWidget {
        height: 100%;
        overflow-y: auto;
    }

    ContextInputWidget {
        height: 100%;
        content-align: center middle;
    }

    .panel-title {
        dock: top;
        padding: 0 1;
        background: $primary-darken-2;
        color: $text;
        text-style: bold;
    }

    .hidden {
        display: none;
    }
    """

    BINDINGS = [
        # Core actions
        Binding("q", "quit", "Quit"),
        Binding("n", "new_seed", "New Seed"),
        Binding("b", "branch", "Branch"),
        Binding("e", "edit", "Edit"),

        # State changes
        Binding("g", "grow", "Grow"),
        Binding("p", "prune", "Prune"),
        Binding("d", "dormant", "Dormant"),

        # AI features
        Binding("a", "ai_grow", "AI Grow"),
        Binding("ctrl+a", "ai_question", "AI Question"),

        # Navigation & filtering
        Binding("/", "search", "Search"),
        Binding("f", "cycle_filter", "Filter"),
        Binding("0", "filter_all", "All", show=False),

        # Persistence
        Binding("ctrl+s", "save", "Save"),
        Binding("ctrl+o", "load", "Load"),
        Binding("ctrl+e", "export", "Export"),

        # View toggles
        Binding("t", "toggle_timeline", "Timeline"),
        Binding("?", "help", "Help"),
    ]

    def __init__(self):
        super().__init__()
        self.storage = Storage()
        self.forest: Forest | None = None
        self.active_tree: Tree | None = None
        self.config = CONFIG
        self._llm_provider = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-container"):
            with Vertical(id="left-panel"):
                with Container(id="tree-container"):
                    yield Label("🌳 Ideas", classes="panel-title")
                    yield IdeaTreeWidget(id="idea-tree")
                yield StatsBar(id="stats-bar")
                with Container(id="timeline-container"):
                    yield Label("⏱ Timeline", classes="panel-title")
                    yield TimelineWidget(id="timeline")
            with Vertical(id="right-panel"):
                with Container(id="detail-container"):
                    yield Label("📋 Details", classes="panel-title")
                    yield NodeDetailWidget(id="node-detail")
                with Container(id="ai-container"):
                    yield Label("🤖 AI Assistant", classes="panel-title")
                    yield LLMResponseWidget(id="ai-response")
                with Container(id="context-container"):
                    yield Label("💡 Context", classes="panel-title")
                    yield ContextInputWidget(id="context-hint")
        yield Footer()

    def on_mount(self) -> None:
        """Initialize the app state after mounting."""
        # Try to load saved forest, or create new one
        self.forest = self.storage.load()
        if not self.forest:
            self.forest = Forest()
            self.active_tree = self.forest.create_tree("My Ideas")
            self._seed_demo_data()
        else:
            self.active_tree = self.forest.active_tree
            if not self.active_tree and self.forest.trees:
                self.active_tree = list(self.forest.trees.values())[0]

        if self.active_tree:
            tree_widget = self.query_one("#idea-tree", IdeaTreeWidget)
            tree_widget.set_tree(self.active_tree)
            tree_widget.root.expand_all()

        self._update_timeline()
        self._update_stats()
        self._update_context_hint("Navigate with arrows. Press 'n' for new seed, 'b' to branch, 'a' for AI.")

    def _seed_demo_data(self) -> None:
        """Add some initial demo ideas to explore."""
        if not self.active_tree:
            return

        root = self.active_tree.add_node(
            "TUI Framework Ideas",
            context="Starting to think about terminal interfaces"
        )
        root.set_state(NodeState.GROWING)

        child1 = self.active_tree.branch(
            root.id,
            "Tree-based navigation",
            context="Everything is a tree - files, ideas, time"
        )
        child1.set_state(NodeState.SPROUTING)

        self.active_tree.branch(
            child1.id,
            "Collapsible branches like lazygit",
            context="Users love the lazygit UX"
        )

        self.active_tree.branch(
            child1.id,
            "Keyboard-driven with vim bindings",
            context="Our users live in the terminal"
        )

        child2 = self.active_tree.branch(
            root.id,
            "Temporal awareness",
            context="Time is a first-class concept"
        )
        child2.set_state(NodeState.SPROUTING)

        self.active_tree.branch(
            child2.id,
            "Show history as a timeline",
            context="Every change should be visible"
        )

        child3 = self.active_tree.branch(
            root.id,
            "Context capture",
            context="Why did I think this? I always forget"
        )

        self.active_tree.branch(
            child3.id,
            "Prompt for context on each action",
            context="Make it optional but encouraged"
        )

    # -------------------------------------------------------------------------
    # Event Handlers
    # -------------------------------------------------------------------------

    def on_tree_node_selected(self, event: IdeaTreeWidget.NodeSelected) -> None:
        """Handle node selection in the tree."""
        if not self.active_tree:
            return

        if event.node.data:
            node_id = event.node.data
            node = self.active_tree.get_node(node_id)
            if node:
                path = self.active_tree.get_path_to_root(node_id)
                self.query_one("#node-detail", NodeDetailWidget).set_node(node, path)
                self._update_context_hint(f"Selected: {node.content[:30]}… | 'b' branch, 'e' edit, 'a' AI grow")
        else:
            self.query_one("#node-detail", NodeDetailWidget).set_node(None)

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _update_timeline(self) -> None:
        """Update the timeline widget with current tree history."""
        if self.active_tree:
            timeline = self.active_tree.get_timeline()
            self.query_one("#timeline", TimelineWidget).set_timeline(timeline)

    def _update_stats(self) -> None:
        """Update the stats bar."""
        tree_widget = self.query_one("#idea-tree", IdeaTreeWidget)
        stats = tree_widget.get_stats()
        self.query_one("#stats-bar", StatsBar).set_stats(stats)

    def _update_context_hint(self, hint: str, mode: str = "normal") -> None:
        """Update the context hint at the bottom."""
        self.query_one("#context-hint", ContextInputWidget).set_hint(hint, mode)

    def _auto_save(self) -> None:
        """Auto-save if enabled."""
        if self.config.auto_save and self.forest:
            self.storage.save(self.forest)

    def _get_selected_node(self) -> tuple[Node | None, str | None]:
        """Get the currently selected node and its ID."""
        if not self.active_tree:
            return None, None

        tree_widget = self.query_one("#idea-tree", IdeaTreeWidget)
        selected = tree_widget.cursor_node

        if selected and selected.data:
            node = self.active_tree.get_node(selected.data)
            return node, selected.data
        return None, None

    # -------------------------------------------------------------------------
    # Actions - Core
    # -------------------------------------------------------------------------

    async def action_new_seed(self) -> None:
        """Plant a new seed (root-level idea)."""
        content = await self.push_screen_wait(
            InputModal("Plant a Seed", "What's the idea?", "Press Enter to plant, Escape to cancel")
        )
        if content and self.active_tree:
            context = await self.push_screen_wait(ContextModal("planting this seed"))
            self.active_tree.add_node(content, context=context)

            tree_widget = self.query_one("#idea-tree", IdeaTreeWidget)
            tree_widget.set_tree(self.active_tree)
            tree_widget.root.expand_all()
            self._update_timeline()
            self._update_stats()
            self._update_context_hint(f"Planted: {content[:30]}…", "success")
            self._auto_save()

    async def action_branch(self) -> None:
        """Create a branch from the selected node."""
        node, node_id = self._get_selected_node()
        if not node:
            self._update_context_hint("Select a node first to branch from it.", "error")
            return

        content = await self.push_screen_wait(
            InputModal("Create Branch", "Branch into what?", "A new direction from this idea")
        )
        if content and self.active_tree:
            context = await self.push_screen_wait(ContextModal("creating this branch"))
            tree_widget = self.query_one("#idea-tree", IdeaTreeWidget)
            tree_widget.add_child_to_selected(content, context)
            self._update_timeline()
            self._update_stats()
            self._update_context_hint(f"Branched: {content[:30]}…", "success")
            self._auto_save()

    async def action_edit(self) -> None:
        """Edit the selected node."""
        node, node_id = self._get_selected_node()
        if not node:
            self._update_context_hint("Select a node to edit.", "error")
            return

        content = await self.push_screen_wait(
            InputModal("Edit Node", "New content:", default=node.content)
        )
        if content and content != node.content:
            context = await self.push_screen_wait(ContextModal("making this edit"))
            node.edit(content, context)

            tree_widget = self.query_one("#idea-tree", IdeaTreeWidget)
            tree_widget.refresh_node(node.id)
            self._update_timeline()

            path = self.active_tree.get_path_to_root(node.id) if self.active_tree else []
            self.query_one("#node-detail", NodeDetailWidget).set_node(node, path)
            self._update_context_hint(f"Edited: {content[:30]}…", "success")
            self._auto_save()

    # -------------------------------------------------------------------------
    # Actions - State Changes
    # -------------------------------------------------------------------------

    async def _change_state(self, new_state: NodeState, action_verb: str) -> None:
        """Change the state of the selected node."""
        node, node_id = self._get_selected_node()
        if not node:
            self._update_context_hint(f"Select a node to {action_verb}.", "error")
            return

        context = await self.push_screen_wait(ContextModal(f"{action_verb}ing this idea"))
        node.set_state(new_state, context)

        tree_widget = self.query_one("#idea-tree", IdeaTreeWidget)
        tree_widget.refresh_node(node.id)
        self._update_timeline()
        self._update_stats()

        path = self.active_tree.get_path_to_root(node.id) if self.active_tree else []
        self.query_one("#node-detail", NodeDetailWidget).set_node(node, path)
        self._update_context_hint(f"Now {new_state.value}: {node.content[:30]}…", "success")
        self._auto_save()

    async def action_grow(self) -> None:
        """Cycle through growth states."""
        node, _ = self._get_selected_node()
        if node:
            if node.state in (NodeState.SEED, NodeState.SPROUTING):
                await self._change_state(NodeState.GROWING, "grow")
            elif node.state == NodeState.GROWING:
                await self._change_state(NodeState.MATURE, "matur")
            else:
                await self._change_state(NodeState.GROWING, "reviv")

    async def action_prune(self) -> None:
        """Mark a node as pruned."""
        await self._change_state(NodeState.PRUNED, "prun")

    async def action_dormant(self) -> None:
        """Mark a node as dormant."""
        await self._change_state(NodeState.DORMANT, "pause")

    # -------------------------------------------------------------------------
    # Actions - AI
    # -------------------------------------------------------------------------

    def _get_llm_provider(self):
        """Get or create the LLM provider."""
        if self._llm_provider is None:
            try:
                from .llm import get_provider, LLMConfig
                config = LLMConfig(
                    provider_name=self.config.llm_provider,
                    model=self.config.llm_model,
                )
                self._llm_provider = get_provider(config)
            except Exception as e:
                self._update_context_hint(f"LLM error: {e}", "error")
                return None
        return self._llm_provider

    async def action_ai_grow(self) -> None:
        """Use AI to suggest ways to grow the selected idea."""
        node, node_id = self._get_selected_node()
        if not node or not self.active_tree:
            self._update_context_hint("Select a node for AI to help grow.", "error")
            return

        provider = self._get_llm_provider()
        if not provider:
            self._update_context_hint(
                f"Set {self.config.llm_provider.upper()}_API_KEY environment variable",
                "error"
            )
            return

        self._update_context_hint("AI is thinking…", "thinking")

        # Get context
        path = self.active_tree.get_path_to_root(node_id)
        path_contents = [n.content for n in path]

        ai_widget = self.query_one("#ai-response", LLMResponseWidget)
        ai_widget.start_stream("Growing your idea…")

        try:
            from .llm.base import make_grow_prompt

            messages = make_grow_prompt(node.content, path_contents)

            full_response = ""
            async for chunk in provider.stream(messages):
                full_response += chunk.content
                ai_widget.append_chunk(chunk.content)

            ai_widget.finish_stream()
            self._update_context_hint("AI suggestions ready. Press 'b' to branch any you like.", "ai")

        except Exception as e:
            ai_widget.finish_stream()
            self._update_context_hint(f"AI error: {e}", "error")

    async def action_ai_question(self) -> None:
        """Use AI to question/challenge the selected idea."""
        node, node_id = self._get_selected_node()
        if not node or not self.active_tree:
            self._update_context_hint("Select a node for AI to question.", "error")
            return

        provider = self._get_llm_provider()
        if not provider:
            return

        self._update_context_hint("AI is analyzing…", "thinking")

        history_summary = ", ".join([m.action for m in node.history[-5:]])

        ai_widget = self.query_one("#ai-response", LLMResponseWidget)
        ai_widget.start_stream("Questioning your idea…")

        try:
            from .llm.base import make_question_prompt

            messages = make_question_prompt(node.content, history_summary)

            async for chunk in provider.stream(messages):
                ai_widget.append_chunk(chunk.content)

            ai_widget.finish_stream()
            self._update_context_hint("AI critique ready.", "ai")

        except Exception as e:
            ai_widget.finish_stream()
            self._update_context_hint(f"AI error: {e}", "error")

    # -------------------------------------------------------------------------
    # Actions - Filtering
    # -------------------------------------------------------------------------

    async def action_search(self) -> None:
        """Open search modal."""
        query = await self.push_screen_wait(SearchModal())
        if query:
            tree_widget = self.query_one("#idea-tree", IdeaTreeWidget)
            tree_widget.set_filter(FilterMode.SEARCH, query)
            self._update_context_hint(f"Showing results for: {query} | Press '0' to clear", "normal")

    def action_filter_all(self) -> None:
        """Clear all filters."""
        tree_widget = self.query_one("#idea-tree", IdeaTreeWidget)
        tree_widget.set_filter(FilterMode.ALL)
        self._update_context_hint("Showing all ideas", "normal")

    def action_cycle_filter(self) -> None:
        """Cycle through filter modes."""
        tree_widget = self.query_one("#idea-tree", IdeaTreeWidget)
        modes = [FilterMode.ALL, FilterMode.ACTIVE, FilterMode.SEEDS, FilterMode.GROWING, FilterMode.MATURE]
        current_idx = modes.index(tree_widget.filter_mode) if tree_widget.filter_mode in modes else 0
        next_mode = modes[(current_idx + 1) % len(modes)]
        tree_widget.set_filter(next_mode)
        self._update_context_hint(f"Filter: {next_mode.value}", "normal")

    # -------------------------------------------------------------------------
    # Actions - Persistence
    # -------------------------------------------------------------------------

    def action_save(self) -> None:
        """Save the forest to disk."""
        if self.forest:
            path = self.storage.save(self.forest)
            self._update_context_hint(f"Saved to {path}", "success")

    async def action_load(self) -> None:
        """Load a forest from disk."""
        saves = self.storage.list_saves()
        if not saves:
            self._update_context_hint("No saved forests found", "error")
            return

        # For now, just load the default
        loaded = self.storage.load()
        if loaded:
            self.forest = loaded
            self.active_tree = self.forest.active_tree
            if self.active_tree:
                tree_widget = self.query_one("#idea-tree", IdeaTreeWidget)
                tree_widget.set_tree(self.active_tree)
                tree_widget.root.expand_all()
            self._update_timeline()
            self._update_stats()
            self._update_context_hint("Forest loaded", "success")

    def action_export(self) -> None:
        """Export forest to markdown."""
        if self.forest:
            path = self.storage.export_markdown(self.forest)
            self._update_context_hint(f"Exported to {path}", "success")

    # -------------------------------------------------------------------------
    # Actions - View
    # -------------------------------------------------------------------------

    def action_toggle_timeline(self) -> None:
        """Toggle timeline visibility."""
        try:
            timeline_container = self.query_one("#timeline-container")
            timeline_container.display = not timeline_container.display
        except NoMatches:
            pass

    def action_help(self) -> None:
        """Show help."""
        self._update_context_hint(
            "n:seed b:branch e:edit g:grow p:prune d:dormant a:AI /:search f:filter ^s:save q:quit"
        )


def main():
    """Entry point for the application."""
    app = DendriteApp()
    app.run()


if __name__ == "__main__":
    main()
