#!/usr/bin/env python3
"""Point d'entrée CLI pour le serveur HITL FastAPI."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import click
import uvicorn
from dotenv import load_dotenv

load_dotenv()


@click.command()
@click.option("--host", default=lambda: os.getenv("HITL_HOST", "0.0.0.0"), show_default=True)
@click.option("--port", default=lambda: int(os.getenv("HITL_PORT", "8001")), type=int, show_default=True)
@click.option("--reload", is_flag=True, help="Rechargement automatique (dev uniquement).")
def main(host: str, port: int, reload: bool) -> None:
    """Lance le serveur HITL sur host:port."""
    uvicorn.run("hitl.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
