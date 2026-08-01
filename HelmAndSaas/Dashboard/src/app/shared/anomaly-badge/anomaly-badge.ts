import { Component, Input } from '@angular/core';
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

@Component({
  selector: 'app-anomaly-badge',
  template: `
    <span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium" [class]="classes">
      {{ type }}
    </span>
  `,
})
export class AnomalyBadge {
  @Input({ required: true }) type: AnomalyType = 'NORMAL';

  get classes(): string {
    return STYLES[this.type] ?? STYLES['NORMAL'];
  }
}
