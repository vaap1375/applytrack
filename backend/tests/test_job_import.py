"""Synthetic public payload fixtures; no production network or credentials."""
from pathlib import Path
import json
import socket
import time
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from app import job_import as importer
from app import job_fetch as fetch
from app.main import app
from app.auth import current_owner
from conftest import OTHER

FIXTURES = Path(__file__).parent / 'fixtures' / 'job_import'

class FixtureFetcher:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []
    def get(self, url):
        self.calls.append(url)
        value = self.mapping.get(url)
        if value is None:
            raise fetch.ImportFailure('Fixture unavailable')
        if value.endswith(('.html', '.json')):
            value = (FIXTURES / value).read_text()
        return fetch.Page(url, value, 'text/html' if value.lstrip().startswith('<') else 'application/json')

@pytest.mark.parametrize('url,api,fixture,title,location,source',[
 ('https://job-boards.greenhouse.io/example/jobs/12345','https://boards-api.greenhouse.io/v1/boards/example/jobs/12345','greenhouse.json','Backend Engineer','New York, NY','Greenhouse public API'),
 ('https://jobs.lever.co/example/abc-123','https://api.lever.co/v0/postings/example/abc-123?mode=json','lever.json','Frontend Engineer','Remote','Lever public API'),
 ('https://jobs.eu.lever.co/example/abc-123','https://api.eu.lever.co/v0/postings/example/abc-123?mode=json','lever.json','Frontend Engineer','Remote','Lever public API'),
 ('https://jobs.ashbyhq.com/example/abc-123','https://api.ashbyhq.com/posting-api/job-board/example','ashby.json','Platform Engineer','Austin, TX','Ashby public API'),
])
def test_public_platforms(url,api,fixture,title,location,source):
    reader=FixtureFetcher({api:fixture})
    result=importer.finish(importer.extract(url,reader))
    assert result.job_title == title and result.location == location
    assert result.source == source
    assert result.external_job_id and result.description
    if source != 'Greenhouse public API':
        assert result.company_name is None  # slug is not an invented company name
        assert 'company_name' in result.missing_fields
    assert reader.calls[0] == api


def test_generic_jsonld():
    url='https://example.com/careers/engineer?utm_source=test'
    result=importer.finish(importer.extract(url,FixtureFetcher({url:'jobposting.html'})))
    assert result.company_name == 'Example Labs'
    assert result.job_title == 'Software Engineer'
    assert result.location == 'Detroit, MI, US'
    assert result.external_job_id == 'ENG-42'
    assert result.description == 'Build useful tools.'
    assert result.canonical_url == 'https://example.com/careers/engineer'
    assert result.source == 'JobPosting JSON-LD'
    assert not result.missing_fields


def test_metadata_and_malformed_jsonld():
    page=fetch.Page('https://example.com/job', '<script type="application/ld+json">{broken</script>'+(FIXTURES/'metadata.html').read_text(),'text/html')
    result=importer.finish(importer.extract_html(page))
    assert result.job_title == 'Engineer opening'
    assert result.description == 'Join the engineering team.'
    assert result.source == 'Page metadata'
    assert 'location' in result.missing_fields
    assert any('malformed' in warning for warning in result.warnings)


def test_missing_fields_and_unsafe_canonical():
    result=importer.finish(importer.extract_html(fetch.Page('https://example.com/job','<link rel="canonical" href="http://127.0.0.1/private"><html>empty</html>','text/html')))
    assert result.company_name is None and result.job_title is None
    assert len(result.missing_fields) == 5
    assert result.canonical_url == 'https://example.com/job'
    assert any('unsafe' in warning for warning in result.warnings)


def test_remote_job_and_limits():
    data={'@type':'JobPosting','title':'x'*250,'jobLocationType':'TELECOMMUTE','description':'d'*30000}
    result=importer.finish(importer.extract_html(fetch.Page('https://example.com/job',f'<script type="application/ld+json">{json.dumps(data)}</script>','text/html')))
    assert result.location == 'Remote'
    assert len(result.job_title)==200 and len(result.description)==28000
    assert any('truncated' in warning for warning in result.warnings)


