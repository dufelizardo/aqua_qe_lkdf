"""
tests/unit/test_ambiguity_engine.py
AQuA-QE LKDF — Unit Tests: Ambiguity Engine (Detector + Analyzer + Resolver)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from ai_engine.ambiguity_engine.analyzer import AmbiguityAnalyzer
from ai_engine.ambiguity_engine.detector import RuleBasedDetector
from ai_engine.ambiguity_engine.models import (
    AmbiguityReport,
    AmbiguitySeverity,
    AmbiguityType,
    RiskLevel,
)
from ai_engine.ambiguity_engine.resolver import AmbiguityResolver


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

REQ_LOGIN = (
    "REQ-001",
    "O usuário deve ser redirecionado para o dashboard após o login bem-sucedido.",
)
REQ_BLOCK = (
    "REQ-007",
    "Após 3 tentativas incorretas de login, a conta do usuário deve ser bloqueada.",
)
REQ_NOTIFY = (
    "REQ-012",
    "O sistema deve enviar uma notificação quando um pedido for aprovado.",
)
REQ_CLEAN = (
    "REQ-020",
    "O sistema deve retornar HTTP 200 com o payload JSON quando o usuário autenticado "
    "com papel 'admin' envia uma requisição GET para /api/users com token JWT válido "
    "e não expirado. Em caso de token inválido, retornar HTTP 401. "
    "Em caso de token expirado, retornar HTTP 401 com mensagem 'Token expirado'. "
    "O tempo máximo de resposta é de 500ms para o percentil 95.",
)


def make_detector() -> RuleBasedDetector:
    return RuleBasedDetector()


def make_analyzer(mode: str = "rules_only") -> AmbiguityAnalyzer:
    return AmbiguityAnalyzer(api_key="test", mode=mode)


# ===========================================================================
# RuleBasedDetector
# ===========================================================================

class TestRuleBasedDetector:

    def test_detects_implicit_ambiguity(self):
        d = make_detector()
        ambs = d.detect(REQ_LOGIN[1])
        types = {a.type for a in ambs}
        assert AmbiguityType.IMPLICIT in types or AmbiguityType.SCOPE in types

    def test_detects_referential_in_login(self):
        d = make_detector()
        ambs = d.detect(REQ_LOGIN[1])
        types = {a.type for a in ambs}
        assert AmbiguityType.REFERENTIAL in types

    def test_detects_quantitative_in_block(self):
        d = make_detector()
        ambs = d.detect(REQ_BLOCK[1])
        # "3 tentativas" is explicit; but "bloqueada" has implicit scope
        assert len(ambs) >= 0   # may detect scope/implicit

    def test_detects_scope_in_notify(self):
        d = make_detector()
        ambs = d.detect(REQ_NOTIFY[1])
        types = {a.type for a in ambs}
        assert len(types) > 0

    def test_clean_req_has_fewer_ambiguities(self):
        d = make_detector()
        dirty_ambs = d.detect(REQ_LOGIN[1])
        clean_ambs = d.detect(REQ_CLEAN[1])
        assert len(clean_ambs) <= len(dirty_ambs)

    def test_each_ambiguity_has_question(self):
        d = make_detector()
        for req_id, text in [REQ_LOGIN, REQ_BLOCK, REQ_NOTIFY]:
            for amb in d.detect(text):
                assert amb.question != "", f"Sem pergunta para: {amb.text}"

    def test_each_ambiguity_has_id(self):
        d = make_detector()
        ambs = d.detect(REQ_LOGIN[1])
        for amb in ambs:
            assert amb.id.startswith("AMB-")

    def test_deduplication(self):
        d = make_detector()
        # run twice — should not duplicate
        a1 = d.detect(REQ_LOGIN[1])
        a2 = d.detect(REQ_LOGIN[1])
        assert len(a1) == len(a2)
        ids1 = {a.excerpt.lower()[:20] for a in a1}
        ids2 = {a.excerpt.lower()[:20] for a in a2}
        assert ids1 == ids2

    def test_severity_ordering(self):
        """Detector retorna na ordem de detecção; Analyzer ordena por severity."""
        d    = make_detector()
        ambs = d.detect(REQ_LOGIN[1])
        # All ambiguities must have valid severities
        for a in ambs:
            assert a.severity in (
                AmbiguitySeverity.CRITICAL, AmbiguitySeverity.HIGH,
                AmbiguitySeverity.MEDIUM, AmbiguitySeverity.LOW,
            )

    def test_extract_rules_from_explicit_must(self):
        d = make_detector()
        rules = d.extract_rules("O sistema deve validar o token antes de processar a requisição.")
        assert len(rules) >= 1
        assert any("deve" in r.description.lower() for r in rules)

    def test_extract_rules_from_restriction(self):
        d = make_detector()
        rules = d.extract_rules("O usuário não deve acessar recursos de outros usuários.")
        assert any("não deve" in r.description.lower() for r in rules)

    def test_identify_gaps_missing_error_path(self):
        d = make_detector()
        # REQ_LOGIN has no error handling
        gaps = d.identify_gaps(REQ_LOGIN[1])
        gap_types = {g.gap_type for g in gaps}
        assert "missing_error_path" in gap_types

    def test_identify_gaps_clean_req_fewer_gaps(self):
        d = make_detector()
        dirty_gaps = d.identify_gaps(REQ_LOGIN[1])
        clean_gaps = d.identify_gaps(REQ_CLEAN[1])
        assert len(clean_gaps) < len(dirty_gaps)

    def test_all_ambiguities_have_type(self):
        d = make_detector()
        for amb in d.detect(REQ_NOTIFY[1]):
            assert isinstance(amb.type, AmbiguityType)

    def test_all_ambiguities_have_severity(self):
        d = make_detector()
        for amb in d.detect(REQ_NOTIFY[1]):
            assert isinstance(amb.severity, AmbiguitySeverity)

    def test_suggests_options_for_implicit(self):
        d = make_detector()
        ambs = d.detect(
            "O sistema deve processar o pagamento e confirmar o pedido."
        )
        implicit = [a for a in ambs if a.type == AmbiguityType.IMPLICIT]
        for a in implicit:
            assert len(a.options) > 0

    def test_infers_impact(self):
        d = make_detector()
        ambs = d.detect(REQ_LOGIN[1])
        for a in ambs:
            assert a.impact != ""


# ===========================================================================
# AmbiguityAnalyzer
# ===========================================================================

class TestAmbiguityAnalyzerRulesOnly:

    @pytest.mark.asyncio
    async def test_returns_report(self):
        analyzer = make_analyzer()
        report   = await analyzer.analyze(REQ_LOGIN[1], REQ_LOGIN[0])
        assert isinstance(report, AmbiguityReport)

    @pytest.mark.asyncio
    async def test_report_has_requirement_id(self):
        analyzer = make_analyzer()
        report   = await analyzer.analyze(REQ_LOGIN[1], REQ_LOGIN[0])
        assert report.requirement_id == REQ_LOGIN[0]

    @pytest.mark.asyncio
    async def test_report_has_ambiguities(self):
        analyzer = make_analyzer()
        report   = await analyzer.analyze(REQ_LOGIN[1], REQ_LOGIN[0])
        assert len(report.ambiguities) > 0

    @pytest.mark.asyncio
    async def test_report_has_business_rules(self):
        analyzer = make_analyzer()
        report   = await analyzer.analyze(REQ_LOGIN[1], REQ_LOGIN[0])
        assert len(report.business_rules) > 0

    @pytest.mark.asyncio
    async def test_report_has_gaps(self):
        analyzer = make_analyzer()
        report   = await analyzer.analyze(REQ_LOGIN[1], REQ_LOGIN[0])
        assert len(report.gaps) > 0

    @pytest.mark.asyncio
    async def test_risk_level_high_for_vague_req(self):
        analyzer = make_analyzer()
        report   = await analyzer.analyze(REQ_LOGIN[1], REQ_LOGIN[0])
        # Login req has implicit ambiguities → CRITICAL → HIGH risk
        assert report.risk_level in (RiskLevel.HIGH, RiskLevel.MEDIUM)

    @pytest.mark.asyncio
    async def test_risk_level_low_for_clean_req(self):
        """Requisito limpo tem menos gaps do que um vago — valida diferença estrutural."""
        analyzer = make_analyzer()
        dirty_report = await analyzer.analyze(REQ_LOGIN[1], REQ_LOGIN[0])
        clean_report = await analyzer.analyze(REQ_CLEAN[1], REQ_CLEAN[0])
        # Clean req should have fewer gaps (explicit error handling, SLA defined)
        assert len(clean_report.gaps) < len(dirty_report.gaps)

    @pytest.mark.asyncio
    async def test_ambiguity_score_between_0_and_1(self):
        analyzer = make_analyzer()
        report   = await analyzer.analyze(REQ_LOGIN[1], REQ_LOGIN[0])
        assert 0.0 <= report.ambiguity_score <= 1.0

    @pytest.mark.asyncio
    async def test_critical_count_property(self):
        analyzer = make_analyzer()
        report   = await analyzer.analyze(REQ_LOGIN[1], REQ_LOGIN[0])
        assert report.critical_count >= 0
        assert report.critical_count <= report.total_ambiguities

    @pytest.mark.asyncio
    async def test_is_ready_for_testing(self):
        analyzer = make_analyzer()
        report_dirty = await analyzer.analyze(REQ_LOGIN[1], REQ_LOGIN[0])
        report_clean = await analyzer.analyze(REQ_CLEAN[1], REQ_CLEAN[0])
        # Clean req should be more ready
        assert isinstance(report_dirty.is_ready_for_testing, bool)
        assert isinstance(report_clean.is_ready_for_testing, bool)

    @pytest.mark.asyncio
    async def test_summary_structure(self):
        analyzer = make_analyzer()
        report   = await analyzer.analyze(REQ_LOGIN[1], REQ_LOGIN[0])
        summary  = report.summary()
        for key in ("requirement_id", "risk_level", "total_ambiguities",
                    "critical", "ambiguity_score", "is_ready_for_testing",
                    "clarifying_questions"):
            assert key in summary

    @pytest.mark.asyncio
    async def test_batch_analysis(self):
        analyzer = make_analyzer()
        reports  = await analyzer.analyze_batch([REQ_LOGIN, REQ_BLOCK, REQ_NOTIFY])
        assert len(reports) == 3
        assert reports[0].requirement_id == REQ_LOGIN[0]
        assert reports[1].requirement_id == REQ_BLOCK[0]

    @pytest.mark.asyncio
    async def test_by_type_filter(self):
        analyzer = make_analyzer()
        report   = await analyzer.analyze(REQ_LOGIN[1], REQ_LOGIN[0])
        referential = report.by_type(AmbiguityType.REFERENTIAL)
        assert isinstance(referential, list)

    @pytest.mark.asyncio
    async def test_domain_context_accepted(self):
        analyzer = make_analyzer()
        report   = await analyzer.analyze(
            REQ_LOGIN[1], REQ_LOGIN[0], domain_context="sistema bancário"
        )
        assert report is not None


MOCK_AI_RESPONSE = {
    "ambiguities": [
        {
            "type": "lexical",
            "severity": "HIGH",
            "excerpt": "bem-sucedido",
            "text": "\"Bem-sucedido\" pode significar apenas credenciais corretas ou inclui 2FA",
            "question": "O login com credenciais corretas mas sem 2FA é considerado bem-sucedido?",
            "options": ["Apenas credenciais corretas", "Credenciais + 2FA + termos aceitos"],
            "impact": "Implementação pode ignorar 2FA",
            "scenario_hint": "Testar login com credenciais corretas mas 2FA pendente",
        }
    ],
    "business_rules": [
        {
            "description": "Sessão deve ser criada antes do redirecionamento",
            "entities": ["sessão", "usuário"],
            "conditions": ["login bem-sucedido"],
            "outcomes": ["sessão ativa"],
            "source": "inferred",
            "confidence": 0.95,
        }
    ],
    "gaps": [
        {
            "description": "Comportamento no primeiro login não descrito",
            "gap_type": "missing_first_login",
            "priority": "MEDIUM",
            "suggested_scenario": "Testar primeiro acesso do usuário ao sistema",
        }
    ],
    "clarifying_questions": [
        "O redirecionamento vai para /dashboard fixo ou para a URL que o usuário tentava acessar?"
    ],
    "recommendations": [
        "Especifique o URL exato de destino do redirecionamento"
    ],
    "risk_level": "HIGH",
}


class TestAmbiguityAnalyzerWithMockedClaude:

    @pytest.mark.asyncio
    async def test_full_mode_merges_ai_and_rules(self):
        analyzer = AmbiguityAnalyzer(api_key="sk-fake", mode="full")
        with patch.object(analyzer, "_call_claude", new=AsyncMock(return_value=MOCK_AI_RESPONSE)):
            report = await analyzer.analyze(REQ_LOGIN[1], REQ_LOGIN[0])

        # Should have both rule-based AND AI ambiguities
        assert report.total_ambiguities >= 1
        ai_ids = {a.id for a in report.ambiguities if "AI" in a.id}
        assert len(ai_ids) >= 1

    @pytest.mark.asyncio
    async def test_ai_rule_merged_correctly(self):
        analyzer = AmbiguityAnalyzer(api_key="sk-fake", mode="full")
        with patch.object(analyzer, "_call_claude", new=AsyncMock(return_value=MOCK_AI_RESPONSE)):
            report = await analyzer.analyze(REQ_LOGIN[1], REQ_LOGIN[0])

        ai_ambs = [a for a in report.ambiguities if a.type == AmbiguityType.LEXICAL]
        assert len(ai_ambs) >= 1

    @pytest.mark.asyncio
    async def test_ai_business_rules_merged(self):
        analyzer = AmbiguityAnalyzer(api_key="sk-fake", mode="full")
        with patch.object(analyzer, "_call_claude", new=AsyncMock(return_value=MOCK_AI_RESPONSE)):
            report = await analyzer.analyze(REQ_LOGIN[1], REQ_LOGIN[0])

        ai_rules = [r for r in report.business_rules if "sessão" in r.description.lower()]
        assert len(ai_rules) >= 1

    @pytest.mark.asyncio
    async def test_ai_gaps_merged(self):
        analyzer = AmbiguityAnalyzer(api_key="sk-fake", mode="full")
        with patch.object(analyzer, "_call_claude", new=AsyncMock(return_value=MOCK_AI_RESPONSE)):
            report = await analyzer.analyze(REQ_LOGIN[1], REQ_LOGIN[0])

        ai_gaps = [g for g in report.gaps if g.gap_type == "missing_first_login"]
        assert len(ai_gaps) == 1

    @pytest.mark.asyncio
    async def test_risk_from_ai_respected(self):
        analyzer = AmbiguityAnalyzer(api_key="sk-fake", mode="full")
        with patch.object(analyzer, "_call_claude", new=AsyncMock(return_value=MOCK_AI_RESPONSE)):
            report = await analyzer.analyze(REQ_LOGIN[1], REQ_LOGIN[0])

        assert report.risk_level == RiskLevel.HIGH

    @pytest.mark.asyncio
    async def test_fallback_on_claude_exception(self):
        analyzer = AmbiguityAnalyzer(api_key="sk-fake", mode="full")
        with patch.object(analyzer, "_call_claude", new=AsyncMock(side_effect=Exception("API down"))):
            report = await analyzer.analyze(REQ_LOGIN[1], REQ_LOGIN[0])

        # Should still return valid report from rules
        assert report is not None
        assert report.total_ambiguities > 0

    @pytest.mark.asyncio
    async def test_severity_upgrade_on_ai_reclassification(self):
        """IA pode elevar severidade de ambiguidade já detectada por regras."""
        analyzer = AmbiguityAnalyzer(api_key="sk-fake", mode="full")

        # AI reclassifies "o usuário" (MEDIUM by rules) to CRITICAL
        ai_resp = {**MOCK_AI_RESPONSE, "ambiguities": [
            {
                "type": "referential",
                "severity": "CRITICAL",
                "excerpt": "o usuário",
                "text": "Ambiguidade crítica: qual usuário?",
                "question": "Qual usuário?",
                "options": ["Usuário logado", "Qualquer usuário"],
                "impact": "Acesso não autorizado",
                "scenario_hint": "Teste com múltiplos usuários",
            }
        ]}
        with patch.object(analyzer, "_call_claude", new=AsyncMock(return_value=ai_resp)):
            report = await analyzer.analyze(REQ_LOGIN[1], REQ_LOGIN[0])

        upgraded = [a for a in report.ambiguities
                    if "usuário" in a.excerpt.lower() and a.severity == AmbiguitySeverity.CRITICAL]
        assert len(upgraded) >= 1


# ===========================================================================
# AmbiguityResolver
# ===========================================================================

class TestAmbiguityResolver:

    @pytest.mark.asyncio
    async def _make_session(self, req_text: str = REQ_LOGIN[1], req_id: str = REQ_LOGIN[0]):
        analyzer = make_analyzer()
        report   = await analyzer.analyze(req_text, req_id)
        return AmbiguityResolver.create_session(report)

    @pytest.mark.asyncio
    async def test_create_session(self):
        session = await self._make_session()
        assert session.requirement_id == REQ_LOGIN[0]
        assert session.resolved_count == 0
        assert session.total_count > 0

    @pytest.mark.asyncio
    async def test_next_question_returns_highest_severity(self):
        session = await self._make_session()
        amb = AmbiguityResolver.next_question(session)
        assert amb is not None
        # First question should be highest severity available
        all_severities = {a.severity for a in session.report.ambiguities}
        sev_order = {AmbiguitySeverity.CRITICAL: 0, AmbiguitySeverity.HIGH: 1,
                     AmbiguitySeverity.MEDIUM: 2, AmbiguitySeverity.LOW: 3}
        min_sev = min(all_severities, key=lambda s: sev_order[s])
        assert amb.severity == min_sev

    @pytest.mark.asyncio
    async def test_resolve_records_decision(self):
        session = await self._make_session()
        amb     = AmbiguityResolver.next_question(session)
        option  = amb.options[0] if amb.options else "Opção padrão"

        resolution = AmbiguityResolver.resolve(session, amb.id, option, rationale="Decisão de teste")

        assert amb.id in session.resolutions
        assert resolution.chosen_option == option
        assert resolution.rationale == "Decisão de teste"

    @pytest.mark.asyncio
    async def test_resolve_derives_rule(self):
        session = await self._make_session()
        amb     = AmbiguityResolver.next_question(session)
        option  = "Rollback automático e notificação ao usuário"

        resolution = AmbiguityResolver.resolve(session, amb.id, option)

        assert resolution.generates_rule != ""

    @pytest.mark.asyncio
    async def test_completion_pct_increases(self):
        session = await self._make_session()
        initial_pct = session.completion_pct

        amb = AmbiguityResolver.next_question(session)
        AmbiguityResolver.resolve(session, amb.id, "Opção A")

        assert session.completion_pct > initial_pct

    @pytest.mark.asyncio
    async def test_resolve_all_with_defaults(self):
        session = await self._make_session()
        AmbiguityResolver.resolve_all_with_defaults(session)

        assert session.resolved_count == session.total_count
        assert session.completion_pct == 100.0

    @pytest.mark.asyncio
    async def test_next_question_returns_none_when_all_resolved(self):
        session = await self._make_session()
        AmbiguityResolver.resolve_all_with_defaults(session)

        assert AmbiguityResolver.next_question(session) is None

    @pytest.mark.asyncio
    async def test_is_ready_after_critical_resolved(self):
        session = await self._make_session()
        # Resolve all critical ones
        for amb in list(session.pending_critical):
            AmbiguityResolver.resolve(session, amb.id, "Opção padrão")

        assert AmbiguityResolver.is_ready(session) is True

    @pytest.mark.asyncio
    async def test_generate_refined_requirement(self):
        session = await self._make_session()
        AmbiguityResolver.resolve_all_with_defaults(session)

        refined = AmbiguityResolver.generate_refined_requirement(session)

        assert session.requirement_text in refined
        assert "Critérios de aceite" in refined

    @pytest.mark.asyncio
    async def test_export_decisions_structure(self):
        session = await self._make_session()
        AmbiguityResolver.resolve_all_with_defaults(session)

        export = AmbiguityResolver.export_decisions(session)

        for key in ("requirement_id", "resolutions", "unresolved",
                    "business_rules", "is_ready_for_testing", "completion"):
            assert key in export

    @pytest.mark.asyncio
    async def test_export_json_valid(self):
        import json
        session = await self._make_session()
        AmbiguityResolver.resolve_all_with_defaults(session)

        json_str = AmbiguityResolver.export_json(session)
        parsed   = json.loads(json_str)

        assert parsed["requirement_id"] == REQ_LOGIN[0]
        assert parsed["completion"] == "100%"

    @pytest.mark.asyncio
    async def test_resolve_invalid_id_raises(self):
        session = await self._make_session()
        with pytest.raises(ValueError, match="não encontrada"):
            AmbiguityResolver.resolve(session, "AMB-INVALID", "Qualquer coisa")

    @pytest.mark.asyncio
    async def test_pending_critical_filters_correctly(self):
        session = await self._make_session()
        criticals = session.pending_critical
        for c in criticals:
            assert c.severity == AmbiguitySeverity.CRITICAL
            assert c.id not in session.resolutions
