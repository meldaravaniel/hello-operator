import { TestBed, ComponentFixture } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import { ConfigComponent } from './config.component';
import { ApiService, RadioStation } from '../api.service';

describe('ConfigComponent', () => {
  let fixture: ComponentFixture<ConfigComponent>;
  let component: ConfigComponent;
  let fakeApi: { getConfig: jest.Mock; saveConfigEnv: jest.Mock; saveRadio: jest.Mock };

  const CONFIG_PAYLOAD = {
    fields: [
      { section: 'Plex', key: 'PLEX_URL', label: 'Plex URL', type: 'url', required: false, help: '' },
      { section: 'Plex', key: 'PLEX_TOKEN', label: 'Plex Token', type: 'password', required: true, help: '' },
      { section: 'GPIO', key: 'HOOK_SWITCH_PIN', label: 'Hook Switch Pin', type: 'number', required: false, help: '' },
    ],
    values: { PLEX_URL: 'http://localhost:32400', HOOK_SWITCH_PIN: '17' },
    stations: [
      { name: 'KEXP', frequency_mhz: 90.3, phone_number: '5550903' },
      { name: 'KBCS', frequency_mhz: 91.3, phone_number: '5550913' },
    ],
  };

  beforeEach(async () => {
    fakeApi = {
      getConfig: jest.fn().mockReturnValue(of(CONFIG_PAYLOAD)),
      saveConfigEnv: jest.fn().mockReturnValue(of({ ok: true, message: 'Settings saved.' })),
      saveRadio: jest.fn().mockReturnValue(of({ ok: true, message: 'Radio saved.' })),
    };

    await TestBed.configureTestingModule({
      imports: [ConfigComponent],
      providers: [{ provide: ApiService, useValue: fakeApi }],
    }).compileComponents();

    fixture = TestBed.createComponent(ConfigComponent);
    component = fixture.componentInstance;
    fixture.detectChanges(); // triggers ngOnInit → load()
  });

  // ── init / load() ─────────────────────────────────────────────────────────

  it('calls getConfig() on init', () => {
    expect(fakeApi.getConfig).toHaveBeenCalledTimes(1);
  });

  it('populates fields from the response', () => {
    expect(component.fields).toHaveLength(3);
    expect(component.fields[0].key).toBe('PLEX_URL');
  });

  it('populates values from the response', () => {
    expect(component.values['PLEX_URL']).toBe('http://localhost:32400');
  });

  it('populates stations from the response', () => {
    expect(component.stations).toHaveLength(2);
    expect(component.stations[0].name).toBe('KEXP');
  });

  it('deduplicates sections while preserving order', () => {
    expect(component.sections).toEqual(['Plex', 'GPIO']);
  });

  it('makes a deep copy of values so mutations do not affect the original', () => {
    component.values['PLEX_URL'] = 'http://changed:32400';
    expect(CONFIG_PAYLOAD.values['PLEX_URL']).toBe('http://localhost:32400');
  });

  it('makes a deep copy of stations so mutations do not affect the original', () => {
    component.stations[0].name = 'changed';
    expect(CONFIG_PAYLOAD.stations[0].name).toBe('KEXP');
  });

  // ── fieldsForSection() ────────────────────────────────────────────────────

  describe('fieldsForSection(section)', () => {
    it('returns only fields belonging to the given section', () => {
      const plexFields = component.fieldsForSection('Plex');
      expect(plexFields).toHaveLength(2);
      expect(plexFields.every(f => f.section === 'Plex')).toBe(true);
    });

    it('returns an empty array for an unknown section', () => {
      expect(component.fieldsForSection('Unknown')).toHaveLength(0);
    });
  });

  // ── mediaBackend getter ────────────────────────────────────────────────────

  describe('mediaBackend', () => {
    it('returns the value of MEDIA_BACKEND when set', () => {
      component.values['MEDIA_BACKEND'] = 'mpd';
      expect(component.mediaBackend).toBe('mpd');
    });

    it("defaults to 'plex' when MEDIA_BACKEND is not set", () => {
      delete component.values['MEDIA_BACKEND'];
      expect(component.mediaBackend).toBe('plex');
    });
  });

  // ── isSectionVisible() ────────────────────────────────────────────────────

  describe('isSectionVisible(section)', () => {
    it('returns true for sections not tied to a specific backend', () => {
      expect(component.isSectionVisible('GPIO')).toBe(true);
      expect(component.isSectionVisible('TTS')).toBe(true);
      expect(component.isSectionVisible('Phone System')).toBe(true);
    });

    it("shows Plex section when backend is 'plex'", () => {
      component.values['MEDIA_BACKEND'] = 'plex';
      expect(component.isSectionVisible('Plex')).toBe(true);
    });

    it("hides Plex section when backend is 'mpd'", () => {
      component.values['MEDIA_BACKEND'] = 'mpd';
      expect(component.isSectionVisible('Plex')).toBe(false);
    });

    it("shows MPD section when backend is 'mpd'", () => {
      component.values['MEDIA_BACKEND'] = 'mpd';
      expect(component.isSectionVisible('MPD')).toBe(true);
    });

    it("hides MPD section when backend is 'plex'", () => {
      component.values['MEDIA_BACKEND'] = 'plex';
      expect(component.isSectionVisible('MPD')).toBe(false);
    });

    it("defaults to showing Plex when MEDIA_BACKEND is unset", () => {
      delete component.values['MEDIA_BACKEND'];
      expect(component.isSectionVisible('Plex')).toBe(true);
      expect(component.isSectionVisible('MPD')).toBe(false);
    });
  });

  // ── addStation() ──────────────────────────────────────────────────────────

  describe('addStation()', () => {
    it('appends a new empty station row', () => {
      const before = component.stations.length;
      component.addStation();
      expect(component.stations.length).toBe(before + 1);
    });

    it('new station has empty name and phone_number', () => {
      component.addStation();
      const last = component.stations[component.stations.length - 1];
      expect(last.name).toBe('');
      expect(last.phone_number).toBe('');
    });

    it('new station has frequency_mhz of 0', () => {
      component.addStation();
      const last = component.stations[component.stations.length - 1];
      expect(last.frequency_mhz).toBe(0);
    });
  });

  // ── removeStation() ───────────────────────────────────────────────────────

  describe('removeStation(i)', () => {
    it('removes the station at the given index', () => {
      component.removeStation(0);
      expect(component.stations).toHaveLength(1);
      expect(component.stations[0].name).toBe('KBCS');
    });

    it('removes the last station', () => {
      component.removeStation(1);
      expect(component.stations).toHaveLength(1);
      expect(component.stations[0].name).toBe('KEXP');
    });

    it('results in empty array when the only station is removed', () => {
      component.stations = [{ name: 'KEXP', frequency_mhz: 90.3, phone_number: '5550903' }];
      component.removeStation(0);
      expect(component.stations).toHaveLength(0);
    });
  });

  // ── saveEnv() ─────────────────────────────────────────────────────────────

  describe('saveEnv()', () => {
    it('calls saveConfigEnv with the current values', () => {
      component.saveEnv();
      expect(fakeApi.saveConfigEnv).toHaveBeenCalledWith(component.values);
    });

    it('sets saveMessage and saveSuccess = true on success', () => {
      component.saveEnv();
      expect(component.saveSuccess).toBe(true);
      expect(component.saveMessage).toBe('Settings saved.');
    });

    it('uses "Saved." as fallback message when API returns no message', () => {
      fakeApi.saveConfigEnv.mockReturnValue(of({ ok: true }));
      component.saveEnv();
      expect(component.saveMessage).toBe('Saved.');
    });

    it('sets saving = false after success', () => {
      component.saveEnv();
      expect(component.saving).toBe(false);
    });

    it('sets saveErrors and saveSuccess = false on HTTP error', () => {
      fakeApi.saveConfigEnv.mockReturnValue(
        throwError(() => ({ error: { errors: ['PLEX_URL is required'] } }))
      );
      component.saveEnv();
      expect(component.saveSuccess).toBe(false);
      expect(component.saveErrors).toEqual(['PLEX_URL is required']);
    });

    it('sets a generic error message when HTTP error has no errors array', () => {
      fakeApi.saveConfigEnv.mockReturnValue(throwError(() => ({ error: {} })));
      component.saveEnv();
      expect(component.saveErrors).toEqual(['Request failed.']);
    });

    it('sets saving = false after an error', () => {
      fakeApi.saveConfigEnv.mockReturnValue(throwError(() => ({ error: {} })));
      component.saveEnv();
      expect(component.saving).toBe(false);
    });
  });

  // ── saveRadio() ───────────────────────────────────────────────────────────

  describe('saveRadio()', () => {
    it('calls api.saveRadio with the current stations', () => {
      component.saveRadio();
      expect(fakeApi.saveRadio).toHaveBeenCalledWith(component.stations);
    });

    it('sets radioMessage and radioSuccess = true on success', () => {
      component.saveRadio();
      expect(component.radioSuccess).toBe(true);
      expect(component.radioMessage).toBe('Radio saved.');
    });

    it('uses "Saved." as fallback when API returns no message', () => {
      fakeApi.saveRadio.mockReturnValue(of({ ok: true }));
      component.saveRadio();
      expect(component.radioMessage).toBe('Saved.');
    });

    it('sets radioSaving = false after success', () => {
      component.saveRadio();
      expect(component.radioSaving).toBe(false);
    });

    it('sets radioErrors and radioSuccess = false on HTTP error', () => {
      fakeApi.saveRadio.mockReturnValue(
        throwError(() => ({ error: { errors: ['Invalid frequency'] } }))
      );
      component.saveRadio();
      expect(component.radioSuccess).toBe(false);
      expect(component.radioErrors).toEqual(['Invalid frequency']);
    });

    it('sets a generic error when HTTP error has no errors array', () => {
      fakeApi.saveRadio.mockReturnValue(throwError(() => ({ error: {} })));
      component.saveRadio();
      expect(component.radioErrors).toEqual(['Request failed.']);
    });

    it('sets radioSaving = false after an error', () => {
      fakeApi.saveRadio.mockReturnValue(throwError(() => ({ error: {} })));
      component.saveRadio();
      expect(component.radioSaving).toBe(false);
    });
  });
});
