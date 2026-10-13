/* Files for the resume / capture import, prepared in the browser before they are sent:
   images are re-encoded as JPEG (smaller, and no photo metadata such as location leaves the
   phone), very long screenshots are cut into pieces the reader can still read, and a PDF goes
   as it is. Nothing is kept on the server. */

export type UploadPart = { media_type: string; data: string };

export const MAX_PDF_BYTES = 2_500_000;
const MAX_PARTS = 6;
const MAX_TOTAL_CHARS = 4_200_000; // the proxy takes about 4.5 MB per request
const LONG_EDGE = 2576; // the reader's high-resolution limit
const TALL = 2.4; // taller than this (height / width) is cut into pieces
const PIECE = 2.2;

export class UploadError extends Error {}

function base64(blob: Blob): Promise<string> {
  return new Promise((done, fail) => {
    const r = new FileReader();
    r.onload = () => done(String(r.result).split(",", 2)[1] ?? "");
    r.onerror = () => fail(new UploadError("파일을 읽지 못했어요"));
    r.readAsDataURL(blob);
  });
}

function image(file: File): Promise<HTMLImageElement> {
  return new Promise((done, fail) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => { URL.revokeObjectURL(url); done(img); };
    img.onerror = () => { URL.revokeObjectURL(url); fail(new UploadError("이미지를 열지 못했어요. JPG나 PNG로 올려 주세요")); };
    img.src = url;
  });
}

async function jpeg(img: HTMLImageElement, top: number, height: number): Promise<UploadPart> {
  const w = img.naturalWidth;
  const scale = Math.min(1, LONG_EDGE / Math.max(w, height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(w * scale);
  canvas.height = Math.round(height * scale);
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new UploadError("이미지를 준비하지 못했어요");
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, top, w, height, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise<Blob | null>((done) => canvas.toBlob(done, "image/jpeg", 0.85));
  if (!blob) throw new UploadError("이미지를 준비하지 못했어요");
  return { media_type: "image/jpeg", data: await base64(blob) };
}

async function imageParts(file: File): Promise<UploadPart[]> {
  const img = await image(file);
  const w = img.naturalWidth, h = img.naturalHeight;
  if (!w || !h) throw new UploadError("이미지를 열지 못했어요");
  if (h / w <= TALL) return [await jpeg(img, 0, h)];
  // A long scroll capture: pieces about a phone screen tall, overlapping a little.
  const piece = Math.round(w * PIECE), step = Math.round(piece * 0.92);
  const parts: UploadPart[] = [];
  for (let top = 0; top < h; top += step) {
    parts.push(await jpeg(img, top, Math.min(piece, h - top)));
    if (top + piece >= h) break;
    if (parts.length >= MAX_PARTS) throw new UploadError("캡처가 너무 길어요. 두세 장으로 나눠서 올려 주세요");
  }
  return parts;
}

export async function prepareUpload(files: File[]): Promise<UploadPart[]> {
  const parts: UploadPart[] = [];
  for (const f of files) {
    if (f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf")) {
      if (f.size > MAX_PDF_BYTES) throw new UploadError("PDF는 2.5MB까지 올릴 수 있어요");
      parts.push({ media_type: "application/pdf", data: await base64(f) });
    } else if (f.type.startsWith("image/") || /\.(jpe?g|png|webp|heic)$/i.test(f.name)) {
      parts.push(...await imageParts(f));
    } else {
      throw new UploadError("PDF나 이미지 파일만 올릴 수 있어요");
    }
  }
  if (parts.length > MAX_PARTS) throw new UploadError("한 번에 올릴 수 있는 양을 넘었어요. 파일 수를 줄여 주세요");
  if (parts.reduce((n, p) => n + p.data.length, 0) > MAX_TOTAL_CHARS) {
    throw new UploadError("파일이 너무 커요. 파일 수를 줄이거나 작은 파일로 올려 주세요");
  }
  return parts;
}
