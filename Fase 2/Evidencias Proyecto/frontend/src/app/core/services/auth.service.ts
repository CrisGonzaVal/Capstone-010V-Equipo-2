import { Injectable, computed, signal } from '@angular/core';

const CLAVE_TOKEN = 'compustock_token';

/**
 * Estado de sesion y almacenamiento del token.
 *
 * La autenticacion sigue siendo decorativa (AGENTS.md §3): el backend emite un
 * JWT HS256 local y no hay login ni verificacion real todavia. Este servicio
 * existe para que el token tenga un unico dueño —el interceptor lo lee, los
 * guards lo consultan— y no se lea de `localStorage` desde tres archivos.
 *
 * El estado es un `signal`, no un `BehaviorSubject`: lo consume la vista con
 * `@if`/`@for` y no necesita `async` en ningun template.
 */
@Injectable({ providedIn: 'root' })
export class AutenticacionService {
  private readonly _token = signal<string | null>(localStorage.getItem(CLAVE_TOKEN));

  /** `true` cuando hay un token en memoria. No implica que el token sea valido. */
  readonly estaAutenticado = computed(() => this._token() !== null);

  readonly token = this._token.asReadonly();

  guardarToken(token: string): void {
    localStorage.setItem(CLAVE_TOKEN, token);
    this._token.set(token);
  }

  cerrarSesion(): void {
    localStorage.removeItem(CLAVE_TOKEN);
    this._token.set(null);
  }
}