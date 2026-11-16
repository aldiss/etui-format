#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Draft validator for Etui collections (the Etui format, SPEC.md, draft 3). Standard library only.

Usage: validate.py PATH [PATH ...]
  PATH is a manifest (.json), a collection folder (holding collection.json), an archive (.etui or any
  ZIP), or a folder of those, which is checked one level deep.

A manifest alone gets rules 1, 4, 5 and 6 plus path syntax; a folder or an archive also gets rules 2 and 3:
the files exist, their sizes and SHA-256 match, and the archive's structure is sound. Lyrics files (§5.7) are
read from the folder or the archive; for a manifest alone, from the folder next to it with its name, if there is
one (rym-list.json: rym-list/). A broken lyrics file is a warning, never a validity failure. Exit status 1 when
anything is INVALID or the check itself failed, 2 for a usage error.
"""
import base64
import binascii
import datetime
import hashlib
import json
import math
import os
import re
import stat
import struct
import sys
import unicodedata
import zipfile
import zlib
from pathlib import Path
from urllib.parse import urlsplit

MAX_MANIFEST = 8 * 1024 * 1024
MAX_DEPTH = 32
MAX_INT = 2**53 - 1
MAX_MS = 2**32 - 1
MAX_REVISION = 2**31 - 1
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_PIXELS = 16_000_000
READER_MAX_AUDIO = 20 * 1024**3
READER_MAX_ITEMS = 10_000
MAX_PER_ITEM = 1024
MAX_LYRICS = 1024 * 1024
MAX_LINES = 4096
MIMETYPE = b"application/vnd.etui+zip"

KINDS = {"playlist", "event", "album", "audiobook", "course", "fragments", "rym_list", "mixtape"}
SECTION_KINDS = {"artist", "album", "work", "part", "other"}
ITEM_KINDS = {"set", "live", "track", "movement", "chapter", "episode", "fragment", "other"}
ROLES = {"dj", "live", "performer", "composer", "conductor", "ensemble", "soloist", "narrator", "author", "host",
         "guest", "remixer", "producer", "other"}
LINK_KINDS = {"website", "soundcloud", "mixcloud", "bandcamp", "youtube", "instagram", "facebook", "x", "ra", "discogs",
              "spotify", "apple_music", "beatport", "bandsintown", "songkick", "wikipedia", "rateyourmusic", "other"}
# §3.4: what a translation may hold, per object: the object's own fields of type text, long text or sourced text, or
# arrays of these. References aren't translated: a section's room and the event's rooms keep their names. Other members
# are ignored.
TRANSLATABLE = {
    "collection": {"title": "text", "subtitle": "text", "description": "long text"},
    "event": {"title": "text", "venue": "text", "city": "text"},
    "rym_list": {"title": "text", "author": "text"},
    "series": {"title": "text", "part": "text"},
    "curator": {"name": "text"},
    "link": {"title": "text"},
    "person": {"name": "text", "sort_name": "text", "native_name": "text", "pronunciation": "text", "tagline": "text",
               "bio": "sourced text", "facts": "sourced texts"},
    "section": {"title": "text", "description": "long text", "reason": "text"},
    "album": {"native_title": "text", "title_meaning": "text", "hook": "text"},
    "item": {"title": "text", "title_meaning": "text", "artist": "text", "notes": "long text", "reason": "text",
             "tags": "texts"},
}
NOUNS = {"collection": "collection", "event": "event", "rym_list": "rym_list object", "series": "series object", "curator": "curator",
         "link": "link", "person": "person",
         "section": "section", "album": "album object", "item": "item"}
AUDIO_EXT = {"mp3", "m4a", "m4b", "aac", "flac", "opus", "wav", "aiff", "aif"}  # §5.1; formats beyond MP3 and M4A since 2026-11-10
IMAGE_EXT = {"jpg", "jpeg", "png"}
WINDOWS_DEVICES = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(10)} | {f"lpt{i}" for i in range(10)}
CONTROL = set(range(0x00, 0x20)) | set(range(0x7F, 0xA0))
BANNED_TEXT = CONTROL | {0x2028, 0x2029} | set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A))
PATH_CHARS = set('\\:*?"<>|')

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[45][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
KEY_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
EXT_KEY_RE = re.compile(r"^(?=.{3,128}$)[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+$")
VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
TS_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|([+-])(\d{2}):(\d{2}))$")
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
# RFC 5646 well-formedness, approximately: language, extlang, script, region, variants, extensions, private use.
LANG_RE = re.compile(r"^(?:(?:[A-Za-z]{2,3}(?:-[A-Za-z]{3}){0,3}|[A-Za-z]{4,8})(?:-[A-Za-z]{4})?(?:-(?:[A-Za-z]{2}|[0-9]{3}))?"
                     r"(?:-(?:[A-Za-z0-9]{5,8}|[0-9][A-Za-z0-9]{3}))*(?:-[0-9A-WY-Za-wy-z](?:-[A-Za-z0-9]{2,8})+)*"
                     r"(?:-[Xx](?:-[A-Za-z0-9]{1,8})+)?|[Xx](?:-[A-Za-z0-9]{1,8})+)$")


class JFloat(float):
    """A JSON number written with a fraction or an exponent: never an integer."""


class Repeated(Exception):
    pass


class Report:
    def __init__(self, label, mode):
        self.label, self.mode, self.errors, self.warnings = label, mode, [], []
        self.lyrics_from = None  # for a manifest alone: the folder its lyrics files were read from

    def err(self, rule, message):
        self.errors.append(f"rule {rule}: {message}")

    def warn(self, message):
        self.warnings.append(message)


class Findings:
    """What the check of one lyrics file found. Errors break §5.7, so readers ignore the file; warnings don't."""

    def __init__(self):
        self.errors, self.warnings = [], []

    def err(self, rule, message):
        self.errors.append(message)

    def warn(self, message):
        self.warnings.append(message)


def is_int(v, low=0, high=MAX_INT):
    return type(v) is int and low <= v <= high


def is_number(v):
    return (type(v) is int or type(v) is JFloat) and math.isfinite(v)


def scalars_ok(s):
    return not any(0xD800 <= ord(c) <= 0xDFFF for c in s)


def utf8_len(s):
    return len(s.encode("utf-8"))


def fold(path):
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", path).casefold())


def text_problem(v, long=False):
    if type(v) is not str:
        return "isn't a string"
    if not scalars_ok(v):
        return "holds an unpaired surrogate"
    size = utf8_len(v)
    if long:
        if size > 65536:
            return "is longer than 64 KiB"
        banned = BANNED_TEXT - {0x0A}
    else:
        if size < 1 or size > 1024:
            return "must be 1 to 1,024 bytes"
        if v.strip() == "":
            return "is only white space"
        banned = BANNED_TEXT
    bad = sorted({ord(c) for c in v if ord(c) in banned})
    if bad:
        return "holds " + ", ".join(f"U+{c:04X}" for c in bad[:4])
    return None


def line_problem(v):
    """§5.7: a line's text follows the rule for text, except that it may be empty."""
    if v == "":
        return None
    if type(v) is str and utf8_len(v) > 1024:
        return "is longer than 1,024 bytes"
    return text_problem(v)


def url_problem(v):
    if type(v) is not str:
        return "isn't a string"
    if not scalars_ok(v) or utf8_len(v) > 2048:
        return "isn't a URL of at most 2,048 bytes"
    if any(c.isspace() or ord(c) in CONTROL for c in v):
        return "holds white space or a control character"
    try:
        parts = urlsplit(v)
        host, _ = parts.hostname, parts.port
    except ValueError:
        return "isn't a well-formed URL"
    if parts.scheme.lower() != "https":
        return "isn't https"
    if not parts.netloc or not host:
        return "has no host"
    if "@" in parts.netloc:
        return "has user information"
    return None


