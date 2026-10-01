import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { URL_API } from '../../shared/config/url-api';
import { CatalogosTicket } from '../../shared/interfaces';
import { TicketsComponent } from './tickets.component';

const RUTA_CATALOGOS = `${URL_API}/tickets/catalogos`;
const RUTA_TICKETS = `${URL_API}/tickets/`;

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

describe('TicketsComponent', () => {
  let fixture: ComponentFixture<TicketsComponent>;
  let componente: TicketsComponent;
  let httpMock: HttpTestingController;

  /** Abre el modal y responde la peticion de catalogos. */
  function abrirConCatalogos(catalogos: CatalogosTicket = CATALOGOS) {
    componente.abrirModal();
    httpMock.expectOne(RUTA_CATALOGOS).flush(catalogos);
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
    await TestBed.configureTestingModule({
      imports: [TicketsComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
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
    it('debe pedir los catalogos al abrir el modal, con una sola peticion', () => {
      componente.abrirModal();

      const peticiones = httpMock.match(RUTA_CATALOGOS);
      expect(peticiones.length).toBe(1);
      peticiones[0].flush(CATALOGOS);
    });

    it('no debe pedir catalogos antes de abrir el modal', () => {
      httpMock.expectNone(RUTA_CATALOGOS);
      expect(componente.catalogos()).toBeNull();
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

    it('debe distinguir el error de catalogos del de guardado', () => {
      componente.abrirModal();
      httpMock
        .expectOne(RUTA_CATALOGOS)
        .flush('Falla', { status: 500, statusText: 'Server Error' });
      fixture.detectChanges();

      expect(componente.errorCatalogos()).toBeTruthy();
      expect(componente.errorGuardado()).toBeNull();
      expect(componente.cargandoCatalogos()).toBe(false);
    });

    it('debe limpiar el estado de catalogos al reabrir el modal', () => {
      abrirConCatalogos();
      componente.cerrarModal();

      componente.abrirModal();
      httpMock.expectOne(RUTA_CATALOGOS).flush(CATALOGOS);

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

      peticion.flush({ ticket_id: 42 });
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
      httpMock.expectOne(RUTA_TICKETS).flush({ ticket_id: 42 });

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
      httpMock.expectOne(RUTA_TICKETS).flush({ ticket_id: 42 });
    });

    it('debe deshabilitar el envio mientras guarda', () => {
      completarFormulario();
      componente.enviar();
      const peticion = httpMock.expectOne(RUTA_TICKETS);

      expect(componente.guardando()).toBe(true);

      peticion.flush({ ticket_id: 42 });
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
    it('debe conservar los datos de muestra', () => {
      const total = componente.columnas().reduce(
        (suma, columna) => suma + columna.tarjetas.length,
        0
      );

      expect(componente.columnas().length).toBe(4);
      expect(total).toBe(6);
    });
  });
});