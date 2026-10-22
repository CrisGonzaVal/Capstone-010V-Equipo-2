import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { forkJoin } from 'rxjs';

import { DepartamentoGestion, Encargado, Rol, Usuario } from '../../shared/interfaces';
import { mensajeDeErrorAdministracion } from './administracion-errores';
import { AdministracionService } from './services/administracion.service';

const _SOLICITANTE = 'Solicitante';

/**
 * Vista de encargados por departamento (Feature 012, AC-10).
 *
 * Permite escoger un departamento del tenant, ver sus encargados vigentes (o el
 * estado vacío) y asociar o retirar encargados. Los candidatos se limitan a los
 * usuarios **Solicitantes del mismo departamento** que aún no son encargados,
 * derivados del listado del tenant: la vista no inventa candidatos ni ofrece
 * usuarios de otro departamento. Las reglas y respuestas son las de la Feature
 * 011; ser encargado no cambia el rol ni concede permisos.
 */
@Component({
  selector: 'app-administracion-encargados',
  standalone: true,
  imports: [],
  templateUrl: './encargados.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EncargadosComponent implements OnInit {
  private readonly administracion = inject(AdministracionService);

  readonly cargando = signal(true);
  readonly departamentos = signal<DepartamentoGestion[]>([]);
  readonly usuarios = signal<Usuario[]>([]);
  readonly roles = signal<Rol[]>([]);
  readonly encargados = signal<Encargado[]>([]);

  readonly departamentoSeleccionado = signal<number | null>(null);
  readonly candidatoSeleccionado = signal<number | null>(null);

  readonly mensajeError = signal<string | null>(null);
  readonly mensajeExito = signal<string | null>(null);
  readonly errorAccion = signal<string | null>(null);
  readonly guardando = signal(false);
  readonly cargandoEncargados = signal(false);

  private readonly rolesPorId = computed(
    () => new Map(this.roles().map((rol) => [rol.rol_id, rol.nombre_rol])),
  );

  /** Candidatos a encargado: Solicitantes del departamento aún no asociados. */
  readonly candidatos = computed(() => {
    const departamentoId = this.departamentoSeleccionado();
    if (departamentoId === null) {
      return [];
    }
    const yaAsociados = new Set(this.encargados().map((e) => e.usuario_id));
    return this.usuarios().filter(
      (usuario) =>
        usuario.departamento_id === departamentoId &&
        this.rolesPorId().get(usuario.rol_id) === _SOLICITANTE &&
        !yaAsociados.has(usuario.usuario_id),
    );
  });

  ngOnInit(): void {
    this.cargar();
  }

  reintentar(): void {
    this.cargar();
  }

  nombreDepartamento(departamentoId: number | null): string | null {
    if (departamentoId === null) {
      return null;
    }
    return (
      this.departamentos().find((d) => d.departamento_id === departamentoId)
        ?.nombre_dep ?? null
    );
  }

  seleccionarDepartamento(evento: Event): void {
    const valor = (evento.target as HTMLSelectElement).value;
    this.departamentoSeleccionado.set(valor === '' ? null : Number(valor));
    this.mensajeExito.set(null);
    this.errorAccion.set(null);
    this.candidatoSeleccionado.set(null);
    this.cargarEncargados();
  }

  seleccionarCandidato(evento: Event): void {
    const valor = (evento.target as HTMLSelectElement).value;
    this.candidatoSeleccionado.set(valor === '' ? null : Number(valor));
  }

  asociar(): void {
    const departamentoId = this.departamentoSeleccionado();
    const usuarioId = this.candidatoSeleccionado();
    if (departamentoId === null || usuarioId === null) {
      return;
    }
    this.guardando.set(true);
    this.errorAccion.set(null);
    this.mensajeExito.set(null);

    this.administracion.asociarEncargado(departamentoId, usuarioId).subscribe({
      next: (encargado) => {
        this.guardando.set(false);
        this.candidatoSeleccionado.set(null);
        this.encargados.update((lista) => [...lista, encargado]);
        this.mensajeExito.set(
          `«${encargado.nombre} ${encargado.apellido}» asociado como encargado.`,
        );
      },
      error: (error: HttpErrorResponse) => {
        this.guardando.set(false);
        this.errorAccion.set(mensajeDeErrorAdministracion(error));
      },
    });
  }

  retirar(usuarioId: number): void {
    const departamentoId = this.departamentoSeleccionado();
    if (departamentoId === null) {
      return;
    }
    this.guardando.set(true);
    this.errorAccion.set(null);
    this.mensajeExito.set(null);

    this.administracion.retirarEncargado(departamentoId, usuarioId).subscribe({
      next: () => {
        this.guardando.set(false);
        this.encargados.update((lista) =>
          lista.filter((item) => item.usuario_id !== usuarioId),
        );
        this.mensajeExito.set('Encargado retirado.');
      },
      error: (error: HttpErrorResponse) => {
        this.guardando.set(false);
        this.errorAccion.set(mensajeDeErrorAdministracion(error));
      },
    });
  }

  private cargar(): void {
    this.cargando.set(true);
    this.mensajeError.set(null);

    forkJoin({
      departamentos: this.administracion.listarDepartamentos(),
      usuarios: this.administracion.listarUsuarios(),
      roles: this.administracion.listarRoles(),
    }).subscribe({
      next: ({ departamentos, usuarios, roles }) => {
        this.departamentos.set(departamentos);
        this.usuarios.set(usuarios);
        this.roles.set(roles);
        this.cargando.set(false);

        const primero = departamentos[0];
        if (primero) {
          this.departamentoSeleccionado.set(primero.departamento_id);
          this.cargarEncargados();
        }
      },
      error: (error: HttpErrorResponse) => {
        this.cargando.set(false);
        this.mensajeError.set(mensajeDeErrorAdministracion(error));
      },
    });
  }

  private cargarEncargados(): void {
    const departamentoId = this.departamentoSeleccionado();
    if (departamentoId === null) {
      this.encargados.set([]);
      return;
    }
    this.cargandoEncargados.set(true);

    this.administracion.listarEncargados(departamentoId).subscribe({
      next: (encargados) => {
        this.encargados.set(encargados);
        this.cargandoEncargados.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.encargados.set([]);
        this.cargandoEncargados.set(false);
        this.errorAccion.set(mensajeDeErrorAdministracion(error));
      },
    });
  }
}
