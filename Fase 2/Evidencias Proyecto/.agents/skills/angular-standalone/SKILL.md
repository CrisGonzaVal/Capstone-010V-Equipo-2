---
name: angular-standalone
description: "Angular 18 standalone conventions for this repo - no @NgModule, inject() over constructors, signal()/computed() over RxJS BehaviorSubject, Tailwind classes over hardcoded CSS. Use whenever creating, editing or reviewing ANY file under frontend/src - components, services, guards, interceptors, routes, pipes, or templates."
---

# Angular 18 Standalone

Regla de oro del proyecto (`docs/spec/stack.md` §3): **cero `NgModule`**, todo standalone con `inject()`, estado con signals, y **Tailwind en el template en vez de CSS quemado**.

## Reglas

1. **Nunca uses `@NgModule`.** Todo componente es `standalone: true`. No crees ni modifiques un `*.module.ts`. Si necesitas importar algo en un componente, va en su array `imports:`.
2. **`inject()`, nunca constructor.** No escribas `constructor(private readonly x: X) {}`. Usá `private readonly x = inject(X);`.
3. **Signals, no `BehaviorSubject`.** Estado local y reactividad con `signal()`, derivado con `computed()`. `BehaviorSubject`/`Subject` solo si hay un flujo de eventos que de verdad lo justifique (streams HTTP largos, websockets).
4. **Control flow nativo.** `@if` / `@for` / `@switch` en vez de `*ngIf` / `*ngFor` / `*ngSwitch`. Con eso no importes `CommonModule`.
5. **Nada de CSS quemado en el template.** Ni `styles: []` en el componente, ni `<style>` inline, ni clases utilitarias inventadas. Todo con clases de Tailwind. Solo `styles.css` global y `styles.scss` en `src/` pueden tener reglas propias.
6. **Nombres `kebab-case.ts`.** `ticket-kanban.component.ts`, `auth.service.ts`, `role.guard.ts`.
7. **Estructura por feature.** Lo reutilizable va en `src/app/shared/`, lo de dominio en `src/app/features/<dominio>/` con su `routes.ts` y su `services/`. Los services globales en `core/services/`.

## Español en identificadores

Variables, propiedades, funciones, métodos y campos de interfaces se escriben **en español** (`AGENTS.md` §6).

**La regla del sufijo:** en Angular el sufijo es vocabulario del framework y **se conserva**; lo que se traduce es el dominio.

| Archivo | Clase | Nota |
|---|---|---|
| `auth.service.ts` | `AutenticacionService` | dominio traducido, sufijo intacto |
| `auth.guard.ts` | `AutenticacionGuard` | idem |
| `role.guard.ts` | `RolGuard` | idem |
| `token.interceptor.ts` | `TokenInterceptor` | "token" es préstamo aceptado |
| `inventario.component.ts` | `InventarioComponent` | dominio ya en español |
| `inventario.service.ts` | `InventarioService` | idem |

**No se renombran:** los sufijos `Component`, `Service`, `Guard`, `Interceptor`, `Pipe`, `Routes`; los nombres de archivo; ni la API de Angular (`Component`, `Injectable`, `signal`, `computed`, `inject`, `input`, `output`, `Routes`, `loadComponent`, `loadChildren`, `CanActivateFn`, `HttpInterceptorFn`).

```ts
// ❌ INGLÉS
export class TicketService {
  private apiUrl = '/api/v1/tickets';
  stockList: StockItem[] = [];
  getTickets() { return this.http.get(this.apiUrl); }
}

// ✅ ESPAÑOL
export class TicketService {
  private readonly urlApi = '/api/v1/tickets';
  readonly listaStock: StockItem[] = [];
  obtenerTickets() { return this.http.get(this.urlApi); }
}
```

Ojo con `stockList`: en español se escribe `listaStock` (un solo término, sin espacio). No `stockLista` ni `lista_Stock`.

## Antes / después

### Componente

```ts
// ❌ ANTIGUO
@NgModule({
  declarations: [TicketKanbanComponent],
  imports: [CommonModule, ReactiveFormsModule],
  exports: [TicketKanbanComponent],
})
export class TicketSharedModule {}

@Component({
  selector: 'app-ticket-kanban',
  templateUrl: './ticket-kanban.component.html',
})
export class TicketKanbanComponent implements OnInit, OnDestroy {
  tickets = new BehaviorSubject<Ticket[]>([]);
  filtrados$ = this.tickets.asObservable().pipe(map((t) => t.filter(...)));

  constructor(private readonly ticketService: TicketService) {}

  ngOnInit() {
    this.subscription = this.ticketService.cargar().subscribe((t) => this.tickets.next(t));
  }
}
```

```ts
// ✅ STANDALONE
@Component({
  selector: 'app-ticket-kanban',
  standalone: true,
  imports: [ReactiveFormsModule],
  templateUrl: './ticket-kanban.component.html',
})
export class TicketKanbanComponent {
  private readonly ticketService = inject(TicketService);

  readonly busqueda = signal('');
  readonly tickets = signal<Ticket[]>([]);
  readonly filtrados = computed(() =>
    this.tickets().filter((t) => t.ref.includes(this.busqueda())),
  );

  constructor() {
    this.ticketService.cargar().subscribe((t) => this.tickets.set(t));
  }
}
```

`imports: [ReactiveFormsModule]` en vez de `CommonModule` es válido y correcto: los módulos de Angular que no son tus componentes se importan en el componente que los usa. Lo que no se hace es declarar tus propios componentes dentro de un módulo.

### Template

```html
<!-- ❌ ANTIGUO -->
<div class="card" [style.padding.px]="12">
  <div *ngFor="let t of filtrados$ | async">{{ t.ref }}</div>
</div>
```

```html
<!-- ✅ STANDALONE + TAILWIND -->
<div class="rounded-lg border border-slate-200 p-3">
  @for (t of filtrados(); track t.ticketId) {
    <div>{{ t.ref }}</div>
  } @empty {
    <p class="text-slate-500">Sin tickets para este filtro</p>
  }
</div>
```

`track` es **obligatorio** en `@for` - sin track, Angular no compila.

### Servicio

```ts
// ❌ ANTIGUO
@Injectable()
export class AuthService {
  constructor(private http: HttpClient) {}
}

// ✅ STANDALONE
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
}
```

`providedIn: 'root'` reemplaza al `providers: [AuthService]` que antes iba en `AppModule`. Por eso no hace falta ningun modulo.

### Inputs y outputs

```ts
// ❌ ANTIGUO
@Input() ticket!: Ticket;
@Output() refresh = new EventEmitter<void>();

// ✅ MODERNO
readonly ticket = input.required<Ticket>();
readonly refresh = output<void>();
```

`input()` / `output()` reemplazan a `@Input()` / `@Output()`, y no necesitan ser inicializados en el constructor.

## Cuando ademas aplicar otras skills

- **Creando un componente o vista NUEVA** (no editando uno existente): carga `frontend-design` para la direccion visual. Esta skill dice *como* construirlo, aquella decide *como se ve*.
- **Despues de escribir UI**: carga `web-design-guidelines` para auditar accesibilidad (contraste, foco visible, `prefers-reduced-motion`, responsive).
- **Escribiendo el `.spec.ts` del componente o servicio**: carga `tdd`. Test primero, por la interfaz publica del componente (`componentRef.setInput`, `fixture.componentInstance` sobre signals), nunca mockeando signals internas.

## Nada de esto aplica a

`backend/`. Para Python usa la skill `fastapi-pydantic-v2`.
