"""
AQuA-QE LKDF — Compliance & Governança Corporativa §38
Motor de análise de conformidade: WCAG 2.1, LGPD, OWASP Top 10, ISO 25010.
Analisa histórias, critérios de aceite e artefatos contra os padrões.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ── Compliance Rules ──────────────────────────────────────────

@dataclass
class ComplianceRule:
    id:          str
    standard:    str      # WCAG | LGPD | OWASP | ISO25010
    code:        str      # e.g. "1.1.1", "Art.9", "A01:2021"
    level:       str      # AA | A | AAA | obrigatório | recomendado
    title:       str
    description: str
    check_fn:    Any      # callable(text) -> bool (True = compliant)
    remediation: str = ""
    severity:    str = "medium"  # low | medium | high | critical


# ── WCAG 2.1 Rules ───────────────────────────────────────────

WCAG_RULES: list[ComplianceRule] = [
    ComplianceRule(
        id="wcag-1.1.1", standard="WCAG", code="1.1.1", level="A",
        title="Conteúdo não textual",
        description="Imagens e ícones devem ter texto alternativo (alt text).",
        check_fn=lambda t: bool(re.search(r'alt\s*=|texto alternativo|alt text|aria-label', t, re.I)),
        remediation="Adicionar critério: 'Toda imagem/ícone deve ter alt text descritivo'.",
        severity="high",
    ),
    ComplianceRule(
        id="wcag-1.4.3", standard="WCAG", code="1.4.3", level="AA",
        title="Contraste mínimo",
        description="Texto deve ter contraste mínimo 4.5:1 (normal) ou 3:1 (grande).",
        check_fn=lambda t: bool(re.search(r'contraste|contrast ratio|4\.5:1|3:1', t, re.I)),
        remediation="Especificar requisito de contraste nos critérios de aceite visuais.",
        severity="high",
    ),
    ComplianceRule(
        id="wcag-2.1.1", standard="WCAG", code="2.1.1", level="A",
        title="Teclado",
        description="Toda funcionalidade deve ser acessível via teclado.",
        check_fn=lambda t: bool(re.search(r'teclado|keyboard|tab\s+order|navegação por teclado', t, re.I)),
        remediation="Adicionar CA: 'Todas as ações devem ser executáveis via teclado (Tab, Enter, Esc)'.",
        severity="high",
    ),
    ComplianceRule(
        id="wcag-2.4.3", standard="WCAG", code="2.4.3", level="A",
        title="Ordem de foco",
        description="Ordem de foco deve ser lógica e coerente com o layout.",
        check_fn=lambda t: bool(re.search(r'foco|focus order|tab\s+index|ordem de navegação', t, re.I)),
        remediation="Especificar ordem de foco nos critérios de aceite de formulários.",
        severity="medium",
    ),
    ComplianceRule(
        id="wcag-3.1.1", standard="WCAG", code="3.1.1", level="A",
        title="Idioma da página",
        description="Idioma principal do conteúdo deve ser identificável programaticamente.",
        check_fn=lambda t: bool(re.search(r'lang=|idioma|language|pt-BR|html lang', t, re.I)),
        remediation="Mencionar requisito de atributo lang no HTML.",
        severity="low",
    ),
    ComplianceRule(
        id="wcag-4.1.2", standard="WCAG", code="4.1.2", level="A",
        title="Nome, função, valor",
        description="Componentes de interface devem ter nome, função e valor acessíveis.",
        check_fn=lambda t: bool(re.search(r'aria-|role=|aria-label|aria-describedby|semântica', t, re.I)),
        remediation="Adicionar requisito de atributos ARIA para componentes interativos.",
        severity="high",
    ),
]

# ── LGPD Rules ────────────────────────────────────────────────

LGPD_RULES: list[ComplianceRule] = [
    ComplianceRule(
        id="lgpd-art6", standard="LGPD", code="Art.6",
        level="obrigatório",
        title="Princípios do tratamento",
        description="Tratamento de dados deve seguir: finalidade, adequação, necessidade, transparência.",
        check_fn=lambda t: bool(re.search(r'finalidade|necessidade|proporcionalidade|transparência|dado pessoal', t, re.I)),
        remediation="Especificar finalidade do uso de dados pessoais na história.",
        severity="critical",
    ),
    ComplianceRule(
        id="lgpd-art8", standard="LGPD", code="Art.8",
        level="obrigatório",
        title="Consentimento",
        description="Coleta de dados pessoais requer consentimento livre, informado e inequívoco.",
        check_fn=lambda t: bool(re.search(r'consentimento|consent|opt.in|aceitar termos|política de privacidade', t, re.I)),
        remediation="Adicionar CA de consentimento explícito antes da coleta de dados.",
        severity="critical",
    ),
    ComplianceRule(
        id="lgpd-art18", standard="LGPD", code="Art.18",
        level="obrigatório",
        title="Direitos do titular",
        description="Titular tem direito a: acesso, correção, exclusão, portabilidade e revogação.",
        check_fn=lambda t: bool(re.search(r'excluir conta|portabilidade|revogar|direito do titular|deletar dados|apagar', t, re.I)),
        remediation="Incluir US para gerenciamento de dados pessoais pelo usuário.",
        severity="high",
    ),
    ComplianceRule(
        id="lgpd-art46", standard="LGPD", code="Art.46",
        level="obrigatório",
        title="Segurança e sigilo",
        description="Medidas técnicas e administrativas para proteger dados pessoais.",
        check_fn=lambda t: bool(re.search(r'criptografia|encrypt|https|tls|ssl|hash|bcrypt|segurança de dados', t, re.I)),
        remediation="Especificar medidas de segurança técnica (criptografia em repouso e trânsito).",
        severity="critical",
    ),
    ComplianceRule(
        id="lgpd-dpo", standard="LGPD", code="Art.41",
        level="recomendado",
        title="DPO / Encarregado",
        description="Organizações devem nomear encarregado de dados (DPO).",
        check_fn=lambda t: bool(re.search(r'dpo|encarregado|data protection officer|lgpd', t, re.I)),
        remediation="Mencionar referência ao DPO nos fluxos que envolvem dados pessoais.",
        severity="low",
    ),
]

# ── OWASP Top 10 Rules ────────────────────────────────────────

OWASP_RULES: list[ComplianceRule] = [
    ComplianceRule(
        id="owasp-a01", standard="OWASP", code="A01:2021",
        level="crítico",
        title="Broken Access Control",
        description="Verificar controles de acesso: autorização, permissões, RBAC.",
        check_fn=lambda t: bool(re.search(r'autorização|permissão|role|perfil|acesso negado|rbac|401|403', t, re.I)),
        remediation="Adicionar CAs de autorização: acesso negado para usuário sem perfil.",
        severity="critical",
    ),
    ComplianceRule(
        id="owasp-a02", standard="OWASP", code="A02:2021",
        level="crítico",
        title="Cryptographic Failures",
        description="Dados sensíveis devem ser criptografados em repouso e em trânsito.",
        check_fn=lambda t: bool(re.search(r'criptografi|tls|https|ssl|senha.*hash|bcrypt|sha.256|aes', t, re.I)),
        remediation="Especificar requisito de HTTPS e hash de senhas (bcrypt/Argon2).",
        severity="critical",
    ),
    ComplianceRule(
        id="owasp-a03", standard="OWASP", code="A03:2021",
        level="alto",
        title="Injection",
        description="Inputs devem ser validados e sanitizados (SQL, XSS, Command injection).",
        check_fn=lambda t: bool(re.search(r'validação|sanitiz|injection|xss|sql inject|escape|parametriz', t, re.I)),
        remediation="Adicionar CA: 'Inputs devem ser validados e sanitizados antes de processamento'.",
        severity="critical",
    ),
    ComplianceRule(
        id="owasp-a07", standard="OWASP", code="A07:2021",
        level="alto",
        title="Identification & Authentication Failures",
        description="Autenticação robusta: MFA, bloqueio de conta, senhas seguras.",
        check_fn=lambda t: bool(re.search(r'mfa|2fa|autenticação|bloqueio|tentativas|senha segura|complexidade', t, re.I)),
        remediation="Especificar política de senhas e mecanismo de bloqueio por tentativas.",
        severity="high",
    ),
    ComplianceRule(
        id="owasp-a09", standard="OWASP", code="A09:2021",
        level="médio",
        title="Security Logging & Monitoring",
        description="Eventos de segurança devem ser logados e monitorados.",
        check_fn=lambda t: bool(re.search(r'log|auditoria|monitoramento|audit trail|siem|alerta', t, re.I)),
        remediation="Adicionar RN de logging de eventos de segurança (login, acesso negado).",
        severity="medium",
    ),
]

# ── ISO 25010 Rules ───────────────────────────────────────────

ISO_RULES: list[ComplianceRule] = [
    ComplianceRule(
        id="iso-perf", standard="ISO25010", code="6.1",
        level="recomendado",
        title="Eficiência de performance",
        description="Tempo de resposta e uso de recursos devem ser especificados.",
        check_fn=lambda t: bool(re.search(r'tempo de resposta|latência|performance|sla|\d+\s*ms|\d+\s*s(?:egundo)?|throughput', t, re.I)),
        remediation="Especificar SLA de performance: 'Resposta em até X segundos'.",
        severity="medium",
    ),
    ComplianceRule(
        id="iso-usab", standard="ISO25010", code="6.4",
        level="recomendado",
        title="Usabilidade",
        description="Interface deve ser intuitiva, acessível e com feedback claro.",
        check_fn=lambda t: bool(re.search(r'usabilidade|usability|mensagem de erro|feedback|intuitiv|ux|experiência', t, re.I)),
        remediation="Incluir critérios de UX: mensagens de erro claras, confirmações visuais.",
        severity="low",
    ),
    ComplianceRule(
        id="iso-reli", standard="ISO25010", code="6.3",
        level="recomendado",
        title="Confiabilidade",
        description="Tolerância a falhas, disponibilidade e recuperabilidade.",
        check_fn=lambda t: bool(re.search(r'disponibilidade|uptime|sla|tolerância|fallback|recovery|backup', t, re.I)),
        remediation="Especificar SLA de disponibilidade (ex: 99.5% uptime).",
        severity="medium",
    ),
    ComplianceRule(
        id="iso-maint", standard="ISO25010", code="6.7",
        level="recomendado",
        title="Manutenibilidade",
        description="Código e dados devem ser testáveis, modulares e documentados.",
        check_fn=lambda t: bool(re.search(r'cobertura de teste|documentação|modular|testabilidade|api contract', t, re.I)),
        remediation="Adicionar critérios de cobertura de testes e documentação de API.",
        severity="low",
    ),
]

ALL_RULES = WCAG_RULES + LGPD_RULES + OWASP_RULES + ISO_RULES


# ── ComplianceEngine ──────────────────────────────────────────

class ComplianceEngine:
    """
    Motor de análise de conformidade para histórias de usuário e artefatos.
    Verifica contra WCAG 2.1, LGPD, OWASP Top 10 e ISO 25010.
    """

    STANDARDS = ["WCAG", "LGPD", "OWASP", "ISO25010"]

    def __init__(self):
        self.rules = ALL_RULES

    def analyze(
        self,
        text:       str,
        standards:  list[str] | None = None,
        story_name: str = "",
    ) -> dict:
        """
        Analisa texto contra os padrões selecionados.
        Retorna: { score, findings, passed, failed, by_standard, recommendations }
        """
        active_standards = set(standards or self.STANDARDS)
        active_rules     = [r for r in self.rules if r.standard in active_standards]

        findings:        list[dict] = []
        passed_rules:    list[dict] = []
        critical_count   = 0
        high_count       = 0

        for rule in active_rules:
            try:
                compliant = bool(rule.check_fn(text))
            except Exception:
                compliant = False

            entry = {
                "id":          rule.id,
                "standard":    rule.standard,
                "code":        rule.code,
                "level":       rule.level,
                "title":       rule.title,
                "description": rule.description,
                "compliant":   compliant,
                "severity":    rule.severity,
                "remediation": rule.remediation if not compliant else "",
            }

            if compliant:
                passed_rules.append(entry)
            else:
                findings.append(entry)
                if rule.severity == "critical": critical_count += 1
                elif rule.severity == "high":   high_count += 1

        total = len(active_rules)
        passed = len(passed_rules)

        # Score: 100 - penalties
        base_score = int((passed / total) * 100) if total else 0
        penalty    = critical_count * 15 + high_count * 8
        score      = max(0, base_score - penalty)

        # Compliance level
        if score >= 90:   level = "AA"
        elif score >= 70: level = "A"
        elif score >= 50: level = "Parcial"
        else:             level = "Não Conforme"

        # Group by standard
        by_standard: dict[str, dict] = {}
        for std in active_standards:
            std_rules  = [r for r in active_rules if r.standard == std]
            std_pass   = [r for r in passed_rules  if r["standard"] == std]
            std_fail   = [r for r in findings      if r["standard"] == std]
            std_total  = len(std_rules)
            std_score  = int(len(std_pass) / std_total * 100) if std_total else 0
            by_standard[std] = {
                "total":   std_total,
                "passed":  len(std_pass),
                "failed":  len(std_fail),
                "score":   std_score,
                "level":   "✅ Conforme" if std_score >= 80 else "⚠️ Parcial" if std_score >= 50 else "❌ Não Conforme",
                "findings": std_fail,
            }

        # Top recommendations (critical/high first)
        recommendations = sorted(
            [f for f in findings if f["remediation"]],
            key=lambda f: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(f["severity"], 4)
        )[:8]

        return {
            "story_name":      story_name,
            "score":           score,
            "level":           level,
            "total_rules":     total,
            "passed":          passed,
            "failed":          len(findings),
            "critical_issues": critical_count,
            "high_issues":     high_count,
            "by_standard":     by_standard,
            "findings":        findings,
            "passed_rules":    passed_rules,
            "recommendations": recommendations,
            "standards":       list(active_standards),
        }

    def quick_scan(self, text: str) -> dict:
        """Scan rápido retornando apenas score e issues críticos."""
        result = self.analyze(text)
        return {
            "score":    result["score"],
            "level":    result["level"],
            "critical": result["critical_issues"],
            "high":     result["high_issues"],
            "top_issues": [
                {"code": f["code"], "standard": f["standard"], "title": f["title"]}
                for f in result["findings"][:3]
            ],
        }

    def rules_catalog(self, standard: str = "") -> list[dict]:
        """Retorna catálogo de regras, opcionalmente filtrado por standard."""
        rules = self.rules if not standard else [r for r in self.rules if r.standard == standard]
        return [{
            "id":          r.id,
            "standard":    r.standard,
            "code":        r.code,
            "level":       r.level,
            "title":       r.title,
            "description": r.description,
            "severity":    r.severity,
            "remediation": r.remediation,
        } for r in rules]


# Singleton
compliance_engine = ComplianceEngine()