def test_platform_html_fallback_and_company_enrichment():
    url='https://jobs.lever.co/example/abc-123'
    reader=FixtureFetcher({url:'jobposting.html'})
    result=importer.extract(url,reader)
    assert result.source=='JobPosting JSON-LD'
    assert any('API was unavailable' in warning for warning in result.warnings)
    reader.mapping['https://api.lever.co/v0/postings/example/abc-123?mode=json']='lever.json'
    result=importer.extract(url,reader)
    assert result.company_name=='Example Labs'
    assert result.job_title=='Frontend Engineer'
    assert result.source=='Lever public API + JobPosting JSON-LD'


def test_preview_duplicate_and_owner_scope(client,monkeypatch):
    monkeypatch.setattr(importer,'PublicFetcher',lambda:FixtureFetcher({'https://example.com/job':'jobposting.html'}))
    created=client.post('/api/applications',json={'company_name':'Example','job_title':'Engineer','job_url':'https://example.com/careers/engineer/?utm_campaign=test','external_job_id':'ENG-42'}).json()
    response=client.post('/api/job-import/preview',json={'url':'https://example.com/job'})
    assert response.status_code==200
    assert response.json()['duplicate_ids']==[created['id']]
    assert 'Possible duplicate' in response.json()['warnings'][0]
    assert client.get('/api/applications').json()['total']==1  # preview never saves
    app.dependency_overrides[current_owner]=lambda:OTHER
    result=client.post('/api/job-import/preview',json={'url':'https://example.com/job'}).json()
    assert result['duplicate_ids']==[]


def test_preview_url_duplicate_without_job_id(client,monkeypatch):
    url='https://example.com/job'
    monkeypatch.setattr(importer,'PublicFetcher',lambda:FixtureFetcher({url:'metadata.html'}))
    item=client.post('/api/applications',json={'company_name':'Example','job_title':'Engineer','job_url':url+'/?utm_source=test'}).json()
    assert client.post('/api/job-import/preview',json={'url':url}).json()['duplicate_ids']==[item['id']]


def test_preview_errors_and_auth(client,monkeypatch):
    monkeypatch.setattr(importer,'PublicFetcher',lambda:FixtureFetcher({}))
    assert client.post('/api/job-import/preview',json={'url':'https://example.com/job'}).status_code==422
    assert client.post('/api/job-import/preview',json={'url':'http://127.0.0.1'}).status_code==422
    assert client.post('/api/job-import/preview',json={'url':'x','owner_id':str(OTHER)}).status_code==422
    app.dependency_overrides.pop(current_owner)
    monkeypatch.setenv('SUPABASE_URL','https://test.supabase.co')
    monkeypatch.setenv('OWNER_ID',str(OTHER))
    from app.config import settings
    settings.cache_clear()
    try:
        assert client.post('/api/job-import/preview',json={'url':'https://example.com'}).status_code==401
    finally:
        settings.cache_clear()

@pytest.mark.parametrize('url',[
 'file:///etc/passwd','ftp://example.com/a','http://localhost/a','http://127.0.0.1',
 'http://169.254.169.254/latest/meta-data','http://10.0.0.1','http://[::1]',
 'http://[::ffff:127.0.0.1]','http://user:password@example.com',
 'https://example.com:8443','http://example.com\\@127.0.0.1','http://example.com\n/x',
 'http://[ff02::1]','http://[2001:db8::1]','http://corp.internal',
])
def test_unsafe_url_syntax(url):
    with pytest.raises(fetch.ImportFailure):fetch.parse_destination(url)

