import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Signal,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink } from '@angular/router';
import { filter } from 'rxjs';

/** Sección del área administrativa institucional enlazada desde la barra. */
export interface EnlaceAdministracion {
  /** Ruta hija completa a la que apunta el enlace (destino real del anchor). */
  readonly ruta: string;
  /** Segmento final de la ruta; da forma al `id` estable de la pestaña. */
  readonly seccion: string;
  readonly etiqueta: string;
}

/**
 * Orden visual y de tabulación de la barra. Es también el orden del recorrido
 * circular con las flechas.
 */
export const ENLACES_ADMINISTRACION: readonly EnlaceAdministracion[] = [
  { ruta: '/administracion/sedes', seccion: 'sedes', etiqueta: 'Sedes' },
  {
    ruta: '/administracion/departamentos',
    seccion: 'departamentos',
    etiqueta: 'Departamentos',
  },
  { ruta: '/administracion/usuarios', seccion: 'usuarios', etiqueta: 'Usuarios' },
  { ruta: '/administracion/encargados', seccion: 'encargados', etiqueta: 'Encargados' },
];

/** `id` estable de la pestaña (y valor de `aria-labelledby` del panel). */
export function identificadorPestana(enlace: EnlaceAdministracion): string {
  return `pestana-administracion-${enlace.seccion}`;
}

/**
 * Resuelve el enlace activo a partir de una URL del Router (enmienda T-17, D-1).
 *
 * Quita query y fragmento y compara por segmento: coincidencia exacta o prefijo
 * seguido de `/`, nunca substring crudo (evita que `/administracion/sedes-x`
 * active `sedes`). La comparación es la misma que usa `routerLinkActive` no
 * exacto, de modo que un futuro segmento anidado seguiría marcando su padre.
 *
 * Ante una URL transitoria sin coincidencia (por ejemplo durante una
 * redirección) devuelve `sedes` como fallback **visual**: no navega ni reescribe
 * la URL.
 */
export function resolverEnlaceActivo(url: string): EnlaceAdministracion {
  const ruta = (url.split(/[?#]/)[0] ?? '').replace(/\/+$/, '');
  return (
    ENLACES_ADMINISTRACION.find(
      (enlace) => ruta === enlace.ruta || ruta.startsWith(`${enlace.ruta}/`),
    ) ?? ENLACES_ADMINISTRACION[0]
  );
}

/**
 * URL vigente del Router como señal, actualizada en cada `NavigationEnd`.
 *
 * La fuente de verdad sigue siendo `Router.url`; la señal solo la hace reactiva
 * para la detección de cambios `OnPush`. Cubre deep links, atrás/adelante y
 * navegaciones disparadas fuera de la barra, a diferencia de un estado local
 * actualizado solo al hacer clic. Se comparte entre la barra y el panel del
 * layout (`AdministracionComponent`) para que ambos deriven la misma sección
 * activa de una única resolución (riesgo "aria-labelledby apunta a pestaña
 * incorrecta").
 */
export function urlActivaDelRouter(router: Router): Signal<string> {
  const url = signal(router.url);
  router.events
    .pipe(
      filter((evento): evento is NavigationEnd => evento instanceof NavigationEnd),
      takeUntilDestroyed(),
    )
    .subscribe((evento) => url.set(evento.urlAfterRedirects));
  return url.asReadonly();
}

/**
 * Navegación interna del área administrativa institucional (Feature 012, T10;
 * pestañas ARIA en la enmienda T-17).
 *
 * Barra de secciones para el Administrador Institucional: sedes, departamentos,
 * usuarios y encargados. La fuente de verdad es el Router (D-1): de `Router.url`
 * se derivan `aria-selected`, el `tabindex` roving y el panel asociado. Sigue
 * siendo solo navegación: la autorización real la resuelve el `RolGuard` de la
 * ruta y la matriz central del backend.
 */
@Component({
  selector: 'app-administracion-nav',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './administracion-nav.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AdministracionNavComponent {
  private readonly router = inject(Router);
  private readonly anfitrion: ElementRef<HTMLElement> = inject(ElementRef);

  /** Enlaces de la barra, en orden visual y de recorrido. */
  readonly enlaces = ENLACES_ADMINISTRACION;

  private readonly urlActiva = urlActivaDelRouter(this.router);

  /** Enlace correspondiente a la ruta vigente (con fallback visual a sedes). */
  readonly enlaceActivo = computed(() => resolverEnlaceActivo(this.urlActiva()));

  /** `id` estable de una pestaña. */
  identificador(enlace: EnlaceAdministracion): string {
    return identificadorPestana(enlace);
  }

  /** ¿Este enlace es la pestaña seleccionada? */
  esActivo(enlace: EnlaceAdministracion): boolean {
    return enlace.ruta === this.enlaceActivo().ruta;
  }

  /**
   * Flechas izquierda/derecha con recorrido circular (enmienda T-17, D-2).
   *
   * Solo atiende esas dos teclas: `preventDefault()` se aplica únicamente a
   * ellas y ninguna otra tecla se intercepta. Mueve el foco al anchor destino y
   * lo activa con un clic, de modo que su `RouterLink` realice la navegación y
   * se conserven el resto de comportamientos nativos del enlace (Ctrl/Cmd+clic,
   * clic central, apertura en pestaña nueva, `href` copiable).
   */
  alNavegarPestanas(evento: KeyboardEvent): void {
    if (evento.key !== 'ArrowRight' && evento.key !== 'ArrowLeft') {
      return;
    }
    evento.preventDefault();

    const origen = evento.target as HTMLElement | null;
    const enfocado = this.enlaces.findIndex(
      (enlace) => identificadorPestana(enlace) === origen?.id,
    );
    const indice =
      enfocado >= 0
        ? enfocado
        : this.enlaces.findIndex((enlace) => enlace.ruta === this.enlaceActivo().ruta);

    const paso = evento.key === 'ArrowRight' ? 1 : -1;
    const destino = this.enlaces[(indice + paso + this.enlaces.length) % this.enlaces.length];

    const anchor = this.anfitrion.nativeElement.querySelector<HTMLAnchorElement>(
      `#${identificadorPestana(destino)}`,
    );
    if (!anchor) {
      return;
    }
    anchor.focus();
    anchor.click();
  }
}
