import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ApplicationForm } from './Form';
import type { JobPreview } from './api';
afterEach(cleanup);
const preview: JobPreview = {
  company_name:'Example Labs', job_title:'Software Engineer', location:'Remote',
  external_job_id:'ENG-42', description:'Build useful tools.',
  canonical_url:'https://example.com/jobs/42', source:'JobPosting JSON-LD',
  missing_fields:[], warnings:['Possible duplicate: a matching job ID already exists.'], duplicate_ids:['existing'],
};
function paste(url='https://example.com/jobs/42?utm_source=test') {
  fireEvent.change(screen.getByLabelText('Job URL'),{target:{value:url}});
  fireEvent.click(screen.getByRole('button',{name:'Auto-fill from link'}));
}
it('previews, reports source/duplicates, allows correction, and only saves explicitly',async()=>{
  const save=vi.fn().mockResolvedValue(undefined);
  const extract=vi.fn().mockResolvedValue(preview);
  render(<ApplicationForm onPreview={extract} onSave={save} onCancel={()=>{}}/>);
  paste();
  expect(await screen.findByText('Extraction source: JobPosting JSON-LD')).toBeVisible();
  expect(screen.getByText(/Possible duplicate/)).toBeVisible();
  expect(screen.getByLabelText(/Company name/)).toHaveValue('Example Labs');
  expect(screen.getByLabelText(/Job title/)).toHaveValue('Software Engineer');
  expect(screen.getByLabelText('Location')).toHaveValue('Remote');
  expect(screen.getByLabelText('External job ID')).toHaveValue('ENG-42');
  expect(screen.getByLabelText('Job URL')).toHaveValue(preview.canonical_url);
  expect(screen.getByLabelText('Notes')).toHaveValue('Job description:\nBuild useful tools.');
  expect(screen.getByLabelText('Status')).toHaveValue('Applied');
  expect(screen.getByText(/does not submit an application/)).toBeVisible();
  expect(save).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText(/Job title/),{target:{value:'Senior Engineer'}});
  fireEvent.click(screen.getByRole('button',{name:'Add application'}));
  await waitFor(()=>expect(save).toHaveBeenCalledWith(expect.objectContaining({job_title:'Senior Engineer',status:'Applied'})));
});
it('preserves manual entry on failure and can still save',async()=>{
  const save=vi.fn().mockResolvedValue(undefined);
  render(<ApplicationForm onPreview={vi.fn().mockRejectedValue(new Error('Posting access restricted.'))} onSave={save} onCancel={()=>{}}/>);
  fireEvent.change(screen.getByLabelText(/Company name/),{target:{value:'My company'}});
  fireEvent.change(screen.getByLabelText(/Job title/),{target:{value:'Engineer'}});
  fireEvent.change(screen.getByLabelText('Notes'),{target:{value:'My personal notes'}});
  paste();
  expect(await screen.findByRole('alert')).toHaveTextContent('Your entries are preserved. Continue manually');
  expect(screen.getByLabelText('Notes')).toHaveValue('My personal notes');
  fireEvent.click(screen.getByRole('button',{name:'Add application'}));
  await waitFor(()=>expect(save).toHaveBeenCalledWith(expect.objectContaining({company_name:'My company',notes:'My personal notes'})));
});
it('shows loading and blocks saving until the preview finishes',async()=>{
  let complete!:(value:JobPreview)=>void;
  const pending=new Promise<JobPreview>(resolve=>{complete=resolve;});
  render(<ApplicationForm onPreview={()=>pending} onSave={vi.fn()} onCancel={()=>{}}/>);
  paste();
  expect(screen.getByRole('button',{name:'Reading job posting…'})).toBeDisabled();
  expect(screen.getByRole('button',{name:'Add application'})).toBeDisabled();
  expect(screen.getByLabelText(/Company name/)).toBeDisabled();
  complete(preview);
  await screen.findByText('Extraction source: JobPosting JSON-LD');
  expect(screen.getByRole('button',{name:'Add application'})).toBeEnabled();
});
it('keeps missing fields and personal notes intact',async()=>{
  render(<ApplicationForm onPreview={vi.fn().mockResolvedValue({...preview,company_name:null,missing_fields:['company_name']})} onSave={vi.fn()} onCancel={()=>{}}/>);
  fireEvent.change(screen.getByLabelText(/Company name/),{target:{value:'Entered manually'}});
  fireEvent.change(screen.getByLabelText('Notes'),{target:{value:'Interview contact'}});
  paste();
  await screen.findByText(/Not found: company name/);
  expect(screen.getByLabelText(/Company name/)).toHaveValue('Entered manually');
  expect(screen.getByLabelText('Notes')).toHaveValue('Interview contact\n\nJob description:\nBuild useful tools.');
});
it('asks for a URL without disabling manual entry',async()=>{
  const extract=vi.fn();
  render(<ApplicationForm onPreview={extract} onSave={vi.fn()} onCancel={()=>{}}/>);
  fireEvent.click(screen.getByRole('button',{name:'Auto-fill from link'}));
  expect(screen.getByRole('alert')).toHaveTextContent('Paste a public job posting URL first');
  expect(extract).not.toHaveBeenCalled();
  expect(screen.getByLabelText(/Company name/)).toBeEnabled();
});
