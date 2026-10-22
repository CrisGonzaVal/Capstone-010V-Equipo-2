import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  effect,
  inject,
  viewChild,
} from '@angular/core';
import { Router } from '@angular/router';

import { AutenticacionService } from '../../core/services/auth.service';

/** Ruta protegida a la que se va tras reconocerse la sesión de control. */
export const DESTINO_ALTA_CONTROL = '/control/alta';

/**
 * Login del portal `/control` (Feature 010, AC-7/AC-15).
 *
 * Reutiliza la UI prebuilt de inicio de sesión de Clerk ya embebida
 * (`AutenticacionService.montarInicioSesion`): no hay formulario propio, ni
 * registro, ni un segundo mecanismo de sesión. Al reconocerse la sesión navega
 * al alta de control, donde el `ControlSuperadminGuard` decide por rol.
 *
 * Es una vista pública (sin guard) para poder iniciar sesión; la protección
 * recae en la ruta de alta, no aquí.
 */
@Component({
  selector: 'app-control-login',
  standalone: true,
  templateUrl: './control-login.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ControlLoginComponent implements AfterViewInit, OnDestroy {
  private readonly autenticacion = inject(AutenticacionService);
  private readonly router = inject(Router);

  readonly contenedor = viewChild.required<ElementRef<HTMLDivElement>>('contenedorSignIn');

  private nodoMontado?: HTMLDivElement;

  constructor() {
    effect(() => {
      if (this.autenticacion.estaAutenticado()) {
        void this.router.navigateByUrl(DESTINO_ALTA_CONTROL);
      }
    });
  }

  ngAfterViewInit(): void {
    void this.montarInicioSesion();
  }

  ngOnDestroy(): void {
    if (this.nodoMontado) {
      this.autenticacion.desmontarInicioSesion(this.nodoMontado);
    }
  }

  private async montarInicioSesion(): Promise<void> {
    await this.autenticacion.inicializar();
    const nodo = this.contenedor().nativeElement;
    // Fija el destino del `SignIn` prebuilt. Con una sesión ya activa, Clerk
    // redirige por su cuenta al reconocerla; sin este `forceRedirectUrl` ese
    // destino es `/` (que el router convierte en `/dashboard`) y el portal de
    // control nunca llega al alta. Con él, login y sesión preexistente aterrizan
    // en el mismo sitio: `/control/alta`.
    this.autenticacion.montarInicioSesion(nodo, {
      forceRedirectUrl: DESTINO_ALTA_CONTROL,
    });
    this.nodoMontado = nodo;
  }
}
