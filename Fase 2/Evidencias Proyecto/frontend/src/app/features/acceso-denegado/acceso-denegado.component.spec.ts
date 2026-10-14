import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { AccesoDenegadoComponent } from './acceso-denegado.component';

/**
 * El estado dedicado de AC-2 comunica el permiso insuficiente sin cerrar sesión
 * ni enviar a `/login`, y ofrece una salida operativa a una sección permitida.
 */
describe('AccesoDenegadoComponent', () => {
  let fixture: ComponentFixture<AccesoDenegadoComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AccesoDenegadoComponent],
      providers: [provideRouter([])],
    }).compileComponents();

    fixture = TestBed.createComponent(AccesoDenegadoComponent);
    fixture.detectChanges();
  });

  it('muestra el mensaje de acceso denegado', () => {
    const texto = fixture.nativeElement.textContent;

    expect(texto).toContain('Acceso denegado');
    expect(texto).toContain('Tu rol actual no tiene permiso');
    expect(texto).not.toContain('Inicia sesión');
  });

  it('ofrece volver al dashboard sin enlazar a /login', () => {
    const enlaces: HTMLAnchorElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('a'),
    );

    const destinos = enlaces.map((enlace) => enlace.getAttribute('href') ?? '');
    expect(destinos).toContain('/dashboard');
    expect(destinos).not.toContain('/login');
  });
});
