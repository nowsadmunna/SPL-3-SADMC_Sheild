import { Component, computed, effect, signal } from '@angular/core';
import { ChartConfiguration } from 'chart.js';
import { BaseChartDirective } from 'ng2-charts';
import { ClusterService } from '../../core/cluster.service';
import { ThemeService } from '../../core/theme.service';
import { MetricPoint, ServiceSummary } from '../../core/models';

// Small-multiples: one single-series chart per metric, so no two
// different-scale measures ever share an axis (see dataviz skill —
// "one axis" rule). Every panel uses the same line color since each is
// independently titled and there's no cross-panel legend to disambiguate.
// Light/dark pairs are the same categorical-slot-1 / gridline steps used
// elsewhere in the palette (palette.md); axis/label ink is mode-invariant.
const LINE_COLOR = { light: '#2a78d6', dark: '#3987e5' };
const GRID_COLOR = { light: '#e1e0d9', dark: '#2c2c2a' };
const AXIS_COLOR = '#898781';

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

  private readonly rawPoints = signal<MetricPoint[]>([]);

  readonly chartData = computed(() => {
    const points = this.rawPoints();
    const dark = this.theme.isDark();
    const labels = points.map((p) => new Date(p.time).toLocaleTimeString());
    const color = dark ? LINE_COLOR.dark : LINE_COLOR.light;

    const data: Record<string, ChartConfiguration<'line'>['data']> = {};
    for (const panel of this.panels) {
      data[panel.key] = {
        labels,
        datasets: [
          {
            data: points.map((p) => p[panel.key] ?? 0),
            borderColor: color,
            backgroundColor: color,
            tension: 0.25,
            fill: false,
          },
        ],
      };
    }
    return data;
  });

  readonly chartOptions = computed<ChartConfiguration<'line'>['options']>(() => {
    const gridColor = this.theme.isDark() ? GRID_COLOR.dark : GRID_COLOR.light;
    return {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      elements: { point: { radius: 0 }, line: { borderWidth: 2 } },
      scales: {
        x: { grid: { color: gridColor }, ticks: { color: AXIS_COLOR, maxRotation: 0 } },
        y: { grid: { color: gridColor }, ticks: { color: AXIS_COLOR } },
      },
    };
  });

  constructor(
    private readonly clusters: ClusterService,
    private readonly theme: ThemeService,
  ) {
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
      this.rawPoints.set(await this.clusters.queryMetrics(clusterId, serviceName));
    } finally {
      this.loading.set(false);
    }
  }
}
