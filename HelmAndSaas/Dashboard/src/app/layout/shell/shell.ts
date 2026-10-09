import { Component, DestroyRef, OnDestroy, OnInit, computed, effect, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { ANOMALY_INFO, actionText, agoSeconds } from '../../core/anomaly-info';
import { AuthService } from '../../core/auth.service';
import { ClusterService } from '../../core/cluster.service';
import { EventsService } from '../../core/events.service';
import { ToastService } from '../../core/toast.service';
import { ThemeToggle } from '../../shared/theme-toggle/theme-toggle';
import { ToastContainer } from '../../shared/toast/toast-container';

const REFRESH_MS = 10_000;
/** a detection starts a new incident (and a new toast) when its service+type was quiet for this long */
const INCIDENT_GAP_MS = 60_000;

@Component({
  selector: 'app-shell',
  imports: [RouterLink, RouterLinkActive, RouterOutlet, ThemeToggle, ToastContainer],
  templateUrl: './shell.html',
})
export class Shell implements OnInit, OnDestroy {
  readonly renaming = signal(false);
  readonly renameValue = signal('');
  readonly renameError = signal<string | null>(null);
  readonly now = signal(Date.now());

  /** how fresh the selected cluster's data is: the answer to "is the agent alive?" */
  readonly freshness = computed(() => {
    const c = this.clusters.selectedCluster();
    if (!c) return null;
    const age = this.clusters.dataAge(c, this.now());
    if (age === null) return { color: 'bg-slate-400', text: 'No data yet', tone: 'text-slate-500 dark:text-slate-400' };
    if (age < 45) return { color: 'bg-emerald-500', text: `Agent connected · data ${agoSeconds(age)}`, tone: 'text-emerald-700 dark:text-emerald-400' };
    if (age < 180) return { color: 'bg-amber-500', text: `Data delayed · last ${agoSeconds(age)}`, tone: 'text-amber-700 dark:text-amber-400' };
    return { color: 'bg-rose-500', text: `Agent offline · last data ${agoSeconds(age)}`, tone: 'text-rose-700 dark:text-rose-400' };
  });

  private readonly lastToast = new Map<string, number>();

  constructor(
    protected readonly auth: AuthService,
    protected readonly clusters: ClusterService,
    private readonly events: EventsService,
    private readonly toast: ToastService,
  ) {
    const tick = setInterval(() => this.now.set(Date.now()), 5_000);
    const refresh = setInterval(() => void this.clusters.loadClusters().catch(() => undefined), REFRESH_MS);
    inject(DestroyRef).onDestroy(() => {
      clearInterval(tick);
      clearInterval(refresh);
    });

    // Lives at the Shell level (mounted for every /dashboard/* child route), so a toast fires no matter which page is open.
    // One toast per INCIDENT: a problem is detected again every 15 s, but the user only needs to be told once.
    effect(() => {
      const frame = this.events.lastFrame();
      const clusterUuid = this.clusters.selectedCluster()?.cluster_uuid;
      if (!frame || frame.cluster_uuid !== clusterUuid) return;

      if (frame.type === 'ANOMALY_DETECTED') {
        const key = `${frame.service_name}|${frame.anomaly_type}`;
        const at = Date.parse(frame.timestamp) || Date.now();
        const previous = this.lastToast.get(key);
        this.lastToast.set(key, at);
        if (previous !== undefined && at - previous < INCIDENT_GAP_MS) return;
        const info = ANOMALY_INFO[frame.anomaly_type];
        this.toast.show('anomaly', `${info.label}: ${frame.service_name}`, info.what);
      } else if (frame.type === 'REMEDIATION_EXECUTED') {
        const success = frame.status === 'success';
        this.toast.show(
          success ? 'remediation-success' : 'remediation-failed',
          `${frame.action} ${success ? 'done' : 'failed'}: ${frame.service_name}`,
          actionText(frame.action, null),
        );
      }
    });
  }

  startRename(): void {
    const c = this.clusters.selectedCluster();
    if (!c) return;
    this.renameValue.set(c.name ?? '');
    this.renameError.set(null);
    this.renaming.set(true);
  }

  cancelRename(): void {
    this.renaming.set(false);
    this.renameError.set(null);
  }

  async saveRename(): Promise<void> {
    const current = this.clusters.selectedCluster();
    const name = this.renameValue().trim();
    if (!current) return;
    if (!name || name === current.name) return this.cancelRename();
    try {
      await this.clusters.renameCluster(current.id, name);
      this.cancelRename();
    } catch (e) {
      this.renameError.set((e as Error).message);
    }
  }

  async ngOnInit(): Promise<void> {
    await this.clusters.loadClusters();
    this.events.connect();
  }

  ngOnDestroy(): void {
    this.events.disconnect();
  }

  onClusterChange(event: Event): void {
    const id = (event.target as HTMLSelectElement).value;
    this.cancelRename();
    this.clusters.selectCluster(id);
  }

  logout(): void {
    void this.auth.logout();
  }
}
