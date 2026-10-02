"""Core data models for Dendrite - trees, branches, time, context."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class NodeState(Enum):
    """The lifecycle state of an idea."""
    SEED = "seed"           # Just planted, raw thought
    SPROUTING = "sprouting" # Being developed
    GROWING = "growing"     # Active development
    MATURE = "mature"       # Fully formed
    DORMANT = "dormant"     # Paused, may revisit
    PRUNED = "pruned"       # Deliberately cut


@dataclass
class Moment:
    """A point in time when something happened to a node."""
    timestamp: datetime
    action: str  # created, edited, branched, pruned, etc.
    content_snapshot: str
    context: str = ""  # What were you thinking? What triggered this?

    @classmethod
    def now(cls, action: str, content: str, context: str = "") -> Moment:
        return cls(
            timestamp=datetime.now(),
            action=action,
            content_snapshot=content,
            context=context
        )


@dataclass
class Node:
    """A single idea node in the tree."""
    id: str
    content: str
    state: NodeState = NodeState.SEED
    parent_id: Optional[str] = None
    children_ids: list[str] = field(default_factory=list)
    history: list[Moment] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    tags: list[str] = field(default_factory=list)

    @classmethod
    def create(cls, content: str, parent_id: Optional[str] = None, context: str = "") -> Node:
        """Create a new node with initial history."""
        node = cls(
            id=str(uuid.uuid4())[:8],
            content=content,
            parent_id=parent_id,
        )
        node.history.append(Moment.now("created", content, context))
        return node

    def edit(self, new_content: str, context: str = "") -> None:
        """Edit the node, preserving history."""
        self.history.append(Moment.now("edited", new_content, context))
        self.content = new_content

    def set_state(self, new_state: NodeState, context: str = "") -> None:
        """Change the node's lifecycle state."""
        self.history.append(Moment.now(f"state:{new_state.value}", self.content, context))
        self.state = new_state

    @property
    def age_display(self) -> str:
        """Human-readable age."""
        delta = datetime.now() - self.created_at
        if delta.days > 0:
            return f"{delta.days}d ago"
        elif delta.seconds > 3600:
            return f"{delta.seconds // 3600}h ago"
        elif delta.seconds > 60:
            return f"{delta.seconds // 60}m ago"
        else:
            return "just now"

    @property
    def state_icon(self) -> str:
        """Visual icon for the state."""
        icons = {
            NodeState.SEED: "🌱",
            NodeState.SPROUTING: "🌿",
            NodeState.GROWING: "🌳",
            NodeState.MATURE: "🌲",
            NodeState.DORMANT: "💤",
            NodeState.PRUNED: "✂️",
        }
        return icons.get(self.state, "•")


@dataclass
class Tree:
    """A tree of ideas with full history."""
    id: str
    name: str
    nodes: dict[str, Node] = field(default_factory=dict)
    root_ids: list[str] = field(default_factory=list)  # Trees can have multiple roots
    created_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def create(cls, name: str) -> Tree:
        return cls(
            id=str(uuid.uuid4())[:8],
            name=name
        )

    def add_node(self, content: str, parent_id: Optional[str] = None, context: str = "") -> Node:
        """Add a new node to the tree."""
        node = Node.create(content, parent_id, context)
        self.nodes[node.id] = node

        if parent_id is None:
            self.root_ids.append(node.id)
        elif parent_id in self.nodes:
            self.nodes[parent_id].children_ids.append(node.id)

        return node

    def get_node(self, node_id: str) -> Optional[Node]:
        return self.nodes.get(node_id)

    def get_children(self, node_id: str) -> list[Node]:
        """Get all children of a node."""
        node = self.nodes.get(node_id)
        if not node:
            return []
        return [self.nodes[cid] for cid in node.children_ids if cid in self.nodes]

    def get_path_to_root(self, node_id: str) -> list[Node]:
        """Get the path from a node back to its root."""
        path = []
        current_id = node_id
        while current_id:
            node = self.nodes.get(current_id)
            if not node:
                break
            path.append(node)
            current_id = node.parent_id
        return path

    def branch(self, from_node_id: str, content: str, context: str = "") -> Node:
        """Create a branch (child) from an existing node."""
        return self.add_node(content, from_node_id, context)

    def get_timeline(self) -> list[tuple[datetime, Node, Moment]]:
        """Get a chronological timeline of all changes across the tree."""
        timeline = []
        for node in self.nodes.values():
            for moment in node.history:
                timeline.append((moment.timestamp, node, moment))
        timeline.sort(key=lambda x: x[0], reverse=True)
        return timeline


@dataclass
class Forest:
    """A collection of trees - your entire idea space."""
    trees: dict[str, Tree] = field(default_factory=dict)
    active_tree_id: Optional[str] = None

    def create_tree(self, name: str) -> Tree:
        tree = Tree.create(name)
        self.trees[tree.id] = tree
        if self.active_tree_id is None:
            self.active_tree_id = tree.id
        return tree

    @property
    def active_tree(self) -> Optional[Tree]:
        if self.active_tree_id:
            return self.trees.get(self.active_tree_id)
        return None

    def get_global_timeline(self, limit: int = 50) -> list[tuple[Tree, datetime, Node, Moment]]:
        """Timeline across all trees."""
        timeline = []
        for tree in self.trees.values():
            for ts, node, moment in tree.get_timeline():
                timeline.append((tree, ts, node, moment))
        timeline.sort(key=lambda x: x[1], reverse=True)
        return timeline[:limit]
