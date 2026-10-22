import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { of } from 'rxjs';

import { AutenticacionService } from '../../core/services/auth.service';
import { IdentidadAutenticada } from '../../shared/interfaces';
import { administracionRoutes } from './administracion.routes';
import { AdministracionService } from './services/administracion.service';

/**
 * Navegación de administración como pestañas ARIA (enmienda T-17, 22/Oct/2026).
 *
 * Se monta el **layout real** (`AdministracionComponent`, con su
 * `<app-administracion-nav />` y su `<router-outlet />`) sobre las **rutas
 * reales** de `administracion.routes.ts`, y se navega de verdad a cada una de
 * las cuatro rutas hijas. Así se prueba el contrato observable de AC-15
 * (tablist, cuatro tabs, una sola seleccionada y tabbable, IDs estables),
 * AC-17 (panel asociado por `aria-labelledby`) y AC-18 (deep links y destinos
 * intactos), sin duplicar los tests de cada vista hija.
 *
 * La sección de teclado (E17-2) cubre AC-16 sobre el mismo montaje real: flechas
 * izquierda/derecha con recorrido circular, foco DOM en el enlace destino, ruta
 * activa actualizada, `preventDefault` solo en las flechas atendidas y ninguna
 * interceptación de otras teclas. El keydown se dispara **en el DOM real** sobre
 * el enlace enfocado, no a través de un `DebugElement`, porque el contrato que
 * hay que fijar es precisamente el del navegador (foco, propagación y
 * cancelación del evento) y el harness ya expone el elemento nativo.
 *
 * Los colaboradores se sustituyen por stubs vacíos: estas pruebas son de
 * navegación y semántica, no de carga de datos. `administracion.routes.ts` no se
 * modifica ni se replica: se consume tal cual.
 */