def timestamp_problem(v):
    if type(v) is not str:
        return "isn't a string"
    m = TS_RE.fullmatch(v)
    if not m:
        return "isn't an RFC 3339 date-time with seconds and an offset"
    y, mo, d, h, mi, s = (int(m.group(i)) for i in range(1, 7))
    try:
        datetime.datetime(y, mo, d, h, mi, min(s, 59))
    except ValueError:
        return "isn't a date and time that exists"
    if s > 60 or (m.group(9) and (int(m.group(10)) > 23 or int(m.group(11)) > 59)):
        return "has an impossible second or offset"
    return None


def parse_timestamp(v):
    try:
        return datetime.datetime.fromisoformat(v.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def date_problem(v):
    if type(v) is not str:
        return "isn't a string"
    m = DATE_RE.fullmatch(v)
    if not m:
        return "isn't YYYY-MM-DD"
    try:
        datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return "isn't a date that exists"
    return None


def language_problem(v):
    return None if type(v) is str and LANG_RE.fullmatch(v) else "isn't a BCP 47 tag"


def country_problem(v):
    return None if type(v) is str and re.fullmatch(r"[A-Z]{2}", v) else "isn't an ISO 3166-1 alpha-2 code"


def path_problem(v):
    if type(v) is not str or not v:
        return "isn't a non-empty string"
    if not scalars_ok(v):
        return "holds an unpaired surrogate"
    if not unicodedata.is_normalized("NFC", v):
        return "isn't in Unicode NFC"
    if utf8_len(v) > 1024:
        return "is longer than 1,024 bytes"
    if v.startswith("/"):
        return "starts with /"
    for part in v.split("/"):
        if part in ("", ".", ".."):
            return "has an empty part, . or .."
        if any(c in PATH_CHARS or ord(c) in CONTROL for c in part):
            return "holds a character paths may not hold"
        if utf8_len(part) > 255:
            return "has a part longer than 255 bytes"
        if part.endswith(".") or part.endswith(" "):
            return "has a part ending in a dot or a space"
        if part.split(".")[0].lower() in WINDOWS_DEVICES:
            return "has a part named like a Windows device"
    return None


def extension_of(path):
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def load_json(data, rep):
    value, problem = parse_json(data, "collection.json", MAX_MANIFEST, "8 MiB")
    if problem:
        rep.err(1, problem)
        return None
    if type(value) is not dict:
        # JSON null, a list or a scalar: rule 1 wants one object. None stands for a failed parse, so say it here.
        rep.err(1, "collection.json isn't a JSON object")
        return None
    return value


def parse_json(data, name, limit, limit_text):
    """§3's JSON rules, which lyrics files share (§5.7): (value, None), or (None, what's wrong)."""
    if len(data) > limit:
        return None, f"{name} is larger than {limit_text}"
    if data.startswith(b"\xef\xbb\xbf"):
        return None, f"{name} starts with a byte-order mark"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, f"{name} isn't UTF-8"

    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise Repeated(key)
            out[key] = value
        return out

    def parse_int(s):
        if len(s.lstrip("-")) > 20:
            return JFloat("inf")  # outside every range; reported as a type error, never rounded
        return int(s)

    def parse_constant(s):
        raise ValueError(f"{s} isn't JSON")

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_int=parse_int, parse_float=JFloat,
                          parse_constant=parse_constant), None
    except Repeated as r:
        return None, f"an object repeats the member name {str(r)!r}"
    except RecursionError:
        return None, f"{name} is nested too deeply"
    except ValueError as e:
        return None, f"{name} isn't valid JSON ({e})"


def depth(value):
    deepest, stack = 0, [(value, 1)]
    while stack:
        v, d = stack.pop()
        if isinstance(v, (dict, list)):
            deepest = max(deepest, d)
            stack.extend((x, d + 1) for x in (v.values() if isinstance(v, dict) else v))
    return deepest


def join(where, name):
    """Where a member is: where.name, or the name alone at the top of a lyrics file (where "")."""
    return f"{where}.{name}" if where else name


def lead(where):
    return f"{where} " if where else "the file "


class Checker:
    """Small helpers that report through self.rep and never raise on wrong types."""

    def __init__(self, rep):
        self.rep = rep

    def field(self, obj, name, where, check, required=False):
        if name not in obj:
            if required:
                self.rep.err(1, f"{lead(where)}has no {name}")
            return None
        value = obj[name]
        problem = check(value)
        if problem:
            self.rep.err(2 if check is path_problem else 1, f"{join(where, name)} {problem}")  # §9: paths are rule 2
            return None
        return value

    def text(self, long=False):
        return lambda v: text_problem(v, long)

    @staticmethod
    def integer(low=0, high=MAX_INT):
        return lambda v: None if is_int(v, low, high) else f"isn't an integer from {low:,} to {high:,}"

    @staticmethod
    def boolean(v):
        return None if type(v) is bool else "isn't true or false"

    @staticmethod
    def string(v):
        return None if type(v) is str and scalars_ok(v) else "isn't a string"

    def objects(self, obj, name, where, required=False, minimum=0):
        if name not in obj:
            if required:
                self.rep.err(1, f"{lead(where)}has no {name}")
            return []
        value = obj[name]
        w = join(where, name)
        if type(value) is not list:
            self.rep.err(1, f"{w} isn't an array")
            return []
        if len(value) < minimum:
            self.rep.err(1, f"{w} needs at least {minimum} entr{'y' if minimum == 1 else 'ies'}")
        out = []
        for i, entry in enumerate(value):
            if type(entry) is not dict:
                self.rep.err(1, f"{w}[{i}] isn't an object")
            else:
                out.append((i, entry))
        return out

    def known(self, obj, where, fields):
        for name in obj:
            if name not in fields:
                self.rep.warn(f"{lead(where)}has a field this spec doesn't define, {name!r} (readers ignore it)")

    def extensions(self, obj, where):
        if "extensions" not in obj:
            return
        ext = obj["extensions"]
        w = join(where, "extensions")
        if type(ext) is not dict:
            self.rep.err(1, f"{w} isn't an object")
            return
        for key in ext:
            if not EXT_KEY_RE.fullmatch(key):
                self.rep.err(1, f"{w} key {key!r} isn't two or more dot-separated parts of 3 to 128 characters")

    def rights(self, obj, where):
        if "rights" not in obj:
            return
        r = obj["rights"]
        w = join(where, "rights")
        if type(r) is not dict:
            self.rep.err(1, f"{w} isn't an object")
            return
        self.known(r, w, {"statement", "license", "url"})
        self.field(r, "statement", w, self.text(long=True))
        self.field(r, "license", w, self.string)
        self.field(r, "url", w, url_problem)
        if "statement" not in r and "license" not in r:
            self.rep.err(1, f"{w} needs a statement or a license")


