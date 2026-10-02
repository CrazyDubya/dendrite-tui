"""Custom widgets for Dendrite TUI."""
from __future__ import annotations

from enum import Enum
from typing import Callable

from rich.text import Text
from rich.console import RenderableType
from textual.widgets import Static, Tree as TextualTree, Input
from textual.widgets.tree import TreeNode
from textual.reactive import reactive
from textual.message import Message as TextualMessage

from .models import Node, Tree, NodeState


class FilterMode(Enum):
    """Filter modes for tree view."""
    ALL = "all"
    SEEDS = "seeds"
    GROWING = "growing"
    MATURE = "mature"
    ACTIVE = "active"  # Not dormant or pruned
    SEARCH = "search"


class IdeaTreeWidget(TextualTree):
    """A visual tree of ideas with state indicators and filtering."""

    # Color scheme for different states
    STATE_COLORS = {
        NodeState.SEED: "#88C0D0",      # Nord frost blue
        NodeState.SPROUTING: "#A3BE8C",  # Nord green
        NodeState.GROWING: "#EBCB8B",    # Nord yellow
        NodeState.MATURE: "#BF616A",     # Nord red (mature = important)
        NodeState.DORMANT: "#4C566A",    # Nord dark gray
        NodeState.PRUNED: "#3B4252",     # Nord darker gray
    }

    filter_mode: reactive[FilterMode] = reactive(FilterMode.ALL)
    search_query: reactive[str] = reactive("")

    def __init__(self, tree: Tree | None = None, **kwargs):
        super().__init__("Ideas", **kwargs)
        self.idea_tree = tree
        self._node_map: dict[str, TreeNode] = {}
        self._all_node_ids: set[str] = set()

    def set_tree(self, tree: Tree) -> None:
        """Set or replace the tree being displayed."""
        self.idea_tree = tree
        self._rebuild_tree()

    def _rebuild_tree(self) -> None:
        """Rebuild the visual tree from the data tree."""
        if not self.idea_tree:
            return

        self.clear()
        self.root.label = Text(self.idea_tree.name, style="bold cyan")
        self._node_map.clear()
        self._all_node_ids.clear()

        # Collect all node IDs first
        for node in self.idea_tree.nodes.values():
            self._all_node_ids.add(node.id)

        # Build the visual tree from roots
        for root_id in self.idea_tree.root_ids:
            root_node = self.idea_tree.get_node(root_id)
            if root_node and self._should_show_node(root_node):
                self._add_node_recursive(root_node, self.root)

        self.root.expand()

    def _should_show_node(self, node: Node) -> bool:
        """Check if a node should be shown based on current filter."""
        if self.filter_mode == FilterMode.ALL:
            return True
        elif self.filter_mode == FilterMode.SEEDS:
            return node.state == NodeState.SEED
        elif self.filter_mode == FilterMode.GROWING:
            return node.state in (NodeState.SPROUTING, NodeState.GROWING)
        elif self.filter_mode == FilterMode.MATURE:
            return node.state == NodeState.MATURE
        elif self.filter_mode == FilterMode.ACTIVE:
            return node.state not in (NodeState.DORMANT, NodeState.PRUNED)
        elif self.filter_mode == FilterMode.SEARCH:
            return self.search_query.lower() in node.content.lower()
        return True

    def _has_visible_children(self, node: Node) -> bool:
        """Check if any children would be visible with current filter."""
        if not self.idea_tree:
            return False
        for child in self.idea_tree.get_children(node.id):
            if self._should_show_node(child) or self._has_visible_children(child):
                return True
        return False

    def _add_node_recursive(self, node: Node, parent: TreeNode) -> None:
        """Recursively add nodes to the visual tree."""
        # Show node if it matches filter OR has visible children
        show_self = self._should_show_node(node)
        has_visible_kids = self._has_visible_children(node)

        if not show_self and not has_visible_kids:
            return

        label = self._format_node_label(node, dimmed=not show_self)
        tree_node = parent.add(label, data=node.id)
        self._node_map[node.id] = tree_node

        if self.idea_tree:
            for child in self.idea_tree.get_children(node.id):
                self._add_node_recursive(child, tree_node)

    def _format_node_label(self, node: Node, dimmed: bool = False) -> Text:
        """Format a node's label with icon, styling, and color."""
        text = Text()

        # State icon with color
        color = self.STATE_COLORS.get(node.state, "white")
        if dimmed:
            color = "#4C566A"

        text.append(f"{node.state_icon} ", style=f"bold {color}")

        # Content (truncated if long)
        content = node.content[:45] + "…" if len(node.content) > 45 else node.content

        # Highlight search matches
        if self.filter_mode == FilterMode.SEARCH and self.search_query:
            # Simple highlighting
            lower_content = content.lower()
            lower_query = self.search_query.lower()
            if lower_query in lower_content:
                idx = lower_content.find(lower_query)
                before = content[:idx]
                match = content[idx:idx + len(self.search_query)]
                after = content[idx + len(self.search_query):]
                text.append(before, style=color if not dimmed else "dim")
                text.append(match, style="bold reverse yellow")
                text.append(after, style=color if not dimmed else "dim")
            else:
                text.append(content, style="dim" if dimmed else color)
        else:
            # Style based on state
            style = color if not dimmed else "dim"
            if node.state == NodeState.MATURE:
                style = f"bold {color}"
            elif node.state == NodeState.PRUNED:
                style = f"strike {color}"
            text.append(content, style=style)

        # Child count indicator
        if self.idea_tree:
            children = self.idea_tree.get_children(node.id)
            if children:
                text.append(f" [{len(children)}]", style="dim cyan")

        # Age indicator
        text.append(f"  {node.age_display}", style="dim")

        return text

    def watch_filter_mode(self, new_mode: FilterMode) -> None:
        """React to filter mode changes."""
        self._rebuild_tree()

    def watch_search_query(self, new_query: str) -> None:
        """React to search query changes."""
        if self.filter_mode == FilterMode.SEARCH:
            self._rebuild_tree()

    def set_filter(self, mode: FilterMode, query: str = "") -> None:
        """Set the filter mode and optional search query."""
        self.search_query = query
        self.filter_mode = mode

    def refresh_node(self, node_id: str) -> None:
        """Refresh the display of a specific node."""
        if node_id in self._node_map and self.idea_tree:
            node = self.idea_tree.get_node(node_id)
            if node:
                self._node_map[node_id].label = self._format_node_label(node)

    def add_child_to_selected(self, content: str, context: str = "") -> str | None:
        """Add a child node to the currently selected node."""
        if not self.idea_tree:
            return None

        selected = self.cursor_node
        if selected and selected.data:
            parent_id = selected.data
            new_node = self.idea_tree.branch(parent_id, content, context)
            label = self._format_node_label(new_node)
            new_tree_node = selected.add(label, data=new_node.id)
            self._node_map[new_node.id] = new_tree_node
            self._all_node_ids.add(new_node.id)
            selected.expand()
            return new_node.id
        elif selected == self.root:
            # Adding to root
            new_node = self.idea_tree.add_node(content, context=context)
            label = self._format_node_label(new_node)
            new_tree_node = self.root.add(label, data=new_node.id)
            self._node_map[new_node.id] = new_tree_node
            self._all_node_ids.add(new_node.id)
            return new_node.id
        return None

    def get_stats(self) -> dict[str, int]:
        """Get statistics about the tree."""
        if not self.idea_tree:
            return {}

        stats = {state.value: 0 for state in NodeState}
        stats["total"] = len(self.idea_tree.nodes)

        for node in self.idea_tree.nodes.values():
            stats[node.state.value] += 1

        return stats