describe('navegación de administración como pestañas ARIA (enmienda T-17)', () => {
  interface PestanaEsperada {
    /** Ruta hija que activa la pestaña. */
    readonly href: string;
    /** `id` estable pactado por la enmienda. */
    readonly id: string;
    /** Elemento de la vista hija que el router monta dentro del panel. */
    readonly vista: string;
    readonly etiqueta: string;
  }

  const PESTANAS: readonly PestanaEsperada[] = [
    {
      href: '/administracion/sedes',
      id: 'pestana-administracion-sedes',
      vista: 'app-administracion-sedes',
      etiqueta: 'Sedes',
    },
    {
      href: '/administracion/departamentos',
      id: 'pestana-administracion-departamentos',
      vista: 'app-administracion-departamentos',
      etiqueta: 'Departamentos',
    },
    {
      href: '/administracion/usuarios',
      id: 'pestana-administracion-usuarios',
      vista: 'app-administracion-usuarios',
      etiqueta: 'Usuarios',
    },
    {
      href: '/administracion/encargados',
      id: 'pestana-administracion-encargados',
      vista: 'app-administracion-encargados',
      etiqueta: 'Encargados',
    },
  ];

  /**
   * Stub del servicio de administración: estas pruebas no cargan datos, solo
   * comprueban navegación. Las vistas hijas reciben listas vacías.
   */
  const SERVICIO_VACIO = {
    listarSedes: () => of([]),
    listarDepartamentos: () => of([]),
    listarUsuarios: () => of([]),
    listarRoles: () => of([]),
    listarEncargados: () => of([]),
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      providers: [
        // Las rutas reales, montadas bajo el segmento `/administracion` tal como
        // las cuelga `app.routes.ts`. No se redefine ninguna ruta hija.
        provideRouter([{ path: 'administracion', children: administracionRoutes }]),
        { provide: AdministracionService, useValue: SERVICIO_VACIO },
        {
          provide: AutenticacionService,
          useValue: { identidad: signal<IdentidadAutenticada | null>(null) },
        },
      ],
    }).compileComponents();
  });

  interface LayoutAbierto {
    readonly router: Router;
    readonly raiz: HTMLElement;
    readonly harness: RouterTestingHarness;
  }

  /** Navega de verdad a `url` y devuelve el layout real ya renderizado. */
  async function abrir(url: string): Promise<LayoutAbierto> {
    const router = TestBed.inject(Router);
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl(url);
    harness.detectChanges();

    const raiz = harness.routeNativeElement as HTMLElement | null;
    expect(raiz)
      .withContext(`el layout de administración debe montarse en el outlet para ${url}`)
      .toBeTruthy();
    return { router, raiz: raiz as HTMLElement, harness };
  }

  /** Las pestañas declaradas en el DOM (role="tab"). */
  function pestanasDe(raiz: HTMLElement): HTMLElement[] {
    return Array.from(raiz.querySelectorAll<HTMLElement>('[role="tab"]'));
  }

  /**
   * Localiza el enlace-tab por su **destino real**, no por `role="tab"` ni por
   * `id`: así las pruebas de teclado siguen midiendo comportamiento (ruta y
   * foco) aunque el marcado ARIA esté a medias, y fallan por lo que deben
   * fallar. Se busca dentro de la barra de secciones para no confundirlo con
   * enlaces de las vistas hijas.
   */
  function anchorDe(raiz: HTMLElement, ruta: string): HTMLAnchorElement {
    const barra = raiz.querySelector('nav') ?? raiz;
    const anchor = barra.querySelector<HTMLAnchorElement>(`a[href="${ruta}"]`);
    expect(anchor)
      .withContext(`la barra de secciones debe ofrecer un enlace real a ${ruta}`)
      .toBeTruthy();
    return anchor as HTMLAnchorElement;
  }

  /**
   * Dispara la tecla sobre el elemento real y espera a que el Router termine la
   * navegación que su `routerLink` haya podido generar. `cancelable: true` es
   * imprescindible: sin él `preventDefault()` no tendría efecto y
   * `defaultPrevented` nunca podría observarse.
   */
  async function pulsar(
    contexto: LayoutAbierto,
    elemento: HTMLElement,
    tecla: string,
  ): Promise<KeyboardEvent> {
    const evento = new KeyboardEvent('keydown', {
      key: tecla,
      bubbles: true,
      cancelable: true,
    });
    elemento.dispatchEvent(evento);
    await contexto.harness.fixture.whenStable();
    contexto.harness.detectChanges();
    return evento;
  }

  for (const esperada of PESTANAS) {
    it(`AC-15: ${esperada.href} deja una sola pestaña seleccionada y tabbable`, async () => {
      const { router, raiz } = await abrir(esperada.href);

      const tablist = raiz.querySelector('[role="tablist"]');
      expect(tablist)
        .withContext(`la barra de secciones debe declararse tablist en ${esperada.href}`)
        .toBeTruthy();
      expect((tablist?.getAttribute('aria-label') ?? '').trim())
        .withContext('el tablist necesita un nombre accesible')
        .not.toBe('');

      const pestanas = pestanasDe(raiz);
      expect(pestanas.length)
        .withContext(`deben existir exactamente cuatro pestañas en ${esperada.href}`)
        .toBe(4);

      // Solo la pestaña de la ruta activa está seleccionada.
      const seleccionadas = pestanas.filter(
        (pestana) => pestana.getAttribute('aria-selected') === 'true',
      );
      expect(seleccionadas.length)
        .withContext(`solo una pestaña puede estar seleccionada en ${esperada.href}`)
        .toBe(1);
      expect(seleccionadas[0]?.id)
        .withContext(`la pestaña activa de ${esperada.href} debe tener el id estable`)
        .toBe(esperada.id);

      // Roving tabindex: un único tab stop, en la pestaña activa.
      const tabbables = pestanas.filter((pestana) => pestana.getAttribute('tabindex') === '0');
      expect(tabbables.length)
        .withContext(`un solo tab stop en ${esperada.href}`)
        .toBe(1);
      expect(tabbables[0]?.id)
        .withContext(`el tab stop de ${esperada.href} debe ser la pestaña activa`)
        .toBe(esperada.id);
      const noTabbables = pestanas.filter((pestana) => pestana.getAttribute('tabindex') === '-1');
      expect(noTabbables.length)
        .withContext(`las otras tres pestañas deben quedar fuera del orden de tabulación`)
        .toBe(3);

      // Estado explícito de las cuatro, sin atributos ausentes.
      for (const pestana of pestanas) {
        const activa = pestana.id === esperada.id;
        expect(pestana.getAttribute('aria-selected'))
          .withContext(`aria-selected de #${pestana.id} en ${esperada.href}`)
          .toBe(activa ? 'true' : 'false');
        expect(pestana.getAttribute('tabindex'))
          .withContext(`tabindex de #${pestana.id} en ${esperada.href}`)
          .toBe(activa ? '0' : '-1');
      }

      // El deep link no se reescribe: la ruta pedida sigue vigente (AC-18).
      expect(router.url).withContext('la ruta visitada debe conservarse').toBe(esperada.href);
    });

    it(`AC-17: el panel de ${esperada.href} se etiqueta con su pestaña activa`, async () => {
      const { raiz } = await abrir(esperada.href);

      const paneles = Array.from(raiz.querySelectorAll<HTMLElement>('[role="tabpanel"]'));
      expect(paneles.length)
        .withContext(`debe existir un único panel de pestaña en ${esperada.href}`)
        .toBe(1);

      const panel = paneles[0];
      expect(panel.getAttribute('aria-labelledby'))
        .withContext(`el panel de ${esperada.href} debe etiquetarse con la pestaña activa`)
        .toBe(esperada.id);

      // La pestaña referenciada existe realmente en el DOM.
      expect(raiz.querySelector(`#${esperada.id}`))
        .withContext(`aria-labelledby debe apuntar a un id existente (${esperada.id})`)
        .toBeTruthy();

      // El panel contiene el `router-outlet`: la vista hija de la ruta vive ahí.
      expect(panel.querySelector(esperada.vista))
        .withContext(`la vista ${esperada.vista} debe renderizarse dentro del panel`)
        .toBeTruthy();
    });
  }

  it('AC-15/AC-18: las cuatro pestañas son anchors reales con su href y sus IDs estables', async () => {
    const { raiz } = await abrir(PESTANAS[0].href);

    const pestanas = pestanasDe(raiz);
    expect(pestanas.length)
      .withContext('deben existir exactamente cuatro pestañas')
      .toBe(4);

    // Son enlaces, no botones: conservan apertura en pestaña nueva y demás
    // comportamiento nativo del navegador.
    expect(pestanas.map((pestana) => pestana.tagName)).toEqual(['A', 'A', 'A', 'A']);

    // Cada pestaña enlaza a su ruta hija real, en el orden de la barra.
    expect(pestanas.map((pestana) => pestana.getAttribute('href'))).toEqual([
      '/administracion/sedes',
      '/administracion/departamentos',
      '/administracion/usuarios',
      '/administracion/encargados',
    ]);

    // Los IDs son estables y no dependen de la ruta activa.
    expect(pestanas.map((pestana) => pestana.id)).toEqual([
      'pestana-administracion-sedes',
      'pestana-administracion-departamentos',
      'pestana-administracion-usuarios',
      'pestana-administracion-encargados',
    ]);

    // Los textos siguen siendo los de siempre.
    expect(
      pestanas.map((pestana) => (pestana.textContent ?? '').replace(/\s+/g, ' ').trim()),
    ).toEqual(['Sedes', 'Departamentos', 'Usuarios', 'Encargados']);
  });

  it('AC-17: la entrada /administracion redirige a sedes y su panel apunta a esa pestaña', async () => {
    const { router, raiz } = await abrir('/administracion');

    expect(router.url)
      .withContext('la raíz de administración debe seguir redirigiendo a sedes')
      .toBe('/administracion/sedes');

    const panel = raiz.querySelector('[role="tabpanel"]');
    expect(panel)
      .withContext('la redirección también debe mostrar el panel de pestaña')
      .toBeTruthy();
    expect(panel?.getAttribute('aria-labelledby')).toBe('pestana-administracion-sedes');

    const activa = pestanasDe(raiz).filter(
      (pestana) => pestana.getAttribute('aria-selected') === 'true',
    );
    expect(activa.map((pestana) => pestana.id)).toEqual(['pestana-administracion-sedes']);
  });

  // --- Teclado y navegación nativa (E17-2, AC-16/AC-18/AC-19) ---------------

  describe('AC-16: flechas con recorrido circular sobre los cuatro destinos', () => {
    // El orden del recorrido es el de `enlaces` (orden visual de la barra).
    PESTANAS.forEach((origen, indice) => {
      const siguiente = PESTANAS[(indice + 1) % PESTANAS.length];
      const anterior = PESTANAS[(indice + PESTANAS.length - 1) % PESTANAS.length];

      it(`ArrowRight desde ${origen.etiqueta} activa y enfoca ${siguiente.etiqueta}`, async () => {
        const contexto = await abrir(origen.href);
        const tabOrigen = anchorDe(contexto.raiz, origen.href);
        tabOrigen.focus();
        expect(document.activeElement)
          .withContext('el punto de partida del recorrido debe ser la pestaña de la ruta activa')
          .toBe(tabOrigen);

        const evento = await pulsar(contexto, tabOrigen, 'ArrowRight');

        expect(evento.defaultPrevented)
          .withContext(
            'ArrowRight debe atender la tecla y prevenir el desplazamiento horizontal de la barra',
          )
          .toBe(true);
        expect(contexto.router.url)
          .withContext(`ArrowRight desde ${origen.href} debe activar ${siguiente.href}`)
          .toBe(siguiente.href);

        const destino = anchorDe(contexto.raiz, siguiente.href);
        expect(document.activeElement)
          .withContext(`el foco debe quedar en el enlace de ${siguiente.etiqueta}`)
          .toBe(destino);
        expect(destino.tagName)
          .withContext('la pestaña destino es un enlace real, no un botón')
          .toBe('A');
        expect(destino.href)
          .withContext(`el enlace destino debe apuntar a ${siguiente.href}`)
          .toContain(siguiente.href);
      });

      it(`ArrowLeft desde ${origen.etiqueta} activa y enfoca ${anterior.etiqueta}`, async () => {
        const contexto = await abrir(origen.href);
        const tabOrigen = anchorDe(contexto.raiz, origen.href);
        tabOrigen.focus();
        expect(document.activeElement)
          .withContext('el punto de partida del recorrido debe ser la pestaña de la ruta activa')
          .toBe(tabOrigen);

        const evento = await pulsar(contexto, tabOrigen, 'ArrowLeft');

        expect(evento.defaultPrevented)
          .withContext(
            'ArrowLeft debe atender la tecla y prevenir el desplazamiento horizontal de la barra',
          )
          .toBe(true);
        expect(contexto.router.url)
          .withContext(`ArrowLeft desde ${origen.href} debe activar ${anterior.href}`)
          .toBe(anterior.href);

        const destino = anchorDe(contexto.raiz, anterior.href);
        expect(document.activeElement)
          .withContext(`el foco debe quedar en el enlace de ${anterior.etiqueta}`)
          .toBe(destino);
        expect(destino.tagName)
          .withContext('la pestaña destino es un enlace real, no un botón')
          .toBe('A');
        expect(destino.href)
          .withContext(`el enlace destino debe apuntar a ${anterior.href}`)
          .toContain(anterior.href);
      });
    });

    it('AC-16: Enter, Tab y una letra no se interceptan', async () => {
      const contexto = await abrir(PESTANAS[0].href);
      const tabOrigen = anchorDe(contexto.raiz, PESTANAS[0].href);
      tabOrigen.focus();

      for (const tecla of ['Enter', 'Tab', 'a']) {
        const evento = await pulsar(contexto, tabOrigen, tecla);

        expect(evento.defaultPrevented)
          .withContext(`${tecla} no forma parte del contrato de pestañas y no debe cancelarse`)
          .toBe(false);
        expect(contexto.router.url)
          .withContext(`${tecla} no debe provocar navegación por sí sola en este contrato`)
          .toBe(PESTANAS[0].href);
        expect(document.activeElement)
          .withContext(`${tecla} no debe mover el foco declarado por la barra`)
          .toBe(tabOrigen);
      }
    });
  });

  it('AC-16/AC-18: tras ArrowRight, ARIA, panel y URL quedan coherentes con el destino', async () => {
    const abrirPestana = spyOn(window, 'open');

    const contexto = await abrir(PESTANAS[0].href);
    const tabOrigen = anchorDe(contexto.raiz, PESTANAS[0].href);
    tabOrigen.focus();

    await pulsar(contexto, tabOrigen, 'ArrowRight');

    const destino = PESTANAS[1];
    expect(contexto.router.url)
      .withContext(`la ruta activa debe ser la del destino (${destino.href})`)
      .toBe(destino.href);

    const tabDestino = anchorDe(contexto.raiz, destino.href);
    expect(tabDestino.getAttribute('aria-selected'))
      .withContext(`la pestaña destino (${destino.id}) debe quedar seleccionada`)
      .toBe('true');
    expect(tabDestino.getAttribute('tabindex'))
      .withContext(`la pestaña destino (${destino.id}) debe ser el tab stop`)
      .toBe('0');

    for (const otra of PESTANAS.filter((pestana) => pestana.href !== destino.href)) {
      const enlace = anchorDe(contexto.raiz, otra.href);
      expect(enlace.getAttribute('aria-selected'))
        .withContext(`${otra.id} no es la ruta activa y no debe estar seleccionada`)
        .toBe('false');
      expect(enlace.getAttribute('tabindex'))
        .withContext(`${otra.id} no debe quedar en el orden de tabulación`)
        .toBe('-1');
    }

    const panel = contexto.raiz.querySelector('[role="tabpanel"]');
    expect(panel)
      .withContext('el panel de la ruta activa debe seguir presente tras la tecla')
      .toBeTruthy();
    expect(panel?.getAttribute('aria-labelledby'))
      .withContext('el panel debe etiquetarse con la pestaña del destino')
      .toBe(destino.id);

    // Navegación nativa: la tecla no abre ni simula pestañas desde JavaScript.
    expect(abrirPestana)
      .withContext('la barra no debe abrir ventanas ni pestañas desde el manejador de teclado')
      .not.toHaveBeenCalled();
    for (const pestana of PESTANAS) {
      expect(anchorDe(contexto.raiz, pestana.href).hasAttribute('target'))
        .withContext(`${pestana.href} debe conservar el destino nativo, sin target`)
        .toBe(false);
    }
  });
});
