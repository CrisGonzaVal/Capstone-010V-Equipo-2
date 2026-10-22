import { HttpErrorResponse } from '@angular/common/http';

/**
 * Mensaje legible de un fallo de la administración institucional (Feature 012, T10;
 * ampliado en Feature 017 con 409/422/503 de invitaciones y motivos).
 *
 * Prefiere el `detail` textual del backend (404/409/422 del contrato organizacional
 * de las Features 011/012/017) y, si no es texto (p. ej. un error de validación de
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
      return 'La operación entra en conflicto con el estado actual (por ejemplo, un correo ya vinculado o una invitación ya aceptada).';
    case 422:
      return 'Los datos o el motivo enviados no son válidos: revisa el catálogo, el texto de «Otro» y el límite de 500 caracteres.';
    case 503:
      return 'El servicio de identidad o una confirmación local no está disponible. Si el alta quedó incompleta, reintenta con el mismo correo para completarla.';
    case 0:
      return 'No se pudo contactar al servidor. Verifica la conexión e inténtalo de nuevo.';
    default:
      return `No se pudo completar la operación (HTTP ${error.status}).`;
  }
}
