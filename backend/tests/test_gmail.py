import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4
from unittest.mock import Mock
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import select, func
from app import gmail, gmail_sync, gmail_google, gmail_analysis
from app.auth import current_owner
from app.config import settings
from app.main import app
from app.models import Application, Event, now
from app.gmail_models import GmailConnection, GmailMessage, GmailMatchRule, GmailOAuthState
from app.gmail_google import GoogleFailure, encrypt, decrypt, SCOPE
from app.gmail_analysis import parse_message, classify, match_applications
from conftest import OWNER, OTHER

FIXTURES=json.loads((Path(__file__).parent/'fixtures/gmail/labeled.json').read_text())

@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv('GOOGLE_CLIENT_ID','test-client')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET','test-secret')
    monkeypatch.setenv('GMAIL_ENCRYPTION_KEY',Fernet.generate_key().decode())
    monkeypatch.setenv('GMAIL_REDIRECT_URI','http://testserver/api/gmail/oauth/callback')
    monkeypatch.setenv('GMAIL_FRONTEND_URL','http://localhost:5173')
    monkeypatch.setenv('CORS_ORIGINS','http://localhost:5173')
    # testserver is not a valid configured redirect host; use localhost callback
    monkeypatch.setenv('GMAIL_REDIRECT_URI','http://localhost:8000/api/gmail/oauth/callback')
    settings.cache_clear()
    yield
    settings.cache_clear()


def raw(body='',subject='Application update',id='m1',at=None,sender='recruiting@example.com',verified=True,**extras):
    at=at or now()-timedelta(minutes=1)
    headers=[{'name':'Subject','value':subject},{'name':'From','value':sender}]
    if verified:headers.append({'name':'Authentication-Results','value':'mx.google.com; dkim=pass header.d='+sender.split('@')[-1]})
    value={'id':id,'internalDate':str(int(at.timestamp()*1000)),'labelIds':['INBOX'],'payload':{'mimeType':'text/plain','headers':headers,'body':{'data':base64.urlsafe_b64encode(body.encode()).decode()}}}
    value.update(extras)
    return value


def application(db,owner=OWNER,**values):
    data=dict(company_name='Example Labs',job_title='Backend Engineer',job_url='https://careers.example.com/jobs/ENG-1234',external_job_id='ENG-1234',status='Applied',owner_id=owner,status_changed_at=now()-timedelta(days=30),status_manual_at=now()-timedelta(days=30))
    data.update(values);item=Application(**data);db.add(item);db.flush();return item


def connection(db,auto=False):
    item=GmailConnection(owner_id=OWNER,email='owner@example.com',encrypted_refresh=encrypt(OWNER,'refresh-secret'),auto_updates=auto,auto_enabled_at=now()-timedelta(days=1) if auto else None,lookback_days=30)
    db.add(item);db.flush();return item


def message(db,conn,body=None,id='m1',at=None,**kwargs):
    return gmail_sync.process(db,conn,raw(body or 'We invite you to an interview for Backend Engineer at Example Labs. Job ENG-1234.',id=id,at=at,**kwargs))


@pytest.mark.parametrize('fixture',FIXTURES,ids=lambda f:f['subject'])
def test_labeled_classification(fixture):
    result=classify(parse_message(raw(fixture['body'],fixture['subject'])))
    assert result[0]==fixture['label']
    if result[1]>=.99:assert fixture['label'] in gmail_analysis.TARGETS


def test_fixture_precision_report():
    results=[(classify(parse_message(raw(f['body'],f['subject']))),f['label']) for f in FIXTURES]
    high=[(result,label) for result,label in results if result[1]>=.99]
    correct=sum(result[0]==label for result,label in high)
    accuracy=sum(result[0]==label for result,label in results)
    print(f'CLASSIFICATION FIXTURES: high-confidence precision {correct}/{len(high)}; overall labels {accuracy}/{len(results)}. Synthetic fixtures do not establish real-world accuracy.')
    assert correct==len(high) and accuracy==len(results)


