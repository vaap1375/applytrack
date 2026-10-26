"""Bounded resumable manual sync; each checkpoint and status event commits atomically."""
from datetime import timedelta
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from .models import Application, Event, now
from .gmail_models import GmailMessage, GmailMatchRule
from .gmail_analysis import RECRUITING, TARGETS, classify, match_applications, parse_message, safe_transition
from .gmail_google import GoogleClient, GoogleFailure, decrypt, encrypt

SEARCH='-in:spam -in:trash -in:sent -in:drafts {application applying assessment interview recruiter recruiting hiring candidate "job offer" "employment offer" "coding challenge" "your candidacy" offer position careers}'


def record_change(db,application,target,message,source):
    previous=application.status
    application.status=target
    application.status_revision+=1
    application.status_changed_at=message.received_at if source=='gmail' else now()
    if source!='gmail':application.status_manual_at=now()
    event=Event(application_id=application.id,event_type='gmail_status_undone' if source=='gmail_undo' else 'status_changed',old_status=previous,new_status=target,
                source=source,source_message_id=message.gmail_id,source_timestamp=message.received_at,
                notes='Gmail '+message.classification+'; '+('explicit owner review' if source!='gmail' else 'strict rule and unique identity evidence')+'.')
    db.add(event);db.flush()
    return event


def remember_ignored(db,connection,id,received,reason):
    db.add(GmailMessage(owner_id=connection.owner_id,gmail_id=id,received_at=received,
        classification='unknown',class_confidence=0,match_confidence=0,evidence=[],
        state='ignored',reason=reason))


def process(db,connection,raw):
    email=parse_message(raw)
    if db.scalar(select(GmailMessage.id).where(GmailMessage.owner_id==connection.owner_id,GmailMessage.gmail_id==email.id)):
        return (0,0,0)
    if email.excluded:
        remember_ignored(db,connection,email.id,email.received_at,'Excluded sent/draft/spam/trash message.')
        return (1,0,0)
    applications=db.scalars(select(Application).where(Application.owner_id==connection.owner_id)).all()
    rules={r.application_id:r for r in db.scalars(select(GmailMatchRule).join(Application).where(Application.owner_id==connection.owner_id)).all()}
    winner,evidence=match_applications(email,applications,rules)
    event,confidence,reason=classify(email)
    if not evidence and not RECRUITING.search(email.subject+'\n'+email.body):
        remember_ignored(db,connection,email.id,email.received_at,'No recruiting relevance.')
        return (1,0,0)
    application=next((a for a in applications if winner and str(a.id)==winner['application_id']),None)
    identity_changed=False
    if application:
        identity=(application.company_name,application.job_title,application.external_job_id,application.job_url)
        application=db.scalar(select(Application).where(Application.id==application.id,Application.owner_id==connection.owner_id).with_for_update().execution_options(populate_existing=True))
        if not application:winner=None
        else:identity_changed=identity!=(application.company_name,application.job_title,application.external_job_id,application.job_url)
    message=GmailMessage(owner_id=connection.owner_id,gmail_id=email.id,subject=email.subject,sender=email.sender,
        excerpt=email.body[:500],received_at=email.received_at,classification=event,class_confidence=confidence,
        match_confidence=winner['score'] if winner else 0,evidence=evidence,
        application_id=application.id if application else None,proposed_status=TARGETS.get(event),
        state='review',snapshot_revision=application.status_revision if application else None,reason=reason)
    db.add(message)
    allowed,guard=safe_transition(application,message.proposed_status,email.received_at) if application else (False,'No unique application match.')
    reliable=bool(winner and winner['score']>=0.99 and winner['trusted_sender'] and confidence>=0.99 and not identity_changed)
    fresh=bool(connection.auto_enabled_at and email.received_at>=connection.auto_enabled_at and email.received_at<=now()+timedelta(minutes=5))
    applied=0
    if connection.auto_updates and reliable and fresh and allowed:
        message.old_status=application.status
        event_record=record_change(db,application,message.proposed_status,message,'gmail')
        message.resulting_revision=application.status_revision;message.event_id=event_record.id
        message.state='applied';message.reason='Automatic: '+reason+' '+guard;applied=1
    elif application and message.proposed_status==application.status:
        message.state='unchanged';message.reason='Application already has this status.'
    else:
        message.reason=(reason+' '+(guard if not allowed else 'Review required: '+('automatic updates are disabled.' if not connection.auto_updates else 'identity, sender authentication, or freshness threshold not met.')))[:500]
    return (1,int(bool(winner)),applied)


