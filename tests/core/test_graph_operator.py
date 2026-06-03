import pytest

from sqllineage.config import SQLLineageConfig
from sqllineage.core.graph import get_graph_operator_class
from sqllineage.core.graph.networkx import NetworkXGraphOperator
from sqllineage.core.graph.rustworkx import RustworkXGraphOperator

GRAPH_OPERATOR_CLASSES = [NetworkXGraphOperator, RustworkXGraphOperator]


def test_graph_operator_dummy():
    with pytest.raises(TypeError):
        NetworkXGraphOperator().merge(RustworkXGraphOperator())
    with pytest.raises(TypeError):
        RustworkXGraphOperator().merge(NetworkXGraphOperator())


def test_graph_operator_import():
    assert get_graph_operator_class() == NetworkXGraphOperator
    with SQLLineageConfig(
        GRAPH_OPERATOR_CLASS="sqllineage.core.graph.rustworkx.RustworkXGraphOperator"
    ):
        assert get_graph_operator_class() == RustworkXGraphOperator


def test_graph_operator_import_fail():
    with SQLLineageConfig(GRAPH_OPERATOR_CLASS="invalid_format"):
        assert get_graph_operator_class() == NetworkXGraphOperator
    with SQLLineageConfig(
        GRAPH_OPERATOR_CLASS="sqllineage.core.graph.invalid_module.UnknownGraphOperator"
    ):
        assert get_graph_operator_class() == NetworkXGraphOperator
    with SQLLineageConfig(
        GRAPH_OPERATOR_CLASS="sqllineage.core.graph.networkx.UnknownGraphOperator"
    ):
        assert get_graph_operator_class() == NetworkXGraphOperator


@pytest.mark.parametrize("GraphOperatorClass", GRAPH_OPERATOR_CLASSES)
def test_non_true_props_rejected(GraphOperatorClass):
    # props are used exclusively as boolean tags (always True) across the code base
    # non-True values are currently not supported in GraphOperator classes
    go = GraphOperatorClass()
    with pytest.raises(AssertionError):
        go.add_vertex_if_not_exist("a", tagged=False)
    with pytest.raises(AssertionError):
        go.retrieve_vertices_by_props(category="source")
