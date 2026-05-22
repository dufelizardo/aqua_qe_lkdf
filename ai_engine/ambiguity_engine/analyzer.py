"""
ai_engine/ambiguity_engine/analyzer.py
AQuA-QE LKDF — Ambiguity Engine: AI Analyzer

Camada de IA sobre o RuleBasedDetector.
Claude lê o requisito + os padrões detectados e:
  - Identifica ambiguidades não capturáveis por regex
  - Classifica a severidade com raciocínio contextual
  - Gera perguntas de clarificação precisas para o PO
  - Extrai regras de negócio implícitas profundas
  - Propõe scenarios de teste para cada ambiguidade
  - Calcula o risco geral do requisito
"""
from __future__ import annotations

import json
import os
from typing import Any
from uuid import uuid4

import structlog

from ai_engine.ambiguity_engine.detector import RuleBasedDetector
from ai_engine.ambiguity_engine.models import (
    Ambiguity,
    AmbiguityReport,
    AmbiguitySeverity,
    AmbiguityType,
    BusinessRule,
    CoverageGap,
    RiskLevel,
)

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
Você é o AQuA-QE LKDF Ambiguity Analyzer — especialista em Engenharia de Requisitos \
e Análise de Qualidade de Software.

Sua tarefa: analisar requisitos em linguagem natural e identificar TODAS as ambiguidades \
que podem causar implementação incorreta, testes inadequados ou falhas em produção.

TIPOS DE AMBIGUIDADE:
  lexical      → palavra com múltiplos significados no domínio
  referential  → pronome/artigo assume instância única quando há múltiplas
  scope        → fronteira do comportamento não está clara
  implicit     → caminho de falha, exceção ou precondição omitida
  temporal     → timing, ordenação ou deadline não especificados
  quantitative → quantidade, limite ou threshold sem valor numérico

SEVERIDADES:
  CRITICAL → bloqueia implementação correta; requisito não testável sem resolução
  HIGH     → alto risco de interpretação divergente entre equipes
  MEDIUM   → importante mas contornável com convenção; deve ser documentado
  LOW      → cosmético ou preferência; baixo impacto

REGRAS DE ANÁLISE:
  1. Seja específico: aponte o TRECHO EXATO que é ambíguo, não o requisito todo
  2. Para cada ambiguidade, liste as interpretações POSSÍVEIS (pelo menos 2)
  3. Gere PERGUNTAS PRECISAS para o Product Owner — não retóricas
  4. Identifique regras de negócio NÃO ESCRITAS mas implícitas no domínio
  5. Detecte gaps de cobertura (o que NÃO está descrito mas deveria estar)
  6. O risco geral é HIGH se há qualquer CRITICAL; MEDIUM se há HIGH; LOW se só MEDIUM/LOW

