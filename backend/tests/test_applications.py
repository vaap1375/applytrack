import uuid
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from app.main import app
from app.auth import current_owner
from app.models import Application, Event, Reminder, now
from conftest import OTHER

def add(client, **fields):
    return client.post('/api/applications', json={'company_name':'Acme','job_title':'Engineer',**fields})

def test_crud_and_events(client, db):
    response = add(client, job_url='https://example.com/job', notes='Private notes')
    assert response.status_code == 201
    item = response.json(); id = item['id']
    assert client.get(f'/api/applications/{id}').json()['notes'] == 'Private notes'
    assert client.patch(f'/api/applications/{id}',json={'status':'Interview','notes':None}).json()['status'] == 'Interview'
    events = client.get(f'/api/applications/{id}/events').json()
    assert len(events) == 2
    assert any(e['old_status']=='Saved' and e['new_status']=='Interview' for e in events)
    assert client.get('/api/dashboard/summary').json()['by_status']['Interview'] == 1
    assert client.patch(f'/api/applications/{id}',json={'status':'Interview'}).status_code == 200
    assert len(client.get(f'/api/applications/{id}/events').json()) == 3  # generic edit, no duplicate status event
    db.add(Reminder(application_id=uuid.UUID(id), title='Follow up', due_at=now())); db.commit()
    assert client.delete(f'/api/applications/{id}').status_code == 204
    assert client.get(f'/api/applications/{id}').status_code == 404
    assert not db.scalars(select(Event)).all()
    assert not db.scalars(select(Reminder)).all()

def test_owner_isolation(client):
    id = add(client).json()['id']
    app.dependency_overrides[current_owner] = lambda: OTHER
    assert client.get('/api/applications').json()['total'] == 0
    assert client.get('/api/dashboard/summary').json()['total'] == 0
    for method, suffix, data in [('get','',None),('patch','',{'notes':'stolen'}),('delete','',None),('get','/events',None)]:
        kwargs = {'json':data} if data else {}
        assert getattr(client,method)(f'/api/applications/{id}{suffix}',**kwargs).status_code == 404

def test_pagination_filter_search(client):
    for i in range(4): add(client, company_name=f'Company {i}', status='Applied' if i%2 else 'Saved')
    assert client.get('/api/applications?page_size=2').json()['total'] == 4
    first = client.get('/api/applications?page_size=2').json()['items']
    second = client.get('/api/applications?page=2&page_size=2').json()['items']
    assert len(first)==len(second)==2
    assert not {x['id'] for x in first} & {x['id'] for x in second}
    assert client.get('/api/applications?status=Applied').json()['total'] == 2
    assert client.get('/api/applications?search=company%201').json()['total'] == 1
    assert client.get('/api/applications?search=%25').json()['total'] == 0
    assert client.get('/api/applications?page=0').status_code == 422
    assert client.get('/api/applications?page_size=101').status_code == 422

@pytest.mark.parametrize('fields',[{'company_name':' '},{'status':'Unknown'},{'job_url':'javascript:alert(1)'},{'company_name':'x'*201},{'applied_at':'2026-01-01T10:00:00'},{'owner_id':str(OTHER)}])
def test_validation(client,fields):
    assert add(client,**fields).status_code == 422

def test_patch_null_validation(client):
    id=add(client).json()['id']
    for field in ['company_name','job_title','status']:
        assert client.patch(f'/api/applications/{id}',json={field:None}).status_code == 422

def test_database_constraint(db):
    with pytest.raises(IntegrityError):
        db.add(Application(owner_id=OTHER,company_name='A',job_title='B',status='Invalid'))
        db.flush()
    db.rollback()

def test_transaction_rollback(client, db, monkeypatch):
    id=add(client).json()['id']
    def fail():
        raise RuntimeError('simulated failure')
    monkeypatch.setattr(db,'commit',fail)
    with pytest.raises(RuntimeError):
        client.patch(f'/api/applications/{id}',json={'status':'Offer'})
    db.rollback()
    assert db.get(Application,uuid.UUID(id)).status == 'Saved'
    assert len(db.scalars(select(Event)).all()) == 1
