// Stage 2 of the fresh-project check (see HStyleRbdFreshCheck.cs): runs in Play mode.
// The player must start by itself, follow game time, stop on the last frame, and every crack must have
// emitted its particles at its own place. events_truth.txt lists the cracks in Blender world axes.
using UnityEngine;

public class HStyleRbdPlayProbe : MonoBehaviour
{
    public HStyleRbdVatPlayer player;
    public ParticleSystem particles;
    public string truthPath, resultPath;

    readonly System.Text.StringBuilder log = new System.Text.StringBuilder();
    int failed, count, frames, total, updates;
    float fps, startTime, largestStep;
    float[] evSize;
    Vector3[] evLocal;
    bool done;

    void Check(string name, bool ok, string detail)
    {
        if (!ok) failed++;
        log.Append(ok ? "ok   " : "FAIL ").Append(name).Append("  ").Append(detail).Append('\n');
    }

    int PerCrack(int i)
    {
        return Mathf.Clamp(Mathf.RoundToInt(evSize[i] * player.particlesPerMetre), 1, player.maxParticlesPerCrack);
    }

    void Start()
    {
        var inv = System.Globalization.CultureInfo.InvariantCulture;
        string[] lines = System.IO.File.ReadAllLines(truthPath);
        string[] head = lines[0].Split(' ');
        count = int.Parse(head[0]);
        fps = float.Parse(head[1], inv);
        frames = int.Parse(head[2]);
        evSize = new float[count];
        evLocal = new Vector3[count];
        for (int i = 0; i < count; i++)
        {
            float[] v = System.Array.ConvertAll(lines[1 + i].Split(' '), s => float.Parse(s, inv));
            evLocal[i] = new Vector3(-v[1], v[3], -v[2]);      // Blender (x, y, z) -> Unity (-x, z, -y)
            evSize[i] = v[4];
            total += PerCrack(i);
        }
        Renderer r = player.GetComponent<Renderer>();
        MaterialPropertyBlock block = new MaterialPropertyBlock();
        r.GetPropertyBlock(block);
        Check("starts_by_itself", player.IsPlaying && r.HasPropertyBlock() && block.GetFloat("_AutoPlay") == 0f,
            "playing " + player.IsPlaying + ", frame " + block.GetFloat("_Frame"));
        Check("particle_system_is_idle", !particles.isPlaying && !particles.emission.enabled, "isPlaying " + particles.isPlaying);
        startTime = Time.time;
    }

    void Update()
    {
        if (done)
            return;
        updates++;
        largestStep = Mathf.Max(largestStep, Time.deltaTime);
        if (player.IsPlaying && Time.realtimeSinceStartup < 120f)
            return;
        done = true;
        float duration = (frames - 1) / fps;
        float took = Time.time - startTime;
        // Unity's first frame has Time.time = 0 but a non-zero Time.deltaTime, so the clip may end one step "early"
        Check("finished_in_time", !player.IsPlaying && took >= duration - largestStep - 1e-3f && took <= duration + 2f * largestStep + 1e-3f,
            "took " + took + " s for a " + duration + " s clip (" + updates + " updates, largest step " + largestStep + " s)");
        Renderer r = player.GetComponent<Renderer>();
        MaterialPropertyBlock block = new MaterialPropertyBlock();
        r.GetPropertyBlock(block);
        Check("stops_on_last_frame", Mathf.Abs(block.GetFloat("_Frame") - (frames - 1)) < 1e-3f, "frame " + block.GetFloat("_Frame"));

        ParticleSystem.Particle[] buffer = new ParticleSystem.Particle[100000];
        int alive = particles.GetParticles(buffer);
        Check("every_crack_emitted", alive == total && total > count, alive + " particles for " + count + " cracks (expected " + total + ")");
        float worst = 0f;
        int misplaced = 0;
        int[] got = new int[count];
        for (int p = 0; p < alive; p++)
        {
            int best = -1;
            float bestD = float.MaxValue;
            for (int i = 0; i < count; i++)
            {
                float d = (player.transform.TransformPoint(evLocal[i]) - buffer[p].position).sqrMagnitude;
                if (d < bestD) { bestD = d; best = i; }
            }
            worst = Mathf.Max(worst, Mathf.Sqrt(bestD));
            got[best]++;
        }
        for (int i = 0; i < count; i++)
            if (got[i] != PerCrack(i)) misplaced++;
        Check("particles_at_the_cracks", worst < 2e-3f && misplaced == 0, "worst " + worst + " m, " + misplaced + " cracks with a wrong count");

        // Play() again from code restarts the clip
        player.Play();
        r.GetPropertyBlock(block);
        Check("play_again_restarts", player.IsPlaying && block.GetFloat("_Frame") == 0f, "frame " + block.GetFloat("_Frame"));

        System.IO.File.AppendAllText(resultPath, "STAGE 2 (play mode): " + (failed == 0 ? "ALL OK" : failed + " FAILED") + "\n" + log);
#if UNITY_EDITOR
        UnityEditor.EditorApplication.Exit(failed == 0 ? 0 : 1);
#endif
    }
}
