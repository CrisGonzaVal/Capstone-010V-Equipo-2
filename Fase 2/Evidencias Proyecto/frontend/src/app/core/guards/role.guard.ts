import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AutenticacionService } from '../services/auth.service';

/**
 * Ruta dedicada al acceso denegado por rol. Es la navegación que devuelve el
 * `RolGuard` cuando la identidad no tiene el rol permitido: ni `/login` ni
 * cierre de sesión, porque la persona autenticada sigue con su sesión vigente.
 */
export const RUTA_ACCESO_DENEGADO = '/acceso-denegado';

/**
 * Guard de autorización por rol.
 *
 * Espera el estado de identidad de `AutenticacionService` (sin repetir
 * `/auth/me`) y compara el rol local de forma **exacta** contra los roles
 * permitidos por la ruta. Los cuatro roles son literales distintos: `Admin` no
 * es un alias de `Administrador` y un rol ausente/desconocido nunca concede.
 *
 * La exigencia de sesión vive en `AutenticacionGuard` (que redirige a `/login`
 * con retorno); este guard nunca manda a `/login` ni cierra la sesión. Ante
 * falta de permiso devuelve navegación a `RUTA_ACCESO_DENEGADO` y no activa la
 * ruta, de modo que la operación de la vista no llega a ejecutarse.
 */
export const RolGuard = (rolesPermitidos: readonly string[]): CanActivateFn => {
  return async () => {
    const autenticacion = inject(AutenticacionService);
    const router = inject(Router);

    const identidad = await autenticacion.esperarIdentidad();

    const autorizado = identidad !== null && rolesPermitidos.includes(identidad.rol);
    return autorizado ? true : router.createUrlTree([RUTA_ACCESO_DENEGADO]);
  };
};
