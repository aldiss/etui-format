# The Etui format, version 1.0

Status: **draft 3**, published for comment on 2026-11-15. It may change before 1.0 is final; a later draft keeps today's files readable wherever it can. The format is called Etui: an étui is a small fitted case for a set of precious things.

## 1. What it is

A collection is a set of audio files plus what's needed to play them well:
- their order and titles;
- who made them;
- artwork, chapters and highlights;
- for a live event, where and when it happened and who played;
- the words of songs, and the text in as many languages as the producer has.

It comes as one `.etui` file or as a folder. Anyone can make one: a script, an app, an AI agent, or a person with a text editor and a ZIP tool (Appendix B). Any player that implements this spec can open it.

The format groups and describes audio of any kind: DJ sets from a club night, a classical recording, an audiobook, a lecture series, or a handful of favourite fragments.

**Goals**
- **Self-contained:** one file, or one folder, holds the audio and its description. It works offline and travels any way files do: AirDrop, a website, a cloud drive, a USB stick.
- **Easy to produce:** one JSON file next to the audio. Nothing else is needed beyond a ZIP tool and SHA-256.
- **Safe to open:** a reader can check every audio file before it plays anything.
- **Updatable:** a new revision of a collection can replace the old one, and each listener keeps their place and marks.
- **Extensible:** producers can add their own data without breaking readers.

**Not goals**
- **Hosting, streaming or a network protocol.** Where a file lives is up to whoever shares it.
- **Rights management or DRM** (see §11).
- **Listener data.** Positions and marks stay in the listener's app.

**Words**
- MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are used as in RFC 2119.
- **Producer:** software or a person that writes collections.
- **Reader:** software that opens and plays them.
- **Listener:** the person using a reader.
- **Listener data:** what a reader keeps for its listener: the position reached in each item, and marks (moments the listener saved).
- **Slot:** one act's place in an event's running order.

## 2. Containers

A collection comes in two forms with the same contents:

| Form | What it is | Use it |
|---|---|---|
| **Archive** | A ZIP file, normally named `<anything>.etui` | To send or publish one file |
| **Folder** | A folder holding the same files | While producing, or in a shared cloud folder |

Both have the manifest, `collection.json`, at their root. The manifest names every other file by its path (§2.3).

### 2.1 The archive

- **ZIP:** it's a ZIP file as in the PKWARE APPNOTE. Every file entry uses compression method 0 (stored) or 8 (deflate). Audio SHOULD be stored: it's compressed already, and a stored entry can be read in place.
- **ZIP64:** it MUST be used when a size, an offset or the entry count doesn't fit its 32-bit or 16-bit field. Readers MUST support it, because collections of several gigabytes are normal.
- **First and second entries:**
  - Producers SHOULD write, as the first entry, a file named `mimetype`, stored, with no extra field and no data descriptor, containing exactly the 24 bytes `application/vnd.etui+zip`. The archive then shows `mimetype` at byte 30 and the media type at byte 38, so tools can recognise it from its first bytes, as EPUB does.
  - Producers SHOULD write `collection.json` as the second entry, so a reader streaming the archive meets the manifest before the audio.
  - Readers MUST NOT require either.
- **Entry names:**
  - Names MUST be valid UTF-8 and, for files, follow §2.3. Producers SHOULD set general-purpose flag bit 11. Readers MUST decode every name as UTF-8 whether or not bit 11 is set, because common tools never set it.
  - An entry whose name isn't valid UTF-8 fails rule 2 (§9).
  - Directory entries (a name ending in `/` with no data) MAY be present. Readers ignore them; producers SHOULD omit them.
- **Not allowed:**
  - encryption;
  - archives split over several files;
  - symbolic links and other special entries;
  - any two file entries whose names collide (§2.3), whether or not the manifest names them.
  A reader MUST reject an archive with any of these.
- **Recognising it:** readers MAY open any ZIP whose first entry is the `mimetype` entry above, whatever the file is called.

### 2.2 The folder

- **A folder with `collection.json` at its root.** Its name doesn't matter.
- **How a path is found:** a path names a file that exists when walking its parts reaches a regular file, each part matching (§2.3) an actual entry of its directory. A reader MUST NOT rely on the file system's own case or normalisation folding.
- **Links:** a symbolic link anywhere in the folder makes the collection fail rule 2. Readers check with `lstat` or its equivalent before reading. Hard links can't be detected reliably; readers verify bytes, not file identities.

### 2.3 Paths

Every path in the manifest is relative to the collection's root. A path:
- is written in Unicode NFC, at most 1,024 bytes of UTF-8;
- separates its parts with `/`, and has no empty part, `.` or `..`;
- doesn't start with `/`;
- contains no `\`, `:`, `*`, `?`, `"`, `<`, `>` or `|`, and no code point in U+0000–U+001F or U+007F–U+009F;
- has no part longer than 255 bytes, no part ending in `.` or a space, and no part whose name before its first `.` is a Windows device name, in any letter case (`CON`, `PRN`, `AUX`, `NUL`, `COM0`–`COM9`, `LPT0`–`LPT9`).

**Two paths match** when their NFC forms are identical byte for byte. Every path in the manifest MUST match exactly one file of the collection. Readers MUST NOT match ignoring case.

