import zipfile, re, sys, glob

path = r"d:\cxdownload\移动机器人技术01.pptx"
z = zipfile.ZipFile(path)
names = [n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)]
names.sort(key=lambda n: int(re.search(r"(\d+)", n.split("/")[-1]).group(1)))

for n in names:
    xml = z.read(n).decode("utf-8", errors="ignore")
    texts = re.findall(r"<a:t>(.*?)</a:t>", xml, re.S)
    print("=" * 60)
    print("SLIDE:", n)
    print("=" * 60)
    for t in texts:
        t = t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#10;", "\n")
        print(t)
    print()