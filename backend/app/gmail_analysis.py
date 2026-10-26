"""Deterministic conservative rules. Scores are rule strength, not probabilities."""
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parseaddr
from email.header import decode_header, make_header
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

TARGETS = {'confirmation':'Applied','assessment':'Assessment','interview':'Interview','rejection':'Rejected','offer':'Offer'}
RECRUITING = re.compile(r'\b(application|applying|assessment|interview|recruiter|recruiting|hiring|candidate|job offer|employment offer|coding challenge|position|talent acquisition)\b',re.I)
ATS = ('greenhouse.io','greenhouse-mail.io','lever.co','ashbyhq.com','myworkday.com','workday.com')
SHARED = ATS + ('linkedin.com','indeed.com','glassdoor.com','ziprecruiter.com','wellfound.com')
FREE_MAIL = {'gmail.com','outlook.com','hotmail.com','yahoo.com','proton.me','icloud.com'}


class EmailHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]
        self.stack=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        hidden = tag in {'blockquote','script','style','head'} or 'gmail_quote' in attrs.get('class','')
        if tag not in {'br','hr','img','meta','link','input'}:
            self.stack.append((tag,hidden or any(item[1] for item in self.stack)))
        if not any(item[1] for item in self.stack):
            if tag in {'p','div','br','li'}:self.parts.append('\n')
            if tag=='a':
                href=attrs.get('href','')
                if href.startswith(('https://','http://')):self.parts.append(' '+href+' ')
    def handle_endtag(self,tag):
        for index in range(len(self.stack)-1,-1,-1):
            if self.stack[index][0]==tag:
                del self.stack[index:]
                break
    def handle_data(self,data):
        if not any(item[1] for item in self.stack):self.parts.append(data)


def strip_thread(text):
    lines=[]
    forwarded=False
    all_lines=text.splitlines()
    for index,line in enumerate(all_lines):
        trimmed=line.strip()
        if trimmed.startswith('On ') and re.search(r'wrote:', ' '.join(all_lines[index:index+4]),re.I):
            break
        if re.search(r'forwarded message|begin forwarded|original message',trimmed,re.I) or re.match(r'^From:.*@',trimmed,re.I):
            forwarded=True
            break
        if re.match(r'On .{0,200}wrote:',trimmed,re.I) or trimmed in {'--','-- '} or re.match(r'^(best regards|kind regards|sincerely|regards|best|thanks|thank you)[,!]?$' ,trimmed,re.I):
            break
        if trimmed.startswith('>'):continue
        lines.append(line)
    return '\n'.join(lines).strip()[:32000],forwarded


@dataclass
class Email:
    id: str
    subject: str
    sender: str
    sender_domain: str
    body: str
    received_at: datetime
    forwarded: bool
    dkim_verified: bool
    excluded: bool


