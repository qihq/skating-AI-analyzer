import { createAdaptiveSharePoster, type ShareImageResult } from "./shareCanvas";
import { paginateShareDocument, type ShareDocument } from "./shareLayout";

export type ShareDocumentExport = { pages: ShareImageResult[] };

export async function exportShareDocument(document: ShareDocument): Promise<ShareDocumentExport> {
  const pages = paginateShareDocument(document);
  const results = await Promise.all(pages.map((page) => createAdaptiveSharePoster({
    eyebrow: page.eyebrow,
    title: page.pageCount > 1 ? `${page.title} (${page.pageNumber}/${page.pageCount})` : page.title,
    subtitle: page.subtitle,
    intro: page.intro,
    sections: page.sections,
    footer: page.footer,
    filename: page.pageCount > 1 ? page.filename.replace(/(\.[^.]+)?$/, `-${page.pageNumber}$1`) : page.filename,
  })));
  return { pages: results };
}
