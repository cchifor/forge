import typer

from app.cli.server import server_cli

cli = typer.Typer(
    name="gatekeeper",
    help="Gatekeeper Command Line Interface",
    no_args_is_help=True,
)
cli.add_typer(server_cli, name="server", help="Start the application server")