def test_html_quotes_and_attachments_are_excluded():
    data=raw()
    data['payload'].update(mimeType='multipart/mixed',parts=[{'mimeType':'text/html','body':{'data':base64.urlsafe_b64encode(b'<p>Recruiting update</p><blockquote>We are pleased to offer you the role.</blockquote><script>bad()</script>').decode()}},{'mimeType':'text/plain','filename':'attachment.txt','body':{'data':base64.urlsafe_b64encode(b'We are pleased to offer you the position.').decode()}}])
    parsed=parse_message(data)
    assert 'pleased' not in parsed.body and 'bad()' not in parsed.body
    assert classify(parsed)[0]=='recruiter'


def test_matching_multiple_applications_and_explicit_identifiers(db):
    one=application(db);two=application(db,job_title='Frontend Engineer',external_job_id='FRONT-5678')
    winner,evidence=match_applications(parse_message(raw('Backend Engineer at Example Labs job ENG-1234')), [one,two],{})
    assert winner['application_id']==str(one.id) and winner['score']==.99
    assert len(evidence)==2
    winner,_=match_applications(parse_message(raw('Your application at Example Labs')), [one,two],{})
    assert winner is None
    third=application(db,external_job_id='ENG-9999')
    winner,_=match_applications(parse_message(raw('Your Backend Engineer application at Example Labs')), [one,third],{})
    assert winner is None


def test_alias_url_and_sender_evidence(db):
    item=application(db)
    rule=GmailMatchRule(application_id=item.id,aliases=['Example Corporation'],sender_domains=['example.com'])
    winner,_=match_applications(parse_message(raw('Backend Engineer at Example Corporation https://careers.example.com/jobs/ENG-1234?utm_source=email')),[item],{item.id:rule})
    assert winner['score']==.99 and winner['trusted_sender']
    unsigned,_=match_applications(parse_message(raw('Backend Engineer at Example Labs ENG-1234',verified=False)),[item],{})
    assert not unsigned['trusted_sender']


def test_match_precision_report(db):
    one=application(db);two=application(db,job_title='Frontend Engineer',external_job_id='FRONT-5678')
    examples=[('Backend Engineer at Example Labs ENG-1234',one.id),('Frontend Engineer at Example Labs FRONT-5678',two.id),('Your application at Example Labs',None),('Example Labs',None)]
    predicted=[]
    for text,expected in examples:
        winner,_=match_applications(parse_message(raw(text)),[one,two],{})
        actual=UUID(winner['application_id']) if winner else None
        assert actual==expected
        if actual:predicted.append(actual==expected)
    print(f'MATCH FIXTURES: unique-match precision {sum(predicted)}/{len(predicted)}; abstained {len(examples)-len(predicted)}/{len(examples)}. Synthetic fixtures only.')


def test_dry_run_is_default_and_approval_undo_audit(client,db,config):
    item=application(db);conn=connection(db)
    assert message(db,conn)==(1,1,0)
    db.commit();suggestion=db.scalar(select(GmailMessage))
    assert suggestion.state=='review' and db.get(Application,item.id).status=='Applied'
    response=client.post(f'/api/gmail/messages/{suggestion.id}/accept',json={'application_id':str(item.id),'status':'Interview','expected_revision':item.status_revision})
    assert response.status_code==200
    assert db.get(Application,item.id).status=='Interview'
    assert client.post(f'/api/gmail/messages/{suggestion.id}/undo').status_code==200
    assert db.get(Application,item.id).status=='Applied'
    events=db.scalars(select(Event).where(Event.application_id==item.id)).all()
    assert [event.source for event in events]==['gmail_review','gmail_undo']
    assert all(event.source_message_id=='m1' for event in events)
    assert client.post(f'/api/gmail/messages/{suggestion.id}/undo').status_code==409


def test_automatic_update_and_duplicate_idempotence(db,config):
    item=application(db);conn=connection(db,auto=True)
    assert message(db,conn)==(1,1,1);db.flush()
    assert item.status=='Interview'
    assert message(db,conn)==(0,0,0)
    assert db.scalar(select(func.count()).select_from(Event))==1
    saved=db.scalar(select(GmailMessage));assert saved.state=='applied' and saved.old_status=='Applied'

