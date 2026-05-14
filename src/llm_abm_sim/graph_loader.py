from __future__ import annotations

from pathlib import Path

import networkx as nx


def load_edge_list(path: str | Path, delimiter: str | None = None) -> nx.Graph:
    """Load a real social-network dataset from an edge-list file."""

    return nx.read_edgelist(path, delimiter=delimiter, nodetype=str)
