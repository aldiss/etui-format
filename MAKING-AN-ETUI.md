# Making an Etui collection: a brief for agents

Give this file to your agent, with `SPEC.md` and `validate.py` beside it, and say what you want collected. It is enough to make a valid `.etui` from audio files you have. `SPEC.md` is the contract: where this brief and the spec differ, the spec wins.

## What you are making

An `.etui` file is a ZIP archive holding:
- `collection.json`, the manifest: what plays, in what order, with titles, credits and pictures;
- the audio files, unchanged;
- optional pictures (a cover) and lyrics.

Any player that implements the spec opens it. The Etui app (iPhone, iPad, Mac) is one: it checks every file's size and SHA-256 before anything plays.

Everything the listener needs goes inside the file. Don't make the collection depend on a web page: a link to an artist's or an event's own page is fine, a link that holds the collection's own text isn't.

## What to ask the person, only when they haven't said

1. Which audio files, and in what order.
2. The collection's title. Then, if they care: a subtitle, who put it together (the curator), a cover picture, the language of the text.
3. For a club night or a concert: the event's name, venue, city, country and date (§3.2). For an album: the artist and the year.

Don't invent facts: a title, a date or a credit you can't take from the person, the files' own tags or a source you name is left out.

## The steps

**1. Lay out a folder**

```
my-collection/
  collection.json
  audio/01 First.mp3
  audio/02 Second.m4a
  images/cover.jpg
```

- Formats in 1.0: MP3, M4A/M4B (AAC or ALAC), AAC (ADTS), FLAC, Opus in Ogg, WAV, AIFF (§5.1). Not Ogg Vorbis.
- Paths are relative, use `/`, have no `..`, and are in Unicode NFC. No two paths may differ only in letter case. No `\ : * ? " < > |`, no part ending in a dot or a space, no part named like a Windows device (`CON`, `NUL`, `COM1`…) (§2.3). When you make file names from titles, clean them first: "Why?" can't be a file name.
- A cover is a JPEG or PNG, square, at least 1000×1000 pixels if you can, at most 4 MiB. Strip its EXIF, XMP and IPTC metadata, which can say where and when a photo was taken (§6): `exiftool -all= cover.jpg`, or save a copy without metadata from an image tool.

