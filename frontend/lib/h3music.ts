// The film's music track in the editor: its waveform for the timeline, decoded once per song.
import { shallowReactive } from "vue";
import { stableUrl } from "./h3studio";

/** Peaks per second of song. */
const RESOLUTION = 40;

export interface Song {
  duration: number;
  /** Peak levels 0–1, `RESOLUTION` per second. */
  peaks: Float32Array;
}

const songs = shallowReactive(new Map<string, Song | "loading" | "failed">());

/** The song's waveform, or undefined until it has been decoded (the map is reactive). */
export function songOf(media: string): Song | undefined {
  const known = songs.get(media);
  if (known === undefined) void load(media);
  return typeof known === "object" ? known : undefined;
}

async function load(media: string) {
  songs.set(media, "loading");
  try {
    const data = await (await fetch(stableUrl(media))).arrayBuffer();
    const context = new OfflineAudioContext(1, 1, 44100);
    const audio = await context.decodeAudioData(data);
    songs.set(media, { duration: audio.duration, peaks: peaksOf(audio) });
  } catch {
    songs.set(media, "failed");
  }
}

function peaksOf(audio: AudioBuffer): Float32Array {
  const step = Math.max(1, Math.round(audio.sampleRate / RESOLUTION));
  const peaks = new Float32Array(Math.ceil(audio.length / step));
  for (let c = 0; c < audio.numberOfChannels; c++) {
    const data = audio.getChannelData(c);
    for (let i = 0; i < data.length; i++) {
      const v = Math.abs(data[i]!);
      const k = (i / step) | 0;
      if (v > peaks[k]!) peaks[k] = v;
    }
  }
  const top = peaks.reduce((m, v) => Math.max(m, v), 0) || 1;
  return peaks.map((v) => v / top);
}

/** `count` peak levels evenly from `from` to `to` (song seconds); silence past the song's end. */
export function wave(song: Song, from: number, to: number, count: number): number[] {
  return Array.from({ length: count }, (_, i) => {
    const a = Math.floor((from + ((to - from) * i) / count) * RESOLUTION);
    const b = Math.max(a + 1, Math.floor((from + ((to - from) * (i + 1)) / count) * RESOLUTION));
    let peak = 0;
    for (let k = Math.max(0, a); k < Math.min(b, song.peaks.length); k++)
      peak = Math.max(peak, song.peaks[k]!);
    return peak;
  });
}
