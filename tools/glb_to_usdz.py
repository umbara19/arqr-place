"""
Konversi GLB beranimasi (hasil tools/bake.html) → USDZ untuk AR Quick Look di iPhone.

Mendukung: hierarki node (TRS), mesh segitiga (posisi, normal, UV), material PBR
(warna, metallic, roughness, emissive, transparansi, tekstur PNG) dan animasi
translation/rotation/scale (keyframe linear) sebagai timeSamples USD.

Pakai: python tools/glb_to_usdz.py            (semua models/*.glb)
       python tools/glb_to_usdz.py file.glb   (satu file)
Butuh: pip install usd-core numpy
"""
import glob
import json
import os
import re
import shutil
import struct
import sys
import tempfile

import numpy as np
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdUtils, Vt

FPS = 30
HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(os.path.dirname(HERE), "models")

COMPONENT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


class Glb:
    def __init__(self, path):
        data = open(path, "rb").read()
        magic, _, _ = struct.unpack_from("<III", data, 0)
        assert magic == 0x46546C67, "bukan file GLB"
        offset, self.json, self.bin = 12, None, b""
        while offset < len(data):
            length, kind = struct.unpack_from("<II", data, offset)
            chunk = data[offset + 8: offset + 8 + length]
            if kind == 0x4E4F534A:
                self.json = json.loads(chunk)
            elif kind == 0x004E4942:
                self.bin = chunk
            offset += 8 + length
        self.j = self.json

    def view_bytes(self, index):
        v = self.j["bufferViews"][index]
        start = v.get("byteOffset", 0)
        return self.bin[start:start + v["byteLength"]], v.get("byteStride")

    def accessor(self, index):
        a = self.j["accessors"][index]
        dtype = np.dtype(COMPONENT[a["componentType"]])
        width = WIDTH[a["type"]]
        raw, stride = self.view_bytes(a["bufferView"])
        offset = a.get("byteOffset", 0)
        count = a["count"]
        item = dtype.itemsize * width
        if stride and stride != item:
            rows = [np.frombuffer(raw, dtype, width, offset + i * stride) for i in range(count)]
            arr = np.array(rows)
        else:
            arr = np.frombuffer(raw, dtype, count * width, offset).reshape(count, width) if width > 1 \
                else np.frombuffer(raw, dtype, count, offset)
        if a.get("normalized") and dtype.kind in "iu":
            arr = arr.astype(np.float32) / np.iinfo(dtype).max
        return arr


def safe(name, used):
    base = re.sub(r"[^A-Za-z0-9_]", "_", name or "node") or "node"
    if base[0].isdigit():
        base = "_" + base
    out, n = base, 1
    while out in used:
        n += 1
        out = f"{base}_{n}"
    used.add(out)
    return out