**Two paths collide** when they are different but become identical after NFC normalisation and full Unicode case folding (`CaseFolding.txt`, statuses C and F, independent of locale). `Set.mp3` and `set.mp3` collide. So do `Straße.mp3` and `STRASSE.mp3`, and the composed and decomposed forms of `é`. No two files of a collection may collide.

A suggested layout, not a required one:

```
collection.json
audio/…       the audio files
images/…      artwork
lyrics/…      lyrics files (§5.7)
```

Readers ignore files the manifest doesn't name, such as a downloader's `*.info.json`; the rules on collisions and links still apply to them.

## 3. The manifest

`collection.json` is one JSON object (RFC 8259) in UTF-8, without a byte-order mark, at most 8 MiB, nested at most 32 levels deep, `extensions` included.
- **Unique names:** member names within one object MUST be unique. A reader MUST reject a manifest that repeats a name. Parsers differ on which copy they keep: Apple's keep the first, many others the last.
- **One parse:** a reader MUST check and play from the same parsed document.

| Field | Type | Required | What it is |
|---|---|---|---|
| `etui` | version | yes | The format version, `"1.0"` (§10) |
| `id` | UUID | yes | The collection's identity (§7) |
| `revision` | integer, 1 to 2,147,483,647 | yes | Goes up with every published change (§7) |
| `updated` | timestamp | no, SHOULD | When this revision was made |
| `kind` | string | no | What sort of collection (§3.1); default `playlist` |
| `title` | text | yes | "Nightshift", "Symphony No. 5", "The Time Machine" |
| `subtitle` | text | no | A second line, e.g. "Halle 9, Berlin" |
| `description` | long text | no | |
| `language` | language | no | The language of the collection's text |
| `translations` | object | no | The collection's text in other languages (§3.4) |
| `artwork` | path | no | The collection's cover (§6) |
| `curator` | object | no | Who put it together: `name` (text, required), `url` (url), `translations` (§3.4) |
| `generator` | object | no | What made the file: `name` (text, required), `version` (text) |
| `rights` | object | no | §11 |
| `event` | object | no | For a live event (§3.2) |
| `rym_list` | object | no | For albums picked from a RateYourMusic list or chart (§3.3) |
| `series` | object | no | The series it belongs to, such as a weekend's nights (§3.5) |
| `people` | array | no | Everyone credited (§4) |
| `sections` | array | no | Groups of items (§5.2) |
| `files` | array, at least 1 | yes | The audio files (§5.1) |
| `items` | array, at least 1 | yes | What plays, in order (§5.3) |
| `playback` | object | no | Hints (§8) |
| `extensions` | object | no | Producers' own data (§10.2) |

**Value types used throughout**

| Type | Rule |
|---|---|
| text | 1 to 1,024 bytes of UTF-8. It isn't only white space, and has no code point in U+0000–U+001F, U+007F–U+009F, U+2028, U+2029, U+202A–U+202E or U+2066–U+2069 (control and direction-override characters) |
| long text | Up to 64 KiB of UTF-8, with the same character rule as text except that U+000A (line feed) is allowed. A blank line separates paragraphs. No HTML or Markdown: readers show it as written |
| integer | A JSON number written as decimal digits, with a `-` only where a range allows it, and no fraction or exponent. From 0 to 9,007,199,254,740,991 (2^53 − 1) unless a narrower range is given. `true`, `1.0` and `1e3` aren't integers |
| number | A JSON number, finite |
| boolean | `true` or `false` |
| version | `MAJOR.MINOR`: two decimal integers without leading zeros, e.g. `"1.0"` (§10.1) |
| UUID | RFC 9562, lowercase hex with hyphens, version 4 (random) or 5 (name-based). `uuidgen \| tr A-Z a-z` makes one. Readers MAY accept uppercase and store it lowercase |
| key | 1 to 128 characters from `A–Z a–z 0–9 . _ -`, unique among objects of the same kind in the manifest |
| timestamp | RFC 3339 `date-time` with an uppercase `T`, seconds, and an offset, e.g. `2026-10-17T23:59:00+02:00`. `Z` is allowed, but the local offset of where it happened is better. The date and time must exist |
| date | RFC 3339 `full-date`, `YYYY-MM-DD`, a date that exists |
| url | An absolute URI (RFC 3986) with scheme `https`, a non-empty host, no user information, no white space or control characters, at most 2,048 bytes |
| ms | An integer number of milliseconds, from 0 to 4,294,967,295 (about 49 days) |
| path | §2.3 |
| language | A well-formed BCP 47 tag (RFC 5646), e.g. `en`, `de`, `pt-BR` |

An object this spec defines may carry fields it doesn't define; readers ignore them (§10). A field it does define MUST have the type given here, or the collection is invalid (§9, rule 1).

### 3.1 Kinds

`kind` tells a reader what the collection is, so it can choose a layout and the defaults in §8. An unknown kind is read as `playlist`.

| `kind` | For |
|---|---|
| `playlist` | Any ordered selection (the default) |
| `event` | A club night, festival or concert series, with sections for its slots |
| `album` | A release: an album, a classical recording, with sections for its works |
| `audiobook` | A book read aloud |
| `course` | Lectures, talks, a season of a podcast |
| `fragments` | Short stretches taken from longer recordings |
| `rym_list` | Whole albums picked from a RateYourMusic list or chart, each a section of kind `album` (§3.3) |

