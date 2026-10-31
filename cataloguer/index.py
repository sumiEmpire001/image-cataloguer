import hashlib
import io
import json
import math
import sqlite3
import warnings
from contextlib import contextmanager
from pathlib import Path
from PIL import Image, ImageOps, ImageStat, UnidentifiedImageError


class Conflict(ValueError):
    pass


def describe(data):
    if not isinstance(data, bytes) or not 1 <= len(data) <= 20*1024*1024:
        raise ValueError("Use image bytes up to 20 MiB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in ("PNG", "JPEG", "WEBP") or getattr(source,"n_frames",1) != 1:
                    raise ValueError("Supported formats: nonanimated PNG, JPEG, WEBP")
                if source.width*source.height > 20000000:
                    raise ValueError("Image exceeds 20 million pixels")
                format = source.format
                oriented = ImageOps.exif_transpose(source)
                rgba = oriented.convert("RGBA")
                background = Image.new("RGBA",rgba.size,"white")
                background.alpha_composite(rgba)
                rgb = background.convert("RGB")
                means = tuple(round(v,4) for v in ImageStat.Stat(rgb).mean)
                grey = rgb.convert("L").resize((9,8),Image.Resampling.LANCZOS)
                pixels = list(grey.tobytes())
                signature = sum((1 << (y*8+x)) for y in range(8) for x in range(8) if pixels[y*9+x] > pixels[y*9+x+1])
                width,height = rgb.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Image decoding failed or exceeded safety limits") from exc
    tags = ["landscape" if width>height else "portrait" if height>width else "square"]
    brightness = sum(means)/3
    tags.append("dark" if brightness<65 else "bright" if brightness>190 else "mid-tone")
    strongest = max(range(3),key=lambda i:means[i])
    tags.append(("red","green","blue")[strongest]+"-dominant" if all(means[strongest]>means[i]*1.2+10 for i in range(3) if i!=strongest) else "mixed-colour")
    return {"width":width,"height":height,"format":format,"mean_rgb":means,"dhash":f"{signature:016x}","suggested_tags":tags}


def distance(a,b):
    structural = (int(a["dhash"],16)^int(b["dhash"],16)).bit_count()/64
    colour = math.sqrt(sum((x-y)**2 for x,y in zip(a["mean_rgb"],b["mean_rgb"])))/(255*math.sqrt(3))
    aspect = min(1,abs(math.log((a["width"]/a["height"])/(b["width"]/b["height"]))))
    return .55*structural+.35*colour+.10*aspect


def label(value, maximum=80):
    if not isinstance(value,str) or not value.strip() or len(value)>maximum or "\x00" in value:
        raise ValueError("Invalid text label")
    return value.strip()


class Catalogue:
    def __init__(self,root):
        self.root=Path(root)
        if self.root.is_symlink() or (self.root/"objects").is_symlink():
            raise ValueError("Storage folders must not be symlinks")
        (self.root/"objects").mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS assets(
                id TEXT PRIMARY KEY,name TEXT NOT NULL,metadata TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tags(asset TEXT NOT NULL REFERENCES assets(id),tag TEXT NOT NULL,
                state TEXT NOT NULL,revision INTEGER NOT NULL,PRIMARY KEY(asset,tag));
                CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY,asset TEXT NOT NULL,tag TEXT NOT NULL,
                revision INTEGER NOT NULL,actor TEXT NOT NULL,reason TEXT NOT NULL,decision TEXT NOT NULL);""")

    @contextmanager
    def db(self,write=False):
        db=sqlite3.connect(self.root/"catalogue.db",timeout=10,isolation_level=None)
        db.row_factory=sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def path(self,ident):
        import re
        if not isinstance(ident,str) or not re.fullmatch(r"[0-9a-f]{64}",ident):
            raise ValueError("Invalid asset ID")
        target=self.root/"objects"/ident
        if target.is_symlink() or target.parent.is_symlink():
            raise ValueError("Unsafe object path")
        return target

    def ingest(self,file):
        file=Path(file)
        if not file.is_file() or file.stat().st_size>20*1024*1024:
            raise ValueError("Image missing or exceeds 20 MiB")
        # Bound the read even if the input changes after stat().
        with file.open("rb") as stream:
            data=stream.read(20*1024*1024+1)
        metadata=describe(data)
        ident=hashlib.sha256(data).hexdigest()
        name=label(file.name,255)
        target=self.path(ident)
        with self.db(True) as db:
            existing=db.execute("SELECT * FROM assets WHERE id=?",(ident,)).fetchone()
            if target.exists():
                if target.stat().st_size>20*1024*1024 or hashlib.sha256(target.read_bytes()).hexdigest()!=ident:
                    raise ValueError("Managed object checksum mismatch")
            else:
                # Generated checksum name; never overwrite a preexisting object.
                with target.open("xb") as stream:
                    stream.write(data)
            if existing:
                if json.loads(existing["metadata"]) != json.loads(json.dumps(metadata)):
                    raise ValueError("Stored metadata mismatch")
                return {"id":ident,"duplicate":True}
            db.execute("INSERT INTO assets VALUES(?,?,?)",(ident,name,json.dumps(metadata)))
            db.executemany("INSERT INTO tags VALUES(?,?,'proposed',0)",[(ident,tag) for tag in metadata["suggested_tags"]])
            return {"id":ident,"duplicate":False}

    def get(self,ident):
        self.path(ident)
        with self.db() as db:
            row=db.execute("SELECT * FROM assets WHERE id=?",(ident,)).fetchone()
            if row is None:
                raise KeyError(ident)
            tags=[dict(t) for t in db.execute("SELECT tag,state,revision FROM tags WHERE asset=? ORDER BY tag",(ident,))]
            return {"id":row["id"],"name":row["name"],"metadata":json.loads(row["metadata"]),"tags":tags}

    def verify(self,ident):
        self.get(ident)
        path=self.path(ident)
        if not path.is_file() or path.stat().st_size>20*1024*1024 or hashlib.sha256(path.read_bytes()).hexdigest()!=ident:
            raise ValueError("Managed image missing or checksum mismatch")
        return True

    def review(self,ident,tag,*,decision,expected_revision,actor,reason):
        tag,actor,reason=label(tag),label(actor),label(reason,500)
        if decision not in ("accepted","rejected") or type(expected_revision) is not int or expected_revision<0:
            raise ValueError("Invalid review")
        with self.db(True) as db:
            row=db.execute("SELECT * FROM tags WHERE asset=? AND tag=?",(ident,tag)).fetchone()
            if row is None:
                raise KeyError((ident,tag))
            if row["revision"]!=expected_revision:
                raise Conflict("Tag review changed")
            revision=expected_revision+1
            db.execute("UPDATE tags SET state=?,revision=? WHERE asset=? AND tag=?",(decision,revision,ident,tag))
            db.execute("INSERT INTO reviews(asset,tag,revision,actor,reason,decision) VALUES(?,?,?,?,?,?)",(ident,tag,revision,actor,reason,decision))
            return revision

    def search(self,query="",*,tag=None,limit=50,offset=0):
        if not isinstance(query,str) or len(query)>255 or type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or offset<0:
            raise ValueError("Invalid search")
        if tag is not None:
            tag=label(tag)
        with self.db() as db:
            rows=db.execute("SELECT id,name FROM assets ORDER BY id").fetchall()
            accepted={row["asset"] for row in db.execute("SELECT asset FROM tags WHERE tag=? AND state='accepted'",(tag,))} if tag else None
        return [dict(row) for row in rows if query.casefold() in row["name"].casefold() and (accepted is None or row["id"] in accepted)][offset:offset+limit]

    def similar(self,ident,*,limit=10):
        if type(limit) is not int or not 1<=limit<=100:
            raise ValueError("Use result limit1..100")
        base=self.get(ident)["metadata"]
        with self.db() as db:
            rows=db.execute("SELECT * FROM assets WHERE id!=?",(ident,)).fetchall()
        ranked=[{"id":row["id"],"name":row["name"],"distance":distance(base,json.loads(row["metadata"]))} for row in rows]
        return sorted(ranked,key=lambda row:(row["distance"],row["id"]))[:limit]

    def history(self,ident):
        self.get(ident)
        with self.db() as db:
            return [dict(row) for row in db.execute("SELECT tag,revision,actor,reason,decision FROM reviews WHERE asset=? ORDER BY id",(ident,))]
