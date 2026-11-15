# Etui

An open file format for collections of audio: the DJ sets of a club night, an album, an audiobook, a lecture series, a handful of favourite fragments. One `.etui` file holds the audio and everything needed to play it well: the order, titles and credits, artwork, chapters, highlights, lyrics, and the text in as many languages as its maker has.

Anyone can make one: a script, an app, an AI agent, or a person with a text editor and a ZIP tool. Any player that implements the spec can open it.

| File | What it is |
|---|---|
| [`SPEC.md`](SPEC.md) | The Etui format, version 1.0: draft 3, published for comment |
| [`MAKING-AN-ETUI.md`](MAKING-AN-ETUI.md) | A brief to give your AI agent. With the spec beside it, it is enough to make a valid file from audio you have |
| [`validate.py`](validate.py) | Checks a manifest, a collection folder or an `.etui` file. Python 3, standard library only: `python3 validate.py my.etui` |
| [`examples/`](examples) | Valid collections of every kind, and invalid ones with what makes each one invalid |

## In short

- An `.etui` file is a ZIP archive with a manifest, `collection.json`, at its root, beside the audio files and pictures it names.
- Every audio file is listed with its size and SHA-256, so a player can check it before it plays anything.
- A collection has an id and a revision: a new revision replaces the old one, and listeners keep their place and their marks.
- Media type `application/vnd.etui+zip` (not registered); Apple type identifier `io.github.aldiss.etui`.

The Etui app for iPhone, iPad and Mac reads the format; it is in private testing.

## Rights

The format describes audio; it grants no rights to it. Whoever makes or shares a collection answers for being allowed to (SPEC.md §11).

## Licence

- The specification, the brief and the other text: [Creative Commons Attribution 4.0](LICENSE-docs.md) (CC BY 4.0).
- `validate.py` and the examples: [MIT](LICENSE).

Questions and corrections are welcome as issues.
