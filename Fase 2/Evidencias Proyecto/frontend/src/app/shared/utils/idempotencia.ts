/**
 * Clave de idempotencia para una mutación administrativa (Feature 017, D-5).
 *
 * El backend la usa para completar el registro de motivo en un reintento sin
 * repetir el cambio de negocio. Se genera una vez al abrir el formulario y se
 * reutiliza mientras la operación no confirme éxito.
 */
export function nuevaClaveIdempotencia(): string {
  const cripto = globalThis.crypto;
  if (cripto && typeof cripto.randomUUID === 'function') {
    return cripto.randomUUID();
  }
  return `idem-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}
