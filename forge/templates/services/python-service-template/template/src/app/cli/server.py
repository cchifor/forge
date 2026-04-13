import typer
import uvicorn

server_app = typer.Typer()


@server_app.command("run")
def run(
    port: int = typer.Option(None, help="Override server port"),
    host: str = typer.Option(None, help="Override server host"),
    reload: bool = typer.Option(False, help="Enable auto-reload"),
    workers: int = typer.Option(None, help="Number of workers"),
    log_level: str = typer.Option(None, help="Uvicorn log level"),
):
    """Start the application server."""
    try:
        from app.core.config import get_settings

        settings = get_settings()
        _port = port or settings.server.port
        _host = host or settings.server.host
        _log_level = log_level or settings.server.log_level
        _workers = workers or settings.server.max_workers
    except Exception:
        _port = port or 5000
        _host = host or "0.0.0.0"
        _log_level = log_level or "info"
        _workers = workers or 1

    uvicorn.run(
        "app.main:app",
        host=_host,
        port=_port,
        reload=reload,
        workers=_workers,
        log_level=_log_level,
    )
