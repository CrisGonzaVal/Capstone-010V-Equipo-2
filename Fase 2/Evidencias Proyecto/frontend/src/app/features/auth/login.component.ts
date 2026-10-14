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
 * Destino tras iniciar sesión: la ruta local solicitada si es válida, `/dashboard`
 * en cualquier otro caso. Se rechaza lo que no sea una ruta interna (`//host` o
 * una URL absoluta) para no aceptar redirecciones externas.
 */
export function resolverDestinoRetorno(retorno: string | null): string {
  const esRutaLocal =
    !!retorno && retorno.startsWith('/') && !retorno.startsWith('//') && retorno !== '/login';
  return esRutaLocal ? retorno : '/dashboard';
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

  private readonly destino = resolverDestinoRetorno(
    this.ruta.snapshot.queryParamMap.get('retorno'),
  );

  private nodoMontado?: HTMLDivElement;

  constructor() {
    effect(() => {
      if (this.autenticacion.estaAutenticado()) {
        void this.router.navigateByUrl(this.destino);
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
    this.autenticacion.montarInicioSesion(nodo);
    this.nodoMontado = nodo;
  }
}