class Manifest(Checker):
    """Checks one parsed manifest. Collects every path it names for the container checks."""

    def __init__(self, m, rep):
        super().__init__(rep)
        self.m = m
        self.audio = {}      # path -> files[] entry
        self.images = {}     # path -> where it's used
        self.lyrics = {}     # path -> where it's used
        self.ok = False

    def image(self, obj, name, where):
        path = self.field(obj, name, where, path_problem)
        if path is not None:
            self.images.setdefault(path, f"{where}.{name}")

    def credits(self, obj, name, where):
        for i, c in self.objects(obj, name, where):
            w = f"{where}.{name}[{i}]"
            self.known(c, w, {"person", "role"})
            person = self.field(c, "person", w, lambda v: None if type(v) is str and KEY_RE.fullmatch(v) else "isn't a key", True)
            if person is not None and person not in self.people:
                self.rep.err(4, f"{w}.person {person!r} isn't in people")
            role = self.field(c, "role", w, self.string, True)
            if role is not None and role not in ROLES:
                self.rep.warn(f"{w}.role {role!r} is unknown; readers show it as other")

    def unique_key(self, obj, where, seen, kind):
        key = self.field(obj, "id", where, lambda v: None if type(v) is str and KEY_RE.fullmatch(v) else "isn't a key", True)
        if key is not None:
            if key in seen:
                self.rep.err(1, f"{where}.id {key!r} repeats another {kind}'s id")
            seen.add(key)
        return key

    def check(self):
        m, rep = self.m, self.rep
        if type(m) is not dict:
            rep.err(1, "collection.json isn't a JSON object")
            return
        if depth(m) > MAX_DEPTH:
            rep.err(1, f"collection.json is nested more than {MAX_DEPTH} levels deep")
            return
        self.known(m, "the manifest", {"etui", "id", "revision", "updated", "kind", "title", "subtitle", "description",
                                       "language", "translations", "artwork", "curator", "generator", "rights", "event",
                                       "rym_list", "series", "people", "sections", "files", "items", "playback", "extensions"})
        version = self.field(m, "etui", "the manifest", lambda v: None if type(v) is str and VERSION_RE.fullmatch(v)
                             else "isn't a MAJOR.MINOR version", True)
        if version is not None:
            major, minor = (int(x) for x in version.split("."))
            if major != 1:
                rep.err(1, f"the file needs a reader for version {major}; this checks version 1")
                return
            if minor > 0:
                rep.warn(f"version 1.{minor} is newer than 1.0; fields this checker doesn't know are only reported")
        self.field(m, "id", "the manifest", lambda v: None if type(v) is str and UUID_RE.fullmatch(v)
                   else "isn't a lowercase version-4 or version-5 UUID", True)
        self.field(m, "revision", "the manifest", self.integer(1, MAX_REVISION), True)
        if self.field(m, "updated", "the manifest", timestamp_problem) is None and "updated" not in m:
            rep.warn("the manifest has no updated time (SHOULD)")
        kind = self.field(m, "kind", "the manifest", self.string)
        if kind is not None and kind not in KINDS:
            rep.warn(f"kind {kind!r} is unknown; readers treat it as playlist")
        self.field(m, "title", "the manifest", self.text(), True)
        self.field(m, "subtitle", "the manifest", self.text())
        self.field(m, "description", "the manifest", self.text(long=True))
        self.field(m, "language", "the manifest", language_problem)
        self.translations(m, "the manifest", "collection")
        self.image(m, "artwork", "the manifest")
        for name in ("curator", "generator"):
            if name in m:
                obj = m[name]
                if type(obj) is not dict:
                    rep.err(1, f"{name} isn't an object")
                    continue
                self.known(obj, name, {"name", "url", "translations"} if name == "curator" else {"name", "version"})
                self.field(obj, "name", name, self.text(), True)
                if name == "curator":
                    self.field(obj, "url", name, url_problem)
                    self.translations(obj, name, "curator")
                else:
                    self.field(obj, "version", name, self.text())
        self.rights(m, "the manifest")
        self.extensions(m, "the manifest")
        self.check_event()
        self.check_rym_list()
        self.check_series()
        self.check_people()
        self.check_sections()
        self.check_files()
        self.check_items()
        self.check_playback()
        # Rule 2 across every path the manifest names, audio, images and lyrics alike.
        folded = {}
        for path in list(self.audio) + list(self.images) + list(self.lyrics):
            other = folded.setdefault(fold(path), path)
            if other != path:
                rep.err(2, f"the paths {other!r} and {path!r} collide")
        self.ok = not rep.errors

    def check_event(self):
        self.rooms = set()
        if "event" not in self.m:
            return
        e = self.m["event"]
        if type(e) is not dict:
            self.rep.err(1, "event isn't an object")
            return
        self.known(e, "event", {"title", "venue", "city", "country", "starts", "ends", "rooms", "url", "translations",
                                "extensions"})
        self.field(e, "title", "event", self.text(), True)
        for name in ("venue", "city"):
            self.field(e, name, "event", self.text())
        self.field(e, "country", "event", country_problem)
        starts = self.field(e, "starts", "event", timestamp_problem)
        ends = self.field(e, "ends", "event", timestamp_problem)
        if starts and ends and parse_timestamp(ends) < parse_timestamp(starts):
            self.rep.err(1, "event.ends is before event.starts")
        self.field(e, "url", "event", url_problem)
        self.translations(e, "event", "event")
        self.extensions(e, "event")
        self.rooms = self.room_list(e, "rooms", "event")

    def room_list(self, obj, name, where):
        """Rooms or stages, each listed once (§3.2)."""
        rooms = set()
        if name not in obj:
            return rooms
        w = join(where, name)
        if type(obj[name]) is not list:
            self.rep.err(1, f"{w} isn't an array")
            return rooms
        for i, room in enumerate(obj[name]):
            problem = text_problem(room)
            if problem:
                self.rep.err(1, f"{w}[{i}] {problem}")
            elif room in rooms:
                self.rep.err(1, f"{w} lists {room!r} twice")
            else:
                rooms.add(room)
        return rooms

    def check_series(self):
        """§3.5: the series the collection belongs to, by its id, with its title and this collection's part."""
        if "series" not in self.m:
            return
        s = self.m["series"]
        if type(s) is not dict:
            self.rep.err(1, "series isn't an object")
            return
        self.known(s, "series", {"id", "title", "part", "translations", "extensions"})
        self.field(s, "id", "series", lambda v: None if type(v) is str and UUID_RE.fullmatch(v)
                   else "isn't a lowercase version-4 or version-5 UUID", True)
        self.field(s, "title", "series", self.text(), True)
        self.field(s, "part", "series", self.text())
        self.translations(s, "series", "series")
        self.extensions(s, "series")

    def check_rym_list(self):
        if "rym_list" not in self.m:
            return
        r = self.m["rym_list"]
        if type(r) is not dict:
            self.rep.err(1, "rym_list isn't an object")
            return
        self.known(r, "rym_list", {"title", "url", "author", "round", "translations", "extensions"})
        self.field(r, "title", "rym_list", self.text())
        self.field(r, "url", "rym_list", url_problem)
        self.field(r, "author", "rym_list", self.text())
        self.field(r, "round", "rym_list", self.integer(1))
        self.translations(r, "rym_list", "rym_list")
        self.extensions(r, "rym_list")

    def translations(self, obj, where, kind):
        """§3.4: the object's own text fields in other languages. Each has the original's type and rules (rule 1);
        anything else in a translation is ignored by readers."""
        if "translations" not in obj:
            return
        tr, w = obj["translations"], join(where, "translations")
        if type(tr) is not dict:
            self.rep.err(1, f"{w} isn't an object")
            return
        fields = TRANSLATABLE[kind]
        for tag, value in tr.items():
            tw = f"{w}.{tag}"
            if not LANG_RE.fullmatch(tag):
                self.rep.err(1, f"{w} key {tag!r} isn't a BCP 47 tag")
            if type(value) is not dict:
                self.rep.err(1, f"{tw} isn't an object")
                continue
            for name in value:
                form = fields.get(name)
                if form is None:
                    self.rep.warn(f"{tw}.{name} isn't one of the {NOUNS[kind]}'s text fields; readers ignore it")
                elif form in ("text", "long text"):
                    self.field(value, name, tw, self.text(long=form == "long text"))
                elif form == "sourced text":
                    self.sourced(value[name], f"{tw}.{name}")
                elif form == "sourced texts":
                    self.sourced_list(value, name, tw)
                elif form == "texts":
                    self.text_list(value, name, tw)
                else:
                    self.room_list(value, name, tw)

    def text_list(self, obj, name, where):
        if name not in obj:
            return
        w = join(where, name)
        if type(obj[name]) is not list:
            self.rep.err(1, f"{w} isn't an array")
            return
        for j, entry in enumerate(obj[name]):
            problem = text_problem(entry)
            if problem:
                self.rep.err(1, f"{w}[{j}] {problem}")

    def sourced_list(self, obj, name, where):
        if name not in obj:
            return
        w = join(where, name)
        if type(obj[name]) is not list:
            self.rep.err(1, f"{w} isn't an array")
            return
        for j, entry in enumerate(obj[name]):
            self.sourced(entry, f"{w}[{j}]")

    def links(self, obj, where):
        for j, link in self.objects(obj, "links", where):
            lw = f"{where}.links[{j}]"
            self.known(link, lw, {"kind", "title", "url", "translations"})
            self.translations(link, lw, "link")
            self.field(link, "title", lw, self.text(), True)
            self.field(link, "url", lw, url_problem, True)
            lk = self.field(link, "kind", lw, self.string)
            if lk is not None and lk not in LINK_KINDS:
                self.rep.warn(f"{lw}.kind {lk!r} is unknown; readers show it as other")

    def sourced(self, obj, where):
        if type(obj) is not dict:
            self.rep.err(1, f"{where} isn't an object")
            return
        self.known(obj, where, {"text", "source", "url"})
        text = self.field(obj, "text", where, self.text(long=True), True)
        if text is not None and text.strip() == "":
            self.rep.err(1, f"{where}.text is empty")
        self.field(obj, "source", where, self.text(), True)
        self.field(obj, "url", where, url_problem)

    def check_people(self):
        self.people, members = {}, {}
        seen = set()
        for i, p in self.objects(self.m, "people", "the manifest"):
            w = f"people[{i}]"
            self.known(p, w, {"id", "name", "sort_name", "native_name", "pronunciation", "members", "tagline", "bio",
                              "facts", "links", "image", "dates_url", "translations", "extensions"})
            key = self.unique_key(p, w, seen, "person")
            if key is not None:
                self.people[key] = p
            for name in ("name", "sort_name", "native_name", "pronunciation", "tagline"):
                self.field(p, name, w, self.text(), name == "name")
            if "bio" in p:
                self.sourced(p["bio"], f"{w}.bio")
            self.sourced_list(p, "facts", w)
            self.links(p, w)
            self.image(p, "image", w)
            self.field(p, "dates_url", w, url_problem)
            self.translations(p, w, "person")
            self.extensions(p, w)
            if "members" in p:
                if type(p["members"]) is not list or not all(type(x) is str for x in p["members"]):
                    self.rep.err(1, f"{w}.members isn't an array of keys")
                elif key is not None:
                    members[key] = p["members"]
        for key, ms in members.items():
            for member in ms:
                if member == key:
                    self.rep.err(4, f"person {key!r} is their own member")
                elif member not in self.people:
                    self.rep.err(4, f"person {key!r} has member {member!r}, who isn't in people")
        # Membership can't form a cycle.
        state = {}

        def visit(node, trail):
            state[node] = 1
            for nxt in members.get(node, []):
                if nxt == node or nxt not in self.people:
                    continue
                if state.get(nxt) == 1:
                    self.rep.err(4, "membership forms a cycle: " + " → ".join(trail + [nxt]))
                elif state.get(nxt) is None:
                    visit(nxt, trail + [nxt])
            state[node] = 2

        for key in members:
            if state.get(key) is None:
                visit(key, [key])

    def check_sections(self):
        self.sections = {}
        self.section_order = []
        seen = set()
        for i, s in self.objects(self.m, "sections", "the manifest"):
            w = f"sections[{i}]"
            self.known(s, w, {"id", "title", "kind", "number", "people", "room", "starts", "artwork", "links", "album",
                              "reason", "translations", "description", "extensions"})
            key = self.unique_key(s, w, seen, "section")
            if key is not None:
                self.sections[key] = s
                self.section_order.append(key)
            self.field(s, "title", w, self.text(), True)
            kind = self.field(s, "kind", w, self.string)
            if kind is not None and kind not in SECTION_KINDS:
                self.rep.warn(f"{w}.kind {kind!r} is unknown; readers show it as other")
            self.field(s, "number", w, self.integer())
            self.credits(s, "people", w)
            room = self.field(s, "room", w, self.text())
            if room is not None and room not in self.rooms:
                self.rep.err(4, f"{w}.room {room!r} isn't one of event.rooms")
            self.field(s, "starts", w, timestamp_problem)
            self.image(s, "artwork", w)
            self.links(s, w)
            self.check_album(s, w)
            self.field(s, "reason", w, self.text())
            self.translations(s, w, "section")
            self.field(s, "description", w, self.text(long=True))
            self.extensions(s, w)

    def check_album(self, s, w):
        """§5.2.1: what a section of kind album says about its release."""
        if "album" not in s:
            return
        a, aw = s["album"], f"{w}.album"
        if type(a) is not dict:
            self.rep.err(1, f"{aw} isn't an object")
            return
        self.known(a, aw, {"native_title", "title_meaning", "year", "country", "language", "hook", "rating",
                           "translations", "extensions"})
        for name in ("native_title", "title_meaning"):
            self.field(a, name, aw, self.text())
        self.field(a, "year", aw, self.integer(1000, 9999))
        self.field(a, "country", aw, country_problem)
        self.field(a, "language", aw, language_problem)
        self.field(a, "hook", aw, self.text())
        self.check_rating(a, aw)
        self.translations(a, aw, "album")
        self.extensions(a, aw)

    def check_rating(self, a, w):
        """§5.2.1: how listeners rate the album on a site."""
        if "rating" not in a:
            return
        r, rw = a["rating"], f"{w}.rating"
        if type(r) is not dict:
            self.rep.err(1, f"{rw} isn't an object")
            return
        self.known(r, rw, {"source", "value", "best", "ratings", "reviews", "retrieved"})
        number = lambda v: None if is_number(v) else "isn't a number"
        self.field(r, "source", rw, self.text(), required=True)
        value = self.field(r, "value", rw, number, required=True)
        best = self.field(r, "best", rw, number, required=True)
        self.field(r, "ratings", rw, self.integer())
        self.field(r, "reviews", rw, self.integer())
        self.field(r, "retrieved", rw, date_problem)
        if value is not None and best is not None and not (best > 0 and 0 <= value <= best):
            self.rep.err(1, f"{rw}.value isn't from 0 to its best, which is above 0")

    def skyline(self, f, w):
        """§5.1: base64 of one byte a second, as many as the file has seconds, give or take one."""
        value = f["skyline"]
        try:
            levels = base64.b64decode(value, validate=True) if type(value) is str else None
        except (ValueError, binascii.Error):
            levels = None
        if not levels:
            self.rep.err(1, f"{w}.skyline isn't base64 of one byte a second")
            return
        duration = f.get("duration_ms")
        if is_int(duration, 0, MAX_MS):
            seconds = (duration + 999) // 1000
            if abs(len(levels) - seconds) > 1:
                self.rep.err(1, f"{w}.skyline has {len(levels)} seconds, and the file {seconds}")

    def check_files(self):
        folded = {}
        for i, f in self.objects(self.m, "files", "the manifest", required=True, minimum=1):
            w = f"files[{i}]"
            self.known(f, w, {"path", "sha256", "bytes", "format", "duration_ms", "codec", "bitrate_kbps", "sample_rate_hz",
                              "channels", "loudness", "skyline", "rights", "extensions"})
            path = self.field(f, "path", w, path_problem, True)
            self.field(f, "sha256", w, lambda v: None if type(v) is str and SHA_RE.fullmatch(v) else "isn't 64 lowercase hex digits", True)
            self.field(f, "bytes", w, self.integer(1), True)
            ext = extension_of(path) if path else ""
            fmt = self.field(f, "format", w, self.string)
            if fmt is not None and path is not None and fmt != ext:
                self.rep.err(1, f"{w}.format {fmt!r} isn't the path's extension {ext!r}")
            if path is not None and ext not in AUDIO_EXT:
                self.rep.warn(f"{w} is .{ext or '(none)'}, not a 1.0 format (MP3, M4A, AAC, FLAC, Opus, WAV, AIFF): readers leave out its items")
            if self.field(f, "duration_ms", w, self.integer(0, MAX_MS)) is None and "duration_ms" not in f:
                self.rep.warn(f"{w} has no duration_ms (SHOULD)")
            self.field(f, "codec", w, self.text())
            for name in ("bitrate_kbps", "sample_rate_hz", "channels"):
                self.field(f, name, w, self.integer())
            if "loudness" in f:
                loud = f["loudness"]
                if type(loud) is not dict:
                    self.rep.err(1, f"{w}.loudness isn't an object")
                else:
                    for name in ("integrated_lufs", "true_peak_dbtp"):
                        self.field(loud, name, f"{w}.loudness", lambda v: None if is_number(v) else "isn't a number", True)
            if "skyline" in f:
                self.skyline(f, w)
            self.rights(f, w)
            self.extensions(f, w)
            if path is not None:
                if path in self.audio:
                    self.rep.err(1, f"{w}.path {path!r} is listed twice")
                    continue
                other = folded.get(fold(path))
                if other is not None:
                    self.rep.err(2, f"{w}.path {path!r} collides with {other!r}")
                folded[fold(path)] = path
                self.audio[path] = f

    def stretch(self, item, w, file):
        duration = file.get("duration_ms") if file and is_int(file.get("duration_ms"), 0, MAX_MS) else None
        start = self.field(item, "start_ms", w, self.integer(0, MAX_MS))
        end = self.field(item, "end_ms", w, self.integer(0, MAX_MS))
        s = start if start is not None else 0
        e = end if end is not None else duration
        if e is not None and s >= e:
            self.rep.err(5, f"{w}'s stretch is empty or starts after it ends")
        if duration is not None and end is not None and end > duration:
            self.rep.err(5, f"{w}.end_ms is past its file's duration_ms")
        if duration is not None and start is not None and start >= duration:
            self.rep.err(5, f"{w}.start_ms is at or past its file's duration_ms")
        return s, e

    def check_items(self):
        seen, used, seq = set(), set(), []
        items = self.objects(self.m, "items", "the manifest", required=True, minimum=1)
        if len(items) > READER_MAX_ITEMS:
            self.rep.warn(f"{len(items):,} items is more than the Etui app's limit of {READER_MAX_ITEMS:,}")
        for i, it in items:
            w = f"items[{i}]"
            self.known(it, w, {"id", "file", "title", "title_meaning", "kind", "section", "credits", "artist", "start_ms", "end_ms", "disc",
                               "artwork", "lyrics", "recorded", "published", "source", "chapters", "highlights", "notes",
                               "reason", "tags", "translations", "rights", "extensions"})
            self.unique_key(it, w, seen, "item")
            path = self.field(it, "file", w, path_problem, True)
            file = None
            if path is not None:
                file = self.audio.get(path)
                if file is None:
                    self.rep.err(4, f"{w}.file {path!r} doesn't match any files[].path")
                else:
                    used.add(path)
            self.field(it, "title", w, self.text(), True)
            kind = self.field(it, "kind", w, self.string)
            if kind is not None and kind not in ITEM_KINDS:
                self.rep.warn(f"{w}.kind {kind!r} is unknown; readers show it as other")
            section = self.field(it, "section", w, lambda v: None if type(v) is str and KEY_RE.fullmatch(v) else "isn't a key")
            if section is not None:
                if section not in self.sections:
                    self.rep.err(4, f"{w}.section {section!r} isn't a section")
                else:
                    seq.append(section)
            self.credits(it, "credits", w)
            self.field(it, "title_meaning", w, self.text())
            self.field(it, "artist", w, self.text())
            s, e = self.stretch(it, w, file)
            self.field(it, "disc", w, self.integer(1))
            self.image(it, "artwork", w)
            lyrics = self.field(it, "lyrics", w, path_problem)
            if lyrics is not None:
                self.lyrics.setdefault(lyrics, f"{w}.lyrics")
                if extension_of(lyrics) != "json":
                    self.rep.warn(f"{w}.lyrics {lyrics!r} doesn't end in .json (SHOULD)")
            self.field(it, "recorded", w, lambda v: None if date_problem(v) is None or timestamp_problem(v) is None
                       else "isn't a date or an RFC 3339 date-time")
            self.field(it, "published", w, date_problem)
            if "source" in it:
                src, sw = it["source"], f"{w}.source"
                if type(src) is not dict:
                    self.rep.err(1, f"{sw} isn't an object")
                else:
                    self.known(src, sw, {"service", "url", "id", "uploader", "retrieved"})
                    for name in ("service", "id", "uploader"):
                        self.field(src, name, sw, self.text())
                    self.field(src, "url", sw, url_problem)
                    self.field(src, "retrieved", sw, timestamp_problem)
            self.check_chapters(it, w, s, e)
            self.check_highlights(it, w, s, e)
            self.field(it, "notes", w, self.text(long=True))
            self.field(it, "reason", w, self.text())
            self.text_list(it, "tags", w)
            self.translations(it, w, "item")
            self.rights(it, w)
            self.extensions(it, w)
        for path in self.audio:
            if path not in used:
                self.rep.warn(f"the file {path!r} isn't used by any item (SHOULD be)")
        # Rule 6: a section's items are adjacent, and sections are listed in the order their items first appear.
        runs = [key for n, key in enumerate(seq) if n == 0 or seq[n - 1] != key]
        if len(runs) != len(set(runs)):
            self.rep.err(6, "a section's items aren't next to each other")
        elif runs != [key for key in self.section_order if key in set(runs)]:
            self.rep.err(6, "sections aren't listed in the order their first items appear")

    def check_chapters(self, it, w, s, e):
        chapters = self.objects(it, "chapters", w)
        if len(chapters) > MAX_PER_ITEM:
            self.rep.err(6, f"{w} has more than {MAX_PER_ITEM} chapters")
        parsed = []
        for j, c in chapters:
            cw = f"{w}.chapters[{j}]"
            self.known(c, cw, {"start_ms", "end_ms", "title", "artist", "exact"})
            start = self.field(c, "start_ms", cw, self.integer(0, MAX_MS), True)
            end = self.field(c, "end_ms", cw, self.integer(0, MAX_MS))
            self.field(c, "title", cw, self.text(), True)
            self.field(c, "artist", cw, self.text())
            self.field(c, "exact", cw, self.boolean)
            parsed.append((cw, start, end))
        for n, (cw, start, end) in enumerate(parsed):
            if start is None:
                continue
            if start < s or (e is not None and start >= e):
                self.rep.err(5, f"{cw} starts outside its item's stretch")
            following = next((p[1] for p in parsed[n + 1:] if p[1] is not None), None)
            if following is not None and following <= start:
                self.rep.err(6, f"{cw}: chapter starts don't strictly increase")
            if end is not None:
                if end <= start:
                    self.rep.err(5, f"{cw} ends before it starts")
                if following is not None and end > following:
                    self.rep.err(6, f"{cw} overlaps the next chapter")
                if e is not None and end > e:
                    self.rep.err(5, f"{cw} ends outside its item's stretch")

    def check_highlights(self, it, w, s, e):
        highlights = self.objects(it, "highlights", w)
        if len(highlights) > MAX_PER_ITEM:
            self.rep.err(6, f"{w} has more than {MAX_PER_ITEM} highlights")
        previous = None
        for j, h in highlights:
            hw = f"{w}.highlights[{j}]"
            self.known(h, hw, {"start_ms", "end_ms", "label", "evidence"})
            start = self.field(h, "start_ms", hw, self.integer(0, MAX_MS), True)
            end = self.field(h, "end_ms", hw, self.integer(0, MAX_MS), True)
            self.field(h, "label", hw, self.text())
            if start is not None and end is not None:
                if start >= end:
                    self.rep.err(5, f"{hw} is empty or ends before it starts")
                if start < s or (e is not None and end > e):
                    self.rep.err(5, f"{hw} lies outside its item's stretch")
            if start is not None:
                if previous is not None and start < previous:
                    self.rep.err(6, f"{hw} is out of start_ms order")
                previous = start
            if "evidence" in h:
                ev, ew = h["evidence"], f"{hw}.evidence"
                if type(ev) is not dict:
                    self.rep.err(1, f"{ew} isn't an object")
                else:
                    self.known(ev, ew, {"method", "listeners", "confidence"})
                    self.field(ev, "method", ew, self.text())
                    self.field(ev, "listeners", ew, self.integer())
                    self.field(ev, "confidence", ew, lambda v: None if is_number(v) and 0 <= v <= 1 else "isn't a number from 0 to 1")

    def check_playback(self):
        if "playback" not in self.m:
            return
        pb = self.m["playback"]
        if type(pb) is not dict:
            self.rep.err(1, "playback isn't an object")
            return
        self.known(pb, "playback", {"order", "continuous", "resume", "skip_back_s", "skip_forward_s", "speed_adjustable"})
        for name, allowed in (("order", {"sequential", "shuffle"}), ("resume", {"always", "never"})):
            value = self.field(pb, name, "playback", self.string)
            if value is not None and value not in allowed:
                self.rep.warn(f"playback.{name} {value!r} is unknown; readers use the default")
        for name in ("continuous", "speed_adjustable"):
            self.field(pb, name, "playback", self.boolean)
        for name in ("skip_back_s", "skip_forward_s"):
            self.field(pb, name, "playback", self.integer(1, 600))


