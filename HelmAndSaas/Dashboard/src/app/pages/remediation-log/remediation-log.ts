import { Component, computed, effect, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ClusterService } from '../../core/cluster.service';
import { EventsService } from '../../core/events.service';
import { RemediationAction } from '../../core/models';

const ACTION_BADGE_CLASS: Partial<Record<string, string>> = {
  THROTTLE_CPU: 'bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300',
  RESTART_POD: 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300',
  SCALE_UP: 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300',
  NO_ACTION: 'bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300',
};

const PAGE_SIZE_OPTIONS = [10, 25, 50];

@Component({
  selector: 'app-remediation-log',
  imports: [DatePipe],
  templateUrl: './remediation-log.html',
})
export class RemediationLog {
  readonly remediations = signal<RemediationAction[]>([]);
  readonly loading = signal(false);
  readonly actionBadgeClass = ACTION_BADGE_CLASS;

  readonly page = signal(1);
  readonly pageSize = signal(PAGE_SIZE_OPTIONS[0]);
  readonly total = signal(0);
  readonly pageSizeOptions = PAGE_SIZE_OPTIONS;

  readonly totalPages = computed(() => Math.max(1, Math.ceil(this.total() / this.pageSize())));
  readonly rangeStart = computed(() => (this.total() === 0 ? 0 : (this.page() - 1) * this.pageSize() + 1));
  readonly rangeEnd = computed(() => Math.min(this.page() * this.pageSize(), this.total()));

  private lastClusterId: string | null = null;

  constructor(
    private readonly clusters: ClusterService,
    private readonly events: EventsService,
  ) {
    effect(() => {
      const clusterId = this.clusters.selectedClusterId();
      if (!clusterId) return;

      // Reset to page 1 whenever the selected cluster changes, rather than
      // carrying over a page offset that may not exist for the new cluster.
      if (clusterId !== this.lastClusterId) {
        this.lastClusterId = clusterId;
        if (this.page() !== 1) {
          this.page.set(1);
          return; // the page() write above re-triggers this effect
        }
      }

      const pageSize = this.pageSize();
      const page = this.page();
      void this.load(clusterId, pageSize, (page - 1) * pageSize);
    });

    effect(() => {
      const frame = this.events.lastFrame();
      const clusterUuid = this.clusters.selectedCluster()?.cluster_uuid;
      if (frame?.type !== 'REMEDIATION_EXECUTED' || frame.cluster_uuid !== clusterUuid) return;

      this.total.update((t) => t + 1);
      // Only splice a live event into the visible page when looking at page
      // 1 (newest-first) — other pages stay stable rather than shifting
      // underneath the user.
      if (this.page() === 1) {
        this.remediations.update((current) => {
          const next = [
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
          ];
          return next.length > this.pageSize() ? next.slice(0, this.pageSize()) : next;
        });
      }
    });
  }

  nextPage(): void {
    if (this.page() < this.totalPages()) this.page.update((p) => p + 1);
  }

  prevPage(): void {
    if (this.page() > 1) this.page.update((p) => p - 1);
  }

  onPageSizeChange(event: Event): void {
    this.pageSize.set(Number((event.target as HTMLSelectElement).value));
    this.page.set(1);
  }

  private async load(clusterId: string, limit: number, offset: number): Promise<void> {
    this.loading.set(true);
    try {
      const { remediations, total } = await this.clusters.listRemediations(clusterId, limit, offset);
      this.remediations.set(remediations);
      this.total.set(total);
    } finally {
      this.loading.set(false);
    }
  }
}
