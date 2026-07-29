import { Component, OnDestroy, OnInit } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { ClusterService } from '../../core/cluster.service';
import { EventsService } from '../../core/events.service';

@Component({
  selector: 'app-shell',
  imports: [RouterLink, RouterLinkActive, RouterOutlet],
  templateUrl: './shell.html',
})
export class Shell implements OnInit, OnDestroy {
  constructor(
    protected readonly auth: AuthService,
    protected readonly clusters: ClusterService,
    private readonly events: EventsService,
  ) {}

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