class Lyrics(Checker):
    """§5.7 for one lyrics file's bytes. What breaks the file goes in the findings' errors, the rest in warnings."""

    def __init__(self, data):
        super().__init__(Findings())
        self.data = data

    def check(self):
        lyr, problem = parse_json(self.data, "the file", MAX_LYRICS, "1 MiB")
        if problem:
            self.rep.err(None, problem)
            return self.rep
        if type(lyr) is not dict:
            self.rep.err(None, "the file isn't a JSON object")
            return self.rep
        if depth(lyr) > MAX_DEPTH:
            self.rep.err(None, f"the file is nested more than {MAX_DEPTH} levels deep")
            return self.rep
        self.known(lyr, "", {"language", "lines", "timing", "translations", "source", "rights", "extensions"})
        if self.field(lyr, "language", "", language_problem) is None and "language" not in lyr:
            self.rep.warn("the file has no language (SHOULD)")
        texts = self.lines(lyr, "")
        timing = self.field(lyr, "timing", "", self.string)
        if timing is not None and timing not in ("exact", "estimated"):
            self.rep.warn(f"timing {timing!r} is unknown; readers read it as exact")
        self.translations(lyr, texts)
        if "source" in lyr:
            src = lyr["source"]
            if type(src) is not dict:
                self.rep.err(None, "source isn't an object")
            else:
                self.known(src, "source", {"name", "url"})
                self.field(src, "name", "source", self.text(), True)
                self.field(src, "url", "source", url_problem)
        self.rights(lyr, "")
        self.extensions(lyr, "")
        return self.rep

    def lines(self, obj, where):
        """The file's lines. Returns each line's text, None where the line is broken, or None when lines is."""
        w = join(where, "lines")
        if "lines" not in obj:
            self.rep.err(None, f"{lead(where)}has no lines")
            return None
        value = obj["lines"]
        if type(value) is not list:
            self.rep.err(None, f"{w} isn't an array")
            return None
        if not value:
            self.rep.err(None, f"{w} is empty: the file has 1 to {MAX_LINES:,} lines")
        elif len(value) > MAX_LINES:
            self.rep.err(None, f"{w} has {len(value):,} lines, more than {MAX_LINES:,}")
        texts, timed, untimed, previous = [], None, None, None
        for i, line in enumerate(value):
            lw = f"{w}[{i}]"
            if type(line) is not dict:
                self.rep.err(None, f"{lw} isn't an object")
                texts.append(None)
                continue
            self.known(line, lw, {"text", "start_ms"})
            texts.append(self.field(line, "text", lw, line_problem, True))
            if "start_ms" not in line:
                untimed = i if untimed is None else untimed
                continue
            timed = i if timed is None else timed
            start = self.field(line, "start_ms", lw, self.integer(0, MAX_MS))
            if start is not None:
                if previous is not None and start < previous[1]:
                    self.rep.err(None, f"{lw}.start_ms is {start:,}, before {previous[0]}'s {previous[1]:,}: "
                                       "the times never go down")
                previous = (lw, start)
        if timed is not None and untimed is not None:
            self.rep.err(None, f"{w}[{untimed}] has no start_ms but {w}[{timed}] has one: "
                               "either every line has start_ms or none does")
        return texts

    def translated_lines(self, t, tw, texts):
        """A translation's lines: strings, not line objects, one for each of the file's lines (texts: theirs, when
        lines could be read), each following the rule for a line's text and empty exactly where that line is."""
        w = f"{tw}.lines"
        if "lines" not in t:
            self.rep.err(None, f"{tw} has no lines")
            return
        value = t["lines"]
        if type(value) is not list:
            self.rep.err(None, f"{w} isn't an array")
            return
        if texts is not None and len(value) != len(texts):
            self.rep.err(None, f"{w} has {len(value):,} lines, not exactly as many as the file's {len(texts):,}")
        objects = [i for i, line in enumerate(value) if type(line) is dict]
        if objects:  # one finding for the whole translation: it's one mistake, however long the words
            self.rep.err(None, f"{w} holds line objects ({len(objects):,} of {len(value):,}, the first at "
                               f"[{objects[0]}]): a translation's lines are strings, not line objects")
        for i, line in enumerate(value):
            lw = f"{w}[{i}]"
            if type(line) is dict:
                continue
            if type(line) is not str:
                self.rep.err(None, f"{lw} isn't a string")
                continue
            problem = line_problem(line)
            if problem:
                self.rep.err(None, f"{lw} {problem}")
                continue
            original = texts[i] if texts is not None and i < len(texts) else None
            if original is not None and (line == "") != (original == ""):
                state = (f"is empty, though lines[{i}].text isn't" if line == ""
                         else f"isn't empty, though lines[{i}].text is")
                self.rep.err(None, f"{lw} {state}: each is empty exactly where that line is empty")

    def translations(self, lyr, texts):
        """The lines in other languages, line by line."""
        if "translations" not in lyr:
            return
        tr = lyr["translations"]
        if type(tr) is not dict:
            self.rep.err(None, "translations isn't an object")
            return
        for tag, t in tr.items():
            tw = f"translations.{tag}"
            if not LANG_RE.fullmatch(tag):
                self.rep.err(None, f"translations key {tag!r} isn't a BCP 47 tag")
            if type(t) is not dict:
                self.rep.err(None, f"{tw} isn't an object")
                continue
            self.known(t, tw, {"lines", "by"})
            self.translated_lines(t, tw, texts)
            self.field(t, "by", tw, self.text())


