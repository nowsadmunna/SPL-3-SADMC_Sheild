import { Component, Input } from '@angular/core';
import { ANOMALY_INFO } from '../../core/anomaly-info';
import { AnomalyType } from '../../core/models';

const STYLES: Record<AnomalyType, string> = {
  NORMAL: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
  CPU_HOG: 'bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300',
  MEMORY_LEAK: 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300',
  NETWORK_DELAY: 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300',
};

/** Same identity mapping as STYLES above, as a left-accent border for cards/rows. */
export const ANOMALY_BORDER_CLASS: Record<AnomalyType, string> = {
  NORMAL: 'border-l-emerald-400 dark:border-l-emerald-500',
  CPU_HOG: 'border-l-orange-400 dark:border-l-orange-500',
  MEMORY_LEAK: 'border-l-rose-400 dark:border-l-rose-500',
  NETWORK_DELAY: 'border-l-sky-400 dark:border-l-sky-500',
};

const NO_DATA_STYLE = 'bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300';

@Component({
  selector: 'app-anomaly-badge',
  template: `
    <span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium" [class]="classes" [title]="tooltip">
      {{ label }}
    </span>
  `,
})
export class AnomalyBadge {
  /** a verdict, or NO_DATA when the agent has not reported recently */
  @Input({ required: true }) type: AnomalyType | 'NO_DATA' = 'NORMAL';
  /** show the raw code instead of the plain-language name (tables that want the exact value) */
  @Input() raw = false;

  get label(): string {
    if (this.type === 'NO_DATA') return 'No data';
    return this.raw ? this.type : ANOMALY_INFO[this.type].label;
  }

  get tooltip(): string {
    if (this.type === 'NO_DATA') return 'No metrics received recently. The agent may be offline.';
    const info = ANOMALY_INFO[this.type];
    return this.type === 'NORMAL' ? info.what : `${this.type}: ${info.what}`;
  }

  get classes(): string {
    return this.type === 'NO_DATA' ? NO_DATA_STYLE : (STYLES[this.type] ?? STYLES['NORMAL']);
  }
}
