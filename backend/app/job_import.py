"""Read-only job previews. External content is data, never executable markup."""
import html
from html.parser import HTMLParser
import json
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_owner
from .db import get_db
from .job_fetch import ImportFailure, PublicFetcher, parse_destination
from .models import Application

router = APIRouter(prefix="/api/job-import", tags=["job import"])
FIELD_LIMITS = {"company_name": 200, "job_title": 200, "location": 200, "external_job_id": 200, "description": 28000}


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    url: str = Field(min_length=1, max_length=2048)


class Preview(BaseModel):
    company_name: str | None = None
    job_title: str | None = None
    location: str | None = None
    external_job_id: str | None = None
    description: str | None = None
    canonical_url: str
    source: str
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    duplicate_ids: list[UUID] = Field(default_factory=list)


class Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.canonical = None
        self.scripts = []
        self.script = None
        self.title = []
        self.in_title = False
        self.text = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            key = attrs.get("property") or attrs.get("name")
            if key and attrs.get("content"):
                self.meta[key.lower()] = attrs["content"]
        if tag == "link" and "canonical" in attrs.get("rel", "").lower().split():
            self.canonical = attrs.get("href")
        if tag == "title":
            self.in_title = True
        if tag in ("script", "style"):
            self.hidden += 1
        if tag == "script" and attrs.get("type", "").lower().split(";")[0] == "application/ld+json":
            self.script = []
        if tag in ("p", "div", "li", "br", "h1", "h2", "h3"):
            self.text.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag == "script" and self.script is not None:
            self.scripts.append("".join(self.script))
            self.script = None
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)
        if self.in_title:
            self.title.append(data)
        if not self.hidden:
            self.text.append(data)


def plain(value):
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    parser = Document()
    parser.feed(html.unescape(str(value)))
    result = re.sub(r"[ \t\r\f\v]+", " ", "".join(parser.text))
    result = re.sub(r"\n\s*\n", "\n", result).strip()
    return result or None


def canonicalize(url):
    url, _, _ = parse_destination(url)
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_") and k.lower() not in {"source", "ref", "referrer", "gh_src", "lever-source", "lever-origin", "fbclid", "gclid"}]
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/") or "/", urlencode(sorted(query)), ""))


def safe_canonical(value, base, warnings):
    if not isinstance(value, str) or not value:
        return canonicalize(base)
    try:
        result = canonicalize(urljoin(base, value))
        # Never trust external metadata to replace a link with a different host.
        if urlsplit(result).hostname != urlsplit(base).hostname:
            raise ImportFailure("Cross-host canonical")
        return result
    except ImportFailure:
        warnings.append("Ignored an unsafe or cross-site canonical URL.")
        return canonicalize(base)


def objects(value):
    # Iterative traversal avoids recursion on untrusted JSON-LD graphs.
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            yield item
            pending.extend(reversed(list(item.values())))
        elif isinstance(item, list):
            pending.extend(reversed(item))


def location_text(value):
    values = value if isinstance(value, list) else [value]
    results = []
    for item in values:
        if isinstance(item, str):
            results.append(item)
        elif isinstance(item, dict):
            address = item.get("address", item)
            if isinstance(address, dict):
                components = [address.get(k) for k in ("addressLocality", "addressRegion", "addressCountry")]
                country = components[-1]
                if isinstance(country, dict):
                    components[-1] = country.get("name")
                name = ", ".join(x for x in components if isinstance(x, str) and x)
                if name or isinstance(item.get("name"), str):
                    results.append(name or item["name"])
    return plain("; ".join(dict.fromkeys(results)))


