import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AutenticacionService } from '../services/auth.service';

/**
 * Bloquea la ruta si no hay token.
 *
 * **Inerte por ahora, y a proposito.** No se aplica a ninguna ruta de
 * `app.routes.ts`: la autenticacion sigue siendo decorativa (AGENTS.md §3) y no
 * existe pantalla de login, asi que aplicarlo dejaria la app entera
 * inaccesible en vez de protegida. Feature 006 agrega el login, aplica este
 * guard a las rutas privadas y cambia el destino del redirect.
 *
 * While iste en pie, el destino del redirect es `dashboard` —la ruta por
 * defecto de la app— en vez de un `/login` inexistente que daria 404.
 */
export const AutenticacionGuard: CanActivateFn = () => {
  const autenticacion = inject(AutenticacionService);
  const router = inject(Router);

  return autenticacion.estaAutenticado() ? true : router.createUrlTree(['/dashboard']);
};