import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { WritableSignal, signal } from '@angular/core';

import { URL_API } from '../../shared/config/url-api';
import { AutenticacionService } from '../../core/services/auth.service';
import { CatalogosTicket, IdentidadAutenticada, Ticket } from '../../shared/interfaces';
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
 * Fixture de T8 (transiciones): la de T6/T7 mas un ticket en el estado
 * **terminal** (Cerrado, id 4), que la de T6 deja a proposito vacio. Asi AC-11
 * se prueba sin alterar los conteos que T6/T7 ya verifican.
 */
const TICKETS_TRANSICION: Ticket[] = [
  ...TICKETS,
  {
    ticket_id: 5,
    usuario_id: 5,
    prioridad_id: 1,
    estado_id: 4,
    asunto: 'Ticket terminal',
    descripcion: null,
    fecha_creacion: '2026-10-04T10:00:00',
    fecha_cierre: '2026-10-05T10:00:00',
    detalles: [],
  },
];

/**
 * Fixture de T10 (Feature 005): catalogo con `EnCurso` (3) y `Cerrado` (4), el
 * flujo canonico completo. La 004 no tenia `EnCurso`, asi que este es el unico
 * catalogo con el que se puede probar la regla de no avanzar desde esa columna.
 */
const CATALOGOS_005: CatalogosTicket = {
  ...CATALOGOS,
  estados: [
    { estado_id: 1, nombre: 'Pendiente', descripcion: 'Sin revisar' },
    { estado_id: 2, nombre: 'EnRevision', descripcion: 'En revision' },
    { estado_id: 3, nombre: 'EnCurso', descripcion: 'En preparacion' },
    { estado_id: 4, nombre: 'Cerrado', descripcion: 'Cerrado' },
  ],
};

/** Tickets de T10: reusa los de T8 (transiciones) y agrega uno en `EnCurso` (3). */
const TICKETS_005: Ticket[] = [
  ...TICKETS_TRANSICION,
  {
    ticket_id: 6,
    usuario_id: 5,
    prioridad_id: 1,
    estado_id: 3,
    asunto: 'Preparando pedido',
    descripcion: null,
    fecha_creacion: '2026-10-06T10:00:00',
    fecha_cierre: null,
    detalles: [],
  },
];

/**
 * Catalogo degenerado de T10: `EnCurso` duplicado con el **menor id en posicion
 * media** (el 3 va despues del 4). El canonico es el de menor `estado_id` (3),
 * no el primero del arreglo; el duplicado (4) conserva sus controles segun su
 * posicion, igual que cualquier otra columna.
 */
const CATALOGOS_EN_CURSO_DUPLICADO: CatalogosTicket = {
  ...CATALOGOS_005,
  estados: [
    { estado_id: 1, nombre: 'Pendiente', descripcion: 'Sin revisar' },
    { estado_id: 2, nombre: 'EnRevision', descripcion: 'En revision' },
    { estado_id: 4, nombre: 'EnCurso', descripcion: 'Duplicado no canonico' },
    { estado_id: 3, nombre: 'EnCurso', descripcion: 'En preparacion' },
    { estado_id: 5, nombre: 'Cerrado', descripcion: 'Cerrado' },
  ],
};

