import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, UrlTree, provideRouter } from '@angular/router';

import { URL_API } from '../../shared/config/url-api';
import { CatalogosTicket, Ticket } from '../../shared/interfaces';
import { TicketsComponent } from './tickets.component';

const RUTA_CATALOGOS = `${URL_API}/tickets/catalogos`;
const RUTA_TICKETS = `${URL_API}/tickets/`;
const RUTA_ESTADO = (id: number) => `${URL_API}/tickets/${id}/estado`;

/**
 * `estados` en el orden del flujo, no alfabeticamente: "Pendiente" (1),
 * "EnRevision" (2), "Cerrado" (4). El componente toma `estados[0]`, asi que si
 * el fixture no respeta ese orden los tests probarian otra cosa.
 */
const CATALOGOS: CatalogosTicket = {
  prioridades: [
    { prioridad_id: 1, nombre: 'Alta', descripcion: 'Corto plazo' },
    { prioridad_id: 2, nombre: 'Media', descripcion: 'Reposicion' },
  ],
  estados: [
    { estado_id: 1, nombre: 'Pendiente', descripcion: 'Sin revisar' },
    { estado_id: 2, nombre: 'EnRevision', descripcion: 'En revision' },
    { estado_id: 4, nombre: 'Cerrado', descripcion: 'Cerrado' },
  ],
  productos: [
    {
      producto_id: 1,
      nombre: 'Cuaderno linedado',
      unidad_medida: 'UNIDAD',
      categoria_nombre: 'Papeleria',
      stock_total: 50,
      es_critico: false,
    },
    {
      producto_id: 2,
      nombre: 'Toner HP 26A',
      unidad_medida: 'UNIDAD',
      categoria_nombre: 'Toner',
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
      departamento_nombre: 'Direccion',
    },
  ],
};

/**
 * Catalogo completo de la Feature 013 (D-1/D-2): los cuatro estados operativos
 * del flujo lineal mas el terminal `Anulado` al final, tal como lo siembra y
 * lo migra el backend. La columna del tablero y la exclusion del alta se
 * prueban contra este catalogo, nunca contra ids fijos.
 */
const CATALOGOS_013: CatalogosTicket = {
  ...CATALOGOS,
  estados: [
    { estado_id: 1, nombre: 'Pendiente', descripcion: 'Sin revisar' },
    { estado_id: 2, nombre: 'EnRevision', descripcion: 'En revision' },
    { estado_id: 3, nombre: 'EnCurso', descripcion: 'En preparacion' },
    { estado_id: 4, nombre: 'Cerrado', descripcion: 'Cerrado' },
    { estado_id: 5, nombre: 'Anulado', descripcion: 'Anulado o rechazado' },
  ],
};

// Fecha compartida por los tickets 3 y 4: ejercita el empate que se resuelve
// por `ticket_id` descendente. El ticket 4 ademas trae `fecha_cierre`.
const FECHA_EMPATE = '2026-10-02T10:00:00';
const FECHA_CIERRE = '2026-10-05T10:00:00';

/**
 * Fixture de tickets: cubre dos del mismo estado con fechas distintas (1 y 2),
 * dos del mismo estado con la **misma** fecha (3 y 4, empate), un estado sin
 * tickets (Cerrado, id 4) y uno con fecha de cierre no nula (el 4).
 */
const TICKETS: Ticket[] = [
  {
    ticket_id: 1,
    usuario_id: 5,
    prioridad_id: 1,
    estado_id: 1,
    asunto: 'Falta de papel',
    descripcion: 'Se solicita papel para el trimestre',
    fecha_creacion: '2026-10-01T10:00:00',
    fecha_cierre: null,
    detalles: [],
  },
  {
    ticket_id: 2,
    usuario_id: 1,
    prioridad_id: 2,
    estado_id: 1,
    asunto: 'Toner agotado',
    descripcion: null,
    fecha_creacion: '2026-10-03T10:00:00',
    fecha_cierre: null,
    detalles: [],
  },
  {
    ticket_id: 3,
    usuario_id: 5,
    prioridad_id: 1,
    estado_id: 2,
    asunto: 'Resma de papel',
    descripcion: null,
    fecha_creacion: FECHA_EMPATE,
    fecha_cierre: null,
    detalles: [],
  },
  {
    ticket_id: 4,
    usuario_id: 1,
    prioridad_id: 2,
    estado_id: 2,
    asunto: 'Grapas',
    descripcion: null,
    fecha_creacion: FECHA_EMPATE,
    fecha_cierre: FECHA_CIERRE,
    detalles: [],
  },
];

/**
 * Fixture de T11: la de T6 mas un ticket en cada **terminal** del catalogo 013
 * —cerrado (5, con `fecha_cierre`) y anulado (6, con `fecha_cierre` nula)—
 * para probar que ambas columnas pintan tarjetas y que toda tarjeta ofrece
 * «Gestionar» sin importar su estado.
 */
const TICKETS_013: Ticket[] = [
  ...TICKETS,
  {
    ticket_id: 5,
    usuario_id: 5,
    prioridad_id: 1,
    estado_id: 4,
    asunto: 'Ticket cerrado por despacho',
    descripcion: null,
    fecha_creacion: '2026-10-04T10:00:00',
    fecha_cierre: FECHA_CIERRE,
    detalles: [],
  },
  {
    ticket_id: 6,
    usuario_id: 1,
    prioridad_id: 2,
    estado_id: 5,
    asunto: 'Ticket anulado con motivo',
    descripcion: null,
    fecha_creacion: '2026-10-05T10:00:00',
    fecha_cierre: null,
    detalles: [],
  },
];

