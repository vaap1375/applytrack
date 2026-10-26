"""Owner-authenticated Gmail integration; only the OAuth callback is state/cookie authenticated."""
import base64
import hashlib
import re
import secrets
from datetime import timedelta
from uuid import UUID
from urllib.parse import urlencode, urlsplit
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select, func
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from .auth import current_owner
from .db import get_db
from .models import Application, now
from .schemas import Status
from .gmail_models import GmailConnection, GmailMessage, GmailMatchRule, GmailOAuthState
from .gmail_google import GoogleClient, GoogleFailure, SCOPE, configured, decrypt, encrypt
from .gmail_analysis import FREE_MAIL
from .gmail_sync import record_change, synchronize

router=APIRouter(prefix='/api/gmail',tags=['gmail'])
COOKIE='applytrack_gmail_link'
CALLBACK='/api/gmail/oauth/callback'


def digest(value):return hashlib.sha256(value.encode()).hexdigest()


def connection_for(db,owner,lock=False,required=True):
    query=select(GmailConnection).where(GmailConnection.owner_id==owner)
    if lock:query=query.with_for_update(nowait=True)
    try:connection=db.scalar(query)
    except OperationalError:
        db.rollback();raise HTTPException(409,'Gmail is busy with another operation. Try again shortly.') from None
    if not connection and required:raise HTTPException(409,'Connect Gmail first')
    return connection


def connection_view(connection):
    from .config import settings
    config=settings()
    ready=bool(config.google_client_id and config.google_client_secret.get_secret_value() and config.gmail_encryption_key.get_secret_value())
    return {'configured':ready,'connected':bool(connection and connection.encrypted_refresh),
        'email':connection.email if connection else None,'health':connection.health if connection else 'disconnected',
        'last_sync_at':connection.last_sync_at if connection else None,'auto_updates':connection.auto_updates if connection else False,
        'lookback_days':connection.lookback_days if connection else 30,'dry_run_at':connection.dry_run_at if connection else None,
        'more':bool(connection and connection.pending),'stats':connection.stats if connection else {}}


@router.get('/connection')
def status(owner:UUID=Depends(current_owner),db:Session=Depends(get_db)):
    return connection_view(connection_for(db,owner,required=False))


