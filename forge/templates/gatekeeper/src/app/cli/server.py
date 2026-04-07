import logging

import typer
import uvicorn

from app.core.config import settings

logger = logging.getLogger(__name__)
server_cli = typer.Typer(help="Application server commands.")


@server_cli.command("run")
def run_server(
    port: int = typer.Option(None, help="Port to bind"),
    host: str = typer.Option(None, help="Host to bind"),
    reload: bool = typer.Option(None, help="Enable auto-reload"),
    workers: int = typer.Option(None, help="Number of worker processes"),
    log_level: str = typer.Option(None, help="Log level (debug, info, warning)"),
):
    """
    Start the Uvicorn server.
    """
    try:
        final_port = port if port is not None else settings.server.port
        final_host = host if host is not None else settings.server.host
        final_reload = reload if reload is not None else settings.server.reload
        final_log = log_level if log_level is not None else settings.server.log_level
    except Exception:
        logger.warning("Failed to load settings, using CLI args or defaults")
        final_port = port if port is not None else 8000
        final_host = host if host is not None else "0.0.0.0"
        final_reload = reload if reload is not None else False
        final_log = log_level if log_level is not None else "info"

    uvicorn_kwargs = {
        "host": final_host,
        "port": final_port,
        "log_level": final_log.lower(),
        "reload": final_reload,
    }

    if not final_reload and workers:
        uvicorn_kwargs["workers"] = workers

    logger.info(f"Starting Server: {uvicorn_kwargs}")
    uvicorn.run("app.main:app", **uvicorn_kwargs)