/** Un ticket en cada `EnCurso` del catalogo duplicado: el canonico y el no canonico. */
const TICKETS_EN_CURSO_DUPLICADO: Ticket[] = [
  {
    ticket_id: 7,
    usuario_id: 5,
    prioridad_id: 1,
    estado_id: 3,
    asunto: 'En el EnCurso canonico',
    descripcion: null,
    fecha_creacion: '2026-10-06T10:00:00',
    fecha_cierre: null,
    detalles: [],
  },
  {
    ticket_id: 8,
    usuario_id: 1,
    prioridad_id: 2,
    estado_id: 4,
    asunto: 'En el EnCurso duplicado',
    descripcion: null,
    fecha_creacion: '2026-10-06T11:00:00',
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

  /** Identidad local (`/auth/me`) que el componente lee para condicionar la UI. */
  let identidad: WritableSignal<IdentidadAutenticada | null>;

  function crearIdentidad(rol: string): IdentidadAutenticada {
    return {
      usuario_id: 9,
      sub: 'user_operativo',
      nombre: 'Bruno',
      apellido: 'Soto',
      correo: 'bruno.soto@losalpes.cl',
      rol,
      institucion: { institucion_id: 'inst-los-alpes', nombre: 'Los Alpes' },
    };
  }

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
    // El componente condiciona la UI al rol de la identidad local. Se inyecta un
    // doble con `identidad` como señal para no arrancar Clerk (ni red) en Karma.
    identidad = signal<IdentidadAutenticada | null>(crearIdentidad('Bodeguero'));

    await TestBed.configureTestingModule({
      imports: [TicketsComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AutenticacionService, useValue: { identidad } },
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

  describe('transiciones del tablero', () => {
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

    beforeEach(() => responderArranque(CATALOGOS, TICKETS_TRANSICION));

    it('AC-12: en el primer estado no hay retroceso y si hay avance', () => {
      const primero = tarjetaDe(1)!; // estado 1, indice 0

      expect(primero.puedeRetroceder).toBe(false);
      expect(primero.estadoAnteriorId).toBeNull();
      expect(primero.puedeAvanzar).toBe(true);
      expect(primero.estadoSiguienteId).toBe(2);
    });

    it('AC-11: en el estado terminal no se ofrece ningun control', () => {
      const terminal = tarjetaDe(5)!; // estado 4, ultimo del catalogo

      expect(terminal.puedeAvanzar).toBe(false);
      expect(terminal.puedeRetroceder).toBe(false);
      expect(terminal.estadoSiguienteId).toBeNull();
      expect(terminal.estadoAnteriorId).toBeNull();

      // Ni un boton de transicion en la tarjeta terminal.
      expect(
        fixture.nativeElement.querySelectorAll('button[aria-label$="#5"]').length
      ).toBe(0);
    });

    it('AC-9/AC-19: moverSiguiente emite un PATCH y mueve la tarjeta sin recargar', () => {
      const tarjeta = tarjetaDe(1)!;
      expect(tarjeta.enProceso).toBe(false);
      expect(columna(1).tarjetas.length).toBe(2);
      expect(columna(2).tarjetas.length).toBe(2);

      componente.moverSiguiente(tarjeta);

      const peticion = httpMock.expectOne(RUTA_ESTADO(1));
      expect(peticion.request.method).toBe('PATCH');
      expect(peticion.request.body).toEqual({ estado_id: 2 });

      peticion.flush({ ...TICKETS[0], estado_id: 2 });
      fixture.detectChanges();

      expect(tarjetaDe(1)!.ticket.estado_id).toBe(2);
      expect(columna(2).tarjetas.some((t) => t.ticket.ticket_id === 1)).toBe(true);
      expect(columna(1).tarjetas.length).toBe(1);
      expect(columna(2).tarjetas.length).toBe(3);
      // Sin recarga: no se reconsulto el tablero.
      httpMock.expectNone(RUTA_TICKETS);
    });

    it('AC-10: moverAnterior emite el PATCH al estado anterior y mueve la tarjeta', () => {
      const tarjeta = tarjetaDe(3)!; // estado 2, indice 1
      expect(tarjeta.estadoAnteriorId).toBe(1);

      componente.moverAnterior(tarjeta);

      const peticion = httpMock.expectOne(RUTA_ESTADO(3));
      expect(peticion.request.body).toEqual({ estado_id: 1 });

      peticion.flush({ ...TICKETS[2], estado_id: 1 });
      fixture.detectChanges();

      expect(tarjetaDe(3)!.ticket.estado_id).toBe(1);
      expect(columna(1).tarjetas.some((t) => t.ticket.ticket_id === 3)).toBe(true);
    });

    it('AC-19: con un PATCH pendiente el control queda deshabilitado y no hay doble envio', () => {
      componente.moverSiguiente(tarjetaDe(1)!);

      expect(tarjetaDe(1)!.enProceso).toBe(true);

      // Segundo intento con el primero aun en vuelo: no debe salir otra peticion.
      componente.moverSiguiente(tarjetaDe(1)!);
      const peticiones = httpMock.match(RUTA_ESTADO(1));
      expect(peticiones.length).toBe(1);

      peticiones[0].flush({ ...TICKETS[0], estado_id: 2 });
      fixture.detectChanges();

      expect(tarjetaDe(1)!.enProceso).toBe(false);
    });

    it('AC-12: los ids ofrecidos son los contiguos del catalogo, sin saltos', () => {
      const primero = tarjetaDe(1)!; // indice 0
      expect(primero.estadoAnteriorId).toBeNull();
      expect(primero.estadoSiguienteId).toBe(2);

      const medio = tarjetaDe(3)!; // indice 1
      expect(medio.estadoAnteriorId).toBe(1);
      expect(medio.estadoSiguienteId).toBe(4);

      const terminal = tarjetaDe(5)!; // indice 2 (ultimo)
      expect(terminal.estadoAnteriorId).toBeNull();
      expect(terminal.estadoSiguienteId).toBeNull();
    });
  });

  describe('regla de despacho: sin avance desde EnCurso (AC-16)', () => {
    /** Busca una tarjeta por el id de su ticket, aplanando las columnas. */
    function tarjetaDe(ticketId: number) {
      return componente
        .columnas()
        .flatMap((columna) => columna.tarjetas)
        .find((tarjeta) => tarjeta.ticket.ticket_id === ticketId);
    }

    it('AC-16: la tarjeta del EnCurso canónico no ofrece avanzar y sí retroceder', () => {
      responderArranque(CATALOGOS_005, TICKETS_005);

      const enCurso = tarjetaDe(6)!; // estado 3, canónico
      expect(enCurso.puedeAvanzar).toBe(false);
      expect(enCurso.estadoSiguienteId).toBeNull();
      // El retroceso no se toca: sigue apuntando al estado anterior del flujo.
      expect(enCurso.puedeRetroceder).toBe(true);
      expect(enCurso.estadoAnteriorId).toBe(2);
    });

    it('AC-16: el DOM no pinta el botón de avanzar en EnCurso pero sí el de retroceder', () => {
      responderArranque(CATALOGOS_005, TICKETS_005);

      expect(
        fixture.nativeElement.querySelector('button[aria-label="Avanzar ticket #6"]')
      ).toBeNull();
      expect(
        fixture.nativeElement.querySelector('button[aria-label="Retroceder ticket #6"]')
      ).not.toBeNull();
    });

    it('AC-16: intentar avanzar desde EnCurso no emite ningún PATCH', () => {
      responderArranque(CATALOGOS_005, TICKETS_005);

      // `estadoSiguienteId` es `null`, así que `moverSiguiente` sale sin tocar
      // la red aunque el usuario invoque la acción.
      componente.moverSiguiente(tarjetaDe(6)!);

      httpMock.expectNone(RUTA_ESTADO(6));
      expect(componente.errorMovimiento()).toBeNull();
    });

    it('AC-16: las demás columnas conservan sus controles', () => {
      responderArranque(CATALOGOS_005, TICKETS_005);

      const pendiente = tarjetaDe(1)!; // estado 1, primer estado
      expect(pendiente.puedeRetroceder).toBe(false);
      expect(pendiente.puedeAvanzar).toBe(true);
      expect(pendiente.estadoSiguienteId).toBe(2);

      const enRevision = tarjetaDe(3)!; // estado 2, intermedio
      expect(enRevision.puedeRetroceder).toBe(true);
      expect(enRevision.estadoAnteriorId).toBe(1);
      expect(enRevision.puedeAvanzar).toBe(true);
      expect(enRevision.estadoSiguienteId).toBe(3);

      const cerrado = tarjetaDe(5)!; // estado 4, terminal
      expect(cerrado.puedeAvanzar).toBe(false);
      expect(cerrado.puedeRetroceder).toBe(false);
      expect(cerrado.estadoSiguienteId).toBeNull();
      expect(cerrado.estadoAnteriorId).toBeNull();
    });

    it('AC-16: resuelve EnCurso sin distinguir mayúsculas', () => {
      const catalogosMinuscula: CatalogosTicket = {
        ...CATALOGOS_005,
        estados: CATALOGOS_005.estados.map((estado) => ({
          ...estado,
          nombre: estado.nombre.toLowerCase(),
        })),
      };
      responderArranque(catalogosMinuscula, TICKETS_005);

      const enCurso = tarjetaDe(6)!;
      expect(enCurso.puedeAvanzar).toBe(false);
      expect(enCurso.estadoSiguienteId).toBeNull();
      // El retroceso se conserva también con el nombre en minúsculas.
      expect(enCurso.puedeRetroceder).toBe(true);
    });

    it('AC-16: con EnCurso duplicado solo el de menor id oculta el avance', () => {
      responderArranque(CATALOGOS_EN_CURSO_DUPLICADO, TICKETS_EN_CURSO_DUPLICADO);

      // El canónico es el de menor `estado_id` (3), aunque no sea el primero del
      // arreglo.
      const canonico = tarjetaDe(7)!; // estado 3
      expect(canonico.puedeAvanzar).toBe(false);
      expect(canonico.estadoSiguienteId).toBeNull();

      // La columna duplicada (4) no es el canónico: conserva su avance.
      const duplicado = tarjetaDe(8)!; // estado 4
      expect(duplicado.puedeAvanzar).toBe(true);
      expect(duplicado.estadoSiguienteId).toBe(3);
    });
  });

  describe('rechazos del tablero', () => {
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

    it('AC-20: un 409 deja la tarjeta quieta, muestra alerta y reconsulta', () => {
      responderArranque(CATALOGOS, TICKETS_TRANSICION);

      componente.moverSiguiente(tarjetaDe(1)!);

      httpMock
        .expectOne(RUTA_ESTADO(1))
        .flush(
          { detail: 'Transición no permitida por el flujo' },
          { status: 409, statusText: 'Conflict' }
        );
      fixture.detectChanges();

      // Alerta accesible con el mensaje del backend.
      expect(componente.errorMovimiento()).toBe('Transición no permitida por el flujo');
      expect(fixture.nativeElement.querySelector('[role="alert"]')).toBeTruthy();
      expect(fixture.nativeElement.textContent).toContain('Transición no permitida por el flujo');

      // La tarjeta no se movio: sigue en su columna de origen.
      expect(columna(1).tarjetas.some((t) => t.ticket.ticket_id === 1)).toBe(true);
      expect(columna(2).tarjetas.some((t) => t.ticket.ticket_id === 1)).toBe(false);

      // Una sola reconsulta, y es la que fija la posicion final.
      httpMock
        .expectOne(RUTA_TICKETS)
        .flush(
          TICKETS_TRANSICION.map((t) => (t.ticket_id === 1 ? { ...t, estado_id: 2 } : t))
        );
      fixture.detectChanges();

      expect(tarjetaDe(1)!.ticket.estado_id).toBe(2);
      expect(columna(2).tarjetas.some((t) => t.ticket.ticket_id === 1)).toBe(true);
    });

    it('AC-20: un 404 deja la tarjeta quieta, muestra alerta y reconsulta', () => {
      responderArranque(CATALOGOS, TICKETS_TRANSICION);

      componente.moverSiguiente(tarjetaDe(1)!);

      httpMock
        .expectOne(RUTA_ESTADO(1))
        .flush({ detail: 'Ticket no encontrado' }, { status: 404, statusText: 'Not Found' });
      fixture.detectChanges();

      expect(componente.errorMovimiento()).toBe('Ticket no encontrado');
      expect(fixture.nativeElement.querySelector('[role="alert"]')).toBeTruthy();
      expect(columna(1).tarjetas.some((t) => t.ticket.ticket_id === 1)).toBe(true);

      httpMock.expectOne(RUTA_TICKETS).flush(TICKETS_TRANSICION);
      fixture.detectChanges();
    });

    it('AC-20: la ausencia de respuesta deja la tarjeta quieta, muestra alerta y reconsulta', () => {
      responderArranque(CATALOGOS, TICKETS_TRANSICION);

      componente.moverSiguiente(tarjetaDe(1)!);

      httpMock.expectOne(RUTA_ESTADO(1)).error(new ProgressEvent('error'));
      fixture.detectChanges();

      expect(componente.errorMovimiento()).toContain('No se pudo cambiar el estado');
      expect(fixture.nativeElement.querySelector('[role="alert"]')).toBeTruthy();
      expect(columna(1).tarjetas.some((t) => t.ticket.ticket_id === 1)).toBe(true);
      expect(columna(2).tarjetas.some((t) => t.ticket.ticket_id === 1)).toBe(false);

      httpMock.expectOne(RUTA_TICKETS).flush(TICKETS_TRANSICION);
      fixture.detectChanges();
    });

    it('AC-8: el ticket creado aparece en el tablero sin recargar', () => {
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

    it('AC-8: el ticket creado no aparece si los filtros no lo admiten (D-6)', () => {
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
   * AC-3: el Solicitante consulta sus tickets pero no opera el Kanban (avanzar,
   * retroceder, despachar). Es comodidad de interfaz: la frontera de seguridad
   * real está en la API (D-2).
   */
  describe('capacidades por rol (AC-3)', () => {
    it('oculta las operaciones de Kanban al Solicitante', () => {
      identidad.set(crearIdentidad('Solicitante'));
      responderArranque(CATALOGOS, TICKETS_TRANSICION);

      expect(componente.puedeGestionarKanban()).toBe(false);
      expect(
        fixture.nativeElement.querySelector('button[aria-label^="Avanzar ticket"]')
      ).toBeNull();
      expect(
        fixture.nativeElement.querySelector('button[aria-label^="Retroceder ticket"]')
      ).toBeNull();
    });

    it('ofrece las operaciones de Kanban a Bodeguero, Administrador y Superadmin', () => {
      responderArranque(CATALOGOS, TICKETS_TRANSICION);

      for (const rol of ['Bodeguero', 'Administrador', 'Superadmin']) {
        identidad.set(crearIdentidad(rol));
        fixture.detectChanges();

        expect(componente.puedeGestionarKanban()).withContext(rol).toBe(true);
        expect(
          fixture.nativeElement.querySelector('button[aria-label^="Avanzar ticket"]')
        )
          .withContext(rol)
          .not.toBeNull();
      }
    });

    it('no ofrece operaciones ante un rol alias o ausente', () => {
      responderArranque();

      identidad.set(crearIdentidad('Admin'));
      expect(componente.puedeGestionarKanban()).toBe(false);

      identidad.set(null);
      expect(componente.puedeGestionarKanban()).toBe(false);
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
