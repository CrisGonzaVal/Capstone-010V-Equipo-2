import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  effect,
  inject,
  viewChild,
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';

import { AutenticacionService } from '../../core/services/auth.service';

/**
 * `true` si el valor de `?retorno=` es una ruta interna navegable. Se rechaza lo
 * que no sea una ruta interna (`//host` o una URL absoluta) para no aceptar
 * redirecciones externas, y la propia `/login` para no entrar en un bucle.
 */
export function esRetornoLocalValido(retorno: string | null): retorno is string {
  return (
    !!retorno &&
    retorno.startsWith('/') &&
    !retorno.startsWith('//') &&
    retorno !== '/login'
  );
}

/**
 * Destino tras iniciar sesión: la ruta local solicitada si es válida; si no hay
 * retorno, `/control` para el Superadmin —cuya única superficie es el portal de
 * control— y `/dashboard` para los roles de negocio (Feature 017, T12).
 *
 * El fallback por rol evita que un Superadmin recién autenticado aterrice en
 * `/dashboard` y sea expulsado a `/acceso-denegado` (AC-15/AC-18).
 */
export function resolverDestinoRetorno(
  retorno: string | null,
  rol: string | null = null,
): string {
  if (esRetornoLocalValido(retorno)) {
    return retorno;
  }
  return rol === 'Superadmin' ? '/control' : '/dashboard';
}

/**
 * Ruta `/login`: monta la UI prebuilt de inicio de sesión de Clerk.
 *
 * No hay formulario propio ni registro: la UI la provee Clerk embebida
 * (`mountSignIn`), no el Account Portal externo. Al reconocerse la sesión se
 * navega al destino de retorno.
 */
@Component({
  selector: 'app-login',
  standalone: true,
  templateUrl: './login.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LoginComponent implements OnDestroy {
  private readonly autenticacion = inject(AutenticacionService);
  private readonly router = inject(Router);
  private readonly ruta = inject(ActivatedRoute);

  readonly contenedor = viewChild.required<ElementRef<HTMLDivElement>>('contenedorSignIn');

  /** Destino ya navegado: evita repetir la navegación en re-ejecuciones. */
  private destinoNavegado: string | null = null;

  private nodoMontado?: HTMLDivElement;

  constructor() {
    effect(() => {
      if (!this.autenticacion.estaAutenticado()) {
        return;
      }
      const destino = this.calcularDestino();
      if (destino === null || destino === this.destinoNavegado) {
        return;
      }
      this.destinoNavegado = destino;
      void this.router.navigateByUrl(destino);
    });
  }

  /**
   * Destino vigente. Un retorno local válido se sigue de inmediato; sin él hay
   * que esperar a que la identidad local deje de estar `cargando` para elegir
   * entre `/control` (Superadmin) y `/dashboard` (resto). `null` = aún no se
   * puede decidir.
   */
  private calcularDestino(): string | null {
    const retorno = this.ruta.snapshot.queryParamMap.get('retorno');
    if (esRetornoLocalValido(retorno)) {
      return retorno;
    }
    if (this.autenticacion.estadoIdentidad() === 'cargando') {
      return null;
    }
    return resolverDestinoRetorno(null, this.autenticacion.identidad()?.rol ?? null);
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
    this.autenticacion.montarInicioSesion(nodo);
    this.nodoMontado = nodo;
  }
}
