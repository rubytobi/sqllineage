from typing import Any

import networkx as nx

from sqllineage.core.graph_operator import GraphOperator
from sqllineage.utils.constant import EdgeDirection
from sqllineage.utils.entities import EdgeTuple


class NetworkXGraphOperator(GraphOperator):
    """
    networkx based implementation of GraphOperator.

    networkx allows any hashable object to be added as a node.

    networkx edge has a native support for edge type, which we use to store edge label.
    """

    def __init__(self, graph: nx.DiGraph = None) -> None:
        if graph is None:
            self.graph = nx.DiGraph()
            self._tag_index: dict[str, set[Any]] = {}
            self._canonical: dict[Any, Any] = {}
        else:
            self.graph = graph
            self._tag_index = {}
            self._canonical = {}
            for v, attr in self.graph.nodes(data=True):
                self._canonical[v] = v
                for prop, val in attr.items():
                    if val is True:
                        self._tag_index.setdefault(prop, set()).add(v)

    def add_vertex_if_not_exist(self, vertex: Any, **props) -> None:
        self.graph.add_node(vertex, **props)
        canonical = self._canonical.setdefault(vertex, vertex)
        for prop, val in props.items():
            if val is True:
                self._tag_index.setdefault(prop, set()).add(canonical)
            else:
                self._tag_index.get(prop, set()).discard(canonical)

    def retrieve_vertices_by_props(self, **props) -> list[Any]:
        if not props:
            return list(self.graph.nodes())
        result: set[Any] | None = None
        for prop, val in props.items():
            if val is True:
                candidates = self._tag_index.get(prop, set())
            else:
                candidates = {
                    v
                    for v, attr in self.graph.nodes(data=True)
                    if attr.get(prop) == val
                }
            result = candidates if result is None else result & candidates
        return list(result or set())

    def retrieve_source_vertices(self) -> list[Any]:
        return list(
            set(v for v, degree in self.graph.in_degree if degree == 0).intersection(
                set(v for v, degree in self.graph.out_degree if degree > 0)
            )
        )

    def retrieve_target_vertices(self) -> list[Any]:
        return list(
            set(v for v, degree in self.graph.out_degree if degree == 0).intersection(
                set(v for v, degree in self.graph.in_degree if degree > 0)
            )
        )

    def retrieve_selfloop_vertices(self) -> list[Any]:
        return [e[0] for e in nx.selfloop_edges(self.graph)]

    def update_vertices(self, *vertices, **props) -> None:
        nx.set_node_attributes(
            self.graph,
            {vertex: {k: v for k, v in props.items()} for vertex in vertices},
        )
        for prop, val in props.items():
            if val is True:
                tag_set = self._tag_index.setdefault(prop, set())
                tag_set.update(self._canonical.get(v, v) for v in vertices)
            else:
                tag_set = self._tag_index.get(prop, set())
                for vertex in vertices:
                    tag_set.discard(self._canonical.get(vertex, vertex))

    def drop_vertices(self, *vertices) -> None:
        for vertex in vertices:
            if self.graph.has_node(vertex):
                self.graph.remove_node(vertex)
            canonical = self._canonical.pop(vertex, vertex)
            for tag_set in self._tag_index.values():
                tag_set.discard(canonical)

    def add_edge_if_not_exist(
        self, src_vertex: Any, tgt_vertex: Any, label: str, **props
    ) -> None:
        # starting NetworkX v2.6, None is not allowed as node, see https://github.com/networkx/networkx/pull/4892
        if src_vertex is not None and tgt_vertex is not None:
            # pop type if present as type is explicitly set by label
            props.pop("type", None)
            self.graph.add_edge(src_vertex, tgt_vertex, type=label, **props)

    def retrieve_edges_by_label(self, label: str) -> list[EdgeTuple]:
        return [
            EdgeTuple(
                source=src, target=tgt, label=attr.get("type", ""), attributes=attr
            )
            for src, tgt, attr in self.graph.edges(data=True)
            if attr.get("type") == label
        ]

    def retrieve_edges_by_vertex(
        self, vertex: Any, direction: str, label: str | None = None
    ) -> list[EdgeTuple]:
        edges = []
        edge_view = (
            self.graph.in_edges(vertex, data=True)
            if direction == EdgeDirection.IN
            else self.graph.out_edges(vertex, data=True)
        )
        for src, tgt, attr in edge_view:
            # always add the edge when label is not specified (or when specified and matches)
            if label is None or attr.get("type") == label:
                edges.append(
                    EdgeTuple(
                        source=src,
                        target=tgt,
                        label=attr.get("type", ""),
                        attributes=attr,
                    )
                )
        return edges

    def drop_edge(self, src_vertex: Any, tgt_vertex: Any) -> None:
        self.graph.remove_edge(src_vertex, tgt_vertex)

    def get_sub_graph(self, *vertices) -> "NetworkXGraphOperator":
        return NetworkXGraphOperator(self.graph.subgraph(vertices))

    def merge(self, other: GraphOperator) -> None:
        if isinstance(other, NetworkXGraphOperator):
            self.graph = nx.compose(self.graph, other.graph)
            for v, c in other._canonical.items():
                self._canonical.setdefault(v, c)
            for prop, tag_set in other._tag_index.items():
                self_tag_set = self._tag_index.setdefault(prop, set())
                for v in tag_set:
                    self_tag_set.add(self._canonical.get(v, v))
        else:
            raise TypeError(
                "Expect other to be NetworkXGraphOperator, got " + str(type(other))
            )

    def list_lineage_paths(self, src_vertex: Any, tgt_vertex: Any) -> list[list[Any]]:
        return list(nx.all_simple_paths(self.graph, src_vertex, tgt_vertex))

    def to_cytoscape(
        self, compound: bool = False
    ) -> list[dict[str, dict[str, object]]]:
        if compound:
            parents_dict = {
                node.parent: {
                    "name": (
                        str(node.parent) if node.parent is not None else "<unknown>"
                    ),
                    "type": (
                        type(node.parent).__name__
                        if node.parent is not None
                        else "Table or SubQuery"
                    ),
                }
                for node in self.graph.nodes
            }
            nodes = [
                {
                    "data": {
                        "id": str(node),
                        "parent": parents_dict[node.parent]["name"],
                        "parent_candidates": [
                            {"name": str(p), "type": type(p).__name__}
                            for p in node.parent_candidates
                        ],
                        "type": type(node).__name__,
                    }
                }
                for node in self.graph.nodes
            ]
            nodes += [
                {"data": {"id": attr["name"], "type": attr["type"]}}
                for _, attr in parents_dict.items()
            ]
        else:
            nodes = [{"data": {"id": str(node)}} for node in self.graph.nodes]
        edges: list[dict[str, dict[str, Any]]] = [
            {"data": {"id": f"e{i}", "source": str(edge[0]), "target": str(edge[1])}}
            for i, edge in enumerate(self.graph.edges)
        ]
        return nodes + edges