def parse_message(message):
    headers={}
    for entry in message.get('payload',{}).get('headers',[]):
        key=entry.get('name','').lower()
        headers.setdefault(key,entry.get('value',''))  # first Gmail-added auth result
    payload=message.get('payload',{})
    plain=[];rich=[];pending=[payload];seen=0
    while pending and seen<100:
        part=pending.pop();seen+=1
        if not isinstance(part,dict):continue
        pending.extend(reversed(part.get('parts',[])[:100]))
        if part.get('filename'):continue  # never read attachments
        data=part.get('body',{}).get('data','')
        if not isinstance(data,str) or len(data)>200000:continue
        try:text=base64.urlsafe_b64decode(data+'='*(-len(data)%4)).decode('utf-8',errors='replace')[:32000]
        except (ValueError,TypeError):continue
        if part.get('mimeType')=='text/plain':plain.append(text)
        elif part.get('mimeType')=='text/html':
            parser=EmailHTML();parser.feed(text);rich.append(''.join(parser.parts))
    body,forwarded=strip_thread('\n'.join(plain or rich))
    try:raw_subject=str(make_header(decode_header(headers.get('subject',''))))
    except (ValueError,LookupError,UnicodeError):raw_subject=headers.get('subject','')
    subject=re.sub(r'[\x00-\x1f\x7f]',' ',raw_subject)[:300]
    sender=parseaddr(headers.get('from',''))[1].lower()[:320]
    domain=sender.rsplit('@',1)[-1] if '@' in sender else ''
    auth=headers.get('authentication-results','')
    passed=re.search(r'\bdkim=pass\b([^;]*)',auth,re.I)
    signed_domain=''
    if passed:
        domain_param=re.search(r'\bheader\.d=([a-z0-9.-]+)',passed[1],re.I)
        identity_param=re.search(r'\bheader\.i=([^\s;]+)',passed[1],re.I)
        signed_domain=domain_param[1].lower() if domain_param else identity_param[1].rsplit('@',1)[-1].lower() if identity_param and '@' in identity_param[1] else ''
    verified=bool(auth.lower().startswith('mx.google.com;') and signed_domain and (domain==signed_domain or domain.endswith('.'+signed_domain)))
    try:received=datetime.fromtimestamp(int(message['internalDate'])/1000,timezone.utc)
    except (KeyError,ValueError,TypeError,OverflowError,OSError):raise ValueError('Missing valid Gmail timestamp') from None
    return Email(str(message['id']),subject,sender,domain,body,received,
                 forwarded or bool(re.match(r'^(fwd?|fw):',subject,re.I)),verified,
                 bool({'SENT','DRAFT','SPAM','TRASH'} & set(message.get('labelIds',[]))))


def classify(email):
    if email.forwarded or email.excluded:
        return 'unknown',0.0,'Forwarded/quoted or excluded content requires review.'
    text=email.subject+'\n'+email.body
    if re.search(r"\b(?:not (?:a |an |your )?(?:(?:job|employment) )?offer|cannot offer|can't offer|no (?:job )?offer|not offering)\b",text,re.I):
        return 'unknown',0.0,'Negated offer wording requires review.'
    patterns={
        'confirmation':r'\b(?:thank you for applying|we (?:have )?received your application|your application (?:has been|was) (?:successfully )?(?:received|submitted))\b',
        'assessment':r'\b(?:invite you to (?:complete|take) (?:an? |the |our )?(?:online |coding |technical )?(?:assessment|coding challenge)|please complete (?:the |our |your |an? )?(?:online |coding |technical )?(?:assessment|coding challenge))\b',
        'interview':r'\b(?:invite you to (?:an? |the |our )?(?:technical |onsite |virtual )?interview|we would like to schedule (?:an? |your )?interview|please (?:select|choose|book) (?:an? |your )?interview (?:time|slot))\b',
        'rejection':r"\b(?:we (?:will not|won't|are unable to) (?:be )?(?:moving|move|proceed|proceeding) (?:forward )?(?:with your (?:application|candidacy)|with you)|we (?:have )?decided (?:not to proceed|to move forward with other candidates)|we are not moving forward with your application)\b",
        'offer':r'\b(?:we are (?:pleased|delighted|excited) to offer you (?:the |a |an )?(?:position|role|job)|we would like to offer you (?:the |a |an )?(?:position|role)|attached (?:is|please find) your (?:formal )?(?:job|employment) offer)\b',
    }
    hits=[]
    for event,pattern in patterns.items():
        for match in re.finditer(pattern,text,re.I):
            # Conditional/negated statements must not become asserted events.
            sentence=re.split(r'[.!?\n]',text[:match.start()])[-1] + re.split(r'[.!?\n]',text[match.start():])[0]
            if re.search(r"\b(if|unless|might|may|could|cannot|can't|not able|not ready)\b",sentence,re.I):
                return 'unknown',0.0,'Conditional or negated event language requires review.'
            hits.append(event)
    unique=set(hits)
    if len(unique)>1:return 'unknown',0.0,'Conflicting event language requires review.'
    if unique:
        event=unique.pop()
        return event,0.99,'Explicit '+event+' language in current message.'
    if RECRUITING.search(text):return 'recruiter',0.5,'Recruiting-related message without an explicit status event.'
    return 'unknown',0.0,'No reliable status evidence.'


