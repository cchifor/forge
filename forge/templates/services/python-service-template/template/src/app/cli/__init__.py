import typer

from app.cli.db import db_app
from app.cli.server import server_app
# FORGE:CLI_IMPORTS

cli = typer.Typer(name="app", help="Service CLI")
cli.add_typer(server_app, name="server", help="Server management")
cli.add_typer(db_app, name="db", help="Database migrations")
# FORGE:CLI_REGISTRATION
