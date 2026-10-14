import { CanActivateFn } from '@angular/router';

/**
 * Guard de autorización por rol — **inerte en la Feature 006**.
 *
 * La sesión la administra Clerk (`AutenticacionService`) y la exigencia de
 * identidad vive en `auth.guard.ts`. La política de roles (Admin, Bodeguero,
 * Solicitante), las redirecciones por rol y la protección por rol son Feature
 * 007. Hoy este guard deja pasar siempre, sin inspeccionar el token ni el rol.
 *
 * Conserva la firma `RolGuard(roles)` para que la 007 implemente la autoría
 * real sin cambiar los sitios de uso.
 */
export const RolGuard = (_rolesPermitidos: string[]): CanActivateFn => {
  return () => true;
};
