// SPDX-License-Identifier: CC0-1.0  (public domain: copy it into any project, including commercial games)
// H-Style RBD Nodes: one-click set-up of a VAT export in Unity (URP).
//
// Put the exported files (with their HStyleRbdUnity folder) under Assets. Select the exported .json, then
//   Assets > H-Style RBD Nodes > Set Up VAT From Json
// Keep ONE copy of this script per project: a second copy is a duplicate class and stops compilation.
// It fixes the import settings of the two data textures, creates <name>.mat with the right numbers and
// <name>.prefab ready to drop into a scene (with an HStyleRbdVatPlayer on it when that script is in the
// project). For a bone FBX export, select the .fbx and run
//   Assets > H-Style RBD Nodes > Fix Bone FBX Import
// which turns animation compression off (the default keyframe reduction is visibly off on tumbling pieces).
#if UNITY_EDITOR
using System.IO;
using UnityEditor;
using UnityEngine;

public static class HStyleRbdVatSetup
{
    const string ShaderName = "H-Style RBD Nodes/VAT Simple (URP)";

    // only the flat fields of the .json that this script needs
    [System.Serializable]
    class Meta
    {
        public string schema = "";
        public string position_file = "", rotation_file = "", mesh_file = "";
        public int width = 0, height = 0, piece_count = 0, frame_count = 0, pivot_row = 0, lookup_uv_index = 1;
        public float fps = 24f;
    }

    [MenuItem("Assets/H-Style RBD Nodes/Set Up VAT From Json", true)]
    static bool CanSetUp()
    {
        return Selection.activeObject is TextAsset && AssetDatabase.GetAssetPath(Selection.activeObject).EndsWith(".json");
    }

    [MenuItem("Assets/H-Style RBD Nodes/Set Up VAT From Json")]
    static void SetUpSelected()
    {
        string prefab = SetUp(AssetDatabase.GetAssetPath(Selection.activeObject));
        if (prefab != null)
            EditorGUIUtility.PingObject(AssetDatabase.LoadAssetAtPath<GameObject>(prefab));
    }

