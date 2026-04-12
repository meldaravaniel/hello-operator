import { Component, OnInit } from '@angular/core';
import { RouterOutlet, RouterLink, RouterLinkActive } from '@angular/router';
import { AsyncPipe, NgClass } from '@angular/common';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatButtonModule } from '@angular/material/button';
import { ApiService } from './api.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, AsyncPipe, NgClass, MatToolbarModule, MatButtonModule],
  templateUrl: './app.component.html',
})
export class AppComponent implements OnInit {
  constructor(public api: ApiService) {}

  ngOnInit(): void {
    this.api.refreshStatus();
  }
}
