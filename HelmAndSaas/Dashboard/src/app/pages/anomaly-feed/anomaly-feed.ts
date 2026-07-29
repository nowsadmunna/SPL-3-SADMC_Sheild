import { Component, effect, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ClusterService } from '../../core/cluster.service';
import { EventsService } from '../../core/events.service';
import { AnomalyEvent } from '../../core/models';
import { AnomalyBadge } from '../../shared/anomaly-badge/anomaly-badge';

@Component({
  selector: 'app-anomaly-feed',
  imports: [DatePipe, AnomalyBadge],
  templateUrl: './anomaly-feed.html',
})
export class AnomalyFeed {
  readonly anomalies = signal<AnomalyEvent[]>([]);
  readonly loading = signal(false);

  constructor(
    private readonly clusters: ClusterService,
    private readonly events: EventsService,
  ) {
    effect(() => {
      const clusterId = this.clusters.selectedClusterId();
      if (clusterId) void this.load(clusterId);
    });

    effect(() => {
      const frame = this.events.lastFrame();
      const clusterUuid = this.clusters.selectedCluster()?.cluster_uuid;
      if (frame?.type === 'ANOMALY_DETECTED' && frame.cluster_uuid === clusterUuid) {
        this.anomalies.update((current) => [
          {
            id: `live-${Date.now()}`,
            service_name: frame.service_name,
            namespace: frame.namespace,
            anomaly_type: frame.anomaly_type,
            confidence: frame.confidence,
            timestamp: frame.timestamp,
          },
          ...current,
        ]);
      }
    });
  }

  private async load(clusterId: string): Promise<void> {
    this.loading.set(true);
    try {
      this.anomalies.set(await this.clusters.listAnomalies(clusterId, 100));
    } finally {
      this.loading.set(false);
    }
  }
}
