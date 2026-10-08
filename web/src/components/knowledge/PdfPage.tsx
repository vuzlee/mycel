/** The page of a PDF a quote sits on, drawn in the app, with the quote highlighted. */

import { useEffect, useRef, useState } from "react";
import type { PDFPageProxy } from "pdfjs-dist";

interface Props {
  url: string;
  first: number;
  last: number;
  quote: string;
}

/** Letters and digits only, lower case: what survives every way of splitting a line. */
const key = (text: string): string => text.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");

type Item = { str: string; transform: number[]; width: number };

/** The items the quote covers on this page, or null when it is not there. */
function cover(items: Item[], quote: string): Item[] | null {
  const wanted = key(quote);
  if (!wanted) return null;
  let joined = "";
  const starts = items.map((item) => {
    const at = joined.length;
    joined += key(item.str);
    return at;
  });
  const at = joined.indexOf(wanted);
  if (at < 0) return null;
  const end = at + wanted.length;
  return items.filter((item, i) => {
    const length = key(item.str).length;
    return length > 0 && starts[i]! < end && starts[i]! + length > at;
  });
}

export function PdfPage({ url, first, last, quote }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const layer = useRef<HTMLDivElement>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [found, setFound] = useState<boolean | null>(null);
  const [shown, setShown] = useState<number | null>(null);

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        const worker = await import("pdfjs-dist/build/pdf.worker.min.mjs?url");
        pdfjs.GlobalWorkerOptions.workerSrc = worker.default;

        const doc = await pdfjs.getDocument(url).promise;
        const clamp = (n: number): number => Math.min(Math.max(n, 1), doc.numPages);
        const from = clamp(first);
        const to = Math.max(from, clamp(last));

        let page: PDFPageProxy | null = null;
        let marked: Item[] | null = null;
        for (let n = from; n <= to && !marked; n++) {
          const candidate = await doc.getPage(n);
          const content = await candidate.getTextContent();
          const items = content.items.filter((i): i is typeof i & Item => "str" in i);
          marked = cover(items, quote);
          if (marked || !page) page = candidate;
        }
        const node = canvas.current;
        const text = layer.current;
        if (!live || !page || !node || !text) return;

        // Fit the frame's width; drawn at the device's pixel ratio so text stays sharp.
        const fit =
          (node.parentElement?.parentElement?.clientWidth ?? 600) /
          page.getViewport({ scale: 1 }).width;
        const viewport = page.getViewport({ scale: fit });
        const ratio = window.devicePixelRatio || 1;
        node.width = Math.floor(viewport.width * ratio);
        node.height = Math.floor(viewport.height * ratio);
        node.style.width = `${viewport.width}px`;
        node.style.height = `${viewport.height}px`;
        await page.render({
          canvasContext: node.getContext("2d")!,
          viewport,
          transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
        }).promise;

        text.replaceChildren();
        text.style.width = `${viewport.width}px`;
        text.style.height = `${viewport.height}px`;
        for (const item of marked ?? []) {
          const [x, y] = pdfjs.Util.applyTransform(
            [item.transform[4]!, item.transform[5]!],
            viewport.transform,
          );
          const height = Math.hypot(item.transform[2]!, item.transform[3]!) * viewport.scale;
          const mark = document.createElement("span");
          mark.className = "pdf-mark";
          mark.style.left = `${x}px`;
          mark.style.top = `${y! - height}px`;
          mark.style.width = `${item.width * viewport.scale}px`;
          mark.style.height = `${height}px`;
          text.appendChild(mark);
        }
        text.firstElementChild?.scrollIntoView({ block: "center" });
        setShown(page.pageNumber);
        setFound(marked !== null);
      } catch (error) {
        if (live) setFailure(error instanceof Error ? error.message : String(error));
      }
    })();
    return () => {
      live = false;
    };
  }, [url, first, last, quote]);

  if (failure) return <p className="kb-error">Could not show the PDF: {failure}</p>;
  return (
    <div className="pdf-view">
      {found === false && <p className="empty">The quote could not be located on this page.</p>}
      {shown !== null && shown !== first && <p className="empty">Page {shown}</p>}
      <div className="pdf-stage">
        <canvas ref={canvas} />
        <div ref={layer} className="pdf-marks" />
      </div>
    </div>
  );
}
