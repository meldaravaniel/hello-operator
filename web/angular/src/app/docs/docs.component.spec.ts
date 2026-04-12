import { TestBed, ComponentFixture, fakeAsync, tick } from '@angular/core/testing';
import { BehaviorSubject, of, throwError } from 'rxjs';
import { ActivatedRoute, Router, provideRouter, convertToParamMap, ParamMap } from '@angular/router';

import { DocsComponent } from './docs.component';
import { ApiService } from '../api.service';

const PAGES = [
  { title: 'Overview', slug: 'README' },
  { title: 'Piper Setup', slug: 'docs_PIPER_SETUP' },
];
const SAMPLE_DOC = { title: 'Overview', slug: 'README', content: '# Hello\n\nWorld.' };

async function buildTestBed(
  snapshotSlug: string | null,
  paramMapSubject: BehaviorSubject<ParamMap>,
  fakeApi: object,
) {
  await TestBed.configureTestingModule({
    imports: [DocsComponent],
    providers: [
      provideRouter([]),
      { provide: ApiService, useValue: fakeApi },
      {
        provide: ActivatedRoute,
        useValue: {
          snapshot: { paramMap: convertToParamMap(snapshotSlug ? { slug: snapshotSlug } : {}) },
          paramMap: paramMapSubject.asObservable(),
        },
      },
    ],
  }).compileComponents();
}

describe('DocsComponent', () => {
  // ── no slug in route (default) ────────────────────────────────────────────

  describe('when no slug is in the route snapshot', () => {
    let fixture: ComponentFixture<DocsComponent>;
    let component: DocsComponent;
    let paramMapSubject: BehaviorSubject<ParamMap>;
    let navigateSpy: jest.SpyInstance;
    let fakeApi: { getDocs: jest.Mock; getDoc: jest.Mock };

    beforeEach(async () => {
      paramMapSubject = new BehaviorSubject<ParamMap>(convertToParamMap({}));
      fakeApi = {
        getDocs: jest.fn().mockReturnValue(of({ pages: PAGES })),
        getDoc: jest.fn().mockReturnValue(of(SAMPLE_DOC)),
      };

      await buildTestBed(null, paramMapSubject, fakeApi);

      navigateSpy = jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      fixture = TestBed.createComponent(DocsComponent);
      component = fixture.componentInstance;
      fixture.detectChanges();
    });

    it('calls getDocs() on init', () => {
      expect(fakeApi.getDocs).toHaveBeenCalledTimes(1);
    });

    it('populates pages from the getDocs response', () => {
      expect(component.pages).toEqual(PAGES);
    });

    it('navigates to the first page slug', () => {
      expect(navigateSpy).toHaveBeenCalledWith(['/docs', 'README'], { replaceUrl: true });
    });

    it('does not navigate when pages list is empty', async () => {
      // Override getDocs to return empty pages and re-create
      fakeApi.getDocs.mockReturnValue(of({ pages: [] }));
      fixture = TestBed.createComponent(DocsComponent);
      component = fixture.componentInstance;
      navigateSpy.mockClear();
      fixture.detectChanges();
      expect(navigateSpy).not.toHaveBeenCalled();
    });

    // ── paramMap subscription ───────────────────────────────────────────────

    it('calls loadPage() when a slug appears in paramMap', () => {
      const spy = jest.spyOn(component, 'loadPage');
      paramMapSubject.next(convertToParamMap({ slug: 'docs_PIPER_SETUP' }));
      expect(spy).toHaveBeenCalledWith('docs_PIPER_SETUP');
    });

    it('does not call loadPage() for paramMap emissions without a slug', () => {
      const spy = jest.spyOn(component, 'loadPage');
      paramMapSubject.next(convertToParamMap({}));
      expect(spy).not.toHaveBeenCalled();
    });
  });

  // ── slug already in route ─────────────────────────────────────────────────

  describe('when a slug is already in the route snapshot', () => {
    let fixture: ComponentFixture<DocsComponent>;
    let navigateSpy: jest.SpyInstance;
    let fakeApi: { getDocs: jest.Mock; getDoc: jest.Mock };

    beforeEach(async () => {
      const paramMapSubject = new BehaviorSubject<ParamMap>(convertToParamMap({ slug: 'README' }));
      fakeApi = {
        getDocs: jest.fn().mockReturnValue(of({ pages: PAGES })),
        getDoc: jest.fn().mockReturnValue(of(SAMPLE_DOC)),
      };

      await buildTestBed('README', paramMapSubject, fakeApi);

      navigateSpy = jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      fixture = TestBed.createComponent(DocsComponent);
      fixture.detectChanges();
    });

    it('does not navigate away since the page is already identified', () => {
      expect(navigateSpy).not.toHaveBeenCalled();
    });
  });

  // ── loadPage() ────────────────────────────────────────────────────────────

  describe('loadPage(slug)', () => {
    let fixture: ComponentFixture<DocsComponent>;
    let component: DocsComponent;
    let paramMapSubject: BehaviorSubject<ParamMap>;
    let fakeApi: { getDocs: jest.Mock; getDoc: jest.Mock };

    beforeEach(async () => {
      paramMapSubject = new BehaviorSubject<ParamMap>(convertToParamMap({}));
      fakeApi = {
        getDocs: jest.fn().mockReturnValue(of({ pages: [] })),
        getDoc: jest.fn().mockReturnValue(of(SAMPLE_DOC)),
      };

      await buildTestBed(null, paramMapSubject, fakeApi);
      jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);

      fixture = TestBed.createComponent(DocsComponent);
      component = fixture.componentInstance;
      fixture.detectChanges(); // runs ngOnInit (no redirect since pages is empty)
    });

    it('sets currentSlug', () => {
      component.loadPage('README');
      expect(component.currentSlug).toBe('README');
    });

    it('sets currentTitle from the response', () => {
      component.loadPage('README');
      expect(component.currentTitle).toBe('Overview');
    });

    it('sets renderedHtml (truthy SafeHtml) on success', () => {
      component.loadPage('README');
      expect(component.renderedHtml).toBeTruthy();
    });

    it('sets loading = false after success', () => {
      component.loadPage('README');
      expect(component.loading).toBe(false);
    });

    it('clears any previous error on a successful load', () => {
      component.error = 'previous error';
      component.loadPage('README');
      expect(component.error).toBe('');
    });

    it('calls getDoc with the provided slug', () => {
      component.loadPage('docs_PIPER_SETUP');
      expect(fakeApi.getDoc).toHaveBeenCalledWith('docs_PIPER_SETUP');
    });

    it('sets error when getDoc fails', () => {
      fakeApi.getDoc.mockReturnValue(throwError(() => new Error('404')));
      component.loadPage('missing');
      expect(component.error).toBe('Page not found.');
    });

    it('sets loading = false after an error', () => {
      fakeApi.getDoc.mockReturnValue(throwError(() => new Error('404')));
      component.loadPage('missing');
      expect(component.loading).toBe(false);
    });

    it('stamps heading ids asynchronously via setTimeout', fakeAsync(() => {
      const container = document.createElement('div');
      container.id = 'doc-render';
      const h1 = document.createElement('h1');
      h1.textContent = 'Hello World';
      container.appendChild(h1);
      document.body.appendChild(container);

      component.loadPage('README');
      tick(0); // flush the setTimeout(0)

      expect(h1.id).toBe('hello-world');
      document.body.removeChild(container);
    }));
  });
});
