/**
 * One page of a PDF, drawn in the app, with the cited quote highlighted.
 *
 * pdf.js is imported only when a PDF source is opened, so the chat page does not carry it.
 * The quote is found in the page's text layer by matching normalised words; when it cannot
 * be placed (two columns, a hyphen across a line) the page still shows, unhighlighted.
 */

import { useEffect, useRef, useState } from "react";

interface Props {
  url: string;
  page: number;
  quote: string;
}

const norm = (text: string): string => text.toLowerCase().replace(/\s+/g, " ").trim();

export function PdfPage({ url, page, quote }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const layer = useRef<HTMLDivElement>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [found, setFound] = useState<boolean | null>(null);

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        const worker = await import("pdfjs-dist/build/pdf.worker.min.mjs?url");
        pdfjs.GlobalWorkerOptions.workerSrc = worker.default;

        const doc = await pdfjs.getDocument(url).promise;
        const pdfPage = await doc.getPage(Math.min(Math.max(page, 1), doc.numPages));
        const viewport = pdfPage.getViewport({ scale: 1.3 });
        const node = canvas.current;
        const text = layer.current;
        if (!live || !node || !text) return;

        node.width = viewport.width;
        node.height = viewport.height;
        await pdfPage.render({ canvasContext: node.getContext("2d")!, viewport }).promise;

        const content = await pdfPage.getTextContent();
        text.replaceChildren();
        text.style.width = `${viewport.width}px`;
        text.style.height = `${viewport.height}px`;
        const items = content.items.filter((i): i is typeof i & { str: string; transform: number[] } =>
          "str" in i,
        );

        // Which text items the quote covers: join them with spaces and find the quote.
        let joined = "";
        const starts = items.map((item) => {
          const at = joined.length;
          joined += `${norm(item.str)} `;
          return at;
        });
        const at = quote ? joined.indexOf(norm(quote)) : -1;
        const end = at + norm(quote).length;

        items.forEach((item, index) => {
          const covered = at >= 0 && starts[index]! < end && starts[index]! + norm(item.str).length > at;
          if (!covered) return;
          const [x, y] = pdfjs.Util.applyTransform([item.transform[4]!, item.transform[5]!], viewport.transform);
          const height = Math.hypot(item.transform[2]!, item.transform[3]!) * viewport.scale;
          const mark = document.createElement("span");
          mark.className = "pdf-mark";
          mark.style.left = `${x}px`;
          mark.style.top = `${y! - height}px`;
          mark.style.width = `${("width" in item ? (item.width as number) : 0) * viewport.scale}px`;
          mark.style.height = `${height}px`;
          text.appendChild(mark);
        });
        setFound(at >= 0);
      } catch (error) {
        if (live) setFailure(error instanceof Error ? error.message : String(error));
      }
    })();
    return () => {
      live = false;
    };
  }, [url, page, quote]);

  if (failure) return <p className="nb-error">Could not show the PDF: {failure}</p>;
  return (
    <div className="pdf-view">
      {found === false && <p className="empty">The quote could not be located on this page.</p>}
      <div className="pdf-stage">
        <canvas ref={canvas} />
        <div ref={layer} className="pdf-marks" />
      </div>
    </div>
  );
}
