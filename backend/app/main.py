from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.branding import PRODUCT_NAME
from app.config import get_settings
from app.db import get_engine
from app.aktualisierung import router as update_router
from app.belege_routes import router as belege_router
from app.routes import router

settings = get_settings()
app = FastAPI(title=PRODUCT_NAME)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="buchhaltung",
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=settings.cookie_secure,
)
app.include_router(router)
app.include_router(belege_router)
app.include_router(update_router)


@app.on_event("startup")
def _startup() -> None:
    from app.migration import migrationen_anwenden

    get_engine()
    migrationen_anwenden()
    from app.db import get_session
    from app.seed import seed_if_empty

    with get_session() as session:
        try:
            if seed_if_empty(session) is not None:
                session.commit()
        except ValueError as exc:
            session.rollback()
            print(f"Seed übersprungen: {exc}")


@app.exception_handler(ValueError)
def _value_error(_request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})
