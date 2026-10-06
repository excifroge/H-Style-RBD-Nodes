// Check of an H-Style RBD Nodes export dropped into an empty Unity project (see Tests/Unity/Fresh/run_fresh.sh).
// Stage 1 (here, edit mode): the exported scripts compile as part of the project, "Set Up VAT From Json"
// builds material + prefab, the prefab carries an HStyleRbdVatPlayer. Stage 2: a scene is saved and Play
// mode is entered; HStyleRbdPlayProbe finishes the check and quits the editor.
using System.IO;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Experimental.Rendering;

public static class HStyleRbdFreshCheck
{
    const string Dir = "Assets/RbdExport";

    [System.Serializable]
    class Meta
    {
        public int width = 0, height = 0, piece_count = 0, frame_count = 0, pivot_row = 0, event_count = 0;
        public float fps = 0f;
    }

    public static void Run()
    {
        string outDir = Path.GetFullPath(Path.Combine(Application.dataPath, ".."));
        string resultPath = Path.Combine(outDir, "fresh_result.txt");
        StringBuilder log = new StringBuilder();
        int failed = 0;
        System.Action<string, bool, string> check = (name, ok, detail) =>
        {
            if (!ok) failed++;
            log.Append(ok ? "ok   " : "FAIL ").Append(name).Append("  ").Append(detail).Append('\n');
        };
        try
        {
            AssetDatabase.Refresh();
            log.Append("Unity ").Append(Application.unityVersion).Append(", colour space ").Append(PlayerSettings.colorSpace).Append('\n');
            Meta meta = JsonUtility.FromJson<Meta>(File.ReadAllText(Dir + "/unity_wall.json"));

            string prefabPath = HStyleRbdVatSetup.SetUp(Dir + "/unity_wall.json");
            check("setup_returns_prefab", prefabPath == Dir + "/unity_wall.prefab", "" + prefabPath);
            GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
            HStyleRbdVatPlayer player = prefab != null ? prefab.GetComponent<HStyleRbdVatPlayer>() : null;
            check("prefab_has_player_with_json", player != null && player.json != null && player.json.name == "unity_wall",
                player == null ? "no player" : "json " + (player.json != null ? player.json.name : "null"));
            check("player_reads_the_export", player != null && player.EventCount == meta.event_count && meta.event_count > 0
                && Mathf.Abs(player.Duration - (meta.frame_count - 1) / meta.fps) < 1e-5f,
                player == null ? "" : player.EventCount + " cracks, " + player.Duration + " s");

            Material mat = prefab.GetComponent<MeshRenderer>().sharedMaterial;
            Shader shader = mat.shader;
            for (int pass = 0; pass < mat.passCount; pass++)
                ShaderUtil.CompilePass(mat, pass, true);
            int shaderErrors = 0;
            foreach (ShaderMessage m in ShaderUtil.GetShaderMessages(shader))
                if (m.severity == UnityEditor.Rendering.ShaderCompilerMessageSeverity.Error)
                {
                    shaderErrors++;
                    log.Append("     shader error: ").Append(m.message).Append('\n');
                }
            check("shader_compiles", shader.name == "H-Style RBD Nodes/VAT Simple (URP)" && !ShaderUtil.ShaderHasError(shader) && shaderErrors == 0
                && mat.passCount == 3, shader.name + ", " + mat.passCount + " passes, " + shaderErrors + " errors");
            check("material_numbers", mat.GetVector("_VatSize") == new Vector4(meta.width, meta.height, 0, 0)
                && mat.GetFloat("_FrameCount") == meta.frame_count && mat.GetFloat("_PivotRow") == meta.pivot_row
                && mat.GetFloat("_Fps") == meta.fps, mat.GetVector("_VatSize") + " frames " + mat.GetFloat("_FrameCount"));
            bool texturesOk = true;
            string texDetail = "";
            foreach (string prop in new[] { "_PosTex", "_RotTex" })
            {
                Texture2D t = mat.GetTexture(prop) as Texture2D;
                bool ok = t != null && t.width == meta.width && t.height == meta.height && t.format == TextureFormat.RGBAHalf
                    && t.filterMode == FilterMode.Point && t.wrapMode == TextureWrapMode.Clamp && t.mipmapCount == 1
                    && !GraphicsFormatUtility.IsSRGBFormat(t.graphicsFormat);
                texturesOk &= ok;
                texDetail += prop + (t == null ? " missing; " : " " + t.width + "x" + t.height + " " + t.format + " mips " + t.mipmapCount + "; ");
            }
            check("textures_are_data", texturesOk, texDetail);
            Mesh mesh = prefab.GetComponent<MeshFilter>().sharedMesh;
            check("mesh_has_lookup_uv_and_colour", mesh != null && mesh.uv2 != null && mesh.uv2.Length == mesh.vertexCount
                && mesh.colors.Length == mesh.vertexCount, mesh == null ? "no mesh" : mesh.vertexCount + " vertices");

            // a second export in the same folder shares the one HStyleRbdUnity folder
            string second = HStyleRbdVatSetup.SetUp(Dir + "/unity_vat.json");
            GameObject secondPrefab = second != null ? AssetDatabase.LoadAssetAtPath<GameObject>(second) : null;
            check("second_export_same_folder", secondPrefab != null && secondPrefab.GetComponent<HStyleRbdVatPlayer>() != null, "" + second);
            // running it again changes nothing that the user may have edited
            player.speed = 0.5f;
            EditorUtility.SetDirty(prefab);
            AssetDatabase.SaveAssets();
            string again = HStyleRbdVatSetup.SetUp(Dir + "/unity_wall.json");
            check("repeat_keeps_the_prefab", again == prefabPath
                && AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath).GetComponent<HStyleRbdVatPlayer>().speed == 0.5f, "" + again);
            player.speed = 1f;
            EditorUtility.SetDirty(prefab);
            AssetDatabase.SaveAssets();

            bool bones = HStyleRbdVatSetup.FixBoneModel(Dir + "/unity_bones.fbx");
            ModelImporter importer = AssetImporter.GetAtPath(Dir + "/unity_bones.fbx") as ModelImporter;
            AnimationClip clip = null;
            foreach (Object o in AssetDatabase.LoadAllAssetsAtPath(Dir + "/unity_bones.fbx"))
                if (o is AnimationClip && !o.name.StartsWith("__preview__"))
                    clip = (AnimationClip)o;
            check("bone_fbx", bones && importer.animationCompression == ModelImporterAnimationCompression.Off && clip != null
                && Mathf.Abs(clip.length - 47f / 24f) < 1e-3f, clip == null ? "no clip" : "clip " + clip.length + " s");

            // stage 2: a scene that plays the prefab once, with a particle system for the cracks
            UnityEngine.SceneManagement.Scene scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
            GameObject instance = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
            instance.transform.position = new Vector3(3f, 1f, -2f);
            instance.transform.rotation = Quaternion.Euler(0f, 40f, 0f);
            HStyleRbdVatPlayer scenePlayer = instance.GetComponent<HStyleRbdVatPlayer>();
            scenePlayer.loop = false;
            GameObject dust = new GameObject("Dust");
            ParticleSystem ps = dust.AddComponent<ParticleSystem>();
            ParticleSystem.MainModule main = ps.main;
            main.playOnAwake = false;
            main.simulationSpace = ParticleSystemSimulationSpace.World;
            main.maxParticles = 100000;
            main.startLifetime = 1000f;
            main.startSpeed = 0f;
            ParticleSystem.EmissionModule emission = ps.emission;
            emission.enabled = false;
            ParticleSystem.ShapeModule shape = ps.shape;
            shape.enabled = false;
            scenePlayer.breakParticles = ps;
            HStyleRbdPlayProbe probe = new GameObject("Probe").AddComponent<HStyleRbdPlayProbe>();
            probe.player = scenePlayer;
            probe.particles = ps;
            probe.truthPath = Path.Combine(outDir, "events_truth.txt");
            probe.resultPath = resultPath;
            EditorSceneManager.SaveScene(scene, "Assets/Check.unity");
        }
        catch (System.Exception e)
        {
            failed++;
            log.Append("EXCEPTION ").Append(e).Append('\n');
        }
        File.WriteAllText(resultPath, "STAGE 1 (edit mode): " + (failed == 0 ? "ALL OK" : failed + " FAILED") + "\n" + log);
        if (failed > 0)
        {
            EditorApplication.Exit(1);
            return;
        }
        EditorSettings.enterPlayModeOptionsEnabled = true;
        EditorSettings.enterPlayModeOptions = EnterPlayModeOptions.DisableDomainReload;
        EditorApplication.EnterPlaymode();
    }
}
