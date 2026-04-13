import { Component, OnInit } from '@angular/core';
import { NgFor, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { ApiService, ConfigField, RadioStation } from '../api.service';

/** Sections visible only when a specific backend is selected. */
const BACKEND_SECTIONS: Record<string, string> = {
  'Plex': 'plex',
  'MPD': 'mpd',
};

@Component({
  selector: 'app-config',
  standalone: true,
  imports: [NgFor, NgIf, FormsModule, MatCardModule, MatFormFieldModule, MatInputModule, MatSelectModule, MatButtonModule, MatIconModule, MatProgressSpinnerModule],
  templateUrl: './config.component.html',
})
export class ConfigComponent implements OnInit {
  fields: ConfigField[] = [];
  values: Record<string, string> = {};
  stations: RadioStation[] = [];
  sections: string[] = [];

  saving = false;
  saveMessage = '';
  saveSuccess = false;
  saveErrors: string[] = [];

  radioSaving = false;
  radioMessage = '';
  radioSuccess = false;
  radioErrors: string[] = [];

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.api.getConfig().subscribe({
      next: data => {
        this.fields = data.fields;
        this.values = { ...data.values };
        this.stations = data.stations.map(s => ({ ...s }));
        // Deduplicate while preserving DOC_PAGES order
        const seen = new Set<string>();
        this.sections = data.fields
          .map(f => f.section)
          .filter(s => { if (seen.has(s)) return false; seen.add(s); return true; });
      },
    });
  }

  fieldsForSection(section: string): ConfigField[] {
    return this.fields.filter(f => f.section === section);
  }

  get mediaBackend(): string {
    return this.values['MEDIA_BACKEND'] || 'plex';
  }

  isSectionVisible(section: string): boolean {
    const requiredBackend = BACKEND_SECTIONS[section];
    if (!requiredBackend) return true;
    return this.mediaBackend === requiredBackend;
  }

  saveEnv(): void {
    this.saving = true;
    this.saveMessage = '';
    this.saveErrors = [];

    this.api.saveConfigEnv(this.values).subscribe({
      next: data => {
        this.saving = false;
        this.saveSuccess = true;
        this.saveMessage = data.message ?? 'Saved.';
      },
      error: err => {
        this.saving = false;
        this.saveSuccess = false;
        this.saveErrors = err.error?.errors ?? ['Request failed.'];
      },
    });
  }

  addStation(): void {
    this.stations = [...this.stations, { name: '', frequency_mhz: 0, phone_number: '' }];
  }

  removeStation(i: number): void {
    this.stations = this.stations.filter((_, idx) => idx !== i);
  }

  saveRadio(): void {
    this.radioSaving = true;
    this.radioMessage = '';
    this.radioErrors = [];

    this.api.saveRadio(this.stations).subscribe({
      next: data => {
        this.radioSaving = false;
        this.radioSuccess = true;
        this.radioMessage = data.message ?? 'Saved.';
      },
      error: err => {
        this.radioSaving = false;
        this.radioSuccess = false;
        this.radioErrors = err.error?.errors ?? ['Request failed.'];
      },
    });
  }
}
