// SPDX-License-Identifier: CC0-1.0  (public domain: copy it into any project, including commercial games)
// H-Style RBD Nodes: plays a VAT export once (or in a loop) and can emit particles where the pieces break apart.
//
// Put it on the object that has the VAT material ("Set Up VAT From Json" does this for a new prefab) and
// assign the exported <name>.json. Without this component the material simply loops by itself (Auto Play).
// With it, the clip starts when the object is enabled or when you call Play(), which is what a one-shot
// destruction effect needs.
//
// Break Particles (optional): any Particle System. Turn its Emission rate and Play On Awake off; this
// script only calls Emit() on it, once for every crack that opens, at the place where it opens. Give it
// a small Shape (a sphere of a few centimetres) so the particles of one crack do not start on one point.
//
// The frame is set through a MaterialPropertyBlock on the Renderer of this same object, so objects sharing
// one material play independently (and that renderer is not batched by the SRP Batcher). Overrides that
// other scripts put on the same renderer are kept, also when this component is disabled: it then only sets
// its own two values back to those of the material. A block set per material index would win over this
// one: do not mix them.
// Keep ONE copy of this script per project: a second copy is a duplicate class and stops compilation.
using UnityEngine;

[DisallowMultipleComponent]
public class HStyleRbdVatPlayer : MonoBehaviour
{
    [Tooltip("The <name>.json that was exported next to the VAT textures.")]
    public TextAsset json;
    public bool playOnEnable = true;
    public bool loop = true;
    [Tooltip("Seconds the last frame is held before a loop starts over.")]
    public float holdAtEnd = 1f;
    [Tooltip("Playback speed: 1 = as simulated, 0.5 = half speed, 0 = paused.")]
    [Min(0f)]
    public float speed = 1f;

    [Header("Particles where pieces break apart (optional)")]
    public ParticleSystem breakParticles;
    [Tooltip("Particles per metre of crack: bigger cracks emit more.")]
    public float particlesPerMetre = 12f;
    public int maxParticlesPerCrack = 20;
    [Tooltip("Cracks smaller than this (metres) emit nothing.")]
    public float minCrackSize = 0f;

    // only the flat fields of the .json that this script needs
    [System.Serializable]
    class Meta
    {
        public string schema = "";
        public int frame_count = 1;
        public float fps = 24f;
        public float[] event_times = new float[0];
        public float[] event_positions = new float[0];
        public float[] event_sizes = new float[0];
    }

    static readonly int FrameId = Shader.PropertyToID("_Frame");
    static readonly int AutoPlayId = Shader.PropertyToID("_AutoPlay");

    Meta meta;
    TextAsset loadedFrom;
    Renderer target;
    MaterialPropertyBlock block;
    float time;
    int nextEvent;
    int eventCount;
    bool playing;
    bool showing;         // our values are on the renderer

    public bool IsPlaying { get { return playing; } }
    /// <summary>Seconds since the clip started.</summary>
    public float CurrentTime { get { return time; } }
    /// <summary>Length of the clip in seconds.</summary>
    public float Duration { get { return Load() ? Mathf.Max(meta.frame_count - 1, 0) / Mathf.Max(meta.fps, 0.001f) : 0f; } }
    /// <summary>Number of cracks in the export.</summary>
    public int EventCount { get { return Load() ? eventCount : 0; } }

    void OnEnable()
    {
        if (!Load())
            return;
        if (playOnEnable)
            Play();
        else
            Seek(0f);
    }

    void OnDisable()
    {
        playing = false;
        if (target == null || !showing)
            return;
        showing = false;
        // A property block cannot give up single values, and it cannot be asked what else is in it. So it
        // is never cleared (that would take other scripts' overrides with it): our two values go back to
        // what the material says.
        Material material = target.sharedMaterial;
        target.GetPropertyBlock(block);
        block.SetFloat(AutoPlayId, material != null && material.HasProperty(AutoPlayId) ? material.GetFloat(AutoPlayId) : 1f);
        block.SetFloat(FrameId, material != null && material.HasProperty(FrameId) ? material.GetFloat(FrameId) : 0f);
        target.SetPropertyBlock(block);
    }