def initial_pending(client,connection,recovered=False):
    profile=client.profile()
    history=str(profile.get('historyId',''))
    if not history.isdigit():raise GoogleFailure()
    since=now()-timedelta(days=connection.lookback_days)
    return {'kind':'initial','query':SEARCH+f' after:{int(since.timestamp())} before:{int(now().timestamp())+1}',
            'baseline':history,'page':None,'ids':[],'next':None,'loaded':False,
            'stats':{'processed':0,'matches':0,'updates':0},'recovered_history':recovered}


def synchronize(db,connection,client=None):
    client=client or GoogleClient()
    try:
        tokens=client.refresh(decrypt(connection.owner_id,connection.encrypted_refresh))
        if tokens.get('refresh_token'):
            connection.encrypted_refresh=encrypt(connection.owner_id,tokens['refresh_token'])
        pending=dict(connection.pending) if connection.pending else ({'kind':'history','baseline':connection.history_id,'page':None,'ids':[],'next':None,'loaded':False,'stats':{'processed':0,'matches':0,'updates':0}} if connection.history_id else initial_pending(client,connection))
        pending['stats']=dict(pending['stats']);pending['ids']=list(pending['ids'])
        connection.pending=pending
        if not pending['loaded']:
            try:
                data=client.history(pending['baseline'],pending.get('page')) if pending['kind']=='history' else client.messages(pending['query'],pending.get('page'))
            except GoogleFailure as exc:
                if not (exc.kind=='invalid_page' or (exc.kind=='not_found' and pending['kind']=='history')):raise
                pending=initial_pending(client,connection,recovered=True)
                connection.pending=pending
                data=client.messages(pending['query'])
            if pending['kind']=='history':
                ids=[entry['message']['id'] for history in data.get('history',[]) for entry in history.get('messagesAdded',[]) if isinstance(entry.get('message',{}).get('id'),str)]
                final=str(data.get('historyId',''))
                if not final.isdigit():raise GoogleFailure()
                pending['final']=final
            else:
                ids=[m['id'] for m in data.get('messages',[]) if isinstance(m.get('id'),str)]
            pending['ids']=list(dict.fromkeys(ids));pending['next']=data.get('nextPageToken');pending['loaded']=True
        for _ in range(min(25,len(pending['ids']))):
            id=pending['ids'][0]
            exists=db.scalar(select(GmailMessage.id).where(GmailMessage.owner_id==connection.owner_id,GmailMessage.gmail_id==id))
            if not exists:
                try:raw=client.message(id)
                except GoogleFailure as exc:
                    if exc.kind=='not_found':pending['ids'].pop(0);continue
                    raise
                try:counts=process(db,connection,raw)
                except (ValueError,KeyError,TypeError):
                    remember_ignored(db,connection,id,now(),'Malformed message; no status action.')
                    counts=(1,0,0)
                for key,count in zip(('processed','matches','updates'),counts):pending['stats'][key]+=count
            pending['ids'].pop(0)
        connection.health='connected'
        if not pending['ids']:
            if pending['next']:
                pending['page']=pending['next'];pending['loaded']=False
            else:
                connection.history_id=pending.get('final') if pending['kind']=='history' else pending['baseline']
                connection.last_sync_at=now()
                if not connection.auto_updates and db.scalar(select(GmailMessage.id).where(GmailMessage.owner_id==connection.owner_id,GmailMessage.state!='ignored').limit(1)):
                    connection.dry_run_at=now()
                connection.stats={**pending['stats'],'recovered_history':pending.get('recovered_history',False)}
                connection.pending=None
        if connection.pending is not None:
            connection.pending={**pending,'ids':list(pending['ids']),'stats':dict(pending['stats'])}
            connection.stats={**pending['stats'],'recovered_history':pending.get('recovered_history',False)}
    except GoogleFailure as exc:
        connection.health='reconnect_required' if exc.kind in {'revoked','permission_denied'} else 'rate_limited' if exc.kind=='rate_limited' else 'paused' if exc.kind=='paused' else 'error'
        if 'pending' in locals():
            connection.pending={**pending,'ids':list(pending['ids']),'stats':dict(pending['stats'])}
            connection.stats=dict(pending['stats'])
        if connection.health=='reconnect_required':connection.auto_updates=False;connection.auto_enabled_at=None
    if connection.pending is not None:
        # Checkpoint dicts may have been autoflushed while processing messages.
        # Mark the final JSON snapshot dirty even when in-place values compare equal.
        flag_modified(connection, 'pending')
    # Retain dedup/audit identifiers; redact email text after 90 days.
    stale=db.scalars(select(GmailMessage).where(GmailMessage.owner_id==connection.owner_id,GmailMessage.received_at<now()-timedelta(days=90))).all()
    for message in stale:message.subject=None;message.sender=None;message.excerpt=None
    db.commit()
