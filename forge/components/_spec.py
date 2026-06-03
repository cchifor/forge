"""The component graph node — one Layer-1/2/3 component as a graph vertex.

A component is identified by ``name`` and carries its composition layer, its
own version, the child components it composes (name → version-spec, mirroring
``[feature.depends]``), and the data contract(s) it consumes/aggregates. This is
the node type the component resolver topo-sorts; it is built from a
``FeatureManifest`` whose ``component_layer`` is set.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ComponentNode:
    """One layered component as a node in the component dependency graph."""

    name: str
    layer: int  # 1 | 2 | 3 (Layer-1 basic / Layer-2 composed / Layer-3 template)
    version: str = "1.0.0"
    # Child components: name → version-spec (PEP 440; "" / "*" mean "any").
    children: dict[str, str] = field(default_factory=dict)
    # The single data contract this component consumes (Layer-1 typically).
    contract: str | None = None
    # Contracts a Layer-2 component aggregates across its children.
    aggregates: tuple[str, ...] = ()
