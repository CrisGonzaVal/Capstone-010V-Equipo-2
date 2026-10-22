import { administracionRoutes } from './administracion.routes';

/**
 * Contrato de navegación del área administrativa institucional (Feature 012, T10).
 *
 * Un layout lazy con `AdministracionComponent` que monta la navegación y sus
 * vistas hijas (sedes, departamentos, usuarios y encargados), todas de carga
 * perezosa. El acceso lo protege `app.routes.ts` con el guard de roles
 * administrativos; este segmento no lo repite ni ofrece selector de institución.
 */
describe('administracionRoutes', () => {
  const layout = administracionRoutes[0];
  const hijas = (layout.children ?? []).filter((r) => r.path !== '');

  it('monta el layout con carga perezosa', () => {
    expect(typeof layout.loadComponent).toBe('function');
  });

  it('redirige la entrada vacía a sedes', () => {
    const raiz = (layout.children ?? []).find((r) => r.path === '');
    expect(raiz?.redirectTo).toBe('sedes');
  });

  it('publica las cuatro vistas de dominio con carga perezosa', () => {
    expect(hijas.map((r) => r.path).sort()).toEqual(
      ['departamentos', 'encargados', 'sedes', 'usuarios'].sort(),
    );
    for (const hija of hijas) {
      const contexto = hija.path ?? '';
      expect(typeof hija.loadComponent).withContext(contexto).toBe('function');
      expect(hija.loadChildren).withContext(contexto).toBeUndefined();
    }
  });
});