/**
 * Fixture de T7 (filtros): no deforma la de T6. Cubre
 * - dos prioridades (1 y 2),
 * - asuntos con acentos (`Reposición de tóner`) y sin ellos (`Reposicion de
 *   sillas`) para probar la busqueda insensible a mayusculas y acentos,
 * - `%` (ticket 3) y `_` (ticket 4) literales para probar que no son comodines,
 * - estados con mas de un ticket (Pendiente: 1, 2 y 6; EnRevision: 3, 4 y 5)
 *   para ver el contador bajar al filtrar.
 */
const TICKETS_FILTROS: Ticket[] = [
  {
    ticket_id: 1,
    usuario_id: 5,
    prioridad_id: 1,
    estado_id: 1,
    asunto: 'Reposición de tóner',
    descripcion: null,
    fecha_creacion: '2026-10-01T10:00:00',
    fecha_cierre: null,
    detalles: [],
  },
  {
    ticket_id: 2,
    usuario_id: 1,
    prioridad_id: 2,
    estado_id: 1,
    asunto: 'Compra de resmas',
    descripcion: null,
    fecha_creacion: '2026-10-02T10:00:00',
    fecha_cierre: null,
    detalles: [],
  },
  {
    ticket_id: 3,
    usuario_id: 5,
    prioridad_id: 1,
    estado_id: 2,
    asunto: 'Descuento del 50% en papel',
    descripcion: null,
    fecha_creacion: '2026-10-03T10:00:00',
    fecha_cierre: null,
    detalles: [],
  },
  {
    ticket_id: 4,
    usuario_id: 1,
    prioridad_id: 2,
    estado_id: 2,
    asunto: 'Guantes_de látex',
    descripcion: null,
    fecha_creacion: '2026-10-04T10:00:00',
    fecha_cierre: null,
    detalles: [],
  },
  {
    ticket_id: 5,
    usuario_id: 5,
    prioridad_id: 1,
    estado_id: 2,
    asunto: 'Reposicion de sillas',
    descripcion: null,
    fecha_creacion: '2026-10-05T10:00:00',
    fecha_cierre: null,
    detalles: [],
  },
  {
    ticket_id: 6,
    usuario_id: 1,
    prioridad_id: 2,
    estado_id: 1,
    asunto: 'Solicitud de papel',
    descripcion: null,
    fecha_creacion: '2026-10-06T10:00:00',
    fecha_cierre: null,
    detalles: [],
  },
];

/**
 * Respuesta completa de `POST /tickets/` (T9): el componente consume el
 * `Ticket` entero, no un `{ ticket_id }` parcial, asi que los tests del modal
 * tienen que responder con esta forma.
 */
function ticketRespuesta(ticket_id: number, estado_id = 1): Ticket {
  return {
    ticket_id,
    usuario_id: 5,
    prioridad_id: 1,
    estado_id,
    asunto: 'Falta de papel',
    descripcion: null,
    fecha_creacion: '2026-10-07T10:00:00',
    fecha_cierre: null,
    detalles: [],
  };
}

