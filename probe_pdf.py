import sys
out = []
try:
    import pymupdf as fitz
    out.append("pymupdf OK")
except Exception as e:
    out.append("pymupdf FAILED: " + repr(e))
    open(r"C:\Users\alexr\Driverless_AGI\probe_pdf_out.txt", "w").write("\n".join(out))
    sys.exit(0)

path = r"C:\Users\alexr\Driverless_AGI\PublicWaterMassMailing.pdf"
doc = fitz.open(path)
out.append("page count: " + str(len(doc)))
total_first3 = 0
for i in range(min(len(doc), 6)):
    t = doc[i].get_text()
    total_first3 += len(t) if i < 3 else 0
    out.append(f"PAGE {i+1} chars={len(t)} :: " + repr(t[:140]))
doc.close()
out.append("first3 total chars (scanned threshold=50): " + str(total_first3))
out.append("CLASSIFIED SCANNED by wrapper: " + str(total_first3 < 50))
open(r"C:\Users\alexr\Driverless_AGI\probe_pdf_out.txt", "w").write("\n".join(out) + "\n")
