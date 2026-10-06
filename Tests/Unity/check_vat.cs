// Unity-side check of an H-Style RBD Nodes VAT export. It is a list of statements, not a class: run it with a
// tool that evaluates C# statements in the open editor.
// Needs in Assets/HStyleRbdTest/: unity_vat_mesh.fbx, unity_vat_pos.exr, unity_vat_rot.exr (data texture import
// settings, Read/Write on) and truth.txt (made from Tests/Out/Unity/truth.json).
// It decodes sample vertices exactly like HStyleRbdVAT.hlsl and compares them with where Blender says they are.
var inv = System.Globalization.CultureInfo.InvariantCulture;
var txt = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.TextAsset>("Assets/HStyleRbdTest/truth.txt").text.Split('\n');
var head = txt[0].Trim().Split(' ');
int W = int.Parse(head[0]), pivotRow = int.Parse(head[3]), uvIndex = int.Parse(head[5]);
var frames = System.Array.ConvertAll(txt[1].Trim().Split(' '), int.Parse);
var posTex = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.Texture2D>("Assets/HStyleRbdTest/unity_vat_pos.exr");
var rotTex = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.Texture2D>("Assets/HStyleRbdTest/unity_vat_rot.exr");
var go = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.GameObject>("Assets/HStyleRbdTest/unity_vat_mesh.fbx");
var mesh = go.GetComponentInChildren<UnityEngine.MeshFilter>().sharedMesh;
var verts = mesh.vertices;
var uvs = new System.Collections.Generic.List<UnityEngine.Vector2>(); mesh.GetUVs(uvIndex, uvs);
// Blender (x, y, z) -> Unity (-x, z, -y): the mapping the exporter claims
System.Func<double, double, double, UnityEngine.Vector3> C = (x, y, z) => new UnityEngine.Vector3((float)-x, (float)z, (float)-y);
int samples = 0, noMatch = 0; var maxErr = new float[frames.Length];
for (int i = 2; i < txt.Length; i++)
{
    var parts = txt[i].Trim().Split(' ');
    if (parts.Length < 4) continue;
    var v = System.Array.ConvertAll(parts, s => double.Parse(s, inv));
    var rest = C(v[0], v[1], v[2]); int piece = (int)v[3];
    // neighbouring pieces share positions on their cut faces: take the vertex at this spot that belongs to this piece
    int best = -1;
    for (int j = 0; j < verts.Length; j++)
        if ((verts[j] - rest).sqrMagnitude < 1e-8f && UnityEngine.Mathf.FloorToInt(uvs[j].x * W) == piece) { best = j; break; }
    samples++;
    if (best < 0) { noMatch++; continue; }
    var pivotC = posTex.GetPixel(piece, pivotRow); var pivot = new UnityEngine.Vector3(pivotC.r, pivotC.g, pivotC.b);
    for (int k = 0; k < frames.Length; k++)
    {
        var pc = posTex.GetPixel(piece, frames[k]); var rc = rotTex.GetPixel(piece, frames[k]);
        var qv = new UnityEngine.Vector3(rc.r, rc.g, rc.b);
        var rel = verts[best] - pivot;
        var t = 2f * UnityEngine.Vector3.Cross(qv, rel);
        var dec = new UnityEngine.Vector3(pc.r, pc.g, pc.b) + rel + rc.a * t + UnityEngine.Vector3.Cross(qv, t);
        var want = C(v[4 + 3 * k], v[5 + 3 * k], v[6 + 3 * k]);
        maxErr[k] = UnityEngine.Mathf.Max(maxErr[k], (dec - want).magnitude);
    }
}
return "samples=" + samples + " noVertexForOwnPiece=" + noMatch + " meshBounds=" + mesh.bounds.min.ToString("F3") + ".." + mesh.bounds.max.ToString("F3")
    + " decodeMaxErr_m@frames[" + string.Join(",", frames) + "]=" + string.Join(", ", System.Array.ConvertAll(maxErr, e => e.ToString("F5")));
