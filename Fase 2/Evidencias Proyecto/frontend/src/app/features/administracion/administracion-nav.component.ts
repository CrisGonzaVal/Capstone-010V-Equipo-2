import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';

interface EnlaceAdministracion {
  readonly ruta: string;
  readonly etiqueta: string;
}

/**
 * Navegación interna del área administrativa institucional (Feature 012, T10).
 *
 * Barra de secciones para el Administrador Institucional: sedes, departamentos,
 * usuarios y encargados. Es solo navegación: la autorización real la resuelve el
 * `RolGuard` de la ruta y la matriz central del backend. No ofrece selector de
 * institución ni de esquema (el ámbito lo deriva el servidor de la sesión).
 */
@Component({
  selector: 'app-administracion-nav',
  standalone: true,
  imports: [RouterLink, RouterLinkActive],
  templateUrl: './administracion-nav.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AdministracionNavComponent {
  readonly enlaces: readonly EnlaceAdministracion[] = [
    { ruta: '/administracion/sedes', etiqueta: 'Sedes' },
    { ruta: '/administracion/departamentos', etiqueta: 'Departamentos' },
    { ruta: '/administracion/usuarios', etiqueta: 'Usuarios' },
    { ruta: '/administracion/encargados', etiqueta: 'Encargados' },
  ];
}
