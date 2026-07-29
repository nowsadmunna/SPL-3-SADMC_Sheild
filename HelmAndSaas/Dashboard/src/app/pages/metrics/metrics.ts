import { Component, effect, signal } from '@angular/core';
import { ChartConfiguration } from 'chart.js';
import { BaseChartDirective } from 'ng2-charts';
import { ClusterService } from '../../core/cluster.service';
import { MetricPoint, ServiceSummary } from '../../core/models';

// Small-multiples: one single-series chart per metric, so no two
// different-scale measures ever share an axis (see dataviz skill —
// "one axis" rule). Every panel uses the same line color since each is
// independently titled and there's no cross-panel legend to disambiguate.
const LINE_COLOR = '#2a78d6'; // categorical slot 1 (blue), per palette.md
const GRID_COLOR = '#e1e0d9'; // hairline gridline
const AXIS_COLOR = '#898781'; // muted ink

interface MetricPanel {
  key: keyof Pick<
    MetricPoint,
    'cpu_usage_percent' | 'memory_usage_mb' | 'network_latency_ms' | 'request_rate' | 'error_rate'
  >;
  title: string;
}

const PANELS: MetricPanel[] = [
  { key: 'cpu_usage_percent', title: 'CPU Usage (%)' },
  { key: 'memory_usage_mb', title: 'Memory (MB)' },
  { key: 'network_latency_ms', title: 'Network Latency (ms)' },
  { key: 'request_rate', title: 'Request Rate (req/s)' },
  { key: 'error_rate', title: 'Error Rate' },
];

@Component({
  selector: 'app-metrics',
  imports: [BaseChartDirective],
  templateUrl: './metrics.html',
})
export class Metrics {
  readonly services = signal<ServiceSummary[]>([]);
  readonly selectedService = signal<string | null>(null);
  readonly loading = signal(false);
  readonly panels = PANELS;

  readonly chartData = signal<Record<string, ChartConfiguration<'line'>['data']>>({});
  readonly chartOptions: ChartConfiguration<'line'>['options'] = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    elements: { point: { radius: 0 }, line: { borderWidth: 2 } },
    scales: {
      x: { grid: { color: GRID_COLOR }, ticks: { color: AXIS_COLOR, maxRotation: 0 } },
      y: { grid: { color: GRID_COLOR }, ticks: { color: AXIS_COLOR } },
    },
  };

  constructor(private readonly clusters: ClusterService) {
    effect(() => {
      const clusterId = this.clusters.selectedClusterId();
      if (clusterId) void this.loadServices(clusterId);
    });

    effect(() => {
      const clusterId = this.clusters.selectedClusterId();
      const serviceName = this.selectedService();
      if (clusterId && serviceName) void this.loadMetrics(clusterId, serviceName);
    });
  }

  onServiceChange(event: Event): void {
    this.selectedService.set((event.target as HTMLSelectElement).value);
  }

  private async loadServices(clusterId: string): Promise<void> {
    const services = await this.clusters.listServices(clusterId);
    this.services.set(services);
    if (!this.selectedService() && services.length > 0) {
      this.selectedService.set(services[0].service_name);
    }
  }

  private async loadMetrics(clusterId: string, serviceName: string): Promise<void> {
    this.loading.set(true);
    try {
      const points = await this.clusters.queryMetrics(clusterId, serviceName);
      const labels = points.map((p) => new Date(p.time).toLocaleTimeString());

      const data: Record<string, ChartConfiguration<'line'>['data']> = {};
      for (const panel of this.panels) {
        data[panel.key] = {
          labels,
          datasets: [
            {
              data: points.map((p) => p[panel.key] ?? 0),
              borderColor: LINE_COLOR,
              backgroundColor: LINE_COLOR,
              tension: 0.25,
              fill: false,
            },
          ],
        };
      }
      this.chartData.set(data);
    } finally {
      this.loading.set(false);
    }
  }
}
