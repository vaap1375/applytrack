import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApplicationForm } from './Form';
import { ApplicationList } from './App';
import { request, type Application } from './api';
afterEach(()=>{cleanup();vi.restoreAllMocks();});
describe('application form',()=>{
 it('submits required fields and a nullable date',async()=>{
  const save=vi.fn().mockResolvedValue(undefined);
  render(<ApplicationForm onSave={save} onCancel={()=>{}}/>);
  fireEvent.change(screen.getByLabelText(/Company name/),{target:{value:'Acme'}});
  fireEvent.change(screen.getByLabelText(/Job title/),{target:{value:'Engineer'}});
  fireEvent.click(screen.getByRole('button',{name:'Add application'}));
  await waitFor(()=>expect(save).toHaveBeenCalledWith(expect.objectContaining({company_name:'Acme',job_title:'Engineer',status:'Applied',applied_at:null})));
 });
 it('shows save errors and lets the user retry',async()=>{
  render(<ApplicationForm onSave={vi.fn().mockRejectedValue(new Error('Network unavailable'))} onCancel={()=>{}}/>);
  fireEvent.change(screen.getByLabelText(/Company name/),{target:{value:'Acme'}});
  fireEvent.change(screen.getByLabelText(/Job title/),{target:{value:'Engineer'}});
  fireEvent.click(screen.getByRole('button',{name:'Add application'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('Network unavailable');
  expect(screen.getByRole('button',{name:'Add application'})).toBeEnabled();
 });
 it('marks required inputs and restricts URLs',()=>{
  render(<ApplicationForm onSave={vi.fn()} onCancel={()=>{}}/>);
  expect(screen.getByLabelText(/Company name/)).toBeRequired();
  expect(screen.getByLabelText(/Job title/)).toBeRequired();
  const url=screen.getByLabelText('Job URL');fireEvent.change(url,{target:{value:'javascript:alert(1)'}});
  expect(url).toBeInvalid();
 });
});
it('lists applications and opens details',()=>{
 const open=vi.fn();const item={id:'1',company_name:'Acme',job_title:'Engineer',status:'Applied',location:'Remote',applied_at:null} as Application;
 render(<ApplicationList items={[item]} onOpen={open}/>);
 expect(screen.getByText('Engineer')).toBeVisible();expect(screen.getByText('Applied')).toBeVisible();
 fireEvent.click(screen.getByRole('button',{name:'View Acme'}));expect(open).toHaveBeenCalledWith(item);
});
it('shows an honest empty state',()=>{render(<ApplicationList items={[]} onOpen={()=>{}}/>);expect(screen.getByText('No applications here yet')).toBeVisible();});
it('surfaces backend errors',async()=>{vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,status:401,json:async()=>({error:{message:'Invalid or expired access token'}})}));await expect(request('/applications','token')).rejects.toThrow('Invalid or expired access token');vi.unstubAllGlobals();});
