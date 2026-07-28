import type { SharePosterSection } from "./shareCanvas";

export type ShareDocument = {
  title: string;
  subtitle: string;
  eyebrow: string;
  intro?: string;
  footer?: string;
  filename: string;
  sections: SharePosterSection[];
};

export type ShareDocumentPage = Omit<ShareDocument, "sections"> & { sections: SharePosterSection[]; pageNumber: number; pageCount: number };

function sectionWeight(section: SharePosterSection) {
  return (section.label.length + section.title.length + (section.body?.length ?? 0) + (section.meta?.length ?? 0)) * 1.9 + 180;
}

// Page only between semantic cards; wrapped text and card content always stay together.
export function paginateShareDocument(document: ShareDocument, maxWeight = 6800): ShareDocumentPage[] {
  const chunks: SharePosterSection[][] = [[]];
  let weight = 1200 + document.title.length * 2 + document.subtitle.length;
  document.sections.forEach((section) => {
    const nextWeight = sectionWeight(section);
    if (chunks[chunks.length - 1].length && weight + nextWeight > maxWeight) {
      chunks.push([]);
      weight = 900;
    }
    chunks[chunks.length - 1].push(section);
    weight += nextWeight;
  });
  const pageCount = chunks.length;
  return chunks.map((sections, index) => ({ ...document, sections, pageNumber: index + 1, pageCount }));
}
