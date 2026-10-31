import base64
import html
import io
from PIL import Image, ImageOps


def report(catalogue):
    cards=[]
    offset=0
    while True:
        page=catalogue.search(limit=100,offset=offset)
        if not page:
            break
        for row in page:
            catalogue.verify(row["id"])
            item=catalogue.get(row["id"])
            with Image.open(catalogue.path(row["id"])) as source:
                thumb=ImageOps.exif_transpose(source).convert("RGBA")
                thumb.thumbnail((320,240))
                # Recreate pixels so source EXIF and textual metadata do not enter the report.
                clean=Image.new("RGBA",thumb.size,"white")
                clean.alpha_composite(thumb)
                stream=io.BytesIO()
                clean.convert("RGB").save(stream,format="PNG")
            esc=lambda value:html.escape(str(value),quote=True)
            tags="".join("<li>"+esc(tag["tag"])+" — "+esc(tag["state"])+" (revision "+str(tag["revision"])+")</li>" for tag in item["tags"])
            cards.append('<article><img alt="Thumbnail of '+esc(item["name"])+'" src="data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode()+'"><h2>'+esc(item["name"])+'</h2><p>'+str(item["metadata"]["width"])+" × "+str(item["metadata"]["height"])+" · "+esc(item["metadata"]["format"])+'</p><ul>'+tags+'</ul><small>SHA-256 '+esc(item["id"])+'</small></article>')
        offset+=len(page)
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Local image catalogue</title><style>body{font:1rem system-ui;line-height:1.5;margin:2rem auto;padding:1rem;max-width:70rem;background:#f6f5ef;color:#1e302a}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,18rem),1fr));gap:1rem}article{padding:1rem;background:white;border:1px solid #a4b5ac;border-radius:1rem}img{max-width:100%;height:12rem;object-fit:contain;width:100%;background:#e6e9df}small{overflow-wrap:anywhere}</style><main><h1>Local image catalogue</h1><p>Suggested tags are deterministic visual heuristics. Proposed tags have not been approved. This is an offline snapshot; review tags using the CLI.</p><div class="grid">'+''.join(cards)+'</div></main></html>'
