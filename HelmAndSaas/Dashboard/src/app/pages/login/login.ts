import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { ThemeToggle } from '../../shared/theme-toggle/theme-toggle';

@Component({
  selector: 'app-login',
  imports: [FormsModule, RouterLink, ThemeToggle],
  templateUrl: './login.html',
})
export class Login {
  email = '';
  password = '';
  readonly error = signal<string | null>(null);
  readonly submitting = signal(false);

  constructor(
    private readonly auth: AuthService,
    private readonly router: Router,
  ) {}

  async submit(): Promise<void> {
    this.error.set(null);
    this.submitting.set(true);
    try {
      await this.auth.login(this.email, this.password);
      await this.router.navigateByUrl('/dashboard');
    } catch {
      this.error.set('Invalid email or password.');
    } finally {
      this.submitting.set(false);
    }
  }
}
