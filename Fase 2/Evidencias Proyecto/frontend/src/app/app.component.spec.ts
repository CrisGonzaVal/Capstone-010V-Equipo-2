import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { AppComponent } from './app.component';
import { routes } from './app.routes';

describe('AppComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AppComponent],
      // `AppComponent` usa `routerLink`/`router-outlet`, asi que sin el router
      //-provider los enlaces no se pueden resolver y el fixture falla al crear.
      providers: [provideRouter(routes)],
    }).compileComponents();
  });

  it('should create the app', () => {
    const fixture = TestBed.createComponent(AppComponent);
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('debe exponer el titulo del sistema', () => {
    const fixture = TestBed.createComponent(AppComponent);
    expect(fixture.componentInstance.titulo).toEqual('CompuStock ERP');
  });

  it('debe renderizar el encabezado principal', () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    const compilado = fixture.nativeElement as HTMLElement;
    expect(compilado.querySelector('h1')?.textContent).toContain('Sistema ERP');
  });

  it('debe alternar el menu lateral', () => {
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;

    expect(app.sidebarAbierto()).toBeTrue();
    app.alternarSidebar();
    expect(app.sidebarAbierto()).toBeFalse();
    app.alternarSidebar();
    expect(app.sidebarAbierto()).toBeTrue();
  });
});