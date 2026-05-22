"""
runtime_core/evidence_engine/collector.py
AQuA-QE LKDF — Evidence Engine & Traceability Engine

Responsável por:
  - Coletar e armazenar evidências de execução
  - Gerar artefatos estruturados (JSON, HTML)
  - Registrar a cadeia de rastreabilidade completa
  - Atualizar o RTM (Requirement Traceability Matrix)
"""
from __future__ import annotations

from typing import Any

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from shared.models import ExecutionReport, ExecutionStatus, TraceEntry


# ---------------------------------------------------------------------------
# Evidence Collector
# ---------------------------------------------------------------------------

class EvidenceCollector:
    """
    Coleta, organiza e persiste evidências de execução.
    Gera relatórios estruturados rastreáveis até o requisito de origem.
    """

    def __init__(self, evidence_dir: str | Path = "/tmp/lkdf/evidence") -> None:
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self._session_id = str(uuid4())[:8]

    # ------------------------------------------------------------------
    def collect_from_report(self, report: ExecutionReport) -> list[str]:
        """Gera todos os artefatos de evidência de um ExecutionReport."""
        paths: list[str] = []

        # 1. Execution summary JSON
        summary_path = self._save_execution_summary(report)
        paths.append(summary_path)

        # 2. Traceability HTML report
        html_path = self._generate_html_report(report)
        paths.append(html_path)

        # 3. RTM entry
        rtm_path = self._update_rtm(report)
        paths.append(rtm_path)

        return paths

    # ------------------------------------------------------------------
    def _save_execution_summary(self, report: ExecutionReport) -> str:
        ts    = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        fname = f"execution_{self._session_id}_{ts}.json"
        path  = self.evidence_dir / fname

        data = {
            "lkdf_version":     "1.1",
            "execution_id":     str(report.id),
            "flow":             report.flow_name,
            "adapter":          report.adapter,
            "requirement_ref":  report.requirement_ref,
            "status":           report.status,
            "timestamp":        ts,
            "duration_ms":      report.duration_ms,
            "success_rate":     f"{report.success_rate:.1f}%",
            "summary": {
                "total":   report.total_scenarios,
                "passed":  report.passed,
                "failed":  report.failed,
                "skipped": report.skipped,
            },
            "scenarios": [
                {
                    "name":     s.scenario_name,
                    "status":   s.status,
                    "duration": s.duration_ms,
                    "steps": [
                        {
                            "id":       str(st.step_id),
                            "status":   st.status,
                            "duration": st.duration_ms,
                            "message":  st.message,
                        }
                        for st in s.step_results
                    ],
                }
                for s in report.scenario_results
            ],
        }
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        return str(path)

    def _generate_html_report(self, report: ExecutionReport) -> str:
        ts    = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        fname = f"trace_{self._session_id}_{ts}.html"
        path  = self.evidence_dir / fname

        status_color = {
            ExecutionStatus.PASSED:  "#22c55e",
            ExecutionStatus.FAILED:  "#ef4444",
            ExecutionStatus.RUNNING: "#4f7cff",
            ExecutionStatus.ERROR:   "#f97316",
        }.get(report.status, "#888")

        scenario_rows = ""
        for s in report.scenario_results:
            sc = "#22c55e" if s.status == ExecutionStatus.PASSED else "#ef4444"
            step_rows = "".join(
                f"<tr><td style='padding:4px 8px;font-family:monospace;font-size:12px;color:#ccc'>{st.step_id!s:.8}</td>"
                f"<td style='padding:4px 8px;font-size:12px;color:{'#22c55e' if st.status == ExecutionStatus.PASSED else '#ef4444'}'>{st.status}</td>"
                f"<td style='padding:4px 8px;font-size:12px;color:#aaa'>{st.duration_ms}ms</td>"
                f"<td style='padding:4px 8px;font-size:12px;color:#ddd'>{st.message}</td></tr>"
                for st in s.step_results
            )
            scenario_rows += f"""
            <div style='background:#1e2230;border:1px solid #2a3040;border-radius:8px;padding:14px;margin-bottom:10px;'>
              <div style='color:{sc};font-weight:600;margin-bottom:8px;'>{s.scenario_name} — {s.status} ({s.duration_ms}ms)</div>
              <table style='width:100%;border-collapse:collapse;'>
                <thead><tr><th style='text-align:left;color:#666;font-size:10px;padding:4px 8px;'>STEP ID</th>
                <th style='text-align:left;color:#666;font-size:10px;padding:4px 8px;'>STATUS</th>
                <th style='text-align:left;color:#666;font-size:10px;padding:4px 8px;'>DURATION</th>
                <th style='text-align:left;color:#666;font-size:10px;padding:4px 8px;'>MESSAGE</th></tr></thead>
                <tbody>{step_rows}</tbody>
              </table>
            </div>"""

        html = f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>AQuA-QE LKDF — Trace Report</title>
