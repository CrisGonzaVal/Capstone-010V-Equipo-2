import { HttpErrorResponse } from '@angular/common/http';

/**
 * Mensaje legible de un fallo del portal de control (Feature 012, T9).
 *
 * Prefiere el `detail` textual del backend (404/409/422 del contrato de control)
 * y, si no es texto (p. ej. error de validación de Pydantic), recurre a un
 * mensaje por código de estado. Vive fuera de los componentes para que las vistas
 * de control compartan el mismo criterio sin duplicar la tabla.
 */
export function mensajeDeErrorControl(error: HttpErrorResponse): string {
  const detalle = (error.error as { detail?: unknown } | null)?.detail;
  if (typeof detalle === 'string' && detalle.trim() !== '') {
    return detalle;
  }
  switch (error.status) {
    case 401:
      return 'Tu sesión no es válida para el portal de control. Vuelve a iniciar sesión.';
    case 403:
      return 'Tu rol no tiene permiso para esta operación de control.';
    case 404:
      return 'La institución indicada no existe.';
    case 409:
      return 'La operación entra en conflicto con el estado actual de la institución.';
    case 422:
      return 'Los datos enviados no son válidos.';
    case 0:
      return 'No se pudo contactar al servidor. Verifica la conexión e inténtalo de nuevo.';
    default:
      return `No se pudo completar la operación (HTTP ${error.status}).`;
  }
}
