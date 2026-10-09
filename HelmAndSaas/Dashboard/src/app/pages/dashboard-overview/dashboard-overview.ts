import { Component, computed, DestroyRef, effect, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ANOMALY_INFO, agoSeconds } from '../../core/anomaly-info';
import { ClusterService } from '../../core/cluster.service';
import { EventsService } from '../../core/events.service';
import { AnomalyType, ServiceOverview } from '../../core/models';
import { ANOMALY_BORDER_CLASS, AnomalyBadge } from '../../shared/anomaly-badge/anomaly-badge';
import { Sparkline } from '../../shared/sparkline/sparkline';

type Status = AnomalyType | 'NO_DATA';

interface Card {
  service_name: string;
  namespace: string;
  status: Status;
  data: ServiceOverview | null;
}

/** A verdict counts as "current" only this long. The agent reports every 15 s, so 90 s = 6 missed cycles. */
const ACTIVE_WINDOW_MS = 90_000;
/** No metrics for this long = the service (or the agent) is silent: shown as "No data", never as healthy. */
const STALE_SECONDS = 60;
const TICK_MS = 5_000;
const REFRESH_MS = 10_000;
const ORDER: Record<Status, number> = { CPU_HOG: 0, MEMORY_LEAK: 0, NETWORK_DELAY: 0, NO_DATA: 1, NORMAL: 2 };

@Component({
  selector: 'app-dashboard-overview',
  imports: [AnomalyBadge, Sparkline, RouterLink],
  templateUrl: './dashboard-overview.html',
})
export class DashboardOverview {
  private readonly overview = signal<ServiceOverview[]>([]);
  /** service_name -> its most recent anomaly (type + when). Filled from history, then kept current by the WebSocket. */
  private readonly latest = signal<Map<string, { type: AnomalyType; at: number }>>(new Map());
  private readonly now = signal(Date.now());
  private readonly fetchedAt = signal<number | null>(null);

  readonly loading = signal(false);
  readonly borderClass: Record<Status, string> = { ...ANOMALY_BORDER_CLASS, NO_DATA: 'border-l-slate-300 dark:border-l-slate-500' };
  readonly info = ANOMALY_INFO;
  readonly hasClusters = computed(() => this.clusters.clusters().length > 0);

  /** Problems first, then silent services, then healthy ones. */
  readonly cards = computed<Card[]>(() => {
    const out = this.overview().map((svc): Card => {
      const last = this.latest().get(svc.service_name);
      const silent = svc.age_seconds === null || svc.age_seconds + (this.now() - (this.fetchedAt() ?? this.now())) / 1000 > STALE_SECONDS;
      const active = !!last && this.now() - last.at < ACTIVE_WINDOW_MS;
      const status: Status = silent ? 'NO_DATA' : active ? last!.type : 'NORMAL';
      return { service_name: svc.service_name, namespace: svc.namespace, status, data: svc };
    });
    return out.sort((a, b) => ORDER[a.status] - ORDER[b.status] || a.service_name.localeCompare(b.service_name));
  });

  readonly problems = computed(() => this.cards().filter((c) => c.status !== 'NORMAL' && c.status !== 'NO_DATA'));
  readonly silent = computed(() => this.cards().filter((c) => c.status === 'NO_DATA'));
  /** how long ago the newest metric of any service arrived, shown when everything is silent */
  readonly newestAge = computed(() => {
    const ages = this.overview().map((s) => s.age_seconds).filter((a): a is number => a !== null);
    return ages.length ? Math.min(...ages) + (this.now() - (this.fetchedAt() ?? this.now())) / 1000 : null;
  });
  readonly agoText = agoSeconds;

  constructor(
    private readonly clusters: ClusterService,
    private readonly events: EventsService,
  ) {
    const tick = setInterval(() => this.now.set(Date.now()), TICK_MS);
    const refresh = setInterval(() => {
      const id = this.clusters.selectedClusterId();
      if (id) void this.refresh(id);
    }, REFRESH_MS);
    inject(DestroyRef).onDestroy(() => {
      clearInterval(tick);
      clearInterval(refresh);
    });

    effect(() => {
      const clusterId = this.clusters.selectedClusterId();
      if (clusterId) void this.load(clusterId);
    });

    // live: every ANOMALY_DETECTED frame of the selected cluster updates the card at once
    effect(() => {
      const frame = this.events.lastFrame();
      const clusterUuid = this.clusters.selectedCluster()?.cluster_uuid;
      if (frame?.type === 'ANOMALY_DETECTED' && frame.cluster_uuid === clusterUuid) {
        const at = Date.parse(frame.timestamp);
        this.latest.update((m) => new Map(m).set(frame.service_name, { type: frame.anomaly_type, at: Number.isFinite(at) ? at : Date.now() }));
        this.now.set(Date.now());
      }
    });
  }

  private async refresh(clusterId: string): Promise<void> {
    try {
      this.overview.set(await this.clusters.overview(clusterId));
      this.fetchedAt.set(Date.now());
    } catch {
      /* keep the last picture; the "updated" age keeps growing */
    }
  }

  private async load(clusterId: string): Promise<void> {
    this.loading.set(true);
    try {
      const [overview, anomalies] = await Promise.all([this.clusters.overview(clusterId), this.clusters.listAnomalies(clusterId, 200)]);
      const latest = new Map<string, { type: AnomalyType; at: number }>();
      // anomalies are ordered newest-first by the backend; the first hit per service is its latest
      for (const a of anomalies) {
        if (!latest.has(a.service_name)) latest.set(a.service_name, { type: a.anomaly_type, at: Date.parse(a.timestamp) });
      }
      this.latest.set(latest);
      this.overview.set(overview);
      this.fetchedAt.set(Date.now());
      this.now.set(Date.now());
    } finally {
      this.loading.set(false);
    }
  }

  fmt(v: number | null | undefined, digits = 1): string {
    return v === null || v === undefined || !Number.isFinite(v) ? '—' : v.toFixed(digits);
  }

  latencyText(v: number | null | undefined): string {
    if (v === null || v === undefined || !Number.isFinite(v)) return '—';
    return v >= 100 ? `${Math.round(v)} ms` : `${v.toFixed(1)} ms`;
  }
}
