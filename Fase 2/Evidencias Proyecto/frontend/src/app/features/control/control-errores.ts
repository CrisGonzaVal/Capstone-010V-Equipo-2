import { HttpErrorResponse } from '@angular/common/http';

/**
 * Mensaje legible de un fallo del portal de control (Feature 012, T9; ampliado en
 * Feature 017 con las mutaciones motivadas y la gestión de Administradores).
 *
 * Prefiere el `detail` textual del backend (404/409/422/503 del contrato de
 * control) y, si no es texto (p. ej. error de validación de Pydantic), recurre a
 * un mensaje por código de estado. Vive fuera de los componentes para que las
 * vistas de control compartan el mismo criterio sin duplicar la tabla.
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
      return 'La institución o el Administrador indicado no existe.';
    case 409:
      return 'La operación entra en conflicto con el estado actual: por ejemplo, la baja del último Administrador activo o una invitación ya aceptada.';
    case 422:
      return 'Los datos o el motivo enviados no son válidos: revisa el catálogo, el texto de «Otro» y el límite de 500 caracteres.';
    case 503:
      return 'El servicio de identidad o una confirmación local no está disponible. Reintenta la operación; el motivo se completa sin repetir el cambio.';
    case 0:
      return 'No se pudo contactar al servidor. Verifica la conexión e inténtalo de nuevo.';
    default:
      return `No se pudo completar la operación (HTTP ${error.status}).`;
  }
}
