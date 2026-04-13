import { Component, OnInit } from '@angular/core';
import { RouterOutlet, RouterLink, RouterLinkActive } from '@angular/router';
import { AsyncPipe, NgClass } from '@angular/common';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { ApiService } from './api.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, AsyncPipe, NgClass, MatToolbarModule, MatButtonModule, MatIconModule],
  templateUrl: './app.component.html',
})
export class AppComponent implements OnInit {
  darkMode = false;

  constructor(public api: ApiService) {}

  ngOnInit(): void {
    this.api.refreshStatus();
    this.darkMode = localStorage.getItem('darkMode') === 'true';
    this.applyTheme();
  }

  toggleDarkMode(): void {
    this.darkMode = !this.darkMode;
    localStorage.setItem('darkMode', String(this.darkMode));
    this.applyTheme();
  }

  private applyTheme(): void {
    document.body.style.colorScheme = this.darkMode ? 'dark' : 'light';
  }
}
