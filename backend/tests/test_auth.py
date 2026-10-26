from datetime import datetime, timedelta, timezone
from uuid import UUID
from unittest.mock import Mock
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app import auth

OWNER='11111111-1111-4111-8111-111111111111'
@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL','https://test.supabase.co')
    monkeypatch.setenv('OWNER_ID',OWNER)
    settings.cache_clear()
    yield
    settings.cache_clear()

def test_missing_config(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL','');settings.cache_clear()
    assert TestClient(app).get('/api/applications').status_code == 503
    settings.cache_clear()

def test_rejections(config,monkeypatch):
    client=TestClient(app)
    assert client.get('/api/applications').status_code == 401
    assert client.get('/api/applications',headers={'Authorization':'Basic abc'}).status_code == 401
    assert client.get('/api/applications',headers={'Authorization':'Bearer broken'}).status_code == 401

@pytest.mark.parametrize('change,status',[({},200),({'aud':'wrong'},401),({'iss':'https://wrong'},401),({'exp':0},401),({'sub':'bad'},401),({'sub':'22222222-2222-4222-8222-222222222222'},403),({'exp':None},401)])
def test_signed_claims(config,monkeypatch,change,status):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    claims={'sub':OWNER,'aud':'authenticated','iss':'https://test.supabase.co/auth/v1','exp':datetime.now(timezone.utc)+timedelta(minutes=5)}
    claims.update(change)
    if claims.get('exp') is None: del claims['exp']
    token=jwt.encode(claims,key,algorithm='RS256',headers={'kid':'test-key'})
    client=Mock();client.get_signing_key_from_jwt.return_value=Mock(key=key.public_key())
    monkeypatch.setattr(auth,'jwks_client',lambda url:client)
    from fastapi.security import HTTPAuthorizationCredentials
    if status==200:
        assert auth.current_owner(HTTPAuthorizationCredentials(scheme='Bearer',credentials=token))==UUID(OWNER)
    else:
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as error: auth.current_owner(HTTPAuthorizationCredentials(scheme='Bearer',credentials=token))
        assert error.value.status_code==status

def test_signature_and_key_selection(config, monkeypatch):
    from jwt import PyJWKClient
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    wrong=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    public=jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(),as_dict=True)
    public.update(kid='known',use='sig',alg='RS256')
    jwks=PyJWKClient('https://test.invalid/jwks')
    monkeypatch.setattr(jwks,'fetch_data',lambda:{'keys':[public]})
    monkeypatch.setattr(auth,'jwks_client',lambda url:jwks)
    claims={'sub':OWNER,'aud':'authenticated','iss':'https://test.supabase.co/auth/v1','exp':datetime.now(timezone.utc)+timedelta(minutes=5)}
    for signing,kid in [(wrong,'known'),(key,'unknown')]:
        token=jwt.encode(claims,signing,algorithm='RS256',headers={'kid':kid})
        assert TestClient(app).get('/api/applications',headers={'Authorization':'Bearer '+token}).status_code==401