def extract_html(page):
    doc = Document()
    if page.content_type in ("application/json", "application/ld+json"):
        doc.scripts.append(page.body)
    else:
        doc.feed(page.body)
    title = " ".join(doc.title).strip().lower()
    if re.search(r"^(just a moment|access denied|sign in|log in|login|captcha|verify you are human)\b", title) or any(marker in page.body.lower() for marker in ('id="challenge-form"', 'id="cf-challenge-running"', 'class="g-recaptcha"')):
        raise ImportFailure("This page requires sign-in or a human access check. Enter the details manually.")
    warnings = []
    jobs = []
    for script in doc.scripts:
        try:
            data = json.loads(script)
            for node in objects(data):
                types = node.get("@type", [])
                if any(isinstance(kind, str) and kind.rstrip("/").rsplit("/", 1)[-1] == "JobPosting" for kind in (types if isinstance(types, list) else [types])):
                    jobs.append(node)
        except (ValueError, RecursionError):
            warnings.append("Ignored malformed JSON-LD.")
    fields = {}
    if jobs:
        job = jobs[0]
        if len(jobs) > 1:
            warnings.append("Multiple JobPosting records found; review the first posting's details.")
        organization = job.get("hiringOrganization")
        identifier = job.get("identifier")
        fields = {
            "company_name": plain(organization.get("name")) if isinstance(organization, dict) else plain(organization),
            "job_title": plain(job.get("title")),
            "external_job_id": plain(identifier.get("value")) if isinstance(identifier, dict) else plain(identifier),
            "description": plain(job.get("description")),
            "location": location_text(job.get("jobLocation")),
        }
        if not fields["location"] and job.get("jobLocationType") == "TELECOMMUTE":
            fields["location"] = "Remote"
    # Metadata titles are suggestions, never split heuristically into invented fields.
    fallback = {"job_title": plain(doc.meta.get("og:title") or doc.meta.get("twitter:title") or "".join(doc.title)), "description": plain(doc.meta.get("description") or doc.meta.get("og:description")), "company_name": plain(doc.meta.get("og:site_name"))}
    for key, value in fallback.items():
        if not fields.get(key):
            fields[key] = value
    if not jobs:
        warnings.append("Only page metadata was available; it may describe the website rather than the job. Review all values.")
    canonical = safe_canonical(doc.canonical, page.url, warnings)
    return Preview(**fields, canonical_url=canonical, source="JobPosting JSON-LD" if jobs else "Page metadata", warnings=warnings)


def platform(url):
    parts = urlsplit(url)
    segments = parts.path.strip("/").split("/")
    host = parts.hostname
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io", "boards.eu.greenhouse.io", "job-boards.eu.greenhouse.io"} and len(segments) >= 3 and segments[1] == "jobs":
        return "greenhouse", segments[0], segments[2], "boards-api.eu.greenhouse.io" if ".eu." in host else "boards-api.greenhouse.io"
    if host in {"jobs.lever.co", "jobs.eu.lever.co"} and len(segments) >= 2:
        return "lever", segments[0], segments[1], "api.eu.lever.co" if host == "jobs.eu.lever.co" else "api.lever.co"
    if host == "jobs.ashbyhq.com" and len(segments) >= 2:
        return "ashby", segments[0], segments[1], "api.ashbyhq.com"
    return None


def ashby_job_matches(job, board, id):
    if not isinstance(job, dict) or not isinstance(job.get("jobUrl"), str):
        return False
    try:
        url, host, _ = parse_destination(job["jobUrl"])
        return host == "jobs.ashbyhq.com" and urlsplit(url).path.rstrip("/") == f"/{board}/{id}"
    except ImportFailure:
        return False


def read_json(fetcher, url):
    page = fetcher.get(url)
    try:
        value = json.loads(page.body)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, RecursionError):
        raise ImportFailure("The public posting API returned malformed data.") from None


