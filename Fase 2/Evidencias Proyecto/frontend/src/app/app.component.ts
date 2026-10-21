import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import {
  puedeAdministrar as rolPuedeAdministrar,
  puedeVerDashboard as rolPuedeVerDashboard,
  puedeVerInventario as rolPuedeVerInventario,
  puedeVerTickets as rolPuedeVerTickets,
} from './core/auth/roles';
import { AutenticacionService } from './core/services/auth.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppComponent {
  readonly autenticacion = inject(AutenticacionService);
  private readonly router = inject(Router);

  readonly titulo = 'CompuStock';

  /** `sidebarAbierto` es un signal, no un booleano mutable: el toggle re-renderiza solo. */
  readonly sidebarAbierto = signal(true);

  /**
   * Estado derivado de la identidad local (`/auth/me`) para la presentación.
   *
   * Son `computed()` sobre las señales del servicio: la vista nunca lee datos
   * quemados ni el perfil de Clerk. Mostrar el rol es solo informativo; aquí no
   * se evalúan permisos, no se filtran elementos ni se redirige por rol.
   */
  readonly nombreCompleto = computed(() => {
    const identidad = this.autenticacion.identidad();
    return identidad ? `${identidad.nombre} ${identidad.apellido}` : null;
  });

  readonly correoLocal = computed(() => this.autenticacion.identidad()?.correo ?? null);

  readonly rolLegible = computed(() => this.autenticacion.identidad()?.rol ?? null);

  /**
   * Contexto institucional derivado de `/auth/me` (Feature 008, AC-17/AC-19).
   *
   * Para Administrador, Bodeguero y Solicitante es el nombre de su institución
   * efectiva; para Superadmin, cuya `institucion` es `null`, es un contexto
   * global explícito ("Todas las instituciones"), no un vacío. Es informativo:
   * la vista solo lo presenta, no autoriza ni permite elegir ámbito.
   */
  readonly contextoInstitucional = computed(() => {
    const identidad = this.autenticacion.identidad();
    if (!identidad) {
      return null;
    }
    if (identidad.institucion) {
      return identidad.institucion.nombre;
    }
    return identidad.rol === 'Superadmin' ? 'Todas las instituciones' : null;
  });

  /**
   * `true` si el rol puede acceder al área administrativa. Solo oculta el
   * enlace de la navegación (AC-3): la ruta sigue protegida por el guard de rol,
   * de modo que un acceso directo no depende de este control de interfaz.
   */
  readonly puedeAdministrar = computed(() =>
    rolPuedeAdministrar(this.autenticacion.identidad()?.rol ?? null),
  );

  /**
   * `true` si el rol navega a las superficies de negocio (Feature 017, AC-15).
   *
   * El Superadmin queda fuera de dashboard, inventario y tickets: su superficie
   * es el portal `/control`. Solo oculta enlaces de la navegación; las rutas
   * siguen protegidas por el guard de rol, de modo que un acceso directo no
   * depende de este control de interfaz.
   */
  readonly puedeVerDashboard = computed(() =>
    rolPuedeVerDashboard(this.autenticacion.identidad()?.rol ?? null),
  );

  readonly puedeVerInventario = computed(() =>
    rolPuedeVerInventario(this.autenticacion.identidad()?.rol ?? null),
  );

  /** `true` si el rol puede navegar a `/tickets` (Feature 012, AC-3; 017, AC-15). */
  readonly puedeVerTickets = computed(() =>
    rolPuedeVerTickets(this.autenticacion.identidad()?.rol ?? null),
  );

  /**
   * `true` si el rol es Superadmin, único con acceso al portal `/control`
   * (Feature 010, AC-15). Solo oculta el enlace de la navegación: la ruta sigue
   * protegida por `ControlSuperadminGuard` y el backend por la matriz central.
   */
  readonly puedeControl = computed(
    () => this.autenticacion.identidad()?.rol === 'Superadmin',
  );

  /** Inicial del nombre normalizada a mayúscula; `null` sin identidad resuelta. */
  readonly inicialNombre = computed(() => {
    const nombre = this.autenticacion.identidad()?.nombre?.trim();
    return nombre ? nombre.charAt(0).toUpperCase() : null;
  });

  /**
   * Marcador neutro mientras la identidad carga o no está disponible. No tiene
   * forma de identidad real (ni nombre plausible ni rol supuesto).
   */
  readonly etiquetaIdentidad = computed(() => {
    switch (this.autenticacion.estadoIdentidad()) {
      case 'cargando':
        return 'Cargando identidad';
      case 'no_disponible':
        return 'Identidad no disponible';
      default:
        return null;
    }
  });

  alternarSidebar(): void {
    this.sidebarAbierto.update((abierto) => !abierto);
  }

  /** Cierra la sesión de Clerk y vuelve al login. */
  cerrarSesion(): void {
    void this.autenticacion.cerrarSesion().then(() => this.router.navigate(['/login']));
  }
}