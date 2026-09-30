import { ChangeDetectionStrategy, Component } from '@angular/core';

interface PermisoRol {
  etiqueta: string;
  activo: boolean;
}

interface FichaRol {
  nombre: string;
  descripcion: string;
  permisos: PermisoRol[];
}

/**
 * Matriz de roles del sistema multi-tenant.
 *
 * **Es documental, no funcional.** Refleja los cuatro actores de `AGENTS.md` §2
 * pero no consulta la tabla `rol`: las casillas no persisten y el toggle no
 * dispara nada. Convertirlo en administration real de permisos pertenece a la
 * feature de administracion de usuarios.
 */
@Component({
  selector: 'app-administracion',
  standalone: true,
  templateUrl: './administracion.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AdministracionComponent {
  readonly roles: FichaRol[] = [
    {
      nombre: 'Super Administrador',
      descripcion: 'Acceso total al sistema multi-tenant y creación de instituciones.',
      permisos: [{ etiqueta: 'Crear Instancias (Instituciones)', activo: true }],
    },
    {
      nombre: 'Administrador de Institución',
      descripcion: 'Gestión de usuarios y asignación de roles dentro de la sede.',
      permisos: [
        { etiqueta: 'Gestionar Usuarios', activo: true },
        { etiqueta: 'Asignar Roles', activo: true },
      ],
    },
    {
      nombre: 'Bodeguero / Solicitante',
      descripcion: 'Control de inventario, despacho y creación de tickets de insumos.',
      permisos: [
        { etiqueta: 'Acceso Catálogo CRUD', activo: true },
        { etiqueta: 'Módulo de Tickets', activo: true },
      ],
    },
  ];
}