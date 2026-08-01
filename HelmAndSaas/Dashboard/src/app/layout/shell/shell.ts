import { Component, OnDestroy, OnInit, effect } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { ClusterService } from '../../core/cluster.service';
import { EventsService } from '../../core/events.service';
import { ToastService } from '../../core/toast.service';
import { ThemeToggle } from '../../shared/theme-toggle/theme-toggle';
import { ToastContainer } from '../../shared/toast/toast-container';

@Component({
  selector: 'app-shell',
  imports: [RouterLink, RouterLinkActive, RouterOutlet, ThemeToggle, ToastContainer],
  templateUrl: './shell.html',
})
export class Shell implements OnInit, OnDestroy {
  constructor(
    protected readonly auth: AuthService,
    protected readonly clusters: ClusterService,
    private readonly events: EventsService,
    private readonly toast: ToastService,
  ) {
    // Lives at the Shell level (mounted for every /dashboard/* child route),
    // so a toast fires no matter which page is currently open — unlike the
    // Anomaly Feed / Remediation Log pages, which only update their own list
    // while they happen to be the active route.
    effect(() => {
      const frame = this.events.lastFrame();
      const clusterUuid = this.clusters.selectedCluster()?.cluster_uuid;
      if (!frame || frame.cluster_uuid !== clusterUuid) return;

      if (frame.type === 'ANOMALY_DETECTED') {
        this.toast.show(
          'anomaly',
          `${frame.anomaly_type} detected`,
          `${frame.service_name} (${frame.namespace}) — ${(frame.confidence * 100).toFixed(0)}% confidence`,
        );
      } else if (frame.type === 'REMEDIATION_EXECUTED') {
        const success = frame.status === 'success';
        this.toast.show(
          success ? 'remediation-success' : 'remediation-failed',
          `${frame.action} ${success ? 'succeeded' : 'failed'}`,
          `${frame.service_name} (${frame.namespace})`,
        );
      }
    });
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
    this.clusters.selectCluster(id);
  }

  logout(): void {
    void this.auth.logout();
  }
}
