// Unity-side GPU check: does a MaterialPropertyBlock really drive the VAT shader? HStyleRbdVatPlayer sets
// _AutoPlay and _Frame that way, and both live in the UnityPerMaterial buffer of the shader.
// Run in a URP project that holds a set-up export (Assets/.../<name>.prefab): compile this file as an editor
// script and call HStyleRbdMpbRenderCheck.Run("Assets/HStyleRbdTest/unity_vat.prefab") while the editor is open.
// It renders the prefab three times off screen: frame 30 written into a private copy of the material, frame 30
// through a property block on the untouched material, and frame 0 through the block. The first two must be the
// same picture, the third a different one. Nothing is saved; the temporary objects are destroyed again.
using UnityEditor;
using UnityEngine;

public static class HStyleRbdMpbRenderCheck
{
    public static string Run(string prefabPath)
    {
        GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
        if (prefab == null)
            return "no prefab at " + prefabPath;
        GameObject go = Object.Instantiate(prefab);
        GameObject camGo = new GameObject("HStyleRbdCheckCamera");
        go.hideFlags = camGo.hideFlags = HideFlags.HideAndDontSave;
        RenderTexture rt = new RenderTexture(256, 256, 24, RenderTextureFormat.ARGB32);
        Material copy = null;
        try
        {
            Component player = go.GetComponent("HStyleRbdVatPlayer");
            if (player != null)
                Object.DestroyImmediate(player);
            Renderer r = go.GetComponent<Renderer>();
            Material shared = r.sharedMaterial;
            go.transform.position = new Vector3(2000f, 2000f, 2000f);        // away from whatever is in the open scene
            Camera cam = camGo.AddComponent<Camera>();
            cam.targetTexture = rt;
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = Color.black;
            cam.nearClipPlane = 0.05f;
            cam.farClipPlane = 500f;
            Bounds b = r.bounds;
            cam.transform.position = b.center + new Vector3(1f, 0.6f, -1f).normalized * b.extents.magnitude * 2.2f;
            cam.transform.LookAt(b.center);

            System.Func<Color32[]> shot = () =>
            {
                cam.Render();
                RenderTexture.active = rt;
                Texture2D t = new Texture2D(256, 256, TextureFormat.RGBA32, false);
                t.ReadPixels(new Rect(0, 0, 256, 256), 0, 0);
                t.Apply();
                RenderTexture.active = null;
                Color32[] px = t.GetPixels32();
                Object.DestroyImmediate(t);
                return px;
            };
            System.Func<Color32[], Color32[], int> differing = (x, y) =>
            {
                int n = 0;
                for (int i = 0; i < x.Length; i++)
                    if (Mathf.Abs(x[i].r - y[i].r) > 2 || Mathf.Abs(x[i].g - y[i].g) > 2 || Mathf.Abs(x[i].b - y[i].b) > 2)
                        n++;
                return n;
            };
            System.Func<Color32[], int> lit = x =>
            {
                int n = 0;
                for (int i = 0; i < x.Length; i++)
                    if (x[i].r + x[i].g + x[i].b > 12)
                        n++;
                return n;
            };

            copy = new Material(shared);
            copy.SetFloat("_AutoPlay", 0f);
            copy.SetFloat("_Frame", 30f);
            r.sharedMaterial = copy;
            Color32[] viaMaterial = shot();

            r.sharedMaterial = shared;
            MaterialPropertyBlock block = new MaterialPropertyBlock();
            block.SetFloat("_AutoPlay", 0f);
            block.SetFloat("_Frame", 30f);
            r.SetPropertyBlock(block);
            Color32[] viaBlock = shot();

            block.SetFloat("_Frame", 0f);
            r.SetPropertyBlock(block);
            Color32[] firstFrame = shot();

            int same = differing(viaMaterial, viaBlock);
            int other = differing(viaBlock, firstFrame);
            bool ok = lit(viaMaterial) > 500 && same == 0 && other > 500;
            return (ok ? "ALL OK" : "FAILED") + ": object covers " + lit(viaMaterial) + " of 65536 pixels; frame 30 by material vs by block: "
                + same + " pixels differ; frame 30 vs frame 0 by block: " + other + " pixels differ; shader " + shared.shader.name
                + ", pipeline " + (UnityEngine.Rendering.GraphicsSettings.currentRenderPipeline != null
                    ? UnityEngine.Rendering.GraphicsSettings.currentRenderPipeline.GetType().Name : "built-in");
        }
        finally
        {
            Object.DestroyImmediate(go);
            Object.DestroyImmediate(camGo);
            if (copy != null)
                Object.DestroyImmediate(copy);
            rt.Release();
            Object.DestroyImmediate(rt);
        }
    }
}