@pytest.mark.parametrize('status,manual_newer,source_newer',[('Offer',False,False),('Rejected',False,False),('Withdrawn',False,False),('Applied',True,False),('Applied',False,True),('Interview',False,False)])
def test_auto_protects_terminal_manual_newer_and_noop(db,config,status,manual_newer,source_newer):
    item=application(db,status=status);conn=connection(db,auto=True)
    if manual_newer:item.status_manual_at=now()
    if source_newer:item.status_changed_at=now()
    assert message(db,conn)[2]==0
    assert item.status==status


def test_out_of_order_events_never_reverse_newer_status(db,config):
    item=application(db);conn=connection(db,auto=True)
    recent=now()-timedelta(minutes=1)
    assert message(db,conn,id='newer',at=recent)[2]==1
    assert message(db,conn,body='Please complete our assessment for Backend Engineer at Example Labs ENG-1234.',id='older',at=recent-timedelta(hours=1))[2]==0
    assert item.status=='Interview'


def test_unverified_sender_future_email_and_pre_enable_email_require_review(db,config):
    item=application(db);conn=connection(db,auto=True)
    for index,options in enumerate([{'verified':False},{'at':now()+timedelta(days=2)},{'at':now()-timedelta(days=2)}]):
        assert message(db,conn,id=str(index),**options)[2]==0
    assert item.status=='Applied'


def test_manual_noop_correction_and_undo_revision_protection(client,db,config):
    item=application(db);conn=connection(db,auto=True);message(db,conn);db.commit()
    suggestion=db.scalar(select(GmailMessage))
    # Explicitly re-selecting Interview is a manual correction, even if unchanged.
    client.patch(f'/api/applications/{item.id}',json={'status':'Interview'})
    assert client.post(f'/api/gmail/messages/{suggestion.id}/undo').status_code==409
    assert db.get(Application,item.id).status=='Interview'


def test_stale_review_revision_and_dismissal(client,db,config):
    item=application(db);conn=connection(db);message(db,conn);db.commit();suggestion=db.scalar(select(GmailMessage))
    previous=item.status_revision
    client.patch(f'/api/applications/{item.id}',json={'status':'Rejected'})
    assert client.post(f'/api/gmail/messages/{suggestion.id}/accept',json={'application_id':str(item.id),'status':'Interview','expected_revision':previous}).status_code==409
    assert client.post(f'/api/gmail/messages/{suggestion.id}/dismiss').status_code==200
    assert client.post(f'/api/gmail/messages/{suggestion.id}/dismiss').status_code==409


def test_owner_isolation_on_all_gmail_data(client,db,config):
    item=application(db);conn=connection(db);message(db,conn);db.commit();suggestion=db.scalar(select(GmailMessage))
    app.dependency_overrides[current_owner]=lambda:OTHER
    assert client.get('/api/gmail/connection').json()['connected'] is False
    assert client.get('/api/gmail/messages').json()['total']==0
    for action in ['dismiss','undo']:
        assert client.post(f'/api/gmail/messages/{suggestion.id}/{action}').status_code==404
    assert client.post(f'/api/gmail/messages/{suggestion.id}/accept',json={'application_id':str(item.id),'status':'Interview','expected_revision':0}).status_code==404
    assert client.patch(f'/api/gmail/rules/{item.id}',json={'aliases':['Other name']}).status_code==404
    assert client.get(f'/api/gmail/rules/{item.id}').status_code==404
    assert client.post('/api/gmail/disconnect',json={}).status_code==200
    assert db.get(GmailConnection,OWNER).encrypted_refresh


def test_alias_rules_and_validation(client,db):
    item=application(db);db.commit()
    response=client.patch(f'/api/gmail/rules/{item.id}',json={'aliases':['Example Corporation'],'sender_domains':['EXAMPLE.COM']})
    assert response.json()['sender_domains']==['example.com']
    assert client.get(f'/api/gmail/rules/{item.id}').json()['aliases']==['Example Corporation']
    assert client.patch(f'/api/gmail/rules/{item.id}',json={'sender_domains':['gmail.com']}).status_code==422