def sniff_audio(head, ext):
    """Whether the file's first 16 bytes are what its extension says (§5.1). An ID3v2 tag may come first in MP3, AAC and FLAC."""
    tagged = head[:3] == b"ID3"
    if ext == "mp3":
        return tagged or (len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0)
    if ext in ("m4a", "m4b"):
        return head[4:8] == b"ftyp"
    if ext == "aac":  # ADTS: a 12-bit sync word, then layer 00
        return tagged or (len(head) >= 2 and head[0] == 0xFF and head[1] & 0xF6 == 0xF0)
    if ext == "flac":
        return tagged or head[:4] == b"fLaC"
    if ext == "opus":
        return head[:4] == b"OggS"
    if ext == "wav":
        return head[:4] == b"RIFF" and head[8:12] == b"WAVE"
    if ext in ("aiff", "aif"):
        return head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC")
    return False


def image_info(data):
    """(kind, width, height); width and height are None when the header can't be read."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(data) >= 24 and data[12:16] == b"IHDR":
            return ("png",) + struct.unpack(">II", data[16:24])
        return "png", None, None
    if data[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 4 <= len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker == 0xFF:
                i += 1
                continue
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            length = struct.unpack(">H", data[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF) and i + 9 <= len(data):
                height, width = struct.unpack(">HH", data[i + 5:i + 9])
                return "jpeg", width, height
            i += 2 + length
        return "jpeg", None, None
    return None, None, None


def image_metadata(data):
    """The kinds of metadata an image carries that §6 says producers SHOULD strip: EXIF, XMP, IPTC."""
    found = []
    if data[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 4 <= len(data) and data[i] == 0xFF:
            marker = data[i + 1]
            if marker == 0xDA:  # the image data starts: no more metadata segments
                break
            if marker == 0xFF:
                i += 1
                continue
            length = struct.unpack(">H", data[i + 2:i + 4])[0]
            body = data[i + 4:i + 2 + length]
            if marker == 0xE1 and body.startswith(b"Exif\x00\x00"):
                found.append("EXIF")
            elif marker == 0xE1 and body.startswith(b"http://ns.adobe.com/xap/1.0/\x00"):
                found.append("XMP")
            elif marker == 0xED and body.startswith(b"Photoshop 3.0\x00"):
                found.append("IPTC")
            i += 2 + length
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        i = 8
        while i + 8 <= len(data):
            length, kind = struct.unpack(">I4s", data[i:i + 8])
            body = data[i + 8:i + 8 + min(length, 64)]
            if kind == b"eXIf":
                found.append("EXIF")
            elif kind == b"iTXt" and body.startswith(b"XML:com.adobe.xmp\x00"):
                found.append("XMP")
            elif kind in (b"tEXt", b"zTXt", b"iTXt") and body.lower().startswith(b"raw profile type exif"):
                found.append("EXIF")
            elif kind in (b"tEXt", b"zTXt", b"iTXt") and body.lower().startswith(b"raw profile type iptc"):
                found.append("IPTC")
            elif kind == b"IEND":
                break
            i += 12 + length
    return sorted(set(found))


def check_contents(man, rep, open_audio, read_image, mode):
    """Rules 2 and 3 for files the manifest names, through the container's own accessors."""
    total = 0
    for path, entry in man.audio.items():
        opened = open_audio(path)
        if opened is None:
            rep.err(2, f"the audio file {path!r} doesn't exist")
            continue
        size, chunks, stored = opened
        if is_int(entry.get("bytes")) and size != entry["bytes"]:
            rep.err(3, f"{path!r} is {size:,} bytes, not {entry['bytes']:,}")
            continue
        digest, head = hashlib.sha256(), b""
        try:
            for chunk in chunks():
                if len(head) < 16:
                    head += chunk[:16 - len(head)]
                digest.update(chunk)
        except (zipfile.BadZipFile, OSError) as e:
            rep.err(2, f"{path!r} can't be read ({e})")
            continue
        total += size
        if entry.get("sha256") != digest.hexdigest():
            rep.err(3, f"{path!r} doesn't match its sha256")
        ext = extension_of(path)
        if ext in AUDIO_EXT and not sniff_audio(head, ext):
            rep.warn(f"{path!r} doesn't look like {ext.upper()}; readers leave out its items")
        if mode == "archive" and stored is False:
            rep.warn(f"{path!r} is compressed in the archive; audio SHOULD be stored")
    if total > READER_MAX_AUDIO:
        rep.warn(f"{total / 1024**3:.1f} GiB of audio is more than the Etui app's limit of 20 GiB")
    for path, where in man.images.items():
        ext = extension_of(path)
        if ext not in IMAGE_EXT:
            rep.warn(f"{where} {path!r} isn't .jpg, .jpeg or .png; readers ignore it")
            continue
        data = read_image(path)
        if data is None:
            rep.warn(f"{where} {path!r} doesn't exist; readers ignore it")
            continue
        if data is False:
            rep.warn(f"{where} {path!r} is larger than 4 MiB; readers ignore it")
            continue
        kind, width, height = image_info(data)
        expected = "png" if ext == "png" else "jpeg"
        if kind != expected:
            rep.warn(f"{where} {path!r} isn't a {expected.upper()} image; readers ignore it")
        elif width is None:
            rep.warn(f"{where} {path!r} has no readable size; readers may ignore it")
        elif width * height > MAX_PIXELS:
            rep.warn(f"{where} {path!r} is {width}×{height}, more than 16,000,000 pixels; readers ignore it")
        elif where == "the manifest.artwork" and (width != height or width < 1000):
            rep.warn(f"the collection's artwork is {width}×{height}; it SHOULD be square and at least 1000×1000")
        if kind == expected:
            metadata = image_metadata(data)
            if metadata:
                rep.warn(f"{where} {path!r} carries {', '.join(metadata)} metadata; producers SHOULD strip it (§6)")


