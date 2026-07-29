import { Component, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiKeyService } from '../../core/api-key.service';
import { ApiKey, ApiKeyCreated } from '../../core/models';

@Component({
  selector: 'app-settings',
  imports: [FormsModule],
  templateUrl: './settings.html',
})
export class Settings implements OnInit {
  readonly apiKeys = signal<ApiKey[]>([]);
  readonly newKeyName = signal('');
  readonly justCreated = signal<ApiKeyCreated | null>(null);
  readonly creating = signal(false);

  constructor(private readonly apiKeyService: ApiKeyService) {}

  async ngOnInit(): Promise<void> {
    await this.refresh();
  }

  async refresh(): Promise<void> {
    this.apiKeys.set(await this.apiKeyService.list());
  }

  async createKey(): Promise<void> {
    this.creating.set(true);
    try {
      const created = await this.apiKeyService.create(this.newKeyName() || 'unnamed');
      this.justCreated.set(created);
      this.newKeyName.set('');
      await this.refresh();
    } finally {
      this.creating.set(false);
    }
  }

  async revoke(id: string): Promise<void> {
    await this.apiKeyService.revoke(id);
    await this.refresh();
  }

  dismissCreated(): void {
    this.justCreated.set(null);
  }

  async copy(text: string): Promise<void> {
    await navigator.clipboard.writeText(text);
  }
}