@router.post('/oauth/start')
def start(response:Response,owner:UUID=Depends(current_owner),db:Session=Depends(get_db)):
    config=configured()
    state=secrets.token_urlsafe(32);browser=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(64)
    old=db.get(GmailOAuthState,owner)
    if old:db.delete(old);db.flush()
    db.add(GmailOAuthState(owner_id=owner,state_hash=digest(state),browser_hash=digest(browser),encrypted_verifier=encrypt(owner,verifier),expires_at=now()+timedelta(minutes=10)))
    db.commit()
    response.set_cookie(COOKIE,browser,max_age=600,httponly=True,secure=urlsplit(config.gmail_redirect_uri).scheme=='https',samesite='lax',path=CALLBACK)
    response.headers['Cache-Control']='no-store'
    return {'authorization_url':'https://accounts.google.com/o/oauth2/v2/auth?'+urlencode({'client_id':config.google_client_id,'redirect_uri':config.gmail_redirect_uri,'response_type':'code','scope':SCOPE,'access_type':'offline','prompt':'consent','include_granted_scopes':'false','state':state,'code_challenge':base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='),'code_challenge_method':'S256'})}


@router.get('/oauth/callback')
def callback(request:Request,state:str=Query('',max_length=200),code:str=Query('',max_length=4096),error:str=Query('',max_length=200),db:Session=Depends(get_db)):
    config=configured()
    pending=db.scalar(select(GmailOAuthState).where(GmailOAuthState.state_hash==digest(state)).with_for_update())
    cookie=request.cookies.get(COOKIE,'')
    if not pending or not cookie or not secrets.compare_digest(pending.browser_hash,digest(cookie)):
        raise HTTPException(400,'Gmail connection request is invalid or expired; start again from ApplyTrack')
    owner=pending.owner_id
    expired=pending.expires_at<now()
    verifier=decrypt(owner,pending.encrypted_verifier)
    db.delete(pending);db.commit() # single use, including cancellations/token failures
    result='cancelled' if error else 'expired' if expired else 'error'
    if not error and not expired and code:
        client=GoogleClient()
        try:
            tokens=client.exchange(code,verifier)
            if SCOPE not in tokens.get('scope','').split() or not tokens.get('access_token'):
                raise GoogleFailure('permission_denied')
            client.access_token=tokens['access_token'];profile=client.profile()
            email=profile.get('emailAddress')
            if not isinstance(email,str) or len(email)>320 or '@' not in email:raise GoogleFailure()
            connection=connection_for(db,owner,lock=True,required=False)
            if connection and connection.email.casefold()!=email.casefold():
                if tokens.get('refresh_token'):client.revoke(tokens['refresh_token'])
                result='account_mismatch'
            else:
                refresh=tokens.get('refresh_token')
                if not refresh and connection and connection.encrypted_refresh and connection.health not in {'reconnect_required','disconnected'}:refresh=decrypt(owner,connection.encrypted_refresh)
                if not refresh:raise GoogleFailure('revoked')
                if not connection:
                    connection=GmailConnection(owner_id=owner,email=email)
                    db.add(connection)
                connection.encrypted_refresh=encrypt(owner,refresh);connection.health='connected'
                connection.auto_updates=False;connection.auto_enabled_at=None;connection.dry_run_at=None
                db.commit();result='connected'
        except GoogleFailure:
            db.rollback();result='error'
    response=RedirectResponse(config.gmail_frontend_url.rstrip('/')+'/#gmail='+result,status_code=303)
    response.delete_cookie(COOKIE,path=CALLBACK)
    response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
    return response


class Preferences(BaseModel):
    model_config=ConfigDict(extra='forbid')
    auto_updates:bool | None=None
    reviewed_dry_run:bool=False
    lookback_days:int | None=Field(default=None,ge=1,le=365)


@router.patch('/settings')
def preferences(data:Preferences,owner:UUID=Depends(current_owner),db:Session=Depends(get_db)):
    connection=connection_for(db,owner,lock=True)
    if data.auto_updates is True:
        if not connection.encrypted_refresh or connection.health!='connected' or not connection.dry_run_at or not data.reviewed_dry_run or connection.pending or not db.scalar(select(GmailMessage.id).where(GmailMessage.owner_id==owner,GmailMessage.state!='ignored').limit(1)):
            raise HTTPException(409,'Complete and review a dry-run sync before enabling automatic updates')
        if not connection.auto_updates:connection.auto_enabled_at=now()
        connection.auto_updates=True
    elif data.auto_updates is False:
        connection.auto_updates=False;connection.auto_enabled_at=None
    if data.lookback_days is not None:
        if connection.pending:raise HTTPException(409,'Finish the current sync before changing lookback')
        connection.lookback_days=data.lookback_days
    db.commit()
    return connection_view(connection)


@router.post('/sync')
def sync(owner:UUID=Depends(current_owner),db:Session=Depends(get_db)):
    configured()
    connection=connection_for(db,owner,lock=True)
    if not connection.encrypted_refresh:raise HTTPException(409,'Reconnect Gmail first')
    synchronize(db,connection)
    return connection_view(connection)


class Disconnect(BaseModel):
    model_config=ConfigDict(extra='forbid')
    delete_data:bool=True


@router.post('/disconnect')
def disconnect(data:Disconnect,owner:UUID=Depends(current_owner),db:Session=Depends(get_db)):
    connection=connection_for(db,owner,lock=True,required=False)
    revoked=False
    if connection:
        if connection.encrypted_refresh:
            try:GoogleClient().revoke(decrypt(owner,connection.encrypted_refresh));revoked=True
            except (HTTPException,GoogleFailure):pass
        connection.encrypted_refresh=None;connection.auto_updates=False;connection.auto_enabled_at=None
        connection.health='disconnected';connection.pending=None
    db.execute(delete(GmailOAuthState).where(GmailOAuthState.owner_id==owner))
    if data.delete_data:
        db.execute(delete(GmailMessage).where(GmailMessage.owner_id==owner))
        db.execute(delete(GmailMatchRule).where(GmailMatchRule.application_id.in_(select(Application.id).where(Application.owner_id==owner))))
        if connection:db.delete(connection)
    db.commit()
    return {'disconnected':True,'data_deleted':data.delete_data,'remote_revocation_attempted':revoked}


def message_view(message):
    return {key:getattr(message,key) for key in ['id','gmail_id','subject','sender','excerpt','received_at','classification','class_confidence','match_confidence','evidence','application_id','proposed_status','old_status','state','snapshot_revision','resulting_revision','reason','processed_at']}


@router.get('/messages')
def messages(state:str=Query('review',pattern='^(review|applied|accepted|dismissed|undone|unchanged)$'),page:int=Query(1,ge=1),owner:UUID=Depends(current_owner),db:Session=Depends(get_db)):
    query=select(GmailMessage).where(GmailMessage.owner_id==owner,GmailMessage.state==state)
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    rows=db.scalars(query.order_by(GmailMessage.processed_at.desc(),GmailMessage.id).offset((page-1)*20).limit(20)).all()
    return {'items':[message_view(m) for m in rows],'total':total,'page':page}


def owned_message(db,owner,id):
    message=db.scalar(select(GmailMessage).where(GmailMessage.owner_id==owner,GmailMessage.id==id).with_for_update())
    if not message:raise HTTPException(404,'Gmail item not found')
    return message


class Approval(BaseModel):
    model_config=ConfigDict(extra='forbid')
    application_id:UUID
    status:Status
    expected_revision:int=Field(ge=0)


@router.post('/messages/{id}/accept')
def accept(id:UUID,data:Approval,owner:UUID=Depends(current_owner),db:Session=Depends(get_db)):
    message=owned_message(db,owner,id)
    if message.state!='review':raise HTTPException(409,'This suggestion has already been handled')
    application=db.scalar(select(Application).where(Application.id==data.application_id,Application.owner_id==owner).with_for_update().execution_options(populate_existing=True))
    if not application:raise HTTPException(404,'Application not found')
    if application.status_revision!=data.expected_revision:raise HTTPException(409,'Application status changed. Reload before reviewing this suggestion.')
    if application.status==data.status:raise HTTPException(409,'Application already has this status; dismiss the suggestion instead')
    message.application_id=application.id;message.old_status=application.status;message.proposed_status=data.status
    event=record_change(db,application,data.status,message,'gmail_review')
    message.resulting_revision=application.status_revision;message.event_id=event.id;message.state='accepted';message.reason='Explicitly approved by the owner.'
    db.commit()
    return message_view(message)


@router.post('/messages/{id}/dismiss')
def dismiss(id:UUID,owner:UUID=Depends(current_owner),db:Session=Depends(get_db)):
    message=owned_message(db,owner,id)
    if message.state!='review':raise HTTPException(409,'This suggestion has already been handled')
    message.state='dismissed';message.reason='Dismissed by the owner.';db.commit()
    return message_view(message)


@router.post('/messages/{id}/undo')
def undo(id:UUID,owner:UUID=Depends(current_owner),db:Session=Depends(get_db)):
    message=owned_message(db,owner,id)
    if message.state not in {'applied','accepted'} or not message.application_id or not message.old_status:raise HTTPException(409,'This change cannot be undone')
    application=db.scalar(select(Application).where(Application.id==message.application_id,Application.owner_id==owner).with_for_update().execution_options(populate_existing=True))
    if not application:raise HTTPException(404,'Application not found')
    if application.status_revision!=message.resulting_revision or application.status!=message.proposed_status:
        raise HTTPException(409,'A newer status change is protected. Edit the application manually instead.')
    record_change(db,application,message.old_status,message,'gmail_undo')
    message.state='undone';message.reason='Reverted by the owner; original audit event retained.';db.commit()
    return message_view(message)


class MatchRule(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    aliases:list[str]=Field(default_factory=list,max_length=20)
    sender_domains:list[str]=Field(default_factory=list,max_length=20)
    @field_validator('aliases')
    @classmethod
    def aliases_valid(cls,values):
        if any(not 3<=len(v.strip())<=200 for v in values):raise ValueError('Aliases must be 3–200 characters')
        return list(dict.fromkeys(v.strip() for v in values))
    @field_validator('sender_domains')
    @classmethod
    def domains_valid(cls,values):
        result=[v.lower().strip().rstrip('.') for v in values]
        if any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,250}[a-z0-9])?',v) or '.' not in v or v in FREE_MAIL for v in result):raise ValueError('Use employer domains, not free-mail providers or URLs')
        return list(dict.fromkeys(result))


@router.get('/rules/{application_id}')
def get_rule(application_id:UUID,owner:UUID=Depends(current_owner),db:Session=Depends(get_db)):
    if not db.scalar(select(Application.id).where(Application.id==application_id,Application.owner_id==owner)):raise HTTPException(404,'Application not found')
    rule=db.get(GmailMatchRule,application_id)
    return {'aliases':rule.aliases if rule else [],'sender_domains':rule.sender_domains if rule else []}


@router.patch('/rules/{application_id}')
def set_rule(application_id:UUID,data:MatchRule,owner:UUID=Depends(current_owner),db:Session=Depends(get_db)):
    if not db.scalar(select(Application.id).where(Application.id==application_id,Application.owner_id==owner)):raise HTTPException(404,'Application not found')
    rule=db.get(GmailMatchRule,application_id)
    if not rule:rule=GmailMatchRule(application_id=application_id);db.add(rule)
    rule.aliases=data.aliases;rule.sender_domains=data.sender_domains;db.commit()
    return data


class GmailCallbackPrivacy:
    """Remove OAuth query secrets before Uvicorn formats its access log."""
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        async def safe_send(message):
            if message['type']=='http.response.start' and scope.get('path')==CALLBACK:
                scope['query_string']=b''
                message['headers']=[(key,value) for key,value in message.get('headers',[]) if key.lower() not in {b'cache-control',b'referrer-policy'}]+[(b'cache-control',b'no-store'),(b'referrer-policy',b'no-referrer')]
            await send(message)
        try:
            await self.app(scope,receive,safe_send)
        finally:
            if scope.get('path')==CALLBACK:
                scope['query_string']=b''