class TimelineWidget(Static):
    """A widget showing the temporal history of changes."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.timeline_data: list = []

    def set_timeline(self, timeline: list) -> None:
        """Set the timeline data to display."""
        self.timeline_data = timeline
        self._render_timeline()

    def _render_timeline(self) -> None:
        """Render the timeline as rich text."""
        if not self.timeline_data:
            self.update(Text("  No history yet...", style="dim italic"))
            return

        text = Text()

        for i, (timestamp, node, moment) in enumerate(self.timeline_data[:20]):
            # Visual connector
            if i == 0:
                text.append("  ◉ ", style="bold cyan")
            else:
                text.append("  │\n  ○ ", style="dim cyan")

            # Time marker
            time_str = timestamp.strftime("%H:%M")
            date_str = timestamp.strftime("%m/%d")
            text.append(f"{date_str} {time_str}  ", style="cyan")

            # Action with icon
            action_display = {
                "created": ("✨", "green"),
                "edited": ("✏️ ", "yellow"),
                "state:growing": ("📈", "green"),
                "state:mature": ("🌲", "bold green"),
                "state:pruned": ("✂️ ", "red"),
                "state:dormant": ("💤", "dim"),
                "state:seed": ("🌱", "cyan"),
                "state:sprouting": ("🌿", "green"),
            }

            icon, style = action_display.get(moment.action, ("•", "white"))
            text.append(f"{icon} ", style=style)

            # Content preview
            preview = moment.content_snapshot[:25] + "…" if len(moment.content_snapshot) > 25 else moment.content_snapshot
            text.append(f"{preview}\n", style="white")

            # Context if present
            if moment.context:
                text.append(f"  │   └─ ", style="dim cyan")
                text.append(f"{moment.context}\n", style="dim italic")

        self.update(text)


class NodeDetailWidget(Static):
    """Shows detailed information about a selected node."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.current_node: Node | None = None

    def set_node(self, node: Node | None, path: list[Node] | None = None) -> None:
        """Display details for a node."""
        self.current_node = node
        if not node:
            self.update(Text("\n  Select a node to see details...", style="dim italic"))
            return

        text = Text()

        # Header bar with state
        state_colors = {
            NodeState.SEED: "#88C0D0",
            NodeState.SPROUTING: "#A3BE8C",
            NodeState.GROWING: "#EBCB8B",
            NodeState.MATURE: "#BF616A",
            NodeState.DORMANT: "#4C566A",
            NodeState.PRUNED: "#3B4252",
        }
        color = state_colors.get(node.state, "white")

        text.append(f"\n  {node.state_icon} ", style=f"bold {color}")
        text.append(f"{node.state.value.upper()}", style=f"bold {color}")
        text.append(f"  •  ", style="dim")
        text.append(f"{node.age_display}", style="cyan")
        text.append("\n")

        # Divider
        text.append("  " + "─" * 40 + "\n", style="dim")

        # Content
        text.append(f"\n  {node.content}\n", style="white")

        # Tags if present
        if node.tags:
            text.append("\n  ", style="")
            for tag in node.tags:
                text.append(f" #{tag} ", style="on dark_blue")
                text.append(" ", style="")
            text.append("\n")

        # Path to root (breadcrumb)
        if path and len(path) > 1:
            text.append("\n  📍 ", style="dim")
            for i, n in enumerate(reversed(path)):
                if i > 0:
                    text.append(" → ", style="dim")
                crumb = n.content[:12] + "…" if len(n.content) > 12 else n.content
                if n.id == node.id:
                    text.append(crumb, style="bold cyan")
                else:
                    text.append(crumb, style="dim")
            text.append("\n")

        # Metadata section
        text.append("\n  " + "─" * 40 + "\n", style="dim")
        text.append(f"  ID ", style="dim")
        text.append(f"{node.id}", style="cyan")
        text.append(f"  •  ", style="dim")
        text.append(f"{len(node.history)} changes\n", style="white")

        # Recent history
        if node.history:
            text.append("\n  Recent activity:\n", style="dim")
            for moment in node.history[-3:]:
                time_str = moment.timestamp.strftime("%H:%M")
                text.append(f"    {time_str} ", style="cyan")
                text.append(f"{moment.action}", style="yellow")
                if moment.context:
                    text.append(f" — {moment.context[:20]}…" if len(moment.context) > 20 else f" — {moment.context}", style="dim italic")
                text.append("\n")

        self.update(text)