    void Update()
    {
        if (playing && speed > 0f)
            Advance(Time.deltaTime * speed);
    }

    /// <summary>Start the clip from its first frame.</summary>
    public void Play()
    {
        if (!Load())
            return;
        time = 0f;
        nextEvent = 0;
        playing = true;
        Show(0f);
    }

    public void Stop()
    {
        playing = false;
    }

    /// <summary>Jump to a time in seconds without emitting particles for the cracks that were skipped.</summary>
    public void Seek(float seconds)
    {
        if (!Load())
            return;
        time = Mathf.Clamp(seconds, 0f, Duration);
        nextEvent = 0;
        while (nextEvent < eventCount && meta.event_times[nextEvent] <= time)
            nextEvent++;
        Show(time);
    }

    /// <summary>Move the clip forward by dt seconds. Update() calls this; call it yourself (with Stop()) to drive
    /// the clip from a Timeline or your own code.</summary>
    public void Advance(float dt)
    {
        if (!Load() || dt <= 0f)
            return;
        float duration = Duration;
        time += dt;
        Emit(time);
        if (loop)
        {
            float period = duration + Mathf.Max(holdAtEnd, 0f);
            if (time >= period)
            {
                // the next round starts where this step ends (a very long step skips whole rounds)
                time = period > 0f ? Mathf.Repeat(time, period) : 0f;
                nextEvent = 0;
                Emit(time);
            }
        }
        else if (time >= duration)
        {
            time = duration;
            playing = false;
        }
        Show(Mathf.Min(time, duration));
    }

    bool Load()
    {
        if (meta != null && loadedFrom == json && target != null)
            return true;
        meta = null;
        target = GetComponent<Renderer>();
        if (json == null || target == null)
            return false;
        Meta parsed = JsonUtility.FromJson<Meta>(json.text);
        if (parsed == null || parsed.schema != "hrbd_vat_1")
        {
            Debug.LogError("H-Style RBD Nodes: " + json.name + " is not an hrbd_vat_1 export.", this);
            return false;
        }
        meta = parsed;
        loadedFrom = json;
        eventCount = Mathf.Min(meta.event_times.Length, meta.event_sizes.Length, meta.event_positions.Length / 3);
        if (block == null)
            block = new MaterialPropertyBlock();
        return true;
    }

    void Show(float seconds)
    {
        showing = true;
        target.GetPropertyBlock(block);
        block.SetFloat(AutoPlayId, 0f);
        block.SetFloat(FrameId, seconds * meta.fps);
        target.SetPropertyBlock(block);
    }

    void Emit(float until)
    {
        // the space the particle system simulates in: null = world
        Transform space = null;
        if (breakParticles != null)
        {
            ParticleSystem.MainModule main = breakParticles.main;
            if (main.simulationSpace == ParticleSystemSimulationSpace.Local)
                space = breakParticles.transform;
            else if (main.simulationSpace == ParticleSystemSimulationSpace.Custom)
                space = main.customSimulationSpace;
        }
        while (nextEvent < eventCount && meta.event_times[nextEvent] <= until)
        {
            int i = nextEvent++;
            float size = meta.event_sizes[i];
            if (breakParticles == null || size < minCrackSize)
                continue;
            int count = Mathf.Clamp(Mathf.RoundToInt(size * particlesPerMetre), 1, Mathf.Max(maxParticlesPerCrack, 1));
            Vector3 p = transform.TransformPoint(new Vector3(
                meta.event_positions[3 * i], meta.event_positions[3 * i + 1], meta.event_positions[3 * i + 2]));
            ParticleSystem.EmitParams emit = new ParticleSystem.EmitParams();
            emit.position = space != null ? space.InverseTransformPoint(p) : p;
            emit.applyShapeToPosition = true;
            breakParticles.Emit(emit, count);
        }
    }
}
