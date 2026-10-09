import { Component, DestroyRef, effect, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ClusterService } from '../../core/cluster.service';
import { EventsService } from '../../core/events.service';
import { Incident, AnomalyType, ServiceSummary } from '../../core/models';
import { ANOMALY_INFO, ANOMALY_TYPES, actionText, agoDate, confidenceWord, durationText } from '../../core/anomaly-info';
import { AnomalyBadge } from '../../shared/anomaly-badge/anomaly-badge';

/** a new detection continues an incident when it comes within this gap of the previous one (same service and type) */
const GAP_MS = 60_000;
const PAGE = 25;

@Component({
  selector: 'app-anomaly-feed',
  imports: [DatePipe, AnomalyBadge],
  templateUrl: './anomaly-feed.html',
})
export class AnomalyFeed {
  readonly incidents = signal<Incident[]>([]);
  readonly total = signal(0);
  readonly loading = signal(false);
  readonly services = signal<ServiceSummary[]>([]);
  readonly service = signal<string>('');
  readonly type = signal<string>('');
  readonly expanded = signal<string | null>(null);
  readonly now = signal(Date.now());

  readonly types = ANOMALY_TYPES;
  readonly info = ANOMALY_INFO;
  readonly agoDate = agoDate;
  readonly confidenceWord = confidenceWord;
  readonly durationText = durationText;
  readonly actionText = actionText;

  constructor(
    private readonly clusters: ClusterService,
    private readonly events: EventsService,
  ) {
    const tick = setInterval(() => this.now.set(Date.now()), 5000);
    inject(DestroyRef).onDestroy(() => clearInterval(tick));

    effect(() => {
      const clusterId = this.clusters.selectedClusterId();
      const service = this.service();
      const type = this.type();
      if (clusterId) void this.load(clusterId, service, type);
    });
    effect(() => {
      const clusterId = this.clusters.selectedClusterId();
      if (clusterId) void this.clusters.listServices(clusterId).then((s) => this.services.set(s));
    });

    // live: a detection extends the matching ongoing incident or opens a new one at the top
    effect(() => {
      const frame = this.events.lastFrame();
      const clusterUuid = this.clusters.selectedCluster()?.cluster_uuid;
      if (frame?.type !== 'ANOMALY_DETECTED' || frame.cluster_uuid !== clusterUuid) return;
      if (this.service() && this.service() !== frame.service_name) return;
      if (this.type() && this.type() !== frame.anomaly_type) return;
      const at = Date.parse(frame.timestamp);
      const iso = Number.isFinite(at) ? new Date(at).toISOString() : new Date().toISOString();
      this.incidents.update((list) => {
        const i = list.findIndex((x) => x.service_name === frame.service_name && x.anomaly_type === frame.anomaly_type
          && Date.parse(x.last_seen_at) >= Date.parse(iso) - GAP_MS);
        if (i >= 0) {
          const cur = list[i];
          const next = { ...cur, last_seen_at: iso, detections: cur.detections + 1, ongoing: true, max_confidence: Math.max(cur.max_confidence, frame.confidence) };
          return [next, ...list.filter((_, j) => j !== i)];
        }
        this.total.update((t) => t + 1);
        return [{
          service_name: frame.service_name, namespace: frame.namespace, anomaly_type: frame.anomaly_type as AnomalyType,
          started_at: iso, last_seen_at: iso, detections: 1, max_confidence: frame.confidence, ongoing: true, actions: [],
        }, ...list];
      });
    });
  }

  key(i: Incident): string {
    return `${i.service_name}|${i.anomaly_type}|${i.started_at}`;
  }

  toggle(i: Incident): void {
    this.expanded.update((k) => (k === this.key(i) ? null : this.key(i)));
  }

  /** an incident whose last detection is older than the gap is over, even before the next reload says so */
  isOngoing(i: Incident): boolean {
    return this.now() - Date.parse(i.last_seen_at) < GAP_MS;
  }

  lasted(i: Incident): number {
    return Math.max(0, (Date.parse(i.last_seen_at) - Date.parse(i.started_at)) / 1000);
  }

  setService(e: Event): void {
    this.service.set((e.target as HTMLSelectElement).value);
  }

  setType(e: Event): void {
    this.type.set((e.target as HTMLSelectElement).value);
  }

  async more(): Promise<void> {
    const clusterId = this.clusters.selectedClusterId();
    if (!clusterId) return;
    const res = await this.clusters.listIncidents(clusterId, {
      limit: PAGE, offset: this.incidents().length, service: this.service() || null, type: this.type() || null,
    });
    this.incidents.update((l) => [...l, ...res.incidents]);
    this.total.set(res.total);
  }

  private async load(clusterId: string, service: string, type: string): Promise<void> {
    this.loading.set(true);
    try {
      const res = await this.clusters.listIncidents(clusterId, { limit: PAGE, service: service || null, type: type || null });
      this.incidents.set(res.incidents);
      this.total.set(res.total);
    } finally {
      this.loading.set(false);
    }
  }
}
