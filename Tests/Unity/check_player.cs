// Unity-side check of HStyleRbdVatPlayer.cs. This file has no using directives on purpose: it is appended to
// a copy of Extension/HStyleRbdVatPlayer.cs and the pair is compiled as one script, so that the check does not
// depend on the player being part of the project:
//   cat Extension/HStyleRbdVatPlayer.cs Tests/Unity/check_player.cs > Tests/Out/Unity/check_player_combined.cs
// then call HStyleRbdVatPlayerCheck.Run(<unity_wall.json>, <events_truth.txt>) from the editor.
// events_truth.txt comes from Tests/unity_export.py: the cracks in Blender world axes, straight from the bake.
public static class HStyleRbdVatPlayerCheck
{
    public static string Run(string jsonPath, string truthPath)
    {
        var inv = System.Globalization.CultureInfo.InvariantCulture;
        var lines = System.IO.File.ReadAllLines(truthPath);
        var head = lines[0].Split(' ');
        int count = int.Parse(head[0]);
        float fps = float.Parse(head[1], inv);
        int frames = int.Parse(head[2]);
        var evTime = new float[count];
        var evSize = new float[count];
        var evLocal = new Vector3[count];
        for (int i = 0; i < count; i++)
        {
            var v = System.Array.ConvertAll(lines[1 + i].Split(' '), s => float.Parse(s, inv));
            evTime[i] = v[0] / fps;
            evLocal[i] = new Vector3(-v[1], v[3], -v[2]);      // Blender (x, y, z) -> Unity (-x, z, -y)
            evSize[i] = v[4];
        }
        System.Func<int, int> perCrack = i => Mathf.Clamp(Mathf.RoundToInt(evSize[i] * 12f), 1, 20);

        var go = new GameObject("HStyleRbdPlayerCheck");
        var psGo = new GameObject("HStyleRbdPlayerCheckParticles");
        go.hideFlags = psGo.hideFlags = HideFlags.HideAndDontSave;
        var log = new System.Text.StringBuilder();
        int failed = 0;
        System.Action<string, bool, string> check = (name, ok, detail) =>
        {
            if (!ok) failed++;
            log.Append(ok ? "ok   " : "FAIL ").Append(name).Append("  ").Append(detail).Append('\n');
        };
        try
        {
            go.transform.position = new Vector3(3f, 1f, -2f);
            go.transform.rotation = Quaternion.Euler(0f, 40f, 0f);
            var renderer = go.AddComponent<MeshRenderer>();
            var ps = psGo.AddComponent<ParticleSystem>();
            ps.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
            var main = ps.main;
            main.simulationSpace = ParticleSystemSimulationSpace.World;
            main.maxParticles = 100000;
            main.startLifetime = 1000f;
            main.startSpeed = 0f;
            main.playOnAwake = false;
            var emission = ps.emission;
            emission.enabled = false;
            var shape = ps.shape;
            shape.enabled = false;
            // outside Play mode a particle system that was never simulated drops its first Emit()
            ps.Simulate(0.001f, false, true);

            var player = go.AddComponent<HStyleRbdVatPlayer>();
            check("component_added", player != null, "");
            player.json = new TextAsset(System.IO.File.ReadAllText(jsonPath));
            player.breakParticles = ps;
            player.loop = false;
            player.particlesPerMetre = 12f;
            player.maxParticlesPerCrack = 20;
            var block = new MaterialPropertyBlock();
            var buffer = new ParticleSystem.Particle[100000];
            float duration = (frames - 1) / fps;

            // 1. start
            player.Play();
            renderer.GetPropertyBlock(block);
            check("play_sets_first_frame", player.IsPlaying && block.GetFloat("_Frame") == 0f && block.GetFloat("_AutoPlay") == 0f,
                "frame " + block.GetFloat("_Frame"));
            check("duration_and_event_count", Mathf.Abs(player.Duration - duration) < 1e-5f && player.EventCount == count,
                player.Duration + " s, " + player.EventCount + " cracks");

            // 2. step through at 60 fps: after every step the particles alive are exactly those of the cracks so far
            int steps = 0, wrongCount = 0;
            float worstFrame = 0f;
            while (player.IsPlaying && steps < 10000)
            {
                player.Advance(1f / 60f);
                steps++;
                // a crack whose time falls exactly on a step may land on either side of it
                int atLeast = 0, atMost = 0;
                float t = steps / 60f;
                for (int i = 0; i < count; i++)
                {
                    if (evTime[i] <= t - 1e-4f) atLeast += perCrack(i);
                    if (evTime[i] <= t + 1e-4f) atMost += perCrack(i);
                }
                int alive = ps.GetParticles(buffer);
                if (alive < atLeast || alive > atMost) wrongCount++;
                renderer.GetPropertyBlock(block);
                worstFrame = Mathf.Max(worstFrame, Mathf.Abs(block.GetFloat("_Frame") - Mathf.Min(t, duration) * fps));
            }
            int total = 0;
            for (int i = 0; i < count; i++) total += perCrack(i);
            int aliveEnd = ps.GetParticles(buffer);
            check("emission_follows_the_clock", wrongCount == 0 && aliveEnd == total && total > count,
                wrongCount + " of " + steps + " steps off; " + aliveEnd + " particles for " + count + " cracks (expected " + total + ")");
            check("frame_follows_the_clock", worstFrame < 1e-3f, "worst " + worstFrame + " frames");
            renderer.GetPropertyBlock(block);
            check("stops_on_last_frame", !player.IsPlaying && Mathf.Abs(block.GetFloat("_Frame") - (frames - 1)) < 1e-3f,
                "frame " + block.GetFloat("_Frame"));

            // 3. where: every crack has its particles on its own spot (shape off, so exactly there)
            float worstPlace = 0f;
            int misplaced = 0;
            var got = new int[count];
            for (int p = 0; p < aliveEnd; p++)
            {
                int best = -1;
                float bestD = float.MaxValue;
                for (int i = 0; i < count; i++)
                {
                    float d = (go.transform.TransformPoint(evLocal[i]) - buffer[p].position).sqrMagnitude;
                    if (d < bestD) { bestD = d; best = i; }
                }
                worstPlace = Mathf.Max(worstPlace, Mathf.Sqrt(bestD));
                got[best]++;
            }
            for (int i = 0; i < count; i++)
                if (got[i] != perCrack(i)) misplaced++;
            check("particles_at_the_cracks_world", worstPlace < 2e-3f && misplaced == 0,
                "worst " + worstPlace + " m, " + misplaced + " cracks with a wrong count");

            // 4. Seek does not emit, and playback continues from there
            ps.Simulate(0.001f, false, true);     // clear, and stay initialised (see above)
            player.Seek(0.5f);
            renderer.GetPropertyBlock(block);
            int afterSeek = ps.GetParticles(buffer);
            player.Advance(0.6f);
            int expectedTail = 0;
            for (int i = 0; i < count; i++)
                if (evTime[i] > 0.5f && evTime[i] <= 1.1f) expectedTail += perCrack(i);
            int tail = ps.GetParticles(buffer);
            check("seek_is_silent_then_continues", afterSeek == 0 && tail == expectedTail && expectedTail > 0,
                "after seek " + afterSeek + ", then " + tail + " (expected " + expectedTail + ")");

            // 5. loop: hold the last frame, then start over and emit again
            ps.Simulate(0.001f, false, true);     // clear, and stay initialised (see above)
            player.loop = true;
            player.holdAtEnd = 0.25f;
            player.Play();
            player.Advance(duration + 0.1f);
            renderer.GetPropertyBlock(block);
            float held = block.GetFloat("_Frame");
            int firstRound = ps.GetParticles(buffer);
            // 0.3 s past the end with a 0.25 s hold: the next round is 0.05 s old, and its first cracks are out
            player.Advance(0.2f);
            renderer.GetPropertyBlock(block);
            float wrapped = block.GetFloat("_Frame");
            int early = 0;
            for (int i = 0; i < count; i++)
                if (evTime[i] <= 0.05f) early += perCrack(i);
            int afterWrap = ps.GetParticles(buffer);
            player.Advance(duration);
            int secondRound = ps.GetParticles(buffer);
            check("loop_holds_then_restarts", player.IsPlaying && Mathf.Abs(held - (frames - 1)) < 1e-3f
                && Mathf.Abs(wrapped - 0.05f * fps) < 1e-3f && firstRound == total && afterWrap == total + early && early > 0
                && secondRound == 2 * total,
                "held " + held + ", wrapped to frame " + wrapped + ", particles " + firstRound + " -> " + afterWrap + " -> " + secondRound);
            // one step longer than three whole rounds: lands 0.5 s into a round, having emitted one round and that part
            ps.Simulate(0.001f, false, true);
            player.Play();
            player.Advance(3f * (duration + 0.25f) + 0.5f);
            renderer.GetPropertyBlock(block);
            int half = 0;
            for (int i = 0; i < count; i++)
                if (evTime[i] <= 0.5f) half += perCrack(i);
            check("long_step_keeps_the_remainder", Mathf.Abs(block.GetFloat("_Frame") - 0.5f * fps) < 1e-2f
                && ps.GetParticles(buffer) == total + half, "frame " + block.GetFloat("_Frame") + ", particles " + ps.GetParticles(buffer));

            // 6. a particle system that simulates in local space, sitting somewhere else
            ps.Simulate(0.001f, false, true);     // clear, and stay initialised (see above)
            psGo.transform.position = new Vector3(-5f, 2f, 7f);
            psGo.transform.rotation = Quaternion.Euler(20f, -70f, 10f);
            main.simulationSpace = ParticleSystemSimulationSpace.Local;
            player.loop = false;
            player.Play();
            player.Advance(duration);
            int aliveLocal = ps.GetParticles(buffer);
            float worstLocal = 0f;
            for (int p = 0; p < aliveLocal; p++)
            {
                Vector3 world = psGo.transform.TransformPoint(buffer[p].position);
                float bestD = float.MaxValue;
                for (int i = 0; i < count; i++)
                    bestD = Mathf.Min(bestD, (go.transform.TransformPoint(evLocal[i]) - world).sqrMagnitude);
                worstLocal = Mathf.Max(worstLocal, Mathf.Sqrt(bestD));
            }
            check("particles_at_the_cracks_local", aliveLocal == total && worstLocal < 2e-3f, aliveLocal + " particles, worst " + worstLocal + " m");

            // 6b. a custom simulation space: positions are relative to that transform, not to the particle system
            var spaceGo = new GameObject("HStyleRbdPlayerCheckSpace");
            spaceGo.hideFlags = HideFlags.HideAndDontSave;
            try
            {
                spaceGo.transform.position = new Vector3(8f, -3f, 1f);
                spaceGo.transform.rotation = Quaternion.Euler(-35f, 15f, 60f);
                main.simulationSpace = ParticleSystemSimulationSpace.Custom;
                main.customSimulationSpace = spaceGo.transform;
                ps.Simulate(0.001f, false, true);
                player.Play();
                player.Advance(duration);
                int aliveCustom = ps.GetParticles(buffer);
                float worstCustom = 0f;
                for (int p = 0; p < aliveCustom; p++)
                {
                    Vector3 world = spaceGo.transform.TransformPoint(buffer[p].position);
                    float bestD = float.MaxValue;
                    for (int i = 0; i < count; i++)
                        bestD = Mathf.Min(bestD, (go.transform.TransformPoint(evLocal[i]) - world).sqrMagnitude);
                    worstCustom = Mathf.Max(worstCustom, Mathf.Sqrt(bestD));
                }
                check("particles_at_the_cracks_custom_space", aliveCustom == total && worstCustom < 2e-3f,
                    aliveCustom + " particles, worst " + worstCustom + " m");
            }
            finally
            {
                main.simulationSpace = ParticleSystemSimulationSpace.Local;
                Object.DestroyImmediate(spaceGo);
            }

            // 7. no particle system, a size filter, and giving the material back
            ps.Simulate(0.001f, false, true);     // clear, and stay initialised (see above)
            player.minCrackSize = 1000f;
            player.Play();
            player.Advance(duration);
            int filtered = ps.GetParticles(buffer);
            player.breakParticles = null;
            player.minCrackSize = 0f;
            player.Play();
            player.Advance(duration);
            check("filter_and_no_particles", filtered == 0 && ps.GetParticles(buffer) == 0, "filtered " + filtered);
            typeof(HStyleRbdVatPlayer).GetMethod("OnDisable", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)
                .Invoke(player, null);
            // a property block cannot give up single values, so the player sets its two back to the material's
            // (no material on this test renderer: the defaults, Auto Play on and frame 0)
            renderer.GetPropertyBlock(block);
            check("disable_hands_the_clock_back", !player.IsPlaying && block.GetFloat("_AutoPlay") == 1f && block.GetFloat("_Frame") == 0f,
                "auto play " + block.GetFloat("_AutoPlay") + ", frame " + block.GetFloat("_Frame"));
            renderer.SetPropertyBlock(null);

            // 8. overrides of another script on the same renderer survive the player
            var theirs = new MaterialPropertyBlock();
            theirs.SetColor("_BaseColor", Color.red);
            theirs.SetFloat("_Dissolve", 0.25f);
            renderer.SetPropertyBlock(theirs);
            player.Play();
            player.Advance(0.5f);
            renderer.GetPropertyBlock(block);
            bool during = block.GetColor("_BaseColor") == Color.red && block.GetFloat("_AutoPlay") == 0f
                && Mathf.Abs(block.GetFloat("_Frame") - 0.5f * fps) < 1e-3f;
            typeof(HStyleRbdVatPlayer).GetMethod("OnDisable", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)
                .Invoke(player, null);
            renderer.GetPropertyBlock(block);
            check("other_overrides_survive", during && renderer.HasPropertyBlock() && block.GetColor("_BaseColor") == Color.red
                && block.GetFloat("_Dissolve") == 0.25f && block.GetFloat("_AutoPlay") == 1f && block.GetFloat("_Frame") == 0f,
                "during " + during + ", after: colour " + block.GetColor("_BaseColor") + ", auto play " + block.GetFloat("_AutoPlay"));

            // 9. ... also overrides that another script adds while the player is already running
            renderer.SetPropertyBlock(null);
            player.Play();
            player.Advance(0.25f);
            renderer.GetPropertyBlock(block);
            block.SetColor("_BaseColor", Color.green);
            renderer.SetPropertyBlock(block);
            player.Advance(0.25f);
            typeof(HStyleRbdVatPlayer).GetMethod("OnDisable", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)
                .Invoke(player, null);
            renderer.GetPropertyBlock(block);
            check("overrides_added_later_survive", block.GetColor("_BaseColor") == Color.green && block.GetFloat("_AutoPlay") == 1f,
                "colour " + block.GetColor("_BaseColor") + ", auto play " + block.GetFloat("_AutoPlay"));
        }
        catch (System.Exception e)
        {
            failed++;
            log.Append("EXCEPTION ").Append(e).Append('\n');
        }
        finally
        {
            Object.DestroyImmediate(go);
            Object.DestroyImmediate(psGo);
        }
        return (failed == 0 ? "ALL OK\n" : failed + " FAILED\n") + log;
    }
}
