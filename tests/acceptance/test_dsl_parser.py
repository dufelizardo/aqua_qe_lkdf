"""Acceptance: DSL Parser cria flows válidos."""
from runtime_core.parser.dsl_parser import DSLParser, validate_dsl

DSL = """
@flow LoginFlow
  @scenario ValidLogin
    Dado que o usuário está na página de login
    Quando o usuário clica no botão "Entrar"
    Então é esperado que a mensagem "Bem-vindo" seja exibida
"""

result = validate_dsl(DSL)
assert result.valid, f"DSL inválido: {result.errors}"
flow = DSLParser().parse(DSL)
assert len(flow.scenarios) > 0
print("PASS: DSL Parser OK")
