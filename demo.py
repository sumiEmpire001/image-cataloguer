import argparse
import json
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw
from cataloguer import Catalogue
from cataloguer.report import report

parser=argparse.ArgumentParser(description="Synthetic image fixtures only")
parser.add_argument("--html",type=Path)
args=parser.parse_args()
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder)
    catalogue=Catalogue(root/"catalogue")
    for name,colour in [("red-sample.png",(220,40,40)),("near-red-sample.png",(210,45,45)),("blue-sample.png",(40,40,220))]:
        image=Image.new("RGB",(180,120),colour)
        ImageDraw.Draw(image).rectangle((20,20,80,80),outline="white",width=4)
        image.save(root/name)
        result=catalogue.ingest(root/name)
        if name=="red-sample.png":
            first=result["id"]
    catalogue.review(first,"red-dominant",decision="accepted",expected_revision=0,actor="demo-reviewer",reason="Confirmed on a synthetic colour fixture")
    print("Synthetic colour/shape examples; no photographs or model service used")
    print(json.dumps(catalogue.similar(first),indent=2))
    print(json.dumps(catalogue.search(tag="red-dominant"),indent=2))
    if args.html:
        args.html.write_text(report(catalogue),encoding="utf-8")
        print("Offline contact sheet:",args.html)
