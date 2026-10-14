import type {
  InstanciaClerk,
  RecursosClerk,
  SesionClerk,
  UsuarioClerk,
} from '../app/core/services/auth.service';

/**
 * Doble de pruebas del SDK `@clerk/clerk-js`.
 *
 * Karma no puede salir a la red ni montar el widget real de Clerk, así que la
 * `AutenticacionService` se prueba contra este doble. Implementa la costura
 * `InstanciaClerk` (interfaz estructural del SDK) y añade utilidades para
 * empujar emisiones al listener registrado, que es lo que el SDK real hace al
 * cambiar la sesión.
 */
export interface InstanciaClerkFalsa extends InstanciaClerk {
  load: jasmine.Spy;
  signOut: jasmine.Spy;
  mountSignIn: jasmine.Spy;
  unmountSignIn: jasmine.Spy;
  /** Simula un inicio de sesión: fija la sesión, el usuario y notifica al listener. */
  firmarSesion(usuario?: UsuarioClerk, token?: string | null): void;
  /** Empuja recursos arbitrarios al listener, como haría el SDK real. */
  emitir(recursos: RecursosClerk): void;
}

export function crearClerkFalso(): InstanciaClerkFalsa {
  let listener: ((recursos: RecursosClerk) => void) | null = null;

  const falso: InstanciaClerkFalsa = {
    load: jasmine.createSpy('load').and.resolveTo(undefined),
    signOut: jasmine.createSpy('signOut').and.resolveTo(undefined),
    mountSignIn: jasmine.createSpy('mountSignIn'),
    unmountSignIn: jasmine.createSpy('unmountSignIn'),
    isSignedIn: false,
    session: null,
    user: null,
    addListener: (fn: (recursos: RecursosClerk) => void) => {
      listener = fn;
      return () => {
        listener = null;
      };
    },
    emitir: (recursos: RecursosClerk) => {
      falso.session = recursos.session ?? null;
      falso.user = recursos.user ?? null;
      falso.isSignedIn = (recursos.session ?? null) !== null;
      listener?.(recursos);
    },
    firmarSesion: (usuario?: UsuarioClerk, token: string | null = 'token-de-prueba') => {
      const sesion: SesionClerk = { getToken: () => Promise.resolve(token) };
      falso.emitir({ session: sesion, user: usuario ?? { id: 'user_de_prueba' } });
    },
  };

  return falso;
}
