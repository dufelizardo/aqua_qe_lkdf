"""
ai_engine/ambiguity_engine/resolver.py
AQuA-QE LKDF — Ambiguity Engine: Resolver

Responsável por:
  - Gerenciar o ciclo de clarificação interativo com o analista/PO
  - Registrar respostas para cada ambiguidade
  - Verificar se o requisito está pronto para teste
  - Gerar versão refinada do requisito com as ambiguidades resolvidas
  - Exportar o relatório final com decisões documentadas
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import structlog

from ai_engine.ambiguity_engine.models import (
    Ambiguity,
    AmbiguityReport,
    AmbiguitySeverity,
    RiskLevel,
)

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Resolution tracking
# ---------------------------------------------------------------------------

@dataclass
class AmbiguityResolution:
    """Registro de resolução de uma ambiguidade pelo analista."""
    ambiguity_id:   str
    ambiguity_text: str
    chosen_option:  str          # opção escolhida ou resposta livre
    rationale:      str = ""     # justificativa da decisão
    resolved_by:    str = ""     # quem resolveu
    resolved_at:    datetime = field(default_factory=datetime.utcnow)
    generates_rule: str = ""     # regra de negócio derivada da resolução


@dataclass
class ResolutionSession:
    """Sessão de clarificação de um requisito."""
    requirement_id:   str
    requirement_text: str
    report:           AmbiguityReport
    resolutions:      dict[str, AmbiguityResolution] = field(default_factory=dict)
    started_at:       datetime = field(default_factory=datetime.utcnow)
    notes:            list[str] = field(default_factory=list)

    @property
    def pending_critical(self) -> list[Ambiguity]:
        return [
            a for a in self.report.ambiguities
            if a.severity == AmbiguitySeverity.CRITICAL
            and a.id not in self.resolutions
        ]

    @property
    def pending_high(self) -> list[Ambiguity]:
        return [
            a for a in self.report.ambiguities
            if a.severity == AmbiguitySeverity.HIGH
            and a.id not in self.resolutions
        ]

    @property
    def resolved_count(self) -> int:
        return len(self.resolutions)

    @property
    def total_count(self) -> int:
        return len(self.report.ambiguities)

    @property
    def is_ready_for_testing(self) -> bool:
        return len(self.pending_critical) == 0

    @property
    def completion_pct(self) -> float:
        if not self.total_count:
            return 100.0
        return self.resolved_count / self.total_count * 100


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

class AmbiguityResolver:
    """
    Gerencia o ciclo de vida de resolução de ambiguidades.

    Fluxo típico:
      1. `create_session(report)` → abre sessão
      2. `next_question(session)` → retorna próxima ambiguidade não resolvida
      3. `resolve(session, amb_id, answer)` → registra resposta
      4. `is_ready(session)` → verifica se pode prosseguir para testes
      5. `generate_refined_requirement(session)` → gera texto melhorado
      6. `export_decisions(session)` → exporta JSON auditável
    """

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    @staticmethod
    def create_session(report: AmbiguityReport) -> ResolutionSession:
        return ResolutionSession(
            requirement_id=report.requirement_id,
            requirement_text=report.requirement_text,
            report=report,
        )

    @staticmethod
    def next_question(session: ResolutionSession) -> Ambiguity | None:
        """
        Retorna a próxima ambiguidade a ser resolvida.
        Prioridade: CRITICAL → HIGH → MEDIUM → LOW.
        """
        order = {
            AmbiguitySeverity.CRITICAL: 0,
            AmbiguitySeverity.HIGH:     1,
            AmbiguitySeverity.MEDIUM:   2,
            AmbiguitySeverity.LOW:      3,
        }
        pending = [
            a for a in session.report.ambiguities
            if a.id not in session.resolutions
        ]
        if not pending:
            return None
        return sorted(pending, key=lambda a: order.get(a.severity, 4))[0]

    @staticmethod
    def resolve(
        session:       ResolutionSession,
        ambiguity_id:  str,
        chosen_option: str,
        rationale:     str = "",
        resolved_by:   str = "analyst",
    ) -> AmbiguityResolution:
        """Registra a resolução de uma ambiguidade."""
        amb = next((a for a in session.report.ambiguities if a.id == ambiguity_id), None)
        if not amb:
            raise ValueError(f"Ambiguidade '{ambiguity_id}' não encontrada na sessão.")

        rule = AmbiguityResolver._derive_rule(amb, chosen_option)

        resolution = AmbiguityResolution(
            ambiguity_id=ambiguity_id,
            ambiguity_text=amb.text,
            chosen_option=chosen_option,
            rationale=rationale,
            resolved_by=resolved_by,
            generates_rule=rule,
        )
        session.resolutions[ambiguity_id] = resolution
        log.info(
            "ambiguity_resolved",
            id=ambiguity_id,
            severity=amb.severity,
            by=resolved_by,
        )
        return resolution

    @staticmethod
    def resolve_all_with_defaults(session: ResolutionSession) -> None:
        """
        Resolve todas as ambiguidades pendentes com a primeira opção disponível.
        Útil para testes e demo.
        """
        for amb in session.report.ambiguities:
            if amb.id not in session.resolutions:
                default = amb.options[0] if amb.options else "Aceitar interpretação mais conservadora"
                AmbiguityResolver.resolve(
                    session, amb.id, default,
                    rationale="Resolução automática (padrão conservador)",
                    resolved_by="system",
                )

    @staticmethod
    def is_ready(session: ResolutionSession) -> bool:
        return session.is_ready_for_testing

    # ------------------------------------------------------------------
    # Requirement refinement
    # ------------------------------------------------------------------

    @staticmethod
    def generate_refined_requirement(session: ResolutionSession) -> str:
        """
        Gera uma versão refinada do requisito incorporando as resoluções.
        Adiciona clarificações como critérios de aceite explícitos.
        """
        lines: list[str] = [
            f"**Requisito refinado — {session.requirement_id}**",
            "",
            session.requirement_text,
            "",
            "**Critérios de aceite adicionais (derivados da análise de ambiguidade):**",
        ]

        for resolution in session.resolutions.values():
            if resolution.generates_rule:
                lines.append(f"- {resolution.generates_rule}")

        lines.extend(["", "**Regras de negócio explícitas:**"])
        for rule in session.report.business_rules[:5]:
            lines.append(f"- {rule.description}")

        lines.extend(["", "**Gaps a documentar:**"])
        for gap in session.report.gaps:
            lines.append(f"- {gap.description} → {gap.suggested_scenario}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    @staticmethod
    def export_decisions(session: ResolutionSession) -> dict[str, Any]:
        """Exporta todas as decisões em formato JSON auditável."""
        return {
            "requirement_id":     session.requirement_id,
            "requirement_text":   session.requirement_text,
            "session_started_at": session.started_at.isoformat(),
            "exported_at":        datetime.utcnow().isoformat(),
            "risk_level":         session.report.risk_level,
            "ambiguity_score":    round(session.report.ambiguity_score, 2),
            "completion":         f"{session.completion_pct:.0f}%",
            "is_ready_for_testing": session.is_ready_for_testing,
            "resolutions": [
                {
                    "id":            r.ambiguity_id,
                    "ambiguity":     r.ambiguity_text,
                    "decision":      r.chosen_option,
                    "rationale":     r.rationale,
                    "resolved_by":   r.resolved_by,
                    "resolved_at":   r.resolved_at.isoformat(),
                    "derived_rule":  r.generates_rule,
                }
                for r in session.resolutions.values()
            ],
            "unresolved": [
                {
                    "id":       a.id,
                    "type":     a.type,
                    "severity": a.severity,
                    "text":     a.text,
                    "question": a.question,
                }
                for a in session.report.ambiguities
                if a.id not in session.resolutions
            ],
            "business_rules": [
                {"description": r.description, "confidence": r.confidence}
                for r in session.report.business_rules
            ],
            "notes": session.notes,
        }

    @staticmethod
    def export_json(session: ResolutionSession) -> str:
        return json.dumps(
            AmbiguityResolver.export_decisions(session),
            indent=2,
            ensure_ascii=False,
            default=str,
        )

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_rule(amb: Ambiguity, chosen_option: str) -> str:
        """Deriva uma regra de negócio da resolução de uma ambiguidade."""
        from ai_engine.ambiguity_engine.models import AmbiguityType

        if amb.type == AmbiguityType.IMPLICIT:
            return f"Em caso de falha em '{amb.excerpt}': {chosen_option}"
        if amb.type == AmbiguityType.TEMPORAL:
            return f"Tempo máximo para '{amb.excerpt}': {chosen_option}"
        if amb.type == AmbiguityType.QUANTITATIVE:
            return f"Limite numérico para '{amb.excerpt}': {chosen_option}"
        if amb.type == AmbiguityType.SCOPE:
            return f"Escopo de '{amb.excerpt}': {chosen_option}"
        if amb.type == AmbiguityType.REFERENTIAL:
            return f"'{amb.excerpt}' refere-se a: {chosen_option}"
        return f"Decisão para '{amb.excerpt}': {chosen_option}"
