import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { API_BASE_URL } from './api-config';
import { ApiKey, ApiKeyCreated } from './models';

@Injectable({ providedIn: 'root' })
export class ApiKeyService {
  constructor(private readonly http: HttpClient) {}

  async list(): Promise<ApiKey[]> {
    const res = await firstValueFrom(this.http.get<{ api_keys: ApiKey[] }>(`${API_BASE_URL}/api-keys`));
    return res.api_keys;
  }

  async create(name: string): Promise<ApiKeyCreated> {
    return firstValueFrom(this.http.post<ApiKeyCreated>(`${API_BASE_URL}/api-keys`, { name }));
  }

  async revoke(id: string): Promise<void> {
    await firstValueFrom(this.http.delete<void>(`${API_BASE_URL}/api-keys/${id}`));
  }
}
