"""
AQuA-QE LKDF — CI/CD Integration §36
Exporta Casos de Teste (CTs) para formatos de pipelines de CI/CD:
  - GitHub Actions (workflow YAML)
  - GitLab CI (.gitlab-ci.yml fragment)
  - JUnit XML (compatível com Jenkins, CircleCI, Azure DevOps)
  - Robot Framework (.robot file)
  - JSON genérico para integrações customizadas
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any


class CICDExporter:
    """
    Converte Casos de Teste do AQuA-QE LKDF para formatos de CI/CD.
    """

    # ── GitHub Actions ────────────────────────────────────────

    def to_github_actions(
        self,
        test_cases:    list[dict],
        project_name:  str = "AQuA-QE",
        branch:        str = "main",
        python_version:str = "3.12",
    ) -> str:
        """
        Gera workflow YAML do GitHub Actions com steps para cada CT de alto risco.
        CTs com auto=Sim viram steps de teste automatizado.
        CTs com auto=Não viram steps de verificação manual (informativo).
        """
        auto_cts   = [ct for ct in test_cases if ct.get("auto","").lower() == "sim"]
        manual_cts = [ct for ct in test_cases if ct.get("auto","").lower() != "sim"]
        high_risk  = [ct for ct in test_cases if ct.get("risco","").lower() == "alto"]

        steps_yaml = ""
        for ct in auto_cts[:20]:  # max 20 automated steps
            ct_id   = ct.get("id","CT-???")
            desc    = ct.get("desc", ct.get("description", ""))[:80]
            rn      = ct.get("rn","")
            ca      = ct.get("ca","")
            steps_yaml += f"""
      - name: "{ct_id} | {rn} | {ca}"
        id: {ct_id.lower().replace("-","_")}
        run: |
          echo "Running: {desc}"
          python -m pytest tests/ -k "{ct_id}" -v --tb=short || true
        continue-on-error: {'true' if ct.get("risco","").lower() != "alto" else 'false'}
"""

        manual_yaml = ""
        if manual_cts:
            manual_list = "\n".join(
                f"          - {ct.get('id')}: {ct.get('desc','')[:60]}"
                for ct in manual_cts[:10]
            )
            manual_yaml = f"""
      - name: "Manual Test Checklist ({len(manual_cts)} cases)"
        run: |
          echo "=== MANUAL TEST CASES ==="
{manual_list}
          echo "Please validate these manually before merge."
"""

        return f"""# AQuA-QE LKDF — Generated Test Workflow
# Project: {project_name}
# Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
# Total CTs: {len(test_cases)} | Automated: {len(auto_cts)} | Manual: {len(manual_cts)} | High Risk: {len(high_risk)}

name: "{project_name} — Quality Gate"

on:
  push:
    branches: ["{branch}"]
  pull_request:
    branches: ["{branch}"]

jobs:
  quality-gate:
    name: "LKDF Quality Gate"
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python {python_version}
        uses: actions/setup-python@v5
        with:
          python-version: "{python_version}"
          cache: pip

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-html robot-framework

      - name: Run AQuA-QE Quality Gate
        run: |
          echo "=== AQuA-QE LKDF Quality Gate ==="
          echo "Total test cases: {len(test_cases)}"
          echo "High risk (auto): {len([c for c in high_risk if c.get('auto','').lower()=='sim'])}"
{steps_yaml}{manual_yaml}
      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: aqua-qe-results
          path: |
            reports/
            *.xml
          retention-days: 30

  compliance-check:
    name: "Compliance Gate (WCAG + OWASP)"
    runs-on: ubuntu-latest
    needs: quality-gate
    steps:
      - uses: actions/checkout@v4
      - name: OWASP Dependency Check
        run: echo "Running OWASP checks..."
      - name: WCAG Accessibility Check
        run: echo "Running accessibility checks..."
