"""Persistence layer for Dendrite - save and load forests."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import Forest, Tree, Node, NodeState, Moment


class DendriteEncoder(json.JSONEncoder):
    """Custom JSON encoder for Dendrite objects."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return {"__datetime__": obj.isoformat()}
        if isinstance(obj, NodeState):
            return {"__nodestate__": obj.value}
        if isinstance(obj, (Forest, Tree, Node, Moment)):
            return {"__class__": type(obj).__name__, **asdict(obj)}
        return super().default(obj)


def dendrite_decoder(dct: dict) -> Any:
    """Custom JSON decoder for Dendrite objects."""
    if "__datetime__" in dct:
        return datetime.fromisoformat(dct["__datetime__"])
    if "__nodestate__" in dct:
        return NodeState(dct["__nodestate__"])
    if "__class__" in dct:
        class_name = dct.pop("__class__")
        if class_name == "Moment":
            return Moment(
                timestamp=dct["timestamp"],
                action=dct["action"],
                content_snapshot=dct["content_snapshot"],
                context=dct.get("context", "")
            )
        elif class_name == "Node":
            node = Node(
                id=dct["id"],
                content=dct["content"],
                state=dct["state"],
                parent_id=dct["parent_id"],
                children_ids=dct["children_ids"],
                history=dct["history"],
                created_at=dct["created_at"],
                tags=dct.get("tags", [])
            )
            return node
        elif class_name == "Tree":
            tree = Tree(
                id=dct["id"],
                name=dct["name"],
                nodes=dct["nodes"],
                root_ids=dct["root_ids"],
                created_at=dct["created_at"]
            )
            return tree
        elif class_name == "Forest":
            forest = Forest(
                trees=dct["trees"],
                active_tree_id=dct["active_tree_id"]
            )
            return forest
    return dct


class Storage:
    """Handles saving and loading forests to/from disk."""

    DEFAULT_DIR = Path.home() / ".dendrite"
    DEFAULT_FILE = "forest.json"

    def __init__(self, storage_dir: Path | None = None):
        self.storage_dir = storage_dir or self.DEFAULT_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, filename: str | None = None) -> Path:
        """Get the full path for a storage file."""
        return self.storage_dir / (filename or self.DEFAULT_FILE)

    def save(self, forest: Forest, filename: str | None = None) -> Path:
        """Save a forest to disk."""
        path = self._get_path(filename)
        with open(path, "w") as f:
            json.dump(forest, f, cls=DendriteEncoder, indent=2)
        return path

    def load(self, filename: str | None = None) -> Forest | None:
        """Load a forest from disk. Returns None if file doesn't exist."""
        path = self._get_path(filename)
        if not path.exists():
            return None
        with open(path, "r") as f:
            return json.load(f, object_hook=dendrite_decoder)

    def list_saves(self) -> list[tuple[str, datetime]]:
        """List all saved forests with their modification times."""
        saves = []
        for path in self.storage_dir.glob("*.json"):
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            saves.append((path.name, mtime))
        saves.sort(key=lambda x: x[1], reverse=True)
        return saves

    def delete(self, filename: str) -> bool:
        """Delete a saved forest."""
        path = self._get_path(filename)
        if path.exists():
            path.unlink()
            return True
        return False

    def export_markdown(self, forest: Forest, filename: str | None = None) -> Path:
        """Export a forest to markdown format."""
        path = self.storage_dir / (filename or "export.md")

        lines = ["# Dendrite Export\n"]
        lines.append(f"*Exported: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\n")

        for tree in forest.trees.values():
            lines.append(f"## {tree.name}\n\n")

            def render_node(node: Node, depth: int = 0) -> None:
                indent = "  " * depth
                state_markers = {
                    NodeState.SEED: "🌱",
                    NodeState.SPROUTING: "🌿",
                    NodeState.GROWING: "🌳",
                    NodeState.MATURE: "🌲",
                    NodeState.DORMANT: "💤",
                    NodeState.PRUNED: "~~",
                }
                marker = state_markers.get(node.state, "-")

                if node.state == NodeState.PRUNED:
                    lines.append(f"{indent}- ~~{node.content}~~\n")
                else:
                    lines.append(f"{indent}- {marker} {node.content}\n")

                # Add context if present in last history entry
                if node.history and node.history[-1].context:
                    lines.append(f"{indent}  > *{node.history[-1].context}*\n")

                for child_id in node.children_ids:
                    child = tree.nodes.get(child_id)
                    if child:
                        render_node(child, depth + 1)

            for root_id in tree.root_ids:
                root = tree.nodes.get(root_id)
                if root:
                    render_node(root)
            lines.append("\n")

        with open(path, "w") as f:
            f.writelines(lines)

        return path
