"""Production static hosting and response hardening; no authentication shortcuts."""
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import text
from .db import engine


def install_hosting(app, config):
    if config.app_env == 'production':
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(config.app_origin).hostname])

    @app.middleware('http')
    async def security_headers(request, call_next):
        # The ASGI server accepts forwarded headers only from configured proxies.
        if config.app_env == 'production' and request.url.scheme != 'https':
            response = JSONResponse({'error': {'message': 'HTTPS required'}}, status_code=400)
        else:
            response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Cache-Control'] = 'no-store'
        if config.app_env == 'production':
            supabase = urlsplit(config.supabase_url)
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                f"connect-src 'self' https://{supabase.netloc}; "
                "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")
            if request.url.scheme == 'https':
                response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    @app.get('/ready')
    def ready():
        try:
            with engine.connect() as connection:
                connection.execute(text('SELECT 1'))
        except Exception:
            return JSONResponse({'status': 'unavailable'}, status_code=503)
        return {'status': 'ready'}

    if not config.static_dir:
        return
    root = Path(config.static_dir).resolve()
    if not (root / 'index.html').is_file():
        raise RuntimeError('STATIC_DIR must contain the compiled frontend')
    app.mount('/assets', StaticFiles(directory=root / 'assets'), name='assets')

    @app.get('/{path:path}', include_in_schema=False)
    def frontend(path: str):
        if path == 'api' or path.startswith(('api/', '.')) or any(part.startswith('.') for part in path.split('/')):
            raise HTTPException(404, 'Not found')
        candidate = (root / path).resolve()
        if not candidate.is_relative_to(root):
            raise HTTPException(404, 'Not found')
        if candidate.is_file():
            return FileResponse(candidate)
        if Path(path).suffix:
            raise HTTPException(404, 'Not found')
        return FileResponse(root / 'index.html')
