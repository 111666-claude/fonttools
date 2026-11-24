"""Bit-level coordinate snapshot of real test fonts after full instancing."""
import json
import os
import sys

sys.path.insert(0, "/home/real666/feedback/uid41/Lib")

from fontTools import ttLib
from fontTools.varLib import instancer

TESTDATA = "/home/real666/feedback/uid41/Tests/varLib/instancer/data"


def snap(ttx, pins):
    f = ttLib.TTFont()
    f.importXML(os.path.join(TESTDATA, ttx))
    instancer.instantiateVariableFont(f, pins)
    g = f["glyf"]
    out = {}
    for name in g.glyphOrder:
        gl = g[name]
        if gl.numberOfContours == 0:
            continue
        c, _ = g._getCoordinatesAndControls(
            name, f["hmtx"].metrics, getattr(f.get("vmtx"), "metrics", None)
        )
        out[name] = [tuple(p) for p in c]
    return out


payload = {
    "a": snap("PartialInstancerTest-VF.ttx", {"wght": 0.3, "wdth": -0.7}),
    "b": snap("PartialInstancerTest2-VF.ttx", {"wght": 0.625, "wdth": 0.25}),
}
with open(sys.argv[1], "w") as f:
    json.dump(payload, f, sort_keys=True)
print("wrote", sys.argv[1])