def normalized(value):
    return re.sub(r'[^a-z0-9]+',' ',value.lower()).strip()


def contains(text,value):
    term=normalized(value)
    return len(term)>=3 and bool(re.search(r'(?<!\w)'+re.escape(term)+r'(?!\w)',normalized(text)))


def host_for(application):
    try:
        host=(urlsplit(application.job_url or '').hostname or '').lower()
    except ValueError:return ''
    if any(host==suffix or host.endswith('.'+suffix) for suffix in SHARED):return ''
    return re.sub(r'^(?:www|jobs|careers)\.','',host)


def match_applications(email,applications,rules):
    text=email.subject+'\n'+email.body
    candidates=[]
    for app in applications:
        rule=rules.get(app.id)
        names=[app.company_name]+(rule.aliases if rule else [])
        company=any(contains(text,name) for name in names)
        title=contains(text,app.job_title)
        job_id=bool(app.external_job_id and len(app.external_job_id)>=4 and re.search(r'(?<![a-z0-9])'+re.escape(app.external_job_id)+r'(?![a-z0-9])',text,re.I))
        urls=re.findall(r'https?://[^\s<>"\)]+',text)
        url_match=False
        if app.job_url:
            from .job_import import canonicalize
            from .job_fetch import ImportFailure
            try:url_match=any(canonicalize(url.rstrip('.,;'))==canonicalize(app.job_url) for url in urls)
            except ImportFailure:pass
        domains=([host_for(app)] if host_for(app) else [])+(rule.sender_domains if rule else [])
        domain=any(d and (email.sender_domain==d or email.sender_domain.endswith('.'+d)) for d in domains if d not in FREE_MAIL)
        if not any([company,job_id,url_match,domain]):continue
        reasons=[name for flag,name in [(company,'Company/alias explicitly mentioned'),(title,'Job title explicitly mentioned'),(job_id,'Exact external job ID'),(url_match,'Exact application URL'),(domain,'Sender domain matches employer rule/URL')] if flag]
        score=0.99 if (job_id or url_match) and company and title else 0.8 if title and (company or domain) else 0.5
        trusted_sender=email.dkim_verified and (domain or any(email.sender_domain==d or email.sender_domain.endswith('.'+d) for d in ATS))
        candidates.append({'application_id':str(app.id),'company_name':app.company_name,'job_title':app.job_title,'score':score,'reasons':reasons,'trusted_sender':bool(trusted_sender)})
    candidates.sort(key=lambda item:item['score'],reverse=True)
    # Any other plausible company/title/ID candidate makes automation unsafe.
    plausible=[c for c in candidates if c['score']>=0.8 or 'Exact external job ID' in c['reasons'] or 'Exact application URL' in c['reasons']]
    hard=[c for c in candidates if 'Exact external job ID' in c['reasons'] or 'Exact application URL' in c['reasons']]
    winner=hard[0] if len(hard)==1 and hard[0]['score']>=0.99 else plausible[0] if len(plausible)==1 else None
    return winner,candidates[:10]


def safe_transition(application,target,email_time):
    if not target:return False,'No proposed status.'
    if application.status in {'Offer','Rejected','Withdrawn'}:return False,'Terminal status is protected from automatic changes.'
    if application.status_manual_at and application.status_manual_at>=email_time:return False,'A newer manual status correction is protected.'
    if application.status_changed_at and application.status_changed_at>=email_time:return False,'A newer status event is protected.'
    rank={'Saved':0,'Applied':1,'Assessment':2,'Interview':3,'Offer':4}
    if target==application.status:return False,'Application already has this status.'
    if target!='Rejected' and rank.get(target,-1)<=rank.get(application.status,-1):return False,'Automatic status regression is blocked.'
    return True,'Reliable event advances the application.'
