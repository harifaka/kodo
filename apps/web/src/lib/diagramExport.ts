/**
 * Client-side diagram export (Phase 14).
 *
 * Everything here is a pure browser download: nothing is uploaded and no file is ever written to
 * the scanned workspace, the sandbox or the guarded apply pipeline.
 */

export type ExportTheme = 'dark' | 'light';

export const EXPORT_BACKGROUND: Record<ExportTheme, string> = {
  dark: '#0b0f16',
  light: '#ffffff',
};

export class DiagramExportError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DiagramExportError';
  }
}

/** `My Api (local)` -> `my-api-local`, never empty. */
export function slugifyFilename(value: string | null | undefined, fallback = 'kodo'): string {
  const slug = (value ?? '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return slug || fallback;
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = 'noopener';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Revoke on the next tick so Safari has started the download.
  window.setTimeout(() => URL.revokeObjectURL(url), 4_000);
}

export function downloadText(text: string, filename: string, mime = 'text/plain;charset=utf-8'): void {
  downloadBlob(new Blob([text], { type: mime }), filename);
}

function dataUrlFromSvg(svgMarkup: string): string {
  // `encodeURIComponent` (not btoa) keeps non-ASCII labels and `#hex` colours intact.
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgMarkup)}`;
}

/** Intrinsic size of an SVG document, preferring the `viewBox` over the `width`/`height` hints. */
export function svgMetrics(svgMarkup: string): { width: number; height: number } {
  const host = document.createElement('div');
  host.innerHTML = svgMarkup;
  const element = host.querySelector('svg');
  if (!element) {
    throw new DiagramExportError('The rendered diagram could not be read as SVG.');
  }

  const viewBox = element.getAttribute('viewBox');
  if (viewBox) {
    const parts = viewBox.split(/[\s,]+/).map(Number);
    if (parts.length === 4 && parts[2] > 0 && parts[3] > 0) {
      return { width: parts[2], height: parts[3] };
    }
  }

  const width = Number.parseFloat(element.getAttribute('width') ?? '');
  const height = Number.parseFloat(element.getAttribute('height') ?? '');
  if (Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0) {
    return { width, height };
  }

  throw new DiagramExportError('This diagram has no measurable size to export.');
}

/**
 * Turn a rendered `<svg>` fragment into a standalone document: explicit `xmlns`, explicit
 * `width`/`height` from the `viewBox`, and a solid background rect so the image is legible in
 * GitHub PRs, Confluence and Notion.
 */
export function buildStandaloneSvg(svgMarkup: string, theme: ExportTheme): string {
  const host = document.createElement('div');
  host.innerHTML = svgMarkup;
  const element = host.querySelector('svg');
  if (!element) {
    throw new DiagramExportError('The rendered diagram could not be read as SVG.');
  }

  const { width, height } = svgMetrics(svgMarkup);
  element.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  element.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink');
  element.setAttribute('width', String(Math.ceil(width)));
  element.setAttribute('height', String(Math.ceil(height)));
  element.setAttribute('viewBox', `0 0 ${width} ${height}`);
  element.style.removeProperty('max-width');
  element.style.removeProperty('width');
  element.style.removeProperty('height');

  const background = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  background.setAttribute('x', '0');
  background.setAttribute('y', '0');
  background.setAttribute('width', String(width));
  background.setAttribute('height', String(height));
  background.setAttribute('fill', EXPORT_BACKGROUND[theme]);
  // Inline style wins over any theme CSS rule that might target rects inside the document.
  background.setAttribute('style', `fill:${EXPORT_BACKGROUND[theme]};stroke:none;`);
  element.insertBefore(background, element.firstChild);

  return new XMLSerializer().serializeToString(element);
}

async function loadImage(markup: string): Promise<HTMLImageElement> {
  const image = new Image();
  const loaded = new Promise<void>((resolve, reject) => {
    image.onload = () => resolve();
    image.onerror = () =>
      reject(
        new DiagramExportError(
          'The browser could not decode the diagram image. Use Export SVG for this diagram instead.',
        ),
      );
  });
  image.src = dataUrlFromSvg(markup);
  await loaded;
  return image;
}

function isBlankPixel(data: Uint8ClampedArray, index: number, background: [number, number, number]): boolean {
  return (
    data[index] === background[0] && data[index + 1] === background[1] && data[index + 2] === background[2]
  );
}

function hexToRgb(hex: string): [number, number, number] {
  const value = hex.replace('#', '');
  return [
    Number.parseInt(value.slice(0, 2), 16),
    Number.parseInt(value.slice(2, 4), 16),
    Number.parseInt(value.slice(4, 6), 16),
  ];
}

/**
 * Rasterise an SVG at `scale`x with a solid background.
 *
 * `foreignObject`-based labels and cross-origin assets can make the canvas unreadable in some
 * browsers; both failure modes surface as a clear {@link DiagramExportError} instead of a crash or
 * a silently blank file.
 */
export async function svgToPngBlob(svgMarkup: string, theme: ExportTheme, scale = 2): Promise<Blob> {
  const { width, height } = svgMetrics(svgMarkup);
  const background = EXPORT_BACKGROUND[theme];
  const image = await loadImage(svgMarkup);

  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));

  const context = canvas.getContext('2d');
  if (!context) {
    throw new DiagramExportError('This browser cannot rasterise diagrams (no 2D canvas support).');
  }

  context.fillStyle = background;
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);

  const rgb = hexToRgb(background);
  try {
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
    const stride = 4 * 7; // sample a coarse grid: cheap and enough to detect an empty render
    let drawn = 0;
    for (let index = 0; index < pixels.data.length - 4; index += stride) {
      if (!isBlankPixel(pixels.data, index, rgb)) {
        drawn += 1;
        if (drawn > 40) {
          break;
        }
      }
    }
    if (drawn === 0) {
      throw new DiagramExportError(
        'The browser produced an empty image. Try Export SVG instead, or a different browser.',
      );
    }
  } catch (reason) {
    if (reason instanceof DiagramExportError) {
      throw reason;
    }
    throw new DiagramExportError(
      'The browser blocked reading the rendered diagram (tainted canvas). Try Export SVG instead.',
    );
  }

  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'));
  if (!blob) {
    throw new DiagramExportError('The browser could not encode the PNG. Try Export SVG instead.');
  }
  return blob;
}

/** Data-URL variant used by the React Flow (html-to-image) exporter. */
export async function dataUrlToBlob(dataUrl: string): Promise<Blob> {
  const response = await fetch(dataUrl);
  return response.blob();
}