<style>body{{background:#0a0c10;color:#e8eaf0;font-family:sans-serif;padding:24px;}}</style>
</head><body>
<h1 style='font-size:20px;margin-bottom:4px;'>AQuA-QE LKDF — Execution Trace</h1>
<div style='color:#666;font-size:12px;margin-bottom:20px;'>Gerado em {ts} · Runtime v1.1</div>
<div style='background:#1e2230;border-radius:10px;padding:16px;margin-bottom:16px;display:grid;grid-template-columns:repeat(4,1fr);gap:12px;'>
  <div><div style='color:#666;font-size:10px;'>FLOW</div><div style='font-weight:600;'>{report.flow_name}</div></div>
  <div><div style='color:#666;font-size:10px;'>STATUS</div><div style='color:{status_color};font-weight:700;'>{report.status}</div></div>
  <div><div style='color:#666;font-size:10px;'>REQUISITO</div><div style='color:#4f7cff;font-size:12px;'>{report.requirement_ref or "—"}</div></div>
  <div><div style='color:#666;font-size:10px;'>DURAÇÃO</div><div style='font-family:monospace;'>{report.duration_ms}ms</div></div>
</div>
<h2 style='font-size:14px;color:#888;margin-bottom:12px;text-transform:uppercase;letter-spacing:.08em;'>Scenarios</h2>
{scenario_rows}
<div style='margin-top:16px;font-size:11px;color:#444;'>
  AQuA-QE LKDF · Requirement Traceability Matrix · {report.requirement_ref} → {report.flow_name} → Execution {str(report.id)[:8]}
</div>
</body></html>"""

        path.write_text(html, encoding="utf-8")
        return str(path)

    def _update_rtm(self, report: ExecutionReport) -> str:
        """Atualiza ou cria a entrada RTM para o requisito de origem."""
        rtm_file = self.evidence_dir / "rtm.json"
        rtm: dict[str, dict] = {}

        if rtm_file.exists():
            rtm = json.loads(rtm_file.read_text())

        req_id = report.requirement_ref or f"REQ-{str(report.flow_id)[:6]}"
        entry  = rtm.get(req_id, {
            "requirement_id": req_id,
            "flows":          [],
            "executions":     [],
            "last_status":    None,
            "coverage":       0,
        })

        if report.flow_name not in entry["flows"]:
            entry["flows"].append(report.flow_name)

        entry["executions"].append({
            "id":          str(report.id),
            "timestamp":   datetime.utcnow().isoformat(),
            "status":      report.status,
            "passed":      report.passed,
            "failed":      report.failed,
            "duration_ms": report.duration_ms,
        })
        entry["last_status"] = report.status
        entry["coverage"]    = int(report.success_rate)

        rtm[req_id] = entry
        rtm_file.write_text(json.dumps(rtm, indent=2, default=str), encoding="utf-8")
        return str(rtm_file)


# ---------------------------------------------------------------------------
# Traceability Engine
# ---------------------------------------------------------------------------

class TraceabilityEngine:
    """
    Registra e mantém a cadeia completa de rastreabilidade:
    Requirement → Business Rule → Flow → Scenario → Test Case → Execution → Evidence → Defect
    """

    def __init__(self) -> None:
        self._entries: list[TraceEntry] = []

    def register(self, entry: TraceEntry) -> None:
        entry.updated_at = datetime.utcnow()
        self._entries.append(entry)

    def from_report(self, report: ExecutionReport) -> list[TraceEntry]:
        entries: list[TraceEntry] = []
        for scenario_result in report.scenario_results:
            entry = TraceEntry(
                requirement_id=report.requirement_ref or str(report.flow_id),
                flow_id=report.flow_id,
                flow_name=report.flow_name,
                scenario_id=scenario_result.scenario_id,
                scenario_name=scenario_result.scenario_name,
                execution_id=report.id,
                execution_status=scenario_result.status,
                evidence_paths=report.evidence_paths,
            )
            self.register(entry)
            entries.append(entry)
        return entries

    def get_by_requirement(self, req_id: str) -> list[TraceEntry]:
        return [e for e in self._entries if e.requirement_id == req_id]

    def coverage_report(self) -> dict[str, Any]:
        by_req: dict[str, list[TraceEntry]] = {}
        for e in self._entries:
            by_req.setdefault(e.requirement_id, []).append(e)
        return {
            req: {
                "total":   len(entries),
                "passed":  sum(1 for e in entries if e.execution_status == ExecutionStatus.PASSED),
                "failed":  sum(1 for e in entries if e.execution_status == ExecutionStatus.FAILED),
            }
            for req, entries in by_req.items()
        }
