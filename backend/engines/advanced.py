"""
AQuA-QE LKDF — Fase 2
Engines Avançadas: Risk, Coverage, Inference, Synthesis,
                   Consistency, Impact, Compliance  (§6.6 – §6.12)
Cada engine orquestra Gateway + PromptManager e retorna resultado estruturado.
"""
from __future__ import annotations
import re, json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from enum import Enum

from backend.gateway.core import gateway, AIGateway
from backend.gateway.prompt_manager import prompt_manager, PromptType
from backend.models.schemas import (
    GatewayRequest, EngineType, DeploymentMode, ProviderName
)


# ──────────────────────────────────────────────
# Shared result container
# ──────────────────────────────────────────────

@dataclass
class EngineResult:
    engine: str
    success: bool
    content: str
    structured: dict[str, Any] = field(default_factory=dict)
    provider_used: str = ""
    model_used: str = ""
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    fallback_used: bool = False
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    error: Optional[str] = None


# ──────────────────────────────────────────────
# Base Engine
# ──────────────────────────────────────────────

class BaseEngine:
    engine_type: EngineType
    prompt_type: PromptType
    default_max_tokens: int = 2500
    default_temperature: float = 0.2

    def __init__(self, gw: AIGateway = None):
        self.gw = gw or gateway

    async def run(
        self,
        content: str,
        variables: dict[str, str] = {},
        deployment_mode: DeploymentMode = DeploymentMode.CLOUD,
        force_provider: Optional[ProviderName] = None,
    ) -> EngineResult:
        # Build prompt via PromptManager
        template = prompt_manager.get_by_type(self.prompt_type)
        if template:
            system, user = prompt_manager.render(template.id, {**variables, "input": content})
        else:
            system, user = "", content

        req = GatewayRequest(
            engine=self.engine_type,
            messages=[{"role": "user", "content": user or content}],
            system_prompt=system,
            max_tokens=self.default_max_tokens,
            temperature=self.default_temperature,
            deployment_mode=deployment_mode,
            force_provider=force_provider,
        )
        resp = await self.gw.execute(req)

        result = EngineResult(
            engine=self.engine_type.value,
            success=resp.status.value in ("success", "fallback"),
            content=resp.content,
            provider_used=resp.provider_used.value if hasattr(resp.provider_used, 'value') else str(resp.provider_used),
            model_used=resp.model_used,
            latency_ms=resp.latency_ms,
            cost_usd=resp.cost_usd,
            fallback_used=resp.fallback_used,
            error=resp.error_message,
        )
        result.structured = self._parse(resp.content)

        # Log no PromptManager
        if template:
            prompt_manager.log_execution(
                template.id, result.provider_used, result.model_used,
                resp.input_tokens, resp.output_tokens,
                resp.latency_ms, resp.cost_usd, result.success,
            )
        return result

    def _parse(self, content: str) -> dict:
        """Override para extração estruturada específica de cada engine."""
        return {"raw": content}

    # ── Helpers de parsing ──────────────────

    @staticmethod
    def _extract_rtm_rows(text: str) -> list[dict]:
        rows = []
        block = re.search(r'```rtm\n([\s\S]*?)```', text)
        if not block:
            return rows
        for line in block.group(1).strip().split('\n'):
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 8:
                rows.append({
                    "id": parts[0], "rn": parts[1], "ca": parts[2],
                    "description": parts[3], "risk": parts[4],
                    "gap": parts[5], "priority": parts[6], "automatable": parts[7],
                })
        return rows

    @staticmethod
    def _extract_section(text: str, heading: str) -> str:
        pattern = rf'###\s*{re.escape(heading)}(.*?)(?=###|\Z)'
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _extract_gherkin(text: str) -> str:
        m = re.search(r'```gherkin\n([\s\S]*?)```', text)
        return m.group(1) if m else ""

    @staticmethod
    def _extract_list_items(text: str) -> list[str]:
        return [m.strip('- ').strip() for m in re.findall(r'^[-•*]\s+(.+)$', text, re.MULTILINE)]

    @staticmethod
    def _extract_risk_level(text: str) -> str:
        text_l = text.lower()
        if 'alto' in text_l or 'crítico' in text_l or 'high' in text_l:
            return "Alto"
        if 'médio' in text_l or 'médio' in text_l or 'medium' in text_l:
            return "Médio"
        return "Baixo"


# ──────────────────────────────────────────────
# Risk Engine  (§6.6)
# ──────────────────────────────────────────────

