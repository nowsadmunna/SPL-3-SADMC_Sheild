import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { ThemeService } from './core/theme.service';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  // Injecting here (root component, constructed first) applies the saved/
  // system theme to <html> before any page renders.
  constructor(private readonly theme: ThemeService) {}
}