def test_enable_requires_completed_dry_run_and_owner_ack(client,db,config):
    conn=connection(db);db.commit()
    assert client.patch('/api/gmail/settings',json={'auto_updates':True,'reviewed_dry_run':True}).status_code==409
    application(db);message(db,conn);conn.dry_run_at=now();db.commit()
    assert client.patch('/api/gmail/settings',json={'auto_updates':True}).status_code==409
    assert client.patch('/api/gmail/settings',json={'auto_updates':True,'reviewed_dry_run':True}).json()['auto_updates'] is True
    assert client.patch('/api/gmail/settings',json={'auto_updates':False}).json()['auto_updates'] is False
    assert client.patch('/api/gmail/settings',json={'lookback_days':366}).status_code==422


class FakeGoogle:
    def __init__(self,items=None):
        self.items=items or {'m1':raw('We invite you to an interview for Backend Engineer at Example Labs ENG-1234.')}
        self.message_calls=[];self.pages=[]
    def refresh(self,token):assert token=='refresh-secret';return {'access_token':'access-only-in-memory'}
    def profile(self):return {'historyId':'100','emailAddress':'owner@example.com'}
    def messages(self,query,page=None):self.pages.append((query,page));return {'messages':[{'id':key} for key in self.items]}
    def history(self,start,page=None):return {'historyId':'200','history':[{'messagesAdded':[{'message':{'id':key}} for key in self.items]}]}
    def message(self,id):self.message_calls.append(id);return self.items[id]


def test_sync_and_incremental_dedup(db,config):
    item=application(db);conn=connection(db);google=FakeGoogle()
    gmail_sync.synchronize(db,conn,google)
    assert conn.history_id=='100' and conn.last_sync_at and conn.dry_run_at
    assert conn.stats['processed']==1 and conn.stats['matches']==1 and conn.stats['updates']==0
    gmail_sync.synchronize(db,conn,google)
    assert google.message_calls==['m1'] and conn.history_id=='200'
    assert db.scalar(select(func.count()).select_from(GmailMessage))==1


def test_paginated_sync_and_partial_checkpoints(db,config):
    application(db);conn=connection(db);google=FakeGoogle()
    google.messages=lambda query,page=None: {'messages':[{'id':'m1'}],'nextPageToken':'page2'} if page is None else {'messages':[{'id':'m1'}]}
    gmail_sync.synchronize(db,conn,google)
    assert conn.pending['page']=='page2' and conn.last_sync_at is None
    gmail_sync.synchronize(db,conn,google)
    assert conn.pending is None and conn.last_sync_at and google.message_calls==['m1']


def test_expired_history_uses_bounded_recovery(db,config):
    application(db);conn=connection(db);conn.history_id='old-history';google=FakeGoogle()
    def expired(*args):raise GoogleFailure('not_found')
    google.history=expired
    gmail_sync.synchronize(db,conn,google)
    assert 'after:' in google.pages[0][0] and 'before:' in google.pages[0][0]
    assert conn.stats['recovered_history'] and conn.history_id=='100'


def test_rate_limit_preserves_resume_and_never_advances_cursor(db,config):
    application(db);conn=connection(db);google=FakeGoogle()
    original=google.message
    google.message=lambda id:(_ for _ in ()).throw(GoogleFailure('rate_limited'))
    gmail_sync.synchronize(db,conn,google)
    assert conn.health=='rate_limited' and conn.history_id is None and conn.pending['ids']==['m1']
    google.message=original;gmail_sync.synchronize(db,conn,google)
    assert conn.health=='connected' and conn.history_id=='100'


def test_revoked_refresh_sets_reconnect_without_leaking_secret(db,config):
    conn=connection(db,auto=True);google=FakeGoogle()
    google.refresh=lambda token:(_ for _ in ()).throw(GoogleFailure('revoked'))
    gmail_sync.synchronize(db,conn,google)
    assert conn.health=='reconnect_required' and not conn.auto_updates
    assert 'refresh-secret' not in str(conn.stats)


