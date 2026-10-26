"""Fixed-endpoint transport fixtures: never call Google or use real credentials."""
import json
from unittest.mock import Mock
import pytest
import httpx
from cryptography.fernet import Fernet
from app import gmail_google as google
from app.config import settings
from app.gmail_google import GoogleClient, GoogleFailure, SCOPE

@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv('GOOGLE_CLIENT_ID','test-client');monkeypatch.setenv('GOOGLE_CLIENT_SECRET','test-secret')
    monkeypatch.setenv('GMAIL_ENCRYPTION_KEY',Fernet.generate_key().decode())
    monkeypatch.setenv('GMAIL_REDIRECT_URI','http://localhost:8000/api/gmail/oauth/callback')
    monkeypatch.setenv('GMAIL_FRONTEND_URL','http://localhost:5173');monkeypatch.setenv('CORS_ORIGINS','http://localhost:5173');settings.cache_clear()
    yield
    settings.cache_clear()


def transport(monkeypatch,replies):
    from urllib.parse import parse_qsl
    calls=[];replies=iter(replies)
    original=httpx.Client
    def handler(request):
        calls.append((request.method,str(request.url),{'data':dict(parse_qsl(request.content.decode())), 'headers':{'Authorization':request.headers['Authorization']} if 'Authorization' in request.headers else {}}))
        status,body,headers=next(replies)
        return httpx.Response(status,content=json.dumps(body).encode(),headers=headers,request=request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return original(transport=httpx.MockTransport(handler),**kwargs)
    monkeypatch.setattr(google.httpx,'Client',client)
    monkeypatch.setattr(google.time,'sleep',lambda seconds:None)
    return calls


def test_refresh_and_authorization_code_use_post_body_not_query(config,monkeypatch):
    calls=transport(monkeypatch,[(200,{'access_token':'fresh','scope':SCOPE},{}),(200,{'access_token':'fresh','scope':SCOPE},{}),(200,{'emailAddress':'test@example.com'}, {})])
    client=GoogleClient();client.exchange('authorization-code','pkce-verifier');client.refresh('refresh-secret');client.profile()
    assert calls[0][2]['data']['code_verifier']=='pkce-verifier'
    assert calls[1][2]['data']['refresh_token']=='refresh-secret'
    assert calls[2][2]['headers']=={'Authorization':'Bearer fresh'}
    assert all('secret' not in url and 'authorization-code' not in url for _,url,_ in calls)


def test_rate_limit_retries_are_bounded_and_retry_after_respected(monkeypatch):
    calls=transport(monkeypatch,[(429,{}, {'Retry-After':'1'}),(429,{},{}),(429,{},{})])
    with pytest.raises(GoogleFailure) as error:GoogleClient('token').profile()
    assert error.value.kind=='rate_limited' and len(calls)==3

@pytest.mark.parametrize('status,body,kind',[(400,{'error':'invalid_grant'},'revoked'),(401,{},'revoked'),(404,{},'not_found'),(403,{'error':{'errors':[{'reason':'userRateLimitExceeded'}]}},'rate_limited'),(403,{},'permission_denied'),(302,{},'unavailable')])
def test_safe_error_mapping(monkeypatch,status,body,kind):
    transport(monkeypatch,[(status,body,{})])
    with pytest.raises(GoogleFailure) as error:GoogleClient('token').profile()
    assert error.value.kind==kind and 'token' not in str(error.value)


def test_response_size_and_request_budget(monkeypatch):
    transport(monkeypatch,[(200,{'large':'x'*(4*1024*1024)},{})])
    with pytest.raises(GoogleFailure):GoogleClient('token').profile()
    client=GoogleClient('token');client.requests=35
    with pytest.raises(GoogleFailure) as error:client.profile()
    assert error.value.kind=='paused'


def test_refresh_rejects_missing_scope(config,monkeypatch):
    transport(monkeypatch,[(200,{'access_token':'fresh','scope':'unrelated'}, {})])
    with pytest.raises(GoogleFailure) as error:GoogleClient().refresh('refresh-secret')
    assert error.value.kind=='permission_denied'


def test_invalid_encryption_and_redirects_fail_closed(config,monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setenv('GMAIL_REDIRECT_URI','http://evil.example/api/gmail/oauth/callback');settings.cache_clear()
    with pytest.raises(HTTPException):google.configured()
    monkeypatch.setenv('GMAIL_REDIRECT_URI','http://localhost:8000/api/gmail/oauth/callback')
    monkeypatch.setenv('GMAIL_ENCRYPTION_KEY','not-a-key');settings.cache_clear()
    with pytest.raises(HTTPException):google.configured()
