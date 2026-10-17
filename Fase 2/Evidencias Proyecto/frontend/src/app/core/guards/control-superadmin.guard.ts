import { CanActivateFn } from '@angular/router';

import { ROLES_CONTROL } from '../auth/roles';
import { RolGuard } from './role.guard';

/**
 * Guard de navegación del portal `/control` (Feature 010, AC-7/AC-9/AC-15).
 *
 * Solo el rol exacto `Superadmin` activa la ruta de alta. Reutiliza el patrón
 * del `RolGuard`: espera la identidad ya resuelta por `AutenticacionService`
 * (sin repetir `/auth/me`), compara el rol local de forma exacta y, ante
 * denegación, navega a `/acceso-denegado` sin cerrar la sesión.
 *
 * **No es frontera de seguridad:** es navegación. El backend valida el token de
 * Clerk y la matriz central en cada petición, de modo que un acceso directo a la
 * API no depende de este guard.
 */
export const ControlSuperadminGuard: CanActivateFn = RolGuard(ROLES_CONTROL);
