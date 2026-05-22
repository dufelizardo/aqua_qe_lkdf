"""
runtime_core/cli.py
AQuA-QE LKDF — CLI

Uso:
  lkdf parse flow.lkdf
  lkdf run flow.lkdf
  lkdf validate flow.lkdf
  lkdf analyze "Usuário bloqueado não deve acessar sistema"
  lkdf serve
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from rich.table import Table

app     = typer.Typer(name="lkdf", help="AQuA-QE LKDF — Runtime Core CLI v1.1")
console = Console()

BANNER = """
[bold blue]  ╔═══════════════════════════════════════╗
  ║   AQuA-QE LKDF Runtime Core v1.1    ║
  ║   Layered Keyword-Driven Framework   ║
  ╚═══════════════════════════════════════╝[/bold blue]
"""


@app.command()
def validate(
    dsl_file: Path = typer.Argument(..., help="Arquivo .lkdf ou .feature"),
):
    """Valida o DSL semântico sem executar."""
    from runtime_core.parser.dsl_parser import validate_dsl

    rprint(BANNER)
    source = dsl_file.read_text(encoding="utf-8")
    result = validate_dsl(source)

    if result.valid:
        rprint(f"[green]✓ DSL válido:[/green] {dsl_file.name}")
    else:
        rprint(f"[red]✗ DSL inválido:[/red] {dsl_file.name}")

    for err in result.errors:
        rprint(f"  [red]ERROR[/red] linha {err.line_no}: {err.message}")
    for warn in result.warnings:
        rprint(f"  [yellow]WARN[/yellow]  linha {warn.line_no}: {warn.message}")

    raise typer.Exit(0 if result.valid else 1)


@app.command("parse")
def parse_cmd(
    dsl_file: Path = typer.Argument(..., help="Arquivo .lkdf para parsear"),
    json_out: bool = typer.Option(False, "--json", help="Output em JSON"),
):
    """Parse o DSL e exibe a AST do Flow."""
    from runtime_core.parser.dsl_parser import DSLParser

    rprint(BANNER)
    source = dsl_file.read_text(encoding="utf-8")
    parser = DSLParser()

    try:
        flow = parser.parse(source)
    except Exception as exc:
        rprint(f"[red]Erro de parse:[/red] {exc}")
        raise typer.Exit(1)

    if json_out:
        rprint(flow.model_dump_json(indent=2))
        return

    console.print(Panel(
        f"[bold]{flow.name}[/bold]\n"
        f"Requisito: [cyan]{flow.requirement_ref or 'N/A'}[/cyan]\n"
        f"Adapter: [green]{flow.adapter}[/green] · "
        f"Prioridade: [yellow]{flow.priority}[/yellow]",
        title="Flow Parsed",
        border_style="blue",
    ))

    table = Table(title="Scenarios & Steps", show_header=True, header_style="bold cyan")
    table.add_column("Scenario", style="white")
    table.add_column("Steps", justify="right", style="cyan")
    table.add_column("Intents")

    for s in flow.scenarios:
        table.add_row(s.name, str(len(s.steps)), ", ".join(set(
            st.step_type for st in s.steps
        )))

    console.print(table)


@app.command("run")
def run_cmd(
    dsl_file: Path  = typer.Argument(..., help="Arquivo .lkdf para executar"),
    base_url: str   = typer.Option("http://localhost:4200", help="Base URL da aplicação"),
    dry_run:  bool  = typer.Option(False, help="Dry run (sem execução real do adapter)"),
    output:   Path  = typer.Option(Path("./lkdf-evidence"), help="Diretório de evidências"),
):
    """Executa um Flow completo e gera evidências."""

    async def _run():
        from runtime_core.parser.dsl_parser import DSLParser
        from runtime_core.execution_engine.engine import ExecutionEngine
        from runtime_core.adapters.robot.robot_adapter import RobotAdapter
        from runtime_core.evidence_engine.collector import EvidenceCollector
        from shared.models import ProjectContext, RuntimeContext

        rprint(BANNER)
        source  = dsl_file.read_text(encoding="utf-8")
        parser  = DSLParser()

        try:
            flow = parser.parse(source)
        except Exception as exc:
            rprint(f"[red]DSL inválido:[/red] {exc}")
            raise typer.Exit(1)

        rprint(f"\n[bold]Executando:[/bold] [cyan]{flow.name}[/cyan] "
               f"({len(flow.scenarios)} scenarios)\n")

        context = RuntimeContext(
            flow=flow,
            project=ProjectContext(base_url=base_url),
        )
        adapter    = RobotAdapter(base_url=base_url)
        engine     = ExecutionEngine(adapter=adapter)
        collector  = EvidenceCollector(evidence_dir=output)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Executando pipeline semântico...", total=None)

            report = await engine.execute_flow(flow, context)
            evidence_paths = collector.collect_from_report(report)
            report.evidence_paths = evidence_paths

            progress.stop()

        # Summary
        status_color = "green" if report.status == "passed" else "red"
        console.print(Panel(
            f"Status: [{status_color}]{report.status.upper()}[/{status_color}]\n"
            f"Passed:  [green]{report.passed}[/green]  "
            f"Failed: [red]{report.failed}[/red]  "
            f"Skipped: {report.skipped}\n"
            f"Duração: [cyan]{report.duration_ms}ms[/cyan]\n"
            f"Evidências: {len(evidence_paths)} artefatos",
            title=f"Resultado — {flow.name}",
            border_style=status_color,
        ))

        for path in evidence_paths:
            rprint(f"  [dim]→[/dim] {path}")

        raise typer.Exit(0 if report.failed == 0 else 1)

    asyncio.run(_run())


@app.command()
def analyze(
    requirement: str = typer.Argument(..., help="Texto do requisito"),
    req_id: str      = typer.Option("REQ-AUTO", help="ID do requisito"),
    save_flow: Path  = typer.Option(None, "--save", help="Salvar DSL gerado em arquivo"),
):
    """Analisa um requisito com IA e gera Flow DSL automaticamente."""

    async def _analyze():
        from ai_engine.requirement_agent.agent import RequirementAgent

        rprint(BANNER)
        rprint(f"\n[bold]Analisando requisito:[/bold] [cyan]{requirement[:80]}...[/cyan]\n")

        agent    = RequirementAgent()
        analysis = await agent.analyze(requirement, req_id)

        console.print(Panel(analysis.interpreted_intent, title="Intenção Interpretada", border_style="cyan"))

        if analysis.business_rules:
            t = Table(title="Regras de Negócio", show_header=True, header_style="bold")
            t.add_column("Regra")
            t.add_column("Entidades")
            for r in analysis.business_rules:
                t.add_row(r.description[:60], ", ".join(r.entities[:3]))
            console.print(t)

        if analysis.ambiguities:
            rprint("\n[yellow]⚠ Ambiguidades detectadas:[/yellow]")
            for a in analysis.ambiguities:
                rprint(f"  • {a}")

        rprint("\n[bold]DSL Gerado:[/bold]")
        console.print(Syntax(analysis.generated_flow_dsl, "gherkin", theme="monokai"))

        if save_flow:
            save_flow.write_text(analysis.generated_flow_dsl, encoding="utf-8")
            rprint(f"\n[green]✓ Flow salvo em:[/green] {save_flow}")

    asyncio.run(_analyze())


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Host"),
    port: int = typer.Option(8080, help="Porta"),
    reload: bool = typer.Option(False, help="Hot reload"),
):
    """Inicia o servidor FastAPI do Runtime Core."""
    import uvicorn
    rprint(BANNER)
    rprint(f"[bold green]Servidor iniciando em http://{host}:{port}[/bold green]")
    rprint(f"[dim]Docs: http://{host}:{port}/docs[/dim]\n")
    uvicorn.run("runtime_core.api:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
