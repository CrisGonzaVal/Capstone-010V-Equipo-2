import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AutenticacionService } from '../services/auth.service';

/**
 * Restringe una ruta a los roles permitidos.
 *
 * Se usa como `canActivate: [RolGuard(['ADMINISTRADOR'])]`. Igual que
 * `AutenticacionGuard`, **no se aplica a ninguna ruta todavia**: el rol vive en
 * el token como decodificacion tentativa y la verificacion real es de
 * Feature 006.
 *
 * Sin token, o con un rol que no este en la lista, devuelve `false` y el router
 * aplica su redireccion por defecto. No se inventa una ruta `/sin-permisos`:
 * ese caso de uso se resuelve cuando exista la pantalla.
 */
export const RolGuard = (rolesPermitidos: string[]): CanActivateFn => {
  return () => {
    const autenticacion = inject(AutenticacionService);
    const router = inject(Router);

    const token = autenticacion.token();
    if (!token) {
      return router.createUrlTree(['/dashboard']);
    }

    // Decodificacion tentativa del payload: sirve para decidir el menu, no para
    // autorizar. La autorizacion real la hace el backend en cada endpoint.
    try {
      const carga = JSON.parse(atob(token.split('.')[1])) as { rol?: string };
      return rolesPermitidos.includes(carga.rol ?? '')
        ? true
        : router.createUrlTree(['/dashboard']);
    } catch {
      return router.createUrlTree(['/dashboard']);
    }
  };
};