class RiskEngine(BaseEngine):
    engine_type = EngineType.RISK
    prompt_type = PromptType.RISK_ANALYSIS
    default_max_tokens = 2000

    def _parse(self, content: str) -> dict:
        rows = self._extract_rtm_rows(content)
        risks_raw = self._extract_section(content, "Matriz de Risco")
        critical = [r for r in rows if r["risk"].lower() in ("alto", "crítico")]
        medium   = [r for r in rows if "médio" in r["risk"].lower()]
        low      = [r for r in rows if "baixo" in r["risk"].lower()]
        return {
            "rtm_rows": rows,
            "total_risks": len(rows),
            "critical": len(critical),
            "medium": len(medium),
            "low": len(low),
            "overall_risk": "Alto" if critical else ("Médio" if medium else "Baixo"),
            "risk_matrix_text": risks_raw,
            "recommendations": self._extract_section(content, "Recomendações de Priorização"),
        }


# ──────────────────────────────────────────────
# Coverage Validation Engine  (§6.7)
# ──────────────────────────────────────────────

class CoverageEngine(BaseEngine):
    engine_type = EngineType.COVERAGE
    prompt_type = PromptType.COVERAGE
    default_max_tokens = 2500

    def _parse(self, content: str) -> dict:
        rows = self._extract_rtm_rows(content)
        # Extrai % de cobertura mencionadas no texto
        percentages = re.findall(r'(\d{1,3})%', content)
        func_cov = int(percentages[0]) if percentages else 0
        risk_cov = int(percentages[1]) if len(percentages) > 1 else 0
        comp_cov = int(percentages[2]) if len(percentages) > 2 else 0
        gaps = self._extract_section(content, "Gaps")
        return {
            "rtm_rows": rows,
            "functional_coverage": func_cov,
            "risk_coverage": risk_cov,
            "compliance_coverage": comp_cov,
            "overall_coverage": round((func_cov + risk_cov + comp_cov) / 3) if percentages else 0,
            "black_box": self._extract_section(content, "Caixa Preta"),
            "white_box": self._extract_section(content, "Caixa Branca"),
            "gaps": self._extract_list_items(gaps) if gaps else [],
        }


# ──────────────────────────────────────────────
# Inference Engine  (§6.8)
# ──────────────────────────────────────────────

class InferenceEngine(BaseEngine):
    engine_type = EngineType.INFERENCE
    prompt_type = PromptType.INFERENCE
    default_max_tokens = 2000

    def _parse(self, content: str) -> dict:
        rows = self._extract_rtm_rows(content)
        alt_flows = self._extract_section(content, "Fluxos Alternativos")
        exceptions = self._extract_section(content, "Cenários de Exceção")
        implicit   = self._extract_section(content, "Testes Implícitos Sugeridos")
        return {
            "rtm_rows": rows,
            "inferred_count": len(rows),
            "alternative_flows": self._extract_list_items(alt_flows),
            "exception_scenarios": self._extract_list_items(exceptions),
            "implicit_tests": implicit,
            "insights": self._extract_section(content, "Insights de Qualidade"),
        }


# ──────────────────────────────────────────────
# Synthesis Engine  (§6.9)
# ──────────────────────────────────────────────

class SynthesisEngine(BaseEngine):
    engine_type = EngineType.SYNTHESIS
    prompt_type = PromptType.REQUIREMENT_ENG    # reutiliza base + instrução de síntese
    default_max_tokens = 2000

    SYNTHESIS_SYSTEM = """Você é o Synthesis Engine do AQuA-QE.
Sua função é consolidar múltiplas análises em uma visão final coerente.
Estruture a síntese com: resumo executivo, pontos críticos, recomendações, próximos passos."""

    async def synthesize(self, analyses: list[str],
                         deployment_mode: DeploymentMode = DeploymentMode.CLOUD) -> EngineResult:
        combined = "\n\n---\n\n".join(analyses)
        content = f"Consolide as seguintes análises em uma visão final:\n\n{combined}"
        req = GatewayRequest(
            engine=self.engine_type,
            messages=[{"role": "user", "content": content}],
            system_prompt=self.SYNTHESIS_SYSTEM,
            max_tokens=self.default_max_tokens,
            deployment_mode=deployment_mode,
        )
        resp = await self.gw.execute(req)
        return EngineResult(
            engine=self.engine_type.value,
            success=resp.status.value in ("success", "fallback"),
            content=resp.content,
            provider_used=str(resp.provider_used),
            model_used=resp.model_used,
            latency_ms=resp.latency_ms,
            cost_usd=resp.cost_usd,
            structured=self._parse(resp.content),
        )

    def _parse(self, content: str) -> dict:
        return {
            "executive_summary": self._extract_section(content, "Resumo Executivo"),
            "critical_points":   self._extract_list_items(
                self._extract_section(content, "Pontos Críticos")),
            "recommendations":   self._extract_list_items(
                self._extract_section(content, "Recomendações")),
            "next_steps":        self._extract_list_items(
                self._extract_section(content, "Próximos Passos")),
        }


