import { HttpClient } from '@angular/common/http';
import { InjectionToken, Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { environment } from '../../../environments/environment';
import { URL_API } from '../../shared/config/url-api';
import { IdentidadAutenticada } from '../../shared/interfaces';

/**
 * Sesión de Clerk: la app solo necesita poder pedir el token vigente.
 * `session.getToken()` es la única fuente del Bearer.
 */
export interface SesionClerk {
  getToken(): Promise<string | null>;
}

/** Datos mínimos del usuario de Clerk que la aplicación consume. */
export interface UsuarioClerk {
  id: string;
  fullName?: string | null;
  primaryEmailAddress?: { emailAddress: string } | null;
}

/** Emisión de `addListener`: estado consolidado que publica el SDK. */
export interface RecursosClerk {
  session?: SesionClerk | null;
  user?: UsuarioClerk | null;
}

/**
 * Disponibilidad de la identidad local (`/auth/me`), **independiente** del
 * estado de sesión de Clerk: una sesión puede existir aunque el vínculo local
 * responda 401.
 *
 * - `cargando`: hay sesión y la identidad está en tránsito (o Clerk aún carga).
 * - `disponible`: `/auth/me` respondió y hay identidad local vinculada.
 * - `no_disponible`: no hay sesión, se cerró sesión o la identidad falló/no existe.
 */
export type EstadoIdentidad = 'cargando' | 'disponible' | 'no_disponible';

/**
 * Superficie del SDK `@clerk/clerk-js` que la aplicación usa.
 *
 * Es una interfaz estructural a propósito: permite inyectar el SDK real en
 * producción y un doble en Karma sin salir a la red. La instancia real de
 * `Clerk` la satisface sin adaptadores. Ver `frontend/src/testing/clerk-falso.ts`.
 */
export interface InstanciaClerk {
  isSignedIn: boolean;
  session: SesionClerk | null | undefined;
  user: UsuarioClerk | null | undefined;
  load(): Promise<void>;
  addListener(listener: (recursos: RecursosClerk) => void): () => void;
  signOut(): Promise<void>;
  mountSignIn(nodo: HTMLDivElement, props?: unknown): void;
  unmountSignIn(nodo: HTMLDivElement): void;
}

export type CargadorClerk = () => Promise<InstanciaClerk>;

/**
 * Deriva el dominio del Frontend API desde la publishable key.
 *
 * Una publishable key tiene la forma `pk_test_<base64>`, donde el base64
 * decodifica el dominio del Frontend API con un `$` final que se descarta. Es la
 * misma derivación que usa el quickstart de Clerk para ubicar el bundle de UI.
 */
export function derivarDominioFrontendApi(publishableKey: string): string {
  return atob(publishableKey.split('_')[2]).slice(0, -1);
}

/**
 * Carga el bundle de UI prebuilt de Clerk (`@clerk/ui`) desde el Frontend API.
 *
 * `@clerk/clerk-js` v6 es headless: los componentes prebuilt (`mountSignIn`)
 * viven en un paquete aparte que el SDK ya no incluye. El quickstart oficial
 * para JavaScript vanilla lo carga desde el CDN del Frontend API y lo entrega a
 * `load({ ui: { ClerkUI } })`. Sin esto `mountSignIn` lanza
 * "Clerk was not loaded with Ui components".
 */
async function cargarUiClerk(): Promise<{ ClerkUI: unknown }> {
  const global = window as unknown as { __internal_ClerkUICtor?: unknown };
  if (global.__internal_ClerkUICtor) {
    return { ClerkUI: global.__internal_ClerkUICtor };
  }

  const dominio = derivarDominioFrontendApi(environment.clerkPublishableKey);
  await new Promise<void>((resolver, rechazar) => {
    const script = document.createElement('script');
    script.src = `https://${dominio}/npm/@clerk/ui@1/dist/ui.browser.js`;
    script.async = true;
    script.crossOrigin = 'anonymous';
    script.onload = () => resolver();
    script.onerror = () => rechazar(new Error('No se pudo cargar el bundle de UI de Clerk'));
    document.head.appendChild(script);
  });

  return { ClerkUI: global.__internal_ClerkUICtor };
}

/**
 * Costura de inyección del SDK de Clerk.
 *
 * La fábrica real usa `import()` dinámico: `@clerk/clerk-js` pesa más que el
 * presupuesto del bundle inicial, así que se carga en su propio chunk. La UI
 * prebuilt se resuelve dentro de `load()`, de modo que el contrato de la costura
 * `InstanciaClerk` no cambia. En pruebas se reemplaza por `crearClerkFalso()`.
 */
export const CARGADOR_CLERK = new InjectionToken<CargadorClerk>('CARGADOR_CLERK', {
  providedIn: 'root',
  factory: (): CargadorClerk => async () => {
    const { Clerk } = await import('@clerk/clerk-js');
    const clerk = new Clerk(environment.clerkPublishableKey);
    const cargarOriginal = clerk.load.bind(clerk);
    clerk.load = async () => {
      const ui = await cargarUiClerk();
      await (cargarOriginal as (opciones: { ui: unknown }) => Promise<void>)({ ui });
    };
    return clerk;
  },
});

/**
 * Dueño único de la sesión de Clerk en el frontend.
 *
 * Reemplaza al antiguo estado de token en `localStorage`: la sesión la
 * administra el SDK y aquí se expone como señales (`estaAutenticado`,
 * `usuario`) para que guards, interceptor y vistas la consuman sin leer
 * almacenamiento local ni manejar JWT locales.
 */
@Injectable({ providedIn: 'root' })
export class AutenticacionService {
  private readonly cargarClerk = inject(CARGADOR_CLERK);
  private readonly http = inject(HttpClient);

  private readonly _sesion = signal<SesionClerk | null>(null);
  private readonly _usuario = signal<UsuarioClerk | null>(null);
  private readonly _cargando = signal(true);

  /** Identidad local vinculada (`/auth/me`). Estado separado de la sesión. */
  private readonly _identidad = signal<IdentidadAutenticada | null>(null);
  private readonly _estadoIdentidad = signal<EstadoIdentidad>('cargando');

  private clerk?: InstanciaClerk;
  private inicializacion?: Promise<void>;

  /**
   * Invalida respuestas pendientes de `/auth/me`. Cada carga captura la
   * generación vigente; al limpiar/cambiar de sesión sube la generación, de modo
   * que una respuesta tardía ya no publica identidad de una sesión anterior.
   */
  private generacionIdentidad = 0;

  /** `true` cuando Clerk reconoce una sesión activa. No evalúa roles. */
  readonly estaAutenticado = computed(() => this._sesion() !== null);

  /** `true` mientras Clerk aún no termina de cargar. */
  readonly cargando = this._cargando.asReadonly();

  readonly usuario = this._usuario.asReadonly();

  /** Identidad local vinculada, o `null` mientras carga/falla/no hay sesión. */
  readonly identidad = this._identidad.asReadonly();

  /** Disponibilidad de la identidad, separada del estado de sesión. */
  readonly estadoIdentidad = this._estadoIdentidad.asReadonly();

  constructor() {
    void this.inicializar();
  }

  /**
   * Carga Clerk una sola vez, publica el estado inicial y engancha el listener
   * de cambios. Idempotente: varias llamadas comparten la misma promesa.
   */
  inicializar(): Promise<void> {
    this.inicializacion ??= this.arrancar();
    return this.inicializacion;
  }

  /** Pide al SDK el token de sesión vigente. `null` si no hay sesión. */
  async obtenerToken(): Promise<string | null> {
    const sesion = this._sesion();
    return sesion ? sesion.getToken() : null;
  }

  /** Cierre de sesión programático. El listener refleja el nuevo estado. */
  async cerrarSesion(): Promise<void> {
    await this.clerk?.signOut();
    this._sesion.set(null);
    this._usuario.set(null);
    // Limpieza inmediata: no se espera al listener del SDK ni a respuestas de
    // `/auth/me` que puedan llegar tarde.
    this.limpiarIdentidad();
  }

  /** Monta la UI prebuilt de inicio de sesión sobre el nodo indicado. */
  montarInicioSesion(nodo: HTMLDivElement): void {
    this.clerk?.mountSignIn(nodo);
  }

  /** Desmonta la UI prebuilt de inicio de sesión. */
  desmontarInicioSesion(nodo: HTMLDivElement): void {
    this.clerk?.unmountSignIn(nodo);
  }

  private async arrancar(): Promise<void> {
    const clerk = await this.cargarClerk();
    await clerk.load();
    this.clerk = clerk;
    this.sincronizar(clerk);
    clerk.addListener((recursos) => this.sincronizar(recursos));
    this._cargando.set(false);
  }

  private sincronizar(recursos: RecursosClerk): void {
    const sesionAnterior = this._sesion();
    const sesionNueva = recursos.session ?? null;

    this._sesion.set(sesionNueva);
    this._usuario.set(recursos.user ?? null);

    if (sesionNueva === null) {
      // Sin sesión: identidad no disponible de inmediato.
      this.limpiarIdentidad();
      return;
    }

    // Misma sesión (Clerk reemite por actualizaciones de usuario, o el usuario
    // navega): no se repite la petición. Solo inicialización/cambio efectivo de
    // sesión dispara `/auth/me`.
    if (sesionNueva === sesionAnterior) {
      return;
    }

    // Nueva sesión: se borra cualquier identidad anterior antes de resolver.
    this.limpiarIdentidad();
    void this.cargarIdentidad();
  }

  /** Solicita la identidad local una vez para la sesión vigente. */
  private async cargarIdentidad(): Promise<void> {
    this.invalidarRespuestasPendientes();
    const generacion = this.generacionIdentidad;

    this._identidad.set(null);
    this._estadoIdentidad.set('cargando');

    try {
      const identidad = await firstValueFrom(
        this.http.get<IdentidadAutenticada>(`${URL_API}/auth/me`),
      );
      if (generacion !== this.generacionIdentidad) {
        return; // Respuesta tardía de una sesión ya cerrada/cambiada.
      }
      this._identidad.set(identidad);
      this._estadoIdentidad.set('disponible');
    } catch {
      if (generacion !== this.generacionIdentidad) {
        return;
      }
      // Error/401: sin identidad y sin sustituto desde el perfil de Clerk.
      this._identidad.set(null);
      this._estadoIdentidad.set('no_disponible');
    }
  }

  /** Limpia la identidad y descarta respuestas de `/auth/me` aún en vuelo. */
  private limpiarIdentidad(): void {
    this.invalidarRespuestasPendientes();
    this._identidad.set(null);
    this._estadoIdentidad.set('no_disponible');
  }

  private invalidarRespuestasPendientes(): void {
    this.generacionIdentidad += 1;
  }
}