### 3.2 Event

| Field | Type | What it is |
|---|---|---|
| `title` | text | The event's name; required when `event` is present |
| `venue`, `city` | text | |
| `country` | string | ISO 3166-1 alpha-2, e.g. `DE` |
| `starts`, `ends` | timestamp | `ends` is not before `starts` |
| `rooms` | array of text | Rooms or stages, each listed once, for sections to refer to |
| `url` | url | The event's page |
| `extensions` | object | §10.2 |

### 3.3 RYM list

For `kind: "rym_list"`: whole albums picked from a list or chart on RateYourMusic, heard one after another, often a few at a time in rounds. The collection is made of:
- **albums:** sections of kind `album`. Each has an `album` object (§5.2.1), its cover and its links;
- **artists:** people (§4), with their names in their own script, how to say them, and their story;
- **tracks:** items, with their words in lyrics files (§5.7).

A reader shows the albums with their covers and details, the artists' stories, and the words with a translation.

The `rym_list` object says where the albums came from:

| Field | Type | What it is |
|---|---|---|
| `title` | text | The list's or chart's name on RateYourMusic, as written there, whatever the collection's language |
| `url` | url | Its page |
| `author` | text | Who made the list, as named there. A chart has none |
| `round` | integer, at least 1 | Which round this is, when the list is heard a few albums at a time |
| `translations` | object | §3.4 |
| `extensions` | object | §10.2 |

### 3.4 Languages

A collection's text is written in its `language`. The same text in other languages goes in `translations`. The collection, `event`, `rym_list`, `series`, `curator`, a person, a link, a section, an `album` object and an item may each carry one:

```json
"translations": {
  "en": {"title": "World Hip-Hop, round 1", "description": "Eleven countries, one album each."}
}
```

- **Keys** are language tags. There can be any number of them.
- **What a translation holds:** any of the enclosing object's own fields of type text, long text or sourced text, or arrays of these, in that language. Each follows the same type and rules as the original, and a wrong type fails rule 1.
- **What stays as it is:** ids, paths, numbers, addresses and nested objects. An `album` object, a link and `curator` carry their own `translations`. References aren't translated either: a section's `room` and the event's `rooms` keep the names that sections refer to. Other objects aren't translated in this version: chapters, highlights, links, `curator`, `generator` and a lyrics file's `source`.
- **Readers** show the language the listener chose. Otherwise they show the first of the listener's preferred languages that the collection has, and otherwise the original text. A field missing from a translation falls back to the original, except `title_meaning`: it is written for the readers of one language, so a reader showing another language without one shows none. A reader MAY show the original next to the translation, and MAY offer a choice among the collection's languages: its `language` and every key used in `translations`.
- **Lyrics** carry their own translations, line by line (§5.7).

### 3.5 Series

A collection can be one of a series: a weekend's nights, the rounds of a list. The series itself is described apart, by whoever publishes it, beside the collections it names. A collection carries only a pointer to it, so that a file which arrives alone can be shown under its series' name, and joins the others when they come.

| Field | Type | What it is |
|---|---|---|
| `id` | UUID | The series' identity; required |
| `title` | text | Its name: "Amsterdam weekend"; required |
| `part` | text | This collection's part of it: "Friday 20 Nov", "Round 2" |
| `translations` | object | `title` and `part` in other languages (§3.4) |
| `extensions` | object | §10.2 |

- **One series:** a collection names at most one.
- **What a reader does:** it shows the collection under its series' title, beside the other collections that name the same id, in the order of their parts. A reader that knows more about the series, such as its pictures or its other members, may show that instead.
- **Revisions:** moving a collection to another series is a change to the collection, so it is a new revision (§7). A series that gains a member needs no change to the collections already in it.

## 4. People

Everyone credited: DJs, live acts, composers, ensembles, soloists, narrators, authors, hosts.

| Field | Type | Required | What it is |
|---|---|---|---|
| `id` | key | yes | Referenced from sections, credits and `members` |
| `name` | text | yes | As shown |
| `sort_name` | text | no | e.g. "Volk, Mara" |
| `native_name` | text | no | The name in its own script, when `name` spells it in Latin letters: 九维 for Jiuwei |
| `pronunciation` | text | no | How to say the name, written for the collection's language: «Цзювэй» |
| `members` | array of keys | no | For a duo, a band or a back-to-back pairing: the people in it |
| `tagline` | text | no | One line about them |
| `bio` | sourced text | no | Their story, ideally in their own words |
| `facts` | array of sourced text | no | Short facts from other sources |
| `links` | array of links | no | |
| `image` | path | no | §6 |
| `dates_url` | url | no | Where their upcoming dates are listed |
| `translations` | object | no | §3.4 |
| `extensions` | object | no | §10.2 |

- **`members`** refer to other entries in `people`. A person can't be their own member, and membership can't form a cycle.
- **Sourced text:** `{"text": long text, "source": text, "url": url}`. `text` and `source` are required. Name the source ("SoundCloud", "Discogs", "Wikipedia", "their website") so a reader can say where the words came from. They are someone else's words (§11).
- **Link:** `{"kind": string, "title": text, "url": url, "translations": object}`. `title` and `url` are required, and `kind` defaults to `other`. `translations` holds the `title` in other languages (§3.4). The kinds in 1.0:
  - `website`, `soundcloud`, `mixcloud`, `bandcamp`, `youtube`, `instagram`, `facebook`, `x`;
  - `ra` (Resident Advisor), `discogs`, `spotify`, `apple_music`, `beatport`, `bandsintown`, `songkick`, `wikipedia`, `rateyourmusic`;
  - `other`.

