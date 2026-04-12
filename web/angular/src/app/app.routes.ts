import { Routes } from '@angular/router';
import { StatusComponent } from './status/status.component';
import { DocsComponent } from './docs/docs.component';
import { ConfigComponent } from './config/config.component';

export const routes: Routes = [
  { path: '',        component: StatusComponent },
  { path: 'docs',    component: DocsComponent },
  { path: 'docs/:slug', component: DocsComponent },
  { path: 'config',  component: ConfigComponent },
  { path: '**',      redirectTo: '' },
];