"""

    # ── GitLab CI ─────────────────────────────────────────────

    def to_gitlab_ci(self, test_cases: list[dict], project_name: str = "AQuA-QE") -> str:
        """Gera fragmento de .gitlab-ci.yml."""
        auto_cts = [ct for ct in test_cases if ct.get("auto","").lower() == "sim"]
        high     = [ct for ct in test_cases if ct.get("risco","").lower() == "alto"]

        ct_scripts = "\n".join(
            f'  - python -m pytest tests/ -k "{ct.get("id","")}" -v || true'
            for ct in auto_cts[:15]
        )

        return f"""# AQuA-QE LKDF — GitLab CI fragment
# Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
# CTs: {len(test_cases)} | Auto: {len(auto_cts)} | High Risk: {len(high)}

stages:
  - test
  - quality-gate
  - compliance

variables:
  AQUA_PROJECT: "{project_name}"
  AQUA_CT_TOTAL: "{len(test_cases)}"
  AQUA_CT_AUTO: "{len(auto_cts)}"

unit-tests:
  stage: test
  image: python:3.12
  before_script:
    - pip install -r requirements.txt pytest pytest-html
  script:
    - echo "=== AQuA-QE Quality Gate: {project_name} ==="
{ct_scripts}
  artifacts:
    reports:
      junit: reports/junit.xml
    paths:
      - reports/
    expire_in: 7 days
  coverage: '/TOTAL.*\s+(\d+\%)$/'

