import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { from } from 'rxjs';
import { switchMap } from 'rxjs/operators';

import { AutenticacionService } from '../services/auth.service';

/**
 * Adjunta `Authorization: Bearer <token>` con el token de sesión de Clerk.
 *
 * Es un interceptor funcional (`HttpInterceptorFn`), registrado en
 * `app.config.ts` con `provideHttpClient(withInterceptors([...]))`.
 *
 * `session.getToken()` es asíncrono, así que la cadena espera al token antes de
 * continuar. Sin sesión, la petición pasa intacta: no hay token local ni
 * fallback.
 */
export const tokenInterceptor: HttpInterceptorFn = (peticion, siguiente) => {
  const autenticacion = inject(AutenticacionService);

  return from(autenticacion.obtenerToken()).pipe(
    switchMap((token) =>
      token
        ? siguiente(
            peticion.clone({
              setHeaders: { Authorization: `Bearer ${token}` },
            }),
          )
        : siguiente(peticion),
    ),
  );
};
