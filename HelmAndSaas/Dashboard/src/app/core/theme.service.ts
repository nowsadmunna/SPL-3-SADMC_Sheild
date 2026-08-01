import { Injectable, signal } from '@angular/core';

const STORAGE_KEY = 'sadmc_theme'; // 'light' | 'dark'

@Injectable({ providedIn: 'root' })
export class ThemeService {
  readonly isDark = signal(this.resolveInitial());

  constructor() {
    this.apply(this.isDark());
  }

  toggle(): void {
    this.set(!this.isDark());
  }

  set(dark: boolean): void {
    this.isDark.set(dark);
    localStorage.setItem(STORAGE_KEY, dark ? 'dark' : 'light');
    this.apply(dark);
  }

  private apply(dark: boolean): void {
    document.documentElement.classList.toggle('dark', dark);
  }

  private resolveInitial(): boolean {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'dark') return true;
    if (saved === 'light') return false;
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
  }
}
