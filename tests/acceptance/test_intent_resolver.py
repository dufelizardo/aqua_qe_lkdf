"""Acceptance: Intent Resolver enriquece steps com intent e action."""
from runtime_core.parser.dsl_parser import DSLParser
from runtime_core.semantic_engine.intent_resolver import IntentResolver

DSL = """
@flow TestFlow
  @scenario Test
    Dado que o usuário está na página de login
    Quando o usuário clica no botão "Entrar"
    Então é esperado que a mensagem "Sucesso" seja exibida
"""

flow = DSLParser().parse(DSL)
resolver = IntentResolver()
for scenario in flow.scenarios:
    for step in scenario.steps:
        enriched = resolver.enrich_step(step)
        assert enriched.intent, f"Step sem intent: {step.text}"
        assert enriched.action, f"Step sem action: {step.text}"
print("PASS: Intent Resolver OK")
