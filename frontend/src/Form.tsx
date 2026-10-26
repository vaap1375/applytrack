import { useRef, useState, type FormEvent } from 'react';
import { statuses, type Application, type ApplicationInput, type JobPreview } from './api';

type Props = {
  item?: Application;
  onSave: (data: ApplicationInput) => Promise<void>;
  onCancel: () => void;
  onPreview?: (url: string) => Promise<JobPreview>;
};

export function ApplicationForm({item, onSave, onCancel, onPreview}: Props) {
  const formRef = useRef<HTMLFormElement>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [importError, setImportError] = useState('');
  const [preview, setPreview] = useState<JobPreview | null>(null);
  const [jobUrl, setJobUrl] = useState(item?.job_url || '');

  async function autoFill() {
    const form = formRef.current;
    const urlInput = form?.elements.namedItem('job_url') as HTMLInputElement | null;
    if (!form || !onPreview || !urlInput) return;
    if (!jobUrl.trim()) {
      setImportError('Paste a public job posting URL first. You can also enter details manually.');
      urlInput.focus();
      return;
    }
    if (!urlInput.reportValidity()) return;
    setExtracting(true);
    setImportError('');
    setPreview(null);
    try {
      const result = await onPreview(jobUrl.trim());
      for (const field of ['company_name', 'job_title', 'location', 'external_job_id'] as const) {
        const input = form.elements.namedItem(field) as HTMLInputElement;
        // Missing values never erase existing manual entries.
        if (result[field]) input.value = result[field];
      }
      if (result.description) {
        const notes = form.elements.namedItem('notes') as HTMLTextAreaElement;
        const description = `Job description:\n${result.description}`;
        if (!notes.value.includes(description)) {
          notes.value = [notes.value.trim(), description].filter(Boolean).join('\n\n').slice(0, 30000);
        }
      }
      setJobUrl(result.canonical_url);
      setPreview(result);
    } catch (err) {
      setImportError(`${err instanceof Error ? err.message : 'Could not extract job details.'} Your entries are preserved. Continue manually or try another link.`);
    } finally {
      setExtracting(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setBusy(true);
    const fields = new FormData(event.currentTarget);
    const value = (name: string) => String(fields.get(name) || '').trim();
    try {
      await onSave({company_name:value('company_name'),job_title:value('job_title'),location:value('location')||null,job_url:value('job_url')||null,external_job_id:value('external_job_id')||null,status:value('status') as ApplicationInput['status'],applied_at:value('applied_at') ? new Date(value('applied_at')+'T12:00:00').toISOString() : null,notes:value('notes')||null});
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save application');
    } finally {
      setBusy(false);
    }
  }

  return <form ref={formRef} onSubmit={submit} className="application-form">
    <section className={!item ? 'job-import' : undefined} aria-label="Job link">
      <label>Job URL<input name="job_url" type="url" pattern="https?://.*" maxLength={2048} value={jobUrl} onChange={e=>{setJobUrl(e.target.value);setPreview(null);setImportError('');}} placeholder="https://company.com/careers/…" autoFocus={!item} disabled={extracting || busy} /></label>
      {!item && <>
        <p className="import-help">Paste a public posting to fill in the details, or enter them below.</p>
        {onPreview && <button type="button" className="secondary" disabled={extracting || busy} onClick={()=>void autoFill()}>{extracting ? 'Reading job posting…' : 'Auto-fill from link'}</button>}
        {extracting && <p role="status" className="import-help">Retrieving public job details. Nothing will be saved yet.</p>}
        {importError && <p role="alert" className="error import-message">{importError}</p>}
        {preview && <div className="import-result" role="status">
          <strong>Extraction source: {preview.source}</strong>
          <p>Details are editable below. Nothing has been saved.</p>
          {preview.missing_fields.length > 0 && <p>Not found: {preview.missing_fields.map(field=>field.replaceAll('_',' ')).join(', ')}. Fill these in if known.</p>}
          {preview.warnings.length > 0 && <ul>{preview.warnings.map((warning,index)=><li key={index}>{warning}</li>)}</ul>}
        </div>}
      </>}
    </section>
    <fieldset disabled={extracting || busy} className="application-fields">
      <div className="form-grid"><label>Company name <span>*</span><input name="company_name" defaultValue={item?.company_name} required maxLength={200} placeholder="e.g. Company name" /></label>
      <label>Job title <span>*</span><input name="job_title" defaultValue={item?.job_title} required maxLength={200} placeholder="e.g. Software Engineer" /></label></div>
      <div className="form-grid"><label>Location<input name="location" defaultValue={item?.location||''} maxLength={200} placeholder="City or remote" /></label><label>External job ID<input name="external_job_id" defaultValue={item?.external_job_id||''} maxLength={200} placeholder="Optional reference" /></label></div>
      <div className="form-grid"><label>Status<select name="status" defaultValue={item?.status||'Applied'}>{statuses.map(s=><option key={s}>{s}</option>)}</select></label><label>Application date<input name="applied_at" type="date" defaultValue={item?.applied_at?.slice(0,10)||''} /></label></div>
      {!item && <p className="import-help">Applied is a tracking default. Importing a link does not submit an application or verify that you applied.</p>}
      <label>Notes<textarea name="notes" rows={5} defaultValue={item?.notes||''} maxLength={30000} placeholder="Contacts, interview details, or what caught your eye…" /></label>
    </fieldset>
    {error && <p role="alert" className="error">{error}</p>}
    <div className="form-actions"><button type="button" className="secondary" disabled={busy} onClick={onCancel}>Cancel</button><button disabled={busy || extracting}>{busy?'Saving…':item?'Save changes':'Add application'}</button></div>
  </form>;
}
