import { Component, effect, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ClusterService } from '../../core/cluster.service';
import { EventsService } from '../../core/events.service';
import { RemediationAction } from '../../core/models';

@Component({
  selector: 'app-remediation-log',
  imports: [DatePipe],
  templateUrl: './remediation-log.html',
})
export class RemediationLog {
  readonly remediations = signal<RemediationAction[]>([]);
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
      if (frame?.type === 'REMEDIATION_EXECUTED' && frame.cluster_uuid === clusterUuid) {
        this.remediations.update((current) => [
          {
            id: `live-${Date.now()}`,
            service_name: frame.service_name,
            namespace: frame.namespace,
            action_type: frame.action,
            status: frame.status as RemediationAction['status'],
            executed_at: frame.timestamp,
            duration_ms: null,
            error_message: null,
          },
          ...current,
        ]);
      }
    });
  }

  private async load(clusterId: string): Promise<void> {
    this.loading.set(true);
    try {
      this.remediations.set(await this.clusters.listRemediations(clusterId, 100));
    } finally {
      this.loading.set(false);
    }
  }
}
