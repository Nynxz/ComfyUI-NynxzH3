// A studio file carried out of the page on a drag.
import { mediaKind, setImageDragData } from "@/framework";
import { stableUrl } from "./h3studio";

/** The file on the drag, as ComfyUI's asset browser carries one: another app (a chat box, say)
 *  fetches it from its URL, ComfyUI and ZenKit take it as that file, and Chrome can drop it on the
 *  desktop. */
export function carryMedia(e: DragEvent, media: string) {
  const dt = e.dataTransfer;
  if (!dt) return;
  const parts = media.split("/");
  const filename = parts.pop()!;
  const [type, ...subfolder] = parts;
  const comfyType = type === "input" || type === "output" || type === "temp" ? type : undefined;
  setImageDragData(e, {
    url: stableUrl(media),
    ref: media,
    filename,
    ...(comfyType ? { type: comfyType, subfolder: subfolder.join("/") } : {}),
  });
  // A plain-text copy makes some chat boxes paste the address instead of the picture.
  dt.clearData("text/plain");
  const absolute = new URL(stableUrl(media), location.href).href;
  const mime = { image: "image", video: "video", audio: "audio" }[mediaKind(media)];
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  dt.setData("DownloadURL", `${mime}/${ext === "jpg" ? "jpeg" : ext}:${filename}:${absolute}`);
}
