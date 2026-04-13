import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient } from '@angular/common/http';

import { ApiService, AuthStatus, RadioStation } from './api.service';

describe('ApiService', () => {
  let service: ApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(ApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify(); // assert no outstanding requests
  });

  // ── status$ ──────────────────────────────────────────────────────────────

  it('status$ starts as "unknown"', done => {
    service.status$.subscribe(s => {
      expect(s).toBe('unknown');
      done();
    });
  });

  // ── refreshStatus ─────────────────────────────────────────────────────────

  describe('refreshStatus()', () => {
    it('makes GET /api/status', () => {
      service.refreshStatus();
      const req = http.expectOne('/api/status');
      expect(req.request.method).toBe('GET');
      req.flush({ status: 'active' });
    });

    it('updates status$ to the returned value', done => {
      service.refreshStatus();
      http.expectOne('/api/status').flush({ status: 'active' });
      service.status$.subscribe(s => {
        expect(s).toBe('active');
        done();
      });
    });

    it('sets status$ to "unknown" on network error', done => {
      service.refreshStatus();
      http.expectOne('/api/status').error(new ProgressEvent('error'));
      service.status$.subscribe(s => {
        expect(s).toBe('unknown');
        done();
      });
    });
  });

  // ── getDocs ───────────────────────────────────────────────────────────────

  describe('getDocs()', () => {
    it('makes GET /api/docs', () => {
      service.getDocs().subscribe();
      const req = http.expectOne('/api/docs');
      expect(req.request.method).toBe('GET');
      req.flush({ pages: [] });
    });

    it('returns the pages array from the response', done => {
      const pages = [{ title: 'Overview', slug: 'README' }];
      service.getDocs().subscribe(data => {
        expect(data.pages).toEqual(pages);
        done();
      });
      http.expectOne('/api/docs').flush({ pages });
    });
  });

  // ── getDoc ────────────────────────────────────────────────────────────────

  describe('getDoc(slug)', () => {
    it('makes GET /api/docs/{slug}', () => {
      service.getDoc('README').subscribe();
      const req = http.expectOne('/api/docs/README');
      expect(req.request.method).toBe('GET');
      req.flush({ title: 'Overview', slug: 'README', content: '# Hello' });
    });

    it('interpolates the slug correctly', () => {
      service.getDoc('docs_PIPER_SETUP').subscribe();
      http.expectOne('/api/docs/docs_PIPER_SETUP').flush({ title: 'Piper', slug: 'docs_PIPER_SETUP', content: '' });
    });

    it('returns title, slug, and content', done => {
      service.getDoc('README').subscribe(data => {
        expect(data.title).toBe('Overview');
        expect(data.slug).toBe('README');
        expect(data.content).toContain('# Hello');
        done();
      });
      http.expectOne('/api/docs/README').flush({ title: 'Overview', slug: 'README', content: '# Hello' });
    });
  });

  // ── getConfig ─────────────────────────────────────────────────────────────

  describe('getConfig()', () => {
    it('makes GET /api/config', () => {
      service.getConfig().subscribe();
      const req = http.expectOne('/api/config');
      expect(req.request.method).toBe('GET');
      req.flush({ fields: [], values: {}, stations: [] });
    });

    it('returns fields, values, and stations', done => {
      const payload = {
        fields: [{ section: 'Plex', key: 'PLEX_URL', label: 'Plex URL', type: 'url', required: false, help: '' }],
        values: { PLEX_URL: 'http://localhost:32400' },
        stations: [{ name: 'KEXP', frequency_mhz: 90.3, phone_number: '5550903' }],
      };
      service.getConfig().subscribe(data => {
        expect(data.fields.length).toBe(1);
        expect(data.values['PLEX_URL']).toBe('http://localhost:32400');
        expect(data.stations[0].name).toBe('KEXP');
        done();
      });
      http.expectOne('/api/config').flush(payload);
    });
  });

  // ── saveConfigEnv ─────────────────────────────────────────────────────────

  describe('saveConfigEnv(values)', () => {
    it('makes POST /api/config/env', () => {
      service.saveConfigEnv({}).subscribe();
      const req = http.expectOne('/api/config/env');
      expect(req.request.method).toBe('POST');
      req.flush({ ok: true, message: 'Saved.' });
    });

    it('sends the values dict as the request body', () => {
      const values = { PLEX_URL: 'http://192.168.1.50:32400', ASSISTANT_NUMBER: '5550001' };
      service.saveConfigEnv(values).subscribe();
      const req = http.expectOne('/api/config/env');
      expect(req.request.body).toEqual(values);
      req.flush({ ok: true, message: 'Saved.' });
    });

    it('returns the API result', done => {
      service.saveConfigEnv({}).subscribe(result => {
        expect(result.ok).toBe(true);
        expect(result.message).toBe('Settings saved and service restarted.');
        done();
      });
      http.expectOne('/api/config/env').flush({ ok: true, message: 'Settings saved and service restarted.' });
    });
  });

  // ── saveRadio ─────────────────────────────────────────────────────────────

  describe('saveRadio(stations)', () => {
    it('makes POST /api/config/radio', () => {
      service.saveRadio([]).subscribe();
      const req = http.expectOne('/api/config/radio');
      expect(req.request.method).toBe('POST');
      req.flush({ ok: true });
    });

    it('sends the stations array as the request body', () => {
      const stations: RadioStation[] = [{ name: 'KEXP', frequency_mhz: 90.3, phone_number: '5550903' }];
      service.saveRadio(stations).subscribe();
      const req = http.expectOne('/api/config/radio');
      expect(req.request.body).toEqual(stations);
      req.flush({ ok: true });
    });
  });

  // ── checkAuthStatus ───────────────────────────────────────────────────────

  describe('checkAuthStatus()', () => {
    it('makes GET /api/auth/status', () => {
      service.checkAuthStatus().subscribe();
      const req = http.expectOne('/api/auth/status');
      expect(req.request.method).toBe('GET');
      req.flush({ authenticated: true, required: false });
    });

    it('sets authenticated$ to true when auth not required', done => {
      service.checkAuthStatus().subscribe(() => {
        service.authenticated$.subscribe(v => {
          expect(v).toBe(true);
          done();
        });
      });
      http.expectOne('/api/auth/status').flush({ authenticated: false, required: false });
    });

    it('sets authenticated$ to true when already authenticated', done => {
      service.checkAuthStatus().subscribe(() => {
        service.authenticated$.subscribe(v => {
          expect(v).toBe(true);
          done();
        });
      });
      http.expectOne('/api/auth/status').flush({ authenticated: true, required: true });
    });

    it('sets authenticated$ to false when required but not logged in', done => {
      service.checkAuthStatus().subscribe(() => {
        service.authenticated$.subscribe(v => {
          expect(v).toBe(false);
          done();
        });
      });
      http.expectOne('/api/auth/status').flush({ authenticated: false, required: true });
    });
  });

  // ── login ─────────────────────────────────────────────────────────────────

  describe('login(password)', () => {
    it('makes POST /api/auth/login with the password', () => {
      service.login('hunter2').subscribe();
      const req = http.expectOne('/api/auth/login');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({ password: 'hunter2' });
      req.flush({ ok: true });
    });

    it('sets authenticated$ to true on successful login', done => {
      service.login('hunter2').subscribe(() => {
        service.authenticated$.subscribe(v => {
          expect(v).toBe(true);
          done();
        });
      });
      http.expectOne('/api/auth/login').flush({ ok: true });
    });

    it('does not set authenticated$ on failed login', done => {
      (service as any)._authenticated.next(null);
      service.login('wrong').subscribe(() => {
        service.authenticated$.subscribe(v => {
          expect(v).toBeNull();
          done();
        });
      });
      http.expectOne('/api/auth/login').flush({ ok: false, error: 'Incorrect password' });
    });
  });

  // ── logout ────────────────────────────────────────────────────────────────

  describe('logout()', () => {
    it('makes POST /api/auth/logout', () => {
      service.logout().subscribe();
      const req = http.expectOne('/api/auth/logout');
      expect(req.request.method).toBe('POST');
      req.flush({ ok: true });
    });

    it('sets authenticated$ to false after logout', done => {
      (service as any)._authenticated.next(true);
      service.logout().subscribe(() => {
        service.authenticated$.subscribe(v => {
          expect(v).toBe(false);
          done();
        });
      });
      http.expectOne('/api/auth/logout').flush({ ok: true });
    });
  });

  // ── restart ───────────────────────────────────────────────────────────────

  describe('restart()', () => {
    it('makes POST /service/restart', () => {
      service.restart().subscribe();
      const req = http.expectOne('/service/restart');
      expect(req.request.method).toBe('POST');
      req.flush({ ok: true, status: 'active' });
    });

    it('updates status$ to the status returned in the response', done => {
      service.restart().subscribe(() => {
        service.status$.subscribe(s => {
          expect(s).toBe('active');
          done();
        });
      });
      http.expectOne('/service/restart').flush({ ok: true, status: 'active' });
    });

    it('does not update status$ when response has no status field', done => {
      // Pre-set status$ to a known value
      (service as any)._status.next('inactive');

      service.restart().subscribe(() => {
        service.status$.subscribe(s => {
          // Should stay 'inactive' since response has no status
          expect(s).toBe('inactive');
          done();
        });
      });
      http.expectOne('/service/restart').flush({ ok: false, error: 'unit not found' });
    });
  });
});