@pytest.mark.parametrize('addresses',[
 ['127.0.0.1'],['169.254.169.254'],['93.184.216.34','10.0.0.1'],['::ffff:192.168.1.1'],[],
])
def test_dns_rejects_private_and_mixed_answers(monkeypatch,addresses):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *args,**kwargs:[(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,443)) for ip in addresses])
    with pytest.raises(fetch.ImportFailure):fetch.resolve_public('example.com',443,time.monotonic()+1)


def test_dns_failure_and_deadline(monkeypatch):
    def fail(*args,**kwargs):raise socket.gaierror('test')
    monkeypatch.setattr(socket,'getaddrinfo',fail)
    with pytest.raises(fetch.ImportFailure):fetch.resolve_public('example.com',443,time.monotonic()+1)
    with pytest.raises(fetch.ImportFailure):fetch.remaining(time.monotonic()-1)


def test_pinned_connection_never_resolves_hostname_again(monkeypatch):
    sock=Mock()
    monkeypatch.setattr(socket,'socket',lambda *args:sock)
    resolver=Mock(side_effect=AssertionError('DNS re-resolution'))
    monkeypatch.setattr(socket,'getaddrinfo',resolver)
    context=Mock();context.wrap_socket.return_value=sock
    monkeypatch.setattr(fetch.ssl,'create_default_context',lambda:context)
    connection=fetch.PinnedConnection('example.com',443,'93.184.216.34',True,time.monotonic()+5)
    connection.connect()
    sock.connect.assert_called_once_with(('93.184.216.34',443))
    context.wrap_socket.assert_called_once_with(sock,server_hostname='example.com')
    resolver.assert_not_called()


def response(status=200,headers=None,body=b'<html></html>'):
    result=Mock(status=status)
    result.getheader.side_effect=lambda key,default=None:(headers or {'Content-Type':'text/html'}).get(key,default)
    chunks=iter([body,b''])
    result.read1.side_effect=lambda size:next(chunks)
    return result


def install_connections(monkeypatch,responses):
    connections=[]
    def connection(*args):
        conn=Mock();conn.getresponse.return_value=next(responses);connections.append(conn);return conn
    monkeypatch.setattr(fetch,'PinnedConnection',connection)
    monkeypatch.setattr(fetch,'resolve_public',lambda *args:'93.184.216.34')
    return connections


def test_safe_relative_redirect_and_no_credentials_forwarded(monkeypatch):
    connections=install_connections(monkeypatch,iter([response(302,{'Location':'/next'}),response()]))
    result=fetch.PublicFetcher().get('https://example.com/job')
    assert result.url=='https://example.com/next'
    headers=connections[0].request.call_args.kwargs['headers']
    assert 'Authorization' not in headers and 'Cookie' not in headers
    assert headers['Accept-Encoding']=='identity'
    assert all(c.close.called for c in connections)


def test_unsafe_redirect_is_not_requested(monkeypatch):
    connections=install_connections(monkeypatch,iter([response(302,{'Location':'http://127.0.0.1/secret'})]))
    with pytest.raises(fetch.ImportFailure):fetch.PublicFetcher().get('https://example.com/job')
    assert len(connections)==1

@pytest.mark.parametrize('responses',[
 [response(302,{'Location':'/job'}) for _ in range(4)],
 [response(headers={'Content-Type':'text/html','Content-Length':str(fetch.MAX_BYTES+1)})],
 [response(headers={'Content-Type':'text/html','Content-Encoding':'gzip'})],
 [response(headers={'Content-Type':'application/octet-stream'})],
 [response(403)],
 [response(body=b'x'*(fetch.MAX_BYTES+1))],
])
def test_transport_limits(monkeypatch,responses):
    install_connections(monkeypatch,iter(responses))
    with pytest.raises(fetch.ImportFailure):fetch.PublicFetcher().get('https://example.com/job')

@pytest.mark.parametrize('ip',['2002:7f00:1::','64:ff9b::a00:1','64:ff9b:1::a00:1','2001:0000:4136:e378:8000:63bf:3fff:fdd2'])
def test_ipv6_translation_ranges_rejected(ip):
    assert not fetch.public_ip(ip)

