import argparse
import json
from pathlib import Path
from .index import Catalogue
from .report import report


def main():
    parser=argparse.ArgumentParser(description="Trusted local image catalogue")
    parser.add_argument("root",type=Path)
    sub=parser.add_subparsers(dest="command",required=True)
    ingest=sub.add_parser("ingest");ingest.add_argument("files",nargs="+",type=Path)
    listing=sub.add_parser("list");listing.add_argument("--query",default="");listing.add_argument("--tag");listing.add_argument("--offset",type=int,default=0)
    for name in ("show","verify","similar"):
        item=sub.add_parser(name);item.add_argument("id")
    review=sub.add_parser("review");review.add_argument("id");review.add_argument("tag");review.add_argument("--decision",choices=["accepted","rejected"],required=True);review.add_argument("--revision",type=int,required=True);review.add_argument("--actor",required=True);review.add_argument("--reason",required=True)
    export=sub.add_parser("report");export.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    try:
        catalogue=Catalogue(args.root)
        if args.command=="ingest":
            value=[catalogue.ingest(file) for file in args.files]
        elif args.command=="list":
            value=catalogue.search(args.query,tag=args.tag,offset=args.offset)
        elif args.command=="show":
            value=catalogue.get(args.id)
        elif args.command=="verify":
            value={"verified":catalogue.verify(args.id)}
        elif args.command=="similar":
            value=catalogue.similar(args.id)
        elif args.command=="review":
            value={"revision":catalogue.review(args.id,args.tag,decision=args.decision,expected_revision=args.revision,actor=args.actor,reason=args.reason)}
        else:
            args.output.write_text(report(catalogue),encoding="utf-8")
            value={"report":str(args.output)}
        print(json.dumps(value,ensure_ascii=False,indent=2))
    except (ValueError,KeyError,OSError) as exc:
        parser.error(str(exc))


if __name__=="__main__":
    main()
