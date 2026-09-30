import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';

import { AutenticacionService } from '../services/auth.service';

/**
 * Adjunta `Authorization: Bearer <token>` a las peticiones de la API.
 *
 * Es un interceptor funcional (`HttpInterceptorFn`), no una clase: se registra
 * en `app.config.ts` con `provideHttpClient(withInterceptors([...]))` y no
 * necesita providers de clase ni `@Injectable({providedIn, useClass})`.
 *
 * Si no hay token devuelve la peticion intacta: hoy la autenticacion es
 * decorativa y las rutas siguen abiertas, asi que sumar el header solo cuando
 * existe evita mandar `Bearer null` al backend.
 */
export const tokenInterceptor: HttpInterceptorFn = (peticion, siguiente) => {
  const token = inject(AutenticacionService).token();

  if (!token) {
    return siguiente(peticion);
  }

  return siguiente(
    peticion.clone({
      setHeaders: { Authorization: `Bearer ${token}` },
    }),
  );
};