def check_lyrics(man, rep, read):
    """§5.7: a lyrics file that's missing, too large or broken is ignored and reported, and the item still plays. So
    every finding is a warning naming the item, never a validity failure."""
    for path, where in man.lyrics.items():
        try:
            data = read(path)
        except (zipfile.BadZipFile, OSError, EOFError, zlib.error) as e:
            rep.warn(f"{where} {path!r} can't be read ({e}); readers ignore it, and the item still plays")
            continue
        if data is None:
            rep.warn(f"{where} {path!r} doesn't exist; readers ignore it, and the item still plays")
            continue
        if data is False:
            rep.warn(f"{where} {path!r} is larger than 1 MiB; readers ignore it, and the item still plays")
            continue
        found = Lyrics(data).check()
        for problem in found.errors:
            rep.warn(f"{where} {path!r}: {problem}; readers ignore the file, and the item still plays")
        for note in found.warnings:
            rep.warn(f"{where} {path!r}: {note}")


def locate(root, path):
    """Walks the path's parts, matching each to an actual directory entry in NFC (§2.2)."""
    current = root
    for part in path.split("/"):
        try:
            entries = {unicodedata.normalize("NFC", n): n for n in os.listdir(current)}
        except (NotADirectoryError, FileNotFoundError):
            return None
        actual = entries.get(part)
        if actual is None:
            return None
        current = current / actual
    mode = os.lstat(current).st_mode
    return current if stat.S_ISREG(mode) else None