# ──────────────────────────────────────────────
# Consistency Engine  (§6.10)
# ──────────────────────────────────────────────

class ConsistencyEngine(BaseEngine):
    engine_type = EngineType.CONSISTENCY
    prompt_type = PromptType.REQUIREMENT_ENG

    CONSISTENCY_SYSTEM = """Você é o Consistency Engine do AQuA-QE.
Detecte contradições, inconsistências e desalinhamentos entre RN e CA.
Seja preciso: cite as RN e CA específicas que conflitam."""

    async def check(self, rns: list[str], cas: list[str],
                    deployment_mode: DeploymentMode = DeploymentMode.CLOUD) -> EngineResult:
        content = (f"Verifique consistência entre:\n\n**Regras de Negócio:**\n"
                   + "\n".join(f"- {r}" for r in rns)
                   + f"\n\n**Critérios de Aceite:**\n"
                   + "\n".join(f"- {c}" for c in cas)
                   + "\n\nIdentifique: contradições, inconsistências, alinhamento e sugestões de correção.")
        req = GatewayRequest(
            engine=self.engine_type,
            messages=[{"role": "user", "content": content}],
            system_prompt=self.CONSISTENCY_SYSTEM,
            max_tokens=1500,
            deployment_mode=deployment_mode,
        )
        resp = await self.gw.execute(req)
        return EngineResult(
            engine=self.engine_type.value,
            success=resp.status.value in ("success", "fallback"),
            content=resp.content,
            provider_used=str(resp.provider_used),
            model_used=resp.model_used,
            latency_ms=resp.latency_ms,
            cost_usd=resp.cost_usd,
            structured=self._parse(resp.content),
        )

    def _parse(self, content: str) -> dict:
        contradictions = self._extract_list_items(
            self._extract_section(content, "Contradições") or
            self._extract_section(content, "Inconsistências"))
        suggestions    = self._extract_list_items(
            self._extract_section(content, "Sugestões"))
        is_consistent  = len(contradictions) == 0
        return {
            "is_consistent": is_consistent,
            "contradictions": contradictions,
            "suggestions": suggestions,
            "alignment_score": 100 - len(contradictions) * 15,
        }


# ──────────────────────────────────────────────
# Impact Analysis Engine  (§6.11)
# ──────────────────────────────────────────────

class ImpactEngine(BaseEngine):
    engine_type = EngineType.IMPACT
    prompt_type = PromptType.REQUIREMENT_ENG

    IMPACT_SYSTEM = """Você é o Impact Analysis Engine do AQuA-QE.
Analise impacto de mudanças em requisitos: identifique cenários afetados,
necessidade de regressão e atualização do RTM."""

    async def analyze(self, change_description: str, existing_rtm: list[dict],
                      deployment_mode: DeploymentMode = DeploymentMode.CLOUD) -> EngineResult:
        rtm_text = "\n".join(f"- {r['id']}: {r.get('description','')}" for r in existing_rtm[:20])
        content  = (f"**Mudança:** {change_description}\n\n"
                    f"**RTM existente:**\n{rtm_text}\n\n"
                    f"Identifique: casos afetados, necessidade de regressão, "
                    f"novos casos necessários e impacto no Quality Score.")
        req = GatewayRequest(
            engine=self.engine_type,
            messages=[{"role": "user", "content": content}],
            system_prompt=self.IMPACT_SYSTEM,
            max_tokens=2000,
            deployment_mode=deployment_mode,
        )
        resp = await self.gw.execute(req)
        return EngineResult(
            engine=self.engine_type.value,
            success=resp.status.value in ("success", "fallback"),
            content=resp.content,
            provider_used=str(resp.provider_used),
            model_used=resp.model_used,
            latency_ms=resp.latency_ms,
            cost_usd=resp.cost_usd,
            structured=self._parse(resp.content),
        )

    def _parse(self, content: str) -> dict:
        affected_ids = re.findall(r'CT-\d+', content)
        new_rows     = self._extract_rtm_rows(content)
        return {
            "affected_test_ids": list(set(affected_ids)),
            "affected_count":    len(set(affected_ids)),
            "regression_needed": len(set(affected_ids)) > 0,
            "new_test_cases":    new_rows,
            "impact_summary":    self._extract_section(content, "Impacto"),
        }


