import { Component, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { ChartConfiguration, Plugin, TooltipItem } from 'chart.js';
import { BaseChartDirective } from 'ng2-charts';
import { ClusterService } from '../../core/cluster.service';
import { ThemeService } from '../../core/theme.service';
import { ANOMALY_INFO } from '../../core/anomaly-info';
import { AnomalyType, Incident, MetricPoint, ServiceSummary } from '../../core/models';
import { agoDate } from '../../core/anomaly-info';

// Small-multiples: one single-series chart per metric, so no two different-scale measures ever share an axis.
// Detected incidents are shaded behind the line (colour = type), so a spike can be tied to what the detector said.
const LINE_COLOR = { light: '#2a78d6', dark: '#3987e5' };
const GRID_COLOR = { light: '#e1e0d9', dark: '#2c2c2a' };
const AXIS_COLOR = '#898781';
/** same hues as the badges, semi-transparent so the line stays readable */
const BAND_COLOR: Record<AnomalyType, string> = {
  NORMAL: 'rgba(16,185,129,0.15)',
  CPU_HOG: 'rgba(249,115,22,0.22)',
  MEMORY_LEAK: 'rgba(244,63,94,0.20)',
  NETWORK_DELAY: 'rgba(14,165,233,0.22)',
};

interface MetricPanel {
  key: keyof Pick<MetricPoint, 'cpu_usage_percent' | 'memory_usage_mb' | 'network_latency_ms' | 'request_rate' | 'error_rate'>;
  title: string;
  hint: string;
}

const PANELS: MetricPanel[] = [
  { key: 'cpu_usage_percent', title: 'CPU usage (% of one core)', hint: 'How much processor the service uses. 100 = one full core.' },
  { key: 'memory_usage_mb', title: 'Memory (MB)', hint: 'Memory held by the service (RAM plus cache).' },
  { key: 'network_latency_ms', title: 'Response time (ms)', hint: 'How long a test request to the service takes.' },
  { key: 'request_rate', title: 'Requests per second', hint: 'How many requests the service answers.' },
  { key: 'error_rate', title: 'Server errors per second', hint: 'Responses with a 5xx status code.' },
];

const RANGES = [
  { label: '15 min', minutes: 15 },
  { label: '1 hour', minutes: 60 },
  { label: '6 hours', minutes: 360 },
  { label: '24 hours', minutes: 1440 },
];

/** paints a translucent column for every incident behind the datasets */
const incidentBands: Plugin<'line'> = {
  id: 'incidentBands',
  beforeDatasetsDraw(chart, _args, opts: unknown) {
    const bands = (opts as { bands?: { from: number; to: number; color: string }[] })?.bands ?? [];
    const x = chart.scales['x'];
    if (!x || !bands.length) return;
    const { ctx, chartArea } = chart;
    ctx.save();
    for (const b of bands) {
      const x1 = Math.max(chartArea.left, x.getPixelForValue(b.from));
      const x2 = Math.min(chartArea.right, x.getPixelForValue(Math.max(b.to, b.from + 20_000)));
      if (x2 > chartArea.left && x1 < chartArea.right) {
        ctx.fillStyle = b.color;
        ctx.fillRect(x1, chartArea.top, Math.max(3, x2 - x1), chartArea.bottom - chartArea.top);
      }
    }
    ctx.restore();
  },
};

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
  readonly ranges = RANGES;
  readonly rangeMinutes = signal(15);
  /** refresh every 10 s so a fault injected during the demo shows up without a reload */
  readonly live = signal(true);
  /** right edge of the time axis: the moment of the last load, so an ongoing incident reaches the edge */
  private readonly windowEnd = signal(Date.now());
  private readonly clock = signal(Date.now());
  readonly lastUpdated = signal<number | null>(null);
  readonly plugins = [incidentBands];
  readonly info = ANOMALY_INFO;

  private readonly rawPoints = signal<MetricPoint[]>([]);
  readonly incidents = signal<Incident[]>([]);
  /** which incident types appear in the chart, for the legend */
  readonly legend = computed(() => [...new Set(this.incidents().map((i) => i.anomaly_type))]);
  readonly bandColor = BAND_COLOR;

  private readonly bands = computed(() =>
    this.incidents().map((i) => ({
      from: Date.parse(i.started_at),
      to: Date.parse(i.last_seen_at),
      color: BAND_COLOR[i.anomaly_type],
      label: ANOMALY_INFO[i.anomaly_type].label,
    })),
  );

  /** what the detector says about this service right now: a problem whose last detection is under 90 s old */
  readonly current = computed(() => {
    const now = this.clock();
    const active = this.incidents().find((i) => now - Date.parse(i.last_seen_at) < 90_000);
    return active ? { type: active.anomaly_type, label: ANOMALY_INFO[active.anomaly_type].label, hint: ANOMALY_INFO[active.anomaly_type].hint } : null;
  });
  readonly freshness = computed(() => {
    const at = this.lastUpdated();
    const pts = this.rawPoints();
    if (!at || !pts.length) return null;
    return agoDate(pts[pts.length - 1].time, this.clock());
  });
  readonly latest = computed(() => this.rawPoints().at(-1) ?? null);

  readonly chartData = computed(() => {
    const points = this.rawPoints();
    const color = this.theme.isDark() ? LINE_COLOR.dark : LINE_COLOR.light;
    const data: Record<string, ChartConfiguration<'line'>['data']> = {};
    for (const panel of this.panels) {
      data[panel.key] = {
        datasets: [
          {
            data: points.map((p) => ({ x: Date.parse(p.time), y: p[panel.key] ?? 0 })),
            borderColor: color,
            backgroundColor: color,
            tension: 0.25,
            fill: false,
          },
        ],
      } as unknown as ChartConfiguration<'line'>['data'];
    }
    return data;
  });

  readonly chartOptions = computed<ChartConfiguration<'line'>['options']>(() => {
    const gridColor = this.theme.isDark() ? GRID_COLOR.dark : GRID_COLOR.light;
    const hhmm = (v: number | string) => new Date(Number(v)).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items: TooltipItem<'line'>[]) => (items.length ? new Date(Number(items[0].parsed.x)).toLocaleTimeString() : ''),
            afterBody: (items: TooltipItem<'line'>[]) => {
              const x = items.length ? Number(items[0].parsed.x) : 0;
              const b = this.bands().find((band) => x >= band.from - 5_000 && x <= Math.max(band.to, band.from + 20_000) + 5_000);
              return b ? `Detector: ${b.label}` : '';
            },
          },
        },
        incidentBands: { bands: this.bands() },
      } as unknown as NonNullable<ChartConfiguration<'line'>['options']>['plugins'],
      elements: { point: { radius: 0 }, line: { borderWidth: 2 } },
      scales: {
        x: {
          type: 'linear',
          grid: { color: gridColor },
          min: this.windowEnd() - this.rangeMinutes() * 60_000,
          max: this.windowEnd(),
          ticks: { color: AXIS_COLOR, maxRotation: 0, maxTicksLimit: 6, callback: (v) => hhmm(v) },
        },
        y: { beginAtZero: true, grid: { color: gridColor }, ticks: { color: AXIS_COLOR, maxTicksLimit: 5 } },
      },
    };
  });

  constructor(
    private readonly clusters: ClusterService,
    private readonly theme: ThemeService,
    route: ActivatedRoute,
  ) {
    // arriving from an Overview card: /dashboard/metrics?service=payment
    const fromLink = route.snapshot.queryParamMap.get('service');
    if (fromLink) this.selectedService.set(fromLink);

    effect(() => {
      const clusterId = this.clusters.selectedClusterId();
      if (clusterId) void this.loadServices(clusterId);
    });

    effect(() => {
      const clusterId = this.clusters.selectedClusterId();
      const serviceName = this.selectedService();
      const minutes = this.rangeMinutes();
      if (clusterId && serviceName) void this.loadMetrics(clusterId, serviceName, minutes);
    });

    const timer = setInterval(() => {
      this.clock.set(Date.now());
      const clusterId = this.clusters.selectedClusterId();
      const serviceName = this.selectedService();
      if (this.live() && clusterId && serviceName && !this.loading()) void this.loadMetrics(clusterId, serviceName, this.rangeMinutes());
    }, 10_000);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  toggleLive(): void {
    this.live.update((v) => !v);
  }

  onServiceChange(event: Event): void {
    this.selectedService.set((event.target as HTMLSelectElement).value);
  }

  setRange(minutes: number): void {
    this.rangeMinutes.set(minutes);
  }

  private async loadServices(clusterId: string): Promise<void> {
    const services = await this.clusters.listServices(clusterId);
    this.services.set(services);
    const current = this.selectedService();
    if ((!current || !services.some((s) => s.service_name === current)) && services.length > 0) {
      this.selectedService.set(services[0].service_name);
    }
  }

  private async loadMetrics(clusterId: string, serviceName: string, minutes: number): Promise<void> {
    this.loading.set(true);
    try {
      const start = new Date(Date.now() - minutes * 60_000).toISOString();
      const [points, inc] = await Promise.all([
        this.clusters.queryMetrics(clusterId, serviceName, start),
        this.clusters.listIncidents(clusterId, { limit: 100, service: serviceName }),
      ]);
      this.windowEnd.set(Date.now());
      this.lastUpdated.set(Date.now());
      this.rawPoints.set(points);
      this.incidents.set(inc.incidents.filter((i) => Date.parse(i.last_seen_at) >= Date.parse(start)));
    } finally {
      this.loading.set(false);
    }
  }
}
