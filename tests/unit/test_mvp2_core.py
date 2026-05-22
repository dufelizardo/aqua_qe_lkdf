"""
tests/unit/test_mvp2_core.py
AQuA-QE LKDF v1.4 — Unit Tests: GraphRepository · AIGateway · FanOutPipeline
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from runtime_core.persistence.graph.models import Edge, Graph, Node, RelationType
from runtime_core.persistence.adapters.sqlite_adapter import SQLiteGraphAdapter
from ai_engine.gateway.gateway import (
    AIGateway, LLMConfig, LLMProvider, LLMRequest, LLMResponse,
    TaskType, create_default_gateway,
)
from runtime_core.pipeline.fanout import (
    FanOutPipeline, PipelineContext, PipelineStage, StageStatus,
)


# ===========================================================================
# Graph Models
# ===========================================================================

class TestGraphModels:

    def test_node_default_id(self):
        n = Node(label="Requirement")
        assert n.id is not None

    def test_node_get_set_property(self):
        n = Node(label="Flow")
        n.set("name", "LoginFlow")
        assert n.get("name") == "LoginFlow"

    def test_node_repr(self):
        n = Node(label="Story", external_id="BFTG-127")
        assert "BFTG-127" in repr(n)

    def test_edge_repr(self):
        e = Edge(relation=RelationType.HAS_FLOW)
        assert "HAS_FLOW" in repr(e)

    def test_graph_find_node(self):
        n1 = Node(label="A")
        n2 = Node(label="B")
        g  = Graph(nodes=[n1, n2])
        assert g.find_node(n1.id) == n1
        assert g.find_node(uuid4()) is None

    def test_graph_find_by_label(self):
        n1 = Node(label="Requirement")
        n2 = Node(label="Flow")
        n3 = Node(label="Requirement")
        g  = Graph(nodes=[n1, n2, n3])
        reqs = g.find_by_label("Requirement")
        assert len(reqs) == 2

    def test_graph_find_by_external_id(self):
        n = Node(label="Requirement", external_id="REQ-001")
        g = Graph(nodes=[n])
        assert g.find_by_external_id("REQ-001") == n
        assert g.find_by_external_id("REQ-999") is None

    def test_graph_neighbors(self):
        n1 = Node(label="A")
        n2 = Node(label="B")
        e  = Edge(source_id=n1.id, target_id=n2.id, relation=RelationType.HAS_FLOW)
        g  = Graph(nodes=[n1, n2], edges=[e])
        neighbors = g.neighbors(n1.id)
        assert n2 in neighbors

    def test_graph_neighbors_filtered_by_relation(self):
        n1 = Node(label="A")
        n2 = Node(label="B")
        n3 = Node(label="C")
        e1 = Edge(source_id=n1.id, target_id=n2.id, relation=RelationType.HAS_FLOW)
        e2 = Edge(source_id=n1.id, target_id=n3.id, relation=RelationType.HAS_SCENARIO)
        g  = Graph(nodes=[n1, n2, n3], edges=[e1, e2])
        flows = g.neighbors(n1.id, RelationType.HAS_FLOW)
        assert n2 in flows
        assert n3 not in flows

    def test_graph_merge(self):
        n1 = Node(label="A")
        n2 = Node(label="B")
        g1 = Graph(nodes=[n1])
        g2 = Graph(nodes=[n2])
        merged = g1.merge(g2)
        assert len(merged.nodes) == 2

    def test_graph_merge_no_duplicates(self):
        n1 = Node(label="A")
        g1 = Graph(nodes=[n1])
        g2 = Graph(nodes=[n1])   # same node
        merged = g1.merge(g2)
        assert len(merged.nodes) == 1

    def test_graph_is_empty(self):
        assert Graph().is_empty()
        assert not Graph(nodes=[Node(label="X")]).is_empty()

    def test_relation_type_values(self):
        assert RelationType.HAS_FLOW.value == "HAS_FLOW"
        assert RelationType.IMPACTS.value == "IMPACTS"
        assert RelationType.CONTRADICTS.value == "CONTRADICTS"


# ===========================================================================
# SQLiteGraphAdapter
# ===========================================================================

@pytest.fixture
async def db():
    adapter = SQLiteGraphAdapter("sqlite+aiosqlite:///:memory:")
    await adapter.initialize()
    yield adapter
    await adapter.close()


class TestSQLiteGraphAdapter:

    @pytest.mark.asyncio
    async def test_initialize(self, db):
        assert db._engine is not None

    @pytest.mark.asyncio
    async def test_add_and_get_node(self, db):
        node = Node(label="Requirement", external_id="REQ-001",
                    properties={"text": "Login deve funcionar"})
        saved = await db.add_node(node)
        fetched = await db.get_node(saved.id)
        assert fetched is not None
        assert fetched.label == "Requirement"
        assert fetched.external_id == "REQ-001"
        assert fetched.properties["text"] == "Login deve funcionar"

    @pytest.mark.asyncio
    async def test_get_nonexistent_node(self, db):
        result = await db.get_node(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_node_by_external_id(self, db):
        node = Node(label="Flow", external_id="FLOW-007")
        await db.add_node(node)
        fetched = await db.get_node_by_external_id("FLOW-007")
        assert fetched is not None
        assert fetched.external_id == "FLOW-007"

    @pytest.mark.asyncio
    async def test_get_node_by_external_id_with_label(self, db):
        n1 = Node(label="Requirement", external_id="X-001")
        n2 = Node(label="Flow",        external_id="X-001")
        await db.add_node(n1)
        await db.add_node(n2)
        fetched = await db.get_node_by_external_id("X-001", label="Flow")
        assert fetched.label == "Flow"

    @pytest.mark.asyncio
    async def test_update_node(self, db):
        node = Node(label="Story", external_id="S-001", properties={"title": "old"})
        saved = await db.add_node(node)
        saved.properties["title"] = "new"
        updated = await db.update_node(saved)
        fetched = await db.get_node(updated.id)
        assert fetched.properties["title"] == "new"

    @pytest.mark.asyncio
    async def test_delete_node(self, db):
        node  = Node(label="Temp")
        saved = await db.add_node(node)
        result = await db.delete_node(saved.id)
        assert result is True
        assert await db.get_node(saved.id) is None

    @pytest.mark.asyncio
    async def test_find_nodes_by_label(self, db):
        await db.add_node(Node(label="Requirement", external_id="R-1"))
        await db.add_node(Node(label="Requirement", external_id="R-2"))
        await db.add_node(Node(label="Flow",        external_id="F-1"))
        reqs = await db.find_nodes(label="Requirement")
        assert len(reqs) == 2

    @pytest.mark.asyncio
    async def test_add_and_get_edge(self, db):
        n1 = await db.add_node(Node(label="Requirement", external_id="REQ-010"))
        n2 = await db.add_node(Node(label="Flow",        external_id="FLOW-010"))
        edge = await db.add_edge(n1.id, n2.id, RelationType.HAS_FLOW)
        fetched = await db.get_edge(edge.id)
        assert fetched is not None
        assert fetched.relation == RelationType.HAS_FLOW
        assert fetched.source_id == n1.id
        assert fetched.target_id == n2.id

    @pytest.mark.asyncio
    async def test_get_edges_by_source(self, db):
        n1 = await db.add_node(Node(label="A"))
        n2 = await db.add_node(Node(label="B"))
        n3 = await db.add_node(Node(label="C"))
        await db.add_edge(n1.id, n2.id, RelationType.HAS_FLOW)
        await db.add_edge(n1.id, n3.id, RelationType.HAS_SCENARIO)
        edges = await db.get_edges(source_id=n1.id)
        assert len(edges) == 2

    @pytest.mark.asyncio
    async def test_get_edges_by_relation(self, db):
        n1 = await db.add_node(Node(label="A"))
        n2 = await db.add_node(Node(label="B"))
        n3 = await db.add_node(Node(label="C"))
        await db.add_edge(n1.id, n2.id, RelationType.HAS_FLOW)
        await db.add_edge(n1.id, n3.id, RelationType.IMPACTS)
        flows = await db.get_edges(source_id=n1.id, relation=RelationType.HAS_FLOW)
        assert len(flows) == 1

    @pytest.mark.asyncio
    async def test_get_neighbors(self, db):
        n1 = await db.add_node(Node(label="Requirement"))
        n2 = await db.add_node(Node(label="Flow"))
        await db.add_edge(n1.id, n2.id, RelationType.HAS_FLOW)
        neighbors = await db.get_neighbors(n1.id)
        assert any(n.id == n2.id for n in neighbors)

    @pytest.mark.asyncio
    async def test_get_subgraph(self, db):
        n1 = await db.add_node(Node(label="Requirement", external_id="R-SUB"))
        n2 = await db.add_node(Node(label="Flow",        external_id="F-SUB"))
        n3 = await db.add_node(Node(label="Scenario",    external_id="S-SUB"))
        await db.add_edge(n1.id, n2.id, RelationType.HAS_FLOW)
        await db.add_edge(n2.id, n3.id, RelationType.HAS_SCENARIO)
        subgraph = await db.get_subgraph(n1.id, max_depth=2)
        assert len(subgraph.nodes) == 3

    @pytest.mark.asyncio
    async def test_shortest_path(self, db):
        n1 = await db.add_node(Node(label="A"))
        n2 = await db.add_node(Node(label="B"))
        n3 = await db.add_node(Node(label="C"))
        await db.add_edge(n1.id, n2.id, RelationType.HAS_FLOW)
        await db.add_edge(n2.id, n3.id, RelationType.HAS_SCENARIO)
        path = await db.shortest_path(n1.id, n3.id)
        assert len(path) == 3
        assert path[0].id == n1.id
        assert path[-1].id == n3.id

    @pytest.mark.asyncio
    async def test_shortest_path_no_connection(self, db):
        n1 = await db.add_node(Node(label="Isolated-A"))
        n2 = await db.add_node(Node(label="Isolated-B"))
        path = await db.shortest_path(n1.id, n2.id)
        assert path == []

    @pytest.mark.asyncio
    async def test_upsert_node_creates(self, db):
        node = Node(label="Story", external_id="US-NEW")
        result = await db.upsert_node(node)
        assert result.external_id == "US-NEW"

    @pytest.mark.asyncio
    async def test_upsert_node_updates(self, db):
        node = Node(label="Story", external_id="US-UPD", properties={"v": 1})
        await db.add_node(node)
        updated = Node(label="Story", external_id="US-UPD", properties={"v": 2})
        result = await db.upsert_node(updated)
        assert result.properties["v"] == 2

    @pytest.mark.asyncio
    async def test_ensure_edge_idempotent(self, db):
        n1 = await db.add_node(Node(label="A"))
        n2 = await db.add_node(Node(label="B"))
        e1 = await db.ensure_edge(n1.id, n2.id, RelationType.HAS_FLOW)
        e2 = await db.ensure_edge(n1.id, n2.id, RelationType.HAS_FLOW)
        assert e1.id == e2.id

    @pytest.mark.asyncio
    async def test_bulk_add_nodes(self, db):
        nodes = [Node(label="Bulk", external_id=f"B-{i}") for i in range(5)]
        result = await db.add_nodes_bulk(nodes)
        assert len(result) == 5
        found = await db.find_nodes(label="Bulk")
        assert len(found) == 5

    @pytest.mark.asyncio
    async def test_find_by_intent(self, db):
        await db.add_node(Node(label="Requirement", external_id="REQ-INTENT",
                               properties={"text": "login com autenticação"}))
        found = await db.find_by_intent("autenticação")
        assert len(found) >= 1

    @pytest.mark.asyncio
    async def test_get_impact_path(self, db):
        req  = await db.add_node(Node(label="Requirement", external_id="REQ-IMP"))
        flow = await db.add_node(Node(label="Flow",        external_id="FLOW-IMP"))
        scen = await db.add_node(Node(label="Scenario",    external_id="SCEN-IMP"))
        await db.add_edge(req.id, flow.id, RelationType.HAS_FLOW)
        await db.add_edge(flow.id, scen.id, RelationType.HAS_SCENARIO)
        impact = await db.get_impact_path(req.id)
        labels = {n.label for n in impact.nodes}
        assert "Flow" in labels
        assert "Scenario" in labels


# ===========================================================================
# AIGateway
# ===========================================================================

def make_mock_response(content: str = "test response") -> LLMResponse:
    return LLMResponse(
        request_id=uuid4(),
        provider=LLMProvider.ANTHROPIC,
        model="claude-sonnet-4-20250514",
        content=content,
        input_tokens=100,
        output_tokens=50,
        latency_ms=300,
        cost_usd=0.00225,
    )


class TestAIGateway:

    def test_register_provider(self):
        gw = AIGateway()
        gw.register(LLMConfig(
            provider=LLMProvider.ANTHROPIC,
            model="claude-sonnet-4-20250514",
            api_key="test",
        ))
        assert LLMProvider.ANTHROPIC in gw.registered_providers

    def test_set_routing(self):
        gw = AIGateway()
        gw.set_routing(TaskType.CHAT, LLMProvider.OPENAI)
        assert gw._routing[TaskType.CHAT] == LLMProvider.OPENAI

    def test_set_fallback_chain(self):
        gw = AIGateway()
        chain = [LLMProvider.OPENAI, LLMProvider.ANTHROPIC]
        gw.set_fallback_chain(chain)
        assert gw._fallback_chain == chain

    @pytest.mark.asyncio
    async def test_complete_calls_client(self):
        gw = AIGateway()
        gw.register(LLMConfig(provider=LLMProvider.ANTHROPIC, model="claude", api_key="k"))

        mock_client = MagicMock()
        mock_client.complete = AsyncMock(return_value=make_mock_response("hello"))
        gw._clients[LLMProvider.ANTHROPIC] = mock_client

        req = LLMRequest(
            task_type=TaskType.REQUIREMENT_ANALYSIS,
            messages=[{"role": "user", "content": "test"}],
        )
        resp = await gw.complete(req)
        assert resp.content == "hello"
        mock_client.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_on_primary_failure(self):
        gw = AIGateway()
        gw.register(LLMConfig(provider=LLMProvider.ANTHROPIC, model="claude", api_key="k1"))
        gw.register(LLMConfig(provider=LLMProvider.OPENAI, model="gpt", api_key="k2"))
        gw.set_fallback_chain([LLMProvider.ANTHROPIC, LLMProvider.OPENAI])

        failing_client = MagicMock()
        failing_client.complete = AsyncMock(side_effect=Exception("API down"))
        fallback_client = MagicMock()
        fallback_client.complete = AsyncMock(return_value=make_mock_response("fallback"))

        gw._clients[LLMProvider.ANTHROPIC] = failing_client
        gw._clients[LLMProvider.OPENAI]    = fallback_client

        req  = LLMRequest(task_type=TaskType.CHAT,
                          messages=[{"role": "user", "content": "test"}])
        resp = await gw.complete(req, provider=LLMProvider.ANTHROPIC)
        assert resp.content == "fallback"

    @pytest.mark.asyncio
    async def test_all_providers_fail_raises(self):
        gw = AIGateway()
        gw.register(LLMConfig(provider=LLMProvider.ANTHROPIC, model="claude", api_key="k"))
        gw._fallback_chain = [LLMProvider.ANTHROPIC]

        mock_client = MagicMock()
        mock_client.complete = AsyncMock(side_effect=Exception("totally down"))
        gw._clients[LLMProvider.ANTHROPIC] = mock_client

        req = LLMRequest(task_type=TaskType.CHAT,
                         messages=[{"role": "user", "content": "test"}])
        with pytest.raises(RuntimeError, match="All AI providers failed"):
            await gw.complete(req)

    @pytest.mark.asyncio
    async def test_complete_batch(self):
        gw = AIGateway()
        gw.register(LLMConfig(provider=LLMProvider.ANTHROPIC, model="claude", api_key="k"))

        call_count = 0
        async def mock_complete(req: LLMRequest) -> LLMResponse:
            nonlocal call_count
            call_count += 1
            return make_mock_response(f"response-{call_count}")

        mock_client = MagicMock()
        mock_client.complete = mock_complete
        gw._clients[LLMProvider.ANTHROPIC] = mock_client

        reqs = [LLMRequest(task_type=TaskType.CHAT,
                           messages=[{"role": "user", "content": f"q{i}"}])
                for i in range(3)]
        responses = await gw.complete_batch(reqs)
        assert len(responses) == 3
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_batch_partial_failure_returns_all(self):
        gw = AIGateway()
        gw.register(LLMConfig(provider=LLMProvider.ANTHROPIC, model="claude", api_key="k"))
        gw._fallback_chain = [LLMProvider.ANTHROPIC]

        call_count = [0]
        async def mock_complete(req):
            call_count[0] += 1
            if call_count[0] == 2:
                raise Exception("fail")
            return make_mock_response("ok")

        mock_client = MagicMock()
        mock_client.complete = mock_complete
        gw._clients[LLMProvider.ANTHROPIC] = mock_client

        reqs = [LLMRequest(task_type=TaskType.CHAT,
                           messages=[{"role":"user","content":f"q{i}"}])
                for i in range(3)]
        responses = await gw.complete_batch(reqs)
        assert len(responses) == 3    # all returned, even failed ones

    def test_cost_report_structure(self):
        gw = AIGateway()
        report = gw.cost_report()
        for key in ("total_calls", "successful", "failed", "total_cost_usd",
                    "by_provider", "by_task", "avg_latency_ms"):
            assert key in report

    def test_audit_log_after_success(self):
        gw = AIGateway()
        resp = make_mock_response()
        req  = LLMRequest(task_type=TaskType.CHAT)
        gw._audit_success(req, resp)
        assert len(gw.audit_log) == 1
        assert gw.audit_log[0].success is True

    def test_create_default_gateway_no_keys(self):
        with patch.dict("os.environ", {}, clear=True):
            gw = create_default_gateway()
        assert isinstance(gw, AIGateway)


# ===========================================================================
# FanOutPipeline
# ===========================================================================

class EchoStage(PipelineStage):
    """Stage de teste que retorna o valor do contexto inputs[key]."""
    def __init__(self, stage_id, name, key="input", depends_on=None, optional=False, fail=False):
        super().__init__(stage_id, name, depends_on, optional)
        self.key  = key
        self._fail = fail

    async def execute(self, context: PipelineContext):
        if self._fail:
            raise RuntimeError(f"Stage {self.stage_id} forced failure")
        await asyncio.sleep(0.01)  # simulate work
        return context.inputs.get(self.key, f"output-{self.stage_id}")


class AccumulatorStage(PipelineStage):
    """Stage que agrega outputs de stages anteriores."""
    def __init__(self, stage_id, name, deps, dep_keys):
        super().__init__(stage_id, name, deps)
        self.dep_keys = dep_keys

    async def execute(self, context: PipelineContext):
        return [context.get_output(k) for k in self.dep_keys]


class TestFanOutPipeline:

    def _make_pipeline(self, stages, fail_fast=False):
        return FanOutPipeline("test-pipeline", stages, fail_fast=fail_fast)

    def _make_ctx(self, inputs=None):
        return PipelineContext(inputs=inputs or {})

    @pytest.mark.asyncio
    async def test_single_stage_runs(self):
        pipeline = self._make_pipeline([EchoStage("s1", "Stage1", key="v")])
        ctx      = self._make_ctx({"v": "hello"})
        result   = await pipeline.run(ctx)
        assert result.status == StageStatus.COMPLETED
        assert result.passed == 1
        assert ctx.get_output("s1") == "hello"

    @pytest.mark.asyncio
    async def test_sequential_dependency(self):
        stages = [
            EchoStage("s1", "First"),
            EchoStage("s2", "Second", depends_on=["s1"]),
        ]
        pipeline = self._make_pipeline(stages)
        ctx      = self._make_ctx()
        result   = await pipeline.run(ctx)
        assert result.status == StageStatus.COMPLETED
        assert result.passed == 2

    @pytest.mark.asyncio
    async def test_parallel_stages_run(self):
        """Stages sem dependências devem executar em paralelo."""
        stages = [
            EchoStage("s1", "Stage1"),
            EchoStage("s2", "Stage2"),
            EchoStage("s3", "Stage3"),
        ]
        pipeline = self._make_pipeline(stages)
        ctx      = self._make_ctx()
        t0       = asyncio.get_event_loop().time()
        result   = await pipeline.run(ctx)
        elapsed  = asyncio.get_event_loop().time() - t0
        # 3 parallel stages with 10ms each → total should be ~10ms not ~30ms
        assert elapsed < 0.08
        assert result.passed == 3

    @pytest.mark.asyncio
    async def test_fan_out_then_merge(self):
        """Padrão clássico: 1 stage → 3 paralelos → 1 agregador."""
        stages = [
            EchoStage("root", "Root"),
            EchoStage("a",    "BranchA", depends_on=["root"]),
            EchoStage("b",    "BranchB", depends_on=["root"]),
            EchoStage("c",    "BranchC", depends_on=["root"]),
            AccumulatorStage("merge", "Merge", deps=["a","b","c"], dep_keys=["a","b","c"]),
        ]
        pipeline = self._make_pipeline(stages)
        ctx      = self._make_ctx()
        result   = await pipeline.run(ctx)
        assert result.status == StageStatus.COMPLETED
        assert result.passed == 5
        merged = ctx.get_output("merge")
        assert len(merged) == 3

    @pytest.mark.asyncio
    async def test_failed_stage_propagates(self):
        stages = [
            EchoStage("s1", "OK Stage"),
            EchoStage("s2", "Fail Stage", fail=True),
        ]
        pipeline = self._make_pipeline(stages)
        ctx      = self._make_ctx()
        result   = await pipeline.run(ctx)
        assert result.status == StageStatus.FAILED
        assert result.failed == 1

    @pytest.mark.asyncio
    async def test_fail_fast_stops_pipeline(self):
        stages = [
            EchoStage("s1", "Fail", fail=True),
            EchoStage("s2", "Should Skip", depends_on=["s1"]),
        ]
        pipeline = self._make_pipeline(stages, fail_fast=True)
        ctx      = self._make_ctx()
        result   = await pipeline.run(ctx)
        assert result.status == StageStatus.FAILED
        # s2 was never run because s1 failed — it either doesn't appear or is skipped
        s2_results = [r for r in result.stage_results if r.stage_id == "s2"]
        if s2_results:
            assert s2_results[0].status == StageStatus.SKIPPED
        # Primary assertion: pipeline stopped after s1 failure
        assert result.failed >= 1

    @pytest.mark.asyncio
    async def test_optional_stage_failure_continues(self):
        stages = [
            EchoStage("s1", "Required"),
            EchoStage("s2", "Optional", fail=True, optional=True),
            EchoStage("s3", "After Optional", depends_on=["s1"]),
        ]
        pipeline = self._make_pipeline(stages)
        ctx      = self._make_ctx()
        result   = await pipeline.run(ctx)
        # Pipeline should still complete despite optional stage failure
        completed = {r.stage_id for r in result.stage_results if r.status == StageStatus.COMPLETED}
        assert "s1" in completed
        assert "s3" in completed

    @pytest.mark.asyncio
    async def test_dag_level_resolution(self):
        pipeline = self._make_pipeline([
            EchoStage("a", "A"),
            EchoStage("b", "B", depends_on=["a"]),
            EchoStage("c", "C", depends_on=["a"]),
            EchoStage("d", "D", depends_on=["b", "c"]),
        ])
        levels = pipeline._resolve_levels()
        assert levels[0] == ["a"]
        assert set(levels[1]) == {"b", "c"}
        assert levels[2] == ["d"]

    def test_cycle_detection(self):
        stages = [
            EchoStage("a", "A", depends_on=["b"]),
            EchoStage("b", "B", depends_on=["a"]),
        ]
        pipeline = self._make_pipeline(stages)
        with pytest.raises(ValueError, match="Ciclo detectado"):
            pipeline._resolve_levels()

    @pytest.mark.asyncio
    async def test_context_trace_populated(self):
        pipeline = self._make_pipeline([EchoStage("s1", "Stage1")])
        ctx      = self._make_ctx()
        await pipeline.run(ctx)
        events = [t["event"] for t in ctx.trace]
        assert "start"    in events
        assert "complete" in events

    @pytest.mark.asyncio
    async def test_result_summary_structure(self):
        pipeline = self._make_pipeline([EchoStage("s1", "S1")])
        ctx      = self._make_ctx()
        result   = await pipeline.run(ctx)
        summary  = result.summary()
        for key in ("pipeline_id", "execution_id", "status",
                    "stages", "passed", "failed", "total_ms"):
            assert key in summary

    @pytest.mark.asyncio
    async def test_pipeline_with_graph_persistence(self, db):
        stages   = [EchoStage("s1", "Stage1"), EchoStage("s2", "Stage2")]
        pipeline = self._make_pipeline(stages)
        ctx      = PipelineContext(graph=db)
        result   = await pipeline.run(ctx)
        assert result.status == StageStatus.COMPLETED
        # Verify graph was populated
        exec_nodes = await db.find_nodes(label="PipelineExecution")
        assert len(exec_nodes) >= 1
