import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { WritableSignal, signal } from '@angular/core';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { of } from 'rxjs';

import { URL_API } from '../../shared/config/url-api';
import { AutenticacionService } from '../../core/services/auth.service';
import {
  CatalogosTicket,
  HistorialTransicion,
  IdentidadAutenticada,
  TicketDetalle,
} from '../../shared/interfaces';
import { TicketDetalleComponent } from './ticket-detalle.component';

const RUTA_DETALLE = `${URL_API}/tickets/7`;
const RUTA_HISTORIAL = `${URL_API}/tickets/7/historial`;
const RUTA_CATALOGOS = `${URL_API}/tickets/catalogos`;
const RUTA_ESTADO = `${URL_API}/tickets/7/estado`;
const RUTA_ANULACION = `${URL_API}/tickets/7/anulacion`;
const RUTA_RECHAZO = `${URL_API}/tickets/7/rechazo`;

/** Catálogo canónico de la 013: `Anulado` al final del orden del flujo. */
const CATALOGOS_013: CatalogosTicket = {
  prioridades: [
    { prioridad_id: 1, nombre: 'Alta', descripcion: 'Corto plazo' },
    { prioridad_id: 2, nombre: 'Media', descripcion: 'Reposición' },
  ],
  estados: [
    { estado_id: 1, nombre: 'Pendiente', descripcion: 'Sin revisar' },
    { estado_id: 2, nombre: 'EnRevision', descripcion: 'En revisión' },
    { estado_id: 3, nombre: 'EnCurso', descripcion: 'En preparación' },
    { estado_id: 4, nombre: 'Cerrado', descripcion: 'Despachado' },
    { estado_id: 5, nombre: 'Anulado', descripcion: 'Anulado o rechazado' },
  ],
  productos: [
    {
      producto_id: 1,
      nombre: 'Cuaderno rayado',
      unidad_medida: 'UNIDAD',
      categoria_nombre: 'Papelería',
      stock_total: 50,
      es_critico: false,
    },
    {
      producto_id: 2,
      nombre: 'Toner HP 26A',
      unidad_medida: 'UNIDAD',
      categoria_nombre: 'Tóner',
      stock_total: 3,
      es_critico: true,
    },
  ],
  solicitantes: [
    {
      usuario_id: 5,
      nombre: 'Isabel',
      apellido: 'Contreras',
      correo: 'isabel.contreras@losalpes.cl',
      departamento_nombre: 'Docencia',
    },
    {
      usuario_id: 1,
      nombre: 'Camila',
      apellido: 'Fernandez',
      correo: 'camila.fernandez@losalpes.cl',
      departamento_nombre: 'Dirección',
    },
  ],
};

const PRODUCTO_DETALLE = {
  producto_id: 1,
  nombre: 'Cuaderno rayado',
  descripcion: null,
  unidad_medida: 'UNIDAD',
  stock_minimo: 5,
  categoria_id: 1,
  categoria: null,
};

/** Detalle base: `Pendiente`, del Solicitante dueño (usuario 5), con un ítem. */
function crearDetalle(estado_id = 1, usuario_id = 5): TicketDetalle {
  return {
    ticket_id: 7,
    usuario_id,
    prioridad_id: 1,
    estado_id,
    asunto: 'Falta de papel para el trimestre',
    descripcion: 'Se solicita papel oficio para impresiones.',
    fecha_creacion: '2026-10-10T09:00:00',
    fecha_cierre: null,
    sede_id: 3,
    sede_nombre: 'Sede Central',
    detalles: [
      {
        detalle_ticket_id: 10,
        producto_id: 1,
        cantidad_solicitada: 3,
        cantidad_entregada: 1,
        producto: PRODUCTO_DETALLE,
      },
    ],
    estado_nombre: CATALOGOS_013.estados[estado_id - 1].nombre,
  };
}