def extract(url, fetcher):
    url, _, _ = parse_destination(url)
    info = platform(url)
    if not info:
        return extract_html(fetcher.get(url))
    kind, board, id, api_host = info
    # Identifiers are single safe path segments, not arbitrary API paths.
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", board) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", id):
        raise ImportFailure("The posting URL has an invalid board or job identifier.")
    warnings = []
    try:
        if kind == "greenhouse":
            job = read_json(fetcher, f"https://{api_host}/v1/boards/{board}/jobs/{id}")
            result = Preview(company_name=plain(job.get("company_name")), job_title=plain(job.get("title")), location=location_text(job.get("location")), external_job_id=plain(job.get("id")), description=plain(job.get("content")), canonical_url=canonicalize(url), source="Greenhouse public API")
        elif kind == "lever":
            job = read_json(fetcher, f"https://{api_host}/v0/postings/{board}/{id}?mode=json")
            categories = job.get("categories") if isinstance(job.get("categories"), dict) else {}
            result = Preview(job_title=plain(job.get("text")), location=plain(categories.get("location")), external_job_id=plain(job.get("id")), description=plain(job.get("descriptionPlain") or job.get("description")), canonical_url=canonicalize(url), source="Lever public API")
        else:
            data = read_json(fetcher, f"https://{api_host}/posting-api/job-board/{board}")
            jobs = data.get("jobs")
            if not isinstance(jobs, list):
                raise ImportFailure("The public posting API returned malformed data.")
            job = next((j for j in jobs if ashby_job_matches(j, board, id)), None)
            if job is None:
                raise ImportFailure("This posting is not available on the public job board.")
            result = Preview(job_title=plain(job.get("title")), location=plain(job.get("location")), external_job_id=id, description=plain(job.get("descriptionPlain") or job.get("descriptionHtml")), canonical_url=f"https://jobs.ashbyhq.com/{board}/{id}", source="Ashby public API")
        # Lever/Ashby public APIs don't supply an employer name. Use explicit page
        # data if available, never turn a board slug into a made-up company name.
        if not result.company_name:
            try:
                supplemental = extract_html(fetcher.get(url))
                company = supplemental.company_name
                if company and company.lower() not in {"lever", "ashby", "greenhouse"}:
                    result.company_name = company
                    result.source += " + " + supplemental.source
                    result.warnings.extend(supplemental.warnings)
            except ImportFailure:
                result.warnings.append("Employer name could not be read from the public page; enter it manually.")
        return result
    except ImportFailure:
        # A blocked API is not bypassed via private endpoints or browser automation.
        # Only try the same public posting's ordinary HTML as a documented fallback.
        warnings.append("The public posting API was unavailable; used the public page instead.")
        result = extract_html(fetcher.get(url))
        result.warnings = warnings + result.warnings
        return result


def finish(result):
    for field, limit in FIELD_LIMITS.items():
        value = getattr(result, field)
        if value and len(value) > limit:
            setattr(result, field, value[:limit])
            result.warnings.append(f"{field.replace('_', ' ').capitalize()} was truncated to fit the form.")
    result.missing_fields = [field for field in FIELD_LIMITS if not getattr(result, field)]
    if not any(getattr(result, field) for field in FIELD_LIMITS):
        result.warnings.append("No job details found. Continue with manual entry.")
    result.warnings.append("Review extracted details. Applied is a tracking default; application submission has not been verified.")
    return result


@router.post("/preview", response_model=Preview)
def preview(data: PreviewRequest, owner: UUID = Depends(current_owner), db: Session = Depends(get_db)):
    try:
        result = finish(extract(data.url, PublicFetcher()))
    except ImportFailure as exc:
        raise HTTPException(422, str(exc)) from None
    urls = {canonicalize(data.url), result.canonical_url}
    # Owner's lightweight identity fields only; no notes or other users' records.
    for id, job_url, external_id in db.execute(select(Application.id, Application.job_url, Application.external_job_id).where(Application.owner_id == owner)):
        same_url = False
        if job_url:
            try:
                same_url = canonicalize(job_url) in urls
            except ImportFailure:
                pass
        if same_url or (external_id and external_id == result.external_job_id):
            result.duplicate_ids.append(id)
    if result.duplicate_ids:
        result.warnings.insert(0, "Possible duplicate: a matching job ID or canonical URL already exists in your applications.")
    return result