## 5. Audio: files, items and sections

The manifest keeps three things apart:
- **files** are the audio files in the collection, with their checksums;
- **items** are what plays, in order. An item is a whole file or a stretch of one (a fragment), and several items can use the same file;
- **sections** are optional headings over runs of items: a slot, a classical work, a part of a book.

### 5.1 Files

| Field | Type | Required | What it is |
|---|---|---|---|
| `path` | path | yes | Where the file is in the collection |
| `sha256` | string | yes | SHA-256 of the file's bytes, 64 lowercase hex digits |
| `bytes` | integer, at least 1 | yes | The file's size |
| `format` | string | no | One of the extensions below, in lower case; when present, it equals the path's extension in lower case |
| `duration_ms` | ms | no, SHOULD | How long it plays: the decoded length, rounded to the nearest millisecond |
| `codec` | text | no | For information, e.g. `aac`, `alac`, `mp3`, `flac`, `opus`, `vorbis`, `pcm` |
| `bitrate_kbps`, `sample_rate_hz`, `channels` | integer | no | For information |
| `loudness` | object | no | `integrated_lufs` and `true_peak_dbtp`, both numbers (EBU R128), so a reader can even out volume |
| `skyline` | string | no | Each second's loudness, base64: so a reader can draw the audio's shape and even out its volume before the file is on the device (below) |
| `rights` | object | no | §11 |
| `extensions` | object | no | §10.2 |

- **Formats in 1.0:**
  - MP3: `.mp3`, MPEG-1 or MPEG-2 Layer III.
  - M4A: `.m4a`, or `.m4b` for an audiobook, an MPEG-4 audio file holding AAC-LC, HE-AAC (v1 or v2) or ALAC.
  - AAC: `.aac`, an ADTS stream of AAC-LC or HE-AAC.
  - FLAC: `.flac`, a native FLAC stream.
  - Opus: `.opus`, Opus in Ogg (RFC 7845).
  - WAV: `.wav`, RIFF WAVE holding PCM.
  - AIFF: `.aiff` or `.aif`, AIFF or AIFF-C holding PCM.
  - Extensions are matched in any letter case. Every reader MUST play MP3 and M4A, and SHOULD play the others. A collection that declares `1.0` uses only these formats.
  - Not in 1.0: Ogg Vorbis (`.ogg`), which iOS can't open though the Mac plays it (iOS 27, tested 2026-11-11); WebM and Matroska audio, and WMA, which no Apple system opens (tested 2026-11-10). A reader there would leave every such item out.
- **A file a reader can't play** isn't a validity failure. That covers a format from a later version, or content that isn't what its extension says. The reader leaves out the items that use the file, and says so (§10.1).
- **Each audio file appears once** in `files`, and SHOULD be used by at least one item. The same recording in two collections has the same `sha256`, so a reader can store it once.
- **Embedded tags** (ID3, MP4 metadata, Vorbis comments, WAV INFO, embedded chapters and covers) MAY be present:
  - For an item's title, artist line, chapters and cover, the manifest is the only source when the item has the field, even when it's an empty array.
  - When the item lacks the field, a reader MAY use the embedded value.
  - A reader MUST NOT show embedded text for any other field.

- **Skyline:** one byte per second of audio, base64 without line breaks: the RMS level of that second of the audio mixed to mono, in dB full scale, mapped linearly so that 0 is -60 dB or quieter and 255 is 0 dB (`round((dB + 60) / 60 × 255)`, kept within 0 to 255). A last partial second counts as a second, so there are `ceil(duration_ms / 1000)` bytes, give or take one. A reader that streams a file draws its skyline from this and evens out its volume with it, limiting a boost by `loudness.true_peak_dbtp` where given; a reader with the file may measure its own instead. Readers that don't know it ignore it.

### 5.2 Sections

| Field | Type | Required | What it is |
|---|---|---|---|
| `id` | key | yes | Referenced from items |
| `title` | text | yes | "Mara Volk", "Symphony No. 5 in C minor", "Part One" |
| `kind` | string | no | `artist`, `album`, `work`, `part` or `other` (the default) |
| `number` | integer | no | The number shown, e.g. slot `4` |
| `people` | array of credits | no | Who the heading names: the act of a slot, the composer of a work |
| `room` | text | no | One of `event.rooms` |
| `starts` | timestamp | no | When the slot started |
| `artwork` | path | no | The section's own cover, e.g. an album's sleeve (§6) |
| `links` | array of links | no | Pages about it, e.g. an album's page at a shop, a label or an encyclopedia (§4) |
| `album` | object | no | For a section of kind `album`: its details (§5.2.1) |
| `reason` | text | no | Why it is in this collection, for the listener (§5.3) |
| `translations` | object | no | §3.4 |
| `description` | long text | no | |
| `extensions` | object | no | §10.2 |

