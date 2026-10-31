# Image Cataloguer

Local image indexing, byte-exact duplicates, deterministic visual similarity and reviewable tag suggestions. Python 3.10+ with Pillow12.3.0 (the locally tested version).

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
python demo.py --html report.html
```

Open report.html for the synthetic contact sheet. GitHub Actions uploads image-catalogue-python-* artifacts; download, extract and open report.html. The sample generates three simple colour/shape fixtures rather than downloading photographs. No image model or external service is called.

## Use your local files

```sh
python -m cataloguer ./my-catalogue ingest sample.png another.jpg
python -m cataloguer ./my-catalogue list
python -m cataloguer ./my-catalogue show ASSET_SHA256
python -m cataloguer ./my-catalogue similar ASSET_SHA256
python -m cataloguer ./my-catalogue verify ASSET_SHA256
python -m cataloguer ./my-catalogue review ASSET_SHA256 red-dominant --decision accepted --revision 0 --actor local-reviewer --reason "Confirmed manually"
python -m cataloguer ./my-catalogue list --tag red-dominant
python -m cataloguer ./my-catalogue report --output contact-sheet.html
```

Replace ASSET_SHA256 with the ingest result. Inputs remain untouched; managed copies are stored under generated SHA-256 names, with SQLite metadata. Duplicate bytes return the existing asset even under another filename; the first name is retained. Matching pixels encoded differently remain separate assets, potentially at zero similarity distance. Reingesting a valid orphan object restores its metadata after an interrupted metadata commit.

The index reads PNG/JPEG/WEBP single-frame images, applies EXIF orientation for analysis, composites transparency onto white, and records dimensions, format, mean RGB and64-bit difference hash. Similarity distance combines55% structural hash distance,35% mean-colour distance and10% aspect-ratio distance; lower is closer. This is a small image-processing baseline, not semantic search, face recognition or AI-generated object labels. The fixture evaluation checks that a near-red sample ranks ahead of a blue sample; real-photo relevance is not established.

Suggested tags describe orientation, brightness and dominant colour. They start as proposed. Tag search includes accepted tags only, and expected revisions prevent stale/concurrent reviews. Accept/reject decisions record actor/reason history. Actor names are caller supplied and are not authenticated identities. Reports show the exact proposal/review states; they are static snapshots, and review commands run through the CLI.

13 tests cover exact/near duplicates, synthetic retrieval ranking, unsupported/corrupt/animated files, pixel/byte caps, EXIF orientation, transparency, reviewed-tag filtering, concurrent reviews, restart, orphan recovery, object corruption, literal Unicode search, CLI operation and report metadata stripping. CI runs Python3.10/3.12/3.13, installs the pinned dependency, tests and builds the synthetic contact sheet. Actions → Tests and demo → Run workflow repeats it.

Limits:20MiB per file,20million pixels, trusted local storage/input files. No recursive filesystem watcher, hosted UI, authentication, encryption, original-file deletion or scalable vector index. Search/similarity scan the local collection. Symlink checks are not protection against a hostile process replacing filesystem paths concurrently. File writes and SQLite commits are separate; reingestion recovers valid orphan objects but power-loss durability is not guaranteed. Original managed copies retain source metadata, possibly EXIF location; offline reports re-encode thumbnails without source EXIF/text metadata but retain filenames and the visible image. Review sharing/privacy before exporting your own photos. Metadata search does not automatically verify every blob; use verify or report generation for checksum verification. Back up the database and objects together.
