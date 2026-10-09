import { Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { API_BASE_URL } from '../../core/api-config';
import { ApiKeyService } from '../../core/api-key.service';
import { ApiKey } from '../../core/models';
import { ClusterService } from '../../core/cluster.service';
import { agoSeconds } from '../../core/anomaly-info';

type CadvisorMode = 'deploy' | 'external';

const list = (text: string): string[] => text.split(',').map((x) => x.trim()).filter(Boolean);

@Component({
  selector: 'app-setup-guide',
  imports: [FormsModule, RouterLink],
  templateUrl: './setup-guide.html',
})
export class SetupGuide implements OnInit {
  readonly apiKeys = signal<ApiKey[]>([]);
  readonly newKeyName = signal('cluster-1');
  readonly generatedKey = signal<string | null>(null);
  readonly generating = signal(false);

  /** where the agent posts its metrics: an address the CLUSTER can reach (not the dashboard's own localhost) */
  readonly saasEndpoint = signal(API_BASE_URL);
  /** shown in the dashboard instead of the id; empty = the name of the API key */
  readonly clusterName = signal('');
  /** comma separated deployment names to score (empty = every deployment outside kube-system / sadmc) */
  readonly includeServices = signal('');
  readonly namespaces = signal('');
  readonly excludeServices = signal('');
  readonly cadvisorMode = signal<CadvisorMode>('deploy');
  readonly cadvisorUrls = signal('http://cadvisor.monitoring:8080/metrics');
  readonly remediation = signal(false);

  /** the chosen name already belongs to another cluster of this account (the agent would be refused) */
  readonly nameTaken = computed(() => this.clusterService.nameTaken(this.clusterName()));

  /** the clusters (by id) that existed when this page opened: a new one, or one that starts reporting, means the agent came up */
  private readonly clustersAtOpen = signal<Map<string, number | null> | null>(null);
  readonly copied = signal(false);
  readonly agoSeconds = agoSeconds;

  /** a cluster that was not here when the page opened, or whose agent was silent then and is reporting now */
  readonly connected = computed(() => {
    const before = this.clustersAtOpen();
    if (!before) return null;
    for (const c of this.clusterService.clusters()) {
      const age = this.clusterService.dataAge(c);
      const fresh = age !== null && age < 90;
      if (!before.has(c.id) && fresh) return c;
      const wasAge = before.get(c.id);
      if (before.has(c.id) && fresh && (wasAge === null || (wasAge ?? 0) > 180)) return c;
    }
    return null;
  });

  readonly hasActiveKey = computed(() => this.apiKeys().some((k) => k.is_active));
  readonly endpointIsLocal = computed(() => /\/\/(localhost|127\.|0\.0\.0\.0)/.test(this.saasEndpoint()));

  readonly helmInstallCommand = computed(() => {
    const apiKey = this.generatedKey() ?? '<PASTE_YOUR_API_KEY_HERE>';
    const include = list(this.includeServices());
    const namespaces = list(this.namespaces());
    const exclude = list(this.excludeServices());
    const options: string[] = [
      `--namespace sadmc`,
      `--create-namespace`,
      `--set sadmc.apiKey="${apiKey}"`,
      `--set sadmc.saasEndpoint="${this.saasEndpoint()}"`,
    ];
    if (this.clusterName().trim()) options.push(`--set sadmc.clusterName="${this.clusterName().trim()}"`);
    if (namespaces.length) options.push(`--set 'discovery.namespaces={${namespaces.join(',')}}'`);
    if (include.length) options.push(`--set 'discovery.includeServices={${include.join(',')}}'`);
    if (exclude.length) options.push(`--set 'discovery.excludeServices={${exclude.join(',')}}'`);
    if (this.cadvisorMode() === 'external') {
      options.push(`--set cadvisor.enabled=false`, `--set 'cadvisor.externalUrls={${list(this.cadvisorUrls()).join(',')}}'`);
    }
    if (this.remediation()) {
      options.push(`--set remediation.enabled=true`);
      if (include.length) options.push(`--set 'remediation.services={${include.join(',')}}'`);
    }
    return [`helm install sadmc-agent ./HelmAndSaas/Helm/charts/sadmc-agent`, ...options].join(' \\\n  ');
  });

  constructor(
    private readonly apiKeyService: ApiKeyService,
    private readonly clusterService: ClusterService,
  ) {}

  async ngOnInit(): Promise<void> {
    this.apiKeys.set(await this.apiKeyService.list());
    await this.clusterService.loadClusters();
    this.clustersAtOpen.set(new Map(this.clusterService.clusters().map((c) => [c.id, this.clusterService.dataAge(c)])));
    // watch for the agent to appear while the user runs the command
    const timer = setInterval(() => void this.clusterService.loadClusters().catch(() => undefined), 5_000);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
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

  readonly needsKey = computed(() => this.generatedKey() === null);
  readonly emptyEndpoint = computed(() => this.saasEndpoint().trim() === '');

  async copyCommand(): Promise<void> {
    await navigator.clipboard.writeText(this.helmInstallCommand());
    this.copied.set(true);
    setTimeout(() => this.copied.set(false), 2500);
  }
}
