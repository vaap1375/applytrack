from datetime import datetime, timezone
from uuid import uuid4
import pytest
from app import reminders
from app.auth import current_owner
from app.main import app
from conftest import OTHER

NOW = datetime(2026, 10, 26, 16, tzinfo=timezone.utc)

def application(client):
    return client.post('/api/applications',json={'company_name':'Example','job_title':'Engineer'}).json()['id']

def create(client, id, **values):
    return client.post('/api/reminders',json={'application_id':id,'title':'Follow up','due_at':'2026-10-26T13:00:00-04:00',**values})


def test_crud_completion_and_reopen(client,monkeypatch):
    monkeypatch.setattr(reminders,'now',lambda:NOW)
    id=application(client)
    response=create(client,id)
    assert response.status_code==201
    item=response.json(); rid=item['id']
    assert item['company_name']=='Example' and item['job_title']=='Engineer'
    assert datetime.fromisoformat(item['due_at'].replace('Z','+00:00'))==datetime(2026,10,26,17,tzinfo=timezone.utc)
    assert client.get('/api/reminders/'+rid).status_code==200
    changed=client.patch('/api/reminders/'+rid,json={'title':'Interview deadline','due_at':'2026-10-27T11:00:00Z'}).json()
    assert changed['title']=='Interview deadline'
    completed=client.patch('/api/reminders/'+rid,json={'completed':True}).json()
    assert completed['completed_at'] and completed['bucket']=='completed'
    assert client.patch('/api/reminders/'+rid,json={'completed':True}).json()['completed_at']==completed['completed_at']
    reopened=client.patch('/api/reminders/'+rid,json={'completed':False}).json()
    assert reopened['completed_at'] is None and reopened['bucket']=='upcoming'
    assert client.delete('/api/reminders/'+rid).status_code==204
    assert client.get('/api/reminders/'+rid).status_code==404


def test_owner_isolation(client):
    id=application(client);rid=create(client,id).json()['id']
    app.dependency_overrides[current_owner]=lambda:OTHER
    assert client.get('/api/reminders').json()['total']==0
    assert client.get('/api/reminders').json()['counts']==dict(overdue=0,due_today=0,upcoming=0,completed=0)
    assert create(client,id).status_code==404
    assert client.get('/api/reminders?application_id='+id).status_code==404
    assert client.get('/api/reminders/'+rid).status_code==404
    assert client.patch('/api/reminders/'+rid,json={'completed':True}).status_code==404
    assert client.delete('/api/reminders/'+rid).status_code==404


def test_categories_and_timezone_boundaries(client,monkeypatch):
    # At 23:30 Detroit, 00:15 local tomorrow is upcoming despite sharing a UTC day.
    monkeypatch.setattr(reminders,'now',lambda:datetime(2026,10,27,3,30,tzinfo=timezone.utc))
    id=application(client)
    for due in ['2026-10-26T22:00:00-04:00','2026-10-26T23:45:00-04:00','2026-10-27T00:15:00-04:00']:
        create(client,id,due_at=due)
    result=client.get('/api/reminders?timezone=America/Detroit').json()
    assert result['counts']==dict(overdue=1,due_today=1,upcoming=1,completed=0)
    assert [x['bucket'] for x in result['items']]==['overdue','due_today','upcoming']
    utc=client.get('/api/reminders?timezone=UTC').json()
    assert utc['counts']==dict(overdue=1,due_today=2,upcoming=0,completed=0)
    assert client.get('/api/reminders?bucket=upcoming&timezone=America/Detroit').json()['total']==1


def test_dst_calendar_boundary(client,monkeypatch):
    # Fall-back day is 25 hours; tomorrow's boundary must use the IANA zone.
    monkeypatch.setattr(reminders,'now',lambda:datetime(2026,11,1,4,30,tzinfo=timezone.utc))
    id=application(client)
    create(client,id,due_at='2026-11-02T04:30:00Z') # Nov 1 23:30 EST
    assert client.get('/api/reminders?timezone=America/Detroit').json()['items'][0]['bucket']=='due_today'
    assert client.get('/api/reminders?timezone=UTC').json()['items'][0]['bucket']=='upcoming'


def test_pagination_application_filter_and_cascade(client):
    a=application(client); b=application(client)
    for _ in range(3):create(client,a)
    create(client,b)
    first=client.get(f'/api/reminders?application_id={a}&page_size=2').json()
    second=client.get(f'/api/reminders?application_id={a}&page_size=2&page=2').json()
    assert first['total']==3 and len(first['items'])==2 and len(second['items'])==1
    assert {x['id'] for x in first['items']}.isdisjoint(x['id'] for x in second['items'])
    client.delete('/api/applications/'+a)
    assert client.get('/api/reminders').json()['total']==1

@pytest.mark.parametrize('values',[{'title':' '},{'title':'a'*201},{'due_at':'2026-10-26T12:00:00'},{'due_at':None},{'owner_id':str(OTHER)},{'completed_at':'2026-10-26T12:00:00Z'}])
def test_create_validation(client,values):
    assert create(client,application(client),**values).status_code==422

@pytest.mark.parametrize('values',[{'title':None},{'due_at':None},{'completed':None},{'application_id':str(uuid4())},{'title':' '}])
def test_update_validation(client,values):
    rid=create(client,application(client)).json()['id']
    assert client.patch('/api/reminders/'+rid,json=values).status_code==422


def test_missing_and_bad_query(client):
    assert create(client,str(uuid4())).status_code==404
    assert client.get('/api/reminders?timezone=Invalid/Zone').status_code==422
    assert client.get('/api/reminders?bucket=invalid').status_code==422
    assert client.get('/api/reminders?page_size=101').status_code==422


def test_authentication_required(client,monkeypatch):
    app.dependency_overrides.pop(current_owner)
    from app.config import settings
    monkeypatch.setenv('SUPABASE_URL','https://test.supabase.co');monkeypatch.setenv('OWNER_ID',str(OTHER));settings.cache_clear()
    try:
        assert client.get('/api/reminders').status_code==401
        assert client.post('/api/reminders',json={}).status_code==401
        assert client.patch('/api/reminders/'+str(uuid4()),json={'completed':True}).status_code==401
        assert client.delete('/api/reminders/'+str(uuid4())).status_code==401
    finally:settings.cache_clear()