def test_token_rotation_and_encryption_owner_binding(db,config):
    conn=connection(db);google=FakeGoogle();google.refresh=lambda token:{'access_token':'a','refresh_token':'rotated-secret'}
    gmail_sync.synchronize(db,conn,google)
    assert 'rotated-secret' not in conn.encrypted_refresh
    assert decrypt(OWNER,conn.encrypted_refresh)=='rotated-secret'
    with pytest.raises(HTTPException):decrypt(OTHER,conn.encrypted_refresh)


def test_disconnect_purges_retained_data_preserves_app_audit(client,db,config,monkeypatch):
    item=application(db);conn=connection(db,auto=True);message(db,conn);db.commit()
    monkeypatch.setattr(gmail.GoogleClient,'revoke',lambda self,token:None)
    assert client.post('/api/gmail/disconnect',json={'delete_data':True}).json()['data_deleted'] is True
    assert db.get(GmailConnection,OWNER) is None
    assert not db.scalars(select(GmailMessage)).all()
    assert db.get(Application,item.id).status=='Interview'
    assert db.scalar(select(Event)).source_message_id=='m1'


def test_missing_config_fails_closed(client,monkeypatch):
    monkeypatch.setenv('GOOGLE_CLIENT_ID','');settings.cache_clear()
    assert client.post('/api/gmail/oauth/start').status_code==503
    assert client.post('/api/gmail/sync').status_code==503
    settings.cache_clear()


def oauth_start(client):
    response=client.post('/api/gmail/oauth/start')
    assert response.status_code==200
    return parse_qs(urlsplit(response.json()['authorization_url']).query)


def test_oauth_state_pkce_cookie_cancel_and_replay(client,db,config):
    query=oauth_start(client)
    assert query['scope']==[SCOPE] and query['access_type']==['offline'] and query['code_challenge_method']==['S256']
    pending=db.get(GmailOAuthState,OWNER)
    verifier=decrypt(OWNER,pending.encrypted_verifier)
    import hashlib
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    assert challenge==query['code_challenge'][0]
    response=client.get('/api/gmail/oauth/callback',params={'state':query['state'][0],'error':'access_denied'},follow_redirects=False)
    assert response.status_code==303 and response.headers['location'].endswith('#gmail=cancelled')
    assert response.headers['referrer-policy']=='no-referrer'
    assert client.get('/api/gmail/oauth/callback',params={'state':query['state'][0],'code':'code'}).status_code==400


def test_oauth_wrong_cookie_expired_state_and_secret_log_redaction(client,db,config):
    query=oauth_start(client);state=query['state'][0]
    client.cookies.clear()
    response=client.get('/api/gmail/oauth/callback?state='+state+'&code=secret-code',follow_redirects=False)
    assert response.status_code==400
    query=oauth_start(client);pending=db.get(GmailOAuthState,OWNER);pending.expires_at=now()-timedelta(seconds=1);db.commit()
    response=client.get('/api/gmail/oauth/callback',params={'state':query['state'][0],'code':'secret-code'},follow_redirects=False)
    assert response.headers['location'].endswith('#gmail=expired')


def test_oauth_exchange_refresh_and_owner_connection(client,db,config,monkeypatch):
    monkeypatch.setattr(gmail.GoogleClient,'exchange',lambda self,code,verifier:{'access_token':'access-secret','refresh_token':'refresh-secret','scope':SCOPE})
    monkeypatch.setattr(gmail.GoogleClient,'profile',lambda self:{'emailAddress':'owner@example.com','historyId':'100'})
    query=oauth_start(client)
    response=client.get('/api/gmail/oauth/callback',params={'state':query['state'][0],'code':'code'},follow_redirects=False)
    assert response.headers['location'].endswith('#gmail=connected')
    conn=db.get(GmailConnection,OWNER)
    assert conn.email=='owner@example.com' and decrypt(OWNER,conn.encrypted_refresh)=='refresh-secret'
    status=client.get('/api/gmail/connection').json()
    assert status['connected'] and not status['auto_updates'] and 'refresh-secret' not in json.dumps(status) and 'access-secret' not in json.dumps(status)