class Converter:
    def __init__(self, glb_path, usdz_path):
        self.g = Glb(glb_path)
        self.usdz_path = usdz_path
        self.tmp = tempfile.mkdtemp(prefix="glb2usdz_")
        self.usd_path = os.path.join(self.tmp, "model.usdc")
        self.stage = Usd.Stage.CreateNew(self.usd_path)
        UsdGeom.SetStageUpAxis(self.stage, UsdGeom.Tokens.y)
        UsdGeom.SetStageMetersPerUnit(self.stage, 1.0)
        self.materials = {}
        self.textures = {}
        self.node_ops = {}

    # ------------------------------------------------------------ materials

    def texture_file(self, tex_index):
        if tex_index in self.textures:
            return self.textures[tex_index]
        tex = self.g.j["textures"][tex_index]
        img = self.g.j["images"][tex["source"]]
        data, _ = self.g.view_bytes(img["bufferView"])
        os.makedirs(os.path.join(self.tmp, "textures"), exist_ok=True)
        rel = f"textures/tex{tex_index}.png"
        with open(os.path.join(self.tmp, rel), "wb") as f:
            f.write(data)
        self.textures[tex_index] = rel
        return rel

    def material(self, index):
        if index in self.materials:
            return self.materials[index]
        m = self.g.j["materials"][index]
        used = getattr(self, "_mat_names", set())
        self._mat_names = used
        path = f"/Root/Materials/{safe(m.get('name', 'Material'), used)}"
        mat = UsdShade.Material.Define(self.stage, path)
        pbr = UsdShade.Shader.Define(self.stage, path + "/PBR")
        pbr.CreateIdAttr("UsdPreviewSurface")
        mat.CreateSurfaceOutput().ConnectToSource(pbr.ConnectableAPI(), "surface")

        p = m.get("pbrMetallicRoughness", {})
        color = p.get("baseColorFactor", [1, 1, 1, 1])
        unlit = "KHR_materials_unlit" in m.get("extensions", {})
        blend = m.get("alphaMode") == "BLEND"
        pbr.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0 if unlit else float(p.get("metallicFactor", 1.0)))
        pbr.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(1.0 if unlit else float(p.get("roughnessFactor", 1.0)))
        emissive = list(m.get("emissiveFactor", [0, 0, 0]))
        strength = m.get("extensions", {}).get("KHR_materials_emissive_strength", {}).get("emissiveStrength", 1.0)
        pbr.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*[min(1.0, c * strength) for c in emissive]))

        tex = p.get("baseColorTexture")
        if tex is not None:
            reader = UsdShade.Shader.Define(self.stage, path + "/stReader")
            reader.CreateIdAttr("UsdPrimvarReader_float2")
            reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
            t = UsdShade.Shader.Define(self.stage, path + "/BaseColorTex")
            t.CreateIdAttr("UsdUVTexture")
            t.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(self.texture_file(tex["index"]))
            t.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(reader.ConnectableAPI(), "result")
            t.CreateInput("wrapS", Sdf.ValueTypeNames.Token).Set("repeat")
            t.CreateInput("wrapT", Sdf.ValueTypeNames.Token).Set("repeat")
            t.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set("sRGB")
            t.CreateInput("scale", Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(*map(float, color)))
            rgb = t.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)
            pbr.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(rgb)
            if blend:
                a = t.CreateOutput("a", Sdf.ValueTypeNames.Float)
                pbr.CreateInput("opacity", Sdf.ValueTypeNames.Float).ConnectToSource(a)
        else:
            pbr.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*map(float, color[:3])))
            pbr.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(float(color[3]) if blend else 1.0)

        self.materials[index] = mat
        return mat

    # ------------------------------------------------------------ geometry

    def mesh(self, parent_path, mesh_index):
        mesh = self.g.j["meshes"][mesh_index]
        used = set()
        for k, prim in enumerate(mesh["primitives"]):
            if prim.get("mode", 4) != 4:
                continue
            attrs = prim["attributes"]
            pts = self.g.accessor(attrs["POSITION"]).astype(np.float32)
            idx = self.g.accessor(prim["indices"]).astype(np.int32) if "indices" in prim else np.arange(len(pts), dtype=np.int32)
            path = f"{parent_path}/{safe('Geom' if k == 0 else f'Geom{k}', used)}"
            m = UsdGeom.Mesh.Define(self.stage, path)
            m.CreateSubdivisionSchemeAttr("none")
            m.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(pts))
            m.CreateFaceVertexCountsAttr(Vt.IntArray([3] * (len(idx) // 3)))
            m.CreateFaceVertexIndicesAttr(Vt.IntArray.FromNumpy(idx))
            m.CreateExtentAttr(Vt.Vec3fArray([Gf.Vec3f(*map(float, pts.min(0))), Gf.Vec3f(*map(float, pts.max(0)))]))
            if "NORMAL" in attrs:
                m.CreateNormalsAttr(Vt.Vec3fArray.FromNumpy(self.g.accessor(attrs["NORMAL"]).astype(np.float32)))
                m.SetNormalsInterpolation(UsdGeom.Tokens.vertex)
            if "TEXCOORD_0" in attrs:
                uv = self.g.accessor(attrs["TEXCOORD_0"]).astype(np.float32).copy()
                uv[:, 1] = 1.0 - uv[:, 1]  # glTF: origin kiri-atas, USD: kiri-bawah
                st = UsdGeom.PrimvarsAPI(m).CreatePrimvar("st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.vertex)
                st.Set(Vt.Vec2fArray.FromNumpy(uv))
            if "material" in prim:
                UsdShade.MaterialBindingAPI.Apply(m.GetPrim()).Bind(self.material(prim["material"]))

    # ------------------------------------------------------------ nodes

    def node(self, index, parent_path, used):
        n = self.g.j["nodes"][index]
        path = f"{parent_path}/{safe(n.get('name'), used)}"
        x = UsdGeom.Xform.Define(self.stage, path)
        if "matrix" in n:
            m = np.array(n["matrix"], dtype=np.float64).reshape(4, 4)  # kolom-mayor glTF = baris-mayor USD
            x.AddTransformOp().Set(Gf.Matrix4d(m.tolist()))
            ops = None
        else:
            t = n.get("translation", [0, 0, 0])
            r = n.get("rotation", [0, 0, 0, 1])
            s = n.get("scale", [1, 1, 1])
            ops = {
                "translation": x.AddTranslateOp(),
                "rotation": x.AddOrientOp(),
                "scale": x.AddScaleOp(),
            }
            ops["translation"].Set(Gf.Vec3d(*t))
            ops["rotation"].Set(Gf.Quatf(r[3], r[0], r[1], r[2]))
            ops["scale"].Set(Gf.Vec3f(*s))
        self.node_ops[index] = ops
        if "mesh" in n:
            self.mesh(path, n["mesh"])
        child_names = set()
        for c in n.get("children", []):
            self.node(c, path, child_names)

    def animations(self):
        end = 0
        for anim in self.g.j.get("animations", [])[:1]:
            for ch in anim["channels"]:
                target = ch["target"]
                ops = self.node_ops.get(target.get("node"))
                if not ops or target["path"] not in ops:
                    continue
                sampler = anim["samplers"][ch["sampler"]]
                times = self.g.accessor(sampler["input"])
                values = self.g.accessor(sampler["output"])
                op = ops[target["path"]]
                for t, v in zip(times, values):
                    code = round(float(t) * FPS)
                    end = max(end, code)
                    if target["path"] == "translation":
                        op.Set(Gf.Vec3d(*map(float, v)), code)
                    elif target["path"] == "rotation":
                        op.Set(Gf.Quatf(float(v[3]), float(v[0]), float(v[1]), float(v[2])), code)
                    else:
                        op.Set(Gf.Vec3f(*map(float, v)), code)
        if end:
            self.stage.SetStartTimeCode(0)
            self.stage.SetEndTimeCode(end)
            self.stage.SetTimeCodesPerSecond(FPS)
            self.stage.SetFramesPerSecond(FPS)

    def run(self):
        root = UsdGeom.Xform.Define(self.stage, "/Root")
        self.stage.SetDefaultPrim(root.GetPrim())
        used = set()
        scene = self.g.j["scenes"][self.g.j.get("scene", 0)]
        for n in scene["nodes"]:
            self.node(n, "/Root", used)
        self.animations()
        self.stage.GetRootLayer().Save()
        if os.path.exists(self.usdz_path):
            os.remove(self.usdz_path)
        ok = UsdUtils.CreateNewARKitUsdzPackage(self.usd_path, self.usdz_path)
        shutil.rmtree(self.tmp, ignore_errors=True)
        if not ok:
            raise RuntimeError("gagal membuat USDZ")


def main():
    files = sys.argv[1:] or sorted(glob.glob(os.path.join(MODELS, "*.glb")))
    for f in files:
        out = os.path.splitext(f)[0] + ".usdz"
        Converter(f, out).run()
        print(f"ok {os.path.basename(out)} {os.path.getsize(out) // 1024} KB")


if __name__ == "__main__":
    main()
