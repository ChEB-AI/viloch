"""The standalone page: ASP text <-> block editor, with explanations (``viloch serve``)."""

from __future__ import annotations

import os

from starlette.applications import Starlette
from starlette.responses import FileResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from viloch.definition import DEFAULT_TARGET
from viloch.web.api import make_routes

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def create_app(
    library_dir: str | None = None, target: str = DEFAULT_TARGET
) -> Starlette:
    async def index(request):
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    return Starlette(
        routes=[
            Route("/", index),
            Mount("/api", routes=make_routes(library_dir=library_dir, target=target)),
            Mount("/static", app=StaticFiles(directory=STATIC_DIR)),
        ]
    )
