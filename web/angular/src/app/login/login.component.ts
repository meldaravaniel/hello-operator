import { Component } from '@angular/core';
import { Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';

import { ApiService } from '../api.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [FormsModule, MatCardModule, MatFormFieldModule, MatInputModule, MatButtonModule],
  templateUrl: './login.component.html',
})
export class LoginComponent {
  password = '';
  error = '';
  loading = false;

  constructor(private api: ApiService, private router: Router) {}

  submit(): void {
    if (!this.password) return;
    this.loading = true;
    this.error = '';
    this.api.login(this.password).subscribe({
      next: result => {
        this.loading = false;
        if (result.ok) {
          this.router.navigate(['/']);
        } else {
          this.error = result.error || 'Login failed.';
        }
      },
      error: () => {
        this.loading = false;
        this.error = 'Incorrect password.';
      },
    });
  }
}