**2. Describe each audio file** (§5.1). For every file:
- `path`;
- `sha256`: 64 lowercase hex digits of the file's bytes;
- `bytes`: its size;
- `duration_ms`: recommended. Take it from `ffprobe -v error -show_entries format=duration -of csv=p=0 FILE` (seconds; multiply by 1000 and round). Other tools can differ by a few tens of milliseconds (`afinfo` counts an MP3's encoder padding); that is fine for whole files.

**3. Write `collection.json`** (§3). Required: `etui`, `id`, `revision`, `title`, `files`, `items`.

```json
{
  "etui": "1.0",
  "id": "6f1c3e5a-9b2d-4c7e-8a10-2d4f6b8c0e13",
  "revision": 1,
  "updated": "2026-11-15T15:30:00+01:00",
  "kind": "playlist",
  "title": "Sunday morning",
  "curator": {"name": "Ann"},
  "generator": {"name": "my-etui-maker", "version": "0.1"},
  "artwork": "images/cover.jpg",
  "files": [
    {"path": "audio/01 First.mp3", "sha256": "<64 hex>", "bytes": 4810233, "duration_ms": 241000},
    {"path": "audio/02 Second.m4a", "sha256": "<64 hex>", "bytes": 6120400, "duration_ms": 305500}
  ],
  "items": [
    {"id": "1", "file": "audio/01 First.mp3", "title": "First", "artist": "Some Artist"},
    {"id": "2", "file": "audio/02 Second.m4a", "title": "Second", "artist": "Another Artist"}
  ]
}
```

- `id`: a new random UUID, lowercase (`uuidgen | tr A-Z a-z`). Keep it for every later version of the same collection.
- `revision`: `1`. Each new version you publish takes the next number (§7).
- `updated`: an RFC 3339 time with seconds and an offset.
- `kind` (§3.1): `playlist` (the default), `event`, `album`, `audiobook`, `course`, `fragments` or `rym_list`. An event, an album or a list has its own object and sections: read §3.2, §3.3 and §5.2 first.
- Items play in array order. Each item names one file; a fragment adds `start_ms` and `end_ms` (§5.3).
- Credits: list people once in `people` and refer to them from items with a role, or give an item an `artist` line (§4, §5.3). When all you have is a tag's artist, use the `artist` line: a role you'd have to guess is better left out.
- `generator` names the program that wrote the file, if you want to; it is optional.
- Optional and worth having, when the person or a source you can name gives them: `reason` on an item (why it is here, only if the person said), `chapters`, `highlights`, `notes`, `source` (where a recording came from), `translations` (§3.4), `rights` (§11). Ask about `rights` and `source` if the person may share the file.

**4. Make the archive** (Appendix B). From inside the folder:

```
printf '%s' application/vnd.etui+zip > mimetype
zip -X -0 ../my-collection.etui mimetype
zip -X -D -n .mp3:.m4a:.m4b:.aac:.flac:.opus:.wav:.aiff:.aif:.jpg:.jpeg:.png -r ../my-collection.etui collection.json audio images
rm mimetype
```

`mimetype` goes first and stored, `collection.json` second, and the audio stored, not compressed. Don't use the Finder's Compress.

When a file name has letters beyond ASCII (Cyrillic, `é`), use the Python way below instead: the `zip` tool on a Mac writes such names in UTF-8 but doesn't set the archive's UTF-8 flag, which the spec asks for (§2.1). Python's `zipfile` sets it by itself.

**5. Check it**

```
python3 validate.py my-collection.etui
```

It needs only Python 3's standard library. Fix everything it calls INVALID, and read its warnings. A valid file prints `VALID`.

**6. Hand it over.** The file travels any way files do: AirDrop, a message, a cloud folder, a website. In Etui:
- on iPhone or iPad, open the file from Files or AirDrop, or with "Open in… ▸ Etui" from another app;
- on a Mac, double-click it.

Etui shows what it found, checks it, and adds it to the library.

**7. A new version.** Same `id`, `revision` one higher, a new `updated`. Keep each item's `id` for the same recording, so listeners keep their place and their marks (§7).

## In Python, standard library only

A sketch of steps 2 to 4 for a plain playlist. Adapt it; check the result with `validate.py`.

```python
import hashlib, json, subprocess, uuid, zipfile, datetime
from pathlib import Path

AUDIO = {".mp3", ".m4a", ".m4b", ".aac", ".flac", ".opus", ".wav", ".aiff", ".aif"}

def duration_ms(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
        return round(float(out.stdout.strip()) * 1000)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None

def make(folder, title, out):
    folder = Path(folder)
    tracks = sorted(p for p in (folder / "audio").iterdir() if p.suffix.lower() in AUDIO)
    files, items = [], []
    for n, p in enumerate(tracks, 1):
        rel = p.relative_to(folder).as_posix()
        entry = {"path": rel, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
        ms = duration_ms(p)
        if ms:
            entry["duration_ms"] = ms
        files.append(entry)
        items.append({"id": str(n), "file": rel, "title": p.stem})
    manifest = {"etui": "1.0", "id": str(uuid.uuid4()), "revision": 1,
                "updated": datetime.datetime.now().astimezone().replace(microsecond=0).isoformat(),
                "kind": "playlist", "title": title, "files": files, "items": items}
    cover = folder / "images" / "cover.jpg"
    if cover.is_file():
        manifest["artwork"] = "images/cover.jpg"
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("mimetype", "application/vnd.etui+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("collection.json", json.dumps(manifest, ensure_ascii=False, indent=1),
                   compress_type=zipfile.ZIP_DEFLATED)
        for p in tracks + ([cover] if cover.is_file() else []):
            z.write(p, p.relative_to(folder).as_posix(), compress_type=zipfile.ZIP_STORED)
```

Item titles from file names are a start: put the real titles and artists in before you hand the file over.

## What trips producers up

- **Types are strict** (§3): `revision` and every `*_ms` are integers (`1`, not `1.0` or `"1"`); text has no control characters and is 1 to 1,024 bytes; no HTML or Markdown in any text.
- **Times** carry seconds and an offset: `2026-11-15T23:00:00+01:00`, not `2026-11-15 23:00`.
- **UUIDs** are lowercase.
- **Links** are `https` only, with no user name or password in them.
- **Every path in the manifest** matches exactly one file, letter for letter, and each audio file is listed once.
- **Dates and countries:** a `date` is `YYYY-MM-DD` and must exist; a country is two capital letters (`DE`).
- **An event's sections** list their items next to each other, in order (§5.2).

## Rights

The format grants no rights (§11). Whoever makes or shares a collection answers for being allowed to. `rights` and `source` let you say what applies and where each recording came from.

## Files

- `SPEC.md`: the Etui format, version 1.0 (draft 3).
- `validate.py`: the checker, standard library only.
- `examples/`: a minimal manifest, an event, an album, an audiobook, fragments, a RateYourMusic round, a complete archive, and invalid cases with what makes each one invalid.