class ContextInputWidget(Static):
    """Widget for showing contextual prompts and hints."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._hint = "Welcome to Dendrite. Press 'n' to plant a new seed."
        self._mode = "normal"
        self._render()

    def set_hint(self, hint: str, mode: str = "normal") -> None:
        """Set the contextual hint."""
        self._hint = hint
        self._mode = mode
        self._render()

    def _render(self) -> None:
        text = Text()

        mode_styles = {
            "normal": ("💡", "yellow"),
            "success": ("✓", "green"),
            "error": ("✗", "red"),
            "thinking": ("🤔", "cyan"),
            "ai": ("🤖", "magenta"),
        }

        icon, color = mode_styles.get(self._mode, ("•", "white"))
        text.append(f" {icon} ", style=color)
        text.append(self._hint, style="italic")
        self.update(text)


class StatsBar(Static):
    """A status bar showing tree statistics."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._stats: dict[str, int] = {}

    def set_stats(self, stats: dict[str, int]) -> None:
        """Update the stats display."""
        self._stats = stats
        self._render()

    def _render(self) -> None:
        text = Text()

        icons = {
            "seed": "🌱",
            "sprouting": "🌿",
            "growing": "🌳",
            "mature": "🌲",
            "dormant": "💤",
            "pruned": "✂️",
        }

        parts = []
        for state, icon in icons.items():
            count = self._stats.get(state, 0)
            if count > 0:
                parts.append(f"{icon}{count}")

        total = self._stats.get("total", 0)
        text.append(f" {total} ideas ", style="bold")
        text.append("│ ", style="dim")
        text.append(" ".join(parts), style="")

        self.update(text)


class LLMResponseWidget(Static):
    """Widget for displaying streaming LLM responses."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._content = ""
        self._is_streaming = False

    def start_stream(self, prompt: str = "") -> None:
        """Start a new streaming response."""
        self._content = ""
        self._is_streaming = True
        self._render_streaming(prompt)

    def append_chunk(self, chunk: str) -> None:
        """Append a chunk to the streaming response."""
        self._content += chunk
        self._render_streaming()

    def finish_stream(self) -> None:
        """Mark streaming as complete."""
        self._is_streaming = False
        self._render_streaming()

    def _render_streaming(self, prompt: str = "") -> None:
        """Render the current streaming state."""
        text = Text()

        if prompt:
            text.append(f"  🤖 ", style="magenta")
            text.append(f"{prompt}\n\n", style="dim italic")

        text.append(self._content, style="white")

        if self._is_streaming:
            text.append("▌", style="blink magenta")
        elif self._content:
            text.append("\n\n  ", style="")
            text.append("─ Complete ─", style="dim green")

        self.update(text)

    def clear(self) -> None:
        """Clear the widget."""
        self._content = ""
        self._is_streaming = False
        self.update("")
