from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.config import Settings
from app.db import database_url
from app.hosting import install_hosting


def production(**overrides):
    values = dict(_env_file=None, app_env='production', app_origin='https://applytrack.example',
                  cors_origins='https://applytrack.example', owner_id='11111111-1111-4111-8111-111111111111',
                  supabase_url='https://example.supabase.co',
                  database_url='postgresql://user:placeholder@db.example/app?sslmode=require')
    return Settings(**(values | overrides))


@pytest.mark.parametrize('changes', [
    {'app_origin': 'http://example.com'}, {'app_origin': 'https://example.com/'},
    {'cors_origins': '*'}, {'owner_id': ''}, {'supabase_url': 'http://example.com'},
    {'database_url': 'postgresql://user:placeholder@db.example/app'},
    {'migration_database_url': 'postgresql://user:placeholder@db.example/app'},
    {'google_client_id': 'example-client'},
])
def test_production_fails_closed(changes):
    with pytest.raises((ValidationError, ValueError)):
        production(**changes)


def test_managed_database_and_gmail_settings():
    config = production(google_client_id='example-client', gmail_redirect_uri='https://applytrack.example/api/gmail/oauth/callback',
                        gmail_frontend_url='https://applytrack.example')
    url = database_url(config.database_url)
    assert url.drivername == 'postgresql+psycopg'
    assert url.query['sslmode'] == 'require'


@pytest.fixture
def web(tmp_path):
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets' / 'app.js').write_text('console.log("demo")')
    (tmp_path / 'index.html').write_text('<html>ApplyTrack demo</html>')
    app = FastAPI()
    @app.get('/api/private')
    def private():
        from fastapi import HTTPException
        raise HTTPException(401)
    install_hosting(app, production(static_dir=str(tmp_path)))
    return TestClient(app, base_url='https://applytrack.example')


def test_frontend_refresh_and_assets(web):
    assert 'ApplyTrack demo' in web.get('/applications/demo').text
    assert web.get('/assets/app.js').status_code == 200
    assert web.get('/assets/missing.js').status_code == 404
    assert web.get('/missing.png').status_code == 404


@pytest.mark.parametrize('path', ['/api/private', '/api/missing', '/api', '/.env', '/anything/.env', '/%2e%2e/.env'])
def test_spa_never_exposes_private_paths(web, path):
    response = web.get(path)
    assert response.status_code in {401, 404}
    assert 'ApplyTrack demo' not in response.text


def test_https_hosts_and_security_headers(web):
    response = web.get('/')
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['strict-transport-security'] == 'max-age=31536000'
    assert "frame-ancestors 'none'" in response.headers['content-security-policy']
    assert web.get('http://applytrack.example/').status_code == 400
    assert web.get('https://evil.example/').status_code == 400


def test_readiness_failure_is_sanitized(web, monkeypatch):
    from app import hosting
    engine = Mock()
    engine.connect.side_effect = RuntimeError('private connection details')
    monkeypatch.setattr(hosting, 'engine', engine)
    response = web.get('/ready')
    assert response.status_code == 503
    assert response.json() == {'status': 'unavailable'}


def test_port_validation(monkeypatch):
    from app import serve
    monkeypatch.setenv('PORT', '65536')
    with pytest.raises(ValueError):
        serve.main()


def test_dynamic_port_and_graceful_shutdown(monkeypatch):
    from app import serve
    run = Mock()
    monkeypatch.setattr(serve.uvicorn, 'run', run)
    monkeypatch.setenv('PORT', '4321')
    serve.main()
    assert run.call_args.kwargs['port'] == 4321
    assert run.call_args.kwargs['timeout_graceful_shutdown'] == 60
    assert run.call_args.kwargs['access_log'] is False


def test_production_configuration_errors_do_not_print_input_secrets():
    with pytest.raises(ValidationError) as error:
        production(database_url='postgresql://user:private-placeholder@db.example/app')
    assert 'private-placeholder' not in str(error.value)


def test_all_api_routes_require_owner_except_bound_oauth_callback(monkeypatch):
    import re
    from app.main import app
    from app.config import settings
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('OWNER_ID', '11111111-1111-4111-8111-111111111111')
    settings.cache_clear()
    try:
        paths = {path: methods for path, methods in app.openapi()['paths'].items()
                 if path.startswith('/api/') and path != '/api/gmail/oauth/callback'}
        assert len(paths) >= 15
        with TestClient(app) as client:
            for path, methods in paths.items():
                concrete = re.sub(r'\{[^}]+\}', '11111111-1111-4111-8111-111111111111', path)
                for method in methods:
                    if method in {'get', 'post', 'patch', 'delete'}:
                        assert client.request(method, concrete).status_code == 401, (method, path)
    finally:
        settings.cache_clear()
