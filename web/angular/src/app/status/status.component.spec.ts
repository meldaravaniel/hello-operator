import { TestBed, ComponentFixture } from '@angular/core/testing';
import { BehaviorSubject, of, Subject, throwError } from 'rxjs';

import { StatusComponent } from './status.component';
import { ApiService } from '../api.service';

describe('StatusComponent', () => {
  let fixture: ComponentFixture<StatusComponent>;
  let component: StatusComponent;
  let statusSubject: BehaviorSubject<string>;
  let fakeApi: { status$: any; refreshStatus: jest.Mock; restart: jest.Mock };

  beforeEach(async () => {
    statusSubject = new BehaviorSubject<string>('unknown');
    fakeApi = {
      status$: statusSubject.asObservable(),
      refreshStatus: jest.fn(),
      restart: jest.fn().mockReturnValue(of({ ok: true, message: 'Restarted.' })),
    };

    await TestBed.configureTestingModule({
      imports: [StatusComponent],
      providers: [{ provide: ApiService, useValue: fakeApi }],
    }).compileComponents();

    fixture = TestBed.createComponent(StatusComponent);
    component = fixture.componentInstance;
    fixture.detectChanges(); // triggers ngOnInit
  });

  // ── init ─────────────────────────────────────────────────────────────────

  it('calls refreshStatus() on init', () => {
    expect(fakeApi.refreshStatus).toHaveBeenCalledTimes(1);
  });

  it('subscribes to status$ and tracks the current status', () => {
    statusSubject.next('active');
    expect(component.status).toBe('active');
  });

  it('starts with status "unknown"', () => {
    expect(component.status).toBe('unknown');
  });

  // ── badgeClass ───────────────────────────────────────────────────────────

  describe('badgeClass', () => {
    it('returns badge-active for active', () => {
      component.status = 'active';
      expect(component.badgeClass).toBe('badge-active');
    });

    it('returns badge-inactive for inactive', () => {
      component.status = 'inactive';
      expect(component.badgeClass).toBe('badge-inactive');
    });

    it('returns badge-failed for failed', () => {
      component.status = 'failed';
      expect(component.badgeClass).toBe('badge-failed');
    });

    it('returns badge-unknown for unknown status', () => {
      component.status = 'unknown';
      expect(component.badgeClass).toBe('badge-unknown');
    });

    it('returns badge-unknown for unrecognized status', () => {
      component.status = 'foobar';
      expect(component.badgeClass).toBe('badge-unknown');
    });
  });

  // ── statusLabel ──────────────────────────────────────────────────────────

  describe('statusLabel', () => {
    it('returns "Running" for active', () => {
      component.status = 'active';
      expect(component.statusLabel).toBe('Running');
    });

    it('returns "Stopped" for inactive', () => {
      component.status = 'inactive';
      expect(component.statusLabel).toBe('Stopped');
    });

    it('returns "Failed" for failed', () => {
      component.status = 'failed';
      expect(component.statusLabel).toBe('Failed');
    });

    it('echoes the raw status string for unrecognized values', () => {
      component.status = 'unknown';
      expect(component.statusLabel).toBe('unknown');
    });

    it('returns "Unknown" for empty status', () => {
      component.status = '';
      expect(component.statusLabel).toBe('Unknown');
    });

    it('echoes arbitrary unrecognized status strings', () => {
      component.status = 'degraded';
      expect(component.statusLabel).toBe('degraded');
    });
  });

  // ── restart() ────────────────────────────────────────────────────────────

  describe('restart()', () => {
    it('calls api.restart()', () => {
      component.restart();
      expect(fakeApi.restart).toHaveBeenCalledTimes(1);
    });

    it('sets restarting = false and success message on ok response', () => {
      fakeApi.restart.mockReturnValue(of({ ok: true, message: 'Service restarted successfully.' }));
      component.restart();
      expect(component.restarting).toBe(false);
      expect(component.message).toBe('Service restarted successfully.');
      expect(component.messageType).toBe('success');
    });

    it('sets restarting = false and error message when ok is false', () => {
      fakeApi.restart.mockReturnValue(of({ ok: false, error: 'unit not found' }));
      component.restart();
      expect(component.restarting).toBe(false);
      expect(component.message).toContain('unit not found');
      expect(component.messageType).toBe('error');
    });

    it('sets restarting = false and error message on HTTP error', () => {
      fakeApi.restart.mockReturnValue(throwError(() => new Error('Network error')));
      component.restart();
      expect(component.restarting).toBe(false);
      expect(component.message).toBe('Request failed.');
      expect(component.messageType).toBe('error');
    });

    it('clears any previous message before restarting', () => {
      component.message = 'old message';
      const restartSubject = new Subject<any>();
      fakeApi.restart.mockReturnValue(restartSubject.asObservable());
      component.restart();
      expect(component.message).toBe('');
    });

    it('sets restarting = true while the request is in flight', () => {
      const restartSubject = new Subject<any>();
      fakeApi.restart.mockReturnValue(restartSubject.asObservable());
      component.restart();
      expect(component.restarting).toBe(true);
    });
  });
});
