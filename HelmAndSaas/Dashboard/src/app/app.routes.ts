import { Routes } from '@angular/router';
import { authGuard } from './core/auth.guard';
import { Shell } from './layout/shell/shell';
import { Login } from './pages/login/login';
import { Register } from './pages/register/register';
import { DashboardOverview } from './pages/dashboard-overview/dashboard-overview';
import { AnomalyFeed } from './pages/anomaly-feed/anomaly-feed';
import { RemediationLog } from './pages/remediation-log/remediation-log';
import { Metrics } from './pages/metrics/metrics';
import { Settings } from './pages/settings/settings';
import { SetupGuide } from './pages/setup-guide/setup-guide';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
  { path: 'login', component: Login },
  { path: 'register', component: Register },
  {
    path: 'dashboard',
    component: Shell,
    canActivate: [authGuard],
    children: [
      { path: '', component: DashboardOverview },
      { path: 'anomalies', component: AnomalyFeed },
      { path: 'remediations', component: RemediationLog },
      { path: 'metrics', component: Metrics },
      { path: 'setup', component: SetupGuide },
      { path: 'settings', component: Settings },
    ],
  },
  { path: '**', redirectTo: 'dashboard' },
];