/** Historial base: creación (origen nulo) + transición a `EnRevision` con motivo. */
function crearHistorial(): HistorialTransicion[] {
  return [
    {
      historial_transicion_id: 1,
      ticket_id: 7,
      estado_origen_id: null,
      estado_destino_id: 1,
      usuario_id: 5,
      fecha_transicion: '2026-10-10T09:00:00',
      motivo: null,
      estado_origen_nombre: null,
      estado_destino_nombre: 'Pendiente',
      usuario_nombre: 'Isabel',
      usuario_apellido: 'Contreras',
    },
    {
      historial_transicion_id: 2,
      ticket_id: 7,
      estado_origen_id: 1,
      estado_destino_id: 2,
      usuario_id: 9,
      fecha_transicion: '2026-10-11T10:00:00',
      motivo: 'Revisión inicial del requerimiento',
      estado_origen_nombre: 'Pendiente',
      estado_destino_nombre: 'EnRevision',
      usuario_nombre: 'Bruno',
      usuario_apellido: 'Soto',
    },
  ];
}

describe('TicketDetalleComponent', () => {
  let fixture: ComponentFixture<TicketDetalleComponent>;
  let componente: TicketDetalleComponent;
  let httpMock: HttpTestingController;
  let raiz: HTMLElement;

  /** Identidad local (`/auth/me`) que el componente lee para condicionar la UI. */
  let identidad: WritableSignal<IdentidadAutenticada | null>;

  function crearIdentidad(rol: string, usuario_id = 9): IdentidadAutenticada {
    return {
      usuario_id,
      sub: 'user_detalle',
      nombre: 'Bruno',
      apellido: 'Soto',
      correo: 'bruno.soto@losalpes.cl',
      rol,
      institucion: { institucion_id: 'inst-los-alpes', nombre: 'Los Alpes' },
    };
  }

  /** Responde las tres peticiones del arranque de la vista. */
  function responderCarga(
    detalle: TicketDetalle | null = crearDetalle(),
    historial: HistorialTransicion[] = crearHistorial(),
  ) {
    if (detalle === null) {
      // `forkJoin` cancela las otras dos peticiones al fallar el detalle; se
      // descartan del controlador para que `verify` no las cuente como abiertas.
      httpMock
        .expectOne(RUTA_DETALLE)
        .flush({ detail: 'Ticket no encontrado' }, { status: 404, statusText: 'Not Found' });
      httpMock.match(RUTA_HISTORIAL);
      httpMock.match(RUTA_CATALOGOS);
      fixture.detectChanges();
      return;
    }
    httpMock.expectOne(RUTA_DETALLE).flush(detalle);
    httpMock.expectOne(RUTA_HISTORIAL).flush(historial);
    httpMock.expectOne(RUTA_CATALOGOS).flush(CATALOGOS_013);
    fixture.detectChanges();
  }

  /** Responde la reconsulta silenciosa de detalle + historial tras una mutación. */
  function responderReconsulta(
    detalle: TicketDetalle = crearDetalle(2),
    historial: HistorialTransicion[] = crearHistorial(),
  ) {
    httpMock.expectOne(RUTA_DETALLE).flush(detalle);
    httpMock.expectOne(RUTA_HISTORIAL).flush(historial);
    fixture.detectChanges();
  }

  /** Botón cuyo texto visible coincide (más preciso que un índice de CSS). */
  function boton(texto: string): HTMLButtonElement | null {
    const botones = Array.from(raiz.querySelectorAll<HTMLButtonElement>('button'));
    return (
      botones.find((b) => (b.textContent ?? '').replace(/\s+/g, ' ').trim() === texto) ?? null
    );
  }

  /** Botones de acciones visibles en la página (excluye los de los diálogos). */
  function botonesAccion(): string[] {
    return Array.from(raiz.querySelectorAll('button'))
      .filter((b) => b.closest('dialog') === null)
      .map((b) => (b.textContent ?? '').replace(/\s+/g, ' ').trim());
  }

  function textoRaiz(): string {
    return (raiz.textContent ?? '').replace(/\s+/g, ' ');
  }

  function alertas(): string[] {
    return Array.from(raiz.querySelectorAll('[role="alert"]')).map((n) =>
      (n.textContent ?? '').replace(/\s+/g, ' ').trim(),
    );
  }

  beforeEach(async () => {
    identidad = signal<IdentidadAutenticada | null>(crearIdentidad('Administrador'));

    await TestBed.configureTestingModule({
      imports: [TicketDetalleComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AutenticacionService, useValue: { identidad } },
        {
          provide: ActivatedRoute,
          useValue: { paramMap: of(convertToParamMap({ ticketId: '7' })) },
        },
      ],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(TicketDetalleComponent);
    componente = fixture.componentInstance;
    raiz = fixture.nativeElement as HTMLElement;
  });

  afterEach(() => {
    httpMock.verify({ ignoreCancelled: true });
  });

  // ---------------------------------------------------------------------------
  // Carga y render (AC-23)
  // ---------------------------------------------------------------------------

  describe('carga y cabecera', () => {
    it('carga detalle, historial y catálogos al abrir la vista', () => {
      responderCarga();

      expect(componente.ticket()).not.toBeNull();
      expect(componente.historial().length).toBe(2);
      expect(componente.catalogos()).not.toBeNull();
      expect(componente.cargando()).toBe(false);
      expect(componente.errorCarga()).toBeNull();
    });

    it('muestra cabecera con asunto, prioridad, estado, solicitante, departamento, sede y fechas', () => {
      responderCarga();

      const texto = textoRaiz();
      expect(texto).toContain('Falta de papel para el trimestre');
      expect(texto).toContain('Alta');
      expect(texto).toContain('Pendiente');
      expect(texto).toContain('Contreras, Isabel');
      expect(texto).toContain('isabel.contreras@losalpes.cl');
      expect(texto).toContain('Docencia');
      expect(texto).toContain('Sede Central');
      expect(texto).toContain('2026');
      // Sin `fecha_cierre` no aparece el bloque de cierre.
      expect(texto).not.toContain('Cerrado');
    });

    it('muestra la fecha de cierre solo cuando existe', () => {
      const conCierre = crearDetalle();
      conCierre.fecha_cierre = '2026-10-12T15:30:00';
      responderCarga(conCierre);

      expect(textoRaiz()).toContain('Cerrado');
    });

    it('muestra los ítems con cantidades solicitadas y entregadas', () => {
      responderCarga();

      const texto = textoRaiz();
      expect(texto).toContain('Cuaderno rayado');
      expect(texto).toContain('Solicitado');
      expect(texto).toContain('Entregado');
      expect(texto).toContain('3');
      expect(texto).toContain('1');
    });

    it('muestra el historial completo con actor, de→a, instante y motivo', () => {
      responderCarga();

      const texto = textoRaiz();
      expect(texto).toContain('Creación → Pendiente');
      expect(texto).toContain('Pendiente → EnRevision');
      expect(texto).toContain('Contreras, Isabel');
      expect(texto).toContain('Soto, Bruno');
      expect(texto).toContain('Revisión inicial del requerimiento');
    });

    it('diferencia el historial vacío de un error', () => {
      responderCarga(crearDetalle(), []);

      expect(textoRaiz()).toContain('Sin transiciones registradas');
      expect(alertas()).toEqual([]);
    });

    it('diferencia los ítems vacíos', () => {
      const sinItems = crearDetalle();
      sinItems.detalles = [];
      responderCarga(sinItems);

      expect(textoRaiz()).toContain('Este ticket no tiene ítems registrados.');
    });

    it('muestra un error accesible (role="alert") ante un 404 y permite reintentar', () => {
      responderCarga(null);

      expect(componente.ticket()).toBeNull();
      expect(alertas().length).toBeGreaterThan(0);
      expect(alertas()[0]).toContain('Ticket no encontrado');

      // Reintento: vuelve a pedir las tres cosas y se recupera.
      boton('Reintentar')!.click();
      httpMock.expectOne(RUTA_DETALLE).flush(crearDetalle());
      httpMock.expectOne(RUTA_HISTORIAL).flush(crearHistorial());
      httpMock.expectOne(RUTA_CATALOGOS).flush(CATALOGOS_013);
      fixture.detectChanges();

      expect(componente.ticket()).not.toBeNull();
      expect(componente.errorCarga()).toBeNull();
    });
  });

  // ---------------------------------------------------------------------------
  // Barra de acciones por estado y rol (AC-24)
  // ---------------------------------------------------------------------------

  describe('acciones por estado y rol', () => {
    it('Administrador en Pendiente ve avanzar, editar, anular y rechazar (sin retroceder)', () => {
      responderCarga(crearDetalle(1));

      expect(botonesAccion()).toEqual([
        'Avanzar →',
        'Editar',
        'Rechazar',
        'Anular',
      ]);
    });

    it('Bodeguero en EnRevision ve avanzar, retroceder y rechazar; nunca anular ni editar', () => {
      identidad.set(crearIdentidad('Bodeguero'));
      responderCarga(crearDetalle(2));

      expect(botonesAccion()).toEqual(['← Retroceder', 'Avanzar →', 'Rechazar']);
    });

    it('Solicitante dueño en Pendiente solo ve anular y editar', () => {
      identidad.set(crearIdentidad('Solicitante', 5));
      responderCarga(crearDetalle(1));

      expect(botonesAccion()).toEqual(['Editar', 'Anular']);
    });

    it('Solicitante no dueño no ve anulación ni edición, y lo explica', () => {
      identidad.set(crearIdentidad('Solicitante', 99));
      responderCarga(crearDetalle(1));

      expect(botonesAccion()).toEqual([]);
      expect(textoRaiz()).toContain('Tu rol no puede operar el ciclo de vida');
    });

    it('EnCurso no ofrece avance (reservado al despacho) pero sí retroceso', () => {
      responderCarga(crearDetalle(3));

      expect(botonesAccion()).toEqual(['← Retroceder']);
    });

    it('Cerrado no ofrece ninguna acción y lo dice como estado terminal', () => {
      responderCarga(crearDetalle(4));

      expect(botonesAccion()).toEqual([]);
      expect(textoRaiz()).toContain('estado terminal');
    });

    it('Anulado no ofrece ninguna acción y lo dice como estado terminal', () => {
      responderCarga(crearDetalle(5));

      expect(botonesAccion()).toEqual([]);
      expect(textoRaiz()).toContain('estado terminal');
    });
  });

  // ---------------------------------------------------------------------------
  // Transiciones del flujo lineal (PATCH /estado)
  // ---------------------------------------------------------------------------

  describe('transiciones del flujo lineal', () => {
    it('avanza con PATCH /estado al estado destino y reconsulta detalle e historial', () => {
      responderCarga(crearDetalle(1));

      boton('Avanzar →')!.click();

      const cambio = httpMock.expectOne(RUTA_ESTADO);
      expect(cambio.request.method).toBe('PATCH');
      expect(cambio.request.body).toEqual({ estado_id: 2 });
      cambio.flush(crearDetalle(2));
      responderReconsulta();

      expect(alertas()).toEqual([]);
      expect(textoRaiz()).toContain('Estado del ticket actualizado.');
      expect(componente.enOperacion()).toBe(false);
    });

    it('retrocede con PATCH /estado al estado anterior', () => {
      identidad.set(crearIdentidad('Bodeguero'));
      responderCarga(crearDetalle(2));

      boton('← Retroceder')!.click();

      const cambio = httpMock.expectOne(RUTA_ESTADO);
      expect(cambio.request.body).toEqual({ estado_id: 1 });
      cambio.flush(crearDetalle(1));
      responderReconsulta(crearDetalle(1));
    });

    it('muestra el 409 del servidor en un role="alert" y reconsulta la verdad del backend', () => {
      responderCarga(crearDetalle(1));

      boton('Avanzar →')!.click();

      httpMock
        .expectOne(RUTA_ESTADO)
        .flush(
          { detail: 'El cambio de estado hacia Anulado no esta permitido' },
          { status: 409, statusText: 'Conflict' },
        );
      responderReconsulta();

      expect(alertas().length).toBeGreaterThan(0);
      expect(alertas()[0]).toContain('El cambio de estado hacia Anulado no esta permitido');
    });

    it('no permite doble envío mientras el cambio de estado está en vuelo', () => {
      responderCarga(crearDetalle(1));

      boton('Avanzar →')!.click();
      fixture.detectChanges();

      // El control queda deshabilitado y un segundo intento se descarta.
      expect(boton('Avanzar →')!.disabled).toBe(true);
      componente.avanzar();

      // Solo un PATCH: si el segundo intento hubiera pasado, habría dos.
      const cambio = httpMock.expectOne(RUTA_ESTADO);
      cambio.flush(crearDetalle(2));
      responderReconsulta();
      httpMock.expectNone(RUTA_ESTADO);
    });
  });

  // ---------------------------------------------------------------------------
  // Anulación y rechazo con motivo obligatorio (D-6, AC-24)
  // ---------------------------------------------------------------------------

  describe('anulación y rechazo', () => {
    it('la confirmación exige motivo: vacío o en blanco no envía nada', () => {
      responderCarga(crearDetalle(1));

      boton('Anular')!.click();
      fixture.detectChanges();
      expect(componente.confirmando()).toBe('anular');

      const dialogo = raiz.querySelectorAll('dialog')[0];
      dialogo.querySelector<HTMLButtonElement>('button[type="submit"]')!.click();
      fixture.detectChanges();

      httpMock.expectNone(RUTA_ANULACION);
      expect(componente.confirmando()).toBe('anular');
      expect(textoRaiz()).toContain('El motivo es obligatorio');

      // Un motivo de solo espacios tampoco sale del cliente.
      componente.motivoForm.controls.motivo.setValue('   ');
      dialogo.querySelector<HTMLButtonElement>('button[type="submit"]')!.click();
      httpMock.expectNone(RUTA_ANULACION);
    });

    it('anula con el motivo literal y reconsulta tras el éxito', () => {
      responderCarga(crearDetalle(1));

      boton('Anular')!.click();
      fixture.detectChanges();
      componente.motivoForm.controls.motivo.setValue('Ya no hace falta');
      raiz
        .querySelectorAll('dialog')[0]
        .querySelector<HTMLButtonElement>('button[type="submit"]')!
        .click();

      const peticion = httpMock.expectOne(RUTA_ANULACION);
      expect(peticion.request.method).toBe('POST');
      expect(peticion.request.body).toEqual({ motivo: 'Ya no hace falta' });
      peticion.flush(crearDetalle(5));
      responderReconsulta(crearDetalle(5));

      expect(componente.confirmando()).toBeNull();
      expect(textoRaiz()).toContain('Ticket anulado.');
    });

    it('un 422 del backend queda accesible en role="alert" y el modal sigue abierto', () => {
      responderCarga(crearDetalle(1));

      boton('Anular')!.click();
      fixture.detectChanges();
      componente.motivoForm.controls.motivo.setValue('Motivo');
      raiz
        .querySelectorAll('dialog')[0]
        .querySelector<HTMLButtonElement>('button[type="submit"]')!
        .click();

      httpMock
        .expectOne(RUTA_ANULACION)
        .flush({ detail: 'El motivo excede la longitud maxima' }, { status: 422, statusText: 'Unprocessable' });
      responderReconsulta();

      expect(componente.confirmando()).toBe('anular');
      expect(alertas().length).toBeGreaterThan(0);
      expect(alertas()[0]).toContain('El motivo excede la longitud maxima');
    });

    it('el Bodeguero rechaza vía POST /rechazo con su motivo', () => {
      identidad.set(crearIdentidad('Bodeguero'));
      responderCarga(crearDetalle(2));

      boton('Rechazar')!.click();
      fixture.detectChanges();
      componente.motivoForm.controls.motivo.setValue('Sin stock en la sede');
      raiz
        .querySelectorAll('dialog')[0]
        .querySelector<HTMLButtonElement>('button[type="submit"]')!
        .click();

      const peticion = httpMock.expectOne(RUTA_RECHAZO);
      expect(peticion.request.method).toBe('POST');
      expect(peticion.request.body).toEqual({ motivo: 'Sin stock en la sede' });
      peticion.flush(crearDetalle(5));
      responderReconsulta(crearDetalle(5));

      expect(textoRaiz()).toContain('Ticket rechazado.');
    });

    it('muestra el 409 del servidor al rechazar en un role="alert" y reconsulta', () => {
      identidad.set(crearIdentidad('Bodeguero'));
      responderCarga(crearDetalle(2));

      boton('Rechazar')!.click();
      fixture.detectChanges();
      componente.motivoForm.controls.motivo.setValue('Motivo válido');
      raiz
        .querySelectorAll('dialog')[0]
        .querySelector<HTMLButtonElement>('button[type="submit"]')!
        .click();

      httpMock
        .expectOne(RUTA_RECHAZO)
        .flush(
          { detail: 'El estado actual no admite el rechazo' },
          { status: 409, statusText: 'Conflict' },
        );
      responderReconsulta();

      expect(alertas().length).toBeGreaterThan(0);
      expect(alertas()[0]).toContain('El estado actual no admite el rechazo');
      // El modal permanece abierto para que el usuario corrija o cancele.
      expect(componente.confirmando()).toBe('rechazo');
      expect(componente.enOperacion()).toBe(false);
    });
  });

  // ---------------------------------------------------------------------------
  // Edición en Pendiente (PUT, D-9)
  // ---------------------------------------------------------------------------

  describe('edición en Pendiente', () => {
    it('abre el formulario precargado y envía PUT con la cabecera y los ítems completos', () => {
      responderCarga(crearDetalle(1));

      boton('Editar')!.click();
      fixture.detectChanges();
      expect(componente.editando()).toBe(true);

      componente.formularioEdicion.controls.asunto.setValue('Falta de papel y cartulina');
      const dialogo = raiz.querySelectorAll('dialog')[1];
      dialogo.querySelector<HTMLButtonElement>('button[type="submit"]')!.click();

      const peticion = httpMock.expectOne(RUTA_DETALLE);
      expect(peticion.request.method).toBe('PUT');
      expect(peticion.request.body).toEqual({
        asunto: 'Falta de papel y cartulina',
        descripcion: 'Se solicita papel oficio para impresiones.',
        prioridad_id: 1,
        detalles: [{ producto_id: 1, cantidad_solicitada: 3 }],
      });
      const editado = crearDetalle(1);
      editado.asunto = 'Falta de papel y cartulina';
      peticion.flush(editado);
      responderReconsulta(editado);

      expect(componente.editando()).toBe(false);
      expect(textoRaiz()).toContain('Ticket editado.');
    });

    it('un 409 del servidor (fuera de Pendiente) queda accesible en role="alert"', () => {
      responderCarga(crearDetalle(1));

      boton('Editar')!.click();
      fixture.detectChanges();
      raiz
        .querySelectorAll('dialog')[1]
        .querySelector<HTMLButtonElement>('button[type="submit"]')!
        .click();

      httpMock
        .expectOne(RUTA_DETALLE)
        .flush(
          { detail: 'Solo un ticket en Pendiente puede editarse' },
          { status: 409, statusText: 'Conflict' },
        );
      responderReconsulta();

      expect(alertas().length).toBeGreaterThan(0);
      expect(alertas()[0]).toContain('Solo un ticket en Pendiente puede editarse');
      expect(componente.editando()).toBe(true);
    });

    it('no envía la edición con el formulario inválido', () => {
      responderCarga(crearDetalle(1));

      boton('Editar')!.click();
      fixture.detectChanges();
      componente.formularioEdicion.controls.asunto.setValue('');
      componente.guardarEdicion();

      httpMock.expectNone(RUTA_DETALLE);
      expect(componente.editando()).toBe(true);
    });
  });
});
