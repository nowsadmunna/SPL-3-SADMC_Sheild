import { Component, Input } from '@angular/core';
import { AnomalyType } from '../../core/models';

const STYLES: Record<AnomalyType, string> = {
  NORMAL: 'bg-emerald-100 text-emerald-800',
  CPU_HOG: 'bg-orange-100 text-orange-800',
  MEMORY_LEAK: 'bg-rose-100 text-rose-800',
  NETWORK_DELAY: 'bg-sky-100 text-sky-800',
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