def test_oauth_failure_safe_and_no_connection(client,db,config,monkeypatch):
    monkeypatch.setattr(gmail.GoogleClient,'exchange',lambda *args:(_ for _ in ()).throw(GoogleFailure('revoked')))
    query=oauth_start(client)
    response=client.get('/api/gmail/oauth/callback',params={'state':query['state'][0],'code':'secret-code'},follow_redirects=False)
    assert response.headers['location'].endswith('#gmail=error')
    assert db.get(GmailConnection,OWNER) is None and db.get(GmailOAuthState,OWNER) is None


def test_oauth_cannot_silently_switch_mailboxes(client,db,config,monkeypatch):
    connection(db);db.commit()
    monkeypatch.setattr(gmail.GoogleClient,'exchange',lambda *args:{'access_token':'a','refresh_token':'different-refresh','scope':SCOPE})
    monkeypatch.setattr(gmail.GoogleClient,'profile',lambda self:{'emailAddress':'different@example.com'})
    monkeypatch.setattr(gmail.GoogleClient,'revoke',lambda *args:None)
    query=oauth_start(client)
    response=client.get('/api/gmail/oauth/callback',params={'state':query['state'][0],'code':'code'},follow_redirects=False)
    assert response.headers['location'].endswith('#gmail=account_mismatch')
    assert db.get(GmailConnection,OWNER).email=='owner@example.com'


def test_auth_required(client,config,monkeypatch):
    app.dependency_overrides.pop(current_owner)
    monkeypatch.setenv('SUPABASE_URL','https://test.supabase.co');monkeypatch.setenv('OWNER_ID',str(OWNER));settings.cache_clear()
    for method,path in [('get','connection'),('get','messages'),('post','sync'),('post','oauth/start'),('post','disconnect')]:
        assert getattr(client,method)('/api/gmail/'+path).status_code==401
    settings.cache_clear()


def test_chronological_messages_advance_by_source_time_not_processing_time(db,config):
    item=application(db);conn=connection(db,auto=True)
    assert message(db,conn,body='Please complete our assessment for Backend Engineer at Example Labs ENG-1234.',id='assessment',at=now()-timedelta(minutes=20))[2]==1
    assert message(db,conn,id='interview',at=now()-timedelta(minutes=10))[2]==1
    assert item.status=='Interview'


def test_gmail_dkim_identity_header_and_sender_mismatch():
    payload=raw('Hiring update')
    payload['payload']['headers'][-1]['value']='mx.google.com; dkim=pass header.i=@example.com header.s=selector header.b=signature'
    assert parse_message(payload).dkim_verified
    payload['payload']['headers'][-1]['value']='mx.google.com; dkim=pass header.i=@unrelated.com'
    assert not parse_message(payload).dkim_verified


def test_unknown_and_excluded_messages_keep_only_dedup_tombstones(db,config):
    conn=connection(db)
    gmail_sync.process(db,conn,raw('Newsletter sale',subject='Sale',id='newsletter'))
    gmail_sync.process(db,conn,raw('We are pleased to offer you the role.',id='sent',labelIds=['SENT']))
    db.flush()
    rows=db.scalars(select(GmailMessage)).all()
    assert len(rows)==2 and all(m.state=='ignored' and not m.excerpt and not m.subject and not m.sender for m in rows)
    assert gmail_sync.process(db,conn,raw('Newsletter sale',subject='Sale',id='newsletter'))==(0,0,0)


def test_interview_invitation_does_not_fabricate_a_reminder_or_accepted_date(db,config):
    from app.models import Reminder
    application(db);conn=connection(db,auto=True);message(db,conn);db.flush()
    assert db.scalar(select(func.count()).select_from(Reminder))==0


def test_retention_redacts_text_but_keeps_idempotency(db,config):
    conn=connection(db);google=FakeGoogle({'old':raw('Recruiting at Example Labs',at=now()-timedelta(days=100),id='old')})
    gmail_sync.synchronize(db,conn,google)
    saved=db.scalar(select(GmailMessage))
    assert saved.gmail_id=='old' and saved.subject is None and saved.sender is None and saved.excerpt is None


