import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject, Observable } from 'rxjs';
import { tap } from 'rxjs/operators';

export interface DocPage {
  title: string;
  slug: string;
}

export interface ConfigField {
  section: string;
  key: string;
  label: string;
  type: string;
  required: boolean;
  default?: string;
  help: string;
}

export interface RadioStation {
  name: string;
  frequency_mhz: number;
  phone_number: string;
}

export interface ConfigData {
  fields: ConfigField[];
  values: Record<string, string>;
  stations: RadioStation[];
}

export interface ApiResult {
  ok: boolean;
  message?: string;
  errors?: string[];
  error?: string | null;
  status?: string;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private _status = new BehaviorSubject<string>('unknown');
  readonly status$ = this._status.asObservable();

  constructor(private http: HttpClient) {}

  refreshStatus(): void {
    this.http.get<{ status: string }>('/api/status').subscribe({
      next: d => this._status.next(d.status),
      error: () => this._status.next('unknown'),
    });
  }

  getDocs(): Observable<{ pages: DocPage[] }> {
    return this.http.get<{ pages: DocPage[] }>('/api/docs');
  }

  getDoc(slug: string): Observable<{ title: string; slug: string; content: string }> {
    return this.http.get<{ title: string; slug: string; content: string }>(`/api/docs/${slug}`);
  }

  getConfig(): Observable<ConfigData> {
    return this.http.get<ConfigData>('/api/config');
  }

  saveConfigEnv(values: Record<string, string>): Observable<ApiResult> {
    return this.http.post<ApiResult>('/api/config/env', values);
  }

  saveRadio(stations: RadioStation[]): Observable<ApiResult> {
    return this.http.post<ApiResult>('/api/config/radio', stations);
  }

  restart(): Observable<ApiResult> {
    return this.http.post<ApiResult>('/service/restart', {}).pipe(
      tap(d => { if (d.status) this._status.next(d.status); })
    );
  }
}
