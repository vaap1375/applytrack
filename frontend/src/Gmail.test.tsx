import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { GmailPanel, GmailReview, type GmailItem } from './Gmail';
import { request, type Application } from './api';
vi.mock('./api',()=>({request:vi.fn(),statuses:['Saved','Applied','Assessment','Interview','Offer','Rejected','Withdrawn']}));
const api=vi.mocked(request);
const application={id:'a1',company_name:'Example Labs',job_title:'Backend Engineer',status:'Applied',status_revision:3} as Application;
const item:GmailItem={id:'g1',gmail_id:'message1',subject:'Interview invitation',sender:'recruiting@example.com',excerpt:'We invite you to an interview.',received_at:'2026-10-26T12:00:00Z',classification:'interview',class_confidence:.99,match_confidence:.99,application_id:'a1',proposed_status:'Interview',old_status:null,state:'review',reason:'Automatic updates are disabled.',evidence:[{application_id:'a1',company_name:'Example Labs',job_title:'Backend Engineer',score:.99,reasons:['Exact external job ID'],trusted_sender:true}]};
const connection={configured:true,connected:true,email:'owner@example.com',health:'connected',last_sync_at:null,auto_updates:false,lookback_days:30,dry_run_at:null,more:false,stats:{processed:0,matches:0,updates:0}};
beforeEach(()=>{api.mockReset();window.history.replaceState(null,'','/');});afterEach(cleanup);
it('requires explicit review and sends the displayed status revision',async()=>{
 api.mockResolvedValue(application);const done=vi.fn();
 render(<GmailReview item={item} token="token" choices={[application]} onDone={done} onOpen={vi.fn()}/>);
 expect(screen.getByRole('button',{name:'Accept change'})).toBeDisabled();
 await screen.findByText('Applied');
 fireEvent.click(screen.getByRole('checkbox'));
 fireEvent.click(screen.getByRole('button',{name:'Accept change'}));
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/gmail/messages/g1/accept','token',{method:'POST',body:JSON.stringify({application_id:'a1',status:'Interview',expected_revision:3})}));
 expect(done).toHaveBeenCalled();
});
it('shows stale-revision failures and clears approval acknowledgment',async()=>{
 api.mockImplementation(async path=>{if(path.includes('/accept'))throw new Error('Application status changed. Reload before reviewing this suggestion.');return application;});
 render(<GmailReview item={item} token="token" choices={[application]} onDone={vi.fn()} onOpen={vi.fn()}/>);
 await screen.findByText('Applied');fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'Accept change'}));
 expect(await screen.findByRole('alert')).toHaveTextContent('Application status changed');expect(screen.getByRole('checkbox')).not.toBeChecked();
});
it('dismisses uncertain suggestions without changing an application',async()=>{
 api.mockResolvedValue({});const done=vi.fn();
 render(<GmailReview item={{...item,application_id:null,evidence:[],match_confidence:0}} token="token" choices={[application]} onDone={done} onOpen={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'Dismiss'}));
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/gmail/messages/g1/dismiss','token',{method:'POST'}));
 expect(done).toHaveBeenCalled();expect(api.mock.calls.some(args=>args[0].includes('/applications/'))).toBe(false);
});
it('undoes a recent applied change and exposes its audit context',async()=>{
 api.mockResolvedValue(application);const done=vi.fn();
 render(<GmailReview item={{...item,state:'applied',old_status:'Applied'}} token="token" choices={[application]} onDone={done} onOpen={vi.fn()}/>);
 expect(screen.getByText('Applied → Interview')).toBeVisible();
 fireEvent.click(screen.getByRole('button',{name:'Undo change'}));
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/gmail/messages/g1/undo','token',{method:'POST'}));expect(done).toHaveBeenCalled();
});
it('shows unconfigured setup and keeps automatic updates off',async()=>{
 api.mockImplementation(async path=>path==='/gmail/connection'?{...connection,configured:false,connected:false,email:null}:path.startsWith('/applications')?{items:[]}:{items:[],total:0});
 render(<GmailPanel token="token" onChange={vi.fn()} onOpen={vi.fn()}/>);
 expect(await screen.findByRole('button',{name:'Connect Gmail'})).toBeDisabled();
 expect(screen.getByRole('button',{name:'Enable automatic updates'})).toBeDisabled();
 expect(screen.getByText(/Gmail server credentials/)).toBeVisible();
});
it('syncs manually and only enables automation after a completed acknowledged dry run',async()=>{
 let current={...connection};
 api.mockImplementation(async (path,_token,init)=>{
  if(path==='/gmail/connection')return current;
  if(path==='/gmail/sync'){current={...current,dry_run_at:'2026-10-26T12:00:00Z' as unknown as null,stats:{processed:2,matches:1,updates:0}};return current;}
  if(path==='/gmail/settings'){current={...current,auto_updates:JSON.parse(String(init?.body)).auto_updates};return current;}
  if(path.startsWith('/applications'))return {items:[application]};return {items:[],total:0};
 });
 render(<GmailPanel token="token" onChange={vi.fn()} onOpen={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Sync Gmail now'}));
 await screen.findByText('Gmail sync complete. Review the results below.');
 expect(screen.getByRole('button',{name:'Enable automatic updates'})).toBeDisabled();
 fireEvent.click(screen.getByRole('checkbox',{name:/completed and reviewed/}));
 fireEvent.click(screen.getByRole('button',{name:'Enable automatic updates'}));
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/gmail/settings','token',{method:'PATCH',body:JSON.stringify({auto_updates:true,reviewed_dry_run:true})}));
 expect(await screen.findByRole('button',{name:'Disable automatic updates'})).toBeVisible();
});
it('disconnects with deletion confirmation instead of immediately deleting data',async()=>{
 api.mockImplementation(async path=>path==='/gmail/connection'?connection:path.startsWith('/applications')?{items:[]}:{items:[],total:0});
 render(<GmailPanel token="token" onChange={vi.fn()} onOpen={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Disconnect Gmail'}));
 expect(api.mock.calls.some(args=>args[0]==='/gmail/disconnect')).toBe(false);
 expect(screen.getByRole('checkbox',{name:/Delete retained Gmail/})).toBeChecked();
 fireEvent.click(screen.getByRole('button',{name:'Confirm disconnect'}));
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/gmail/disconnect','token',{method:'POST',body:JSON.stringify({delete_data:true})}));
});
it('shows OAuth cancellation without leaking authorization parameters',async()=>{
 window.history.replaceState(null,'','/#gmail=cancelled');
 api.mockImplementation(async path=>path==='/gmail/connection'?connection:path.startsWith('/applications')?{items:[]}:{items:[],total:0});
 render(<GmailPanel token="token" onChange={vi.fn()} onOpen={vi.fn()}/>);
 expect(await screen.findByText('Gmail authorization was cancelled.')).toBeVisible();expect(window.location.hash).toBe('');
});
it('shows safe connection/sync errors and allows retry',async()=>{
 api.mockRejectedValueOnce(new Error('Gmail is temporarily unavailable')).mockResolvedValue({items:[],total:0});
 render(<GmailPanel token="token" onChange={vi.fn()} onOpen={vi.fn()}/>);
 expect(await screen.findByRole('alert')).toHaveTextContent('Gmail is temporarily unavailable');expect(screen.getByRole('button',{name:'Retry Gmail'})).toBeEnabled();
});
