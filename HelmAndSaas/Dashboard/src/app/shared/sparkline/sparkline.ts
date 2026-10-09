import { Component, Input, computed, signal } from '@angular/core';

/**
 * A small time-series for a card. The x position is the real time inside the window (so a gap in the data shows as a gap),
 * the y axis fits the data but never spans less than `minSpan`, so a 0.1-point wobble is not blown up into a big wave while
 * real movement fills the height. Hover shows the value and time.
 */
@Component({
  selector: 'app-sparkline',
  template: `
    <div class="relative h-10 w-full select-none" (mousemove)="move($event)" (mouseleave)="hover.set(null)"
      role="img" [attr.aria-label]="summary()">
      @if (pts().length > 1) {
        <svg viewBox="0 0 100 30" preserveAspectRatio="none" class="h-full w-full overflow-visible" aria-hidden="true">
          <line x1="0" y1="29" x2="100" y2="29" stroke="currentColor" stroke-opacity="0.15" stroke-width="1" vector-effect="non-scaling-stroke" />
          @for (l of lines(); track $index) {
            <polyline [attr.points]="l" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" vector-effect="non-scaling-stroke" />
          }
        </svg>
        @let m = marker();
        @if (m) {
          <span class="pointer-events-none absolute h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-current ring-2 ring-white dark:ring-slate-800"
            [style.left.%]="m.x" [style.top.%]="m.y"></span>
          @if (hover() !== null) {
            <span class="pointer-events-none absolute top-full z-10 mt-1 -translate-x-1/2 whitespace-nowrap rounded bg-slate-900 px-1.5 py-0.5 text-[11px] text-white shadow dark:bg-slate-100 dark:text-slate-900"
              [style.left.%]="clampLeft(m.x)">{{ m.label }}</span>
          }
        }
      } @else {
        <p class="pt-2 text-[11px] text-slate-400 dark:text-slate-500">Not enough history yet</p>
      }
    </div>
  `,
})
export class Sparkline {
  private readonly vals = signal<number[]>([]);
  private readonly ts = signal<number[]>([]);
  readonly hover = signal<number | null>(null);

  @Input() set values(v: number[] | null | undefined) { this.vals.set((v ?? []).map(Number)); }
  /** ISO time of each value (same length); without it points are spread evenly */
  @Input() set times(v: string[] | null | undefined) { this.ts.set((v ?? []).map((t) => Date.parse(t))); }
  /** length of the window in minutes; the right edge is "now" */
  @Input() windowMinutes = 15;
  @Input() unit = '';
  @Input() decimals = 1;
  /** the y axis always covers at least this many units (centred on the data) */
  @Input() minSpan = 2;

  /** points as {x: 0..100, y: 0..30 (svg), v, t} */
  readonly pts = computed(() => {
    const v = this.vals();
    const t = this.ts();
    const ok = v.map((y, i) => ({ y, t: t[i] })).filter((p) => Number.isFinite(p.y));
    if (ok.length < 2) return [];
    let lo = Math.min(...ok.map((p) => p.y));
    let hi = Math.max(...ok.map((p) => p.y));
    if (hi - lo < this.minSpan) {
      const mid = (hi + lo) / 2;
      lo = Math.max(0, mid - this.minSpan / 2);
      hi = lo + this.minSpan;
    }
    const useTime = ok.every((p) => Number.isFinite(p.t));
    const end = useTime ? Math.max(Date.now(), ok[ok.length - 1].t) : 0;
    const start = end - this.windowMinutes * 60_000;
    return ok.map((p, i) => ({
      x: useTime ? Math.min(100, Math.max(0, ((p.t - start) / (end - start)) * 100)) : (i / (ok.length - 1)) * 100,
      y: 28 - ((p.y - lo) / (hi - lo)) * 26,
      v: p.y,
      t: p.t,
    }));
  });

  /** one polyline per run: a gap of more than 2 minutes (agent offline) is left open, not joined */
  readonly lines = computed(() => {
    const out: string[][] = [];
    let prev: number | null = null;
    for (const p of this.pts()) {
      if (prev === null || (Number.isFinite(p.t) && p.t - prev > 120_000)) out.push([]);
      out[out.length - 1].push(`${p.x.toFixed(1)},${p.y.toFixed(1)}`);
      prev = p.t;
    }
    return out.filter((r) => r.length > 1).map((r) => r.join(' '));
  });

  readonly marker = computed(() => {
    const p = this.pts();
    if (!p.length) return null;
    const i = this.hover() ?? p.length - 1;
    const q = p[Math.min(i, p.length - 1)];
    const time = Number.isFinite(q.t) ? new Date(q.t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' · ' : '';
    return { x: q.x, y: (q.y / 30) * 100, label: `${time}${q.v.toFixed(this.decimals)}${this.unit}` };
  });

  readonly summary = computed(() => {
    const p = this.pts();
    if (!p.length) return 'No history yet';
    const vs = p.map((q) => q.v);
    return `Last ${this.windowMinutes} minutes: lowest ${Math.min(...vs).toFixed(this.decimals)}${this.unit}, highest ${Math.max(...vs).toFixed(this.decimals)}${this.unit}`;
  });

  clampLeft(x: number): number {
    return Math.min(85, Math.max(15, x));
  }

  move(e: MouseEvent): void {
    const p = this.pts();
    if (!p.length) return;
    const box = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const x = ((e.clientX - box.left) / box.width) * 100;
    let best = 0;
    for (let i = 1; i < p.length; i++) if (Math.abs(p[i].x - x) < Math.abs(p[best].x - x)) best = i;
    this.hover.set(best);
  }
}