def test_privacy_middleware_scrubs_callback_query_on_success_and_failure():
    import asyncio
    from uvicorn.protocols.utils import get_path_with_query_string
    async def check(raise_error):
        scope={'type':'http','path':gmail.CALLBACK,'query_string':b'code=secret&state=secret-state'}
        logged=[]
        async def receive():return {'type':'http.request'}
        async def send(message):
            if message['type']=='http.response.start':logged.append(get_path_with_query_string(scope))
        async def inner(scope,receive,send):
            if raise_error:raise RuntimeError('internal failure')
            await send({'type':'http.response.start','status':200,'headers':[]})
        try:await gmail.GmailCallbackPrivacy(inner)(scope,receive,send)
        except RuntimeError:logged.append(get_path_with_query_string(scope))
        assert all('secret' not in line and '?' not in line for line in logged)
    asyncio.run(check(False));asyncio.run(check(True))


def test_older_rejection_cannot_reverse_newer_interview(db,config):
    item=application(db);conn=connection(db,auto=True)
    assert message(db,conn,id='recent',at=now()-timedelta(minutes=5))[2]==1
    assert message(db,conn,body='We are not moving forward with your application for Backend Engineer at Example Labs ENG-1234.',id='old-reject',at=now()-timedelta(hours=1))[2]==0
    assert item.status=='Interview'


def test_wrapped_quote_boundary_does_not_reuse_old_offer():
    email=parse_message(raw('Recruiting update\nOn Monday, Someone\n<someone@example.com>\nwrote:\nWe are pleased to offer you the position.'))
    assert 'pleased' not in email.body and classify(email)[0]=='recruiter'


def test_same_company_same_title_unique_id_disambiguates(db):
    one=application(db);two=application(db,external_job_id='ENG-5678',job_url='https://careers.example.com/jobs/ENG-5678')
    winner,_=match_applications(parse_message(raw('Backend Engineer at Example Labs ENG-1234')),[one,two],{})
    assert winner and winner['application_id']==str(one.id)
    ambiguous,_=match_applications(parse_message(raw('Backend Engineer at Example Labs ENG-1234 and ENG-5678')),[one,two],{})
    assert ambiguous is None


def test_marketplace_domain_is_not_employer_identity(db):
    item=application(db,job_url='https://www.linkedin.com/jobs/view/12345')
    winner,candidates=match_applications(parse_message(raw('Backend Engineer at Example Labs ENG-1234',sender='jobs@linkedin.com')),[item],{})
    assert winner and not winner['trusted_sender']


def test_partial_sync_failure_keeps_committed_message_and_remaining_checkpoint(db,config):
    application(db);conn=connection(db)
    google=FakeGoogle({'one':raw('We invite you to an interview for Backend Engineer at Example Labs ENG-1234.',id='one'),'two':raw('Please complete our assessment for Backend Engineer at Example Labs ENG-1234.',id='two')})
    original=google.message
    def limited(id):
        if id=='two':raise GoogleFailure('rate_limited')
        return original(id)
    google.message=limited
    gmail_sync.synchronize(db,conn,google)
    assert db.scalar(select(func.count()).select_from(GmailMessage))==1
    assert conn.pending['ids']==['two'] and conn.history_id is None
    google.message=original;gmail_sync.synchronize(db,conn,google)
    assert db.scalar(select(func.count()).select_from(GmailMessage))==2 and conn.history_id=='100'
    assert google.message_calls==['one','two']


def test_reconnect_without_new_refresh_token_keeps_existing_ciphertext(client,db,config,monkeypatch):
    connection(db);db.commit()
    monkeypatch.setattr(gmail.GoogleClient,'exchange',lambda *args:{'access_token':'a','scope':SCOPE})
    monkeypatch.setattr(gmail.GoogleClient,'profile',lambda self:{'emailAddress':'owner@example.com'})
    query=oauth_start(client)
    result=client.get('/api/gmail/oauth/callback',params={'state':query['state'][0],'code':'code'},follow_redirects=False)
    assert result.headers['location'].endswith('#gmail=connected')
    assert decrypt(OWNER,db.get(GmailConnection,OWNER).encrypted_refresh)=='refresh-secret'