Responda SOMENTE em JSON válido, sem markdown:
{
  "ambiguities": [
    {
      "type": "lexical|referential|scope|implicit|temporal|quantitative",
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "excerpt": "trecho exato do requisito",
      "text": "descrição concisa da ambiguidade",
      "question": "pergunta precisa para o PO resolver a ambiguidade",
      "options": ["interpretação A", "interpretação B"],
      "impact": "impacto se não resolvida",
      "scenario_hint": "cenário de teste sugerido para cobrir a ambiguidade"
    }
  ],
  "business_rules": [
    {
      "description": "regra implícita extraída",
      "entities": ["entidade1"],
      "conditions": ["condição"],
      "outcomes": ["resultado"],
      "source": "explicit|inferred|assumed",
      "confidence": 0.9
    }
  ],
  "gaps": [
    {
      "description": "o que falta no requisito",
      "gap_type": "missing_error_path|missing_actor|missing_edge_case|...",
      "priority": "CRITICAL|HIGH|MEDIUM|LOW",
      "suggested_scenario": "como testar este gap"
    }
  ],
  "clarifying_questions": [
    "Pergunta direta ao PO sobre ponto não resolvido"
  ],
  "recommendations": [
    "Recomendação concreta para melhorar o requisito"
  ],
  "risk_level": "HIGH|MEDIUM|LOW"
}
"""


# ---------------------------------------------------------------------------
# Ambiguity Analyzer
# ---------------------------------------------------------------------------

class AmbiguityAnalyzer:
    """
    Analisador de ambiguidade com duas camadas:
      1. RuleBasedDetector  — padrões linguísticos, offline, zero custo
      2. Claude             — reasoning semântico, detecta o que regex não captura

    Modos:
      full       → regras + Claude (produção)
      rules_only → só RuleBasedDetector (testes, offline)
      ai_only    → só Claude (máxima precisão, maior custo)
    """

    def __init__(
        self,
        api_key: str | None = None,
        model:   str        = "claude-sonnet-4-20250514",
        mode:    str        = "full",
    ) -> None:
        self.api_key  = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model    = model
        self.mode     = mode
        self._detector = RuleBasedDetector()
        self._client:  Any = None

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    async def analyze(
        self,
        requirement_text: str,
        requirement_id:   str = "REQ-AUTO",
        domain_context:   str = "",
    ) -> AmbiguityReport:
        """
        Análise completa de ambiguidade de um requisito.

        Args:
            requirement_text: Texto do requisito
            requirement_id:   ID de rastreabilidade
            domain_context:   Contexto adicional do domínio (ex: "sistema bancário")
        """
        log.info("ambiguity_analyze_start", req_id=requirement_id, mode=self.mode)

        # 1. Regras determinísticas (sempre executadas)
        rule_ambiguities = self._detector.detect(requirement_text)
        rule_rules       = self._detector.extract_rules(requirement_text)
        rule_gaps        = self._detector.identify_gaps(requirement_text)

        # 2. IA (se habilitada)
        ai_data: dict[str, Any] = {}
        if self.mode in ("full", "ai_only") and self.api_key:
            try:
                ai_data = await self._call_claude(
                    requirement_text, requirement_id, domain_context, rule_ambiguities
                )
            except Exception as exc:
                log.warning("ambiguity_analyzer_fallback", error=str(exc))

        # 3. Merge: IA enriquece e complementa as regras
        all_ambiguities = self._merge_ambiguities(rule_ambiguities, ai_data.get("ambiguities", []))
        all_rules       = self._merge_rules(rule_rules, ai_data.get("business_rules", []))
        all_gaps        = self._merge_gaps(rule_gaps, ai_data.get("gaps", []))
        questions       = ai_data.get("clarifying_questions", self._fallback_questions(rule_ambiguities))
        recommendations = ai_data.get("recommendations", self._fallback_recommendations(rule_gaps))
        risk            = self._compute_risk(ai_data.get("risk_level"), all_ambiguities)

        report = AmbiguityReport(
            requirement_id=requirement_id,
            requirement_text=requirement_text,
            risk_level=risk,
            ambiguities=all_ambiguities,
            business_rules=all_rules,
            gaps=all_gaps,
            clarifying_questions=questions,
            recommendations=recommendations,
            raw_ai=ai_data,
        )

        log.info(
            "ambiguity_analyze_done",
            req_id=requirement_id,
            ambiguities=report.total_ambiguities,
            critical=report.critical_count,
            risk=report.risk_level,
            score=f"{report.ambiguity_score:.2f}",
        )
        return report

    async def analyze_batch(
        self,
        requirements: list[tuple[str, str]],   # [(req_id, text), ...]
        domain_context: str = "",
    ) -> list[AmbiguityReport]:
        """Analisa múltiplos requisitos em sequência."""
        results: list[AmbiguityReport] = []
        for req_id, text in requirements:
            report = await self.analyze(text, req_id, domain_context)
            results.append(report)
        return results

    def analyze_sync(
        self,
        requirement_text: str,
        requirement_id:   str = "REQ-AUTO",
        domain_context:   str = "",
    ) -> AmbiguityReport:
        """Versão síncrona para uso em contextos não-async."""
        import asyncio
        return asyncio.run(self.analyze(requirement_text, requirement_id, domain_context))

    # ------------------------------------------------------------------
    # Claude call
    # ------------------------------------------------------------------

    async def _call_claude(
        self,
        text:           str,
        req_id:         str,
        domain_context: str,
        rule_findings:  list[Ambiguity],
    ) -> dict[str, Any]:
        try:
            client = self._get_client()
        except RuntimeError as exc:
            log.warning("claude_unavailable", error=str(exc))
            return {}

        # Feed rule findings to Claude to avoid re-detection and focus on gaps
        rules_summary = ""
        if rule_findings:
            rule_lines = "\n".join(
                f"  - [{a.type.value.upper()}] '{a.excerpt}': {a.text}"
                for a in rule_findings[:6]
            )
            rules_summary = f"\n\nPadrões já detectados automaticamente (NÃO repita, foque nos não detectados):\n{rule_lines}"

        user_msg = (
            f"Requisito [{req_id}]: \"{text}\""
            + (f"\n\nContexto de domínio: {domain_context}" if domain_context else "")
            + rules_summary
            + "\n\nAnalise ambiguidades ADICIONAIS não cobertas pelos padrões acima."
        )

        try:
            response = self._get_client().messages.create(
                model=self.model,
                max_tokens=2000,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw  = response.content[0].text
            clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            return json.loads(clean)

        except json.JSONDecodeError as exc:
            log.warning("ambiguity_json_error", error=str(exc))
            return {}
        except Exception as exc:
            log.error("ambiguity_claude_error", error=str(exc))
            return {}

    # ------------------------------------------------------------------
    # Merge strategies
    # ------------------------------------------------------------------

    def _merge_ambiguities(
        self,
        rule_findings: list[Ambiguity],
        ai_raw:        list[dict],
    ) -> list[Ambiguity]:
        """
        Combina ambiguidades de regras e IA.
        IA tem prioridade em severidade; regras cobrem o que IA não detecta.
        """
        result = list(rule_findings)
        seen_excerpts = {a.excerpt.lower()[:30] for a in result}

        for item in ai_raw:
            excerpt = item.get("excerpt", "")[:30].lower()
            if excerpt in seen_excerpts:
                # Atualiza severidade se IA classifica mais alto
                for existing in result:
                    if existing.excerpt.lower()[:30] == excerpt:
                        ai_sev = self._parse_severity(item.get("severity", "MEDIUM"))
                        rule_sev_ord = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
                        if rule_sev_ord.get(ai_sev, 0) > rule_sev_ord.get(existing.severity, 0):
                            existing.severity = ai_sev
                        if item.get("options"):
                            existing.options = item["options"]
                        if item.get("scenario_hint"):
                            existing.scenario_hint = item["scenario_hint"]
                continue

            seen_excerpts.add(excerpt)
            try:
                result.append(Ambiguity(
                    id=f"AMB-AI-{str(uuid4())[:6].upper()}",
                    type=self._parse_type(item.get("type", "scope")),
                    severity=self._parse_severity(item.get("severity", "MEDIUM")),
                    text=item.get("text", ""),
                    question=item.get("question", ""),
                    excerpt=item.get("excerpt", ""),
                    options=item.get("options", []),
                    impact=item.get("impact", ""),
                    scenario_hint=item.get("scenario_hint", ""),
                ))
            except Exception as exc:
                log.warning("merge_ambiguity_error", error=str(exc))

        # Sort: CRITICAL → HIGH → MEDIUM → LOW
        order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        result.sort(key=lambda a: order.get(a.severity, 4))
        return result

    def _merge_rules(
        self,
        rule_rules: list[BusinessRule],
        ai_raw:     list[dict],
    ) -> list[BusinessRule]:
        result = list(rule_rules)
        seen   = {r.description.lower()[:40] for r in result}

        for item in ai_raw:
            desc = item.get("description", "")
            if desc.lower()[:40] in seen:
                continue
            seen.add(desc.lower()[:40])
            try:
                result.append(BusinessRule(
                    id=f"BR-AI-{str(uuid4())[:6].upper()}",
                    description=desc,
                    entities=item.get("entities", []),
                    conditions=item.get("conditions", []),
                    outcomes=item.get("outcomes", []),
                    source=item.get("source", "inferred"),
                    confidence=float(item.get("confidence", 0.8)),
                ))
            except Exception as exc:
                log.warning("merge_rule_error", error=str(exc))
        return result

    def _merge_gaps(
        self,
        rule_gaps: list[CoverageGap],
        ai_raw:    list[dict],
    ) -> list[CoverageGap]:
        result = list(rule_gaps)
        seen   = {g.gap_type for g in result}

        for item in ai_raw:
            gap_type = item.get("gap_type", "unknown")
            if gap_type in seen:
                continue
            seen.add(gap_type)
            try:
                result.append(CoverageGap(
                    id=f"GAP-AI-{str(uuid4())[:6].upper()}",
                    description=item.get("description", ""),
                    gap_type=gap_type,
                    priority=item.get("priority", "MEDIUM"),
                    suggested_scenario=item.get("suggested_scenario", ""),
                ))
            except Exception as exc:
                log.warning("merge_gap_error", error=str(exc))
        return result

    # ------------------------------------------------------------------
    # Risk computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_risk(
        ai_risk:     str | None,
        ambiguities: list[Ambiguity],
    ) -> RiskLevel:
        if ai_risk:
            try:
                return RiskLevel(ai_risk.upper())
            except ValueError:
                pass

        # Fallback: compute from ambiguities
        has_critical = any(a.severity == AmbiguitySeverity.CRITICAL for a in ambiguities)
        has_high     = any(a.severity == AmbiguitySeverity.HIGH     for a in ambiguities)

        if has_critical:   return RiskLevel.HIGH
        if has_high:       return RiskLevel.MEDIUM
        return RiskLevel.LOW

    # ------------------------------------------------------------------
    # Fallbacks (sem IA)
    # ------------------------------------------------------------------

    @staticmethod
    def _fallback_questions(ambiguities: list[Ambiguity]) -> list[str]:
        return [a.question for a in ambiguities if a.severity in (
            AmbiguitySeverity.CRITICAL, AmbiguitySeverity.HIGH
        )][:5]

    @staticmethod
    def _fallback_recommendations(gaps: list[CoverageGap]) -> list[str]:
        recs: list[str] = []
        for gap in gaps:
            if gap.gap_type == "missing_error_path":
                recs.append("Adicione tratamento explícito para todos os caminhos de erro.")
            elif gap.gap_type == "missing_authorization":
                recs.append("Especifique quais papéis/perfis têm permissão para cada operação.")
            elif gap.gap_type == "missing_timeout":
                recs.append("Defina SLAs numéricos para cada operação crítica.")
            elif gap.gap_type == "missing_concurrency":
                recs.append("Documente o comportamento esperado em acessos concorrentes.")
        return recs

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_type(raw: str) -> AmbiguityType:
        try:
            return AmbiguityType(raw.lower())
        except ValueError:
            return AmbiguityType.SCOPE

    @staticmethod
    def _parse_severity(raw: str) -> AmbiguitySeverity:
        try:
            return AmbiguitySeverity(raw.upper())
        except ValueError:
            return AmbiguitySeverity.MEDIUM

    def _get_client(self) -> Any:
        if not self._client:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                raise RuntimeError("pip install anthropic")
        return self._client