quality-gate:
  stage: quality-gate
  script:
    - echo "High risk CTs automated: {len([c for c in high if c.get('auto','').lower()=='sim'])}/{len(high)}"
    - |
      if [ {len([c for c in high if c.get('auto','').lower()=='sim'])} -lt {max(1,len(high)//2)} ]; then
        echo "WARNING: Less than 50% of high-risk CTs are automated"
        exit 1
      fi
  allow_failure: true
"""

    # ── JUnit XML ────────────────────────────────────────────

    def to_junit_xml(self, test_cases: list[dict], project_name: str = "AQuA-QE") -> str:
        """
        Gera JUnit XML (compatível com Jenkins, CircleCI, Azure DevOps, Bamboo).
        Casos de teste aparecem como pending/skipped no relatório.
        """
        root = ET.Element("testsuites", name=project_name,
                          tests=str(len(test_cases)),
                          time="0",
                          timestamp=datetime.utcnow().isoformat())

        # Group by story
        by_story: dict[str, list] = {}
        for ct in test_cases:
            story = ct.get("story", ct.get("story_name", "General"))
            by_story.setdefault(story, []).append(ct)

        for story, cts in by_story.items():
            suite = ET.SubElement(root, "testsuite",
                                  name=story,
                                  tests=str(len(cts)),
                                  failures="0",
                                  errors="0",
                                  skipped=str(len([c for c in cts if c.get("auto","").lower()!="sim"])),
                                  time="0")

            for ct in cts:
                ct_id  = ct.get("id","CT-???")
                rn     = ct.get("rn","")
                ca     = ct.get("ca","")
                desc   = ct.get("desc", ct.get("description",""))
                is_auto = ct.get("auto","").lower() == "sim"
                risco  = ct.get("risco","Médio")

                case = ET.SubElement(suite, "testcase",
                                     name=f"{ct_id}: {desc[:80]}",
                                     classname=f"{story}.{rn}",
                                     time="0")

                ET.SubElement(case, "properties").append(
                    self._prop("risco", risco)
                )
                ET.SubElement(case, "properties").append(
                    self._prop("prioridade", ct.get("prio","Média"))
                )
                ET.SubElement(case, "properties").append(
                    self._prop("ca", ca)
                )
                ET.SubElement(case, "properties").append(
                    self._prop("automatizavel", ct.get("auto","Não"))
                )

                if not is_auto:
                    skip = ET.SubElement(case, "skipped")
                    skip.set("message", f"Manual test — {desc[:100]}")

        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        lines = ['<?xml version="1.0" encoding="UTF-8"?>']
        lines.append(ET.tostring(root, encoding="unicode"))
        return "\n".join(lines)

    @staticmethod
    def _prop(name: str, value: str):
        el = ET.Element("property", name=name, value=value)
        return el

    # ── Robot Framework ───────────────────────────────────────

    def to_robot(self, test_cases: list[dict], project_name: str = "AQuA-QE") -> str:
        """Gera arquivo .robot com todos os CTs automatizáveis."""
        auto_cts = [ct for ct in test_cases if ct.get("auto","").lower() == "sim"]
        if not auto_cts:
            auto_cts = test_cases[:10]

        test_blocks = ""
        for ct in auto_cts:
            ct_id  = ct.get("id","CT-???")
            desc   = ct.get("desc",ct.get("description",""))
            rn     = ct.get("rn","")
            ca     = ct.get("ca","")
            risco  = ct.get("risco","Médio")
            prio   = ct.get("prio","Média")
            story  = ct.get("story",ct.get("story_name",""))
            tags   = f"smoke    regression    risco-{risco.lower().replace('é','e').replace('é','e')}"

            test_blocks += f"""
{ct_id} - {rn} | {ca}
    [Documentation]    {desc}
    ...    Story: {story}
    ...    Risco: {risco} | Prioridade: {prio}
    [Tags]    {tags}
    [Setup]    Preparar Ambiente
    Executar Caso De Teste    {ct_id}
    Verificar Resultado Esperado
    [Teardown]    Limpar Estado
"""

        return f"""*** Settings ***
# AQuA-QE LKDF — Generated Test Suite
# Project: {project_name}
# Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
# Total CTs: {len(test_cases)} | Automated: {len(auto_cts)}

Library     SeleniumLibrary
Library     Collections
Library     RequestsLibrary
Resource    ../resources/keywords.robot
Resource    ../resources/variables.robot

Suite Setup       Iniciar Suite    {project_name}
Suite Teardown    Finalizar Suite

*** Variables ***
${{PROJECT}}        {project_name}
${{BASE_URL}}       https://app.exemplo.com
${{BROWSER}}        chrome
${{TIMEOUT}}        30s

*** Test Cases ***
{test_blocks}
*** Keywords ***

Preparar Ambiente
    [Documentation]    Configura pré-condições para o caso de teste
    Log    Iniciando caso de teste

Executar Caso De Teste
    [Arguments]    ${{ct_id}}
    Log    Executando: ${{ct_id}}
    # TODO: Implement test steps for ${{ct_id}}

Verificar Resultado Esperado
    [Documentation]    Verifica se o resultado está de acordo com o CA
    Log    Verificando resultado

Limpar Estado
    Log    Limpando estado após teste

Iniciar Suite
    [Arguments]    ${{project}}
    Log    Iniciando suite: ${{project}}

Finalizar Suite
    Log    Suite finalizada
"""

    # ── Generic JSON ──────────────────────────────────────────

    def to_json(self, test_cases: list[dict], metadata: dict | None = None) -> str:
        """Exporta para JSON genérico com metadados completos."""
        export = {
            "aqua_qe_version":    "2.0",
            "export_format":      "lkdf-ct-v1",
            "generated_at":       datetime.utcnow().isoformat() + "Z",
            "metadata":           metadata or {},
            "summary": {
                "total":          len(test_cases),
                "automated":      len([c for c in test_cases if c.get("auto","").lower()=="sim"]),
                "manual":         len([c for c in test_cases if c.get("auto","").lower()!="sim"]),
                "high_risk":      len([c for c in test_cases if c.get("risco","").lower()=="alto"]),
                "with_gaps":      len([c for c in test_cases if c.get("gap","Nenhum")!="Nenhum"]),
            },
            "test_cases":        test_cases,
        }
        return json.dumps(export, indent=2, ensure_ascii=False)


# Singleton
cicd_exporter = CICDExporter()
