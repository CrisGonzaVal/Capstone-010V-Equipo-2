import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { DepartamentoGestion, Sede } from '../../shared/interfaces';
import { mensajeDeErrorAdministracion } from './administracion-errores';
import { AdministracionService } from './services/administracion.service';

/**
 * Vista de departamentos de la institución (Feature 012, AC-7/AC-11).
 *
 * Lista los departamentos del tenant con su sede asignada o la ausencia de
 * asignación, su estado activo/inactivo, y permite crear, editar, desactivar/
 * reactivar y **asignar la sede** escogiendo solo entre las sedes devueltas por
 * el servidor para el tenant (nunca se ofrece una sede ajena). Los conflictos
 * 409 (desactivación con usuarios vinculados) se muestran con el motivo.
 */
@Component({
  selector: 'app-administracion-departamentos',
  standalone: true,
  imports: [ReactiveFormsModule],
  templateUrl: './departamentos.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DepartamentosComponent implements OnInit {
  private readonly administracion = inject(AdministracionService);
  private readonly constructorFormulario = inject(NonNullableFormBuilder);

  readonly cargando = signal(true);
  readonly departamentos = signal<DepartamentoGestion[]>([]);
  readonly sedes = signal<Sede[]>([]);
  readonly mensajeError = signal<string | null>(null);
  readonly mensajeExito = signal<string | null>(null);
  readonly errorAccion = signal<string | null>(null);

  readonly editando = signal<DepartamentoGestion | null>(null);
  readonly confirmando = signal<DepartamentoGestion | null>(null);
  readonly asignandoSede = signal<DepartamentoGestion | null>(null);
  readonly sedeSeleccion = signal<number | null>(null);
  readonly guardando = signal(false);

  readonly formulario = this.constructorFormulario.group({
    nombre_dep: ['', [Validators.required, Validators.maxLength(100)]],
    descripcion: ['', [Validators.maxLength(200)]],
  });

  readonly formularioEdicion = this.constructorFormulario.group({
    nombre_dep: ['', [Validators.required, Validators.maxLength(100)]],
    descripcion: ['', [Validators.maxLength(200)]],
  });

  ngOnInit(): void {
    this.cargar();
  }

  reintentar(): void {
    this.cargar();
  }

  nombreSede(sedeId: number | null): string | null {
    if (sedeId === null) {
      return null;
    }
    return this.sedes().find((sede) => sede.sede_id === sedeId)?.nombre ?? null;
  }

  crear(): void {
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }
    const valores = this.formulario.getRawValue();
    this.guardando.set(true);
    this.errorAccion.set(null);
    this.mensajeExito.set(null);

    this.administracion
      .crearDepartamento({
        nombre_dep: valores.nombre_dep.trim(),
        descripcion: valores.descripcion.trim() || null,
      })
      .subscribe({
        next: (creado) => {
          this.guardando.set(false);
          this.formulario.reset({ nombre_dep: '', descripcion: '' });
          this.departamentos.update((lista) => [...lista, creado]);
          this.mensajeExito.set(`Departamento «${creado.nombre_dep}» creado.`);
        },
        error: (error: HttpErrorResponse) => {
          this.guardando.set(false);
          this.errorAccion.set(mensajeDeErrorAdministracion(error));
        },
      });
  }

  iniciarEdicion(departamento: DepartamentoGestion): void {
    this.errorAccion.set(null);
    this.mensajeExito.set(null);
    this.confirmando.set(null);
    this.asignandoSede.set(null);
    this.formularioEdicion.reset({
      nombre_dep: departamento.nombre_dep,
      descripcion: departamento.descripcion ?? '',
    });
    this.editando.set(departamento);
  }

  cancelarEdicion(): void {
    this.editando.set(null);
  }

  guardarEdicion(): void {
    const departamento = this.editando();
    if (!departamento) {
      return;
    }
    if (this.formularioEdicion.invalid) {
      this.formularioEdicion.markAllAsTouched();
      return;
    }
    const valores = this.formularioEdicion.getRawValue();
    this.guardando.set(true);
    this.errorAccion.set(null);

    this.administracion
      .editarDepartamento(departamento.departamento_id, {
        nombre_dep: valores.nombre_dep.trim(),
        descripcion: valores.descripcion.trim() || null,
      })
      .subscribe({
        next: (actualizado) => {
          this.guardando.set(false);
          this.editando.set(null);
          this.reemplazar(actualizado);
          this.mensajeExito.set(`Departamento «${actualizado.nombre_dep}» actualizado.`);
        },
        error: (error: HttpErrorResponse) => {
          this.guardando.set(false);
          this.errorAccion.set(mensajeDeErrorAdministracion(error));
        },
      });
  }

  iniciarAsignacionSede(departamento: DepartamentoGestion): void {
    this.errorAccion.set(null);
    this.mensajeExito.set(null);
    this.editando.set(null);
    this.confirmando.set(null);
    this.sedeSeleccion.set(departamento.sede_id);
    this.asignandoSede.set(departamento);
  }

  cancelarAsignacionSede(): void {
    this.asignandoSede.set(null);
    this.sedeSeleccion.set(null);
  }

  cambiarSeleccionSede(evento: Event): void {
    const valor = (evento.target as HTMLSelectElement).value;
    this.sedeSeleccion.set(valor === '' ? null : Number(valor));
  }

  guardarSede(): void {
    const departamento = this.asignandoSede();
    const sedeId = this.sedeSeleccion();
    if (!departamento || sedeId === null) {
      return;
    }
    this.guardando.set(true);
    this.errorAccion.set(null);

    this.administracion
      .asignarSedeDepartamento(departamento.departamento_id, sedeId)
      .subscribe({
        next: (resultado) => {
          this.guardando.set(false);
          this.asignandoSede.set(null);
          this.sedeSeleccion.set(null);
          this.reemplazar({ ...departamento, sede_id: resultado.sede_id });
          this.mensajeExito.set(
            `Sede «${this.nombreSede(resultado.sede_id) ?? resultado.sede_id}» asignada a «${departamento.nombre_dep}».`,
          );
        },
        error: (error: HttpErrorResponse) => {
          this.guardando.set(false);
          this.errorAccion.set(mensajeDeErrorAdministracion(error));
        },
      });
  }

  solicitarCambioEstado(departamento: DepartamentoGestion): void {
    this.errorAccion.set(null);
    this.mensajeExito.set(null);
    this.editando.set(null);
    this.asignandoSede.set(null);
    this.confirmando.set(departamento);
  }

  cancelarCambioEstado(): void {
    this.confirmando.set(null);
  }

  confirmarCambioEstado(): void {
    const departamento = this.confirmando();
    if (!departamento) {
      return;
    }
    const nuevoEstado = !departamento.activo;
    this.guardando.set(true);
    this.errorAccion.set(null);

    this.administracion
      .cambiarEstadoDepartamento(departamento.departamento_id, nuevoEstado)
      .subscribe({
        next: (resultado) => {
          this.guardando.set(false);
          this.confirmando.set(null);
          this.departamentos.update((lista) =>
            lista.map((item) =>
              item.departamento_id === resultado.departamento_id
                ? { ...item, activo: resultado.activo }
                : item,
            ),
          );
          this.mensajeExito.set(
            resultado.activo
              ? `Departamento «${departamento.nombre_dep}» reactivado.`
              : `Departamento «${departamento.nombre_dep}» desactivado.`,
          );
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
      sedes: this.administracion.listarSedes(),
    }).subscribe({
      next: ({ departamentos, sedes }) => {
        this.departamentos.set(departamentos);
        this.sedes.set(sedes);
        this.cargando.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.departamentos.set([]);
        this.sedes.set([]);
        this.cargando.set(false);
        this.mensajeError.set(mensajeDeErrorAdministracion(error));
      },
    });
  }

  private reemplazar(actualizado: DepartamentoGestion): void {
    this.departamentos.update((lista) =>
      lista.map((item) =>
        item.departamento_id === actualizado.departamento_id ? actualizado : item,
      ),
    );
  }
}
