import { ChangeDetectionStrategy, Component, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppComponent {
  readonly titulo = 'CompuStock ERP';

  /** `sidebarAbierto` es un signal, no un booleano mutable: el toggle re-renderiza solo. */
  readonly sidebarAbierto = signal(true);

  alternarSidebar(): void {
    this.sidebarAbierto.update((abierto) => !abierto);
  }
}