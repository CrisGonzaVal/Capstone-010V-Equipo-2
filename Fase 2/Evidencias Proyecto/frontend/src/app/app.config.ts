import { provideHttpClient, withFetch, withInterceptors } from '@angular/common/http';
import { ApplicationConfig, provideZoneChangeDetection } from '@angular/core';
import { provideRouter } from '@angular/router';

import { routes } from './app.routes';
import { tokenInterceptor } from './core/interceptors/token.interceptor';

export const appConfig: ApplicationConfig = {
  providers: [
    provideZoneChangeDetection({ eventCoalescing: true }),
    provideRouter(routes),
    // `withInterceptors` (funcional) y no `HTTP_INTERCEPTORS` (clases): no hay
    // providers de clase que registrar.
    provideHttpClient(withFetch(), withInterceptors([tokenInterceptor])),
  ],
};