import subprocess
import sys

import typer

db_app = typer.Typer()


@db_app.command("upgrade")
def upgrade(revision: str = typer.Argument("head", help="Target revision")):
    """Run database migrations to the target revision."""
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        check=True,
    )


@db_app.command("downgrade")
def downgrade(revision: str = typer.Argument(..., help="Target revision")):
    """Downgrade database to the target revision."""
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", revision],
        check=True,
    )


@db_app.command("revision")
def revision(
    message: str = typer.Option(..., "-m", help="Revision message"),
    autogenerate: bool = typer.Option(True, help="Auto-generate from models"),
):
    """Create a new migration revision."""
    cmd = [sys.executable, "-m", "alembic", "revision", "-m", message]
    if autogenerate:
        cmd.append("--autogenerate")
    subprocess.run(cmd, check=True)