    /// <summary>Returns the path of the prefab, or null (with an error in the Console) when something is missing.
    /// Nothing is changed unless every input is present. An existing prefab is left alone, and on an existing
    /// material only the VAT properties are updated.</summary>
    public static string SetUp(string jsonPath)
    {
        Meta meta = JsonUtility.FromJson<Meta>(File.ReadAllText(jsonPath));
        if (meta == null || meta.schema != "hrbd_vat_1")
        {
            Debug.LogError("H-Style RBD Nodes: " + jsonPath + " is not an hrbd_vat_1 export.");
            return null;
        }
        string dir = Path.GetDirectoryName(jsonPath).Replace('\\', '/');
        string name = Path.GetFileNameWithoutExtension(jsonPath);
        string posPath = dir + "/" + meta.position_file, rotPath = dir + "/" + meta.rotation_file;

        // 1. check everything before touching anything
        GameObject model = AssetDatabase.LoadAssetAtPath<GameObject>(dir + "/" + meta.mesh_file);
        Shader shader = Shader.Find(ShaderName);
        bool hasPos = AssetImporter.GetAtPath(posPath) is TextureImporter;
        bool hasRot = AssetImporter.GetAtPath(rotPath) is TextureImporter;
        MeshFilter filter = model != null ? model.GetComponentInChildren<MeshFilter>() : null;
        if (!hasPos || !hasRot || filter == null || filter.sharedMesh == null || shader == null)
        {
            Debug.LogError("H-Style RBD Nodes: cannot set up " + jsonPath + ". Missing: "
                + (hasPos ? "" : meta.position_file + " ") + (hasRot ? "" : meta.rotation_file + " ")
                + (filter == null || filter.sharedMesh == null ? meta.mesh_file + " " : "")
                + (shader == null ? "the shader '" + ShaderName + "' (HStyleRbdVAT_URP.shader + HStyleRbdVAT.hlsl; it needs the Universal Render Pipeline)" : ""));
            return null;
        }
        if (ShaderUtil.ShaderHasError(shader))
        {
            Debug.LogError("H-Style RBD Nodes: the shader '" + ShaderName + "' does not compile in this project (see its Inspector). Nothing was changed.");
            return null;
        }
        if (meta.lookup_uv_index != 1)
        {
            Debug.LogError("H-Style RBD Nodes: this export keeps its lookup UV in channel " + meta.lookup_uv_index
                + ", the bundled shader reads TEXCOORD1. Change the semantic of uvLookup in HStyleRbdVAT_URP.shader to TEXCOORD"
                + meta.lookup_uv_index + " (or export from a mesh with a single UV map). Nothing was changed.");
            return null;
        }

        // 2. textures
        Texture2D pos = DataTexture(posPath);
        Texture2D rot = DataTexture(rotPath);
        if (pos.width != meta.width || pos.height != meta.height || rot.width != meta.width || rot.height != meta.height)
        {
            Debug.LogError("H-Style RBD Nodes: the textures were imported as " + pos.width + "x" + pos.height + " but the export is "
                + meta.width + "x" + meta.height + ". Check Max Size and platform overrides in their import settings.");
            return null;
        }

        // 3. material: create it, or update only the VAT properties of an existing one
        string matPath = dir + "/" + name + ".mat";
        Material mat = AssetDatabase.LoadAssetAtPath<Material>(matPath);
        if (mat == null)
        {
            mat = new Material(shader);
            AssetDatabase.CreateAsset(mat, matPath);
        }
        else if (mat.shader != shader)
        {
            Debug.LogWarning("H-Style RBD Nodes: " + matPath + " uses another shader (" + mat.shader.name + "). It is left as it is; only properties that exist on it are set.");
        }
        if (mat.HasProperty("_PosTex")) mat.SetTexture("_PosTex", pos);
        if (mat.HasProperty("_RotTex")) mat.SetTexture("_RotTex", rot);
        if (mat.HasProperty("_VatSize")) mat.SetVector("_VatSize", new Vector4(meta.width, meta.height, 0, 0));
        if (mat.HasProperty("_FrameCount")) mat.SetFloat("_FrameCount", meta.frame_count);
        if (mat.HasProperty("_PivotRow")) mat.SetFloat("_PivotRow", meta.pivot_row);
        if (mat.HasProperty("_Fps")) mat.SetFloat("_Fps", meta.fps);
        EditorUtility.SetDirty(mat);

        // 4. prefab: only when there is none yet (an existing one may carry your own components)
        string prefabPath = dir + "/" + name + ".prefab";
        if (AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath) == null)
        {
            GameObject go = new GameObject(name);
            try
            {
                go.AddComponent<MeshFilter>().sharedMesh = filter.sharedMesh;
                go.AddComponent<MeshRenderer>().sharedMaterial = mat;
                AddPlayer(go, jsonPath);
                PrefabUtility.SaveAsPrefabAsset(go, prefabPath);
            }
            finally
            {
                Object.DestroyImmediate(go);
            }
        }
        AssetDatabase.SaveAssets();
        Debug.Log("H-Style RBD Nodes: " + prefabPath + " is ready (" + meta.piece_count + " pieces, " + meta.frame_count + " frames at " + meta.fps + " fps).");
        return prefabPath;
    }

    // HStyleRbdVatPlayer.cs is optional: found by name, so this file still compiles when it was not copied.
    static void AddPlayer(GameObject go, string jsonPath)
    {
        foreach (System.Type type in TypeCache.GetTypesDerivedFrom<MonoBehaviour>())
        {
            if (type.FullName != "HStyleRbdVatPlayer")
                continue;
            SerializedObject player = new SerializedObject(go.AddComponent(type));
            SerializedProperty json = player.FindProperty("json");
            if (json != null)
            {
                json.objectReferenceValue = AssetDatabase.LoadAssetAtPath<TextAsset>(jsonPath);
                player.ApplyModifiedPropertiesWithoutUndo();
            }
            return;
        }
    }

    // Data, not colour: every default import option would damage it.
    static Texture2D DataTexture(string path)
    {
        TextureImporter importer = AssetImporter.GetAtPath(path) as TextureImporter;
        if (importer == null)
            return null;
        importer.textureType = TextureImporterType.Default;
        importer.sRGBTexture = false;
        importer.mipmapEnabled = false;
        importer.filterMode = FilterMode.Point;
        importer.wrapMode = TextureWrapMode.Clamp;
        importer.npotScale = TextureImporterNPOTScale.None;
        importer.textureCompression = TextureImporterCompression.Uncompressed;
        importer.maxTextureSize = 8192;
        importer.SaveAndReimport();
        return AssetDatabase.LoadAssetAtPath<Texture2D>(path);
    }

    [MenuItem("Assets/H-Style RBD Nodes/Fix Bone FBX Import", true)]
    static bool CanFixModel()
    {
        return Selection.activeObject != null && AssetImporter.GetAtPath(AssetDatabase.GetAssetPath(Selection.activeObject)) is ModelImporter;
    }

    [MenuItem("Assets/H-Style RBD Nodes/Fix Bone FBX Import")]
    static void FixSelectedModel()
    {
        FixBoneModel(AssetDatabase.GetAssetPath(Selection.activeObject));
    }

    public static bool FixBoneModel(string modelPath)
    {
        ModelImporter importer = AssetImporter.GetAtPath(modelPath) as ModelImporter;
        if (importer == null)
            return false;
        importer.animationType = ModelImporterAnimationType.Generic;
        importer.animationCompression = ModelImporterAnimationCompression.Off;
        importer.SaveAndReimport();
        Debug.Log("H-Style RBD Nodes: " + modelPath + " now imports its animation without compression.");
        return true;
    }
}
#endif