def read_small(root, path, limit):
    """A file's bytes; None when it doesn't exist, False when it's larger than the limit."""
    found = locate(root, path)
    if found is None:
        return None
    if os.lstat(found).st_size > limit:
        return False
    return found.read_bytes()


def check_manifest_file(path):
    rep = Report(str(path), "manifest")
    data = path.read_bytes()
    m = load_json(data, rep)
    if m is not None:
        man = Manifest(m, rep)
        man.check()
        beside = path.with_suffix("")
        if man.lyrics and beside.is_dir():
            rep.lyrics_from = beside
            check_lyrics(man, rep, lambda p: read_small(beside, p, MAX_LYRICS))
    return rep


def check_folder(root):
    rep = Report(str(root), "folder")
    # Every entry: no links, regular files only, no two files colliding.
    files, folded = [], {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            full = os.path.join(directory, name)
            mode = os.lstat(full).st_mode
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if stat.S_ISLNK(mode):
                rep.err(2, f"{rel!r} is a symbolic link")
            elif stat.S_ISREG(mode):
                key = fold(rel)
                if key in folded:
                    rep.err(2, f"{rel!r} collides with {folded[key]!r}")
                folded[key] = rel
                files.append(rel)
            elif not stat.S_ISDIR(mode):
                rep.err(2, f"{rel!r} isn't a regular file")
    manifest = root / "collection.json"
    if not stat.S_ISREG(os.lstat(manifest).st_mode):
        rep.err(2, "collection.json isn't a regular file")
        return rep
    m = load_json(manifest.read_bytes(), rep)
    if m is None:
        return rep
    man = Manifest(m, rep)
    man.check()

    def open_audio(path):
        found = locate(root, path)
        if found is None:
            return None

        def chunks():
            with open(found, "rb") as handle:
                while block := handle.read(1 << 20):
                    yield block
        return os.lstat(found).st_size, chunks, None

    check_contents(man, rep, open_audio, lambda p: read_small(root, p, MAX_IMAGE_BYTES), "folder")
    check_lyrics(man, rep, lambda p: read_small(root, p, MAX_LYRICS))
    return rep


def zip_name(info):
    """The entry's name as UTF-8, whatever flag bit 11 says (§2.1); None when it isn't UTF-8."""
    raw = info.filename.encode("utf-8") if info.flag_bits & 0x800 else info.filename.encode("cp437")
    try:
        return raw.decode("utf-8"), raw
    except UnicodeDecodeError:
        return None, raw


def local_header(handle, info):
    """(name bytes, method, flags, crc, compressed, uncompressed, data offset) from the entry's local header."""
    handle.seek(info.header_offset)
    fixed = handle.read(30)
    if len(fixed) != 30 or fixed[:4] != b"PK\x03\x04":
        return None
    _, _, flags, method, _, _, crc, csize, usize, nlen, xlen = struct.unpack("<IHHHHHIIIHH", fixed)
    name = handle.read(nlen)
    extra = handle.read(xlen)
    if csize == 0xFFFFFFFF or usize == 0xFFFFFFFF:
        i = 0
        while i + 4 <= len(extra):
            tag, size = struct.unpack("<HH", extra[i:i + 4])
            body = extra[i + 4:i + 4 + size]
            if tag == 0x0001:
                values = [struct.unpack("<Q", body[k:k + 8])[0] for k in range(0, len(body) - 7, 8)]
                if usize == 0xFFFFFFFF and values:
                    usize = values.pop(0)
                if csize == 0xFFFFFFFF and values:
                    csize = values.pop(0)
            i += 4 + size
    return name, method, flags, crc, csize, usize, info.header_offset + 30 + nlen + xlen, xlen


def check_archive(path):
    rep = Report(str(path), "archive")
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        rep.err(2, f"isn't a readable ZIP ({e})")
        return rep
    with archive, open(path, "rb") as raw:
        infos = archive.infolist()
        entries, folded, spans = {}, {}, []
        for n, info in enumerate(infos):
            name, raw_name = zip_name(info)
            label = name if name is not None else raw_name.decode("utf-8", "replace")
            if name is None:
                rep.err(2, f"entry {n} has a name that isn't UTF-8")
                continue
            if info.flag_bits & 0x1:
                rep.err(2, f"{label!r} is encrypted")
            if info.compress_type not in (0, 8):
                rep.err(2, f"{label!r} uses compression method {info.compress_type}, not 0 or 8")
            kind = stat.S_IFMT(info.external_attr >> 16)  # 0 when the writer stored permissions only
            if kind == stat.S_IFLNK:
                rep.err(2, f"{label!r} is a symbolic link")
            elif kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                rep.err(2, f"{label!r} is a special entry")
            header = local_header(raw, info)
            if header is None:
                rep.err(2, f"{label!r} has no local header where the central directory says")
                continue
            lname, lmethod, lflags, lcrc, lcsize, lusize, data_at, xlen = header
            if lname != raw_name or lmethod != info.compress_type:
                rep.err(2, f"{label!r}: its local header disagrees with the central directory")
            elif not lflags & 0x8 and (lcrc, lcsize, lusize) != (info.CRC, info.compress_size, info.file_size):
                rep.err(2, f"{label!r}: its local header's sizes or CRC disagree with the central directory")
            spans.append((info.header_offset, data_at + info.compress_size, label))
            if name.endswith("/"):
                if info.file_size:
                    rep.err(2, f"{label!r} is a directory entry with data")
                continue
            problem = path_problem(name)
            if problem:
                rep.err(2, f"the entry name {label!r} {problem}")
            if name in entries:
                rep.err(2, f"{label!r} appears twice")
            key = fold(name)
            if key in folded and folded[key] != name:
                rep.err(2, f"{label!r} collides with {folded[key]!r}")
            folded.setdefault(key, name)
            entries[unicodedata.normalize("NFC", name)] = (info, xlen)
        spans.sort()
        for (_, end, a), (start, _, b) in zip(spans, spans[1:]):
            if start < end:
                rep.err(2, f"entries {a!r} and {b!r} overlap")
        file_infos = [i for i in infos if not i.filename.endswith("/")]
        first = file_infos[0] if file_infos else None
        if first is None or zip_name(first)[0] != "mimetype":
            rep.warn("the first entry isn't mimetype (SHOULD)")
        else:
            xlen = entries["mimetype"][1]
            if first.compress_type != 0 or xlen or first.flag_bits & 0x8 or archive.read(first) != MIMETYPE:
                rep.warn("the mimetype entry isn't stored, bare and exactly application/vnd.etui+zip (SHOULD)")
        if len(file_infos) > 1 and zip_name(file_infos[1])[0] != "collection.json":
            rep.warn("collection.json isn't the second entry (SHOULD)")
        unflagged = [zip_name(i)[0] for i in infos if zip_name(i)[0] and not i.flag_bits & 0x800
                     and not zip_name(i)[0].isascii()]
        if unflagged:
            rep.warn(f"{len(unflagged)} entry name(s) beyond ASCII, such as {unflagged[0]!r}, don't set the UTF-8 flag "
                     "(general-purpose bit 11); producers SHOULD set it (§2.1)")
        manifest = entries.get("collection.json")
        if manifest is None:
            rep.err(2, "there's no collection.json at the root")
            return rep
        if manifest[0].file_size > MAX_MANIFEST:
            rep.err(1, "collection.json is larger than 8 MiB")
            return rep
        try:
            data = archive.read(manifest[0])
        except (zipfile.BadZipFile, OSError) as e:
            rep.err(2, f"collection.json can't be read ({e})")
            return rep
        m = load_json(data, rep)
        if m is None:
            return rep
        man = Manifest(m, rep)
        man.check()

        def open_audio(p):
            found = entries.get(p)
            if found is None:
                return None
            info = found[0]

            def chunks():
                with archive.open(info) as handle:
                    while block := handle.read(1 << 20):
                        yield block
            return info.file_size, chunks, info.compress_type == 0

        def read_entry(p, limit):
            found = entries.get(p)
            if found is None:
                return None
            if found[0].file_size > limit:
                return False
            return archive.read(found[0])

        check_contents(man, rep, open_audio, lambda p: read_entry(p, MAX_IMAGE_BYTES), "archive")
        check_lyrics(man, rep, lambda p: read_entry(p, MAX_LYRICS))
    return rep


def targets(arg):
    p = Path(arg)
    if p.is_dir() and (p / "collection.json").exists():
        return [("folder", p)]
    if p.is_file():
        if p.suffix.lower() == ".json":
            return [("manifest", p)]
        return [("archive", p)]
    if p.is_dir():
        out = []
        for child in sorted(p.iterdir()):
            if child.is_file() and child.suffix.lower() == ".json":
                out.append(("manifest", child))
            elif child.is_dir() and (child / "collection.json").exists():
                out.append(("folder", child))
            elif child.is_file() and child.suffix.lower() in (".etui", ".zip"):
                out.append(("archive", child))
        return out
    return [("missing", p)]


def main(argv):
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    failed = False
    for arg in argv:
        for mode, path in targets(arg):
            if mode == "missing":
                print(f"{path}: ERROR: no such file or folder")
                failed = True
                continue
            try:
                rep = {"manifest": check_manifest_file, "folder": check_folder, "archive": check_archive}[mode](path)
            except Exception as e:  # a crash is reported per collection and never hides the others
                print(f"{path}: ERROR: the check itself failed ({type(e).__name__}: {e})")
                failed = True
                continue
            scope = ""
            if mode == "manifest" and rep.lyrics_from is None:
                scope = " (manifest only: files not checked)"
            elif mode == "manifest":
                scope = f" (manifest only: audio and images not checked; lyrics read from {rep.lyrics_from}/)"
            verdict = "INVALID" if rep.errors else "VALID"
            notes = f", {len(rep.warnings)} warning{'s' if len(rep.warnings) != 1 else ''}" if rep.warnings else ""
            print(f"{path}: {verdict}{scope}{notes}")
            for e in rep.errors:
                print(f"   error   {e}")
            for w in rep.warnings:
                print(f"   warning {w}")
            failed |= bool(rep.errors)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
