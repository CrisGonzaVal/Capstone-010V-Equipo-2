/**
 * Copia un texto al portapapeles (Feature 017, T9).
 *
 * Usa la Clipboard API cuando está disponible y, si no (o si el navegador la
 * deniega), cae al `textarea` temporal con `execCommand`. Devuelve `false` sin
 * lanzar: la vista informa que la copia no fue posible y el usuario puede
 * seleccionar el enlace manualmente.
 */
export async function copiarAlPortapapeles(texto: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(texto);
      return true;
    }
  } catch {
    // Se intenta el camino alternativo.
  }
  try {
    const area = document.createElement('textarea');
    area.value = texto;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const copiado = document.execCommand('copy');
    document.body.removeChild(area);
    return copiado;
  } catch {
    return false;
  }
}
