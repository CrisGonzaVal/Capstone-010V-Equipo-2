import { MotivoCodigo, MotivoMutacion } from '../interfaces';

/**
 * Catálogo cerrado de motivos de mutación (Feature 017, D-5/AC-10).
 *
 * Reproduce 1:1 `MOTIVOS_MUTACION` del backend: no es configurable y la
 * validación real (código válido, `otro` con texto, ≤500 caracteres) permanece
 * en el servidor. Aquí solo se evita enviar una entrada que ya se sabe inválida.
 */
export const LONGITUD_MAXIMA_TEXTO_MOTIVO = 500;

export interface OpcionMotivo {
  codigo: MotivoCodigo;
  etiqueta: string;
}

export const MOTIVOS_MUTACION: readonly OpcionMotivo[] = [
  { codigo: 'cambio_funciones', etiqueta: 'Cambio de funciones' },
  { codigo: 'reasignacion_organizacional', etiqueta: 'Reasignación organizacional' },
  { codigo: 'correccion_datos', etiqueta: 'Corrección de datos' },
  { codigo: 'termino_vinculo', etiqueta: 'Término de vínculo' },
  { codigo: 'seguridad_acceso', etiqueta: 'Seguridad de acceso' },
  { codigo: 'otro', etiqueta: 'Otro' },
];

/** `true` si el código pertenece al catálogo cerrado. */
export function esCodigoDeMotivo(codigo: string): codigo is MotivoCodigo {
  return MOTIVOS_MUTACION.some((opcion) => opcion.codigo === codigo);
}

/**
 * `true` si el motivo puede enviarse: código del catálogo, texto dentro del
 * límite y, para `otro`, texto no vacío. No muta nada ni consulta al servidor.
 */
export function esMotivoCompleto(codigo: string, texto: string): boolean {
  if (!esCodigoDeMotivo(codigo)) {
    return false;
  }
  if (texto.length > LONGITUD_MAXIMA_TEXTO_MOTIVO) {
    return false;
  }
  if (codigo === 'otro' && texto.trim() === '') {
    return false;
  }
  return true;
}

/**
 * Arma el DTO `MotivoMutacion` o `null` si la entrada no es válida. El texto se
 * envía recortado y vacío se traduce a `null` (opcional para los demás códigos).
 */
export function construirMotivo(
  codigo: string,
  texto: string,
): MotivoMutacion | null {
  if (!esMotivoCompleto(codigo, texto)) {
    return null;
  }
  const limpio = texto.trim();
  return {
    codigo: codigo as MotivoCodigo,
    texto: limpio === '' ? null : limpio,
  };
}

const ETIQUETAS_ESTADO_INVITACION: Record<string, string> = {
  pendiente: 'Pendiente',
  aceptada: 'Aceptada',
  revocada: 'Revocada',
  expirada: 'Expirada',
  'no disponible': 'No disponible',
};

/**
 * Etiqueta legible del estado persistido de invitación. Un valor desconocido no
 * se presenta como aceptación: cae en «No disponible» (D-3).
 */
export function etiquetaEstadoInvitacion(estado: string | null | undefined): string {
  if (!estado) {
    return ETIQUETAS_ESTADO_INVITACION['no disponible'];
  }
  return ETIQUETAS_ESTADO_INVITACION[estado] ?? ETIQUETAS_ESTADO_INVITACION['no disponible'];
}
