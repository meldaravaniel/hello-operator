import { Component, OnInit } from '@angular/core';
import { NgClass, NgIf } from '@angular/common';
import { ApiService } from '../api.service';

@Component({
  selector: 'app-status',
  standalone: true,
  imports: [NgClass, NgIf],
  templateUrl: './status.component.html',
})
export class StatusComponent implements OnInit {
  status = 'unknown';
  restarting = false;
  message = '';
  messageType = '';

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    this.api.status$.subscribe(s => (this.status = s));
    this.api.refreshStatus();
  }

  get badgeClass(): string {
    const map: Record<string, string> = {
      active: 'badge-active',
      inactive: 'badge-inactive',
      failed: 'badge-failed',
    };
    return map[this.status] ?? 'badge-unknown';
  }

  get statusLabel(): string {
    const map: Record<string, string> = {
      active: 'Running',
      inactive: 'Stopped',
      failed: 'Failed',
    };
    return map[this.status] ?? (this.status || 'Unknown');
  }

  restart(): void {
    this.restarting = true;
    this.message = '';
    this.api.restart().subscribe({
      next: data => {
        this.restarting = false;
        if (data.ok) {
          this.message = 'Service restarted successfully.';
          this.messageType = 'success';
        } else {
          this.message = `Restart failed: ${data.error}`;
          this.messageType = 'error';
        }
      },
      error: () => {
        this.restarting = false;
        this.message = 'Request failed.';
        this.messageType = 'error';
      },
    });
  }
}