- **Order:** a section's items MUST be next to each other in `items`, and sections MUST be listed in the order their first items appear. A section that no item uses is shown after the others, in array order, or not at all.
- **One level:** sections don't nest in 1.0. An album's discs go in `items[].disc`; an event's days and rooms come from `starts` and `room`.

#### 5.2.1 Album

What a section of kind `album` can say about its release:

| Field | Type | What it is |
|---|---|---|
| `native_title` | text | The title in its own script, when the section's `title` spells it in Latin letters: 趣味小常识 for "Quwei xiao changshi" |
| `title_meaning` | text | What the title means, in the collection's language: «Занимательные мелочи» |
| `year` | integer, 1000 to 9999 | The year it first came out |
| `country` | string | Where it comes from: ISO 3166-1 alpha-2, e.g. `CN` |
| `language` | language | What it is sung or spoken in, e.g. `zh` |
| `hook` | text | One line on what to expect |
| `rating` | object | How listeners rate it on a site, see below |
| `translations` | object | §3.4 |
| `extensions` | object | §10.2 |

- **Around the album object:** the section's `people` name the album's artists, with the role `performer`. Its `description` is about the album, and an artist's story is that person's `bio` (§4).
- **Country and language names:** readers derive them from the codes, in the listener's language.
- **Rating:** `{"source": text, "value": number, "best": number, "ratings": integer, "reviews": integer, "retrieved": date}`. `source` (the site's name), `value` (its average) and `best` (the top of its scale) are required, with `value` from 0 to `best` and `best` above 0. `ratings` and `reviews` say how many people rated it and wrote a review, and `retrieved` is the day the figures were read. They are a snapshot: a reader shows them as they are and doesn't fetch newer ones. The album's page on that site is a link of the section (§5.2).

### 5.3 Items

| Field | Type | Required | What it is |
|---|---|---|---|
| `id` | key | yes | Kept across revisions (§7) |
| `file` | path | yes | Matches a `files[].path` |
| `title` | text | yes | |
| `kind` | string | no | `set`, `live`, `track`, `movement`, `chapter`, `episode`, `fragment` or `other` (the default) |
| `section` | key | no | The section it belongs to |
| `credits` | array of credits | no | Who made this item |
| `artist` | text | no | The artist line as shown, where credits alone don't make it |
| `start_ms`, `end_ms` | ms | no | Play only this stretch of the file, for a fragment |
| `disc` | integer, at least 1 | no | For an album on several discs |
| `title_meaning` | text | no | What the title means, in the collection's language, when the title is in another |
| `artwork` | path | no | This item's own cover |
| `lyrics` | path | no | The words, in a lyrics file (§5.7) |
| `recorded` | date or timestamp | no | When it was performed or recorded |
| `published` | date | no | When it was first published |
| `source` | object | no | Where it came from (§5.4) |
| `chapters` | array | no | §5.5 |
| `highlights` | array | no | §5.6 |
| `notes` | long text | no | |
| `reason` | text | no | Why it is in this collection, for the listener |
| `tags` | array of text | no | Genres, moods |
| `translations` | object | no | §3.4 |
| `rights` | object | no | §11 |
| `extensions` | object | no | §10.2 |

- **Order:** items play in array order.
- **The stretch** is `[start_ms, end_ms)`: from `start_ms`, up to but not including `end_ms`. Either bound may be given alone. Without them the item is the whole file.
- **Times** in an item (`start_ms`, `end_ms`, chapters, highlights) are positions in its file, counted from the file's start, even when the item is a fragment.
- **Credit:** `{"person": key, "role": string}`. Both are required, and an unknown role is read as `other`. The roles in 1.0 are `dj`, `live`, `performer`, `composer`, `conductor`, `ensemble`, `soloist`, `narrator`, `author`, `host`, `guest`, `remixer`, `producer` and `other`.
- **Credits and sections:** an item's `credits` describe that item. A section's `people` describe only its heading. A reader shows an item's credits when it has them, and doesn't add the section's to them.
- **Reason,** on an item or a section: one or two sentences, for the listener, on why this pick is in this collection, such as "The longest set of the last two years on their own profile" or "On ten of the folk lists, beside albums you rate 9". What the music is like stays in an album's `hook` and in `description`. A RateYourMusic round gives it on the album's section, an event on the set's item and, where the act itself needs one, on the act's section. Readers show it as written, in the listener's language through `translations` (§3.4). A reader that doesn't know it ignores it.

### 5.4 Source

Where the audio came from, for credit and to find it again: `{"service": text, "url": url, "id": text, "uploader": text, "retrieved": timestamp}`. Every field is optional. `service` is free text, e.g. `soundcloud`, `mixcloud`, `bandcamp`, `archive.org`, `cd`, `own-recording`.

### 5.5 Chapters

Tracks inside a long recording, or a book's chapters.

| Field | Type | Required | What it is |
|---|---|---|---|
| `start_ms` | ms | yes | |
| `end_ms` | ms | no | Default: the next chapter's start, or the end of the item |
| `title` | text | yes | |
| `artist` | text | no | For a track inside a DJ set |
| `exact` | boolean | no | `true` when the start is known exactly, `false` (the default) when estimated |

- Chapters lie within their item's stretch. Their `start_ms` values strictly increase.
- Each `end_ms` is greater than its `start_ms` and at most the next chapter's `start_ms`. Gaps are allowed.
- An item has at most 1,024 chapters.
- Embedded chapters outside a fragment's stretch are ignored.

### 5.6 Highlights

Stretches worth hearing first. A reader can play the highlights of a whole collection in a row: in item order, and within an item in highlight order.

| Field | Type | Required | What it is |
|---|---|---|---|
| `start_ms`, `end_ms` | ms | yes | The stretch, `[start_ms, end_ms)` |
| `label` | text | no | "Peak", "Closing track" |
| `evidence` | object | no | How it was chosen. `method` (text): e.g. `listener_cluster`, `single_listener`, `audio_fallback` or `curator`. `listeners`: an integer. `confidence`: a number from 0 to 1 |

Highlights lie within their item's stretch, in order of `start_ms`, and MAY overlap. An item has at most 1,024.

### 5.7 Lyrics

An item's words are in a file of their own, named by the item's `lyrics`. The file is a JSON object in UTF-8 without a byte-order mark, at most 1 MiB, and follows the manifest's rules on unique names and nesting (§3). Producers SHOULD give it the extension `.json`.

| Field | Type | Required | What it is |
|---|---|---|---|
| `language` | language | no, SHOULD | The language of the words |
| `lines` | array, 1 to 4,096 | yes | The words, line by line, in order |
| `timing` | `"exact"` or `"estimated"` | no | How the times were found: from a timed source, or worked out by a program from the audio. Default `exact` |
| `translations` | object | no | The lines in other languages |
| `source` | object | no | Where the words came from: `name` (text, required), `url` (url) |
| `rights` | object | no | §11 |
| `extensions` | object | no | §10.2 |

- **A line** is `{"text": line, "start_ms": ms}`.
  - `text` is required. It follows the rule for text, except that it may be empty (`""`). An empty line is a pause, or the break between verses.
  - `start_ms` is when the line begins, a position in the item's file as for chapters (§5.3). Times SHOULD lie within the item's stretch. A line outside it is shown but never reached.
- **Timed or not:** either every line has `start_ms` or none does. When timed, the times never go down, and two lines may start together. A reader follows the playback position through timed words, and MAY seek to a line the listener taps.
- **Translations:**
  - Keys are language tags.
  - Each value is `{"lines": ["…", "", …], "by": text}`. `lines` is required, `by` isn't. Its `lines` are strings, not line objects: a translation has no times of its own and follows the original's. There are exactly as many as the file's `lines`, each the translation of the line in the same place, following the rule for a line's `text`. Each is empty exactly where that line is empty.
  - `by` says who or what translated, e.g. "TranslateGemma 4B, machine translation".
  - Readers show the translation in the listener's language, under or beside the original.
- **Not a validity failure:** a lyrics file that's missing, too large or broken against these rules is ignored and reported. The item still plays.
- **Rights:** the words of songs are someone else's (§11). Whoever makes the collection is responsible for being allowed to include them.

## 6. Images

- **Format and size:** JPEG (`.jpg`, `.jpeg`) or PNG (`.png`), with content that matches the extension, at most 4 MiB and 16,000,000 pixels each. Readers read the size from the image's header before decoding it.
- **Not a validity failure:** an image that's missing, too large or not JPEG or PNG is ignored and reported. It doesn't make the collection invalid.
- **The collection's `artwork`** SHOULD be square and at least 1,000 × 1,000 pixels.
- **Fallback:** an item without `artwork` shows its section's `artwork`, then its file's embedded cover if the reader uses embedded covers, and otherwise the collection's `artwork`.
- **Metadata:** producers SHOULD strip EXIF, XMP and IPTC data, which can carry places and names. Readers MUST NOT display it.

## 7. Identity and updates

- **The collection's `id`** is made once, when the collection is first created, and kept for every later revision. Someone who changes a collection and shares it as their own SHOULD give it a new `id`.
- **`revision`** starts at 1 and goes up with every published change. Producers SHOULD set `updated` on every revision.
- **Item ids** are kept too: an item keeps its `id` across revisions.

Any file can carry any `id`, and nothing in 1.0 proves who made a file. So when a reader opens a collection whose `id` it already has:

| The new `revision` is | The reader |
|---|---|
| higher | MUST NOT replace the stored collection before showing the listener what would change and getting their yes. What would change means: title and curator, and which items are added, removed or have a new file. Until then it keeps the stored collection and its listener data |
| the same | Changes nothing if the manifest is identical. If it differs, the reader SHOULD say so, and MAY offer to replace it as above |
| lower | Keeps what it has, and says that it holds a newer revision |

**After a replacement**
- **Listener data stays** with every item whose `id` and file `sha256` are unchanged.
- **A new file:** an item with a new file (same `id`, different `sha256`) counts as a new recording, and its position is dropped.
- **Positions outside the stretch:** a position that falls outside an item's new stretch is dropped.
- **Removed items:** marks on them SHOULD be kept, so the listener can export them.
- **History:** a reader SHOULD keep where each accepted revision came from (the file name, the place it was opened from), so the listener can see it.

A later version may add signatures, so that a revision signed with the same key as the stored one can be applied without asking.

## 8. Playback hints

These are suggestions. A listener's own settings come first, and a reader may ignore any hint.

| Field | Type | What it suggests |
|---|---|---|
| `order` | `"sequential"` or `"shuffle"` | Whether shuffling makes sense |
| `continuous` | boolean | Items run into each other without a gap: a classical work, a mix split into tracks |
| `resume` | `"always"` or `"never"` | Whether to remember the position reached in each item |
| `skip_back_s`, `skip_forward_s` | integer, 1 to 600 | Skip lengths in seconds |
| `speed_adjustable` | boolean | Offer a playback speed control, for spoken word |

An unknown value is read as the default. The defaults by kind are informative, not required:

| kind | resume | continuous | skip back / forward | speed |
|---|---|---|---|---|
| playlist | items of 20 min or more | no | 10 / 30 s | no |
| event | always | no | 10 / 30 s | no |
| album | never | within a section | 10 / 30 s | no |
| audiobook | always | no | 15 / 30 s | yes |
| course | always | no | 15 / 30 s | yes |
| fragments | never | no | 10 / 30 s | no |
| rym_list | never | within a section | 10 / 30 s | no |

## 9. Validity and what readers do

A collection is **valid** when:
1. `collection.json` parses as one JSON object without repeated member names. Every required field is present, every field this spec defines has the type and range it gives, and every `id` is unique among its kind.
2. Every path follows §2.3, and every audio file's path matches a file that exists. An image or lyrics file that's missing is reported, not a failure (§6, §5.7). No two files collide, no links are present, and the archive follows §2.1 and §12.
3. Every audio file's size and SHA-256 match its entry in `files`.
4. Every reference resolves:
   - `items[].file` to `files`;
   - `items[].section` to `sections`;
   - credits and `members` to `people`;
   - `room` to `event.rooms`.
5. Times are in range: an item's stretch is non-empty, and when the file declares `duration_ms`, it ends at or before it. Chapters and highlights lie within their item's stretch.
6. Sections, chapters and highlights are ordered as §5.2, §5.5 and §5.6 say. No item has more than 1,024 chapters or 1,024 highlights.

**Readers MUST:**
- check rules 1–6 before accepting a collection, and refuse one that fails rule 1, 4, 5 or 6, saying why;
- not play a file that fails rule 2 or 3. A reader MAY accept the rest of the collection without the items that use it, and say which it left out;
- play only bytes they verified: either from the archive entry whose SHA-256 they checked, or from an extracted file whose SHA-256 they checked. Verifying one copy and playing another isn't allowed;
- work with the decoded length when it differs from `duration_ms` or there is none. Clamp every end (`end_ms`, chapter and highlight ends) to the decoded length. Leave out, and report, an item or highlight that starts at or after the decoded length. Don't refuse the collection for that;
- not fetch any URL on their own. They show a link's host before opening it, and open it only when the listener asks;
- ignore fields, kinds and values they don't know (§10.1).

**Limits:** a reader may set limits (the Etui app's: 10,000 items, an 8 MiB manifest, and as much audio as the device has room for; until 2026-11-14 it refused more than 20 GiB in one archive). A reader that meets a collection beyond its limits MUST say so, MUST NOT silently drop part of it, and MAY refuse it.

## 10. Versions and extensions

### 10.1 Versions

`etui` is a version, `MAJOR.MINOR`, compared as numbers: `1.10` is later than `1.9`.
- **Major:** a reader MUST refuse a major version it doesn't know, and say which version the file needs.
- **Minor:** a reader MUST accept any minor version. A minor version only adds optional fields, values and audio formats.
- **What a reader does with things it doesn't know:**
  - it ignores fields;
  - it reads an unknown value as the field's default: collection `kind` as `playlist`, section and item `kind`, link `kind` and credit `role` as `other`, `order` as `sequential`, `resume` as the kind's default;
  - it leaves out, and reports, the items whose file is in a format it can't play.
  None of these makes a collection invalid.

### 10.2 Extensions

- **Where:** producers put their own data in an `extensions` object on the collection, the event, `rym_list`, a person, a section, an `album` object, a file, an item or a lyrics file.
- **Keys** are 3 to 128 characters of `A–Z a–z 0–9 _ -`, in two or more parts separated by dots. Reverse DNS is recommended (`com.example.lights`). Values are any JSON, within the manifest's nesting limit.
- **Readers** ignore extensions they don't understand, and keep them when they rewrite a collection.

## 11. Rights

This format describes audio and the words and pictures around it. It doesn't grant or check any rights to them. Whoever makes or shares a collection is responsible for being allowed to. The format lets them say what applies:
- **`rights`:** `{"statement": long text, "license": string, "url": url}`, with at least one of `statement` and `license`.
  - `license` is an SPDX identifier (`CC-BY-4.0`, `CC0-1.0`) or `all-rights-reserved`. Leave it out when neither fits.
  - `rights` may sit on the collection, a file or an item. The most specific one applies: item, then file, then collection.
  - On the collection, `rights` covers its text and images as well as the audio.
- **`source`** (§5.4) records where each recording came from, and sourced text names where its words came from.

## 12. Security considerations

A collection is untrusted input.

**Paths and links**
- §2.3 and §9 keep a reader inside the collection: no absolute paths, no `..`, no links.
- A reader that extracts an archive MUST apply §2.3 to every entry name before writing anything, including names the manifest doesn't use. It MUST reject the archive if any name fails.

**The archive**
- **The central directory** is the only list of entries.
- **Local headers:** a reader MUST treat a disagreement between an entry's central-directory record and its local header (name, sizes, method, CRC-32) as a rule-2 failure.
- **Entries:** they MUST NOT overlap, and a reader MAY reject an archive whose entries do.
- **Methods and encryption:** a method other than 0 or 8, or encryption, fails rule 2.

**Contents**
- **Size before unpacking:** check the declared `bytes` and the archive's uncompressed sizes against free space and the reader's limits, so a small archive can't expand to fill a disk.
- **Checksums:** verify every audio file's SHA-256 before using it, and play only verified bytes (§9).
- **JSON:** reject repeated member names, nesting deeper than 32 levels, and numbers outside the integer range rather than rounding them. Check and play from one parsed document.
- **Images:** read their size from the header first, and decode within §6's bounds.
- **Text:** there's no executable content (no scripts, no HTML), text is shown as plain text, and §3's character rules exclude control and direction-override characters.

**Links and identity**
- **Links:** they are https only, never opened automatically, and shown with their host. A host that mixes scripts SHOULD be shown in its punycode form.
- **Identity:** `id`, `curator` and `source` are unverified text supplied by the file. §7 keeps a file from silently replacing a collection the listener holds.

**Personal data**
- A collection carries no listener data.
- Producers SHOULD NOT include personal contact details of people beyond what those people published themselves.
- Producers SHOULD let the person sharing a collection review `source.retrieved`, `source.uploader`, `generator`, `extensions` and image metadata before sharing, since these can reveal more than intended.

## 13. Names and identifiers

| | Value | Status |
|---|---|---|
| Format name | Etui | Decided 2026-10-18; the player app takes the same name |
| File extension | `.etui` | Decided |
| Manifest | `collection.json` at the root | Decided 2026-11-07 |
| Media type | `application/vnd.etui+zip` | Provisional; not registered with IANA |
| Apple type identifier | `io.github.aldiss.etui`, conforming to `public.data` and `public.content` (not `public.zip-archive`: declared as a ZIP, the iOS Files app would expand an `.etui` when it is tapped instead of opening it in the app that owns the type) | Decided 2026-11-07 |
| Magic bytes | `mimetype` at byte 30, `application/vnd.etui+zip` at byte 38 (§2.1) | Proposed |

## Appendix A. Examples

| Path | Shows |
|---|---|
| `examples/complete/` | **A complete collection,** as a folder: a manifest, two short audio files (MP3, and M4A with a non-ASCII name) and a cover. `examples/complete.etui` is the same collection as an archive, made with Appendix B |
| `examples/minimal.json` | The least a valid manifest needs: one file, one item |
| `examples/event.json` | A club night: slots, a live duo with members, profiles, sources, chapters, highlights |
| `examples/album-classical.json` | A classical album: a work with its movements, composer, conductor and orchestra; continuous playback |
| `examples/audiobook.json` | A book in two files, with chapters, remembered positions and speed control |
| `examples/fragments.json` | Favourite stretches from two long sets, as items with `start_ms` and `end_ms` |
| `examples/rym-list.json` | A RateYourMusic round: two albums with covers, native names and pronunciation, English translations, and a timed lyrics file with translations (`examples/rym-list/`) |
| `examples/invalid/*.json` | Broken manifests. Each file's name says what's wrong with it |

The people and places are made up. The manifests other than `complete/` name audio files that aren't shipped, so only `complete/` exercises rules 2 and 3.

`validate.py` checks a manifest, a folder or an archive against this spec, using stdlib Python 3. It is a draft, and a reader may be stricter.

The smallest valid manifest, next to a file `audio/recording.mp3`:

```json
{
  "etui": "1.0",
  "id": "0f8b6a52-8f3e-4d55-9b0e-2a64c1d93e11",
  "revision": 1,
  "title": "A recording",
  "files": [
    {"path": "audio/recording.mp3", "sha256": "<64 lowercase hex digits>", "bytes": 1234567}
  ],
  "items": [
    {"id": "1", "file": "audio/recording.mp3", "title": "A recording"}
  ]
}
```

## Appendix B. Making the archive

From a folder laid out as in §2.3, with the `mimetype` file written first:

```
cd <folder>
printf '%s' application/vnd.etui+zip > mimetype
zip -X -0 ../name.etui mimetype
zip -X -D -n .mp3:.m4a:.m4b:.aac:.flac:.opus:.wav:.aiff:.aif:.jpg:.jpeg:.png -r ../name.etui collection.json audio images lyrics
rm mimetype
```

- **The flags:**
  - `-X` writes no extra fields, which the byte-38 magic needs;
  - `-0` stores `mimetype`;
  - `-D` writes no directory entries;
  - `-n` stores the listed extensions instead of compressing them.
- **Expected result:** `unzip -lv name.etui` lists `mimetype` first, stored, 24 bytes, then `collection.json`, then the audio, stored.
- **Not Finder:** Compress in the Finder isn't suitable. It nests everything under the folder's name and adds `__MACOSX` entries.
- **Other folders:** name every folder the manifest uses; a collection without lyrics leaves `lyrics` out.
- **In Python:** `zipfile.ZipFile(path, "w")`, then `writestr("mimetype", "application/vnd.etui+zip", compress_type=zipfile.ZIP_STORED)` first. Then write `collection.json`, and the audio with `ZIP_STORED`.
