import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AutenticacionService } from '../services/auth.service';

/**
 * Exige una sesión de Clerk para entrar a la ruta.
 *
 * Espera a que Clerk termine de cargar (`inicializar`) antes de decidir: si no,
 * una recarga de la página redirigiría a login a una persona ya autenticada.
 * Sin sesión devuelve a `/login` conservando `retorno`, la ruta local solicitada
 * para volver tras iniciar sesión.
 *
 * No evalúa roles: eso es la Feature 007.
 */
export const AutenticacionGuard: CanActivateFn = async (_ruta, estado) => {
  const autenticacion = inject(AutenticacionService);
  const router = inject(Router);

  await autenticacion.inicializar();

  return autenticacion.estaAutenticado()
    ? true
    : router.createUrlTree(['/login'], { queryParams: { retorno: estado.url } });
};
