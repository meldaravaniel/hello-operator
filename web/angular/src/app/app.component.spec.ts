import { TestBed, ComponentFixture } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { BehaviorSubject } from 'rxjs';

import { AppComponent } from './app.component';
import { ApiService } from './api.service';

describe('AppComponent', () => {
  let fixture: ComponentFixture<AppComponent>;
  let statusSubject: BehaviorSubject<string>;
  let fakeApi: { status$: any; refreshStatus: jest.Mock };

  beforeEach(async () => {
    statusSubject = new BehaviorSubject<string>('unknown');
    fakeApi = {
      status$: statusSubject.asObservable(),
      refreshStatus: jest.fn(),
    };

    await TestBed.configureTestingModule({
      imports: [AppComponent],
      providers: [
        provideRouter([]),
        { provide: ApiService, useValue: fakeApi },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(AppComponent);
  });

  it('calls refreshStatus() on init', () => {
    fixture.detectChanges();
    expect(fakeApi.refreshStatus).toHaveBeenCalledTimes(1);
  });

  // ── rendering ────────────────────────────────────────────────────────────

  it('renders the brand name', () => {
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Hello Operator');
  });

  it('renders the brand icon', () => {
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.brand-icon')).toBeTruthy();
  });

  it('renders three nav links', () => {
    fixture.detectChanges();
    const links = fixture.nativeElement.querySelectorAll('.nav-link');
    expect(links.length).toBe(3);
  });

  it('nav links point to /, /docs, /config', () => {
    fixture.detectChanges();
    const links: NodeListOf<HTMLAnchorElement> = fixture.nativeElement.querySelectorAll('.nav-link');
    const hrefs = Array.from(links).map(a => a.getAttribute('href'));
    expect(hrefs).toContain('/');
    expect(hrefs).toContain('/docs');
    expect(hrefs).toContain('/config');
  });

  // ── status dot ───────────────────────────────────────────────────────────

  it('status dot gets "status-unknown" class by default', () => {
    fixture.detectChanges();
    const dot = fixture.nativeElement.querySelector('.status-dot');
    expect(dot.className).toContain('status-unknown');
  });

  it('status dot reflects active status', () => {
    statusSubject.next('active');
    fixture.detectChanges();
    const dot = fixture.nativeElement.querySelector('.status-dot');
    expect(dot.className).toContain('status-active');
  });

  it('status dot reflects inactive status', () => {
    statusSubject.next('inactive');
    fixture.detectChanges();
    const dot = fixture.nativeElement.querySelector('.status-dot');
    expect(dot.className).toContain('status-inactive');
  });

  it('status dot updates when status changes', () => {
    fixture.detectChanges();
    statusSubject.next('failed');
    fixture.detectChanges();
    const dot = fixture.nativeElement.querySelector('.status-dot');
    expect(dot.className).toContain('status-failed');
  });

  it('displays the current status text', () => {
    statusSubject.next('active');
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.nav-status').textContent).toContain('active');
  });
});
