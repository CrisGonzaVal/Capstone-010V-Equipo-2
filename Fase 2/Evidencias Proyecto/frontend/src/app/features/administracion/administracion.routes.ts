import { Routes } from '@angular/router';

/**
 * Segmento lazy-loaded del área administrativa institucional (Feature 012, T10).
 *
 * El acceso lo protege `app.routes.ts` con el guard de roles administrativos. El
 * layout (`AdministracionComponent`) monta la navegación y el `RouterOutlet`; cada
 * vista de dominio (sedes, departamentos, usuarios y encargados) se carga de forma
 * perezosa. No permite elegir institución ni esquema: el ámbito es el de la sesión.
 * La gestión SaaS del Superadmin vive en `/control`.
 */
export const administracionRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./administracion.component').then((m) => m.AdministracionComponent),
    title: 'Administración | CompuStock',
    children: [
      { path: '', redirectTo: 'sedes', pathMatch: 'full' },
      {
        path: 'sedes',
        loadComponent: () => import('./sedes.component').then((m) => m.SedesComponent),
        title: 'Sedes | CompuStock',
      },
      {
        path: 'departamentos',
        loadComponent: () =>
          import('./departamentos.component').then((m) => m.DepartamentosComponent),
        title: 'Departamentos | CompuStock',
      },
      {
        path: 'usuarios',
        loadComponent: () =>
          import('./usuarios.component').then((m) => m.UsuariosComponent),
        title: 'Usuarios | CompuStock',
      },
      {
        path: 'encargados',
        loadComponent: () =>
          import('./encargados.component').then((m) => m.EncargadosComponent),
        title: 'Encargados | CompuStock',
      },
    ],
  },
];
