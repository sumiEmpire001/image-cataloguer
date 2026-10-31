import hashlib
import base64
import io
import json
import re
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PIL import Image, PngImagePlugin
from cataloguer import Catalogue, Conflict
from cataloguer.index import describe
from cataloguer.report import report


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.catalogue=Catalogue(self.root/"catalogue")

    def fixture(self,name="red.png",colour=(220,30,30),size=(80,60),format="PNG"):
        path=self.root/name
        Image.new("RGB",size,colour).save(path,format=format)
        return path

    def test_metadata_and_exact_duplicate_bytes(self):
        file=self.fixture()
        first=self.catalogue.ingest(file)
        duplicate=self.root/"renamed.png";duplicate.write_bytes(file.read_bytes())
        second=self.catalogue.ingest(duplicate)
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["id"],second["id"])
        self.assertEqual(len(self.catalogue.search()),1)
        self.assertEqual(self.catalogue.get(first["id"])["metadata"]["width"],80)

    def test_synthetic_retrieval_relevance(self):
        red=self.catalogue.ingest(self.fixture())["id"]
        near=self.catalogue.ingest(self.fixture("near.png",(210,35,35)))["id"]
        blue=self.catalogue.ingest(self.fixture("blue.png",(30,30,220)))["id"]
        results=self.catalogue.similar(red)
        self.assertEqual(results[0]["id"],near)
        self.assertEqual(results[1]["id"],blue)
        self.assertLess(results[0]["distance"],results[1]["distance"])
        self.assertTrue(all(0<=row["distance"]<=1 for row in results))

    def test_proposals_not_searchable_until_human_accepts(self):
        ident=self.catalogue.ingest(self.fixture())["id"]
        self.assertEqual(self.catalogue.search(tag="red-dominant"),[])
        self.catalogue.review(ident,"red-dominant",decision="accepted",expected_revision=0,actor="reviewer",reason="Synthetic review")
        self.assertEqual(self.catalogue.search(tag="red-dominant")[0]["id"],ident)
        self.catalogue.review(ident,"red-dominant",decision="rejected",expected_revision=1,actor="reviewer",reason="Reconsidered")
        self.assertEqual(self.catalogue.search(tag="red-dominant"),[])
        self.assertEqual(len(self.catalogue.history(ident)),2)

    def test_concurrent_review_revision(self):
        ident=self.catalogue.ingest(self.fixture())["id"]
        def attempt(_):
            try:
                self.catalogue.review(ident,"red-dominant",decision="accepted",expected_revision=0,actor="reviewer",reason="Test")
                return True
            except Conflict:
                return False
        with ThreadPoolExecutor(max_workers=6) as pool:
            self.assertEqual(sum(pool.map(attempt,range(12))),1)

    def test_unsupported_corrupt_and_animated_images(self):
        bad=self.root/"bad.png";bad.write_bytes(b"not an image")
        gif=self.fixture("image.gif",format="GIF")
        animated=self.root/"animated.png"
        Image.new("RGB",(10,10),"red").save(animated,save_all=True,append_images=[Image.new("RGB",(10,10),"blue")],duration=100)
        for file in (bad,gif,animated,self.root/"absent.png"):
            with self.assertRaises(ValueError):
                self.catalogue.ingest(file)
        self.assertEqual(self.catalogue.search(),[])

    def test_restart_and_managed_copy_survives_source_removal(self):
        source=self.fixture()
        ident=self.catalogue.ingest(source)["id"]
        source.unlink()
        restored=Catalogue(self.root/"catalogue")
        self.assertTrue(restored.verify(ident))
        self.assertEqual(restored.get(ident)["name"],"red.png")

    def test_blob_tampering_and_symlink_paths_rejected(self):
        file=self.fixture()
        ident=self.catalogue.ingest(file)["id"]
        target=self.catalogue.path(ident)
        target.write_bytes(b"damaged")
        with self.assertRaises(ValueError):
            self.catalogue.verify(ident)
        with self.assertRaises(ValueError):
            self.catalogue.ingest(file)
        target.unlink();target.symlink_to(file)
        with self.assertRaises(ValueError):
            self.catalogue.verify(ident)
        with self.assertRaises(ValueError):
            self.catalogue.path("../escape")

    def test_orphan_object_reingestion_recovers_metadata(self):
        file=self.fixture()
        data=file.read_bytes();ident=hashlib.sha256(data).hexdigest()
        self.catalogue.path(ident).write_bytes(data)
        self.assertFalse(self.catalogue.ingest(file)["duplicate"])
        self.assertTrue(self.catalogue.verify(ident))

    def test_distinct_bytes_with_same_pixels_are_near_not_exact_duplicates(self):
        first=self.fixture()
        other=self.root/"metadata.png"
        metadata=PngImagePlugin.PngInfo();metadata.add_text("synthetic-secret","not-for-report")
        with Image.open(first) as image:
            image.save(other,pnginfo=metadata)
        a=self.catalogue.ingest(first);b=self.catalogue.ingest(other)
        self.assertNotEqual(a["id"],b["id"])
        self.assertEqual(self.catalogue.similar(a["id"])[0]["distance"],0)
        for encoded in re.findall(r'data:image/png;base64,([^\"]+)',report(self.catalogue)):
            with Image.open(io.BytesIO(base64.b64decode(encoded))) as thumbnail:
                self.assertNotIn("synthetic-secret",thumbnail.info)

    def test_pixel_limit_rejected_before_decode(self):
        data=bytearray(self.fixture().read_bytes())
        # Change the valid PNG IHDR dimensions; the pixel guard must run before decoding.
        data[16:24]=struct.pack(">II",5000,4001)
        data[29:33]=struct.pack(">I",zlib.crc32(data[12:29]))
        with self.assertRaisesRegex(ValueError,"20 million"):
            describe(bytes(data))

    def test_transparency_orientation_and_formats(self):
        transparent=self.root/"alpha.png";Image.new("RGBA",(10,10),(255,0,0,0)).save(transparent)
        self.assertEqual(describe(transparent.read_bytes())["mean_rgb"],(255,255,255))
        file=self.root/"rotated.jpg"
        image=Image.new("RGB",(20,10),"red");exif=Image.Exif();exif[274]=6;image.save(file,exif=exif)
        metadata=describe(file.read_bytes())
        self.assertEqual((metadata["width"],metadata["height"]),(10,20))
        self.assertEqual(describe(self.fixture("image.webp",format="WEBP").read_bytes())["format"],"WEBP")

    def test_search_literal_unicode_pagination_and_limits(self):
        self.catalogue.ingest(self.fixture("Café.png"))
        self.catalogue.ingest(self.fixture("blue.png",(0,0,255)))
        self.assertEqual(len(self.catalogue.search("CAFÉ")),1)
        self.assertEqual(self.catalogue.search("%"),[])
        self.assertNotEqual(self.catalogue.search(limit=1)[0]["id"],self.catalogue.search(limit=1,offset=1)[0]["id"])
        with self.assertRaises(ValueError):
            self.catalogue.search(limit=True)
        with self.assertRaises(ValueError):
            self.catalogue.similar("0"*64,limit=0)
        with self.assertRaises(ValueError):
            describe(b"x"*(20*1024*1024+1))

    def test_cli_and_html_report(self):
        file=self.fixture()
        result=subprocess.run([sys.executable,"-m","cataloguer",str(self.root/"catalogue"),"ingest",str(file)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        ident=json.loads(result.stdout)[0]["id"]
        self.assertTrue(self.catalogue.verify(ident))
        page=report(self.catalogue)
        self.assertIn("data:image/png;base64,",page)
        self.assertIn("proposed",page)
        self.assertNotIn(str(self.root),page)


if __name__=="__main__":
    unittest.main()
