import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { URL_API } from '../../../shared/config/url-api';
import { AdministracionService } from './administracion.service';

/**
 * Feature 012 (T10): contrato HTTP del `AdministracionService`.
 *
 * Seam bajo prueba: la interfaz pública del servicio contra
 * `HttpTestingController`. Se verifica método y ruta contractual de cada
 * operación de sedes, departamentos, usuarios y encargados, y que los cuerpos de
 * mutación no incluyan institución ni esquema (el ámbito lo resuelve el servidor).
 */
describe('AdministracionService', () => {
  const organizacion = `${URL_API}/organizacion`;
  const usuarios = `${URL_API}/usuarios`;

  let servicio: AdministracionService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    servicio = TestBed.inject(AdministracionService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('lista sedes con GET /organizacion/sedes', () => {
    servicio.listarSedes().subscribe();
    const peticion = httpMock.expectOne(`${organizacion}/sedes`);
    expect(peticion.request.method).toBe('GET');
    peticion.flush([]);
  });

  it('crea sede con POST y solo nombre + dirección', () => {
    servicio.crearSede({ nombre: 'Bodega Sur', direccion: null }).subscribe();
    const peticion = httpMock.expectOne(`${organizacion}/sedes`);
    expect(peticion.request.method).toBe('POST');
    expect(peticion.request.body).toEqual({ nombre: 'Bodega Sur', direccion: null });
    peticion.flush({
      sede_id: 1,
      nombre: 'Bodega Sur',
      direccion: null,
      institucion_id: 'INSTA',
      activo: true,
    });
  });

  it('edita sede con PUT /organizacion/sedes/{id}', () => {
    servicio.editarSede(7, { nombre: 'Sede 7', direccion: 'Calle 1' }).subscribe();
    const peticion = httpMock.expectOne(`${organizacion}/sedes/7`);
    expect(peticion.request.method).toBe('PUT');
    expect(peticion.request.body).toEqual({ nombre: 'Sede 7', direccion: 'Calle 1' });
    peticion.flush({
      sede_id: 7,
      nombre: 'Sede 7',
      direccion: 'Calle 1',
      institucion_id: 'INSTA',
      activo: true,
    });
  });

  it('cambia el estado de sede con PATCH .../estado y cuerpo { activo }', () => {
    servicio.cambiarEstadoSede(7, false).subscribe();
    const peticion = httpMock.expectOne(`${organizacion}/sedes/7/estado`);
    expect(peticion.request.method).toBe('PATCH');
    expect(peticion.request.body).toEqual({ activo: false });
    peticion.flush({ sede_id: 7, activo: false });
  });

  it('lista departamentos con GET /organizacion/departamentos', () => {
    servicio.listarDepartamentos().subscribe();
    const peticion = httpMock.expectOne(`${organizacion}/departamentos`);
    expect(peticion.request.method).toBe('GET');
    peticion.flush([]);
  });

  it('crea departamento con POST sin sede obligatoria', () => {
    servicio.crearDepartamento({ nombre_dep: 'Logística', descripcion: null }).subscribe();
    const peticion = httpMock.expectOne(`${organizacion}/departamentos`);
    expect(peticion.request.method).toBe('POST');
    expect(peticion.request.body).toEqual({
      nombre_dep: 'Logística',
      descripcion: null,
    });
    peticion.flush({
      departamento_id: 10,
      nombre_dep: 'Logística',
      descripcion: null,
      institucion_id: 'INSTA',
      sede_id: null,
      activo: true,
    });
  });

  it('asigna sede a un departamento con PUT .../sede y cuerpo { sede_id }', () => {
    servicio.asignarSedeDepartamento(10, 2).subscribe();
    const peticion = httpMock.expectOne(`${organizacion}/departamentos/10/sede`);
    expect(peticion.request.method).toBe('PUT');
    expect(peticion.request.body).toEqual({ sede_id: 2 });
    peticion.flush({ departamento_id: 10, sede_id: 2 });
  });

  it('cambia el estado de departamento con PATCH .../estado', () => {
    servicio.cambiarEstadoDepartamento(10, false).subscribe();
    const peticion = httpMock.expectOne(`${organizacion}/departamentos/10/estado`);
    expect(peticion.request.method).toBe('PATCH');
    expect(peticion.request.body).toEqual({ activo: false });
    peticion.flush({ departamento_id: 10, activo: false });
  });

  it('lista encargados con GET .../encargados', () => {
    servicio.listarEncargados(10).subscribe();
    const peticion = httpMock.expectOne(`${organizacion}/departamentos/10/encargados`);
    expect(peticion.request.method).toBe('GET');
    peticion.flush([]);
  });

  it('asocia encargado con POST y cuerpo { usuario_id }', () => {
    servicio.asociarEncargado(10, 5).subscribe();
    const peticion = httpMock.expectOne(`${organizacion}/departamentos/10/encargados`);
    expect(peticion.request.method).toBe('POST');
    expect(peticion.request.body).toEqual({ usuario_id: 5 });
    peticion.flush({
      usuario_id: 5,
      departamento_id: 10,
      nombre: 'Ana',
      apellido: 'Pérez',
      correo: 'ana@e.com',
    });
  });

  it('retira encargado con DELETE .../encargados/{usuarioId}', () => {
    servicio.retirarEncargado(10, 5).subscribe();
    const peticion = httpMock.expectOne(`${organizacion}/departamentos/10/encargados/5`);
    expect(peticion.request.method).toBe('DELETE');
    peticion.flush(null);
  });

  it('lista usuarios con GET /usuarios/', () => {
    servicio.listarUsuarios().subscribe();
    const peticion = httpMock.expectOne(`${usuarios}/`);
    expect(peticion.request.method).toBe('GET');
    peticion.flush([]);
  });

  it('crea un usuario con POST /usuarios/ y sin institución ni esquema', () => {
    servicio
      .crearUsuario({
        nombre: 'Nuevo',
        apellido: 'Local',
        correo: 'nuevo@example.com',
        departamento_id: 10,
        rol_id: 4,
      })
      .subscribe();
    const peticion = httpMock.expectOne(`${usuarios}/`);
    expect(peticion.request.method).toBe('POST');
    expect(peticion.request.body).toEqual({
      nombre: 'Nuevo',
      apellido: 'Local',
      correo: 'nuevo@example.com',
      departamento_id: 10,
      rol_id: 4,
    });
    const cuerpo = peticion.request.body as Record<string, unknown>;
    expect(cuerpo['institucion_id']).toBeUndefined();
    expect(cuerpo['nombre_esquema']).toBeUndefined();
    peticion.flush({
      usuario_id: 9,
      nombre: 'Nuevo',
      apellido: 'Local',
      correo: 'nuevo@example.com',
      departamento_id: 10,
      rol_id: 4,
      sede_id: null,
      activo: null,
    });
  });

  it('lista roles con GET /usuarios/roles', () => {
    servicio.listarRoles().subscribe();
    const peticion = httpMock.expectOne(`${usuarios}/roles`);
    expect(peticion.request.method).toBe('GET');
    peticion.flush([]);
  });

  it('edita un usuario con PUT sin correo', () => {
    servicio
      .editarUsuario(5, {
        nombre: 'Ana',
        apellido: 'Pérez',
        departamento_id: 10,
        rol_id: 4,
      })
      .subscribe();
    const peticion = httpMock.expectOne(`${usuarios}/5`);
    expect(peticion.request.method).toBe('PUT');
    expect(peticion.request.body).toEqual({
      nombre: 'Ana',
      apellido: 'Pérez',
      departamento_id: 10,
      rol_id: 4,
    });
    peticion.flush({
      usuario_id: 5,
      nombre: 'Ana',
      apellido: 'Pérez',
      correo: 'ana@e.com',
      departamento_id: 10,
      rol_id: 4,
    });
  });

  it('cambia el estado de un usuario con PATCH .../estado', () => {
    servicio.cambiarEstadoUsuario(5, false).subscribe();
    const peticion = httpMock.expectOne(`${usuarios}/5/estado`);
    expect(peticion.request.method).toBe('PATCH');
    expect(peticion.request.body).toEqual({ activo: false });
    peticion.flush({ usuario_id: 5, activo: false });
  });

  it('asigna sede a un usuario con PUT /organizacion/usuarios/{id}/sede', () => {
    servicio.asignarSedeUsuario(5, 2).subscribe();
    const peticion = httpMock.expectOne(`${organizacion}/usuarios/5/sede`);
    expect(peticion.request.method).toBe('PUT');
    expect(peticion.request.body).toEqual({ sede_id: 2 });
    peticion.flush({ usuario_id: 5, sede_id: 2 });
  });
});
