import { Injectable, computed, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { API_BASE_URL } from './api-config';
import { LoginResponse, Tenant } from './models';

const ACCESS_TOKEN_KEY = 'sadmc_access_token';
const REFRESH_TOKEN_KEY = 'sadmc_refresh_token';
const TENANT_KEY = 'sadmc_tenant';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly accessTokenSignal = signal<string | null>(localStorage.getItem(ACCESS_TOKEN_KEY));
  private readonly refreshTokenSignal = signal<string | null>(localStorage.getItem(REFRESH_TOKEN_KEY));
  private readonly tenantSignal = signal<Tenant | null>(readStoredTenant());

  readonly accessToken = this.accessTokenSignal.asReadonly();
  readonly tenant = this.tenantSignal.asReadonly();
  readonly isAuthenticated = computed(() => this.accessTokenSignal() !== null);

  constructor(
    private readonly http: HttpClient,
    private readonly router: Router,
  ) {}

  async register(organizationName: string, email: string, password: string): Promise<void> {
    await firstValueFrom(
      this.http.post<{ tenant: Tenant }>(`${API_BASE_URL}/auth/register`, {
        organization_name: organizationName,
        email,
        password,
      }),
    );
  }

  async login(email: string, password: string): Promise<void> {
    const response = await firstValueFrom(
      this.http.post<LoginResponse>(`${API_BASE_URL}/auth/login`, { email, password }),
    );
    this.setSession(response);
  }

  async refreshAccessToken(): Promise<string> {
    const refreshToken = this.refreshTokenSignal();
    if (!refreshToken) throw new Error('No refresh token available');

    const response = await firstValueFrom(
      this.http.post<{ access_token: string }>(`${API_BASE_URL}/auth/refresh`, {
        refresh_token: refreshToken,
      }),
    );
    this.accessTokenSignal.set(response.access_token);
    localStorage.setItem(ACCESS_TOKEN_KEY, response.access_token);
    return response.access_token;
  }

  async logout(): Promise<void> {
    const refreshToken = this.refreshTokenSignal();
    this.clearSession();
    if (refreshToken) {
      try {
        await firstValueFrom(
          this.http.post(`${API_BASE_URL}/auth/logout`, { refresh_token: refreshToken }),
        );
      } catch {
        // best-effort; session is already cleared client-side
      }
    }
    this.router.navigateByUrl('/login');
  }

  clearSession(): void {
    this.accessTokenSignal.set(null);
    this.refreshTokenSignal.set(null);
    this.tenantSignal.set(null);
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.removeItem(TENANT_KEY);
  }

  private setSession(response: LoginResponse): void {
    this.accessTokenSignal.set(response.access_token);
    this.refreshTokenSignal.set(response.refresh_token);
    this.tenantSignal.set(response.tenant);
    localStorage.setItem(ACCESS_TOKEN_KEY, response.access_token);
    localStorage.setItem(REFRESH_TOKEN_KEY, response.refresh_token);
    localStorage.setItem(TENANT_KEY, JSON.stringify(response.tenant));
  }
}

function readStoredTenant(): Tenant | null {
  const raw = localStorage.getItem(TENANT_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Tenant;
  } catch {
    return null;
  }
}
