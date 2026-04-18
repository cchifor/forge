"""`app rag` — ingest a text file into the RAG vector store.

Only useful when ``rag_pipeline`` is enabled. Reads the file, chunks it,
embeds via OpenAI, writes to pgvector in a single transaction. Fails
loud with a clear message if the feature isn't enabled.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Annotated

import typer

rag_app = typer.Typer(help="RAG operations")


@rag_app.command("ingest")
def ingest(
    path: Annotated[Path, typer.Argument(help="Path to a UTF-8 text file")],
    name: Annotated[str, typer.Option("--name", "-n")] = "",
) -> None:
    """Ingest a text file into the RAG vector store."""
    if not path.is_file():
        typer.echo(f"not a file: {path}", err=True)
        raise typer.Exit(code=1)
    try:
        import os

        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.rag.chunker import chunk_text  # type: ignore
        from app.rag.embeddings import embed  # type: ignore
        from app.rag.vector_store import store_chunks  # type: ignore
    except ImportError:
        typer.echo("rag_pipeline feature not enabled", err=True)
        raise typer.Exit(code=1) from None

    text = path.read_text(encoding="utf-8")
    chunks = chunk_text(text)
    if not chunks:
        typer.echo("no chunks produced (file too short?)", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"chunked into {len(chunks)} blocks; embedding ...")

    async def _run() -> int:
        embeddings = await embed(chunks)
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL not set")
        if url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        customer_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
        async with session_factory() as session:
            doc_id = uuid.uuid4()
            count = await store_chunks(
                session=session,
                document_id=doc_id,
                doc_name=name or path.name,
                customer_id=customer_id,
                user_id=customer_id,
                chunks=chunks,
                embeddings=embeddings,
            )
            await session.commit()
            return count

    count = asyncio.run(_run())
    typer.echo(f"ingested {count} chunks")
