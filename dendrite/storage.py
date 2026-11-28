"""Persistence layer for Dendrite - save and load forests."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import fields
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
            return {"__class__": type(obj).__name__, **{field.name: getattr(obj, field.name) for field in fields(obj)}}
        return super().default(obj)


def _restore_record(value: Any, cls: type) -> Any:
    """Restore the untagged nested records written by the original encoder."""
    if isinstance(value, cls):
        return value
    if not isinstance(value, dict):
        raise ValueError(f"Expected {cls.__name__} record")
    allowed = {field.name for field in fields(cls)}
    if set(value) - allowed:
        raise ValueError(f"Unknown {cls.__name__} fields")
    optional = {Moment: {"context"}, Node: {"tags"}}.get(cls, set())
    if (allowed - optional) - set(value):
        raise ValueError(f"Missing {cls.__name__} fields")
    data = dict(value)
    try:
        if cls is Forest:
            if not isinstance(data["trees"], dict):
                raise ValueError("Expected tree mapping")
            data["trees"] = {key: _restore_record(tree, Tree)
                             for key, tree in data["trees"].items()}
        elif cls is Tree:
            if not isinstance(data["nodes"], dict):
                raise ValueError("Expected node mapping")
            data["nodes"] = {key: _restore_record(node, Node)
                             for key, node in data["nodes"].items()}
        elif cls is Node:
            if not isinstance(data["history"], list):
                raise ValueError("Expected history list")
            data["history"] = [_restore_record(moment, Moment)
                               for moment in data["history"]]
        record = cls(**data)
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Invalid {cls.__name__} record") from exc
    checks = {
        Forest: {"trees": dict, "active_tree_id": (str, type(None))},
        Tree: {"id": str, "name": str, "nodes": dict, "root_ids": list,
               "created_at": datetime},
        Node: {"id": str, "content": str, "state": NodeState,
               "parent_id": (str, type(None)), "children_ids": list,
               "history": list, "created_at": datetime, "tags": list},
        Moment: {"timestamp": datetime, "action": str,
                 "content_snapshot": str, "context": str},
    }
    for name, expected in checks[cls].items():
        if not isinstance(getattr(record, name), expected):
            raise ValueError(f"Invalid {cls.__name__}.{name}")
    for name in ("root_ids", "children_ids", "tags"):
        if hasattr(record, name) and not all(isinstance(item, str)
                                             for item in getattr(record, name)):
            raise ValueError(f"Invalid {cls.__name__}.{name}")
    for name in ("trees", "nodes"):
        if hasattr(record, name) and not all(isinstance(key, str)
                                             for key in getattr(record, name)):
            raise ValueError(f"Invalid {cls.__name__}.{name} keys")
    return record


def dendrite_decoder(dct: dict) -> Any:
    """Decode new tagged records and the original nested untagged format."""
    if "__datetime__" in dct:
        return datetime.fromisoformat(dct["__datetime__"])
    if "__nodestate__" in dct:
        return NodeState(dct["__nodestate__"])
    classes = {cls.__name__: cls for cls in (Forest, Tree, Node, Moment)}
    cls = classes.get(dct.get("__class__"))
    if cls is not None:
        return _restore_record({key: value for key, value in dct.items()
                                if key != "__class__"}, cls)
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
        # Write to a temp file in the same directory and swap it in, so a failed
        # or interrupted save leaves the previous file intact.
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(forest, f, cls=DendriteEncoder, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise
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
