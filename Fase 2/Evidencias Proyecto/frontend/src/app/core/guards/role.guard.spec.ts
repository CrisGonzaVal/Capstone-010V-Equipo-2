import { ActivatedRouteSnapshot, RouterStateSnapshot, provideRouter } from '@angular/router';
import { TestBed } from '@angular/core/testing';

import { RolGuard } from './role.guard';

/**
 * Feature 006 no autoriza por rol: el mecanismo existe para que la Feature 007
 * lo implemente, pero hoy **no** restringe ninguna ruta.
 */
describe('RolGuard', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
  });

  function evaluar(roles: string[]) {
    return TestBed.runInInjectionContext(() =>
      RolGuard(roles)({} as ActivatedRouteSnapshot, { url: '/administracion' } as RouterStateSnapshot),
    );
  }

  it('es inerte: deja pasar aunque el rol no esté en la lista', () => {
    expect(evaluar(['ADMINISTRADOR'])).toBe(true);
  });

  it('es inerte incluso sin roles declarados', () => {
    expect(evaluar([])).toBe(true);
  });
});