@pytest.mark.parametrize('body',['<title>Just a moment...</title>','<title>Sign in to continue</title>','<form id="challenge-form"></form>'])
def test_access_challenges_are_not_imported(body):
    with pytest.raises(fetch.ImportFailure):importer.extract_html(fetch.Page('https://example.com/job',body,'text/html'))


def test_job_ids_warn_even_when_urls_differ(client,monkeypatch):
    url='https://example.com/job'
    monkeypatch.setattr(importer,'PublicFetcher',lambda:FixtureFetcher({url:'jobposting.html'}))
    item=client.post('/api/applications',json={'company_name':'Example','job_title':'Engineer','job_url':'https://different.example.com/job','external_job_id':'ENG-42'}).json()
    assert client.post('/api/job-import/preview',json={'url':url}).json()['duplicate_ids']==[item['id']]


def test_dns_change_on_redirect_is_rejected(monkeypatch):
    answers=iter(['93.184.216.34','127.0.0.1'])
    monkeypatch.setattr(socket,'getaddrinfo',lambda *args,**kwargs:[(socket.AF_INET,socket.SOCK_STREAM,6,'',(next(answers),443))])
    connection=Mock();connection.getresponse.return_value=response(302,{'Location':'/next'})
    constructor=Mock(return_value=connection)
    monkeypatch.setattr(fetch,'PinnedConnection',constructor)
    with pytest.raises(fetch.ImportFailure):fetch.PublicFetcher().get('https://example.com/job')
    assert constructor.call_count==1


def test_dns_lookup_timeout(monkeypatch):
    future=Mock()
    from concurrent.futures import TimeoutError
    future.result.side_effect=TimeoutError()
    future.add_done_callback.side_effect=lambda callback:callback(future)
    monkeypatch.setattr(fetch._dns_pool,'submit',lambda *args:future)
    with pytest.raises(fetch.ImportFailure):fetch.resolve_public('example.com',443,time.monotonic()+1)


def test_total_deadline_closes_slow_connection(monkeypatch):
    # Trigger deadline callback deterministically without sleeping/networking.
    connection=Mock()
    connection.getresponse.side_effect=socket.timeout()
    monkeypatch.setattr(fetch,'PinnedConnection',lambda *args:connection)
    monkeypatch.setattr(fetch,'resolve_public',lambda *args:'93.184.216.34')
    timer=Mock()
    def make_timer(seconds,callback):
        timer.start.side_effect=callback
        return timer
    monkeypatch.setattr(fetch.threading,'Timer',make_timer)
    with pytest.raises(fetch.ImportFailure):fetch.PublicFetcher().get('https://example.com/job')
    connection.sock.shutdown.assert_called_once_with(socket.SHUT_RDWR)
    assert connection.close.called and timer.cancel.called


def test_standalone_jsonld_and_full_schema_type():
    data={'@type':'https://schema.org/JobPosting','title':'Engineer'}
    result=importer.finish(importer.extract_html(fetch.Page('https://example.com/job',json.dumps(data),'application/ld+json')))
    assert result.job_title=='Engineer' and result.source=='JobPosting JSON-LD'


def test_canonical_preserves_identity_query_and_rejects_other_hosts():
    assert importer.canonicalize('https://EXAMPLE.com/job/?gh_jid=42&utm_source=x#apply')=='https://example.com/job?gh_jid=42'
    warnings=[]
    assert importer.safe_canonical('https://other.example.com/job','https://example.com/job',warnings)=='https://example.com/job'
    assert warnings


def test_incomplete_response_is_rejected(monkeypatch):
    install_connections(monkeypatch,iter([response(headers={'Content-Type':'text/html','Content-Length':'500'},body=b'short')]))
    with pytest.raises(fetch.ImportFailure,match='incomplete page'):
        fetch.PublicFetcher().get('https://example.com/job')