# ──────────────────────────────────────────────
# Compliance Engine  (§6.12)
# ──────────────────────────────────────────────

class ComplianceEngine(BaseEngine):
    engine_type = EngineType.COMPLIANCE
    prompt_type = PromptType.COMPLIANCE
    default_max_tokens = 3000
    default_temperature = 0.1   # compliance precisa de precisão máxima

    def _parse(self, content: str) -> dict:
        rows    = self._extract_rtm_rows(content)
        lgpd    = self._extract_section(content, "LGPD")
        owasp   = self._extract_section(content, "OWASP")
        iso     = self._extract_section(content, "ISO")
        wcag    = self._extract_section(content, "WCAG")
        issues  = re.findall(r'(A0\d|Art\.\s*\d+|WCAG\s*\d[\d.]*)', content)
        return {
            "rtm_rows":        rows,
            "lgpd_section":    lgpd,
            "owasp_section":   owasp,
            "iso_section":     iso,
            "wcag_section":    wcag,
            "issues_found":    list(set(issues)),
            "total_issues":    len(set(issues)),
            "compliance_score": max(0, 100 - len(set(issues)) * 10),
        }


# ──────────────────────────────────────────────
# Engine Registry
# ──────────────────────────────────────────────

class EngineRegistry:
    """Ponto central de acesso a todas as engines avançadas."""

    def __init__(self, gw: AIGateway = None):
        _gw = gw or gateway
        self.risk        = RiskEngine(_gw)
        self.coverage    = CoverageEngine(_gw)
        self.inference   = InferenceEngine(_gw)
        self.synthesis   = SynthesisEngine(_gw)
        self.consistency = ConsistencyEngine(_gw)
        self.impact      = ImpactEngine(_gw)
        self.compliance  = ComplianceEngine(_gw)

    async def run_engine(self, engine_name: str, content: str,
                         variables: dict = {},
                         deployment_mode: DeploymentMode = DeploymentMode.CLOUD,
                         force_provider: Optional[ProviderName] = None) -> EngineResult:
        mapping = {
            "risk":        self.risk,
            "coverage":    self.coverage,
            "inference":   self.inference,
            "synthesis":   self.synthesis,
            "consistency": self.consistency,
            "impact":      self.impact,
            "compliance":  self.compliance,
        }
        engine = mapping.get(engine_name)
        if not engine:
            return EngineResult(engine=engine_name, success=False,
                                content="", error=f"Engine '{engine_name}' não encontrada")
        return await engine.run(content, variables, deployment_mode, force_provider)

    async def full_analysis(self, content: str,
                            deployment_mode: DeploymentMode = DeploymentMode.CLOUD) -> dict:
        """Executa pipeline completo: risk + coverage + inference + compliance → synthesis."""
        import asyncio
        # Paralelo: risk, coverage, inference, compliance
        results = await asyncio.gather(
            self.risk.run(content, {"feature": content, "domain": "sistema"}, deployment_mode),
            self.coverage.run(content, {"feature": content, "existing_tests": ""}, deployment_mode),
            self.inference.run(content, {"context": content}, deployment_mode),
            self.compliance.run(content, {"feature": content, "data_types": "dados pessoais"}, deployment_mode),
            return_exceptions=True,
        )
        valid = [r.content for r in results if isinstance(r, EngineResult) and r.success]
        synthesis_result = await self.synthesis.synthesize(valid, deployment_mode) if valid else None

        engine_results = {
            "risk":        results[0] if isinstance(results[0], EngineResult) else None,
            "coverage":    results[1] if isinstance(results[1], EngineResult) else None,
            "inference":   results[2] if isinstance(results[2], EngineResult) else None,
            "compliance":  results[3] if isinstance(results[3], EngineResult) else None,
            "synthesis":   synthesis_result,
        }
        total_cost = sum(
            r.cost_usd for r in engine_results.values()
            if isinstance(r, EngineResult)
        )
        return {
            "engines": {k: (v.__dict__ if isinstance(v, EngineResult) else None)
                        for k, v in engine_results.items()},
            "total_cost_usd": round(total_cost, 6),
            "engines_executed": len(valid),
        }


# Singleton
engine_registry = EngineRegistry()
