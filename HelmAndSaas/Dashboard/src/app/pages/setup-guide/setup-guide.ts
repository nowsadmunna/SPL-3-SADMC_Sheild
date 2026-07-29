import { Component, OnInit, computed, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { API_BASE_URL } from '../../core/api-config';
import { ApiKeyService } from '../../core/api-key.service';
import { ApiKey } from '../../core/models';

type PrometheusMode = 'auto' | 'existing' | 'install';

@Component({
  selector: 'app-setup-guide',
  imports: [FormsModule],
  templateUrl: './setup-guide.html',
})
export class SetupGuide implements OnInit {
  readonly apiKeys = signal<ApiKey[]>([]);
  readonly newKeyName = signal('cluster-1');
  readonly generatedKey = signal<string | null>(null);
  readonly generating = signal(false);

  readonly prometheusMode = signal<PrometheusMode>('auto');
  readonly existingPrometheusUrl = signal('http://prometheus-server.monitoring:9090');

  readonly hasActiveKey = computed(() => this.apiKeys().some((k) => k.is_active));

  readonly helmInstallCommand = computed(() => {
    const apiKey = this.generatedKey() ?? '<PASTE_YOUR_API_KEY_HERE>';
    const lines = [
      `helm install sadmc-agent ./HelmAndSaas/Helm/charts/sadmc-agent \\`,
      `  --namespace sadmc \\`,
      `  --create-namespace \\`,
      `  --set sadmc.apiKey="${apiKey}" \\`,
      `  --set sadmc.saasEndpoint="${API_BASE_URL}"`,
    ];

    if (this.prometheusMode() === 'existing') {
      lines[lines.length - 1] += ' \\';
      lines.push(`  --set prometheus.mode="existing" \\`);
      lines.push(`  --set prometheus.existingUrl="${this.existingPrometheusUrl()}"`);
    } else if (this.prometheusMode() === 'install') {
      lines[lines.length - 1] += ' \\';
      lines.push(`  --set prometheus.mode="install"`);
    }

    return lines.join('\n');
  });

  constructor(private readonly apiKeyService: ApiKeyService) {}

  async ngOnInit(): Promise<void> {
    this.apiKeys.set(await this.apiKeyService.list());
  }

  async generateKey(): Promise<void> {
    this.generating.set(true);
    try {
      const created = await this.apiKeyService.create(this.newKeyName() || 'unnamed');
      this.generatedKey.set(created.api_key);
      this.apiKeys.set(await this.apiKeyService.list());
    } finally {
      this.generating.set(false);
    }
  }

  async copyCommand(): Promise<void> {
    await navigator.clipboard.writeText(this.helmInstallCommand());
  }
}
