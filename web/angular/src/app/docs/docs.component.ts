import { Component, OnInit, SecurityContext } from '@angular/core';
import { NgFor, NgIf } from '@angular/common';
import { RouterLink, ActivatedRoute, Router } from '@angular/router';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { marked } from 'marked';
import { MatListModule } from '@angular/material/list';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatDividerModule } from '@angular/material/divider';
import { ApiService, DocPage } from '../api.service';

@Component({
  selector: 'app-docs',
  standalone: true,
  imports: [NgFor, NgIf, RouterLink, MatListModule, MatProgressSpinnerModule, MatDividerModule],
  templateUrl: './docs.component.html',
})
export class DocsComponent implements OnInit {
  pages: DocPage[] = [];
  currentSlug = '';
  currentTitle = '';
  renderedHtml: SafeHtml = '';
  loading = false;
  error = '';

  constructor(
    private api: ApiService,
    private route: ActivatedRoute,
    private router: Router,
    private sanitizer: DomSanitizer,
  ) {}

  ngOnInit(): void {
    this.api.getDocs().subscribe({
      next: data => {
        this.pages = data.pages;
        const slug = this.route.snapshot.paramMap.get('slug');
        if (!slug && data.pages.length > 0) {
          this.router.navigate(['/docs', data.pages[0].slug], { replaceUrl: true });
        }
      },
    });

    this.route.paramMap.subscribe(params => {
      const slug = params.get('slug');
      if (slug) this.loadPage(slug);
    });
  }

  loadPage(slug: string): void {
    this.loading = true;
    this.currentSlug = slug;
    this.error = '';
    this.renderedHtml = '';

    this.api.getDoc(slug).subscribe({
      next: data => {
        this.currentTitle = data.title;
        const html = marked.parse(data.content) as string;
        this.renderedHtml = this.sanitizer.bypassSecurityTrustHtml(html);
        this.loading = false;
        setTimeout(() => {
          this.stampHeadingIds();
          if (window.location.hash) {
            const el = document.getElementById(window.location.hash.slice(1));
            if (el) el.scrollIntoView({ behavior: 'smooth' });
          }
        }, 0);
      },
      error: () => {
        this.error = 'Page not found.';
        this.loading = false;
      },
    });
  }

  private stampHeadingIds(): void {
    const container = document.getElementById('doc-render');
    if (!container) return;
    container.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(el => {
      if (!el.id) {
        el.id = (el.textContent ?? '')
          .toLowerCase()
          .replace(/[^\w\s-]/g, '')
          .trim()
          .replace(/\s+/g, '-');
      }
    });
  }
}
