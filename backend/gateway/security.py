"""
AQuA-QE LKDF — AI Security & Governance
§30: anonimização de PII, mascaramento de dados sensíveis,
     auditoria de prompts, controles de acesso, logs de governança.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


# ── PII Patterns ─────────────────────────────────────────────

class PIIDetector:
    """
    Detecta e mascara Informações Pessoais Identificáveis (PII)
    e dados sensíveis em prompts e respostas.
    """

    PATTERNS = {
        "cpf":      (r"\b\d{3}[.\-]?\d{3}[.\-]?\d{3}[-.]?\d{2}\b",           "[CPF_MASCARADO]"),
        "cnpj":     (r"\b\d{2}[.\-]?\d{3}[.\-]?\d{3}[/\\]?\d{4}[-.]?\d{2}\b", "[CNPJ_MASCARADO]"),
        "email":    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  "[EMAIL_MASCARADO]"),
        "phone_br": (r"\b(?:\+55\s?)?(?:\(?\d{2}\)?\s?)(?:9\s?\d{4}|\d{4})[-\s]?\d{4}\b", "[TELEFONE_MASCARADO]"),
        "cep":      (r"\b\d{5}[-\s]?\d{3}\b",                                  "[CEP_MASCARADO]"),
        "rg":       (r"\b\d{1,2}[.\-]?\d{3}[.\-]?\d{3}[-.]?[0-9Xx]\b",        "[RG_MASCARADO]"),
        "credit_card": (r"\b(?:\d{4}[- ]?){3}\d{4}\b",                         "[CARTAO_MASCARADO]"),
        "api_key":  (r"\b(?:sk-|AIza|gsk_|key-)[A-Za-z0-9_\-]{20,}\b",        "[API_KEY_MASCARADA]"),
        "bearer":   (r"Bearer\s+[A-Za-z0-9_\-\.]{20,}",                        "Bearer [TOKEN_MASCARADO]"),
        "password": (r"(?i)(?:senha|password|passwd|pwd)\s*[:=]\s*\S+",        "[SENHA_MASCARADA]"),
        "ip_v4":    (r"\b(?:\d{1,3}\.){3}\d{1,3}\b",                          "[IP_MASCARADO]"),
    }

    # Sensitive terms that suggest confidential content
    SENSITIVE_TERMS = [
        "confidencial", "secreto", "restrito", "interno", "classificado",
        "proprietary", "confidential", "restricted", "secret",
    ]

    def __init__(self, enabled_patterns: list[str] | None = None):
        self.enabled = set(enabled_patterns or self.PATTERNS.keys())
        self._lock = threading.Lock()
        self._stats: dict[str, int] = {p: 0 for p in self.PATTERNS}

    def detect(self, text: str) -> dict:
        """
        Analisa texto e retorna findings sem mascarar.
        Retorna: { pii_types: [...], sensitive_terms: [...], risk_level: 'low|medium|high' }
        """
        findings = []
        for ptype, (pattern, _) in self.PATTERNS.items():
            if ptype in self.enabled and re.search(pattern, text):
                findings.append(ptype)

        sensitive = [t for t in self.SENSITIVE_TERMS if t.lower() in text.lower()]
        risk = "high" if len(findings) >= 3 or "api_key" in findings or "credit_card" in findings \
             else "medium" if findings or sensitive \
             else "low"

        return {"pii_types": findings, "sensitive_terms": sensitive, "risk_level": risk}

    def mask(self, text: str, dry_run: bool = False) -> tuple[str, list[str]]:
        """
        Aplica mascaramento ao texto.
        Retorna: (texto_mascarado, lista_de_tipos_mascarados)
        """
        masked_types = []
        result = text
        for ptype, (pattern, replacement) in self.PATTERNS.items():
            if ptype not in self.enabled:
                continue
            new_result, count = re.subn(pattern, replacement, result)
            if count > 0:
                masked_types.append(ptype)
                with self._lock:
                    self._stats[ptype] += count
                if not dry_run:
                    result = new_result
        return (result if not dry_run else text), masked_types

    def stats(self) -> dict[str, int]:
        with self._lock:
            return dict(self._stats)


# ── Audit Logger ─────────────────────────────────────────────

class AuditEntry:
    """Entrada de log de auditoria imutável."""

    def __init__(
        self,
        action:      str,
        actor:       str,
        resource:    str,
        outcome:     str,        # "allowed" | "blocked" | "masked" | "flagged"
        risk_level:  str = "low",
        details:     dict | None = None,
        pii_types:   list[str] | None = None,
        prompt_hash: str = "",
        session_id:  str | None = None,
    ):
        self.id          = str(uuid.uuid4())[:8]
        self.timestamp   = datetime.utcnow().isoformat() + "Z"
        self.action      = action
        self.actor       = actor
        self.resource    = resource
        self.outcome     = outcome
        self.risk_level  = risk_level
        self.details     = details or {}
        self.pii_types   = pii_types or []
        self.prompt_hash = prompt_hash
        self.session_id  = session_id

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "timestamp":   self.timestamp,
            "action":      self.action,
            "actor":       self.actor,
            "resource":    self.resource,
            "outcome":     self.outcome,
            "risk_level":  self.risk_level,
            "pii_types":   self.pii_types,
            "prompt_hash": self.prompt_hash,
            "session_id":  self.session_id,
            "details":     self.details,
        }


class AuditLogger:
    """
    Log de auditoria imutável — registra todas as ações de segurança,
    acessos a providers e detecções de PII.
    """

    def __init__(self, max_entries: int = 2000):
        self._lock    = threading.Lock()
        self._entries: deque[AuditEntry] = deque(maxlen=max_entries)
        self._counters: dict[str, int] = {
            "total": 0, "allowed": 0, "blocked": 0, "masked": 0, "flagged": 0,
        }

    def log(self, entry: AuditEntry) -> None:
        with self._lock:
            self._entries.appendleft(entry)
            self._counters["total"] += 1
            self._counters[entry.outcome] = self._counters.get(entry.outcome, 0) + 1

    def record(
        self,
        action: str,
        actor: str = "system",
        resource: str = "",
        outcome: str = "allowed",
        risk_level: str = "low",
        details: dict | None = None,
        pii_types: list[str] | None = None,
        prompt_hash: str = "",
        session_id: str | None = None,
    ) -> AuditEntry:
        entry = AuditEntry(
            action=action, actor=actor, resource=resource, outcome=outcome,
            risk_level=risk_level, details=details, pii_types=pii_types,
            prompt_hash=prompt_hash, session_id=session_id,
        )
        self.log(entry)
        return entry

    def recent(self, limit: int = 100, outcome_filter: str = "") -> list[dict]:
        with self._lock:
            entries = list(self._entries)
        if outcome_filter:
            entries = [e for e in entries if e.outcome == outcome_filter]
        return [e.to_dict() for e in entries[:limit]]

    def stats(self) -> dict:
        with self._lock:
            total = max(self._counters["total"], 1)
            return {
                **self._counters,
                "blocked_rate": round(self._counters.get("blocked", 0) / total * 100, 1),
                "masked_rate":  round(self._counters.get("masked",  0) / total * 100, 1),
                "flagged_rate": round(self._counters.get("flagged", 0) / total * 100, 1),
            }

    def search(self, query: str, limit: int = 50) -> list[dict]:
        with self._lock:
            entries = list(self._entries)
        q = query.lower()
        filtered = [e for e in entries
                    if q in e.action.lower() or q in e.actor.lower()
                    or q in e.resource.lower() or q in str(e.details).lower()]
        return [e.to_dict() for e in filtered[:limit]]


# ── Security Policy ──────────────────────────────────────────

class SecurityPolicy:
    """
    Política de segurança configurável — define regras de bloqueio,
    mascaramento e alertas por nível de risco.
    """

    DEFAULTS = {
        "pii_masking_enabled":    True,
        "pii_patterns_enabled":   ["cpf","cnpj","email","phone_br","credit_card","api_key","bearer","password"],
        "block_on_high_risk":     False,   # bloquear request se PII de alto risco detectado
        "mask_before_send":       True,    # mascarar antes de enviar ao LLM
        "mask_in_response":       False,   # mascarar resposta antes de retornar
        "audit_all_requests":     True,
        "audit_pii_detections":   True,
        "max_prompt_length":      50000,   # chars
        "allowed_providers":      [],      # [] = all allowed
        "allowed_engines":        [],      # [] = all allowed
        "require_session_id":     False,
        "lgpd_mode":              False,   # modo LGPD: extra mascaramento e auditoria
        "wcag_compliance_check":  False,   # checar outputs por acessibilidade
        "content_filter_level":   "off",   # off | low | medium | high
    }

    def __init__(self):
        self._policy = dict(self.DEFAULTS)
        self._lock   = threading.Lock()

    def get(self, key: str, default=None):
        with self._lock:
            return self._policy.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._policy:
                self._policy[key] = value

    def update(self, updates: dict) -> None:
        with self._lock:
            for k, v in updates.items():
                if k in self._policy:
                    self._policy[k] = v

    def to_dict(self) -> dict:
        with self._lock:
            return dict(self._policy)


# ── Security Gateway ─────────────────────────────────────────

class SecurityGateway:
    """
    Ponto central de controle de segurança.
    Intercepta requests/responses e aplica políticas.
    """

    def __init__(self):
        self.policy   = SecurityPolicy()
        self.detector = PIIDetector()
        self.audit    = AuditLogger()
        self._lock    = threading.Lock()

    def inspect_request(
        self,
        content:    str,
        provider:   str = "",
        engine:     str = "",
        session_id: str | None = None,
        actor:      str = "user",
    ) -> dict:
        """
        Inspeciona um request antes de enviá-lo ao LLM.
        Retorna: { allowed, masked_content, findings, action_taken }
        """
        result = {
            "allowed":        True,
            "masked_content": content,
            "findings":       {},
            "action_taken":   "pass",
            "audit_id":       None,
        }

        # 1. Tamanho máximo
        max_len = self.policy.get("max_prompt_length", 50000)
        if len(content) > max_len:
            self.audit.record(
                action="prompt_too_long", actor=actor, resource=engine,
                outcome="blocked", risk_level="medium",
                details={"length": len(content), "max": max_len},
                session_id=session_id,
            )
            result.update({"allowed": False, "action_taken": "blocked_length"})
            return result

        # 2. Provider/Engine allowlist
        allowed_provs = self.policy.get("allowed_providers", [])
        if allowed_provs and provider and provider not in allowed_provs:
            self.audit.record(
                action="provider_not_allowed", actor=actor, resource=provider,
                outcome="blocked", risk_level="medium", session_id=session_id,
            )
            result.update({"allowed": False, "action_taken": "blocked_provider"})
            return result

        # 3. PII detection & masking
        if self.policy.get("pii_masking_enabled", True):
            findings = self.detector.detect(content)
            result["findings"] = findings

            if findings["pii_types"] or findings["sensitive_terms"]:
                # Audit the detection
                phash = hashlib.sha256(content[:200].encode()).hexdigest()[:8]
                entry = self.audit.record(
                    action="pii_detected", actor=actor, resource=engine,
                    outcome="masked" if self.policy.get("mask_before_send") else "flagged",
                    risk_level=findings["risk_level"],
                    pii_types=findings["pii_types"],
                    details={"sensitive_terms": findings["sensitive_terms"]},
                    prompt_hash=phash, session_id=session_id,
                )
                result["audit_id"] = entry.id

                # Block on high risk if configured
                if findings["risk_level"] == "high" and self.policy.get("block_on_high_risk", False):
                    result.update({"allowed": False, "action_taken": "blocked_pii_high_risk"})
                    return result

                # Mask if configured
                if self.policy.get("mask_before_send", True):
                    masked, masked_types = self.detector.mask(content)
                    result.update({
                        "masked_content": masked,
                        "action_taken": "masked",
                    })
            elif self.policy.get("audit_all_requests", True):
                self.audit.record(
                    action="request_inspected", actor=actor, resource=engine,
                    outcome="allowed", risk_level="low", session_id=session_id,
                )

        return result

    def inspect_response(self, content: str, session_id: str | None = None) -> str:
        """Opcionalmente mascara PII na resposta do LLM."""
        if not self.policy.get("mask_in_response", False):
            return content
        masked, types = self.detector.mask(content)
        if types:
            self.audit.record(
                action="response_masked", actor="system", resource="response",
                outcome="masked", risk_level="medium", pii_types=types,
                session_id=session_id,
            )
        return masked

    def summary(self) -> dict:
        return {
            "policy":        self.policy.to_dict(),
            "audit_stats":   self.audit.stats(),
            "pii_stats":     self.detector.stats(),
            "total_blocked": self.audit.stats().get("blocked", 0),
            "total_masked":  self.audit.stats().get("masked", 0),
        }


# ── Singletons ───────────────────────────────────────────────

security_gateway = SecurityGateway()