describe('TicketsComponent', () => {
  let fixture: ComponentFixture<TicketsComponent>;
  let componente: TicketsComponent;
  let httpMock: HttpTestingController;

  /** Responde las dos peticiones del arranque del tablero. */
  function responderArranque(
    catalogos: CatalogosTicket = CATALOGOS,
    tickets: Ticket[] = TICKETS
  ) {
    httpMock.expectOne(RUTA_CATALOGOS).flush(catalogos);
    httpMock.expectOne(RUTA_TICKETS).flush(tickets);
    fixture.detectChanges();
  }

  /**
   * Abre el modal con los catalogos ya cargados por el arranque del tablero,
   * asi `abrirModal()` no vuelve a pedirlos.
   */
  function abrirConCatalogos(catalogos: CatalogosTicket = CATALOGOS) {
    responderArranque(catalogos);
    componente.abrirModal();
    fixture.detectChanges();
  }

  /** Deja el formulario valido con un solo detalle. */
  function completarFormulario() {
    const formulario = componente.formulario;
    formulario.controls.usuario_id.setValue(5);
    formulario.controls.prioridad_id.setValue(1);
    formulario.controls.asunto.setValue('Falta de papel');
    componente.detalles.at(0).controls.producto_id.setValue(1);
    componente.detalles.at(0).controls.cantidad_solicitada.setValue(3);
  }

  beforeEach(async () => {
    // El tablero ya no condiciona su UI al rol (D-14: sin controles de
    // mutación que ocultar), asi que el TestBed no necesita el doble de
    // `AutenticacionService` que si usaba antes de la 013.
    await TestBed.configureTestingModule({
      imports: [TicketsComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(TicketsComponent);
    componente = fixture.componentInstance;
    fixture.detectChanges();
  });

  afterEach(() => {
    httpMock.verify({ ignoreCancelled: true });
  });

  describe('carga de catalogos', () => {
    it('debe cargar catalogos y tickets al construir el componente', () => {
      httpMock.expectOne(RUTA_CATALOGOS).flush(CATALOGOS);
      httpMock.expectOne(RUTA_TICKETS).flush(TICKETS);
      fixture.detectChanges();

      expect(componente.catalogos()).not.toBeNull();
      expect(componente.tickets().length).toBe(TICKETS.length);
      expect(componente.cargandoTablero()).toBe(false);
      expect(componente.errorTablero()).toBeNull();
    });

    it('no debe volver a pedir los catalogos al abrir el modal si ya estan cargados', () => {
      responderArranque();

      componente.abrirModal();
      fixture.detectChanges();

      httpMock.expectNone(RUTA_CATALOGOS);
      expect(componente.catalogos()).not.toBeNull();
    });

    it('debe exponer los cuatro catalogos como senales', () => {
      abrirConCatalogos();

      expect(componente.prioridades().length).toBe(2);
      expect(componente.estados().length).toBe(3);
      expect(componente.productos().length).toBe(2);
      expect(componente.solicitantes().length).toBe(2);
    });

    it('debe arrancar el estado en el primero del flujo, no en el alfabetico', () => {
      abrirConCatalogos();

      expect(componente.estadoInicial()).toBe(1);
      expect(componente.formulario.controls.estado_id.value).toBe(1);
    });

    it('debe exponer el error del tablero si falla el arranque', () => {
      httpMock
        .expectOne(RUTA_CATALOGOS)
        .flush('Falla', { status: 500, statusText: 'Server Error' });
      fixture.detectChanges();

      expect(componente.errorTablero()).toBeTruthy();
      expect(componente.errorGuardado()).toBeNull();
      expect(componente.cargandoTablero()).toBe(false);
    });

    it('debe exponer errorCatalogos al abrir el modal si el catalogo no se cargo', () => {
      httpMock
        .expectOne(RUTA_CATALOGOS)
        .flush('Falla', { status: 500, statusText: 'Server Error' });
      fixture.detectChanges();

      componente.abrirModal();
      httpMock
        .expectOne(RUTA_CATALOGOS)
        .flush('Falla', { status: 500, statusText: 'Server Error' });
      fixture.detectChanges();

      expect(componente.errorCatalogos()).toBeTruthy();
    });

    it('no debe pedir catalogos al reabrir el modal con catalogos cargados', () => {
      abrirConCatalogos();
      componente.cerrarModal();

      componente.abrirModal();
      fixture.detectChanges();

      httpMock.expectNone(RUTA_CATALOGOS);
      expect(componente.errorCatalogos()).toBeNull();
      expect(componente.cargandoCatalogos()).toBe(false);
    });
  });

  describe('detalles', () => {
    beforeEach(() => abrirConCatalogos());

    it('debe partir con una fila de detalle', () => {
      expect(componente.detalles.length).toBe(1);
    });

    it('debe agregar y quitar filas', () => {
      componente.agregarDetalle();
      expect(componente.detalles.length).toBe(2);

      componente.quitarDetalle(1);
      expect(componente.detalles.length).toBe(1);
    });

    it('no debe permitir quitar la ultima fila', () => {
      expect(componente.puedeQuitarDetalle()).toBe(false);
      componente.quitarDetalle(0);
      expect(componente.detalles.length).toBe(1);
    });

    it('debe sumar las cantidades de un producto repetido', () => {
      componente.agregarDetalle();
      componente.detalles.at(0).controls.producto_id.setValue(1);
      componente.detalles.at(0).controls.cantidad_solicitada.setValue(2);
      componente.detalles.at(1).controls.producto_id.setValue(1);
      componente.detalles.at(1).controls.cantidad_solicitada.setValue(5);

      expect(componente.combinarDetalles()).toEqual([
        { producto_id: 1, cantidad_solicitada: 7 },
      ]);
    });

    it('debe conservar productos distintos como lineas separadas', () => {
      componente.agregarDetalle();
      componente.detalles.at(0).controls.producto_id.setValue(1);
      componente.detalles.at(0).controls.cantidad_solicitada.setValue(2);
      componente.detalles.at(1).controls.producto_id.setValue(2);
      componente.detalles.at(1).controls.cantidad_solicitada.setValue(1);

      expect(componente.combinarDetalles()).toEqual([
        { producto_id: 1, cantidad_solicitada: 2 },
        { producto_id: 2, cantidad_solicitada: 1 },
      ]);
    });
  });

  describe('validacion del formulario', () => {
    beforeEach(() => abrirConCatalogos());

    it('no debe enviar si el formulario es invalido', () => {
      componente.enviar();

      const pendientes = httpMock.match(RUTA_TICKETS);
      expect(pendientes.length).toBe(0);
    });

    it('debe marcar los controles como tocados al intentar enviar', () => {
      componente.enviar();

      expect(componente.formulario.controls.asunto.touched).toBe(true);
    });

    it('debe rechazar un asunto de menos de 3 caracteres', () => {
      completarFormulario();
      componente.formulario.controls.asunto.setValue('ab');

      expect(componente.formulario.invalid).toBe(true);
    });

    it('debe rechazar un asunto de mas de 150 caracteres', () => {
      completarFormulario();
      componente.formulario.controls.asunto.setValue('x'.repeat(151));

      expect(componente.formulario.invalid).toBe(true);
    });

    it('debe aceptar un asunto de exactamente 150 caracteres', () => {
      completarFormulario();
      componente.formulario.controls.asunto.setValue('x'.repeat(150));

      expect(componente.formulario.valid).toBe(true);
    });

    it('debe rechazar una cantidad de 0', () => {
      completarFormulario();
      componente.detalles.at(0).controls.cantidad_solicitada.setValue(0);

      expect(componente.formulario.invalid).toBe(true);
    });
  });

  describe('envio', () => {
    beforeEach(() => abrirConCatalogos());

    it('debe enviar el ticket y avisar el id creado', () => {
      completarFormulario();
      componente.enviar();

      const peticion = httpMock.expectOne(RUTA_TICKETS);
      expect(peticion.request.method).toBe('POST');
      expect(peticion.request.body).toEqual({
        usuario_id: 5,
        prioridad_id: 1,
        estado_id: 1,
        asunto: 'Falta de papel',
        descripcion: null,
        detalles: [{ producto_id: 1, cantidad_solicitada: 3 }],
      });

      peticion.flush(ticketRespuesta(42));
      fixture.detectChanges();

      expect(componente.ticketCreado()).toBe(42);
      expect(componente.modalAbierto()).toBe(false);
    });

    it('debe enviar las cantidades ya sumadas', () => {
      completarFormulario();
      componente.agregarDetalle();
      componente.detalles.at(1).controls.producto_id.setValue(1);
      componente.detalles.at(1).controls.cantidad_solicitada.setValue(4);
      componente.enviar();

      const cuerpo = httpMock.expectOne(RUTA_TICKETS).request.body;
      expect(cuerpo.detalles).toEqual([{ producto_id: 1, cantidad_solicitada: 7 }]);
    });

    it('debe limpiar el formulario tras un envio correcto', () => {
      completarFormulario();
      componente.enviar();
      httpMock.expectOne(RUTA_TICKETS).flush(ticketRespuesta(42));

      expect(componente.formulario.controls.asunto.value).toBe('');
      expect(componente.detalles.length).toBe(1);
    });

    it('no debe permitir el doble envio', () => {
      completarFormulario();
      componente.enviar();

      expect(componente.guardando()).toBe(true);

      componente.enviar();

      // `expectOne` lanza si hay **mas de una** peticion pendiente, asi que esta
      // linea es la que verifica que el segundo `enviar()` no salio. (Un `match`
      // no serviria: ademas de permitir duplicados, `expectOne` ya retiro la
      // primera peticion del backend de pruebas.)
      httpMock.expectOne(RUTA_TICKETS).flush(ticketRespuesta(42));
    });

    it('debe deshabilitar el envio mientras guarda', () => {
      completarFormulario();
      componente.enviar();
      const peticion = httpMock.expectOne(RUTA_TICKETS);

      expect(componente.guardando()).toBe(true);

      peticion.flush(ticketRespuesta(42));
      expect(componente.guardando()).toBe(false);
    });

    it('debe dejar el modal abierto y mostrar el error si el backend falla', () => {
      completarFormulario();
      componente.enviar();
      httpMock
        .expectOne(RUTA_TICKETS)
        .flush({ detail: 'No existe producto indicado: 99' }, { status: 404, statusText: 'Not Found' });
      fixture.detectChanges();

      expect(componente.modalAbierto()).toBe(true);
      expect(componente.errorGuardado()).toContain('No existe producto');
      expect(componente.ticketCreado()).toBeNull();
    });

    it('debe mapear un 422 por campo a su mensaje traducido', () => {
      // El formulario se envia **valido** a proposito: si estuviera invalido,
      // `enviar()` lo cortaria antes del POST y no habria nada que mapear. Lo
      // que se prueba aqui es la traduccion de un 422 que llega del servidor,
      // por ejemplo si las reglas del backend cambiasen antes que el espejo del
      // cliente.
      completarFormulario();
      componente.enviar();

      httpMock.expectOne(RUTA_TICKETS).flush(
        {
          detail: [
            {
              loc: ['body', 'asunto'],
              msg: 'String should have at most 150 characters',
              type: 'string_too_long',
            },
          ],
        },
        { status: 422, statusText: 'Unprocessable Entity' }
      );
      fixture.detectChanges();

      expect(componente.mensajeDe('asunto')).toBe('No puede superar los 150 caracteres.');
    });

    it('debe ubicar un 422 de detalle en su fila', () => {
      completarFormulario();
      // Ambas filas quedan validas en el cliente; el 422 simula que el servidor
      // rechazo la segunda fila. Se omite `agregarDetalle()` y se usa la fila
      // unica con indice 0 a proposito: al combinar, dos filas del **mismo**
      // producto se funden en una, asi que un `loc` con indice 1 solo es
      // reproducible si hay dos filas de productos distintos.
      componente.agregarDetalle();
      componente.detalles.at(1).controls.producto_id.setValue(2);
      componente.detalles.at(1).controls.cantidad_solicitada.setValue(2);
      componente.enviar();

      httpMock.expectOne(RUTA_TICKETS).flush(
        {
          detail: [
            {
              loc: ['body', 'detalles', 1, 'cantidad_solicitada'],
              msg: 'Input should be greater than 0',
              type: 'greater_than',
            },
          ],
        },
        { status: 422, statusText: 'Unprocessable Entity' }
      );
      fixture.detectChanges();

      expect(componente.mensajeDeDetalle(1)).toBe('La cantidad debe ser mayor que 0.');
      expect(componente.mensajeDeDetalle(0)).toBeNull();
    });
  });

  describe('cierre del modal', () => {
    beforeEach(() => abrirConCatalogos());

    it('debe cerrar el modal al cancelar', () => {
      componente.cerrarModal();

      expect(componente.modalAbierto()).toBe(false);
    });

    it('debe abrir el dialogo nativo en el DOM', () => {
      // `showModal()` no existe en el DOM de prueba si el `@if` no renderizo el
      // elemento; verificar `open` confirma que el `effect` llego a ejecutarlo.
      expect(componente.dialogo().nativeElement.open).toBe(true);
    });
  });

  describe('tablero Kanban', () => {
    it('debe mostrar una columna por estado del catalogo, en orden, incluidas las vacias', () => {
      responderArranque();

      const columnas = componente.columnas();
      expect(columnas.length).toBe(3);
      expect(columnas.map((columna) => columna.estado_id)).toEqual([1, 2, 4]);
      expect(columnas.map((columna) => columna.estado)).toEqual([
        'Pendiente',
        'EnRevision',
        'Cerrado',
      ]);

      const vacia = columnas.find((columna) => columna.estado_id === 4);
      expect(vacia?.tarjetas.length).toBe(0);
    });

    it('debe agrupar cada ticket en la columna de su estado', () => {
      responderArranque();

      const columnas = componente.columnas();
      const pendiente = columnas.find((columna) => columna.estado_id === 1)!;
      const enRevision = columnas.find((columna) => columna.estado_id === 2)!;

      expect(pendiente.tarjetas.map((tarjeta) => tarjeta.ticket.ticket_id).sort()).toEqual([1, 2]);
      expect(enRevision.tarjetas.map((tarjeta) => tarjeta.ticket.ticket_id).sort()).toEqual([
        3, 4,
      ]);
    });

    it('debe ordenar por fecha de creacion DESC y, en empate, por ticket_id DESC', () => {
      responderArranque();

      const columnas = componente.columnas();

      // Estado 1: fechas distintas -> el 2 (03-10) va antes que el 1 (01-10).
      const pendiente = columnas.find((columna) => columna.estado_id === 1)!;
      expect(pendiente.tarjetas.map((tarjeta) => tarjeta.ticket.ticket_id)).toEqual([2, 1]);

      // Estado 2: misma fecha -> desempata por ticket_id descendente -> 4 antes que 3.
      const enRevision = columnas.find((columna) => columna.estado_id === 2)!;
      expect(enRevision.tarjetas.map((tarjeta) => tarjeta.ticket.ticket_id)).toEqual([4, 3]);
    });

    it('debe resolver asunto, prioridad, solicitante y fechas en la tarjeta', () => {
      responderArranque();

      const tarjetas = componente
        .columnas()
        .flatMap((columna) => columna.tarjetas);

      const conCierre = tarjetas.find((tarjeta) => tarjeta.ticket.ticket_id === 4)!;
      expect(conCierre.asunto).toBe('Grapas');
      expect(conCierre.prioridad).toBe('Media');
      expect(conCierre.clasePrioridad).toContain('bg-');
      expect(conCierre.solicitante).toBe('Fernandez, Camila · Direccion');
      expect(conCierre.fechaCreacion).toBe(FECHA_EMPATE);
      expect(conCierre.fechaCierre).toBe(FECHA_CIERRE);

      const sinCierre = tarjetas.find((tarjeta) => tarjeta.ticket.ticket_id === 1)!;
      expect(sinCierre.asunto).toBe('Falta de papel');
      expect(sinCierre.prioridad).toBe('Alta');
      expect(sinCierre.solicitante).toBe('Contreras, Isabel · Docencia');
      expect(sinCierre.fechaCreacion).toBe('2026-10-01T10:00:00');
      expect(sinCierre.fechaCierre).toBeNull();
    });

    it('debe tratar un catalogo de estados vacio como error visible', () => {
      responderArranque({ ...CATALOGOS, estados: [] });

      expect(componente.cargandoTablero()).toBe(false);
      expect(componente.errorTablero()).toBeTruthy();
      expect(componente.columnas().length).toBe(0);
    });
  });

  /**
   * D-14 / AC-24 (013): el tablero es de solo lectura. Deroganse en la capa de
   * UI los AC-9, AC-10, AC-12, AC-19 y AC-20 de la 004 (transiciones por
   * botón en el tablero y su feedback): la unica accion por tarjeta es
   * «Gestionar», que abre la vista de detalle, donde vive todo el ciclo de
   * vida. Aqui se verifica tanto el comportamiento nuevo como la **ausencia**
   * de la logica de transiciones que la 004 exibia.
   */
  describe('tablero de solo lectura (D-14, AC-24)', () => {
    /** Busca una tarjeta por el id de su ticket, aplanando las columnas. */
    function tarjetaDe(ticketId: number) {
      return componente
        .columnas()
        .flatMap((columna) => columna.tarjetas)
        .find((tarjeta) => tarjeta.ticket.ticket_id === ticketId);
    }

    /** Los enlaces «Gestionar» que el DOM pinta, uno por tarjeta. */
    function enlacesGestionar() {
      return fixture.nativeElement.querySelectorAll(
        'a[aria-label^="Gestionar ticket #"]'
      ) as NodeListOf<HTMLAnchorElement>;
    }

    beforeEach(() => responderArranque(CATALOGOS_013, TICKETS_013));

    it('ofrece exactamente una acción «Gestionar» por tarjeta, sin controles de transición', () => {
      // Una por tarjeta, sin importar su estado.
      expect(enlacesGestionar().length).toBe(TICKETS_013.length);

      // Ni botones de avanzar/retroceder ni su texto en el tablero.
      expect(
        fixture.nativeElement.querySelector('button[aria-label^="Avanzar ticket"]')
      ).toBeNull();
      expect(
        fixture.nativeElement.querySelector('button[aria-label^="Retroceder ticket"]')
      ).toBeNull();
      const texto = fixture.nativeElement.textContent ?? '';
      expect(texto).not.toContain('Avanzar');
      expect(texto).not.toContain('Retroceder');

      // Ningún `PATCH /estado` sale del tablero: la única red del arranque fue
      // catálogos + lista.
      httpMock.expectNone(RUTA_ESTADO(1));
      httpMock.expectNone(RUTA_ESTADO(6));
    });

    it('ofrece «Gestionar» también en la columna terminal y en la de Anulado', () => {
      expect(tarjetaDe(5)).toBeTruthy(); // Cerrado (terminal)
      expect(tarjetaDe(6)).toBeTruthy(); // Anulado (terminal)

      expect(
        fixture.nativeElement.querySelector('a[aria-label="Gestionar ticket #5"]')
      ).not.toBeNull();
      expect(
        fixture.nativeElement.querySelector('a[aria-label="Gestionar ticket #6"]')
      ).not.toBeNull();
    });

    it('no conserva lógica de transición en el componente ni en la tarjeta (sin código muerto)', () => {
      // Nada de la UI de movimientos de la 004 sobrevive en la clase.
      for (const nombre of [
        'mover',
        'moverSiguiente',
        'moverAnterior',
        'errorMovimiento',
        'enProceso',
        'puedeGestionarKanban',
        'idEstadoEnCurso',
      ]) {
        expect(nombre in componente).withContext(nombre).toBe(false);
      }

      // Ni en la tarjeta, que ya no resuelve controles de mutación.
      const tarjeta = tarjetaDe(1)!;
      for (const nombre of [
        'puedeAvanzar',
        'puedeRetroceder',
        'estadoSiguienteId',
        'estadoAnteriorId',
        'enProceso',
      ]) {
        expect(nombre in tarjeta).withContext(nombre).toBe(false);
      }
    });

    it('la acción «Gestionar» navega a la ruta de detalle del ticket', () => {
      const router = TestBed.inject(Router);
      const navegacion = spyOn(router, 'navigateByUrl').and.returnValue(
        Promise.resolve(true)
      );

      const enlace = fixture.nativeElement.querySelector(
        'a[aria-label="Gestionar ticket #1"]'
      ) as HTMLAnchorElement;
      expect(enlace).not.toBeNull();
      // La ruta hija `tickets/:ticketId` del T10.
      expect(enlace.getAttribute('href')).toBe('/tickets/1');

      enlace.click();

      // El click entra al Router (no a una navegación del navegador) y su
      // destino es la ruta de detalle del ticket.
      expect(navegacion).toHaveBeenCalledTimes(1);
      const destino = navegacion.calls.mostRecent().args[0] as UrlTree;
      expect(router.serializeUrl(destino)).toBe('/tickets/1');
      // La navegación no consulta nada: el detalle carga en su propio componente.
      expect(httpMock.match(() => true).length).toBe(0);
    });

    it('no pinta el banner de «solo consulta» de la 004 (derogado con D-14)', () => {
      // El tablero ya no muta para nadie: no hay UI condicionada al rol que
      // avisar ni controles que ocultar.
      expect(fixture.nativeElement.textContent).not.toContain('Vista de solo consulta');
      expect('rolActual' in componente).toBe(false);
    });

    it('hace exactamente dos peticiones al arranque y ninguna por tarjeta (sin N+1)', () => {
      // `responderArranque` ya descargo catálogos y lista: el render de cinco
      // columnas con seis tarjetas no añade peticiones…
      expect(enlacesGestionar().length).toBe(TICKETS_013.length);

      // …ni los filtros, que son de cliente sobre el conjunto cargado…
      componente.cambiarPrioridad('1');
      fixture.detectChanges();
      componente.actualizarBusqueda('papel');
      fixture.detectChanges();

      // …ni la navegación al detalle.
      (fixture.nativeElement.querySelector(
        'a[aria-label="Gestionar ticket #3"]'
      ) as HTMLAnchorElement).click();
      fixture.detectChanges();

      expect(httpMock.match(() => true).length).toBe(0);
    });
  });

  /**
   * D-1 / D-14 (013): el tablero añade la columna `Anulado`; no hay ids fijos,
   * la columna surge del catálogo igual que las demás.
   */
  describe('columna Anulado (D-1/D-14)', () => {
    it('surge del catálogo junto a las demás, con sus tarjetas', () => {
      responderArranque(CATALOGOS_013, TICKETS_013);

      const columnas = componente.columnas();
      expect(columnas.map((columna) => columna.estado_id)).toEqual([1, 2, 3, 4, 5]);

      const anulado = columnas.find((columna) => columna.estado === 'Anulado')!;
      expect(anulado.estado_id).toBe(5);
      expect(anulado.tarjetas.map((tarjeta) => tarjeta.ticket.ticket_id)).toEqual([6]);
    });

    it('un ticket anulado queda solo en la columna de Anulado', () => {
      responderArranque(CATALOGOS_013, TICKETS_013);

      const conElTicket = componente
        .columnas()
        .filter((columna) =>
          columna.tarjetas.some((tarjeta) => tarjeta.ticket.ticket_id === 6)
        );

      expect(conElTicket.length).toBe(1);
      expect(conElTicket[0].estado).toBe('Anulado');
      // `fecha_cierre` nula en el anulado (D-5): la tarjeta no pinta cierre.
      expect(conElTicket[0].tarjetas[0].fechaCierre).toBeNull();
    });
  });

  /**
   * D-11 (013): un ticket nuevo no puede nacer en `Anulado`. El backend ya
   * responde 409; el modal espeja esa regla excluyendo `Anulado` de la
   * elección de estado inicial, resuelto por nombre (como el resto del
   * catalogo), sin ids fijos.
   */
  describe('alta sin Anulado como estado inicial (D-11)', () => {
    it('excluye Anulado de la elección de estado inicial', () => {
      abrirConCatalogos(CATALOGOS_013);

      expect(componente.estadosAlta().map((estado) => estado.nombre)).toEqual([
        'Pendiente',
        'EnRevision',
        'EnCurso',
        'Cerrado',
      ]);
      expect(componente.estadoInicial()).toBe(1);
      expect(componente.formulario.controls.estado_id.value).toBe(1);
    });

    it('el desplegable del modal no ofrece Anulado', () => {
      abrirConCatalogos(CATALOGOS_013);

      const opciones = fixture.nativeElement.querySelectorAll(
        'dialog select[formcontrolname="estado_id"] option'
      );
      expect(opciones.length).toBe(4);
      const textos = [...opciones].map((opcion) => (opcion as HTMLOptionElement).textContent?.trim());
      expect(textos).not.toContain('Anulado');
    });

    it('resuelve la exclusión por nombre canónico, no por posición ni id', () => {
      // Catálogo degenerado: `anulado` en minúsculas y **primero** del arreglo.
      // La exclusión es por nombre normalizado, asi que el estado inicial sigue
      // siendo el primer operativo del flujo (Pendiente, id 1).
      const catalogoAnuladoPrimero: CatalogosTicket = {
        ...CATALOGOS_013,
        estados: [
          { estado_id: 9, nombre: 'anulado', descripcion: 'Minuscula y primero' },
          ...CATALOGOS_013.estados.filter((estado) => estado.nombre !== 'Anulado'),
        ],
      };
      abrirConCatalogos(catalogoAnuladoPrimero);

      expect(componente.estadosAlta().map((estado) => estado.estado_id)).toEqual([
        1, 2, 3, 4,
      ]);
      expect(componente.estadoInicial()).toBe(1);
    });
  });

  describe('filtros del tablero', () => {
    /** Todos los tickets que el tablero pinta, aplanando las columnas. */
    function tarjetasVisibles() {
      return componente.columnas().flatMap((columna) => columna.tarjetas);
    }

    beforeEach(() => responderArranque(CATALOGOS, TICKETS_FILTROS));

    it('debe arrancar en "todas" y filtrar por prioridad (AC-6)', () => {
      expect(componente.filtroPrioridad()).toBeNull();
      expect(tarjetasVisibles().length).toBe(TICKETS_FILTROS.length);

      componente.cambiarPrioridad('1');
      fixture.detectChanges();

      expect(componente.filtroPrioridad()).toBe(1);
      const visibles = tarjetasVisibles();
      expect(visibles.length).toBe(3);
      expect(visibles.every((tarjeta) => tarjeta.ticket.prioridad_id === 1)).toBe(true);

      componente.cambiarPrioridad('');
      fixture.detectChanges();

      expect(componente.filtroPrioridad()).toBeNull();
      expect(tarjetasVisibles().length).toBe(TICKETS_FILTROS.length);
    });

    it('debe contar las tarjetas despues de filtrar, no el total cargado (AC-3)', () => {
      componente.cambiarPrioridad('2');
      fixture.detectChanges();

      const columnaPendiente = componente.columnas().find((c) => c.estado_id === 1)!;
      const columnaRevision = componente.columnas().find((c) => c.estado_id === 2)!;

      // Cargados: Pendiente 3 y EnRevision 3. Filtrados por prioridad 2: 2 y 1.
      expect(columnaPendiente.tarjetas.length).toBe(2);
      expect(columnaRevision.tarjetas.length).toBe(1);

      const suma = componente
        .columnas()
        .reduce((total, columna) => total + columna.tarjetas.length, 0);
      expect(suma).toBe(3);
      expect(suma).toBeLessThan(TICKETS_FILTROS.length);
    });

    it('debe buscar sin distinguir mayusculas ni acentos (AC-7)', () => {
      componente.busqueda.set('reposicion');
      fixture.detectChanges();
      expect(
        tarjetasVisibles()
          .map((tarjeta) => tarjeta.ticket.ticket_id)
          .sort()
      ).toEqual([1, 5]);

      // Con el acento en la consulta tambien encuentra.
      componente.busqueda.set('REPOSICIÓN');
      fixture.detectChanges();
      expect(
        tarjetasVisibles()
          .map((tarjeta) => tarjeta.ticket.ticket_id)
          .sort()
      ).toEqual([1, 5]);

      componente.busqueda.set('TÓNER');
      fixture.detectChanges();
      expect(
        tarjetasVisibles().map((tarjeta) => tarjeta.ticket.ticket_id)
      ).toEqual([1]);
    });

    it('debe tratar "%" y "_" como texto literal, no comodines (AC-7)', () => {
      componente.busqueda.set('%');
      fixture.detectChanges();
      expect(
        tarjetasVisibles().map((tarjeta) => tarjeta.ticket.ticket_id)
      ).toEqual([3]);

      componente.busqueda.set('_');
      fixture.detectChanges();
      expect(
        tarjetasVisibles().map((tarjeta) => tarjeta.ticket.ticket_id)
      ).toEqual([4]);
    });

    it('debe ignorar una busqueda vacia o de solo espacios (AC-7)', () => {
      componente.busqueda.set('papel');
      fixture.detectChanges();
      expect(tarjetasVisibles().length).toBe(2);

      componente.actualizarBusqueda('   ');
      fixture.detectChanges();

      expect(componente.hayFiltros()).toBe(false);
      expect(tarjetasVisibles().length).toBe(TICKETS_FILTROS.length);
    });

    it('debe combinar prioridad y busqueda en interseccion (AC-7, D-6)', () => {
      componente.busqueda.set('papel');
      fixture.detectChanges();
      // Sin prioridad: el ticket 3 (prioridad 1) y el 6 (prioridad 2).
      expect(
        tarjetasVisibles()
          .map((tarjeta) => tarjeta.ticket.ticket_id)
          .sort()
      ).toEqual([3, 6]);

      componente.filtroPrioridad.set(1);
      fixture.detectChanges();
      expect(
        tarjetasVisibles().map((tarjeta) => tarjeta.ticket.ticket_id)
      ).toEqual([3]);
    });

    it('debe diferenciar el vacio por filtros del vacio normal (AC-5)', () => {
      // Sin filtros: la columna Cerrado (id 4) esta vacia.
      expect(componente.hayFiltros()).toBe(false);
      expect(fixture.nativeElement.textContent).toContain('Sin tickets en esta columna');

      componente.busqueda.set('zzzz');
      fixture.detectChanges();

      expect(componente.errorTablero()).toBeNull();
      expect(componente.hayFiltros()).toBe(true);
      expect(tarjetasVisibles().length).toBe(0);
      expect(fixture.nativeElement.textContent).toContain(
        'Ningún ticket coincide con los filtros'
      );
    });
  });

  describe('alta reflejada en el tablero', () => {
    /** Busca una tarjeta por el id de su ticket, aplanando las columnas. */
    function tarjetaDe(ticketId: number) {
      return componente
        .columnas()
        .flatMap((columna) => columna.tarjetas)
        .find((tarjeta) => tarjeta.ticket.ticket_id === ticketId);
    }

    /** La columna de un estado del catalogo. */
    function columna(estadoId: number) {
      return componente.columnas().find((c) => c.estado_id === estadoId)!;
    }

    it('el ticket creado aparece en el tablero sin recargar', () => {
      abrirConCatalogos();

      completarFormulario();
      componente.enviar();

      httpMock.expectOne(RUTA_TICKETS).flush(ticketRespuesta(42));
      fixture.detectChanges();

      expect(componente.ticketCreado()).toBe(42);
      expect(componente.tickets().some((t) => t.ticket_id === 42)).toBe(true);
      expect(tarjetaDe(42)).toBeTruthy();
      expect(columna(1).tarjetas.some((t) => t.ticket.ticket_id === 42)).toBe(true);
      // Sin reconsulta: el alta se refleja con la respuesta del POST.
      httpMock.expectNone(RUTA_TICKETS);
    });

    it('el ticket creado no aparece si los filtros no lo admiten (D-6)', () => {
      abrirConCatalogos();

      componente.cambiarPrioridad('2');
      fixture.detectChanges();

      completarFormulario();
      componente.enviar();

      httpMock.expectOne(RUTA_TICKETS).flush(ticketRespuesta(42, 1));
      fixture.detectChanges();

      // Esta cargado en el conjunto...
      expect(componente.tickets().some((t) => t.ticket_id === 42)).toBe(true);
      // ...pero el filtro de prioridad 2 lo excluye de todas las columnas.
      expect(tarjetaDe(42)).toBeUndefined();
      expect(
        componente.columnas().some((columna) =>
          columna.tarjetas.some((t) => t.ticket.ticket_id === 42)
        )
      ).toBe(false);
    });
  });

  /**
   * AC-19: la vista de una institución presenta exactamente el catálogo, el
   * stock y los tickets que el servidor devolvió para su ámbito. El servidor ya
   * aísla (T7); el cliente no agrega ni recombina datos de otra institución, y
   * tampoco elige el ámbito: no lo envía.
   */
  describe('aislamiento institucional en la vista (AC-19)', () => {
    /** Catálogo de INST-A: homónimo con id y stock propios, sin nada de INST-B. */
    const CATALOGOS_A: CatalogosTicket = {
      ...CATALOGOS,
      productos: [
        {
          producto_id: 101,
          nombre: 'Resma Carta 75g',
          unidad_medida: 'RESMA',
          categoria_nombre: 'Papeleria',
          stock_total: 120,
          es_critico: false,
        },
      ],
    };

    /** Tickets de INST-A: solo su ámbito, sin tickets de INST-B. */
    const TICKETS_A: Ticket[] = [
      {
        ticket_id: 301,
        usuario_id: 5,
        prioridad_id: 1,
        estado_id: 1,
        asunto: 'Reposición de resma (INST-A)',
        descripcion: null,
        fecha_creacion: '2026-10-01T10:00:00',
        fecha_cierre: null,
        detalles: [],
      },
    ];

    function tarjetasVisibles() {
      return componente.columnas().flatMap((columna) => columna.tarjetas);
    }

    it('presenta solo el catálogo, el stock y los tickets del ámbito recibido', () => {
      responderArranque(CATALOGOS_A, TICKETS_A);

      expect(componente.tickets()).toEqual(TICKETS_A);
      expect(componente.productos()).toEqual(CATALOGOS_A.productos);
      // El stock mostrado es el de INST-A (120), no el de un homónimo de INST-B.
      expect(componente.productos()[0].stock_total).toBe(120);

      const texto = fixture.nativeElement.textContent ?? '';
      expect(texto).toContain('INST-A');
      // Ningún dato de INST-B aparece, ni tickets ni productos homónimos.
      expect(texto).not.toContain('INST-B');
      expect(tarjetasVisibles().map((tarjeta) => tarjeta.ticket.ticket_id)).toEqual([301]);
    });

    it('no pide institución ni parámetros de ámbito: el filtro es del servidor', () => {
      const peticiones = {
        catalogos: httpMock.expectOne(RUTA_CATALOGOS),
        tickets: httpMock.expectOne(RUTA_TICKETS),
      };
      peticiones.catalogos.flush(CATALOGOS_A);
      peticiones.tickets.flush(TICKETS_A);
      fixture.detectChanges();

      for (const peticion of [peticiones.catalogos, peticiones.tickets]) {
        expect(peticion.request.method).toBe('GET');
        expect(peticion.request.params.has('institucion_id')).toBe(false);
        expect(peticion.request.headers.get('X-Institucion-Id')).toBeNull();
      }
    });

    it('el alta de ticket no reenvía la institución como autorización', () => {
      abrirConCatalogos(CATALOGOS_A);

      completarFormulario();
      componente.enviar();

      const peticion = httpMock.expectOne(RUTA_TICKETS);
      expect(peticion.request.method).toBe('POST');
      const cuerpo = peticion.request.body as Record<string, unknown>;
      expect('institucion_id' in cuerpo).toBe(false);
      expect('usuario_id' in cuerpo).toBe(true);

      peticion.flush(ticketRespuesta(500));
    });
  });
});
