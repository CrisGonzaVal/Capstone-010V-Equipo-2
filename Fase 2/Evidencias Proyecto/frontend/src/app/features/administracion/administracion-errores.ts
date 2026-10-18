import { HttpErrorResponse } from '@angular/common/http';

/**
 * Mensaje legible de un fallo de la administración institucional (Feature 012, T10).
 *
 * Prefiere el `detail` textual del backend (404/409/422 del contrato organizacional
 * de las Features 011/012) y, si no es texto (p. ej. un error de validación de
 * Pydantic, que llega como lista), recurre a un mensaje por código de estado. Vive
 * fuera de los componentes para compartir el mismo criterio entre vistas.
 */
export function mensajeDeErrorAdministracion(error: HttpErrorResponse): string {
  const detalle = (error.error as { detail?: unknown } | null)?.detail;
  if (typeof detalle === 'string' && detalle.trim() !== '') {
    return detalle;
  }
  switch (error.status) {
    case 401:
      return 'Tu sesión no es válida. Vuelve a iniciar sesión.';
    case 403:
      return 'Tu rol no tiene permiso para esta operación administrativa.';
    case 404:
      return 'El recurso indicado no existe o no pertenece a tu institución.';
    case 409:
      return 'La operación entra en conflicto con el estado actual: revisa las dependencias antes de continuar.';
    case 422:
      return 'Los datos enviados no son válidos.';
    case 0:
      return 'No se pudo contactar al servidor. Verifica la conexión e inténtalo de nuevo.';
    default:
      return `No se pudo completar la operación (HTTP ${error.status}).`;
  }
}