def test_initial_connection_requires_offline_refresh_token(client,db,config,monkeypatch):
    monkeypatch.setattr(gmail.GoogleClient,'exchange',lambda *args:{'access_token':'a','scope':SCOPE})
    monkeypatch.setattr(gmail.GoogleClient,'profile',lambda self:{'emailAddress':'owner@example.com'})
    query=oauth_start(client)
    result=client.get('/api/gmail/oauth/callback',params={'state':query['state'][0],'code':'code'},follow_redirects=False)
    assert result.headers['location'].endswith('#gmail=error') and db.get(GmailConnection,OWNER) is None


def test_oauth_cookie_flags(client,config):
    response=client.post('/api/gmail/oauth/start')
    cookie=response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=lax' in cookie and 'Max-Age=600' in cookie and 'Path=/api/gmail/oauth/callback' in cookie


def test_empty_or_irrelevant_dry_run_cannot_enable_automation(client,db,config):
    conn=connection(db);google=FakeGoogle({'sale':raw('Newsletter sale',subject='Sale',id='sale')})
    gmail_sync.synchronize(db,conn,google)
    assert conn.last_sync_at and conn.dry_run_at is None
    assert client.patch('/api/gmail/settings',json={'auto_updates':True,'reviewed_dry_run':True}).status_code==409


def test_expired_page_token_recovers_without_duplicate_changes(db,config):
    application(db);conn=connection(db);google=FakeGoogle()
    conn.pending={'kind':'initial','query':'after:1','baseline':'50','page':'expired-page','ids':[],'next':None,'loaded':False,'stats':{'processed':0,'matches':0,'updates':0}}
    original=google.messages
    google.messages=lambda query,page=None:(_ for _ in ()).throw(GoogleFailure('invalid_page')) if page else original(query,page)
    gmail_sync.synchronize(db,conn,google)
    assert conn.pending is None and conn.history_id=='100' and conn.stats['recovered_history']


def test_http_sync_workflow_serializes_stats_and_no_tokens(client,db,config,monkeypatch):
    application(db);connection(db);db.commit()
    fake=FakeGoogle();monkeypatch.setattr(gmail_sync,'GoogleClient',lambda:fake)
    result=client.post('/api/gmail/sync')
    assert result.status_code==200 and result.json()['stats']=={'processed':1,'matches':1,'updates':0,'recovered_history':False}
    assert result.json()['dry_run_at'] and not result.json()['auto_updates']
    assert 'refresh-secret' not in result.text and 'access-only-in-memory' not in result.text
    assert client.get('/api/gmail/messages').json()['total']==1


def test_revoked_connection_cannot_reuse_revoked_refresh_on_reconnect(client,db,config,monkeypatch):
    conn=connection(db);conn.health='reconnect_required';db.commit()
    monkeypatch.setattr(gmail.GoogleClient,'exchange',lambda *args:{'access_token':'a','scope':SCOPE})
    monkeypatch.setattr(gmail.GoogleClient,'profile',lambda self:{'emailAddress':'owner@example.com'})
    query=oauth_start(client)
    result=client.get('/api/gmail/oauth/callback',params={'state':query['state'][0],'code':'code'},follow_redirects=False)
    assert result.headers['location'].endswith('#gmail=error')
    assert db.get(GmailConnection,OWNER).health=='reconnect_required'


def test_lock_refreshes_status_changed_after_matching_before_mutation(db,config,monkeypatch):
    from sqlalchemy import text
    item=application(db);conn=connection(db,auto=True)
    original=gmail_sync.match_applications
    def concurrent_manual_change(email,applications,rules):
        result=original(email,applications,rules)
        # Simulate a newer stored row while the ORM still holds the prior snapshot.
        db.execute(text('UPDATE applications SET status = :status, status_revision = 7, status_manual_at = :at WHERE id = :id'),{'status':'Offer','at':now(),'id':item.id})
        return result
    monkeypatch.setattr(gmail_sync,'match_applications',concurrent_manual_change)
    assert message(db,conn)[2]==0
    assert db.get(Application,item.id).status=='Offer'
    saved=db.scalar(select(GmailMessage));assert saved.snapshot_revision==7 and saved.state=='review'
